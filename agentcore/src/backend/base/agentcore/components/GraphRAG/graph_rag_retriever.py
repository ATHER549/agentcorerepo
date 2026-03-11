"""
Graph RAG Retriever Component

Drag-and-drop node that combines graph-based context with optional
vector store results to produce an enriched context for LLM answering.

Canvas wiring:
  [Neo4j Graph Store] --+
                         +---> [Graph RAG Retriever] ---> Enriched Context / Data
  [Vector Store]       --+          ^
  (optional)                    [Search Query]

This component:
  - Takes search results from Neo4j Graph Store (graph context)
  - Optionally merges results from a traditional vector store (Chroma/Pinecone)
  - Ranks, deduplicates, and formats the combined context
  - Outputs enriched Data ready for an LLM prompt / Agent node
"""

from __future__ import annotations

from agentcore.custom.custom_node.node import Node
from agentcore.field_typing.range_spec import RangeSpec
from agentcore.io import (
    BoolInput,
    DropdownInput,
    FloatInput,
    HandleInput,
    IntInput,
    MultilineInput,
    Output,
    QueryInput,
)
from agentcore.schema.data import Data
from agentcore.schema.message import Message


DEFAULT_CONTEXT_TEMPLATE = """## Retrieved Knowledge Graph Context

{graph_context}

{vector_context}

## Instructions
Use the above context (entities, relationships, and source documents) to answer the user's question.
Cite specific entities and relationships when relevant.
If the context doesn't contain enough information, say so.

## Question
{query}
"""


