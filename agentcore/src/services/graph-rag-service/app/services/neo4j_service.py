"""Core Neo4j graph operations — ingest, embed, search, community, stats."""

from __future__ import annotations

import hashlib
import logging
import re
from collections import defaultdict
from uuid import uuid4

from app.config import get_settings
from app.schemas import (
    CommunityDetectRequest,
    CommunityDetectResponse,
    CommunityItem,
    EmbedEntitiesRequest,
    EmbedEntitiesResponse,
    EnsureVectorIndexRequest,
    EnsureVectorIndexResponse,
    FetchUnembeddedRequest,
    FetchUnembeddedResponse,
    IngestRequest,
    IngestResponse,
    SearchRequest,
    SearchResponse,
    SearchResultItem,
    StatsRequest,
    StatsResponse,
    StoreCommunityRequest,
    StoreCommunityResponse,
    TestConnectionRequest,
    TestConnectionResponse,
    UnembeddedEntity,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Singleton driver
# ---------------------------------------------------------------------------

_driver = None


def get_driver():
    """Return the singleton Neo4j driver, creating it on first call."""
    global _driver
    if _driver is not None:
        return _driver

    from neo4j import GraphDatabase

    settings = get_settings()
    if not settings.neo4j_uri:
        raise ValueError(
            "Neo4j URI is required. Set NEO4J_URI or GRAPH_RAG_SERVICE_NEO4J_URI in .env."
        )

    _driver = GraphDatabase.driver(
        settings.neo4j_uri,
        auth=(settings.neo4j_username, settings.neo4j_password),
    )
    _driver.verify_connectivity()
    logger.info("Neo4j driver connected to %s", settings.neo4j_uri)
    return _driver


def close_driver():
    """Close the singleton driver (called on shutdown)."""
    global _driver
    if _driver is not None:
        _driver.close()
        _driver = None
        logger.info("Neo4j driver closed")


def _get_driver_for_test(uri: str | None = None, username: str | None = None, password: str | None = None):
    """Create a temporary driver for test-connection with custom credentials."""
    if not uri and not username and not password:
        return get_driver()

    from neo4j import GraphDatabase

    settings = get_settings()
    _uri = uri or settings.neo4j_uri
    _user = username or settings.neo4j_username
    _pwd = password or settings.neo4j_password

    if not _uri:
        raise ValueError("Neo4j URI is required.")

    driver = GraphDatabase.driver(_uri, auth=(_user, _pwd))
    driver.verify_connectivity()
    return driver


def _get_database(db: str | None = None) -> str:
    return db or get_settings().neo4j_database


# ---------------------------------------------------------------------------
# Cypher templates for variable-length paths (hops)
# Neo4j does not support parameterised path lengths, so we use a
# pre-validated integer inserted into a template dict.
# ---------------------------------------------------------------------------

_VECTOR_SEARCH_TEMPLATES = {
    1: """
        CALL db.index.vector.queryNodes('graph_entity_embedding', $top_k, $embedding)
        YIELD node AS entity, score
        WHERE entity.graph_kb_id = $graph_kb_id

        OPTIONAL MATCH path = (entity)-[r:RELATED_TO*1..1]-(neighbor)
        WHERE neighbor.graph_kb_id = $graph_kb_id

        OPTIONAL MATCH (chunk:__Chunk__)-[:MENTIONS]->(entity)
        WHERE chunk.graph_kb_id = $graph_kb_id

        RETURN
            entity.name AS entity_name,
            entity.type AS entity_type,
            entity.description AS entity_description,
            score,
            collect(DISTINCT {
                name: neighbor.name,
                type: neighbor.type,
                relationship: type(r[0]),
                description: neighbor.description
            })[0..10] AS neighbors,
            collect(DISTINCT chunk.text)[0..3] AS source_chunks
        ORDER BY score DESC
        LIMIT $top_k
    """,
    2: """
        CALL db.index.vector.queryNodes('graph_entity_embedding', $top_k, $embedding)
        YIELD node AS entity, score
        WHERE entity.graph_kb_id = $graph_kb_id

        OPTIONAL MATCH path = (entity)-[r:RELATED_TO*1..2]-(neighbor)
        WHERE neighbor.graph_kb_id = $graph_kb_id

        OPTIONAL MATCH (chunk:__Chunk__)-[:MENTIONS]->(entity)
        WHERE chunk.graph_kb_id = $graph_kb_id

        RETURN
            entity.name AS entity_name,
            entity.type AS entity_type,
            entity.description AS entity_description,
            score,
            collect(DISTINCT {
                name: neighbor.name,
                type: neighbor.type,
                relationship: type(r[0]),
                description: neighbor.description
            })[0..10] AS neighbors,
            collect(DISTINCT chunk.text)[0..3] AS source_chunks
        ORDER BY score DESC
        LIMIT $top_k
    """,
    3: """
        CALL db.index.vector.queryNodes('graph_entity_embedding', $top_k, $embedding)
        YIELD node AS entity, score
        WHERE entity.graph_kb_id = $graph_kb_id

        OPTIONAL MATCH path = (entity)-[r:RELATED_TO*1..3]-(neighbor)
        WHERE neighbor.graph_kb_id = $graph_kb_id

        OPTIONAL MATCH (chunk:__Chunk__)-[:MENTIONS]->(entity)
        WHERE chunk.graph_kb_id = $graph_kb_id

        RETURN
            entity.name AS entity_name,
            entity.type AS entity_type,
            entity.description AS entity_description,
            score,
            collect(DISTINCT {
                name: neighbor.name,
                type: neighbor.type,
                relationship: type(r[0]),
                description: neighbor.description
            })[0..10] AS neighbors,
            collect(DISTINCT chunk.text)[0..3] AS source_chunks
        ORDER BY score DESC
        LIMIT $top_k
    """,
}

_KEYWORD_SEARCH_TEMPLATES = {
    1: """
        MATCH (e:__Entity__ {graph_kb_id: $graph_kb_id})
        WITH e,
             toLower(e.name) AS name_lower,
             toLower(coalesce(e.description, '')) AS desc_lower
        WITH e, name_lower, desc_lower,
             [t IN $tokens WHERE name_lower CONTAINS t
                              OR desc_lower CONTAINS t] AS matched
        WHERE size(matched) > 0
        WITH e,
             toFloat(size(matched)) / toFloat(size($tokens)) AS score

        OPTIONAL MATCH path = (e)-[r:RELATED_TO*1..1]-(neighbor)
        WHERE neighbor.graph_kb_id = $graph_kb_id

        OPTIONAL MATCH (chunk:__Chunk__)-[:MENTIONS]->(e)
        WHERE chunk.graph_kb_id = $graph_kb_id

        RETURN
            e.name        AS entity_name,
            e.type        AS entity_type,
            e.description AS entity_description,
            score,
            collect(DISTINCT {
                name: neighbor.name,
                type: neighbor.type,
                relationship: type(r[0]),
                description: neighbor.description
            })[0..10] AS neighbors,
            collect(DISTINCT chunk.text)[0..3] AS source_chunks
        ORDER BY score DESC, e.name
        LIMIT $top_k
    """,
    2: """
        MATCH (e:__Entity__ {graph_kb_id: $graph_kb_id})
        WITH e,
             toLower(e.name) AS name_lower,
             toLower(coalesce(e.description, '')) AS desc_lower
        WITH e, name_lower, desc_lower,
             [t IN $tokens WHERE name_lower CONTAINS t
                              OR desc_lower CONTAINS t] AS matched
        WHERE size(matched) > 0
        WITH e,
             toFloat(size(matched)) / toFloat(size($tokens)) AS score

        OPTIONAL MATCH path = (e)-[r:RELATED_TO*1..2]-(neighbor)
        WHERE neighbor.graph_kb_id = $graph_kb_id

        OPTIONAL MATCH (chunk:__Chunk__)-[:MENTIONS]->(e)
        WHERE chunk.graph_kb_id = $graph_kb_id

        RETURN
            e.name        AS entity_name,
            e.type        AS entity_type,
            e.description AS entity_description,
            score,
            collect(DISTINCT {
                name: neighbor.name,
                type: neighbor.type,
                relationship: type(r[0]),
                description: neighbor.description
            })[0..10] AS neighbors,
            collect(DISTINCT chunk.text)[0..3] AS source_chunks
        ORDER BY score DESC, e.name
        LIMIT $top_k
    """,
    3: """
        MATCH (e:__Entity__ {graph_kb_id: $graph_kb_id})
        WITH e,
             toLower(e.name) AS name_lower,
             toLower(coalesce(e.description, '')) AS desc_lower
        WITH e, name_lower, desc_lower,
             [t IN $tokens WHERE name_lower CONTAINS t
                              OR desc_lower CONTAINS t] AS matched
        WHERE size(matched) > 0
        WITH e,
             toFloat(size(matched)) / toFloat(size($tokens)) AS score

        OPTIONAL MATCH path = (e)-[r:RELATED_TO*1..3]-(neighbor)
        WHERE neighbor.graph_kb_id = $graph_kb_id

        OPTIONAL MATCH (chunk:__Chunk__)-[:MENTIONS]->(e)
        WHERE chunk.graph_kb_id = $graph_kb_id

        RETURN
            e.name        AS entity_name,
            e.type        AS entity_type,
            e.description AS entity_description,
            score,
            collect(DISTINCT {
                name: neighbor.name,
                type: neighbor.type,
                relationship: type(r[0]),
                description: neighbor.description
            })[0..10] AS neighbors,
            collect(DISTINCT chunk.text)[0..3] AS source_chunks
        ORDER BY score DESC, e.name
        LIMIT $top_k
    """,
}


# ---------------------------------------------------------------------------
# Ingest entities
# ---------------------------------------------------------------------------


def ingest_entities(req: IngestRequest) -> IngestResponse:
    driver = get_driver()
    db = _get_database()
    graph_kb_id = req.graph_kb_id or "default"
    batch_size = get_settings().ingest_batch_size

    entity_rows = []
    relationship_rows = []

    for item in req.entities:
        entity_name = item.name.strip()
        if not entity_name:
            continue

        entity_rows.append({
            "id": item.id or str(uuid4()),
            "name": entity_name,
            "type": item.type.strip() or "Entity",
            "description": (item.description or "")[:5000],
            "graph_kb_id": graph_kb_id,
            "source_chunk_id": item.source_chunk_id,
        })

        for rel in item.relationships:
            target = rel.target.strip()
            if not target:
                continue
            weight = max(0.0, min(rel.weight, 1.0))
            relationship_rows.append({
                "source_name": entity_name,
                "target_name": target,
                "target_type": (rel.target_type or "Entity").strip(),
                "rel_type": (rel.type or "RELATED_TO").strip(),
                "description": (rel.description or "")[:2000],
                "weight": weight,
                "graph_kb_id": graph_kb_id,
            })

    if not entity_rows:
        return IngestResponse(entities_created=0, relationships_created=0, graph_kb_id=graph_kb_id)

    entities_created = 0
    for i in range(0, len(entity_rows), batch_size):
        batch = entity_rows[i : i + batch_size]
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

    rels_created = 0
    if relationship_rows:
        for i in range(0, len(relationship_rows), batch_size):
            batch = relationship_rows[i : i + batch_size]
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

    return IngestResponse(
        entities_created=entities_created,
        relationships_created=rels_created,
        graph_kb_id=graph_kb_id,
    )


# ---------------------------------------------------------------------------
# Fetch unembedded entities
# ---------------------------------------------------------------------------


def fetch_unembedded(req: FetchUnembeddedRequest) -> FetchUnembeddedResponse:
    driver = get_driver()
    db = _get_database()
    with driver.session(database=db) as session:
        result = session.run(
            """
            MATCH (e:__Entity__ {graph_kb_id: $graph_kb_id})
            WHERE e.embedding IS NULL
            RETURN e.name AS name, e.description AS description, elementId(e) AS eid
            LIMIT $batch_size
            """,
            graph_kb_id=req.graph_kb_id,
            batch_size=req.batch_size,
        )
        entities = [
            UnembeddedEntity(
                name=r["name"],
                description=r.get("description") or "",
                element_id=r["eid"],
            )
            for r in result
        ]
    return FetchUnembeddedResponse(entities=entities)


# ---------------------------------------------------------------------------
# Store entity embeddings
# ---------------------------------------------------------------------------


def store_embeddings(req: EmbedEntitiesRequest) -> EmbedEntitiesResponse:
    driver = get_driver()
    db = _get_database()
    rows = [{"eid": p.element_id, "embedding": p.embedding} for p in req.embeddings]
    with driver.session(database=db) as session:
        session.run(
            """
            UNWIND $rows AS row
            MATCH (e) WHERE elementId(e) = row.eid
            SET e.embedding = row.embedding
            """,
            rows=rows,
        )
    return EmbedEntitiesResponse(
        entities_embedded=len(rows),
        graph_kb_id=req.graph_kb_id,
    )


# ---------------------------------------------------------------------------
# Ensure vector index
# ---------------------------------------------------------------------------


def ensure_vector_index(req: EnsureVectorIndexRequest) -> EnsureVectorIndexResponse:
    driver = get_driver()
    db = _get_database()
    try:
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
                return EnsureVectorIndexResponse(success=False, message="No embedded entities found")
            dim = rec["dim"]

        with driver.session(database=db) as session:
            session.run(
                "CREATE VECTOR INDEX graph_entity_embedding IF NOT EXISTS "
                "FOR (e:__Entity__) ON (e.embedding) "
                "OPTIONS {indexConfig: {`vector.dimensions`: $dim, `vector.similarity_function`: 'cosine'}}",
                dim=dim,
            )
        return EnsureVectorIndexResponse(success=True, dimension=dim, message="Vector index ensured")
    except Exception as e:
        logger.error("ensure_vector_index failed: %s", e)
        return EnsureVectorIndexResponse(success=False, message=str(e))


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------


def search_graph(req: SearchRequest) -> SearchResponse:
    search_type = (req.search_type or "vector_similarity").lower()

    if "keyword" in search_type:
        results = _keyword_search(req)
    elif "hybrid" in search_type:
        vec_results = _vector_search(req) if req.query_embedding else []
        kw_results = _keyword_search(req)
        seen: set[str] = set()
        results = []
        for r in vec_results + kw_results:
            if r.entity_name not in seen:
                seen.add(r.entity_name)
                results.append(r)
    else:
        if not req.query_embedding:
            results = _keyword_search(req)
        else:
            results = _vector_search(req)

    return SearchResponse(
        results=results,
        search_type=search_type,
        graph_kb_id=req.graph_kb_id,
    )


def _build_result_item(rec: dict, search_type: str, graph_kb_id: str, include_source_chunks: bool) -> SearchResultItem:
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
                f"  - {n.get('name')} ({n.get('type', '')}) [{n.get('relationship', 'RELATED_TO')}]"
            )
    source_chunks = rec.get("source_chunks") or []
    if include_source_chunks:
        valid_chunks = [c for c in source_chunks if c]
        if valid_chunks:
            context_parts.append("\nSource text:")
            for c in valid_chunks:
                context_parts.append(f"  {c[:500]}")

    return SearchResultItem(
        text="\n".join(context_parts),
        entity_name=rec["entity_name"],
        entity_type=rec["entity_type"],
        entity_description=rec.get("entity_description") or "",
        score=round(rec.get("score", 0), 4),
        neighbors=valid_neighbors,
        source_chunks=source_chunks,
        search_type=search_type,
        graph_kb_id=graph_kb_id,
    )


