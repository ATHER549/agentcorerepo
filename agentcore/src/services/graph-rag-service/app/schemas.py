"""Pydantic schemas for the Graph RAG microservice API."""

from __future__ import annotations

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Entity / Relationship primitives
# ---------------------------------------------------------------------------


class RelationshipItem(BaseModel):
    target: str
    target_type: str = "Entity"
    type: str = "RELATED_TO"
    description: str = Field(default="", max_length=5000)
    weight: float = Field(default=1.0, ge=0.0, le=1.0)


class EntityItem(BaseModel):
    name: str = Field(..., min_length=1, max_length=1000)
    type: str = "Entity"
    description: str = Field(default="", max_length=10000)
    relationships: list[RelationshipItem] = Field(default_factory=list, max_length=500)
    source_chunk_id: str | None = None
    source_chunk_ids: list[str] = Field(default_factory=list)
    graph_kb_id: str = "default"
    id: str | None = None
    aliases: list[str] = Field(default_factory=list)
    importance: float | None = None


# ---------------------------------------------------------------------------
# Ingest
# ---------------------------------------------------------------------------


class IngestRequest(BaseModel):
    entities: list[EntityItem] = Field(..., max_length=5000)
    graph_kb_id: str = Field(default="default", min_length=1, max_length=256)


class IngestResponse(BaseModel):
    entities_created: int
    relationships_created: int
    graph_kb_id: str


# ---------------------------------------------------------------------------
# Embed entities
# ---------------------------------------------------------------------------


class EmbedEntitiesRequest(BaseModel):
    graph_kb_id: str = "default"
    embeddings: list[EntityEmbeddingPair]


class EntityEmbeddingPair(BaseModel):
    element_id: str
    embedding: list[float]


# Fix forward reference
EmbedEntitiesRequest.model_rebuild()


class EmbedEntitiesResponse(BaseModel):
    entities_embedded: int
    graph_kb_id: str


class FetchUnembeddedRequest(BaseModel):
    graph_kb_id: str = "default"
    batch_size: int = Field(default=200, ge=1, le=1000)


class UnembeddedEntity(BaseModel):
    name: str
    description: str
    element_id: str


class FetchUnembeddedResponse(BaseModel):
    entities: list[UnembeddedEntity]


# ---------------------------------------------------------------------------
# Ensure vector index
# ---------------------------------------------------------------------------


class EnsureVectorIndexRequest(BaseModel):
    graph_kb_id: str = "default"


class EnsureVectorIndexResponse(BaseModel):
    success: bool
    dimension: int | None = None
    message: str = ""


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=10000)
    query_embedding: list[float] | None = None
    graph_kb_id: str = Field(default="default", min_length=1, max_length=256)
    search_type: str = "vector_similarity"
    number_of_results: int = Field(default=10, ge=1, le=100)
    expansion_hops: int = Field(default=2, ge=1, le=3)
    include_source_chunks: bool = True


class SearchResultItem(BaseModel):
    text: str
    entity_name: str
    entity_type: str
    entity_description: str = ""
    score: float = 0.0
    neighbors: list[dict] = Field(default_factory=list)
    source_chunks: list[str] = Field(default_factory=list)
    search_type: str = "vector_similarity"
    graph_kb_id: str = "default"


class SearchResponse(BaseModel):
    results: list[SearchResultItem]
    search_type: str
    graph_kb_id: str


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------


class StatsRequest(BaseModel):
    graph_kb_id: str = "default"


class StatsResponse(BaseModel):
    node_count: int = 0
    edge_count: int = 0
    community_count: int = 0
    graph_kb_id: str = "default"


# ---------------------------------------------------------------------------
# Community detection
# ---------------------------------------------------------------------------


class CommunityDetectRequest(BaseModel):
    graph_kb_id: str = "default"
    max_communities: int = Field(default=10, ge=1, le=50)
    min_community_size: int = Field(default=2, ge=2, le=100)
    community_summaries: list[CommunitySummaryInput] | None = None


class CommunitySummaryInput(BaseModel):
    community_id: str
    title: str
    summary: str
    members: list[str] = Field(default_factory=list)
    node_count: int = 0


# Fix forward reference
CommunityDetectRequest.model_rebuild()


class CommunityItem(BaseModel):
    community_id: str
    title: str = ""
    summary: str = ""
    node_count: int = 0
    members: list[str] = Field(default_factory=list)
    descriptions: list[str] = Field(default_factory=list)
    types: list[str] = Field(default_factory=list)
    graph_kb_id: str = "default"
    needs_summary: bool = False


class CommunityDetectResponse(BaseModel):
    communities: list[CommunityItem]


class StoreCommunityRequest(BaseModel):
    graph_kb_id: str = "default"
    communities: list[CommunitySummaryInput]


class StoreCommunityResponse(BaseModel):
    stored: int


# ---------------------------------------------------------------------------
# Test connection
# ---------------------------------------------------------------------------


class TestConnectionRequest(BaseModel):
    neo4j_uri: str | None = None
    neo4j_username: str | None = None
    neo4j_password: str | None = None
    neo4j_database: str | None = None


class TestConnectionResponse(BaseModel):
    success: bool
    message: str
    node_count: int = 0
