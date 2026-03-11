"""Pydantic schemas for the Pinecone microservice API."""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class DocumentItem(BaseModel):
    page_content: str
    metadata: dict = Field(default_factory=dict)


class IngestRequest(BaseModel):
    index_name: str = Field(..., min_length=1, max_length=128, pattern=r"^[a-z0-9][a-z0-9\-]*$")
    namespace: str = Field(default="", max_length=256)
    text_key: str = "text"
    documents: list[DocumentItem] = Field(..., max_length=10000)
    embedding_vectors: list[list[float]] = Field(..., max_length=10000)
    auto_create_index: bool = True
    embedding_dimension: int = Field(default=768, ge=1, le=20000)
    cloud_provider: str = "aws"
    cloud_region: str = "us-east-1"
    use_hybrid_search: bool = False
    sparse_model: str = "pinecone-sparse-english-v0"

    @field_validator("embedding_vectors")
    @classmethod
    def vectors_match_documents(cls, v, info):
        docs = info.data.get("documents")
        if docs is not None and len(v) != len(docs):
            raise ValueError(f"embedding_vectors length ({len(v)}) must match documents length ({len(docs)})")
        return v


class IngestResponse(BaseModel):
    vectors_upserted: int
    index_name: str
    namespace: str


class SearchRequest(BaseModel):
    index_name: str = Field(..., min_length=1, max_length=128)
    namespace: str = Field(default="", max_length=256)
    text_key: str = "text"
    query: str = Field(..., min_length=1, max_length=10000)
    query_embedding: list[float]
    number_of_results: int = Field(default=4, ge=1, le=100)
    use_hybrid_search: bool = False
    sparse_model: str = "pinecone-sparse-english-v0"
    hybrid_alpha: float = Field(default=0.7, ge=0.0, le=1.0)
    use_reranking: bool = False
    rerank_model: str = "pinecone-rerank-v0"
    rerank_top_n: int = Field(default=5, ge=1, le=100)


class SearchResultItem(BaseModel):
    text: str
    metadata: dict = Field(default_factory=dict)
    score: float = 0.0
    score_info: dict = Field(default_factory=dict)
    rank: int = 0


class SearchResponse(BaseModel):
    results: list[SearchResultItem]
    search_method: str
    rerank_info: str = "disabled"


class EnsureIndexRequest(BaseModel):
    index_name: str = Field(..., min_length=1, max_length=128, pattern=r"^[a-z0-9][a-z0-9\-]*$")
    embedding_dimension: int = Field(default=768, ge=1, le=20000)
    cloud_provider: str = "aws"
    cloud_region: str = "us-east-1"


class EnsureIndexResponse(BaseModel):
    exists: bool
    created: bool
    index_name: str


class TestConnectionRequest(BaseModel):
    pinecone_api_key: str | None = None


class TestConnectionResponse(BaseModel):
    success: bool
    message: str
    indexes: list[str] = Field(default_factory=list)