def _vector_search(req: SearchRequest) -> list[SearchResultItem]:
    driver = get_driver()
    db = _get_database()
    graph_kb_id = req.graph_kb_id or "default"
    top_k = max(1, min(req.number_of_results or 10, 100))
    hops = max(1, min(req.expansion_hops or 2, 3))

    cypher = _VECTOR_SEARCH_TEMPLATES[hops]

    results: list[SearchResultItem] = []
    try:
        with driver.session(database=db) as session:
            records = session.run(
                cypher,
                embedding=req.query_embedding,
                top_k=top_k,
                graph_kb_id=graph_kb_id,
            )
            for record in records:
                rec = dict(record)
                results.append(_build_result_item(rec, "vector_similarity", graph_kb_id, req.include_source_chunks))
    except Exception as e:
        error_msg = str(e)
        if "graph_entity_embedding" in error_msg or "index" in error_msg.lower():
            logger.warning("Vector index not found, falling back to keyword search: %s", e)
            return _keyword_search(req)
        raise ValueError(f"Neo4j vector search failed: {e}") from e

    return results


def _tokenize_query(query: str) -> list[str]:
    tokens = re.findall(r"[a-zA-Z]{3,}", query.lower())
    seen: set[str] = set()
    unique: list[str] = []
    for t in tokens:
        if t not in seen:
            seen.add(t)
            unique.append(t)
    return unique


