"""
Pinecone Vector Store Component

Delegates all Pinecone SDK operations to the pinecone-service microservice.
Embedding generation stays local (via the connected Embedding component).
"""

import time

import numpy as np
from langchain_core.vectorstores import VectorStore
from loguru import logger

from agentcore.base.vectorstores.model import LCVectorStoreNode, check_cached_vector_store
from agentcore.io import BoolInput, DropdownInput, HandleInput, IntInput, StrInput
from agentcore.schema.data import Data
from agentcore.schema.message import Message
from agentcore.services.pinecone_service_client import (
    ensure_index_via_service,
    ingest_via_service,
    search_via_service,
)


# ═══════════════════════════════════════════════════════════════

class PineconeVectorStoreNode(LCVectorStoreNode):
    display_name = "Pinecone"
    description = "Pinecone Vector Store with optional hybrid search and reranking"
    name = "Pinecone"
    icon = "Pinecone"
    inputs = [
        StrInput(name="index_name", display_name="Index Name", required=True),
        StrInput(name="namespace", display_name="Namespace", info="Namespace for the index."),
        StrInput(name="text_key", display_name="Text Key", value="text", advanced=True),
        *LCVectorStoreNode.inputs,
        HandleInput(name="embedding", display_name="Embedding", input_types=["Embeddings"]),
        BoolInput(name="auto_create_index", display_name="Auto Create Index", value=True),
        IntInput(name="embedding_dimension", display_name="Embedding Dimension", value=768),
        DropdownInput(name="cloud_provider", display_name="Cloud Provider",
                      options=["aws", "gcp", "azure"], value="aws", advanced=True),
        StrInput(name="cloud_region", display_name="Cloud Region", value="us-east-1", advanced=True),
        BoolInput(name="use_hybrid_search", display_name="Enable Hybrid Search", value=False,
                  info="Use dense + sparse vectors at RETRIEVAL time. Index must use dotproduct metric."),
        DropdownInput(name="sparse_model", display_name="Sparse Embedding Model",
                      options=["pinecone-sparse-english-v0"], value="pinecone-sparse-english-v0", advanced=True),
        StrInput(name="hybrid_alpha", display_name="Hybrid Alpha", value="0.7",
                 info="0.0 = pure sparse/keyword, 1.0 = pure dense/semantic", advanced=True),
        BoolInput(name="use_reranking", display_name="Enable Reranking", value=False),
        DropdownInput(name="rerank_model", display_name="Rerank Model",
                      options=["pinecone-rerank-v0", "bge-reranker-v2-m3", "cohere-rerank-3.5"],
                      value="pinecone-rerank-v0", advanced=True),
        IntInput(name="rerank_top_n", display_name="Rerank Top N", value=5, advanced=True),
        IntInput(name="number_of_results", display_name="Number of Results", value=4, advanced=True),
    ]

    # ══════════════════════════════════════════════════════════
    #  HELPERS
    # ══════════════════════════════════════════════════════════

    def _get_alpha(self) -> float:
        try:
            return float(self.hybrid_alpha)
        except (ValueError, TypeError):
            return 0.7

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

    # ══════════════════════════════════════════════════════════
    #  AUTO-CREATE INDEX via microservice
    # ══════════════════════════════════════════════════════════

    def _ensure_index_exists(self):
        if not self.auto_create_index:
            logger.info(f"[Pinecone] Auto-create disabled, assuming index '{self.index_name}' exists")
            return
        logger.info(f"[Pinecone] Ensuring index '{self.index_name}' via microservice...")
        result = ensure_index_via_service(
            index_name=self.index_name,
            embedding_dimension=self.embedding_dimension,
            cloud_provider=self.cloud_provider,
            cloud_region=self.cloud_region,
        )
        if result.get("created"):
            logger.info(f"[Pinecone] Index '{self.index_name}' created via microservice")
        else:
            logger.info(f"[Pinecone] Index '{self.index_name}' already exists")

    # ══════════════════════════════════════════════════════════
    #  EMBEDDING MODEL (stays local — from connected component)
    # ══════════════════════════════════════════════════════════

    def _get_embedding_model(self):
        emb = self.embedding
        if hasattr(emb, "build_embeddings"):
            model = emb.build_embeddings()
            if model is not None:
                return model
        if hasattr(emb, "build"):
            model = emb.build()
            if model and hasattr(model, "embed_documents"):
                return model
        if hasattr(emb, "embed_documents") and hasattr(emb, "embed_query"):
            return emb
        raise ValueError(
            "No valid embedding model provided. Please connect an Embedding component "
            "that implements embed_documents() and embed_query()."
        )

    # ══════════════════════════════════════════════════════════
    #  INGESTION via microservice
    # ══════════════════════════════════════════════════════════

    def _ingest_documents(self, documents, embedder):
        texts = [doc.page_content for doc in documents]
        logger.info(f"[Pinecone] Generating dense embeddings for {len(texts)} chunk(s)...")
        t0 = time.time()
        dense_embeddings = embedder.embed_documents(texts)
        logger.info(f"[Pinecone] Dense embeddings done in {time.time()-t0:.1f}s")

        doc_items = [
            {"page_content": doc.page_content, "metadata": dict(doc.metadata) if doc.metadata else {}}
            for doc in documents
        ]

        logger.info(f"[Pinecone] Ingesting {len(doc_items)} document(s) via microservice...")
        result = ingest_via_service(
            index_name=self.index_name,
            namespace=self.namespace or "",
            text_key=self.text_key,
            documents=doc_items,
            embedding_vectors=dense_embeddings,
            auto_create_index=self.auto_create_index,
            embedding_dimension=self.embedding_dimension,
            cloud_provider=self.cloud_provider,
            cloud_region=self.cloud_region,
            use_hybrid_search=self.use_hybrid_search,
            sparse_model=self.sparse_model,
        )
        count = result.get("vectors_upserted", 0)
        logger.info(f"[Pinecone] Microservice upserted {count} vectors")
        return count

    def _ingest_if_needed(self, wrapped_embeddings):
        self.ingest_data = self._prepare_ingest_data()
        if not self.ingest_data:
            return 0
        from langchain_core.documents import Document as LCDocument
        documents = []
        for doc in self.ingest_data:
            if isinstance(doc, Data):
                documents.append(doc.to_lc_document())
            elif isinstance(doc, LCDocument):
                documents.append(doc)
            elif isinstance(doc, str):
                documents.append(LCDocument(page_content=doc))
            elif isinstance(doc, dict):
                text = doc.get("text", doc.get("page_content", ""))
                metadata = {k: v for k, v in doc.items() if k not in ("text", "page_content")}
                documents.append(LCDocument(page_content=str(text), metadata=metadata))
            else:
                documents.append(LCDocument(page_content=str(doc)))
        if not documents:
            return 0
        return self._ingest_documents(documents, wrapped_embeddings)

    # ══════════════════════════════════════════════════════════
    #  BUILD VECTOR STORE
    # ══════════════════════════════════════════════════════════

    @check_cached_vector_store
    def build_vector_store(self) -> VectorStore:
        try:
            self._ensure_index_exists()
        except Exception as e:
            raise ValueError(f"Error creating index: {e}") from e

        real_embedding = self._get_embedding_model()
        wrapped = Float32Embeddings(real_embedding)

        try:
            count = self._ingest_if_needed(wrapped)
            if count > 0:
                self.status = f"Ingested {count} document(s)"
        except Exception as e:
            raise ValueError(f"Error ingesting documents: {e}") from e

        # Return a lightweight proxy that delegates search to the microservice
        # instead of requiring PINECONE_API_KEY locally
        return _MicroservicePineconeProxy(
            index_name=self.index_name,
            namespace=self.namespace or "",
            text_key=self.text_key,
            embedding=wrapped,
            component=self,
        )

    # ══════════════════════════════════════════════════════════
    #  SEARCH via microservice
    # ══════════════════════════════════════════════════════════

    def search_documents(self) -> list[Data]:
        query = self._resolve_search_query()

        try:
            self._ensure_index_exists()
        except Exception as e:
            raise ValueError(f"Error ensuring index: {e}") from e

        real_embedding = self._get_embedding_model()
        wrapped = Float32Embeddings(real_embedding)

        count = 0
        try:
            count = self._ingest_if_needed(wrapped)
            if count > 0:
                logger.info(f"[Pinecone] Ingested {count} document(s) into namespace={self.namespace!r}")
                time.sleep(1)
        except Exception as e:
            raise ValueError(f"Error ingesting: {e}") from e

        if not query:
            self.status = f"Ingested {count} document(s). No search query provided."
            return []

        # Embed the query locally, then delegate search to microservice
        query_embedding = wrapped.embed_query(query)

        try:
            result = search_via_service(
                index_name=self.index_name,
                namespace=self.namespace or "",
                text_key=self.text_key,
                query=query,
                query_embedding=query_embedding,
                number_of_results=self.number_of_results,
                use_hybrid_search=self.use_hybrid_search,
                sparse_model=self.sparse_model,
                hybrid_alpha=self._get_alpha(),
                use_reranking=self.use_reranking,
                rerank_model=self.rerank_model,
                rerank_top_n=self.rerank_top_n,
            )
        except Exception as e:
            raise ValueError(f"Error searching: {type(e).__name__}: {e}") from e

        search_method = result.get("search_method", "dense")
        rerank_info = result.get("rerank_info", "disabled")

        data = []
        for item in result.get("results", []):
            result_data = {
                "text": item["text"],
                "rank": item.get("rank", 0),
                "search_method": search_method,
                "reranking": rerank_info,
                "query": query,
                **item.get("score_info", {}),
                **item.get("metadata", {}),
            }
            data.append(Data(text=item["text"], data=result_data))

        self.status = f"{len(data)} result(s) | method={search_method} | rerank={rerank_info}"
        return data


