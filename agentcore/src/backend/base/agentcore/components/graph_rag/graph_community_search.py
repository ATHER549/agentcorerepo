"""
Graph Community Search Component

Drag-and-drop node for Global Search -- answers broad questions by
summarizing across community clusters in the knowledge graph.

Canvas wiring:
  [LLM]   --+
             +---> [Graph Community Search] ---> Answer / Data
  [Query]  --+

This component:
  - Detects communities in the Neo4j graph (Leiden / label propagation)
  - Generates LLM summaries for each community
  - For a query: ranks communities -> feeds top summaries to LLM -> map-reduce answer
  - Best for broad/summary questions like "What are the main themes?"
"""

from __future__ import annotations

import hashlib
import os

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
    # Internal: driver
    # ------------------------------------------------------------------

    def _get_driver(self):
        try:
            from neo4j import GraphDatabase
        except ImportError as e:
            msg = "The 'neo4j' package is required. Install with: pip install neo4j>=5.20.0"
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
    # Deterministic community hash (safe for all string content)
    # ------------------------------------------------------------------

    @staticmethod
    def _community_hash(seed: str) -> str:
        """Generate a deterministic 8-character community ID from a seed string."""
        return hashlib.sha256(seed.encode("utf-8", errors="replace")).hexdigest()[:8]

    # ------------------------------------------------------------------
    # Community detection
    # ------------------------------------------------------------------

    def detect_communities(self) -> list[Data]:
        """
        Detect communities in the graph and generate LLM summaries.

        Uses Label Propagation (works on all Neo4j editions) by default,
        or Louvain/Leiden if Neo4j GDS is available.

        Returns list of Data items, one per community, with:
          - title, summary, node_count, members
        """
        driver = self._get_driver()
        db = self._get_database()
        graph_kb_id = self.graph_kb_id or "default"
        max_communities = max(1, self.max_communities or 10)
        min_community_size = max(2, self.min_community_size or 2)

        try:
            # Check for existing communities first
            try:
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
            except Exception as e:
                logger.warning(f"[Community Search] Failed to query existing communities: {e}")
                existing_records = []

            if existing_records:
                self.log(f"Found {len(existing_records)} existing communities.")
                results = []
                for rec in existing_records:
                    results.append(Data(
                        text=f"**{rec.get('title', 'Community')}**\n{rec.get('summary', '')}",
                        data={
                            "community_id": rec["id"],
                            "title": rec.get("title", ""),
                            "summary": rec.get("summary", ""),
                            "node_count": rec.get("node_count", 0),
                            "level": rec.get("level", 0),
                            "graph_kb_id": graph_kb_id,
                        },
                    ))
                self.status = f"{len(results)} communities loaded."
                return results

            # No existing communities -- detect them
            self.log(f"No existing communities found for graph_kb_id='{graph_kb_id}'. Running community detection...")

            # Fetch all entities and their edges for Union-Find
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

            self.log(f"Found {len(all_names)} entities and {len(edges)} edges for graph_kb_id='{graph_kb_id}'.")

            if not all_names:
                # No entities at all — check if entities exist under a different graph_kb_id
                with driver.session(database=db) as session:
                    kb_check = session.run(
                        """
                        MATCH (e:__Entity__)
                        RETURN DISTINCT e.graph_kb_id AS kb_id, count(e) AS cnt
                        LIMIT 10
                        """
                    )
                    available_kbs = {r["kb_id"]: r["cnt"] for r in kb_check}

                if available_kbs:
                    kb_list = ", ".join(f"'{k}' ({v} entities)" for k, v in available_kbs.items())
                    self.status = (
                        f"No entities found for graph_kb_id='{graph_kb_id}'. "
                        f"Available graphs: {kb_list}"
                    )
                    self.log(self.status)
                else:
                    self.status = "No entities found in Neo4j. Ingest documents first."
                return []

            # Union-Find to detect connected components
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

            # Group entities by their root (= connected component)
            from collections import defaultdict as _defaultdict
            components: dict[str, list[str]] = _defaultdict(list)
            for name in all_names:
                components[find(name)].append(name)

            # Assign community IDs back to Neo4j
            for root, members in components.items():
                cid = self._community_hash(root)
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

            self.log(
                f"Union-Find detected {len(components)} components "
                f"from {len(all_names)} entities and {len(edges)} edges."
            )

            # Get community groupings
            try:
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
                    communities = [dict(r) for r in community_result]
            except Exception as e:
                raise ValueError(
                    f"Failed to retrieve community groupings from Neo4j: {e}"
                ) from e

            if not communities:
                self.status = (
                    f"No communities >= {min_community_size} members detected "
                    f"(graph_kb_id='{graph_kb_id}', {len(all_names)} entities, {len(edges)} edges, "
                    f"{len(components)} components)."
                )
                self.log(self.status)
                return []

            # Generate LLM summaries for each community
            self.log(f"Generating summaries for {len(communities)} communities...")
            results = []
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

                # Store community in Neo4j
                try:
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
                            cid=comm["cid"],
                            graph_kb_id=graph_kb_id,
                            title=title,
                            summary=summary,
                            node_count=comm["node_count"],
                            members=members,
                        )
                except Exception as e:
                    logger.warning(f"[Community Search] Failed to store community {comm_idx}: {e}")

                results.append(Data(
                    text=f"**{title}**\n{summary}",
                    data={
                        "community_id": comm["cid"],
                        "title": title,
                        "summary": summary,
                        "node_count": comm["node_count"],
                        "members": members,
                        "graph_kb_id": graph_kb_id,
                    },
                ))

            self.status = f"Detected and summarized {len(results)} communities."
            return results

        finally:
            driver.close()

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