def _keyword_search(req: SearchRequest) -> list[SearchResultItem]:
    driver = get_driver()
    db = _get_database()
    graph_kb_id = req.graph_kb_id or "default"
    top_k = max(1, min(req.number_of_results or 10, 100))
    hops = max(1, min(req.expansion_hops or 2, 3))

    tokens = _tokenize_query(req.query)
    if not tokens:
        tokens = [req.query.strip().lower()]

    cypher = _KEYWORD_SEARCH_TEMPLATES[hops]

    results: list[SearchResultItem] = []
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
                results.append(_build_result_item(rec, "keyword", graph_kb_id, req.include_source_chunks))
    except Exception as e:
        raise ValueError(f"Neo4j keyword search failed: {e}") from e

    return results


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------


def get_stats(req: StatsRequest) -> StatsResponse:
    driver = get_driver()
    db = _get_database()
    graph_kb_id = req.graph_kb_id or "default"
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
        stats = dict(rec) if rec else {"node_count": 0, "edge_count": 0, "community_count": 0}
    return StatsResponse(
        node_count=stats["node_count"],
        edge_count=stats["edge_count"],
        community_count=stats["community_count"],
        graph_kb_id=graph_kb_id,
    )


# ---------------------------------------------------------------------------
# Community detection
# ---------------------------------------------------------------------------


