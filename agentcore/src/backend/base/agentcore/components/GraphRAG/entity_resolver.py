from __future__ import annotations

from collections import defaultdict

from loguru import logger

from agentcore.custom.custom_node.node import Node
from agentcore.field_typing.range_spec import RangeSpec
from agentcore.io import (
    BoolInput,
    DropdownInput,
    FloatInput,
    HandleInput,
    IntInput,
    Output,
)
from agentcore.schema.data import Data


def _normalize(name: str) -> str:
    """Normalize an entity name for comparison."""
    import re
    name = name.strip().lower()
    for prefix in ("dr.", "mr.", "mrs.", "ms.", "prof.", "the ", "a "):
        if name.startswith(prefix):
            name = name[len(prefix):].strip()
    name = re.sub(r"[^\w\s]", "", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name


def _token_set(name: str) -> set[str]:
    """Return the set of meaningful tokens in a name."""
    stop = {"the", "a", "an", "of", "in", "at", "for", "and", "or", "to", "is", "by"}
    return {t for t in _normalize(name).split() if t not in stop and len(t) > 1}


def _fuzzy_similarity(a: str, b: str) -> float:
    """Token-based Jaccard similarity (fast, no external deps)."""
    tokens_a = _token_set(a)
    tokens_b = _token_set(b)
    if not tokens_a or not tokens_b:
        return 0.0
    intersection = tokens_a & tokens_b
    union = tokens_a | tokens_b
    return len(intersection) / len(union)


def _levenshtein_ratio(a: str, b: str) -> float:
    """Levenshtein similarity ratio (0.0-1.0). Pure Python, no deps."""
    na = _normalize(a)
    nb = _normalize(b)
    if na == nb:
        return 1.0
    len_a, len_b = len(na), len(nb)
    if len_a == 0 or len_b == 0:
        return 0.0

    # Fast path: if lengths differ drastically, skip
    if abs(len_a - len_b) / max(len_a, len_b) > 0.5:
        return 0.0

    prev = list(range(len_b + 1))
    for i in range(1, len_a + 1):
        curr = [i] + [0] * len_b
        for j in range(1, len_b + 1):
            cost = 0 if na[i - 1] == nb[j - 1] else 1
            curr[j] = min(curr[j - 1] + 1, prev[j] + 1, prev[j - 1] + cost)
        prev = curr

    distance = prev[len_b]
    max_len = max(len_a, len_b)
    return 1.0 - (distance / max_len)


class EntityResolverComponent(Node):
    """Deduplicate and merge entities using fuzzy matching, rules, or LLM-assisted resolution."""

    display_name: str = "Entity Resolver"
    description: str = (
        "Deduplicates and merges entities extracted from multiple document chunks. "
        "Resolves 'Dr. John Smith' + 'John Smith' + 'J. Smith' into a single entity."
    )
    name = "EntityResolver"
    icon = "Merge"

    inputs = [
        # -- Input Entities ---------------------------------------------
        HandleInput(
            name="entities",
            display_name="Entities",
            input_types=["Data"],
            is_list=True,
            info="Extracted entities from Graph Entity Extractor.",
        ),

        # -- Resolution Strategy ----------------------------------------
        DropdownInput(
            name="strategy",
            display_name="Resolution Strategy",
            options=[
                "Exact + Fuzzy",
                "Fuzzy Only",
                "LLM-Assisted",
                "Embedding Similarity",
            ],
            value="Exact + Fuzzy",
            info="Exact+Fuzzy: fast, no LLM cost. "
                 "LLM-Assisted: most accurate, uses LLM to judge duplicates. "
                 "Embedding: uses embedding cosine similarity.",
        ),

        # -- Threshold -------------------------------------------------
        FloatInput(
            name="similarity_threshold",
            display_name="Similarity Threshold",
            info="Minimum similarity score (0.0-1.0) to consider two entities as duplicates. "
                 "Higher = stricter (fewer merges). Recommended: 0.75-0.85.",
            value=0.80,
            range_spec=RangeSpec(min=0.0, max=1.0, step=0.05),
        ),

        # -- Type Matching ----------------------------------------------
        BoolInput(
            name="require_same_type",
            display_name="Require Same Type",
            info="Only merge entities that share the same type (e.g., both 'Person').",
            value=True,
        ),

        # -- LLM (for LLM-Assisted strategy) ---------------------------
        HandleInput(
            name="llm",
            display_name="Language Model (Optional)",
            input_types=["LanguageModel"],
            info="Required only for LLM-Assisted resolution strategy.",
        ),

        # -- Embedding (for Embedding Similarity strategy) ---------------
        HandleInput(
            name="embedding",
            display_name="Embedding (Optional)",
            input_types=["Embeddings"],
            info="Required only for Embedding Similarity resolution strategy.",
        ),

        # -- Advanced --------------------------------------------------
        IntInput(
            name="max_comparisons",
            display_name="Max Comparisons per Entity",
            info="Limit pairwise comparisons to avoid O(n^2) explosion on large graphs. "
                 "0 = no limit.",
            value=50,
            advanced=True,
        ),
        BoolInput(
            name="keep_aliases",
            display_name="Keep Aliases",
            info="Store original variant names as aliases on the merged entity.",
            value=True,
            advanced=True,
        ),
    ]

    outputs = [
        Output(
            display_name="Resolved Entities",
            name="resolved_entities",
            method="resolve",
        ),
        Output(
            display_name="Resolution Report",
            name="report",
            method="get_report",
        ),
    ]

    # ------------------------------------------------------------------
    # Similarity computation
    # ------------------------------------------------------------------

    def _compute_similarity(self, name_a: str, name_b: str) -> float:
        """Compute similarity between two entity names using the chosen strategy."""
        strategy = (self.strategy or "Exact + Fuzzy").lower()

        if "exact" in strategy:
            if _normalize(name_a) == _normalize(name_b):
                return 1.0
            return max(_fuzzy_similarity(name_a, name_b), _levenshtein_ratio(name_a, name_b))

        elif "fuzzy" in strategy:
            return max(_fuzzy_similarity(name_a, name_b), _levenshtein_ratio(name_a, name_b))

        else:
            # For LLM/Embedding strategies, use fuzzy as pre-filter
            return max(_fuzzy_similarity(name_a, name_b), _levenshtein_ratio(name_a, name_b))

    def _llm_judge(self, name_a: str, desc_a: str, name_b: str, desc_b: str) -> bool:
        """Ask the LLM whether two entities refer to the same real-world thing."""
        if not self.llm:
            return False

        prompt = (
            f"Do these two entries refer to the same entity? Answer only YES or NO.\n\n"
            f"Entity A: {name_a} -- {desc_a}\n"
            f"Entity B: {name_b} -- {desc_b}\n\n"
            f"Answer:"
        )
        try:
            response = self.llm.invoke(prompt)
            raw = response.content if hasattr(response, "content") else str(response)
            return "YES" in raw.upper()
        except Exception as e:
            logger.warning(f"[Entity Resolver] LLM judge call failed: {e}")
            self.log(f"LLM judge failed for '{name_a}' vs '{name_b}': {e}")
            return False

    def _embedding_similarity(self, name_a: str, name_b: str) -> float:
        """Compute cosine similarity between embedded entity names."""
        if not self.embedding:
            return 0.0

        try:
            vecs = self.embedding.embed_documents([name_a, name_b])
            import math
            dot = sum(a * b for a, b in zip(vecs[0], vecs[1]))
            norm_a = math.sqrt(sum(a * a for a in vecs[0]))
            norm_b = math.sqrt(sum(b * b for b in vecs[1]))
            if norm_a == 0 or norm_b == 0:
                return 0.0
            return dot / (norm_a * norm_b)
        except Exception as e:
            logger.warning(f"[Entity Resolver] Embedding similarity failed: {e}")
            self.log(f"Embedding similarity failed for '{name_a}' vs '{name_b}': {e}")
            return 0.0

    # ------------------------------------------------------------------
    # Merge two entities
    # ------------------------------------------------------------------

    def _merge_entities(self, primary: dict, secondary: dict) -> dict:
        """Merge secondary entity into primary, keeping the richer data."""
        # Keep longer description
        desc_a = primary.get("description", "")
        desc_b = secondary.get("description", "")
        if len(desc_b) > len(desc_a):
            primary["description"] = desc_b

        # Union relationships (deduplicate by target+type)
        rels_a = primary.get("relationships", [])
        rels_b = secondary.get("relationships", [])
        seen = {
            (r.get("target", "").lower(), r.get("type", "").lower())
            for r in rels_a
            if isinstance(r, dict)
        }
        for r in rels_b:
            if not isinstance(r, dict):
                continue
            key = (r.get("target", "").lower(), r.get("type", "").lower())
            if key not in seen:
                rels_a.append(r)
                seen.add(key)
        primary["relationships"] = rels_a

        # Union source chunks
        chunks_a = set(primary.get("source_chunk_ids", []))
        chunks_b = set(secondary.get("source_chunk_ids", []))
        primary["source_chunk_ids"] = list(chunks_a | chunks_b)

        # Track aliases
        aliases = set(primary.get("aliases", []))
        sec_name = secondary.get("name", "")
        if sec_name:
            aliases.add(sec_name)
        primary["aliases"] = list(aliases)

        return primary

    # ------------------------------------------------------------------
    # Output: resolve
    # ------------------------------------------------------------------

    def resolve(self) -> list[Data]:
        """
        Main resolution method.
        1. Group entities by type (if require_same_type)
        2. Compare pairs within each group
        3. Merge duplicates
        4. Return deduplicated list
        """
        # Reset report for this execution
        self._report = {}

        entities = self.entities
        if not entities:
            self.status = "No entities provided."
            return []

        if not isinstance(entities, list):
            entities = [entities]

        threshold = max(0.0, min(self.similarity_threshold or 0.80, 1.0))
        strategy = (self.strategy or "Exact + Fuzzy").lower()
        max_comp = max(0, self.max_comparisons or 50)

        # Convert to working dicts
        working: list[dict] = []
        for e in entities:
            if not isinstance(e, Data):
                continue
            d = dict(e.data) if hasattr(e, "data") and isinstance(e.data, dict) else {}
            d.setdefault("name", str(e))
            d.setdefault("type", "Entity")
            d.setdefault("description", "")
            d.setdefault("relationships", [])
            d.setdefault("source_chunk_ids", [])
            d.setdefault("aliases", [])
            d["_merged"] = False
            working.append(d)

        original_count = len(working)
        if original_count == 0:
            self.status = "No valid entities to resolve."
            return []

        merge_count = 0

        # Group by type if required
        if self.require_same_type:
            groups: dict[str, list[dict]] = defaultdict(list)
            for w in working:
                groups[w["type"]].append(w)
        else:
            groups = {"_all": working}

        # Pairwise comparison within groups
        total_comparisons = 0
        for group_name, group_entities in groups.items():
            n = len(group_entities)
            if n < 2:
                continue

            self.log(f"Resolving group '{group_name}': {n} entities...")

            for i in range(n):
                if group_entities[i]["_merged"]:
                    continue
                comparisons = 0
                for j in range(i + 1, n):
                    if group_entities[j]["_merged"]:
                        continue
                    if max_comp > 0 and comparisons >= max_comp:
                        break

                    name_a = group_entities[i]["name"]
                    name_b = group_entities[j]["name"]

                    sim = self._compute_similarity(name_a, name_b)
                    comparisons += 1
                    total_comparisons += 1

                    is_duplicate = sim >= threshold

                    # For borderline cases in LLM-Assisted mode, ask LLM
                    if not is_duplicate and "llm" in strategy and sim >= threshold * 0.7:
                        is_duplicate = self._llm_judge(
                            name_a, group_entities[i].get("description", ""),
                            name_b, group_entities[j].get("description", ""),
                        )

                    # For embedding strategy
                    if not is_duplicate and "embedding" in strategy and sim >= threshold * 0.5:
                        emb_sim = self._embedding_similarity(name_a, name_b)
                        is_duplicate = emb_sim >= threshold

                    if is_duplicate:
                        group_entities[i] = self._merge_entities(
                            group_entities[i], group_entities[j]
                        )
                        group_entities[j]["_merged"] = True
                        merge_count += 1

            # Progress logging for large groups
            if n > 20:
                self.log(
                    f"Group '{group_name}' complete: "
                    f"{merge_count} merges so far, {total_comparisons} comparisons."
                )

        # Collect non-merged entities
        resolved = []
        for w in working:
            if w["_merged"]:
                continue

            aliases = w.pop("aliases", [])
            w.pop("_merged", None)

            if self.keep_aliases and aliases:
                w["aliases"] = [a for a in aliases if a and a != w["name"]]

            resolved.append(Data(
                text=f"{w['name']} ({w['type']}): {w.get('description', '')}",
                data=w,
            ))

        self._report = {
            "original_count": original_count,
            "resolved_count": len(resolved),
            "merges_performed": merge_count,
            "total_comparisons": total_comparisons,
            "reduction_pct": round(
                (1 - len(resolved) / max(original_count, 1)) * 100, 1
            ),
            "strategy": self.strategy,
            "threshold": threshold,
        }

        self.status = (
            f"Resolved {original_count} -> {len(resolved)} entities "
            f"({merge_count} merges, {self._report['reduction_pct']}% reduction)"
        )
        return resolved

    # ------------------------------------------------------------------
    # Output: report
    # ------------------------------------------------------------------

    def get_report(self) -> Data:
        """Return resolution statistics."""
        if not hasattr(self, "_report") or not self._report:
            self.resolve()
        return Data(data=self._report)
