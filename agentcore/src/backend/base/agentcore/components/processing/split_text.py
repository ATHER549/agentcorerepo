import hashlib
from agentcore.custom.custom_node.node import Node
from agentcore.io import DropdownInput, HandleInput, IntInput, Output, StrInput
from agentcore.schema.data import Data


class SplitText(Node):
    display_name: str = "Text Splitter"
    description: str = (
        "Split extracted documents into chunks for vector storage. "
        "Preserves all source metadata. Deterministic chunk IDs for idempotent ingestion."
    )
    name = "TextSplitter" 
    icon = "Scissors"

    inputs = [
        HandleInput(
            name="documents",
            display_name="Documents",
            input_types=["Data", "Message"],
            info="Input documents from Gemini OCR Extractor, Text Input, or any Data/Message source.",
            is_list=True,
        ),
        StrInput(
            name="kb_id",
            display_name="Knowledge Base ID",
            info="Identifier for this knowledge base. Used in chunk IDs so re-ingestion is idempotent.",
            value="default",
        ),
        DropdownInput(
            name="chunking_strategy",
            display_name="Chunking Strategy",
            options=["Recursive", "Sliding Window"],
            value="Recursive",
            info=(
                "Recursive: splits on natural boundaries (paragraphs, sentences). Best for general docs. "
                "Sliding Window: fixed-size overlapping windows. Best for uniform chunk sizes."
            ),
        ),
        IntInput(
            name="chunk_size",
            display_name="Chunk Size",
            info="Maximum characters per chunk.",
            value=1000,
        ),
        IntInput(
            name="chunk_overlap",
            display_name="Chunk Overlap",
            info="Characters of overlap between consecutive chunks.",
            value=200,
        ),
    ]

    outputs = [
        Output(
            display_name="Chunks",
            name="chunks",
            method="split_documents",
        ),
    ]

    def split_documents(self) -> list[Data]:
        """Split input documents into chunks. Returns list[Data].
        This method is bound to the 'chunks' Output port.
        """
        if not self.documents:
            self.status = "No documents to split."
            return []

        if self.chunking_strategy == "Recursive":
            chunks = self._recursive_chunk()
        else:
            chunks = self._sliding_window_chunk()

        self.status = f"{len(chunks)} chunks from {len(self.documents)} document(s)"
        return chunks


    @staticmethod
    def _to_data(doc) -> Data | None:
        """Convert a Message or Data input to Data."""
        if isinstance(doc, Data):
            return doc
        text = None
        if hasattr(doc, "text"):
            text = doc.text
        elif hasattr(doc, "content"):
            text = doc.content
        elif isinstance(doc, str):
            text = doc
        if text:
            return Data(text=str(text), data={"source_file": "", "extraction_method": "message"})
        return None

    def _recursive_chunk(self) -> list[Data]:
        from langchain_text_splitters import RecursiveCharacterTextSplitter

        splitter = RecursiveCharacterTextSplitter(
            separators=["\n\n", "\n", ". ", " ", ""],
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
            length_function=len,
            is_separator_regex=False,
        )

        all_chunks: list[Data] = []

        docs = self.documents if isinstance(self.documents, list) else [self.documents]

        for raw_doc in docs:
            doc = self._to_data(raw_doc)
            if doc is None:
                continue
            text = doc.text.strip() if doc.text else ""
            if not text:
                continue

            source_meta = doc.data if doc.data else {}
            splits = splitter.split_text(text)

            for idx, chunk_text in enumerate(splits):
                chunk_text = chunk_text.strip()
                if not chunk_text:
                    continue

                chunk_id = self._make_id(
                    self.kb_id, source_meta.get("source_file", ""), idx, chunk_text
                )

                all_chunks.append(Data(
                    text=chunk_text,
                    data={
                        # ── Inherited from source document ─────
                        "source_file": source_meta.get("source_file", ""),
                        "file_path": source_meta.get("file_path", ""),
                        "page_number": source_meta.get("page_number", 1),
                        "total_pages": source_meta.get("total_pages", 1),
                        "file_type": source_meta.get("file_type", ""),
                        "extraction_method": source_meta.get("extraction_method", ""),
                        "sheet_name": source_meta.get("sheet_name", ""),
                        # ── Chunk-level metadata ───────────────
                        "chunk_id": chunk_id,
                        "kb_id": self.kb_id,
                        "chunk_index": idx,
                        "chunk_size": len(chunk_text),
                        "total_chunks_in_doc": len(splits),
                        "chunking_strategy": "recursive",
                    },
                ))

        return all_chunks

    def _sliding_window_chunk(self) -> list[Data]:
        all_chunks: list[Data] = []
        step = max(self.chunk_size - self.chunk_overlap, 1)

        docs = self.documents if isinstance(self.documents, list) else [self.documents]

        for raw_doc in docs:
            doc = self._to_data(raw_doc)
            if doc is None:
                continue
            text = doc.text.strip() if doc.text else ""
            if not text:
                continue

            source_meta = doc.data if doc.data else {}
            pos = 0
            chunk_num = 0

            while pos < len(text):
                chunk_text = text[pos: pos + self.chunk_size].strip()
                if not chunk_text:
                    pos += step
                    continue

                chunk_id = self._make_id(
                    self.kb_id, source_meta.get("source_file", ""), chunk_num, chunk_text
                )

                all_chunks.append(Data(
                    text=chunk_text,
                    data={
                        "source_file": source_meta.get("source_file", ""),
                        "file_path": source_meta.get("file_path", ""),
                        "page_number": source_meta.get("page_number", 1),
                        "file_type": source_meta.get("file_type", ""),
                        "extraction_method": source_meta.get("extraction_method", ""),
                        "sheet_name": source_meta.get("sheet_name", ""),
                        "chunk_id": chunk_id,
                        "kb_id": self.kb_id,
                        "chunk_index": chunk_num,
                        "chunk_size": len(chunk_text),
                        "chunking_strategy": "sliding_window",
                    },
                ))
                chunk_num += 1
                pos += step

        return all_chunks

    @staticmethod
    def _make_id(kb_id: str, source: str, index: int, content: str) -> str:
        """
        Deterministic ID based on kb + source + position + content.
        Re-ingesting the same file produces the same IDs → idempotent upserts.
        """
        raw = f"{kb_id}::{source}::{index}::{content[:100]}"
        return hashlib.sha256(raw.encode()).hexdigest()[:24]
