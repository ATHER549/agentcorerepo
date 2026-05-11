"""Per-model RPM + TPM limiter, Redis-backed via ``redis.asyncio``.

Algorithm: moving (sliding) window counter implemented with a Redis sorted set
per window. Each model gets two independent windows in Redis:

    ratelimit:rpm:{model_id}
    ratelimit:tpm:{model_id}

Multi-replica deployments share one authoritative bucket per model because
every operation runs as a Lua script -- atomic from Redis's point of view --
so two pods can't both let a request through at the boundary.

Each entry stored in the sorted set is ``"<cost>:<nonce>"`` with score equal
to the unix timestamp it was inserted at. A read-style operation prunes
entries older than ``now - window`` then sums the cost prefixes of the
survivors. A write (``hit``) does the prune, then ZADDs a new entry.

RPM is enforced with one atomic test-and-increment (``CHECK_AND_HIT``,
cost=1). TPM is two-phase because the actual token cost isn't known until the
provider responds:

  1. Pre-flight ``check_tpm`` -- read current consumption (``READ`` script);
     if zero remaining, reject upfront. Does NOT increment.
  2. Post-flight ``debit_tpm`` -- after the call, ``HIT`` the window with
     ``cost=actual_tokens``. Best-effort; Redis errors are swallowed so a
     transient blip never fails an otherwise-successful inference.

Documented tradeoff: a single large request can push consumption past the TPM
ceiling once per window because the pre-flight check sees the prior state,
not the cost of the in-flight call. Subsequent requests will then be
correctly blocked until the window slides.

NOTE: this module is vendored verbatim into both model-service and
guardrails-service so they share one Redis-backed bucket per model. Keep the
two copies in sync -- diverging key formats or Lua scripts would break the
shared-bucket guarantee.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING
from uuid import UUID

import redis.asyncio as redis
from redis.exceptions import RedisError

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

logger = logging.getLogger(__name__)


# Window size in seconds. Both RPM and TPM are "per minute" rates, so this is
# the same for both. Hard-coded -- the public APIs encode this in their names.
_WINDOW_SECONDS = 60


# ---------------------------------------------------------------------------
# Lua scripts (run atomically server-side)
# ---------------------------------------------------------------------------

# CHECK_AND_HIT: prune expired entries, sum current cost, reject if (sum+cost)
# would exceed limit, otherwise add the entry. Used for RPM.
_CHECK_AND_HIT_LUA = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])
local cost = tonumber(ARGV[4])
local member = ARGV[5]

redis.call('ZREMRANGEBYSCORE', key, '-inf', '(' .. (now - window))

local entries = redis.call('ZRANGE', key, 0, -1)
local total = 0
for i = 1, #entries do
    local sep = string.find(entries[i], ':', 1, true)
    if sep then
        total = total + (tonumber(string.sub(entries[i], 1, sep - 1)) or 0)
    end
end

local oldest = now
local first = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
if #first >= 2 then
    oldest = tonumber(first[2])
end

if total + cost > limit then
    return {0, total, oldest}
end

redis.call('ZADD', key, now, member)
redis.call('EXPIRE', key, window + 1)
return {1, total + cost, oldest}
"""

# READ: prune expired entries, sum current cost. No mutation. Used for TPM
# pre-flight check (we don't know the cost yet).
_READ_LUA = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])

redis.call('ZREMRANGEBYSCORE', key, '-inf', '(' .. (now - window))

local entries = redis.call('ZRANGE', key, 0, -1)
local total = 0
for i = 1, #entries do
    local sep = string.find(entries[i], ':', 1, true)
    if sep then
        total = total + (tonumber(string.sub(entries[i], 1, sep - 1)) or 0)
    end
end

local oldest = now
local first = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
if #first >= 2 then
    oldest = tonumber(first[2])
end

