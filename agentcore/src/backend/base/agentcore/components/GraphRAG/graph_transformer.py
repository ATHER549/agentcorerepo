"""
Graph Transformer Component

Drag-and-drop node for post-processing entities AFTER extraction and
resolution, BEFORE Neo4j ingestion. Applies business rules, normalization,
filtering, and enrichment.

Canvas wiring:
  [Entity Resolver] ---> [Graph Transformer] ---> [Neo4j Graph Store]
                              ^
                      [Schema Config] (optional)

What it does:
  - Normalize: entity name casing, type standardization, trim whitespace
  - Filter: remove entities below quality thresholds (no description,
    too short name, blocked types, regex mismatch)
  - Enrich: compute entity importance scores, add metadata tags,
    infer missing types from relationships
  - Validate: enforce schema constraints from Graph Schema Config
  - Transform relationships: merge reciprocal edges, remove self-loops,
    filter by weight threshold
"""

from __future__ import annotations

import re
from collections import Counter

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
)
from agentcore.schema.data import Data


class GraphTransformerComponent(Node):
    """Post-process entities with business rules, normalization, and filtering before graph storage."""

    display_name: str = "Graph Transformer"
    description: str = (
        "Post-processing pipeline for extracted entities: normalize names, "
        "filter low-quality entities, enforce schema constraints, and "
        "enrich with computed scores before Neo4j ingestion."
    )
    name = "GraphTransformer"
    icon = "Filter"

    inputs = [
        # -- Input Entities ---------------------------------------------
        HandleInput(
            name="entities",
            display_name="Entities",
            input_types=["Data"],
            is_list=True,
            info="Resolved entities from Entity Resolver (or directly from Entity Extractor).",
        ),

        # -- Schema (optional) ------------------------------------------
        HandleInput(
            name="schema",
            display_name="Schema Config (Optional)",
            input_types=["Data"],
            info="Schema from Graph Schema Config. If provided, entities are validated against it.",
        ),

        # -- Name Normalization -----------------------------------------
        DropdownInput(
            name="name_casing",
            display_name="Name Casing",
            options=["Title Case", "UPPER CASE", "lower case", "As Extracted"],
            value="Title Case",
            info="How to normalize entity names.",
        ),
        BoolInput(
            name="strip_punctuation",
            display_name="Strip Trailing Punctuation",
            info="Remove trailing periods, commas, colons from entity names.",
            value=True,
        ),

        # -- Filtering -------------------------------------------------
        IntInput(
            name="min_name_length",
            display_name="Min Name Length",
            info="Remove entities with names shorter than this (characters).",
            value=2,
        ),
        BoolInput(
            name="remove_no_description",
            display_name="Remove Entities Without Description",
            info="Filter out entities that have empty descriptions.",
            value=False,
        ),
        MultilineInput(
            name="blocked_names",
            display_name="Blocked Entity Names",
            info="Comma-separated list of entity names to always remove. "
                 "Case-insensitive. Example: 'it, they, this, the system, data'",
            value="it, they, this, that, he, she, we, them, someone, something",
            advanced=True,
        ),
        MultilineInput(
            name="blocked_types",
            display_name="Blocked Entity Types",
            info="Comma-separated entity types to remove. "
                 "Example: 'Pronoun, Unknown, Misc'",
            value="",
            advanced=True,
        ),
        FloatInput(
            name="min_relationship_weight",
            display_name="Min Relationship Weight",
            info="Remove relationships with weight below this threshold.",
            value=0.0,
            advanced=True,
            range_spec=RangeSpec(min=0.0, max=1.0, step=0.05),
        ),

        # -- Enrichment ------------------------------------------------
        BoolInput(
            name="compute_importance",
            display_name="Compute Importance Score",
            info="Add an 'importance' score based on relationship count + description length.",
            value=True,
            advanced=True,
        ),
        BoolInput(
            name="remove_self_loops",
            display_name="Remove Self-Loop Relationships",
            info="Remove relationships where source == target.",
            value=True,
            advanced=True,
        ),
        BoolInput(
            name="remove_orphans",
            display_name="Remove Orphan Entities",
            info="Remove entities that have zero relationships after filtering.",
            value=False,
            advanced=True,
        ),
        BoolInput(
            name="enforce_schema_types",
            display_name="Enforce Schema Types",
            info="If schema is provided, remove entities whose type is not in the schema.",
            value=False,
            advanced=True,
        ),
    ]

    outputs = [
        Output(
            display_name="Transformed Entities",
            name="transformed_entities",
            method="transform",
        ),
        Output(
            display_name="Transform Report",
            name="report",
            method="get_report",
        ),
    ]

    # ------------------------------------------------------------------
    # Name normalization
    # ------------------------------------------------------------------

    def _normalize_name(self, name: str) -> str:
        """Apply casing and cleanup rules to an entity name."""
        name = name.strip()
        if not name:
            return name

        # Strip trailing punctuation
        if self.strip_punctuation:
            name = re.sub(r"[.,;:!?\-]+$", "", name).strip()

        # Apply casing
        casing = (self.name_casing or "Title Case").lower()
        if "title" in casing:
            name = name.title()
        elif "upper" in casing:
            name = name.upper()
        elif "lower" in casing:
            name = name.lower()
        # else: As Extracted -- keep original

        return name

    # ------------------------------------------------------------------
    # Blocked names / types sets
    # ------------------------------------------------------------------

    def _get_blocked_names(self) -> set[str]:
        raw = self.blocked_names or ""
        return {n.strip().lower() for n in raw.split(",") if n.strip()}

    def _get_blocked_types(self) -> set[str]:
        raw = self.blocked_types or ""
        return {t.strip().lower() for t in raw.split(",") if t.strip()}

    def _get_schema_types(self) -> set[str] | None:
        """Extract allowed entity type names from schema Data."""
        if not self.schema:
            return None
        schema_data = {}
        if hasattr(self.schema, "data") and isinstance(self.schema.data, dict):
            schema_data = self.schema.data
        names = schema_data.get("entity_type_names", [])
        if names and isinstance(names, list):
            return {n.lower() for n in names if isinstance(n, str)}
        return None

    # ------------------------------------------------------------------
    # Output: transform
    # ------------------------------------------------------------------

    def transform(self) -> list[Data]:
        """
        Run the full transformation pipeline:
        1. Normalize names
        2. Filter by blocked names / types / length / description
        3. Filter relationships (weight, self-loops)
        4. Enforce schema if provided
        5. Compute importance scores
        6. Remove orphans (optional)
        """
        # Reset report for this execution
        self._report = {}

        entities = self.entities
        if not entities:
            self.status = "No entities provided."
            return []

        if not isinstance(entities, list):
            entities = [entities]

        original_count = len(entities)
        blocked_names = self._get_blocked_names()
        blocked_types = self._get_blocked_types()
        schema_types = self._get_schema_types() if self.enforce_schema_types else None
        min_name_len = max(1, self.min_name_length or 2)

        min_rel_weight = 0.0
        try:
            min_rel_weight = max(0.0, float(self.min_relationship_weight or 0.0))
        except (ValueError, TypeError):
            min_rel_weight = 0.0

        filtered_reasons: Counter = Counter()
        result: list[dict] = []

        for idx, entity in enumerate(entities):
            if not isinstance(entity, Data):
                filtered_reasons["invalid_type"] += 1
                continue

            d = {}
            if hasattr(entity, "data") and isinstance(entity.data, dict):
                d = dict(entity.data)
            else:
                filtered_reasons["no_data"] += 1
                continue

            name = d.get("name", "")
            if not isinstance(name, str):
                name = str(name) if name else ""

            # --- Normalize name ---
            name = self._normalize_name(name)
            d["name"] = name

            # --- Filter: blocked names ---
            if name.lower() in blocked_names:
                filtered_reasons["blocked_name"] += 1
                continue

            # --- Filter: min name length ---
            if len(name) < min_name_len:
                filtered_reasons["short_name"] += 1
                continue

            # --- Filter: blocked types ---
            etype = (d.get("type") or "Entity")
            if not isinstance(etype, str):
                etype = str(etype)
            etype = etype.strip()
            if etype.lower() in blocked_types:
                filtered_reasons["blocked_type"] += 1
                continue

            # --- Filter: schema type enforcement ---
            if schema_types and etype.lower() not in schema_types:
                filtered_reasons["not_in_schema"] += 1
                continue

            # --- Filter: require description ---
            desc = d.get("description", "")
            if not isinstance(desc, str):
                desc = str(desc) if desc else ""
            if self.remove_no_description and not desc.strip():
                filtered_reasons["no_description"] += 1
                continue

            # --- Normalize type casing ---
            d["type"] = etype.title()

            # --- Transform relationships ---
            rels = d.get("relationships", [])
            if not isinstance(rels, list):
                rels = []
            cleaned_rels = []
            for rel in rels:
                if not isinstance(rel, dict):
                    continue

                target = (rel.get("target") or "").strip()
                if not target:
                    continue

                # Self-loop removal
                if self.remove_self_loops and target.lower() == name.lower():
                    continue

                # Weight filter
                weight = rel.get("weight", 1.0)
                try:
                    weight = float(weight)
                except (ValueError, TypeError):
                    weight = 1.0
                weight = max(0.0, min(weight, 1.0))

                if weight < min_rel_weight:
                    continue

                # Normalize target name
                rel["target"] = self._normalize_name(target)
                rel["weight"] = weight
                cleaned_rels.append(rel)

            d["relationships"] = cleaned_rels

            # --- Compute importance score ---
            if self.compute_importance:
                desc_len = len(desc) if desc else 0
                desc_score = min(desc_len / 200.0, 1.0)
                rel_score = min(len(cleaned_rels) / 5.0, 1.0)
                chunks = d.get("source_chunk_ids", [])
                chunk_count = len(chunks) if isinstance(chunks, list) else 0
                chunk_score = min(chunk_count / 3.0, 1.0)
                importance = round((desc_score * 0.3 + rel_score * 0.4 + chunk_score * 0.3), 3)
                d["importance"] = importance

            result.append(d)

            # Progress logging for large sets
            if (idx + 1) % 500 == 0:
                self.log(f"Processed {idx + 1}/{original_count} entities...")

        # --- Optional: remove orphans ---
        if self.remove_orphans:
            connected: set[str] = set()
            for d in result:
                if d.get("relationships"):
                    connected.add(d["name"].lower())
                    for r in d["relationships"]:
                        target = r.get("target", "")
                        if target:
                            connected.add(target.lower())

            before = len(result)
            result = [d for d in result if d["name"].lower() in connected]
            orphans_removed = before - len(result)
            if orphans_removed > 0:
                filtered_reasons["orphan"] = orphans_removed

        # Build output
        output = []
        for d in result:
            output.append(Data(
                text=f"{d['name']} ({d['type']}): {d.get('description', '')}",
                data=d,
            ))

        # Sort by importance if computed
        if self.compute_importance:
            output.sort(key=lambda x: x.data.get("importance", 0), reverse=True)

        self._report = {
            "original_count": original_count,
            "output_count": len(output),
            "filtered_count": original_count - len(output),
            "filter_reasons": dict(filtered_reasons),
            "total_relationships": sum(len(d.get("relationships", [])) for d in result),
            "settings": {
                "name_casing": self.name_casing,
                "min_name_length": min_name_len,
                "min_relationship_weight": min_rel_weight,
                "enforce_schema": bool(schema_types),
                "remove_orphans": bool(self.remove_orphans),
            },
        }

        self.status = (
            f"Transformed: {original_count} -> {len(output)} entities "
            f"({original_count - len(output)} filtered)"
        )
        return output

    # ------------------------------------------------------------------
    # Output: report
    # ------------------------------------------------------------------

    def get_report(self) -> Data:
        """Return transformation statistics and filter breakdown."""
        if not hasattr(self, "_report") or not self._report:
            self.transform()
        return Data(data=self._report)
