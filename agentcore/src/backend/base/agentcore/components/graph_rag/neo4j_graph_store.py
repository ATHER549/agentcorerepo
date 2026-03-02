"""
Neo4j Knowledge Graph Store Component

Drag-and-drop node that connects to Neo4j and stores/retrieves
entities and relationships as a knowledge graph.

Canvas wiring:
  [Embedding] --+
                +---> [Neo4j Graph Store] ---> Search Results / DataFrame
  [Entities]  --+         ^
                      [Search Query]

This component:
  - Accepts extracted entities (from Graph Entity Extractor) and upserts them into Neo4j
  - Supports vector similarity search on entity embeddings
  - Returns graph-aware search results with relationship context
  - Manages per-graph-KB isolation via graph_kb_id labels
"""

from __future__ import annotations

import os
from uuid import uuid4

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

# Max entities per Neo4j UNWIND batch (prevents transaction timeouts)
_INGEST_BATCH_SIZE = 100
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
        # -- Graph Identification ---------------------------------------
        StrInput(
            name="graph_kb_id",
            display_name="Graph KB ID",
            info="Unique identifier to isolate this knowledge graph's data in Neo4j. "
                 "All nodes/edges are tagged with this ID.",
            value="default",
        ),

        # -- Data Ingest ------------------------------------------------
        HandleInput(
            name="ingest_data",
            display_name="Ingest Entities",
            input_types=["Data"],
            is_list=True,
            info="Extracted entities from Graph Entity Extractor. "
                 "Each Data item should have: name, type, description, "
                 "and optionally 'relationships' list.",
        ),

        # -- Search -----------------------------------------------------
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

        # -- Search Config ----------------------------------------------
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
            info="How many relationship hops to expand from matched entities (1-3). "
                 "More hops = richer context but slower queries.",
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
            info="Vector: embedding cosine similarity. "
                 "Keyword: exact name/type match. "
                 "Hybrid: combines both.",
        ),
    ]

    outputs = [
        Output(
            display_name="Search Results",
            name="search_results",
            method="search_graph",
        ),
        Output(
            display_name="DataFrame",
            name="dataframe",
            method="as_dataframe",
        ),
        Output(
            display_name="Graph Stats",
            name="graph_stats",
            method="get_stats",
        ),
    ]

    # ------------------------------------------------------------------
    # Query resolution (handles Message / Data / dict / str)
    # ------------------------------------------------------------------

    def _resolve_search_query(self) -> str:
        """Resolve self.search_query into a plain string regardless of input type."""
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
    # Internal: get or create Neo4j driver
    # ------------------------------------------------------------------

    def _get_driver(self):
        """Create a Neo4j driver and verify connectivity."""
        try:
            from neo4j import GraphDatabase
        except ImportError as e:
            msg = (
                "The 'neo4j' package is required. "
                "Install with: pip install neo4j>=5.20.0"
            )
            raise ImportError(msg) from e

        uri = os.getenv("NEO4J_URI", "")
        username = os.getenv("NEO4J_USERNAME", "neo4j")
        password = os.getenv("NEO4J_PASSWORD", "")

        if not uri:
            raise ValueError(
                "Neo4j URI is required. Set NEO4J_URI in the .env file "
                "(e.g. NEO4J_URI=neo4j+s://xxx.databases.neo4j.io)."
            )

        try:
            driver = GraphDatabase.driver(uri, auth=(username, password))
            driver.verify_connectivity()
        except Exception as e:
            raise ValueError(
                f"Failed to connect to Neo4j at '{uri}': {e}. "
                f"Check your URI, credentials, and network connectivity."
            ) from e

        return driver

    def _get_database(self) -> str:
        return os.getenv("NEO4J_DATABASE", "neo4j")

    # ------------------------------------------------------------------
    # Ingest entities into Neo4j (batched)
    # ------------------------------------------------------------------

    def _ingest_entities(self, driver) -> int:
        """Upsert entities and their relationships into Neo4j in batches."""
        ingest_data = self.ingest_data
        if not ingest_data:
            return 0

        if not isinstance(ingest_data, list):
            ingest_data = [ingest_data]

        db = self._get_database()
        graph_kb_id = self.graph_kb_id or "default"

        # Collect entity rows for batch upsert
        entity_rows = []
        relationship_rows = []

        for item in ingest_data:
            if not isinstance(item, Data):
                continue

            data = item.data if hasattr(item, "data") else {}
            if not isinstance(data, dict):
                continue

            entity_name = (data.get("name") or data.get("entity_name") or "").strip()
            if not entity_name:
                continue

            entity_type = (data.get("type") or data.get("entity_type") or "Entity").strip()
            description = (data.get("description") or data.get("text") or "").strip()
            source_chunk_id = data.get("source_chunk_id")
            entity_id = data.get("id") or str(uuid4())

            entity_rows.append({
                "id": entity_id,
                "name": entity_name,
                "type": entity_type,
                "description": description[:5000],  # Cap description size
                "graph_kb_id": graph_kb_id,
                "source_chunk_id": source_chunk_id,
            })

            # Extract relationships if present
            relationships = data.get("relationships") or []
            for rel in relationships:
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

                relationship_rows.append({
                    "source_name": entity_name,
                    "target_name": target,
                    "target_type": (rel.get("target_type") or "Entity").strip(),
                    "rel_type": (rel.get("type") or rel.get("relationship") or "RELATED_TO").strip(),
                    "description": (rel.get("description") or "")[:2000],
                    "weight": max(0.0, min(weight, 1.0)),
                    "graph_kb_id": graph_kb_id,
                })

        if not entity_rows:
            return 0

        entities_created = 0

        # Batch upsert entities
        try:
            for i in range(0, len(entity_rows), _INGEST_BATCH_SIZE):
                batch = entity_rows[i : i + _INGEST_BATCH_SIZE]
                with driver.session(database=db) as session:
                    session.run(
                        """
                        UNWIND $rows AS row
                        MERGE (e:__Entity__ {name: row.name, graph_kb_id: row.graph_kb_id})
                        ON CREATE SET
                            e.id = row.id,
                            e.type = row.type,
                            e.description = row.description
                        ON MATCH SET
                            e.description = CASE
                                WHEN size(row.description) > size(coalesce(e.description, ''))
                                THEN row.description
                                ELSE e.description
                            END,
                            e.type = row.type
                        """,
                        rows=batch,
                    )
                    entities_created += len(batch)

                    # Link source chunks where available
                    chunk_links = [r for r in batch if r.get("source_chunk_id")]
                    if chunk_links:
                        session.run(
                            """
                            UNWIND $rows AS row
                            MATCH (e:__Entity__ {name: row.name, graph_kb_id: row.graph_kb_id})
                            MERGE (c:__Chunk__ {id: row.source_chunk_id, graph_kb_id: row.graph_kb_id})
                            MERGE (c)-[:MENTIONS]->(e)
                            """,
                            rows=chunk_links,
                        )

                if i + _INGEST_BATCH_SIZE < len(entity_rows):
                    self.log(f"Ingested {entities_created}/{len(entity_rows)} entities...")

        except Exception as e:
            logger.error(f"[Neo4j Graph Store] Entity ingestion failed at batch: {e}")
            raise ValueError(
                f"Failed to ingest entities into Neo4j: {e}. "
                f"Successfully ingested {entities_created} before failure."
            ) from e

        # Batch upsert relationships
        rels_created = 0
        if relationship_rows:
            try:
                for i in range(0, len(relationship_rows), _INGEST_BATCH_SIZE):
                    batch = relationship_rows[i : i + _INGEST_BATCH_SIZE]
                    with driver.session(database=db) as session:
                        session.run(
                            """
                            UNWIND $rows AS row
                            MERGE (src:__Entity__ {name: row.source_name, graph_kb_id: row.graph_kb_id})
                            MERGE (tgt:__Entity__ {name: row.target_name, graph_kb_id: row.graph_kb_id})
                            ON CREATE SET tgt.type = row.target_type, tgt.id = randomUUID()
                            MERGE (src)-[r:RELATED_TO]->(tgt)
                            ON CREATE SET r.description = row.description, r.weight = row.weight
                            ON MATCH SET
                                r.weight = row.weight,
                                r.description = CASE
                                    WHEN size(row.description) > size(coalesce(r.description, ''))
                                    THEN row.description ELSE r.description
                                END
                            """,
                            rows=batch,
                        )
                        rels_created += len(batch)
            except Exception as e:
                logger.error(f"[Neo4j Graph Store] Relationship ingestion failed: {e}")
                raise ValueError(
                    f"Failed to ingest relationships into Neo4j: {e}. "
                    f"Entities were ingested successfully ({entities_created}), "
                    f"but {rels_created}/{len(relationship_rows)} relationships created."
                ) from e

        self.log(
            f"Ingested {entities_created} entities, "
            f"{rels_created} relationships into graph '{graph_kb_id}'."
        )
        return entities_created

    # ------------------------------------------------------------------
    # Compute and store entity embeddings (loops until all done)
    # ------------------------------------------------------------------

    def _embed_entities(self, driver) -> int:
        """Compute embeddings for all entities that don't have one yet."""
        if not self.embedding:
            self.log("No embedding model connected — skipping entity embedding.")
            return 0

        db = self._get_database()
        graph_kb_id = self.graph_kb_id or "default"
        total_embedded = 0

        while True:
            # Fetch next batch of entities without embeddings
            try:
                with driver.session(database=db) as session:
                    result = session.run(
                        """
                        MATCH (e:__Entity__ {graph_kb_id: $graph_kb_id})
                        WHERE e.embedding IS NULL
                        RETURN e.name AS name, e.description AS description, elementId(e) AS eid
                        LIMIT $batch_size
                        """,
                        graph_kb_id=graph_kb_id,
                        batch_size=_EMBED_BATCH_SIZE,
                    )
                    records = [dict(r) for r in result]
            except Exception as e:
                logger.warning(f"[Neo4j Graph Store] Failed to fetch entities for embedding: {e}")
                break

            if not records:
                break

            # Build text for embedding: "name: description"
            texts = [
                f"{r['name']}: {r.get('description', '')}" for r in records
            ]

            try:
                embeddings = self.embedding.embed_documents(texts)
            except Exception as e:
                logger.error(f"[Neo4j Graph Store] Embedding computation failed: {e}")
                raise ValueError(
                    f"Embedding model failed to embed {len(texts)} entities: {e}"
                ) from e

            # Store embeddings back
            rows = [
                {"eid": records[i]["eid"], "embedding": embeddings[i]}
                for i in range(len(records))
            ]
            try:
                with driver.session(database=db) as session:
                    session.run(
                        """
                        UNWIND $rows AS row
                        MATCH (e) WHERE elementId(e) = row.eid
                        SET e.embedding = row.embedding
                        """,
                        rows=rows,
                    )
            except Exception as e:
                logger.error(f"[Neo4j Graph Store] Failed to store embeddings: {e}")
                break

            total_embedded += len(rows)
            self.log(f"Embedded {total_embedded} entities so far...")

            # If we got fewer than batch size, we're done
            if len(records) < _EMBED_BATCH_SIZE:
                break

        if total_embedded > 0:
            self._ensure_vector_index(driver)
            self.log(f"Embedding complete: {total_embedded} entities embedded.")
        return total_embedded

    def _ensure_vector_index(self, driver) -> None:
        """Create the vector index on __Entity__.embedding if it doesn't exist."""
        db = self._get_database()
        try:
            # Detect embedding dimension from the first embedded entity
            with driver.session(database=db) as session:
                result = session.run(
                    """
                    MATCH (e:__Entity__)
                    WHERE e.embedding IS NOT NULL
                    RETURN size(e.embedding) AS dim
                    LIMIT 1
                    """
                )
                rec = result.single()
                if not rec:
                    return
                dim = rec["dim"]

            with driver.session(database=db) as session:
                session.run(
                    "CREATE VECTOR INDEX graph_entity_embedding IF NOT EXISTS "
                    "FOR (e:__Entity__) ON (e.embedding) "
                    "OPTIONS {indexConfig: {`vector.dimensions`: $dim, `vector.similarity_function`: 'cosine'}}",
                    dim=dim,
                )
            self.log(f"Vector index 'graph_entity_embedding' ensured (dim={dim}).")
        except Exception as e:
            logger.warning(f"[Neo4j Graph Store] Could not create vector index: {e}")
            self.log(f"Warning: Could not auto-create vector index: {e}. "
                     f"You may need to create it manually.")

    # ------------------------------------------------------------------
    # Search: Vector Similarity
    # ------------------------------------------------------------------

    def _vector_search(self, driver, query: str) -> list[Data]:
        """Vector similarity search on entity embeddings + graph expansion."""
        if not self.embedding:
            self.log("No embedding model connected — cannot perform vector search.")
            return []

        db = self._get_database()
        graph_kb_id = self.graph_kb_id or "default"
        top_k = max(1, self.number_of_results or 10)
        hops = max(1, min(self.expansion_hops or 2, 3))  # Clamp 1-3

        # Embed the query
        try:
            query_embedding = self.embedding.embed_query(query)
        except Exception as e:
            logger.error(f"[Neo4j Graph Store] Failed to embed query: {e}")
            raise ValueError(f"Failed to embed search query: {e}") from e

        # Vector search + subgraph expansion
        cypher = f"""
            CALL db.index.vector.queryNodes('graph_entity_embedding', $top_k, $embedding)
            YIELD node AS entity, score
            WHERE entity.graph_kb_id = $graph_kb_id

            // Expand neighborhood
            OPTIONAL MATCH path = (entity)-[r:RELATED_TO*1..{hops}]-(neighbor)
            WHERE neighbor.graph_kb_id = $graph_kb_id

            // Optionally get source chunks
            OPTIONAL MATCH (chunk:__Chunk__)-[:MENTIONS]->(entity)
            WHERE chunk.graph_kb_id = $graph_kb_id

            RETURN
                entity.name AS entity_name,
                entity.type AS entity_type,
                entity.description AS entity_description,
                score,
                collect(DISTINCT {{
                    name: neighbor.name,
                    type: neighbor.type,
                    relationship: type(r[0]),
                    description: neighbor.description
                }})[0..10] AS neighbors,
                collect(DISTINCT chunk.text)[0..3] AS source_chunks
            ORDER BY score DESC
            LIMIT $top_k
        """

        results = []
        try:
            with driver.session(database=db) as session:
                records = session.run(
                    cypher,
                    embedding=query_embedding,
                    top_k=top_k,
                    graph_kb_id=graph_kb_id,
                )
                for record in records:
                    rec = dict(record)
                    context_parts = [
                        f"**{rec['entity_name']}** ({rec['entity_type']})",
                        rec.get("entity_description") or "",
                    ]

                    neighbors = rec.get("neighbors") or []
                    valid_neighbors = [n for n in neighbors if n and n.get("name")]
                    if valid_neighbors:
                        context_parts.append("\nRelated entities:")
                        for n in valid_neighbors[:5]:
                            context_parts.append(
                                f"  - {n.get('name')} ({n.get('type', '')}) "
                                f"[{n.get('relationship', 'RELATED_TO')}]"
                            )

                    if self.include_source_chunks:
                        chunks = rec.get("source_chunks") or []
                        valid_chunks = [c for c in chunks if c]
                        if valid_chunks:
                            context_parts.append("\nSource text:")
                            for c in valid_chunks:
                                context_parts.append(f"  {c[:500]}")

                    text = "\n".join(context_parts)
                    results.append(Data(
                        text=text,
                        data={
                            "entity_name": rec["entity_name"],
                            "entity_type": rec["entity_type"],
                            "entity_description": rec.get("entity_description", ""),
                            "score": round(rec.get("score", 0), 4),
                            "neighbors": valid_neighbors,
                            "source_chunks": rec.get("source_chunks") or [],
                            "search_type": "vector_similarity",
                            "graph_kb_id": graph_kb_id,
                        },
                    ))
        except Exception as e:
            error_msg = str(e)
            # Gracefully handle missing vector index
            if "graph_entity_embedding" in error_msg or "index" in error_msg.lower():
                logger.warning(
                    f"[Neo4j Graph Store] Vector index not found. "
                    f"Falling back to keyword search. Error: {e}"
                )
                self.log(
                    "Vector index 'graph_entity_embedding' not found. "
                    "Falling back to keyword search. Create the index with: "
                    "CALL db.index.vector.createNodeIndex('graph_entity_embedding', "
                    "'__Entity__', 'embedding', 1536, 'cosine')"
                )
                return self._keyword_search(driver, query)
            raise ValueError(f"Neo4j vector search failed: {e}") from e

        return results

    # ------------------------------------------------------------------
    # Search: Keyword
    # ------------------------------------------------------------------

    @staticmethod
    def _tokenize_query(query: str) -> list[str]:
        """Tokenize a query into searchable terms.

        Uses regex to extract alphabetic tokens of 3+ characters.
        No hardcoded stop-word lists — relies on token-overlap scoring
        against entity names/descriptions to rank relevance naturally.
        Short tokens (< 3 chars) are dropped as they produce excessive
        false positives regardless of language.
        """
        import re

        tokens = re.findall(r"[a-zA-Z]{3,}", query.lower())
        # Deduplicate while preserving order
        seen: set[str] = set()
        unique: list[str] = []
        for t in tokens:
            if t not in seen:
                seen.add(t)
                unique.append(t)
        return unique

    def _keyword_search(self, driver, query: str) -> list[Data]:
        """Full-text keyword search with graph expansion.

        Matches entity names and descriptions against query tokens,
        then expands the subgraph (neighbors + source chunks) using
        the same strategy as ``_vector_search`` so both search types
        return identically structured results.
        """
        db = self._get_database()
        graph_kb_id = self.graph_kb_id or "default"
        top_k = max(1, self.number_of_results or 10)
        hops = max(1, min(self.expansion_hops or 2, 3))

        tokens = self._tokenize_query(query)
        if not tokens:
            tokens = [query.strip().lower()]

        cypher = f"""
            MATCH (e:__Entity__ {{graph_kb_id: $graph_kb_id}})
            WITH e,
                 toLower(e.name) AS name_lower,
                 toLower(coalesce(e.description, '')) AS desc_lower
            WITH e, name_lower, desc_lower,
                 [t IN $tokens WHERE name_lower CONTAINS t
                                  OR desc_lower CONTAINS t] AS matched
            WHERE size(matched) > 0
            WITH e,
                 toFloat(size(matched)) / toFloat(size($tokens)) AS score

            // Expand neighborhood (mirrors vector search)
            OPTIONAL MATCH path = (e)-[r:RELATED_TO*1..{hops}]-(neighbor)
            WHERE neighbor.graph_kb_id = $graph_kb_id

            // Source chunks
            OPTIONAL MATCH (chunk:__Chunk__)-[:MENTIONS]->(e)
            WHERE chunk.graph_kb_id = $graph_kb_id

            RETURN
                e.name        AS entity_name,
                e.type        AS entity_type,
                e.description AS entity_description,
                score,
                collect(DISTINCT {{
                    name: neighbor.name,
                    type: neighbor.type,
                    relationship: type(r[0]),
                    description: neighbor.description
                }})[0..10] AS neighbors,
                collect(DISTINCT chunk.text)[0..3] AS source_chunks
            ORDER BY score DESC, e.name
            LIMIT $top_k
        """

        results: list[Data] = []
        try:
            with driver.session(database=db) as session:
                records = session.run(
                    cypher,
                    tokens=tokens,
                    graph_kb_id=graph_kb_id,
                    top_k=top_k,
                )
                for record in records:
                    rec = dict(record)
                    context_parts = [
                        f"**{rec['entity_name']}** ({rec['entity_type']})",
                        rec.get("entity_description") or "",
                    ]

                    neighbors = rec.get("neighbors") or []
                    valid_neighbors = [n for n in neighbors if n and n.get("name")]
                    if valid_neighbors:
                        context_parts.append("\nRelated entities:")
                        for n in valid_neighbors[:5]:
                            context_parts.append(
                                f"  - {n.get('name')} ({n.get('type', '')}) "
                                f"[{n.get('relationship', 'RELATED_TO')}]"
                            )

                    if self.include_source_chunks:
                        chunks = rec.get("source_chunks") or []
                        valid_chunks = [c for c in chunks if c]
                        if valid_chunks:
                            context_parts.append("\nSource text:")
                            for c in valid_chunks:
                                context_parts.append(f"  {c[:500]}")

                    text = "\n".join(context_parts)
                    results.append(Data(
                        text=text,
                        data={
                            "entity_name": rec["entity_name"],
                            "entity_type": rec["entity_type"],
                            "entity_description": rec.get("entity_description", ""),
                            "score": round(rec.get("score", 0), 4),
                            "neighbors": valid_neighbors,
                            "source_chunks": rec.get("source_chunks") or [],
                            "search_type": "keyword",
                            "graph_kb_id": graph_kb_id,
                        },
                    ))
                return results
        except Exception as e:
            raise ValueError(f"Neo4j keyword search failed: {e}") from e

    # ------------------------------------------------------------------
    # Output: search_graph
    # ------------------------------------------------------------------

    def search_graph(self) -> list[Data]:
        """Main search method -- ingest first (if data provided), then search."""
        driver = self._get_driver()

        try:
            # Ingest entities if provided
            if self.ingest_data:
                count = self._ingest_entities(driver)
                if count > 0:
                    self._embed_entities(driver)

            # Resolve and validate search query
            query = self._resolve_search_query()
            if not query:
                self.status = "No search query provided."
                return []

            self.log(f"Searching graph with: '{query}' (type={self.search_type})")

            search_type = (self.search_type or "Vector Similarity").lower()
            if "keyword" in search_type:
                results = self._keyword_search(driver, query)
            elif "hybrid" in search_type:
                vec_results = self._vector_search(driver, query)
                kw_results = self._keyword_search(driver, query)
                # Deduplicate by entity_name, keeping vector results first (higher quality)
                seen: set[str] = set()
                results = []
                for r in vec_results + kw_results:
                    name = r.data.get("entity_name", "")
                    if name and name not in seen:
                        seen.add(name)
                        results.append(r)
            else:
                results = self._vector_search(driver, query)

            self.status = (
                f"{len(results)} result(s) | search={self.search_type} "
                f"| graph={self.graph_kb_id}"
            )
            return results

        finally:
            driver.close()

    # ------------------------------------------------------------------
    # Output: as_dataframe
    # ------------------------------------------------------------------

    def as_dataframe(self):
        """Return search results as a DataFrame."""
        from agentcore.schema.dataframe import DataFrame

        results = self.search_graph()
        return DataFrame(results)

    # ------------------------------------------------------------------
    # Output: get_stats
    # ------------------------------------------------------------------

    def get_stats(self) -> Data:
        """Return live graph statistics from Neo4j."""
        driver = self._get_driver()
        db = self._get_database()
        graph_kb_id = self.graph_kb_id or "default"

        try:
            with driver.session(database=db) as session:
                result = session.run(
                    """
                    MATCH (e:__Entity__ {graph_kb_id: $graph_kb_id})
                    WITH count(e) AS node_count
                    OPTIONAL MATCH (:__Entity__ {graph_kb_id: $graph_kb_id})
                            -[r:RELATED_TO]->()
                    WITH node_count, count(r) AS edge_count
                    OPTIONAL MATCH (c:__Community__ {graph_kb_id: $graph_kb_id})
                    RETURN node_count, edge_count, count(c) AS community_count
                    """,
                    graph_kb_id=graph_kb_id,
                )
                rec = result.single()
                stats = dict(rec) if rec else {
                    "node_count": 0, "edge_count": 0, "community_count": 0
                }

            stats["graph_kb_id"] = graph_kb_id
            self.status = (
                f"Nodes: {stats['node_count']} | "
                f"Edges: {stats['edge_count']} | "
                f"Communities: {stats['community_count']}"
            )
            return Data(data=stats)
        except Exception as e:
            raise ValueError(f"Failed to fetch graph stats from Neo4j: {e}") from e
        finally:
            driver.close()