return {total, oldest}
"""

# HIT: prune expired entries and add a new one with the given cost. No check.
# Used for TPM post-flight debit (the dependency already verified room).
_HIT_LUA = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local cost = tonumber(ARGV[3])
local member = ARGV[4]

redis.call('ZREMRANGEBYSCORE', key, '-inf', '(' .. (now - window))
redis.call('ZADD', key, now, member)
redis.call('EXPIRE', key, window + 1)
"""


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


class LimitType(str, Enum):
    """Which dimension is being measured / was breached."""

    RPM = "rpm"
    TPM = "tpm"


@dataclass(slots=True)
class RateLimitResult:
    """Snapshot of one window after a check.

    ``allowed`` reflects the verdict for this single check. ``remaining`` is
    the capacity left after the check (0 when ``allowed`` is False).
    ``reset_at`` is a unix timestamp (seconds) at which the oldest in-window
    entry will fall off, freeing capacity. For moving-window strategies this
    is approximate -- a correct upper bound for the Retry-After header.
    """

    limit_type: LimitType
    limit: int
    remaining: int
    reset_at: int
    allowed: bool

    @property
    def retry_after_seconds(self) -> int:
        """Seconds until the window has space again. Always >= 1 when denied."""
        if self.allowed:
            return 0
        delta = self.reset_at - int(time.time())
        return max(delta, 1)


class RateLimitExceeded(Exception):
    """Raised by :meth:`RateLimiter.check_rpm` / :meth:`check_tpm` on denial.

    Carries the breached limit type, the configured ceiling, and a Retry-After
    hint so the caller can build the 429 response without re-querying Redis.
    """

    def __init__(self, limit_type: LimitType, limit: int, retry_after_seconds: int) -> None:
        self.limit_type = limit_type
        self.limit = limit
        self.retry_after_seconds = retry_after_seconds
        super().__init__(
            f"Rate limit exceeded: {limit_type.value}={limit} (retry after {retry_after_seconds}s)"
        )


class UpstreamModelRateLimitError(Exception):
    """Raised when the LLM call inside a guardrail rail returns HTTP 429.

    Distinct from :class:`RateLimitExceeded`, which is the guardrails-service's
    own pre-flight bucket breach. This one represents the provider (or the
    upstream model-service) rejecting the call mid-rail. The router converts
    it to an HTTP 429 with a payload that identifies which model is throttled
    so the caller can render a specific message.
    """

    def __init__(
        self,
        *,
        provider: str | None,
        model: str | None,
        retry_after_seconds: int,
        original_message: str,
    ) -> None:
        self.provider = provider
        self.model = model
        self.retry_after_seconds = retry_after_seconds
        self.original_message = original_message
        super().__init__(
            f"Upstream model rate-limited: provider={provider}, model={model}, "
            f"retry_after={retry_after_seconds}s"
        )


@dataclass(slots=True)
class RateLimitContext:
    """Handle returned from the pre-flight check, used to debit TPM post-call.

    The route handler runs the dependency once at the start of the request,
    receives this context, then -- after the provider call returns -- calls
    :meth:`debit_tpm` with the actual token count. ``rpm_result`` and
    ``tpm_result`` carry the snapshot for the response headers.

    When ``tpm_limit`` is None (unlimited) :meth:`debit_tpm` is a no-op so
    call sites can invoke it unconditionally without branching.
    """

    model_id: UUID | None
    rpm_limit: int | None
    tpm_limit: int | None
    rpm_result: RateLimitResult | None
    tpm_result: RateLimitResult | None
    _limiter: RateLimiter | None = None

    async def debit_tpm(self, tokens: int) -> None:
        if self._limiter is None or self.model_id is None or not self.tpm_limit or tokens <= 0:
            return
        await self._limiter.debit_tpm(self.model_id, self.tpm_limit, tokens)


# ---------------------------------------------------------------------------
# Limiter
# ---------------------------------------------------------------------------


def _rpm_key(model_id: UUID) -> str:
    return f"ratelimit:rpm:{model_id}"


