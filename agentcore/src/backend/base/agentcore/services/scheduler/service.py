from __future__ import annotations

import asyncio
import time
from uuid import UUID

from loguru import logger

from agentcore.services.base import Service


class SchedulerService(Service):
    """Manages cron/interval-based scheduled execution of agent flows.

    Uses APScheduler's AsyncIOScheduler to register and run jobs that invoke
    deployed agent flows at configured intervals or cron expressions.
    """

    name = "scheduler_service"

    def __init__(self) -> None:
        self._scheduler = None
        self._started = False

    def _ensure_scheduler(self):
        """Lazily import and create the APScheduler instance."""
        if self._scheduler is None:
            try:
                from apscheduler.schedulers.asyncio import AsyncIOScheduler

                self._scheduler = AsyncIOScheduler()
            except ImportError:
                logger.warning(
                    "APScheduler not installed. Schedule triggers will not work. "
                    "Install with: pip install apscheduler>=3.10"
                )
                self._scheduler = None

    def start(self) -> None:
        """Start the scheduler."""
        self._ensure_scheduler()
        if self._scheduler and not self._started:
            self._scheduler.start()
            self._started = True
            logger.info("SchedulerService started")
        self.set_ready()

    async def teardown(self) -> None:
        """Shutdown the scheduler gracefully."""
        if self._scheduler and self._started:
            self._scheduler.shutdown(wait=False)
            self._started = False
            logger.info("SchedulerService shut down")

    async def load_active_schedules(self) -> None:
        """Load all active schedule triggers from the database and register them."""
        from agentcore.services.deps import get_db_service

        try:
            db_service = get_db_service()
            async with db_service.with_session() as session:
                from agentcore.services.database.models.trigger_config.crud import (
                    get_active_triggers_by_type,
                )
                from agentcore.services.database.models.trigger_config.model import TriggerTypeEnum

                triggers = await get_active_triggers_by_type(session, TriggerTypeEnum.SCHEDULE)
                for trigger in triggers:
                    await self._register_from_config(trigger)

                logger.info(f"Loaded {len(triggers)} active schedule triggers")
        except Exception as e:
            logger.warning(f"Failed to load active schedules (table may not exist yet): {e}")

    async def add_schedule(
        self,
        trigger_config_id: UUID,
        agent_id: UUID,
        *,
        schedule_type: str = "interval",
        interval_minutes: int = 60,
        cron_expression: str = "0 * * * *",
        environment: str = "dev",
        version: str | None = None,
    ) -> bool:
        """Add a scheduled job.

        Args:
            trigger_config_id: The trigger config record ID.
            agent_id: The agent to execute.
            schedule_type: "interval" or "cron".
            interval_minutes: Minutes between runs (interval mode).
            cron_expression: Cron expression (cron mode).
            environment: Environment to run in.
            version: Deployment version.

        Returns:
            True if the job was added successfully.
        """
        self._ensure_scheduler()
        if not self._scheduler:
            logger.error("Scheduler not available — cannot add schedule")
            return False

        job_id = str(trigger_config_id)

        # Remove existing job if any
        existing = self._scheduler.get_job(job_id)
        if existing:
            self._scheduler.remove_job(job_id)

        try:
            if schedule_type == "cron":
                from apscheduler.triggers.cron import CronTrigger

                trigger = CronTrigger.from_crontab(cron_expression)
                self._scheduler.add_job(
                    self._execute_trigger,
                    trigger=trigger,
                    id=job_id,
                    kwargs={
                        "trigger_config_id": trigger_config_id,
                        "agent_id": agent_id,
                        "environment": environment,
                        "version": version,
                    },
                    replace_existing=True,
                )
            else:
                from apscheduler.triggers.interval import IntervalTrigger

                trigger = IntervalTrigger(minutes=max(1, interval_minutes))
                self._scheduler.add_job(
                    self._execute_trigger,
                    trigger=trigger,
                    id=job_id,
                    kwargs={
                        "trigger_config_id": trigger_config_id,
                        "agent_id": agent_id,
                        "environment": environment,
                        "version": version,
                    },
                    replace_existing=True,
                )

            logger.info(
                f"Scheduled job {job_id} for agent {agent_id} "
                f"({schedule_type}: {cron_expression if schedule_type == 'cron' else f'{interval_minutes}min'})"
            )
            return True

        except Exception:
            logger.exception(f"Failed to add schedule for trigger {trigger_config_id}")
            return False

    async def remove_schedule(self, trigger_config_id: UUID) -> bool:
        """Remove a scheduled job."""
        if not self._scheduler:
            return False

        job_id = str(trigger_config_id)
        existing = self._scheduler.get_job(job_id)
        if existing:
            self._scheduler.remove_job(job_id)
            logger.info(f"Removed schedule job {job_id}")
            return True
        return False

    async def sync_schedule_for_agent(
        self,
        agent_id: UUID,
        environment: str,
        version: str,
    ) -> None:
        """Sync schedules for an agent from its deployed snapshot.

        Called by the publish flow. Reads ScheduleTrigger nodes from the agent
        snapshot and creates/updates APScheduler jobs.
        """
        logger.info(f"Syncing schedules for agent {agent_id} env={environment} version={version}")
        # This will be wired into publish.py later

    async def _register_from_config(self, trigger_record) -> None:
        """Register a schedule from a TriggerConfigTable record."""
        config = trigger_record.trigger_config or {}
        await self.add_schedule(
            trigger_config_id=trigger_record.id,
            agent_id=trigger_record.agent_id,
            schedule_type=config.get("schedule_type", "interval"),
            interval_minutes=config.get("interval_minutes", 60),
            cron_expression=config.get("cron_expression", "0 * * * *"),
            environment=trigger_record.environment,
            version=trigger_record.version,
        )

    async def _execute_trigger(
        self,
        trigger_config_id: UUID,
        agent_id: UUID,
        environment: str = "dev",
        version: str | None = None,
    ) -> None:
        """Execute the agent flow when the schedule fires.

        Reuses the existing execution pipeline via simple_run_agent_task().
        """
        from agentcore.services.deps import get_db_service

        start_time = time.perf_counter()
        logger.info(f"Schedule triggered for agent {agent_id} (trigger={trigger_config_id})")

        try:
            # Log execution start
            db_service = get_db_service()
            async with db_service.with_session() as session:
                from agentcore.services.database.models.trigger_config.crud import (
                    log_trigger_execution,
                    update_trigger_last_run,
                )
                from agentcore.services.database.models.trigger_config.model import (
                    TriggerExecutionStatusEnum,
                )

                await log_trigger_execution(
                    session,
                    trigger_config_id=trigger_config_id,
                    agent_id=agent_id,
                    status=TriggerExecutionStatusEnum.STARTED,
                    payload={
                        "trigger_type": "schedule",
                        "environment": environment,
                        "version": version,
                    },
                )
                await update_trigger_last_run(session, trigger_config_id)

            # Execute the agent flow — capture result so we can log the output
            run_result = await self._run_agent_flow(agent_id, environment, version, trigger_config_id)

            # Best-effort extraction of session_id and first output text
            session_id: str | None = None
            output_text: str | None = None
            if run_result is not None:
                session_id = run_result.session_id
                try:
                    for run_out in run_result.outputs or []:
                        for data in run_out.outputs or []:
                            if data and data.messages:
                                for msg in data.messages:
                                    txt = getattr(msg, "text", None)
                                    if txt:
                                        output_text = txt[:2000]  # cap to keep DB tidy
                                        break
                            if output_text:
                                break
                        if output_text:
                            break
                except Exception:
                    pass

            # Log success — include session_id and output for the frontend detail view
            elapsed_ms = int((time.perf_counter() - start_time) * 1000)
            async with db_service.with_session() as session:
                await log_trigger_execution(
                    session,
                    trigger_config_id=trigger_config_id,
                    agent_id=agent_id,
                    status=TriggerExecutionStatusEnum.SUCCESS,
                    execution_duration_ms=elapsed_ms,
                    payload={
                        "session_id": session_id or str(agent_id),
                        "output": output_text or "Agent completed (no text output captured)",
                    },
                )

            logger.info(f"Schedule execution completed for agent {agent_id} in {elapsed_ms}ms")

        except Exception as exc:
            elapsed_ms = int((time.perf_counter() - start_time) * 1000)
            logger.exception(f"Schedule execution failed for agent {agent_id}: {exc}")

            try:
                async with db_service.with_session() as session:
                    from agentcore.services.database.models.trigger_config.crud import (
                        log_trigger_execution,
                    )
                    from agentcore.services.database.models.trigger_config.model import (
                        TriggerExecutionStatusEnum,
                    )

                    await log_trigger_execution(
                        session,
                        trigger_config_id=trigger_config_id,
                        agent_id=agent_id,
                        status=TriggerExecutionStatusEnum.ERROR,
                        error_message=str(exc),
                        execution_duration_ms=elapsed_ms,
                    )
            except Exception:
                logger.exception("Failed to log trigger execution error")

    async def _run_agent_flow(
        self,
        agent_id: UUID,
        environment: str,
        version: str | None,
        trigger_config_id: UUID,
    ):
        """Invoke the agent flow using the existing execution pipeline."""
        from agentcore.services.deps import get_db_service

        db_service = get_db_service()
        async with db_service.with_session() as session:
            from sqlmodel import select

            from agentcore.services.database.models.agent.model import Agent

            stmt = select(Agent).where(Agent.id == agent_id)
            result = await session.exec(stmt)
            agent = result.first()

            if not agent:
                msg = f"Agent {agent_id} not found"
                raise ValueError(msg)

        # Use the existing endpoint logic to run the agent
        from agentcore.api.endpoints import _resolve_agent_data_for_env, simple_run_agent_task
        from agentcore.api.schemas import SimplifiedAPIRequest

        agent.data, prod_deployment, uat_deployment = await _resolve_agent_data_for_env(
            agent_id=agent.id,
            env=environment,
            version=version,  # None → latest active published deployment
        )

        # Empty input_value so the flow runs with its own configured node values.
        # The scheduler should NOT inject artificial text into the agent's inputs.
        input_request = SimplifiedAPIRequest(
            input_value="",
            input_type="chat",
            output_type="chat",
            tweaks={},
            session_id=None,
        )

        return await simple_run_agent_task(
            agent=agent,
            input_request=input_request,
            api_key_user=None,
            prod_deployment=prod_deployment,
            uat_deployment=uat_deployment,
        )