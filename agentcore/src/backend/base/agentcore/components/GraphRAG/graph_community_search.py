"""
Graph Community Search Component

Drag-and-drop node for Global Search -- answers broad questions by
summarizing across community clusters in the knowledge graph.

Canvas wiring:
  [LLM]   --+
             +---> [Graph Community Search] ---> Answer / Data
  [Query]  --+

This component:
  - Detects communities in the Neo4j graph (via graph-rag-service microservice)
  - Generates LLM summaries for each community (locally)
  - For a query: ranks communities -> feeds top summaries to LLM -> map-reduce answer
  - Best for broad/summary questions like "What are the main themes?"
"""

from __future__ import annotations

from loguru import logger

from agentcore.custom.custom_node.node import Node
from agentcore.io import (
    HandleInput,
    IntInput,
    Output,
    QueryInput,
    StrInput,
)
from agentcore.schema.data import Data
from agentcore.schema.message import Message
from agentcore.services.graph_rag_service_client import (
    detect_communities_via_service,
    store_communities_via_service,
)


MAP_PROMPT = """You are analyzing a community of related entities in a knowledge graph.
Given the following community description, determine if it is relevant to the user's question.
If relevant, provide a focused summary that addresses the question. If not relevant, respond with "NOT_RELEVANT".

Community:
{community_summary}

Question:
{query}

Your analysis:"""

REDUCE_PROMPT = """You are synthesizing information from multiple knowledge graph communities
to answer a user's question comprehensively.

Community analyses:
{analyses}

Question:
{query}

Provide a comprehensive answer based on the community analyses above.
Cite specific entities and themes when possible.
If the analyses don't contain enough information, say so.

Answer:"""


