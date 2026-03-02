"""
Graph Entity Extractor Component

Drag-and-drop node that uses an LLM to extract named entities and
relationships from text chunks, outputting structured Data objects
ready for the Neo4j Graph Store.

Canvas wiring:
  [Text Splitter] ---> [Graph Entity Extractor] ---> [Neo4j Graph Store]
                              ^
                          [LLM Model]

Each output Data item contains:
  - name: entity name
  - type: entity type (Person, Organization, Concept, etc.)
  - description: entity description extracted from context
  - relationships: [{target, type, description, weight}]
  - source_chunk_id: traceback to original chunk
"""

from __future__ import annotations

import hashlib
import json

from loguru import logger

from agentcore.custom.custom_node.node import Node
from agentcore.io import (
    DropdownInput,
    HandleInput,
    IntInput,
    MultilineInput,
    Output,
    StrInput,
)
from agentcore.schema.data import Data


# Default entity types for knowledge graph extraction
DEFAULT_ENTITY_TYPES = "Person, Organization, Location, Event, Concept, Technology, Product, Document"

# Default relationship types
DEFAULT_RELATION_TYPES = (
    "WORKS_AT, LOCATED_IN, PART_OF, RELATED_TO, DEPENDS_ON, "
    "CREATED_BY, USED_BY, MENTIONS, PRECEDES, FOLLOWS"
)

# Extraction prompt -- structured output via LLM
EXTRACTION_PROMPT = """You are a knowledge graph extraction engine.
Given the following text, extract ALL named entities and their relationships.

## Entity Types to extract:
{entity_types}

## Relationship Types to use:
{relation_types}

## Instructions:
1. Extract every distinct entity mentioned in the text.
2. For each entity provide: name, type, and a one-sentence description based on the context.
3. For each pair of related entities, define a relationship with type, description, and weight (0.0-1.0).
4. Be thorough -- extract ALL entities, not just the most prominent ones.
5. Normalize entity names (e.g., "Dr. John Smith" and "John Smith" -> "John Smith").
6. Return ONLY valid JSON, no markdown fences.

## Output Format (JSON):
{{
  "entities": [
    {{
      "name": "Entity Name",
      "type": "Entity Type",
      "description": "Brief description from context"
    }}
  ],
  "relationships": [
    {{
      "source": "Source Entity Name",
      "target": "Target Entity Name",
      "type": "RELATIONSHIP_TYPE",
      "description": "Brief description of the relationship",
      "weight": 0.8
    }}
  ]
}}

## Text to analyze:
{text}
"""

# Simpler prompt for when chunk is very small
SIMPLE_EXTRACTION_PROMPT = """Extract entities and relationships from this text as JSON.
Entity types: {entity_types}
Relationship types: {relation_types}

Return format:
{{"entities": [{{"name": "...", "type": "...", "description": "..."}}], "relationships": [{{"source": "...", "target": "...", "type": "...", "description": "...", "weight": 0.8}}]}}

Text: {text}
"""

# Max text length sent to LLM per chunk (prevents token overflow)
_MAX_CHUNK_TEXT = 8000