def _community_hash(seed: str) -> str:
    return hashlib.sha256(seed.encode("utf-8", errors="replace")).hexdigest()[:12]


def detect_communities(req: CommunityDetectRequest) -> CommunityDetectResponse:
    driver = get_driver()
    db = _get_database()
    graph_kb_id = req.graph_kb_id or "default"
    max_communities = max(1, min(req.max_communities or 10, 50))
    min_community_size = max(2, req.min_community_size or 2)

    # Check for existing communities
    with driver.session(database=db) as session:
        existing = session.run(
            """
            MATCH (c:__Community__ {graph_kb_id: $graph_kb_id})
            RETURN c.id AS id, c.summary AS summary, c.title AS title,
                   c.node_count AS node_count, c.level AS level
            ORDER BY c.node_count DESC
            LIMIT $limit
            """,
            graph_kb_id=graph_kb_id,
            limit=max_communities,
        )
        existing_records = [dict(r) for r in existing]

    if existing_records:
        communities = [
            CommunityItem(
                community_id=rec["id"],
                title=rec.get("title") or "",
                summary=rec.get("summary") or "",
                node_count=rec.get("node_count") or 0,
                graph_kb_id=graph_kb_id,
            )
            for rec in existing_records
        ]
        return CommunityDetectResponse(communities=communities)

    # No existing — detect via Union-Find
    with driver.session(database=db) as session:
        edge_result = session.run(
            """
            MATCH (a:__Entity__ {graph_kb_id: $graph_kb_id})
                   -[:RELATED_TO]-
                  (b:__Entity__ {graph_kb_id: $graph_kb_id})
            RETURN DISTINCT a.name AS src, b.name AS tgt
            """,
            graph_kb_id=graph_kb_id,
        )
        edges = [(r["src"], r["tgt"]) for r in edge_result]

    with driver.session(database=db) as session:
        all_result = session.run(
            """
            MATCH (e:__Entity__ {graph_kb_id: $graph_kb_id})
            RETURN e.name AS name
            """,
            graph_kb_id=graph_kb_id,
        )
        all_names = [r["name"] for r in all_result]

    if not all_names:
        return CommunityDetectResponse(communities=[])

    # Union-Find
    parent: dict[str, str] = {n: n for n in all_names}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for src, tgt in edges:
        if src in parent and tgt in parent:
            union(src, tgt)

    components: dict[str, list[str]] = defaultdict(list)
    for name in all_names:
        components[find(name)].append(name)

    # Assign community IDs back to Neo4j
    for root, members in components.items():
        cid = _community_hash(root)
        with driver.session(database=db) as session:
            session.run(
                """
                UNWIND $members AS member_name
                MATCH (e:__Entity__ {name: member_name, graph_kb_id: $graph_kb_id})
                SET e.community_id = $cid
                """,
                members=members,
                graph_kb_id=graph_kb_id,
                cid=cid,
            )

    # Get community groupings
    with driver.session(database=db) as session:
        community_result = session.run(
            """
            MATCH (e:__Entity__ {graph_kb_id: $graph_kb_id})
            WHERE e.community_id IS NOT NULL
            WITH e.community_id AS cid,
                 collect(e.name) AS members,
                 collect(e.description) AS descriptions,
                 collect(e.type) AS types,
                 count(e) AS node_count
            WHERE node_count >= $min_size
            RETURN cid, members, descriptions, types, node_count
            ORDER BY node_count DESC
            LIMIT $limit
            """,
            graph_kb_id=graph_kb_id,
            limit=max_communities,
            min_size=min_community_size,
        )
        raw_communities = [dict(r) for r in community_result]

    communities = []
    for comm in raw_communities:
        communities.append(CommunityItem(
            community_id=comm["cid"],
            title=f"Community: {', '.join(comm.get('members', [])[:3])}",
            summary="",
            node_count=comm["node_count"],
            members=comm.get("members", [])[:20],
            descriptions=[d for d in comm.get("descriptions", []) if d and d.strip()][:10],
            types=list(set(t for t in comm.get("types", []) if t)),
            graph_kb_id=graph_kb_id,
            needs_summary=True,
        ))

    return CommunityDetectResponse(communities=communities)