class GraphRAGRetrieverComponent(Node):
    """Combines graph and vector search results into enriched context for LLM answering."""

    display_name: str = "Graph RAG Retriever"
    description: str = (
        "Merges graph-aware search results with optional vector store results "
        "to produce enriched retrieval context for LLM-powered Q&A."
    )
    name = "GraphRAGRetriever"
    icon = "Combine"

    inputs = [
        # -- Graph Results ----------------------------------------------
        HandleInput(
            name="graph_results",
            display_name="Graph Search Results",
            input_types=["Data"],
            is_list=True,
            info="Search results from Neo4j Graph Store component.",
        ),

        # -- Vector Results (optional) ----------------------------------
        HandleInput(
            name="vector_results",
            display_name="Vector Search Results (Optional)",
            input_types=["Data"],
            is_list=True,
            info="Optional results from a traditional vector store (Chroma, Pinecone). "
                 "These are merged with graph results for hybrid RAG.",
        ),

        # -- Search Query -----------------------------------------------
        QueryInput(
            name="search_query",
            display_name="Search Query",
            info="The user's question (used for context formatting).",
            input_types=["Message"],
            tool_mode=True,
        ),

        # -- Merge Config ------------------------------------------------
        DropdownInput(
            name="merge_strategy",
            display_name="Merge Strategy",
            options=["Graph First", "Vector First", "Interleaved", "Score Weighted"],
            value="Graph First",
            info="How to combine graph and vector results. "
                 "Graph First: graph entities prioritized. "
                 "Score Weighted: ordered by relevance score.",
        ),
        FloatInput(
            name="graph_weight",
            display_name="Graph Weight",
            info="Weight for graph results in Score Weighted mode (0.0-1.0). "
                 "Vector weight = 1 - graph_weight.",
            value=0.6,
            advanced=True,
            range_spec=RangeSpec(min=0.0, max=1.0, step=0.05),
        ),
        IntInput(
            name="max_context_items",
            display_name="Max Context Items",
            info="Maximum number of items to include in the final context.",
            value=15,
            advanced=True,
        ),
        BoolInput(
            name="include_relationships",
            display_name="Include Relationships",
            info="Include entity relationships in the formatted context.",
            value=True,
            advanced=True,
        ),
        BoolInput(
            name="include_source_text",
            display_name="Include Source Text",
            info="Include original source chunks in the context.",
            value=True,
            advanced=True,
        ),
        MultilineInput(
            name="context_template",
            display_name="Context Template",
            info="Template for formatting the final context. "
                 "Use {graph_context}, {vector_context}, {query} as placeholders.",
            value=DEFAULT_CONTEXT_TEMPLATE,
            advanced=True,
        ),
    ]

    outputs = [
        Output(
            display_name="Enriched Context",
            name="enriched_context",
            method="build_context",
        ),
        Output(
            display_name="Merged Results",
            name="merged_results",
            method="merge_results",
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
    # Normalize input lists
    # ------------------------------------------------------------------

    def _get_graph_results(self) -> list[Data]:
        results = self.graph_results or []
        if not isinstance(results, list):
            results = [results]
        return [r for r in results if isinstance(r, Data)]

    def _get_vector_results(self) -> list[Data]:
        results = self.vector_results or []
        if not isinstance(results, list):
            results = [results]
        return [r for r in results if isinstance(r, Data)]

    # ------------------------------------------------------------------
    # Format graph results into readable context
    # ------------------------------------------------------------------

    def _format_graph_context(self, results: list[Data]) -> str:
        """Format graph search results into structured text."""
        if not results:
            return ""

        sections = ["### Knowledge Graph Entities\n"]
        for i, item in enumerate(results, 1):
            data = item.data if hasattr(item, "data") and isinstance(item.data, dict) else {}
            name = data.get("entity_name") or data.get("name") or str(item)
            etype = data.get("entity_type") or data.get("type") or ""
            desc = data.get("entity_description") or data.get("description") or ""
            score = data.get("score", 0)

            try:
                score = float(score)
            except (ValueError, TypeError):
                score = 0.0

            sections.append(f"**{i}. {name}** ({etype}) [relevance: {score:.2f}]")
            if desc:
                sections.append(f"   {desc}")

            if self.include_relationships:
                neighbors = data.get("neighbors") or []
                valid_neighbors = [n for n in neighbors if isinstance(n, dict) and n.get("name")]
                if valid_neighbors:
                    sections.append("   Related to:")
                    for n in valid_neighbors[:5]:
                        rel_type = n.get("relationship", "RELATED_TO")
                        sections.append(f"     -> {n['name']} ({n.get('type', '')}) [{rel_type}]")

            if self.include_source_text:
                chunks = data.get("source_chunks") or []
                valid_chunks = [c for c in chunks if c and isinstance(c, str)]
                if valid_chunks:
                    sections.append("   Source:")
                    for c in valid_chunks[:2]:
                        sections.append(f'     "{c[:300]}"')

            sections.append("")

        return "\n".join(sections)

    # ------------------------------------------------------------------
    # Format vector results into readable context
    # ------------------------------------------------------------------

    def _format_vector_context(self, results: list[Data]) -> str:
        """Format traditional vector search results into text."""
        if not results:
            return ""

        sections = ["### Document Retrieval Results\n"]
        for i, item in enumerate(results, 1):
            text = ""
            if hasattr(item, "data") and isinstance(item.data, dict):
                text = item.data.get("text", "")
            if not text and hasattr(item, "text"):
                text = str(item.text) if item.text else ""

            if text:
                sections.append(f"**Document {i}:**")
                sections.append(f"  {text[:500]}")
                sections.append("")

        return "\n".join(sections)

    # ------------------------------------------------------------------
    # Merge results
    # ------------------------------------------------------------------

    def merge_results(self) -> list[Data]:
        """
        Merge graph and vector results using the selected strategy.
        Returns a unified list of Data items.
        """
        graph_results = self._get_graph_results()
        vector_results = self._get_vector_results()
        strategy = (self.merge_strategy or "Graph First").lower()
        max_items = max(1, self.max_context_items or 15)

        if "score" in strategy:
            graph_weight = max(0.0, min(self.graph_weight or 0.6, 1.0))
            vector_weight = 1.0 - graph_weight

            scored = []
            for item in graph_results:
                raw_score = 0.5
                if hasattr(item, "data") and isinstance(item.data, dict):
                    try:
                        raw_score = float(item.data.get("score", 0.5))
                    except (ValueError, TypeError):
                        raw_score = 0.5
                scored.append((item, raw_score * graph_weight))

            for item in vector_results:
                raw_score = 0.5
                if hasattr(item, "data") and isinstance(item.data, dict):
                    try:
                        raw_score = float(item.data.get("score", 0.5))
                    except (ValueError, TypeError):
                        raw_score = 0.5
                scored.append((item, raw_score * vector_weight))

            scored.sort(key=lambda x: x[1], reverse=True)
            merged = [s[0] for s in scored[:max_items]]

        elif "interleaved" in strategy:
            merged = []
            gi, vi = 0, 0
            while len(merged) < max_items and (gi < len(graph_results) or vi < len(vector_results)):
                if gi < len(graph_results):
                    merged.append(graph_results[gi])
                    gi += 1
                if vi < len(vector_results) and len(merged) < max_items:
                    merged.append(vector_results[vi])
                    vi += 1

        elif "vector" in strategy:
            merged = (vector_results + graph_results)[:max_items]

        else:
            # Graph first (default)
            merged = (graph_results + vector_results)[:max_items]

        self.status = (
            f"{len(merged)} items "
            f"({len(graph_results)} graph + {len(vector_results)} vector)"
        )
        return merged

    # ------------------------------------------------------------------
    # Build enriched context
    # ------------------------------------------------------------------

    def build_context(self) -> Data:
        """
        Build the final enriched context string combining graph + vector results.
        Returns a single Data item with the formatted context as text.
        """
        # Use merge_results to get the combined list
        merged = self.merge_results()

        graph_results = self._get_graph_results()
        vector_results = self._get_vector_results()

        # Split merged results back by source type for formatting
        graph_set = set(id(r) for r in graph_results)
        graph_items = [r for r in merged if id(r) in graph_set]
        vector_items = [r for r in merged if id(r) not in graph_set]

        # If split didn't work (all from same source), use original lists capped
        half_max = max(1, (self.max_context_items or 15) // 2)
        if not vector_items and vector_results:
            vector_items = vector_results[:half_max]
        if not graph_items and graph_results:
            graph_items = graph_results[:half_max]

        graph_context = self._format_graph_context(graph_items)
        vector_context = self._format_vector_context(vector_items)
        query = self._resolve_search_query()

        template = self.context_template or DEFAULT_CONTEXT_TEMPLATE
        try:
            enriched = template.format(
                graph_context=graph_context or "(No graph context available)",
                vector_context=vector_context or "(No vector context available)",
                query=query or "(No query provided)",
            )
        except KeyError as e:
            self.log(f"Template formatting failed (missing placeholder {e}), using default.")
            enriched = DEFAULT_CONTEXT_TEMPLATE.format(
                graph_context=graph_context or "(No graph context available)",
                vector_context=vector_context or "(No vector context available)",
                query=query or "(No query provided)",
            )

        self.status = (
            f"Context built: {len(graph_items)} graph + {len(vector_items)} vector items"
        )

        return Data(
            text=enriched,
            data={
                "query": query,
                "graph_items_count": len(graph_items),
                "vector_items_count": len(vector_items),
                "total_items": len(merged),
                "merge_strategy": self.merge_strategy,
            },
        )