# ═══════════════════════════════════════════════════════════════

class Float32Embeddings:
    """Wrapper that ensures float32 output."""
    def __init__(self, real_model):
        self._model = real_model

    def embed_documents(self, texts):
        embeddings = self._model.embed_documents(texts)
        return [[float(np.float32(x)) for x in vec] for vec in embeddings]

    def embed_query(self, text):
        embedding = self._model.embed_query(text)
        return [float(np.float32(x)) for x in embedding]


class _MicroservicePineconeProxy(VectorStore):
    """Lightweight VectorStore proxy that delegates all operations to the pinecone-service microservice.

    This avoids needing PINECONE_API_KEY on the backend — the key lives only in the microservice.
    """

    def __init__(self, index_name: str, namespace: str, text_key: str, embedding, component):
        self._index_name = index_name
        self._namespace = namespace
        self._text_key = text_key
        self._embedding = embedding
        self._component = component

    @property
    def embeddings(self):
        return self._embedding

    def add_texts(self, texts, metadatas=None, **kwargs):
        from langchain_core.documents import Document as LCDocument
        docs = []
        for i, text in enumerate(texts):
            meta = metadatas[i] if metadatas and i < len(metadatas) else {}
            docs.append(LCDocument(page_content=text, metadata=meta))
        dense_embeddings = self._embedding.embed_documents(list(texts))
        doc_items = [
            {"page_content": doc.page_content, "metadata": dict(doc.metadata) if doc.metadata else {}}
            for doc in docs
        ]
        result = ingest_via_service(
            index_name=self._index_name,
            namespace=self._namespace,
            text_key=self._text_key,
            documents=doc_items,
            embedding_vectors=dense_embeddings,
        )
        return [str(i) for i in range(result.get("vectors_upserted", 0))]

    def similarity_search(self, query, k=4, **kwargs):
        from langchain_core.documents import Document as LCDocument
        query_embedding = self._embedding.embed_query(query)
        result = search_via_service(
            index_name=self._index_name,
            namespace=self._namespace,
            text_key=self._text_key,
            query=query,
            query_embedding=query_embedding,
            number_of_results=k,
        )
        docs = []
        for item in result.get("results", []):
            docs.append(LCDocument(
                page_content=item.get("text", ""),
                metadata=item.get("metadata", {}),
            ))
        return docs

    @classmethod
    def from_texts(cls, texts, embedding, metadatas=None, **kwargs):
        raise NotImplementedError("Use the PineconeVectorStoreNode component instead.")
