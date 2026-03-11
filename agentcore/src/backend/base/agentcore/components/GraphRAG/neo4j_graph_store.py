"""
Neo4j Knowledge Graph Store Component

Delegates all Neo4j operations to the graph-rag-service microservice.
Embedding generation stays local (via the connected Embedding component).

Canvas wiring:
  [Embedding] --+
                +---> [Neo4j Graph Store] ---> Search Results / DataFrame
  [Entities]  --+         ^
                      [Search Query]
"""

from __future__ import annotations

from loguru import logger

from agentcore.custom.custom_node.node import Node
from agentcore.io import (
    BoolInput,
    DropdownInput,
    HandleInput,
    IntInput,
    Output,
    QueryInput,
    StrInput,
)
from agentcore.schema.data import Data
from agentcore.schema.message import Message
from agentcore.services.graph_rag_service_client import (
    ensure_vector_index_via_service,
    fetch_unembedded_via_service,
    get_stats_via_service,
    ingest_via_service,
    search_via_service,
    store_embeddings_via_service,
)

# Max entities to embed per loop iteration
_EMBED_BATCH_SIZE = 200


class Neo4jGraphStoreComponent(Node):
    """Neo4j Knowledge Graph Store with entity ingestion and graph-aware search."""

    display_name: str = "Neo4j Graph Store"
    description: str = (
        "Store and retrieve knowledge graph entities in Neo4j. "
        "Ingest extracted entities/relationships and perform graph-aware "
        "vector similarity search with multi-hop context expansion."
    )
    name = "Neo4jGraphStore"
    icon = "GitFork"

    inputs = [
        StrInput(
            name="graph_kb_id",
            display_name="Graph KB ID",
            info="Unique identifier to isolate this knowledge graph's data in Neo4j.",
            value="default",
        ),
        HandleInput(
            name="ingest_data",
            display_name="Ingest Entities",
            input_types=["Data"],
            is_list=True,
            info="Extracted entities from Graph Entity Extractor.",
        ),
        QueryInput(
            name="search_query",
            display_name="Search Query",
            info="Natural language query for graph-aware vector search.",
            input_types=["Message"],
            tool_mode=True,
        ),
        HandleInput(
            name="embedding",
            display_name="Embedding",
            input_types=["Embeddings"],
            info="Embedding model for entity vector search.",
        ),
        IntInput(
            name="number_of_results",
            display_name="Number of Results",
            info="Top-K entities to retrieve via vector similarity.",
            value=10,
            advanced=True,
        ),
        IntInput(
            name="expansion_hops",
            display_name="Expansion Hops",
            info="How many relationship hops to expand (1-3).",
            value=2,
            advanced=True,
        ),
        BoolInput(
            name="include_source_chunks",
            display_name="Include Source Chunks",
            info="Also return the original text chunks that mentioned matched entities.",
            value=True,
            advanced=True,
        ),
        DropdownInput(
            name="search_type",
            display_name="Search Type",
            options=["Vector Similarity", "Keyword", "Hybrid"],
            value="Vector Similarity",
            advanced=True,
        ),
    ]

    outputs = [
        Output(display_name="Search Results", name="search_results", method="search_graph"),
        Output(display_name="DataFrame", name="dataframe", method="as_dataframe"),
        Output(display_name="Graph Stats", name="graph_stats", method="get_stats"),
    ]

    # ------------------------------------------------------------------
    # Query resolution
    # ------------------------------------------------------------------

    def _resolve_search_query(self) -> str:
        query = self.search_query
        if query is None:
            return ""
        if isinstance(query, str):
            return query.strip()
        if isinstance(query, Message):
            return (query.text or "").strip()
        if isinstance(query, Data):
            return (query.text or "").strip()
        if isinstance(query, dict):
            return (query.get("text", "") or "").strip()
        return str(query).strip()

    # ------------------------------------------------------------------
    # Ingest entities via microservice
    # ------------------------------------------------------------------

    def _ingest_entities(self) -> int:
        ingest_data = self.ingest_data
        if not ingest_data:
            return 0
        if not isinstance(ingest_data, list):
            ingest_data = [ingest_data]

        graph_kb_id = self.graph_kb_id or "default"
        entities = []

        for item in ingest_data:
            if not isinstance(item, Data):
                continue
            data = item.data if hasattr(item, "data") else {}
            if not isinstance(data, dict):
                continue

            entity_name = (data.get("name") or data.get("entity_name") or "").strip()
            if not entity_name:
                continue

            relationships = []
            for rel in (data.get("relationships") or []):
                if not isinstance(rel, dict):
                    continue
                target = (rel.get("target") or rel.get("target_name") or "").strip()
                if not target:
                    continue
                weight = rel.get("weight", 1.0)
                try:
                    weight = float(weight)
                except (ValueError, TypeError):
                    weight = 1.0

                relationships.append({
                    "target": target,
                    "target_type": (rel.get("target_type") or "Entity").strip(),
                    "type": (rel.get("type") or rel.get("relationship") or "RELATED_TO").strip(),
                    "description": (rel.get("description") or "")[:2000],
                    "weight": max(0.0, min(weight, 1.0)),
                })

            entities.append({
                "name": entity_name,
                "type": (data.get("type") or data.get("entity_type") or "Entity").strip(),
                "description": (data.get("description") or data.get("text") or "").strip(),
                "source_chunk_id": data.get("source_chunk_id"),
                "id": data.get("id"),
                "relationships": relationships,
            })

        if not entities:
            return 0

        result = ingest_via_service(entities=entities, graph_kb_id=graph_kb_id)
        count = result.get("entities_created", 0)
        rels = result.get("relationships_created", 0)
        self.log(f"Ingested {count} entities, {rels} relationships into graph '{graph_kb_id}'.")
        return count

    # ------------------------------------------------------------------
    # Compute and store entity embeddings (local embedding + microservice storage)
    # ------------------------------------------------------------------

    def _embed_entities(self) -> int:
        if not self.embedding:
            self.log("No embedding model connected -- skipping entity embedding.")
            return 0

        graph_kb_id = self.graph_kb_id or "default"
        total_embedded = 0

        while True:
            resp = fetch_unembedded_via_service(graph_kb_id=graph_kb_id, batch_size=_EMBED_BATCH_SIZE)
            records = resp.get("entities", [])
            if not records:
                break

            texts = [f"{r['name']}: {r.get('description', '')}" for r in records]
            try:
                embeddings = self.embedding.embed_documents(texts)
            except Exception as e:
                logger.error(f"[Neo4j Graph Store] Embedding computation failed: {e}")
                raise ValueError(f"Embedding model failed: {e}") from e

            pairs = [
                {"element_id": records[i]["element_id"], "embedding": embeddings[i]}
                for i in range(len(records))
            ]
            store_embeddings_via_service(graph_kb_id=graph_kb_id, embeddings=pairs)
            total_embedded += len(pairs)
            self.log(f"Embedded {total_embedded} entities so far...")

            if len(records) < _EMBED_BATCH_SIZE:
                break

        if total_embedded > 0:
            ensure_vector_index_via_service(graph_kb_id=graph_kb_id)
            self.log(f"Embedding complete: {total_embedded} entities embedded.")
        return total_embedded

    # ------------------------------------------------------------------
    # Search via microservice
    # ------------------------------------------------------------------

    def search_graph(self) -> list[Data]:
        if self.ingest_data:
            count = self._ingest_entities()
            if count > 0:
                self._embed_entities()

        query = self._resolve_search_query()
        if not query:
            self.status = "No search query provided."
            return []

        self.log(f"Searching graph with: '{query}' (type={self.search_type})")

        query_embedding = None
        search_type = (self.search_type or "Vector Similarity").lower()
        if "vector" in search_type or "hybrid" in search_type:
            if self.embedding:
                try:
                    query_embedding = self.embedding.embed_query(query)
                except Exception as e:
                    logger.warning(f"[Neo4j Graph Store] Failed to embed query: {e}")

        if "keyword" in search_type:
            api_search_type = "keyword"
        elif "hybrid" in search_type:
            api_search_type = "hybrid"
        else:
            api_search_type = "vector_similarity"

        resp = search_via_service(
            query=query,
            query_embedding=query_embedding,
            graph_kb_id=self.graph_kb_id or "default",
            search_type=api_search_type,
            number_of_results=self.number_of_results,
            expansion_hops=self.expansion_hops,
            include_source_chunks=self.include_source_chunks,
        )

        results = []
        for item in resp.get("results", []):
            results.append(Data(
                text=item.get("text", ""),
                data={
                    "entity_name": item.get("entity_name", ""),
                    "entity_type": item.get("entity_type", ""),
                    "entity_description": item.get("entity_description", ""),
                    "score": item.get("score", 0),
                    "neighbors": item.get("neighbors", []),
                    "source_chunks": item.get("source_chunks", []),
                    "search_type": item.get("search_type", ""),
                    "graph_kb_id": item.get("graph_kb_id", ""),
                },
            ))

        self.status = (
            f"{len(results)} result(s) | search={self.search_type} "
            f"| graph={self.graph_kb_id}"
        )
        return results

    # ------------------------------------------------------------------
    # DataFrame output
    # ------------------------------------------------------------------

    def as_dataframe(self):
        from agentcore.schema.dataframe import DataFrame
        results = self.search_graph()
        return DataFrame(results)

    # ------------------------------------------------------------------
    # Stats via microservice
    # ------------------------------------------------------------------

    def get_stats(self) -> Data:
        graph_kb_id = self.graph_kb_id or "default"
        stats = get_stats_via_service(graph_kb_id=graph_kb_id)
        self.status = (
            f"Nodes: {stats.get('node_count', 0)} | "
            f"Edges: {stats.get('edge_count', 0)} | "
            f"Communities: {stats.get('community_count', 0)}"
        )
        return Data(data=stats)
