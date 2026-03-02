from __future__ import annotations

from typing import TYPE_CHECKING, Any

from agentcore.components._importing import import_mod

if TYPE_CHECKING:
    from .entity_resolver import EntityResolverComponent
    from .graph_community_search import GraphCommunitySearchComponent
    from .graph_entity_extractor import GraphEntityExtractorComponent
    from .graph_rag_retriever import GraphRAGRetrieverComponent
    from .graph_schema_config import GraphSchemaConfigComponent
    from .graph_transformer import GraphTransformerComponent
    from .neo4j_graph_store import Neo4jGraphStoreComponent

_dynamic_imports = {
    "Neo4jGraphStoreComponent": "neo4j_graph_store",
    "GraphEntityExtractorComponent": "graph_entity_extractor",
    "GraphRAGRetrieverComponent": "graph_rag_retriever",
    "GraphCommunitySearchComponent": "graph_community_search",
    "GraphSchemaConfigComponent": "graph_schema_config",
    "EntityResolverComponent": "entity_resolver",
    "GraphTransformerComponent": "graph_transformer",
}

__all__ = [
    "Neo4jGraphStoreComponent",
    "GraphEntityExtractorComponent",
    "GraphRAGRetrieverComponent",
    "GraphCommunitySearchComponent",
    "GraphSchemaConfigComponent",
    "EntityResolverComponent",
    "GraphTransformerComponent",
]


def __getattr__(attr_name: str) -> Any:
    """Lazily import graph RAG components on attribute access."""
    if attr_name not in _dynamic_imports:
        msg = f"module '{__name__}' has no attribute '{attr_name}'"
        raise AttributeError(msg)
    try:
        result = import_mod(attr_name, _dynamic_imports[attr_name], __spec__.parent)
    except (ModuleNotFoundError, ImportError, AttributeError) as e:
        msg = f"Could not import '{attr_name}' from '{__name__}': {e}"
        raise AttributeError(msg) from e
    globals()[attr_name] = result
    return result


def __dir__() -> list[str]:
    return list(__all__)