class GraphCommunitySearchComponent(Node):
    """Global search over knowledge graph communities for broad/summary questions."""

    display_name: str = "Graph Community Search"
    description: str = (
        "Global search that answers broad questions by analyzing community "
        "clusters in the knowledge graph. Uses map-reduce over community "
        "summaries for comprehensive answers."
    )
    name = "GraphCommunitySearch"
    icon = "Globe"

    inputs = [
        # -- Graph KB ---------------------------------------------------
        StrInput(
            name="graph_kb_id",
            display_name="Graph KB ID",
            value="default",
        ),

        # -- Query ------------------------------------------------------
        QueryInput(
            name="search_query",
            display_name="Search Query",
            info="Broad question to answer via community analysis.",
            input_types=["Message"],
            tool_mode=True,
        ),

        # -- LLM -------------------------------------------------------
        HandleInput(
            name="llm",
            display_name="Language Model",
            input_types=["LanguageModel"],
            info="LLM for community analysis and answer synthesis.",
        ),

        # -- Config -----------------------------------------------------
        IntInput(
            name="max_communities",
            display_name="Max Communities to Analyze",
            info="Top-N communities to analyze (ranked by size/importance).",
            value=10,
            advanced=True,
        ),
        IntInput(
            name="min_community_size",
            display_name="Min Community Size",
            info="Minimum number of entities for a community to be included. "
                 "Communities smaller than this are discarded.",
            value=2,
            advanced=True,
        ),
    ]

    outputs = [
        Output(
            display_name="Answer",
            name="answer",
            method="global_search",
        ),
        Output(
            display_name="Communities",
            name="communities",
            method="detect_communities",
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
    # Community detection via microservice + local LLM summaries
    # ------------------------------------------------------------------

    def detect_communities(self) -> list[Data]:
        """
        Detect communities in the graph via the graph-rag-service microservice
        and generate LLM summaries locally.

        Returns list of Data items, one per community, with:
          - title, summary, node_count, members
        """
        graph_kb_id = self.graph_kb_id or "default"
        max_communities = max(1, self.max_communities or 10)
        min_community_size = max(2, self.min_community_size or 2)

        # Delegate community detection to graph-rag-service
        resp = detect_communities_via_service(
            graph_kb_id=graph_kb_id,
            max_communities=max_communities,
            min_community_size=min_community_size,
        )

        communities = resp.get("communities", [])

        if not communities:
            self.status = resp.get("message", "No communities found.")
            self.log(self.status)
            return []

        # Check if communities already have summaries (pre-existing)
        already_summarized = all(c.get("summary") for c in communities)
        if already_summarized:
            self.log(f"Found {len(communities)} existing communities with summaries.")
            results = []
            for comm in communities:
                results.append(Data(
                    text=f"**{comm.get('title', 'Community')}**\n{comm.get('summary', '')}",
                    data={
                        "community_id": comm.get("id", ""),
                        "title": comm.get("title", ""),
                        "summary": comm.get("summary", ""),
                        "node_count": comm.get("node_count", 0),
                        "members": comm.get("members", []),
                        "graph_kb_id": graph_kb_id,
                    },
                ))
            self.status = f"{len(results)} communities loaded."
            return results

        # Generate LLM summaries locally for newly detected communities
        self.log(f"Generating summaries for {len(communities)} communities...")
        results = []
        community_summaries = []

        for comm_idx, comm in enumerate(communities):
            members = comm.get("members", [])[:20]
            types = list(set(t for t in comm.get("types", []) if t))
            descriptions = [d for d in comm.get("descriptions", []) if d and d.strip()][:10]

            member_text = ", ".join(members[:10])
            desc_text = ". ".join(descriptions[:5])
            community_text = (
                f"Entities ({len(members)}): {member_text}\n"
                f"Types: {', '.join(types)}\n"
                f"Descriptions: {desc_text}"
            )

            title = f"Community: {', '.join(members[:3])}"
            summary = community_text  # fallback

            if self.llm:
                try:
                    prompt = (
                        f"Summarize this knowledge graph community in 2-3 sentences. "
                        f"Give it a short title.\n\n{community_text}\n\n"
                        f"Format: Title: <title>\nSummary: <summary>"
                    )
                    response = self.llm.invoke(prompt)
                    raw = response.content if hasattr(response, "content") else str(response)

                    if "Title:" in raw and "Summary:" in raw:
                        parts = raw.split("Summary:", 1)
                        title = parts[0].replace("Title:", "").strip()
                        summary = parts[1].strip()
                    else:
                        summary = raw.strip()
                        title = f"Community: {members[0]}" if members else "Community"
                except Exception as e:
                    logger.warning(f"[Community Search] LLM summary failed for community {comm_idx}: {e}")
                    self.log(f"LLM summary failed for community {comm_idx + 1}: {e}")

            # Collect for batch storage via microservice
            community_summaries.append({
                "community_id": comm.get("id", ""),
                "title": title,
                "summary": summary,
                "node_count": comm.get("node_count", 0),
                "members": members,
            })

            results.append(Data(
                text=f"**{title}**\n{summary}",
                data={
                    "community_id": comm.get("id", ""),
                    "title": title,
                    "summary": summary,
                    "node_count": comm.get("node_count", 0),
                    "members": members,
                    "graph_kb_id": graph_kb_id,
                },
            ))

        # Store community summaries back to Neo4j via microservice
        if community_summaries:
            try:
                store_communities_via_service(
                    graph_kb_id=graph_kb_id,
                    communities=community_summaries,
                )
                self.log(f"Stored {len(community_summaries)} community summaries.")
            except Exception as e:
                logger.warning(f"[Community Search] Failed to store communities: {e}")

        self.status = f"Detected and summarized {len(results)} communities."
        return results

    # ------------------------------------------------------------------
    # Global search (map-reduce over communities)
    # ------------------------------------------------------------------

    def global_search(self) -> Data:
        """
        Answer a broad question by analyzing all community summaries.

        Map step: Ask LLM if each community is relevant to the query.
        Reduce step: Synthesize relevant analyses into a final answer.
        """
        query = self._resolve_search_query()
        if not query:
            self.status = "No search query provided."
            return Data(text="No query provided.", data={"status": "no_query"})

        if not self.llm:
            self.status = "No LLM connected."
            return Data(text="No LLM connected for global search.", data={"status": "no_llm"})

        # Get communities
        communities = self.detect_communities()
        if not communities:
            status_msg = self.status or "No communities found"
            return Data(
                text=f"No communities found in the knowledge graph. {status_msg}. "
                     f"Check that graph_kb_id matches the one used during ingestion.",
                data={
                    "query": query,
                    "status": "no_communities",
                    "graph_kb_id": self.graph_kb_id or "default",
                    "diagnostic": status_msg,
                },
            )

        # MAP: Analyze each community against the query
        self.log(f"Map phase: Analyzing {len(communities)} communities against query...")
        relevant_analyses = []

        for idx, comm in enumerate(communities):
            summary = comm.data.get("summary", "") if hasattr(comm, "data") else ""
            if not summary or not summary.strip():
                continue

            try:
                prompt = MAP_PROMPT.format(community_summary=summary, query=query)
                response = self.llm.invoke(prompt)
                raw = response.content if hasattr(response, "content") else str(response)

                if "NOT_RELEVANT" not in raw.upper():
                    title = comm.data.get("title", "Community") if hasattr(comm, "data") else "Community"
                    relevant_analyses.append(f"### {title}\n{raw.strip()}")
            except Exception as e:
                logger.warning(f"[Community Search] Map analysis failed for community {idx}: {e}")
                self.log(f"Map analysis failed for community {idx + 1}: {e}")

        if not relevant_analyses:
            return Data(
                text="No relevant communities found for this query. "
                     "Try a more specific question or use local search instead.",
                data={"query": query, "status": "no_relevant_communities"},
            )

        # REDUCE: Synthesize final answer
        self.log(f"Reduce phase: Synthesizing {len(relevant_analyses)} relevant analyses...")
        analyses_text = "\n\n".join(relevant_analyses)

        try:
            prompt = REDUCE_PROMPT.format(analyses=analyses_text, query=query)
            response = self.llm.invoke(prompt)
            answer = response.content if hasattr(response, "content") else str(response)
        except Exception as e:
            logger.error(f"[Community Search] Reduce synthesis failed: {e}")
            self.log(f"Reduce synthesis failed: {e}")
            answer = (
                f"Analysis found {len(relevant_analyses)} relevant communities "
                f"but synthesis failed: {e}"
            )

        self.status = (
            f"Global search: {len(relevant_analyses)}/{len(communities)} "
            f"communities relevant"
        )

        return Data(
            text=answer,
            data={
                "query": query,
                "total_communities": len(communities),
                "relevant_communities": len(relevant_analyses),
                "analyses": relevant_analyses,
                "search_type": "global",
            },
        )