# ---------------------------------------------------------------------------
# Store community summaries
# ---------------------------------------------------------------------------


def store_communities(req: StoreCommunityRequest) -> StoreCommunityResponse:
    driver = get_driver()
    db = _get_database()
    graph_kb_id = req.graph_kb_id or "default"
    stored = 0
    for comm in req.communities:
        with driver.session(database=db) as session:
            session.run(
                """
                MERGE (c:__Community__ {id: $cid, graph_kb_id: $graph_kb_id})
                SET c.title = $title,
                    c.summary = $summary,
                    c.node_count = $node_count,
                    c.level = 0
                WITH c
                UNWIND $members AS member_name
                MATCH (e:__Entity__ {name: member_name, graph_kb_id: $graph_kb_id})
                MERGE (c)-[:HAS_MEMBER]->(e)
                """,
                cid=comm.community_id,
                graph_kb_id=graph_kb_id,
                title=comm.title,
                summary=comm.summary,
                node_count=comm.node_count,
                members=comm.members,
            )
            stored += 1
    return StoreCommunityResponse(stored=stored)


# ---------------------------------------------------------------------------
# Test connection
# ---------------------------------------------------------------------------


def test_connection(req: TestConnectionRequest) -> TestConnectionResponse:
    try:
        driver = _get_driver_for_test(
            uri=req.neo4j_uri,
            username=req.neo4j_username,
            password=req.neo4j_password,
        )
        db = _get_database(req.neo4j_database)
        with driver.session(database=db) as session:
            result = session.run(
                "MATCH (n) RETURN count(n) AS cnt LIMIT 1"
            )
            rec = result.single()
            count = rec["cnt"] if rec else 0
        # Close only if it's a temporary driver (not the singleton)
        if driver is not _driver:
            driver.close()
        return TestConnectionResponse(
            success=True,
            message=f"Connected. {count} node(s) in database.",
            node_count=count,
        )
    except Exception as e:
        logger.warning("Neo4j test-connection failed: %s", e)
        return TestConnectionResponse(success=False, message=str(e))