def _tpm_key(model_id: UUID) -> str:
    return f"ratelimit:tpm:{model_id}"


class RateLimiter:
    """Redis-backed RPM + TPM enforcer for per-model quotas.

    Construct once at app startup with :meth:`from_url`, attach to
    ``app.state``, and call from a FastAPI dependency. Lua scripts make every
    operation atomic across replicas.

    Failure handling is policy-driven via ``fail_mode``:

    * ``"open"`` (default) -- if Redis is unreachable, log a warning and
      treat the call as allowed. The service stays up during a Redis outage
      at the cost of un-enforced limits.
    * ``"closed"`` -- if Redis is unreachable, raise so the FastAPI
      dependency can convert it to a 503. Pick this if compliance forbids
      un-rate-limited traffic.
    """

    def __init__(self, client: redis.Redis, *, fail_mode: str = "open") -> None:
        self._client = client
        self._fail_mode = fail_mode
        self._check_and_hit = client.register_script(_CHECK_AND_HIT_LUA)
        self._read = client.register_script(_READ_LUA)
        self._hit = client.register_script(_HIT_LUA)

    @classmethod
    async def create(cls, client: redis.Redis, *, fail_mode: str = "open") -> RateLimiter:
        """Build a limiter from a pre-configured client and verify connectivity.

        Caller owns the client (typically built from
        ``app.services.redis_client.build_redis_client``) so we don't fight the
        backend on connection conventions like SSL, Entra credentials, or
        cluster mode. Raises ``ConnectionError`` if Redis is unreachable AND
        ``fail_mode`` is ``"closed"``. Otherwise logs a warning and returns a
        limiter whose operations degrade to allow-all.
        """
        instance = cls(client, fail_mode=fail_mode)
        try:
            await client.ping()
        except (RedisError, OSError) as exc:
            if fail_mode == "closed":
                msg = f"Redis unreachable and fail_mode=closed: {exc}"
                raise ConnectionError(msg) from exc
            logger.warning(
                "Redis unreachable; rate limiting will fail-open until it recovers (%s)",
                exc,
            )
        return instance

    async def ping(self) -> bool:
        """Health-check probe for /health endpoints."""
        try:
            return bool(await self._client.ping())
        except (RedisError, OSError):
            return False

    async def aclose(self) -> None:
        """Release the underlying Redis connection pool. Call from shutdown."""
        try:
            await self._client.aclose()
        except (RedisError, OSError):
            pass

    # -- RPM ---------------------------------------------------------------

    async def check_rpm(self, model_id: UUID, rpm: int) -> RateLimitResult:
        """Atomic test-and-increment for the RPM window.

        On allow: increments by 1 and returns the snapshot. On deny: leaves
        the window untouched and returns a result with ``allowed=False``.
        """

        async def _op() -> RateLimitResult:
            now = time.time()
            member = f"1:{uuid.uuid4().hex}"
            result = await self._check_and_hit(
                keys=[_rpm_key(model_id)],
                args=[now, _WINDOW_SECONDS, rpm, 1, member],
            )
            allowed, total, oldest = int(result[0]), int(result[1]), float(result[2])
            return RateLimitResult(
                limit_type=LimitType.RPM,
                limit=rpm,
                remaining=max(rpm - total, 0),
                reset_at=int(oldest + _WINDOW_SECONDS),
                allowed=bool(allowed),
            )

        return await self._with_fallback(LimitType.RPM, rpm, _op)

    # -- TPM ---------------------------------------------------------------

    async def check_tpm(self, model_id: UUID, tpm: int) -> RateLimitResult:
        """Read-only TPM check. Does NOT increment.

        Returns a snapshot of the current window. ``allowed`` is True when
        ``remaining > 0`` (any room left). The actual debit happens later via
        :meth:`debit_tpm` once we know how many tokens the provider charged.
        """

        async def _op() -> RateLimitResult:
            now = time.time()
            result = await self._read(
                keys=[_tpm_key(model_id)],
                args=[now, _WINDOW_SECONDS],
            )
            total, oldest = int(result[0]), float(result[1])
            remaining = max(tpm - total, 0)
            return RateLimitResult(
                limit_type=LimitType.TPM,
                limit=tpm,
                remaining=remaining,
                reset_at=int(oldest + _WINDOW_SECONDS),
                allowed=remaining > 0,
            )

        return await self._with_fallback(LimitType.TPM, tpm, _op)

    async def debit_tpm(self, model_id: UUID, tpm: int, tokens: int) -> None:
        """Post-flight: charge ``tokens`` against the TPM window. Best-effort.

        Failures are logged and swallowed so a Redis blip never propagates
        back to a successful inference response. ``tpm`` is unused here -- it
        only matters for the read-side check -- but kept in the signature for
        symmetry and so a future per-debit cap could plug in without changing
        callers.
        """
        del tpm  # signature-only
        if tokens <= 0:
            return
        try:
            now = time.time()
            member = f"{tokens}:{uuid.uuid4().hex}"
            await self._hit(
                keys=[_tpm_key(model_id)],
                args=[now, _WINDOW_SECONDS, tokens, member],
            )
            logger.debug("tpm_debit model_id=%s tokens=%d", model_id, tokens)
        except (RedisError, OSError) as exc:
            logger.warning(
                "tpm_debit_failed model_id=%s tokens=%d err=%s", model_id, tokens, exc,
            )

    # -- internals ---------------------------------------------------------

    async def _with_fallback(
        self,
        limit_type: LimitType,
        limit: int,
        op: Callable[[], Awaitable[RateLimitResult]],
    ) -> RateLimitResult:
        try:
            return await op()
        except (RedisError, OSError) as exc:
            if self._fail_mode == "closed":
                logger.error(
                    "rate_limit_storage_error type=%s limit=%d fail_mode=closed err=%s",
                    limit_type.value, limit, exc,
                )
                raise
            logger.warning(
                "rate_limit_storage_error type=%s limit=%d fail_mode=open allowing request (%s)",
                limit_type.value, limit, exc,
            )
            return RateLimitResult(
                limit_type=limit_type,
                limit=limit,
                remaining=limit,
                reset_at=int(time.time()) + _WINDOW_SECONDS,
                allowed=True,
            )

    # -- combined entry point ---------------------------------------------

    async def enforce(
        self,
        model_id: UUID,
        *,
        rpm: int | None,
        tpm: int | None,
    ) -> RateLimitContext:
        """Run RPM then TPM pre-flight checks.

        Either limit may be None (unlimited); skipped fields produce ``None``
        results. On denial raises :class:`RateLimitExceeded` for the first
        breached limit.
        """
        rpm_result: RateLimitResult | None = None
        tpm_result: RateLimitResult | None = None

        if rpm and rpm > 0:
            rpm_result = await self.check_rpm(model_id, rpm)
            if not rpm_result.allowed:
                raise RateLimitExceeded(
                    LimitType.RPM, rpm, rpm_result.retry_after_seconds,
                )

        if tpm and tpm > 0:
            tpm_result = await self.check_tpm(model_id, tpm)
            if not tpm_result.allowed:
                raise RateLimitExceeded(
                    LimitType.TPM, tpm, tpm_result.retry_after_seconds,
                )

        return RateLimitContext(
            model_id=model_id,
            rpm_limit=rpm,
            tpm_limit=tpm,
            rpm_result=rpm_result,
            tpm_result=tpm_result,
            _limiter=self,
        )


# Sentinel context for requests with no limits configured. Lets call sites
# always receive a context object without branching, even when the model is
# unlimited or rate limiting is globally disabled.
NULL_CONTEXT = RateLimitContext(
    model_id=None,
    rpm_limit=None,
    tpm_limit=None,
    rpm_result=None,
    tpm_result=None,
    _limiter=None,
)
