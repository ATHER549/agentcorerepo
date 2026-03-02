"""
Graph Schema Config Component

Drag-and-drop node that lets users define the ontology (schema) for their
knowledge graph BEFORE entity extraction runs. This is a critical enterprise
requirement — without it, the LLM extracts arbitrary types which leads to
an inconsistent, unqueryable graph.

Canvas wiring:
  [Graph Schema Config] ──→ [Graph Entity Extractor]
                                     ↑
                                   [LLM]

What it defines:
  - Allowed entity types with descriptions and examples
  - Allowed relationship types with source→target constraints
  - Validation rules (required fields, cardinality, domain constraints)
  - Business domain context (helps LLM extract more accurately)

The output is a structured schema Data object that the Entity Extractor
reads to constrain its extraction prompt.
"""

from __future__ import annotations

import json
import re

from loguru import logger

from agentcore.custom.custom_node.node import Node
from agentcore.field_typing.range_spec import RangeSpec
from agentcore.io import (
    BoolInput,
    DropdownInput,
    FloatInput,
    MultilineInput,
    Output,
    StrInput,
    TableInput,
)
from agentcore.schema.data import Data


# Pre-built domain schemas for common use cases
DOMAIN_SCHEMAS = {
    "General": {
        "entity_types": [
            {"name": "Person", "description": "A named individual", "examples": "John Smith, Dr. Jane Doe"},
            {"name": "Organization", "description": "A company, institution, or group", "examples": "Google, MIT, WHO"},
            {"name": "Location", "description": "A geographic place", "examples": "New York, Europe, Building A"},
            {"name": "Concept", "description": "An abstract idea or topic", "examples": "Machine Learning, Democracy"},
            {"name": "Event", "description": "A named occurrence", "examples": "World War II, Product Launch"},
            {"name": "Document", "description": "A specific document or publication", "examples": "RFC 2616, Annual Report 2024"},
        ],
        "relationship_types": [
            {"name": "WORKS_AT", "source": "Person", "target": "Organization"},
            {"name": "LOCATED_IN", "source": "*", "target": "Location"},
            {"name": "PART_OF", "source": "*", "target": "*"},
            {"name": "RELATED_TO", "source": "*", "target": "*"},
            {"name": "CREATED_BY", "source": "*", "target": "Person"},
            {"name": "MENTIONS", "source": "Document", "target": "*"},
        ],
    },
    "Corporate / Business": {
        "entity_types": [
            {"name": "Employee", "description": "An employee or contractor", "examples": "John Smith (VP Engineering)"},
            {"name": "Department", "description": "An organizational unit", "examples": "Engineering, Sales, HR"},
            {"name": "Company", "description": "A corporation or subsidiary", "examples": "Acme Corp, TechStart Inc."},
            {"name": "Product", "description": "A product or service offering", "examples": "Widget Pro, CloudSync API"},
            {"name": "Project", "description": "A named project or initiative", "examples": "Project Phoenix, Q4 Migration"},
            {"name": "Policy", "description": "A business policy or procedure", "examples": "Remote Work Policy, SOC2 Compliance"},
            {"name": "Client", "description": "A customer or client organization", "examples": "BigBank Ltd, HealthCo"},
            {"name": "Technology", "description": "A technology, tool, or platform", "examples": "Kubernetes, Salesforce, Python"},
        ],
        "relationship_types": [
            {"name": "WORKS_IN", "source": "Employee", "target": "Department"},
            {"name": "MANAGES", "source": "Employee", "target": "Employee"},
            {"name": "REPORTS_TO", "source": "Employee", "target": "Employee"},
            {"name": "OWNS", "source": "Department", "target": "Product"},
            {"name": "WORKS_ON", "source": "Employee", "target": "Project"},
            {"name": "DEPENDS_ON", "source": "Product", "target": "Technology"},
            {"name": "SERVES", "source": "Company", "target": "Client"},
            {"name": "GOVERNS", "source": "Policy", "target": "*"},
            {"name": "SUBSIDIARY_OF", "source": "Company", "target": "Company"},
        ],
    },
    "Legal / Compliance": {
        "entity_types": [
            {"name": "Regulation", "description": "A law, regulation, or standard", "examples": "GDPR, SOX, ISO 27001"},
            {"name": "Clause", "description": "A specific section or clause", "examples": "Article 17, Section 3.2"},
            {"name": "Party", "description": "A legal party (person or org)", "examples": "Plaintiff, ABC Corp"},
            {"name": "Obligation", "description": "A required action or duty", "examples": "Data retention, annual audit"},
            {"name": "Risk", "description": "An identified risk or threat", "examples": "Data breach, non-compliance"},
            {"name": "Control", "description": "A mitigation control or measure", "examples": "Encryption, access review"},
            {"name": "Jurisdiction", "description": "A legal jurisdiction", "examples": "EU, State of California"},
        ],
        "relationship_types": [
            {"name": "CONTAINS", "source": "Regulation", "target": "Clause"},
            {"name": "REQUIRES", "source": "Regulation", "target": "Obligation"},
            {"name": "MITIGATES", "source": "Control", "target": "Risk"},
            {"name": "SUBJECT_TO", "source": "Party", "target": "Regulation"},
            {"name": "APPLIES_IN", "source": "Regulation", "target": "Jurisdiction"},
            {"name": "VIOLATES", "source": "Party", "target": "Clause"},
        ],
    },
    "Healthcare / Life Sciences": {
        "entity_types": [
            {"name": "Disease", "description": "A medical condition or disease", "examples": "Diabetes Type 2, COVID-19"},
            {"name": "Drug", "description": "A medication or therapeutic", "examples": "Metformin, Remdesivir"},
            {"name": "Gene", "description": "A gene or biomarker", "examples": "BRCA1, TP53, IL-6"},
            {"name": "Protein", "description": "A protein or enzyme", "examples": "Insulin, ACE2"},
            {"name": "Symptom", "description": "A clinical symptom", "examples": "Fever, fatigue, chest pain"},
            {"name": "Treatment", "description": "A treatment protocol", "examples": "Chemotherapy, CBT, surgery"},
            {"name": "ClinicalTrial", "description": "A clinical study", "examples": "NCT04280705"},
            {"name": "Researcher", "description": "A researcher or physician", "examples": "Dr. Fauci, Dr. Zhang"},
        ],
        "relationship_types": [
            {"name": "TREATS", "source": "Drug", "target": "Disease"},
            {"name": "CAUSES", "source": "Gene", "target": "Disease"},
            {"name": "ENCODES", "source": "Gene", "target": "Protein"},
            {"name": "PRESENTS_WITH", "source": "Disease", "target": "Symptom"},
            {"name": "TARGETS", "source": "Drug", "target": "Protein"},
            {"name": "STUDIES", "source": "ClinicalTrial", "target": "Drug"},
            {"name": "INTERACTS_WITH", "source": "Drug", "target": "Drug"},
            {"name": "LEADS", "source": "Researcher", "target": "ClinicalTrial"},
        ],
    },
    "IT / Software": {
        "entity_types": [
            {"name": "Service", "description": "A software service or microservice", "examples": "Auth Service, Payment API"},
            {"name": "Database", "description": "A database or data store", "examples": "PostgreSQL users_db, Redis cache"},
            {"name": "API", "description": "An API endpoint or interface", "examples": "/api/v2/users, GraphQL schema"},
            {"name": "Team", "description": "An engineering team", "examples": "Platform Team, DevOps"},
            {"name": "Incident", "description": "A production incident", "examples": "INC-2024-0156"},
            {"name": "Library", "description": "A software library or dependency", "examples": "React 18, FastAPI, lodash"},
            {"name": "Infrastructure", "description": "Infrastructure component", "examples": "AWS us-east-1, k8s cluster-prod"},
            {"name": "Configuration", "description": "A config or feature flag", "examples": "ENABLE_SSO, max_retries=3"},
        ],
        "relationship_types": [
            {"name": "DEPENDS_ON", "source": "Service", "target": "Service"},
            {"name": "READS_FROM", "source": "Service", "target": "Database"},
            {"name": "WRITES_TO", "source": "Service", "target": "Database"},
            {"name": "EXPOSES", "source": "Service", "target": "API"},
            {"name": "OWNS", "source": "Team", "target": "Service"},
            {"name": "AFFECTED", "source": "Incident", "target": "Service"},
            {"name": "USES", "source": "Service", "target": "Library"},
            {"name": "DEPLOYED_ON", "source": "Service", "target": "Infrastructure"},
            {"name": "CONFIGURED_BY", "source": "Service", "target": "Configuration"},
        ],
    },
    "Custom": {
        "entity_types": [],
        "relationship_types": [],
    },
}


