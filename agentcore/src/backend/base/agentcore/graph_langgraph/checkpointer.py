"""LangGraph checkpointer singleton.

Provides the checkpointer instance used by all compiled graphs.
Required for Human-in-the-Loop (HITL) via interrupt() to work.

Current implementation: MemorySaver (in-process, sufficient for dev/testing).
For production persistence across restarts, swap to AsyncPostgresSaver:

    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    from psycopg_pool import AsyncConnectionPool
    pool = AsyncConnectionPool(conninfo=DATABASE_URL)
    _checkpointer = AsyncPostgresSaver(pool)
    await _checkpointer.asetup()  # once at startup
"""

from __future__ import annotations

from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

# Module-level singleton — shared across all LangGraphAdapter instances.
# MemorySaver keeps state in-memory; interrupted runs survive as long as
# the process is alive.  Swap to AsyncPostgresSaver for production.
_checkpointer: MemorySaver | None = None


def get_checkpointer() -> MemorySaver:
    """Return (or lazily create) the shared LangGraph checkpointer.

    pickle_fallback=True is required because HITL graphs may also contain
    LangChain StructuredTool objects in vertices_results.  These are not
    msgpack-serializable; the JsonPlusSerializer will fall back to pickle
    for any value that msgpack cannot encode.
    """
    global _checkpointer
    if _checkpointer is None:
        serde = JsonPlusSerializer(pickle_fallback=True)
        _checkpointer = MemorySaver(serde=serde)
    return _checkpointer


def reset_checkpointer() -> None:
    """Reset the checkpointer (test helper — clears all saved state)."""
    global _checkpointer
    _checkpointer = None