class GraphEntityExtractorComponent(Node):
    """Extract entities and relationships from text using an LLM for knowledge graph construction."""

    display_name: str = "Graph Entity Extractor"
    description: str = (
        "Uses an LLM to extract named entities and relationships from text chunks. "
        "Outputs structured data ready for Neo4j Graph Store ingestion."
    )
    name = "GraphEntityExtractor"
    icon = "Sparkles"

    inputs = [
        # -- Input Data -------------------------------------------------
        HandleInput(
            name="documents",
            display_name="Text Chunks",
            input_types=["Data", "Message"],
            is_list=True,
            info="Text chunks from Text Splitter, Chat Input, or any Data/Message source. "
                 "Each item should have a 'text' field.",
        ),

        # -- LLM Connection ---------------------------------------------
        HandleInput(
            name="llm",
            display_name="Language Model",
            input_types=["LanguageModel"],
            info="LLM to use for entity extraction (e.g., GPT-4o-mini, Claude).",
        ),

        # -- Schema (optional, from Graph Schema Config) -------------------
        HandleInput(
            name="schema",
            display_name="Schema Config (Optional)",
            input_types=["Data"],
            info="Schema from Graph Schema Config. If connected, entity types, "
                 "relationship types, and extraction hints are applied automatically.",
        ),

        # -- Extraction Config ------------------------------------------
        StrInput(
            name="entity_types",
            display_name="Entity Types",
            value=DEFAULT_ENTITY_TYPES,
            info="Comma-separated list of entity types to extract. "
                 "Overridden by Schema Config if connected.",
        ),
        StrInput(
            name="relation_types",
            display_name="Relationship Types",
            value=DEFAULT_RELATION_TYPES,
            info="Comma-separated list of relationship types to use. "
                 "Overridden by Schema Config if connected.",
            advanced=True,
        ),
        MultilineInput(
            name="custom_prompt",
            display_name="Custom Extraction Prompt",
            info="Override the default extraction prompt. "
                 "Use {text}, {entity_types}, {relation_types} as placeholders.",
            advanced=True,
        ),
        IntInput(
            name="max_chunks",
            display_name="Max Chunks to Process",
            info="Limit the number of chunks processed (0 = no limit). "
                 "Useful for testing before full extraction.",
            value=0,
            advanced=True,
        ),
        DropdownInput(
            name="dedup_strategy",
            display_name="Deduplication Strategy",
            options=["Name Match", "Name + Type Match", "None"],
            value="Name + Type Match",
            advanced=True,
            info="How to deduplicate entities across chunks.",
        ),
        StrInput(
            name="graph_kb_id",
            display_name="Graph KB ID",
            info="Passed through to output Data for Neo4j Graph Store routing.",
            value="default",
            advanced=True,
        ),
    ]

    outputs = [
        Output(
            display_name="Entities",
            name="entities",
            method="extract_entities",
        ),
        Output(
            display_name="Extraction Stats",
            name="stats",
            method="get_extraction_stats",
        ),
    ]

    # ------------------------------------------------------------------
    # Schema resolution
    # ------------------------------------------------------------------

    def _resolve_schema(self) -> tuple[str, str, str]:
        """Resolve entity types, relation types, and prompt addendum from schema or inputs.

        Returns:
            (entity_types, relation_types, prompt_addendum)
        """
        entity_types = self.entity_types or DEFAULT_ENTITY_TYPES
        relation_types = self.relation_types or DEFAULT_RELATION_TYPES
        prompt_addendum = ""

        if self.schema and hasattr(self.schema, "data") and isinstance(self.schema.data, dict):
            schema_data = self.schema.data

            # Override entity types from schema
            schema_entity_names = schema_data.get("entity_type_names", [])
            if schema_entity_names and isinstance(schema_entity_names, list):
                entity_types = ", ".join(schema_entity_names)

            # Override relation types from schema
            schema_rel_names = schema_data.get("relationship_type_names", [])
            if schema_rel_names and isinstance(schema_rel_names, list):
                relation_types = ", ".join(schema_rel_names)

            # Build prompt addendum from schema details
            addendum_parts = []

            business_context = schema_data.get("business_context", "")
            if business_context:
                addendum_parts.append(f"Business context: {business_context}")

            extraction_hints = schema_data.get("extraction_hints", "")
            if extraction_hints:
                addendum_parts.append(f"Additional instructions: {extraction_hints}")

            if schema_data.get("strict_mode"):
                addendum_parts.append(
                    "STRICT MODE: Only extract entities and relationships of the types "
                    "listed above. Do NOT invent new types."
                )

            if addendum_parts:
                prompt_addendum = "\n\n" + "\n".join(addendum_parts)

            self.log(
                f"Schema applied: {len(schema_entity_names)} entity types, "
                f"{len(schema_rel_names)} relationship types"
                f"{', strict mode' if schema_data.get('strict_mode') else ''}"
            )

        return entity_types, relation_types, prompt_addendum

    # ------------------------------------------------------------------
    # Text extraction from various input types
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_text(doc: Data) -> str:
        """Extract text content from a Data item, handling various field names."""
        if not hasattr(doc, "data") or not isinstance(doc.data, dict):
            # Fall back to string representation
            text = getattr(doc, "text", None)
            return str(text) if text else ""

        data = doc.data
        # Try common text field names in priority order
        for key in ("text", "page_content", "content", "chunk_text", "body"):
            val = data.get(key)
            if val and isinstance(val, str) and val.strip():
                return val.strip()

        # Fall back to Data.text attribute
        text = getattr(doc, "text", None)
        return str(text).strip() if text else ""

    # ------------------------------------------------------------------
    # LLM call
    # ------------------------------------------------------------------

    def _call_llm(self, text: str, entity_types: str, relation_types: str, prompt_addendum: str = "") -> dict:
        """Call the LLM with the extraction prompt and parse JSON output."""
        prompt_template = self.custom_prompt or (
            EXTRACTION_PROMPT if len(text) > 200 else SIMPLE_EXTRACTION_PROMPT
        )

        prompt = prompt_template.format(
            text=text[:_MAX_CHUNK_TEXT],
            entity_types=entity_types,
            relation_types=relation_types,
        )

        if prompt_addendum:
            prompt += prompt_addendum

        # Call the LLM (LangChain BaseLanguageModel interface)
        try:
            response = self.llm.invoke(prompt)
            if hasattr(response, "content"):
                raw = response.content
            elif isinstance(response, str):
                raw = response
            else:
                raw = str(response)
        except Exception as e:
            logger.warning(f"[Graph Entity Extractor] LLM call failed: {e}")
            self.log(f"LLM call failed: {e}")
            return {"entities": [], "relationships": []}

        return self._parse_llm_json(raw)

    def _parse_llm_json(self, raw: str) -> dict:
        """Robustly parse JSON from LLM output, handling markdown fences and quirks."""
        text = raw.strip()
        if not text:
            return {"entities": [], "relationships": []}

        # Strip markdown code fences
        if text.startswith("```"):
            lines = text.split("\n")
            lines = [line for line in lines if not line.strip().startswith("```")]
            text = "\n".join(lines)

        # Attempt 1: direct parse
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass

        # Attempt 2: extract JSON object from response
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            try:
                parsed = json.loads(text[start:end])
                if isinstance(parsed, dict):
                    return parsed
            except json.JSONDecodeError:
                pass

        # Attempt 3: json_repair library (optional dependency)
        try:
            from json_repair import repair_json
            repaired = repair_json(text, return_objects=True)
            if isinstance(repaired, dict):
                return repaired
        except ImportError:
            pass
        except Exception as e:
            logger.debug(f"[Graph Entity Extractor] json_repair failed: {e}")

        logger.warning(f"[Graph Entity Extractor] Failed to parse LLM JSON: {text[:200]}...")
        self.log(f"Failed to parse LLM JSON output (first 200 chars): {text[:200]}")
        return {"entities": [], "relationships": []}

    # ------------------------------------------------------------------
    # Deduplication
    # ------------------------------------------------------------------

    def _dedup_key(self, entity: dict) -> str:
        """Generate a deduplication key for an entity."""
        name = (entity.get("name") or "").strip().lower()
        if not name:
            return ""
        strategy = (self.dedup_strategy or "Name + Type Match").lower()

        if "name + type" in strategy:
            etype = (entity.get("type") or "entity").strip().lower()
            return f"{name}::{etype}"
        elif "name" in strategy:
            return name
        else:
            # No dedup -- use content-based hash for deterministic IDs
            content = json.dumps(entity, sort_keys=True, default=str)
            return hashlib.sha256(content.encode()).hexdigest()[:16]

    # ------------------------------------------------------------------
    # Output: extract_entities
    # ------------------------------------------------------------------

    def extract_entities(self) -> list[Data]:
        """
        Main extraction method.

        For each input chunk:
          1. Call LLM to extract entities + relationships
          2. Deduplicate across chunks
          3. Merge relationship data
          4. Output list[Data] ready for Neo4j Graph Store
        """
        # Reset stats for this execution
        self._extraction_stats = {}

        documents = self.documents
        if not documents:
            self.status = "No documents provided."
            return []

        if not isinstance(documents, list):
            documents = [documents]

        if not self.llm:
            self.status = "No LLM connected."
            return []

        # Apply max_chunks limit
        max_chunks = self.max_chunks or 0
        if max_chunks > 0:
            documents = documents[:max_chunks]

        graph_kb_id = self.graph_kb_id or "default"

        # Resolve schema -> entity types, relation types, addendum
        entity_types, relation_types, prompt_addendum = self._resolve_schema()

        # Accumulate all entities + relationships across chunks
        all_entities: dict[str, dict] = {}  # dedup_key -> entity dict
        all_relationships: list[dict] = []
        total_chunks = len(documents)
        processed = 0
        skipped = 0
        errors = 0

        for idx, doc in enumerate(documents):
            if not isinstance(doc, Data):
                skipped += 1
                continue

            text = self._extract_text(doc)
            if not text or len(text) < 10:
                skipped += 1
                continue

            # Generate a deterministic chunk ID for source linking
            chunk_id = None
            if hasattr(doc, "data") and isinstance(doc.data, dict):
                chunk_id = doc.data.get("chunk_id") or doc.data.get("id")
            if not chunk_id:
                chunk_id = hashlib.sha256(text[:500].encode()).hexdigest()[:16]

            try:
                result = self._call_llm(text, entity_types, relation_types, prompt_addendum)
            except Exception as e:
                logger.warning(f"[Graph Entity Extractor] Chunk {idx + 1} extraction failed: {e}")
                self.log(f"Extraction failed for chunk {idx + 1}: {e}")
                errors += 1
                continue

            processed += 1

            # Process entities
            for entity in result.get("entities", []):
                name = (entity.get("name") or "").strip()
                if not name:
                    continue

                key = self._dedup_key(entity)
                if not key:
                    continue

                if key in all_entities:
                    existing = all_entities[key]
                    new_desc = (entity.get("description") or "").strip()
                    if len(new_desc) > len(existing.get("description", "")):
                        existing["description"] = new_desc
                    existing.setdefault("source_chunk_ids", []).append(chunk_id)
                else:
                    entity["source_chunk_ids"] = [chunk_id]
                    all_entities[key] = entity

            # Process relationships
            for rel in result.get("relationships", []):
                source = (rel.get("source") or "").strip()
                target = (rel.get("target") or "").strip()
                if source and target:
                    # Clamp weight to [0.0, 1.0]
                    weight = rel.get("weight", 0.8)
                    try:
                        weight = max(0.0, min(float(weight), 1.0))
                    except (ValueError, TypeError):
                        weight = 0.8

                    rel["weight"] = weight
                    rel["source_chunk_id"] = chunk_id
                    all_relationships.append(rel)

            # Progress logging every 10 chunks or at the end
            if processed % 10 == 0 or idx == total_chunks - 1:
                self.log(
                    f"Processed {processed}/{total_chunks} chunks "
                    f"({len(all_entities)} entities, {len(all_relationships)} relationships)"
                )

        # Build output Data items
        output_data: list[Data] = []
        for entity in all_entities.values():
            entity_name = (entity.get("name") or "").strip()
            if not entity_name:
                continue

            # Find relationships for this entity
            entity_rels = []
            for r in all_relationships:
                if (r.get("source") or "").strip().lower() == entity_name.lower():
                    entity_rels.append({
                        "target": (r.get("target") or "").strip(),
                        "target_type": "Entity",
                        "type": (r.get("type") or "RELATED_TO").strip(),
                        "description": (r.get("description") or "").strip(),
                        "weight": r.get("weight", 0.8),
                    })

            entity_type = (entity.get("type") or "Entity").strip()
            entity_desc = (entity.get("description") or "").strip()
            source_chunk_ids = entity.get("source_chunk_ids", [])

            output_data.append(Data(
                text=f"{entity_name} ({entity_type}): {entity_desc}",
                data={
                    "name": entity_name,
                    "type": entity_type,
                    "description": entity_desc,
                    "relationships": entity_rels,
                    "source_chunk_id": source_chunk_ids[0] if source_chunk_ids else None,
                    "source_chunk_ids": source_chunk_ids,
                    "graph_kb_id": graph_kb_id,
                },
            ))

        # Store stats on instance
        self._extraction_stats = {
            "total_chunks": total_chunks,
            "processed_chunks": processed,
            "skipped_chunks": skipped,
            "errors": errors,
            "unique_entities": len(all_entities),
            "total_relationships": len(all_relationships),
            "graph_kb_id": graph_kb_id,
        }

        self.status = (
            f"Extracted {len(all_entities)} entities, "
            f"{len(all_relationships)} relationships "
            f"from {processed}/{total_chunks} chunks"
            f"{f' ({errors} errors)' if errors else ''}."
        )
        return output_data

    # ------------------------------------------------------------------
    # Output: stats
    # ------------------------------------------------------------------

    def get_extraction_stats(self) -> Data:
        """Return extraction statistics."""
        if not hasattr(self, "_extraction_stats") or not self._extraction_stats:
            self.extract_entities()
        return Data(data=self._extraction_stats)