class GraphSchemaConfigComponent(Node):
    """Define the ontology (entity types, relationship types, constraints) for knowledge graph extraction."""

    display_name: str = "Graph Schema Config"
    description: str = (
        "Define the schema/ontology for your knowledge graph. "
        "Select a pre-built domain or customize entity types, relationship types, "
        "and validation rules. Feeds into Graph Entity Extractor."
    )
    name = "GraphSchemaConfig"
    icon = "Settings2"

    inputs = [
        # ── Domain Template ────────────────────────────────────
        DropdownInput(
            name="domain",
            display_name="Domain Template",
            options=list(DOMAIN_SCHEMAS.keys()),
            value="General",
            info="Pre-built schema for common domains. Select 'Custom' to define your own.",
            real_time_refresh=True,
        ),

        # ── Business Context ──────────────────────────────────
        MultilineInput(
            name="business_context",
            display_name="Business Context",
            info="Describe your business domain so the LLM understands context during extraction. "
                 "Example: 'We are a fintech company. Documents contain regulatory filings, "
                 "compliance reports, and internal policies.'",
            value="",
        ),

        # ── Custom Entity Types ────────────────────────────────
        TableInput(
            name="custom_entity_types",
            display_name="Entity Types",
            info="Define entity types for extraction. "
                 "Each row: name, description, examples. "
                 "Pre-populated from domain template; customize as needed.",
            value=[],
        ),

        # ── Custom Relationship Types ──────────────────────────
        TableInput(
            name="custom_relationship_types",
            display_name="Relationship Types",
            info="Define allowed relationships between entities. "
                 "Each row: name, source type ('*' = any), target type ('*' = any). "
                 "Pre-populated from domain template.",
            value=[],
        ),

        # ── Validation Rules ───────────────────────────────────
        BoolInput(
            name="strict_mode",
            display_name="Strict Mode",
            info="If enabled, only allow entity/relationship types defined in this schema. "
                 "If disabled, allow the LLM to discover additional types beyond the schema.",
            value=False,
            advanced=True,
        ),
        BoolInput(
            name="require_descriptions",
            display_name="Require Entity Descriptions",
            info="Reject entities that have no description from the extraction.",
            value=False,
            advanced=True,
        ),
        FloatInput(
            name="min_relationship_weight",
            display_name="Min Relationship Weight",
            info="Filter out relationships below this confidence weight (0.0-1.0).",
            value=0.0,
            advanced=True,
            range_spec=RangeSpec(min=0.0, max=1.0, step=0.05),
        ),
        StrInput(
            name="entity_name_regex",
            display_name="Entity Name Pattern",
            info="Regex to validate entity names. "
                 "Example: '^[A-Z]' = must start with uppercase. Leave empty for no validation.",
            value="",
            advanced=True,
        ),

        # ── Extraction Hints ──────────────────────────────────
        MultilineInput(
            name="extraction_hints",
            display_name="Extraction Hints",
            info="Additional instructions appended to the extraction prompt. "
                 "Example: 'Focus on people and their organizational roles. "
                 "Ignore generic terms like data, system, process.'",
            value="",
            advanced=True,
        ),
    ]

    outputs = [
        Output(
            display_name="Schema",
            name="schema",
            method="build_schema",
        ),
        Output(
            display_name="Extraction Prompt Addendum",
            name="prompt_addendum",
            method="build_prompt_addendum",
        ),
    ]

    # ------------------------------------------------------------------
    # Merge domain template + custom overrides
    # ------------------------------------------------------------------

    def _get_merged_entity_types(self) -> list[dict]:
        """Merge domain template entity types with user customizations."""
        domain = self.domain or "General"
        template = DOMAIN_SCHEMAS.get(domain, DOMAIN_SCHEMAS["General"])
        base_types = list(template.get("entity_types", []))

        # User overrides via table
        custom = self.custom_entity_types or []
        if custom and isinstance(custom, list):
            # User provided rows — merge or replace
            existing_names = {et["name"].lower() for et in base_types}
            for row in custom:
                if isinstance(row, dict) and row.get("name"):
                    name_lower = row["name"].strip().lower()
                    if name_lower not in existing_names:
                        base_types.append({
                            "name": row["name"].strip(),
                            "description": row.get("description", ""),
                            "examples": row.get("examples", ""),
                        })
                        existing_names.add(name_lower)

        return base_types

    def _get_merged_relationship_types(self) -> list[dict]:
        """Merge domain template relationship types with user customizations."""
        domain = self.domain or "General"
        template = DOMAIN_SCHEMAS.get(domain, DOMAIN_SCHEMAS["General"])
        base_rels = list(template.get("relationship_types", []))

        custom = self.custom_relationship_types or []
        if custom and isinstance(custom, list):
            existing_names = {rt["name"].lower() for rt in base_rels}
            for row in custom:
                if isinstance(row, dict) and row.get("name"):
                    name_lower = row["name"].strip().lower()
                    if name_lower not in existing_names:
                        base_rels.append({
                            "name": row["name"].strip().upper().replace(" ", "_"),
                            "source": row.get("source", "*"),
                            "target": row.get("target", "*"),
                        })
                        existing_names.add(name_lower)

        return base_rels

    # ------------------------------------------------------------------
    # Output: build_schema
    # ------------------------------------------------------------------

    def build_schema(self) -> Data:
        """
        Build the complete schema configuration as a structured Data object.
        This is consumed by Graph Entity Extractor and Graph Transformer.
        """
        entity_types = self._get_merged_entity_types()
        relationship_types = self._get_merged_relationship_types()

        min_weight = 0.0
        try:
            min_weight = max(0.0, min(float(self.min_relationship_weight or 0.0), 1.0))
        except (ValueError, TypeError):
            min_weight = 0.0

        # Validate regex pattern if provided
        entity_name_regex = (self.entity_name_regex or "").strip()
        if entity_name_regex:
            try:
                re.compile(entity_name_regex)
            except re.error as e:
                logger.warning(f"[Graph Schema Config] Invalid entity_name_regex: {e}")
                self.log(f"Invalid regex pattern '{entity_name_regex}': {e}. Ignoring.")
                entity_name_regex = ""

        schema = {
            "domain": self.domain or "General",
            "business_context": (self.business_context or "").strip(),
            "entity_types": entity_types,
            "relationship_types": relationship_types,
            "strict_mode": bool(self.strict_mode),
            "require_descriptions": bool(self.require_descriptions),
            "min_relationship_weight": min_weight,
            "entity_name_regex": entity_name_regex,
            "extraction_hints": (self.extraction_hints or "").strip(),
            # Flatten for convenience
            "entity_type_names": [et["name"] for et in entity_types if et.get("name")],
            "relationship_type_names": [rt["name"] for rt in relationship_types if rt.get("name")],
        }

        self.status = (
            f"Schema: {len(entity_types)} entity types, "
            f"{len(relationship_types)} relationship types "
            f"({self.domain})"
        )

        return Data(
            text=json.dumps(schema, indent=2),
            data=schema,
        )

    # ------------------------------------------------------------------
    # Output: prompt_addendum
    # ------------------------------------------------------------------

    def build_prompt_addendum(self) -> Data:
        """
        Generate a text block that can be appended to the Entity Extractor's
        extraction prompt to constrain it to this schema.
        """
        entity_types = self._get_merged_entity_types()
        relationship_types = self._get_merged_relationship_types()

        lines = []

        # Business context
        if self.business_context:
            lines.append(f"## Business Context\n{self.business_context}\n")

        # Entity types
        lines.append("## Allowed Entity Types")
        for et in entity_types:
            desc = et.get("description", "")
            examples = et.get("examples", "")
            line = f"- **{et['name']}**: {desc}"
            if examples:
                line += f" (e.g., {examples})"
            lines.append(line)
        lines.append("")

        # Relationship types
        lines.append("## Allowed Relationship Types")
        for rt in relationship_types:
            source = rt.get("source", "*")
            target = rt.get("target", "*")
            lines.append(f"- **{rt['name']}**: {source} → {target}")
        lines.append("")

        # Strict mode instruction
        if self.strict_mode:
            lines.append(
                "## STRICT MODE: Only extract entities and relationships of the types listed above. "
                "Do NOT invent new types."
            )
        else:
            lines.append(
                "## NOTE: Prefer the types listed above, but you may introduce new types "
                "if the text clearly contains entities that don't fit the schema."
            )

        # Custom hints
        if self.extraction_hints:
            lines.append(f"\n## Additional Instructions\n{self.extraction_hints}")

        text = "\n".join(lines)
        self.status = f"Prompt addendum: {len(lines)} lines"

        return Data(text=text, data={"addendum": text})
