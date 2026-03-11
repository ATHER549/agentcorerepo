"""Reusable transaction logging for LangGraph vertex execution.

Extracted from adapter.py build_vertex() so that both the custom execution path
(adapter.build_vertex) and the LangGraph compiled path (create_node_function)
can share the same logging logic.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pandas as pd
from loguru import logger

if TYPE_CHECKING:
    from agentcore.graph_langgraph.adapter import LangGraphAdapter
    from agentcore.graph_langgraph.vertex_wrapper import LangGraphVertex


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _prepare_inputs(vertex: LangGraphVertex) -> dict | None:
    """Serialize vertex raw_params to primitive types for logging."""
    from agentcore.graph_langgraph.logging import _vertex_to_primitive_dict

    if not vertex.raw_params:
        return None
    return _vertex_to_primitive_dict(vertex.raw_params)


def _prepare_outputs(vertex: LangGraphVertex) -> dict | None:
    """Serialize vertex built_result for logging."""
    if vertex.built_result is None:
        return None
    try:
        if isinstance(vertex.built_result, dict):
            result_dict = vertex.built_result.copy()
        elif hasattr(vertex.built_result, "model_dump"):
            result_dict = vertex.built_result.model_dump()
        elif hasattr(vertex.built_result, "__dict__"):
            result_dict = vertex.built_result.__dict__
        else:
            result_dict = {"result": str(vertex.built_result)}

        # Handle pandas DataFrames
        for key, value in list(result_dict.items()):
            if isinstance(value, pd.DataFrame):
                result_dict[key] = value.to_dict()
        return result_dict
    except Exception as e:
        logger.debug(f"Error preparing outputs for {vertex.id}: {e}")
        return {"result": str(vertex.built_result)}


def _get_target_ids(vertex: LangGraphVertex) -> list[str]:
    """Get target vertex IDs from outgoing edges."""
    target_ids: list[str] = []
    if hasattr(vertex, "outgoing_edges"):
        for edge in vertex.outgoing_edges:
            if hasattr(edge, "target") and hasattr(edge.target, "id"):
                target_ids.append(edge.target.id)
    return target_ids


def _prepare_serialized_io(
    vertex: LangGraphVertex,
) -> tuple[Any, Any]:
    """Prepare serialized inputs/outputs for orch/prod/uat tables."""
    from agentcore.graph_langgraph.logging import _vertex_to_primitive_dict
    from agentcore.serialization.serialization import (
        get_max_items_length,
        get_max_text_length,
        serialize,
    )

    _ml = get_max_text_length()
    _mi = get_max_items_length()
    ser_inputs = (
        serialize(_vertex_to_primitive_dict(vertex.raw_params), max_length=_ml, max_items=_mi)
        if vertex.raw_params
        else None
    )
    ser_outputs = (
        serialize(vertex.built_result, max_length=_ml, max_items=_mi)
        if vertex.built_result is not None
        else None
    )
    return ser_inputs, ser_outputs


def _to_uuid(value: Any) -> Any:
    """Convert a string to UUID if needed."""
    from uuid import UUID as _UUID

    if value is None:
        return None
    return value if isinstance(value, _UUID) else _UUID(value)


# ---------------------------------------------------------------------------
# Per-table logging
# ---------------------------------------------------------------------------

async def _log_dev_transaction(
    graph: LangGraphAdapter,
    vertex: LangGraphVertex,
    status: str,
    error: str | None = None,
) -> None:
    """Log to the dev `transaction` table."""
    from agentcore.graph_langgraph.logging import log_transaction

    inputs_for_log = _prepare_inputs(vertex)
    outputs_for_log = _prepare_outputs(vertex) if status == "success" else None
    target_ids = _get_target_ids(vertex)

    targets = target_ids if target_ids else [None]
    for target_id in targets:
        await log_transaction(
            agent_id=graph.agent_id,
            vertex_id=vertex.id,
            status=status,
            inputs=inputs_for_log,
            outputs=outputs_for_log,
            target_id=target_id,
            error=error,
        )


async def _log_orch_transaction(
    graph: LangGraphAdapter,
    vertex: LangGraphVertex,
    status: str,
    error: str | None = None,
) -> None:
    """Log to the `orch_transaction` table."""
    from agentcore.services.database.models.orch_transaction.crud import orch_log_transaction
    from agentcore.services.database.models.orch_transaction.model import OrchTransactionTable
    from agentcore.services.database.utils import session_getter
    from agentcore.services.deps import get_db_service

    ser_inputs, ser_outputs = _prepare_serialized_io(vertex)
    if status == "error":
        ser_outputs = None

    agent_uuid = _to_uuid(graph.agent_id)
    dep_uuid = _to_uuid(graph.orch_deployment_id)
    org_uuid = _to_uuid(graph.orch_org_id)
    dept_uuid = _to_uuid(graph.orch_dept_id)

    target_ids = _get_target_ids(vertex)
    targets = target_ids if target_ids else [None]

    async with session_getter(get_db_service()) as db:
        for tid in targets:
            txn = OrchTransactionTable(
                vertex_id=vertex.id,
                target_id=tid,
                inputs=ser_inputs,
                outputs=ser_outputs,
                status=status,
                error=error,
                agent_id=agent_uuid,
                session_id=graph.orch_session_id,
                deployment_id=dep_uuid,
                org_id=org_uuid,
                dept_id=dept_uuid,
            )
            await orch_log_transaction(txn, db)


async def _log_prod_transaction(
    graph: LangGraphAdapter,
    vertex: LangGraphVertex,
    status: str,
    error: str | None = None,
) -> None:
    """Log to the `transaction_prod` table."""
    from agentcore.services.database.models.transaction_prod.crud import log_transaction_prod
    from agentcore.services.database.models.transaction_prod.model import TransactionProdTable
    from agentcore.services.database.utils import session_getter
    from agentcore.services.deps import get_db_service

    ser_inputs, ser_outputs = _prepare_serialized_io(vertex)
    if status == "error":
        ser_outputs = None

    agent_uuid = _to_uuid(graph.agent_id)
    dep_uuid = _to_uuid(graph.prod_deployment_id)
    org_uuid = _to_uuid(graph.prod_org_id)
    dept_uuid = _to_uuid(graph.prod_dept_id)

    target_ids = _get_target_ids(vertex)
    targets = target_ids if target_ids else [None]

    async with session_getter(get_db_service()) as db:
        for tid in targets:
            prod_txn = TransactionProdTable(
                vertex_id=vertex.id,
                target_id=tid,
                inputs=ser_inputs,
                outputs=ser_outputs,
                status=status,
                error=error,
                agent_id=agent_uuid,
                deployment_id=dep_uuid,
                org_id=org_uuid,
                dept_id=dept_uuid,
            )
            await log_transaction_prod(prod_txn, db)


async def _log_uat_transaction(
    graph: LangGraphAdapter,
    vertex: LangGraphVertex,
    status: str,
    error: str | None = None,
) -> None:
    """Log to the `transaction_uat` table."""
    from agentcore.services.database.models.transaction_uat.crud import log_transaction_uat
    from agentcore.services.database.models.transaction_uat.model import TransactionUATTable
    from agentcore.services.database.utils import session_getter
    from agentcore.services.deps import get_db_service

    ser_inputs, ser_outputs = _prepare_serialized_io(vertex)
    if status == "error":
        ser_outputs = None

    agent_uuid = _to_uuid(graph.agent_id)
    dep_uuid = _to_uuid(graph.uat_deployment_id)
    org_uuid = _to_uuid(graph.uat_org_id)
    dept_uuid = _to_uuid(graph.uat_dept_id)

    target_ids = _get_target_ids(vertex)
    targets = target_ids if target_ids else [None]

    async with session_getter(get_db_service()) as db:
        for tid in targets:
            uat_txn = TransactionUATTable(
                vertex_id=vertex.id,
                target_id=tid,
                inputs=ser_inputs,
                outputs=ser_outputs,
                status=status,
                error=error,
                agent_id=agent_uuid,
                deployment_id=dep_uuid,
                org_id=org_uuid,
                dept_id=dept_uuid,
            )
            await log_transaction_uat(uat_txn, db)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def log_all_transactions(
    *,
    vertex: LangGraphVertex,
    graph: LangGraphAdapter,
    status: str,
    error: str | None = None,
) -> None:
    """Log transaction to all applicable tables based on graph context.

    Determines which tables to log to based on graph flags:
    - Dev transaction table: when ``not skip_dev_logging``
    - Orch transaction table: when ``skip_dev_logging`` and ``orch_session_id`` set
    - Prod transaction table: when ``prod_deployment_id`` set
    - UAT transaction table: when ``uat_deployment_id`` set
    """
    # Dev table
    if graph.agent_id and not graph.skip_dev_logging:
        try:
            await _log_dev_transaction(graph, vertex, status, error)
        except Exception as log_error:
            logger.warning(f"Failed to log dev transaction for {vertex.id}: {log_error}")

    # Orch table
    if graph.agent_id and graph.skip_dev_logging and graph.orch_session_id:
        try:
            await _log_orch_transaction(graph, vertex, status, error)
        except Exception as log_error:
            logger.warning(f"Failed to log orch transaction for {vertex.id}: {log_error}")

    # Prod table
    if graph.agent_id and graph.prod_deployment_id:
        try:
            await _log_prod_transaction(graph, vertex, status, error)
        except Exception as log_error:
            logger.warning(f"Failed to log transaction_prod for {vertex.id}: {log_error}")

    # UAT table
    if graph.agent_id and graph.uat_deployment_id:
        try:
            await _log_uat_transaction(graph, vertex, status, error)
        except Exception as log_error:
            logger.warning(f"Failed to log transaction_uat for {vertex.id}: {log_error}")


async def log_vertex_build_record(
    *,
    vertex: LangGraphVertex,
    graph: LangGraphAdapter,
    valid: bool,
    data_dict: dict | None = None,
) -> None:
    """Log vertex build record when dev logging is enabled."""
    if not (graph.agent_id and not graph.skip_dev_logging):
        return

    try:
        from agentcore.graph_langgraph.logging import log_vertex_build

        await log_vertex_build(
            agent_id=_to_uuid(graph.agent_id),
            vertex_id=vertex.id,
            valid=valid,
            params=vertex.raw_params,
            data=data_dict,
            artifacts=vertex.artifacts if valid else None,
        )
    except Exception as log_error:
        logger.warning(f"Failed to log vertex build for {vertex.id}: {log_error}")
