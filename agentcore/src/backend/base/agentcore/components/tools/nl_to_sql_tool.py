"""Talk to Data Tool — LCToolNode wrapper for Worker Node integration.

Exposes the NL-to-SQL pipeline as a LangChain StructuredTool so it can be
connected to the Worker Node's "Tools" input.  The Worker Node agent calls
this tool when the user asks a data/metrics question.

The output includes a <data_json> block containing the raw query results as
JSON — the Data Visualizer Tool can consume this directly when the user also
wants a chart.

Reuses validation and formatting helpers from the existing nl_to_sql module.
"""

import json
import time
from typing import Any

from langchain_core.tools import StructuredTool, ToolException
from pydantic import BaseModel, Field

from agentcore.base.langchain_utilities.model import LCToolNode
from agentcore.field_typing import Tool
from agentcore.inputs.inputs import (
    HandleInput,
    IntInput,
    MultilineInput,
    TableInput,
)
from agentcore.schema.data import Data
from agentcore.logging import logger

# Reuse helpers from the existing NL-to-SQL component
from agentcore.components.tools.nl_to_sql import (
    _validate_sql,
    _format_results_as_markdown,
)


class TalkToDataTool(LCToolNode):
    """Query a database using natural language — as a Worker Node tool.

    Connects to a Database Connector and an LLM.  When the Worker Node agent
    calls this tool it receives a user question, generates SQL via the LLM,
    validates safety (SELECT-only), executes, and returns formatted results.
    """

    display_name = "Talk to Data Tool"
    description = (
        "A tool that queries a database using natural language. "
        "Connect a Database Connector and LLM, then wire this into a Worker Node's Tools input."
    )
    icon = "message-square-code"
    name = "TalkToDataTool"

    inputs = [
        HandleInput(
            name="llm",
            display_name="Language Model",
            input_types=["LanguageModel"],
            required=True,
            info="The LLM used to generate SQL from natural language.",
        ),
        HandleInput(
            name="db_connection",
            display_name="Database Connection",
            input_types=["Data"],
            required=True,
            info="Database connection config from a Database Connector component.",
        ),
        IntInput(
            name="max_rows",
            display_name="Max Result Rows",
            value=100,
            info="Maximum number of rows to return.",
            advanced=True,
        ),
        TableInput(
            name="few_shot_examples",
            display_name="Example Q&A Pairs",
            info="Example question-to-SQL pairs to improve accuracy.",
            table_schema=[
                {
                    "name": "question",
                    "display_name": "Question",
                    "type": "str",
                    "description": "Example natural language question",
                },
                {
                    "name": "sql",
                    "display_name": "SQL Query",
                    "type": "str",
                    "description": "The correct SQL for this question",
                },
            ],
            value=[],
            advanced=True,
        ),
        MultilineInput(
            name="additional_context",
            display_name="Domain Context",
            value="",
            info="Additional context about the data domain to help the LLM.",
            advanced=True,
        ),
        TableInput(
            name="table_relationships",
            display_name="Table Relationships",
            info="Define foreign key relationships between tables to help the LLM generate correct JOINs.",
            table_schema=[
                {
                    "name": "source_table",
                    "display_name": "Source Table",
                    "type": "str",
                    "description": "The table containing the foreign key column",
                },
                {
                    "name": "source_column",
                    "display_name": "Source Column",
                    "type": "str",
                    "description": "The FK column in the source table",
                },
                {
                    "name": "target_table",
                    "display_name": "Target Table",
                    "type": "str",
                    "description": "The referenced (parent) table",
                },
                {
                    "name": "target_column",
                    "display_name": "Target Column",
                    "type": "str",
                    "description": "The referenced column (usually the primary key)",
                },
            ],
            value=[],
            advanced=True,
        ),
        TableInput(
            name="column_descriptions",
            display_name="Column Descriptions",
            info="Add business-friendly descriptions for columns to help the LLM understand domain semantics.",
            table_schema=[
                {
                    "name": "table_name",
                    "display_name": "Table",
                    "type": "str",
                    "description": "Table name",
                },
                {
                    "name": "column_name",
                    "display_name": "Column",
                    "type": "str",
                    "description": "Column name",
                },
                {
                    "name": "description",
                    "display_name": "Description",
                    "type": "str",
                    "description": "Business-friendly description of what this column represents",
                },
            ],
            value=[],
            advanced=True,
        ),
        MultilineInput(
            name="business_rules",
            display_name="Business Rules",
            value="",
            info="Business rules the LLM should follow when generating SQL (e.g., 'status=active means not deleted', 'revenue = amount - discount - refund').",
            advanced=True,
        ),
        IntInput(
            name="query_timeout",
            display_name="Query Timeout (seconds)",
            value=30,
            info="Maximum time to wait for query execution.",
            advanced=True,
        ),
    ]

    # ----- Pydantic schema for the tool arguments -----

    class _ToolSchema(BaseModel):
        user_question: str = Field(
            ...,
            description=(
                "The natural language question to answer using the database. "
                "For example: 'What are the top 5 suppliers by total order amount?'"
            ),
        )

    # ----- LCToolNode interface -----

    def run_model(self) -> list[Data]:
        """Standalone execution (when not used as a tool)."""
        result = self._run_pipeline("Sample question — use via Worker Node tool.")
        return [Data(data=result)]

    def build_tool(self) -> Tool:
        """Build the LangChain StructuredTool for Worker Node."""
        return StructuredTool.from_function(
            name="talk_to_data",
            description=(
                "Query a database using natural language. Given a question about data, "
                "metrics, KPIs, or records, this tool generates a SQL query, executes it, "
                "and returns the results as a formatted table. "
                "ALWAYS call this tool first for ANY data question. "
                "If the user also wants a chart or visualization, call this tool first "
                "to get the data, then pass the <data_json> block from this tool's "
                "response to the data_visualizer tool."
            ),
            func=self._tool_invoke,
            args_schema=self._ToolSchema,
        )

    # ----- Core logic -----

    def _tool_invoke(self, user_question: str) -> str:
        """Entry point when called by the Worker Node agent."""
        try:
            result = self._run_pipeline(user_question)
            if result.get("error"):
                return f"Error: {result['message']}"
            return result["formatted_text"]
        except Exception as e:
            raise ToolException(str(e)) from e

    def _get_db_config(self) -> dict:
        """Extract database config from the connected Database Connector."""
        db_data = self.db_connection
        if isinstance(db_data, Data):
            return db_data.data
        if isinstance(db_data, dict):
            return db_data
        return {}

    def _build_prompt(self, schema_ddl: str, user_question: str, db_config: dict | None = None) -> str:
        """Build the SQL generation prompt."""
        few_shot_text = ""
        if self.few_shot_examples:
            examples = []
            for ex in self.few_shot_examples:
                if isinstance(ex, dict) and ex.get("question") and ex.get("sql"):
                    examples.append(f"Q: {ex['question']}\nSQL: {ex['sql']}")
            if examples:
                few_shot_text = "\n\n**Example question-to-SQL pairs:**\n" + "\n\n".join(examples) + "\n"

        domain_context = ""
        if self.additional_context and self.additional_context.strip():
            domain_context = f"\n\n**Domain Context:**\n{self.additional_context.strip()}\n"

        # Table relationships: merge auto-discovered FKs from DB Connector + manual entries
        relationships_text = ""
        all_relationships = []

        # Auto-discovered FKs from Database Connector
        if db_config:
            auto_fks = db_config.get("foreign_keys", [])
            if auto_fks and isinstance(auto_fks, list):
                all_relationships.extend(auto_fks)

        # Manual user-defined relationships (supplement / override)
        if self.table_relationships:
            all_relationships.extend(self.table_relationships)

        # Deduplicate by (source_table, source_column, target_table, target_column)
        seen = set()
        unique_rels = []
        for rel in all_relationships:
            if isinstance(rel, dict) and rel.get("source_table") and rel.get("target_table"):
                key = (rel["source_table"], rel.get("source_column", ""),
                       rel["target_table"], rel.get("target_column", ""))
                if key not in seen:
                    seen.add(key)
                    unique_rels.append(rel)

        if unique_rels:
            rels = [
                f"  {rel['source_table']}.{rel.get('source_column', '?')} -> "
                f"{rel['target_table']}.{rel.get('target_column', '?')}"
                for rel in unique_rels
            ]
            relationships_text = (
                "\n\n**Table Relationships (Foreign Keys):**\n"
                + "\n".join(rels)
                + "\nUse these relationships for JOIN conditions.\n"
            )

        # Column descriptions (business glossary)
        col_desc_text = ""
        if self.column_descriptions:
            descs = []
            for cd in self.column_descriptions:
                if isinstance(cd, dict) and cd.get("table_name") and cd.get("column_name") and cd.get("description"):
                    descs.append(f"  {cd['table_name']}.{cd['column_name']}: {cd['description']}")
            if descs:
                col_desc_text = (
                    "\n\n**Column Descriptions (Business Glossary):**\n"
                    + "\n".join(descs)
                    + "\n"
                )

        # Business rules
        business_rules_text = ""
        if self.business_rules and self.business_rules.strip():
            business_rules_text = f"\n\n**Business Rules:**\n{self.business_rules.strip()}\n"

        return f"""You are an expert SQL analyst. Given a database schema and a natural language question,
generate a precise SQL query to answer the question.

**Database Schema:**
```sql
{schema_ddl}
```
{relationships_text}{col_desc_text}{domain_context}{business_rules_text}{few_shot_text}
**User Question:** {user_question}

**Rules:**
1. Generate ONLY a SELECT query - never use INSERT, UPDATE, DELETE, DROP, or any DDL/DML
2. Use proper table and column names from the schema exactly as shown
3. Use appropriate JOINs when data spans multiple tables - refer to the Table Relationships above for correct join keys
4. Add meaningful aliases for calculated columns
5. Use LIMIT {self.max_rows} to cap results
6. If the question involves time periods, use appropriate date functions
7. For aggregations, always include GROUP BY
8. Return ONLY the SQL query, no explanations

**SQL Query:**"""

    def _invoke_llm(self, prompt: str) -> str:
        """Call the LLM from a clean thread (no event loop conflict).

        The Worker Node agent runs in an async event loop.  LangChain's
        .invoke() internally uses asyncio too, causing "Future attached to
        a different loop" errors.  Running .invoke() in a dedicated thread
        gives it a fresh event loop context.
        """
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(self.llm.invoke, prompt)
            response = future.result(timeout=120)

        if hasattr(response, "content"):
            return response.content
        if hasattr(response, "text"):
            return response.text
        return str(response)

    def _execute_sql(self, db_config: dict, sql: str) -> tuple[list[str], list[tuple]]:
        """Execute SQL against the database."""
        provider = db_config.get("provider", "postgresql")

        if provider == "postgresql":
            import psycopg2

            conn_kwargs = {
                "host": db_config["host"],
                "port": db_config["port"],
                "dbname": db_config["database_name"],
                "user": db_config["username"],
                "password": db_config["password"],
                "connect_timeout": 15,
                "options": f"-c statement_timeout={self.query_timeout * 1000}",
            }
            if db_config.get("ssl_enabled"):
                conn_kwargs["sslmode"] = "require"

            conn = psycopg2.connect(**conn_kwargs)
            try:
                cur = conn.cursor()
                cur.execute(sql)
                columns = [desc[0] for desc in cur.description] if cur.description else []
                rows = cur.fetchall() if columns else []
                cur.close()
                return columns, rows
            finally:
                conn.close()
        else:
            raise ValueError(f"Provider '{provider}' not yet supported")

    def _run_pipeline(self, user_question: str) -> dict:
        """Full NL-to-SQL pipeline: prompt → LLM → validate → execute → format."""
        db_config = self._get_db_config()
        schema_ddl = db_config.get("schema_ddl", "")

        if not schema_ddl:
            return {"error": True, "message": "No schema information available. Check the Database Connector."}

        if not user_question or not user_question.strip():
            return {"error": True, "message": "No question provided."}

        # Step 1: Generate SQL
        prompt = self._build_prompt(schema_ddl, user_question, db_config)
        try:
            generated_sql = self._invoke_llm(prompt)
        except Exception as e:
            return {"error": True, "message": f"LLM SQL generation failed: {e!s}"}

        # Clean markdown fences
        sql = generated_sql.strip()
        if sql.startswith("```sql"):
            sql = sql[6:]
        if sql.startswith("```"):
            sql = sql[3:]
        if sql.endswith("```"):
            sql = sql[:-3]
        sql = sql.strip()

        # Step 2: Validate
        is_valid, msg = _validate_sql(sql)
        if not is_valid:
            return {"error": True, "message": f"SQL validation failed: {msg}\n\nGenerated SQL:\n```sql\n{sql}\n```"}

        # Step 3: Execute
        try:
            start = time.time()
            columns, rows = self._execute_sql(db_config, sql)
            exec_time = round((time.time() - start) * 1000, 2)
        except Exception as e:
            return {"error": True, "message": f"Query execution failed: {e!s}\n\nSQL:\n```sql\n{sql}\n```"}

        # Step 4: Format
        rows_as_lists = [list(r) for r in rows]
        md_table = _format_results_as_markdown(columns, [tuple(r) for r in rows])
        parts = [
            f"**Query Results** ({len(rows)} rows, {exec_time}ms)\n",
            f"**Generated SQL:**\n```sql\n{sql}\n```\n",
            md_table,
        ]

        # Include raw data as JSON so the data_visualizer tool can consume it
        data_json = json.dumps({"columns": columns, "rows": rows_as_lists}, default=str)
        parts.append(f"\n<data_json>{data_json}</data_json>")

        # If the user's question mentions visualization, remind the agent to chain tools
        viz_keywords = {"chart", "graph", "plot", "visuali", "pie", "bar chart", "line chart", "scatter", "draw", "diagram"}
        question_lower = user_question.lower()
        if any(kw in question_lower for kw in viz_keywords):
            parts.append(
                "\n\n[AGENT NOTE: The user asked for a visualization. "
                "You MUST now call the data_visualizer tool with the <data_json> above. "
                "Do NOT respond to the user yet.]"
            )

        return {
            "error": False,
            "formatted_text": "\n".join(parts),
            "generated_sql": sql,
            "columns": columns,
            "rows": rows_as_lists,
            "row_count": len(rows),
            "execution_time_ms": exec_time,
        }