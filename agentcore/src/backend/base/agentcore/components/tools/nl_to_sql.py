"""Talk to Data (NL → SQL) component for the Agent Builder.

Takes a natural language question, generates SQL using an LLM with schema context,
executes the query against the database, and returns formatted results.
"""

import json
import time
from typing import Any

import sqlparse

from agentcore.custom.custom_node.node import Node
from agentcore.inputs.inputs import (
    BoolInput,
    HandleInput,
    IntInput,
    MessageTextInput,
    MultilineInput,
    TableInput,
)
from agentcore.schema.data import Data
from agentcore.schema.message import Message
from agentcore.template.field.base import Output
from agentcore.logging import logger


# SQL safety: Only these statement types are allowed
_ALLOWED_SQL_TYPES = {"SELECT"}
_BLOCKED_KEYWORDS = {
    "DROP", "DELETE", "INSERT", "UPDATE", "ALTER", "CREATE", "TRUNCATE",
    "GRANT", "REVOKE", "EXEC", "EXECUTE", "CALL", "MERGE",
}


def _validate_sql(sql: str) -> tuple[bool, str]:
    """Validate that SQL is a safe SELECT query."""
    sql_stripped = sql.strip().rstrip(";")
    if not sql_stripped:
        return False, "Empty SQL query"

    try:
        parsed = sqlparse.parse(sql_stripped)
        if not parsed:
            return False, "Failed to parse SQL"

        for statement in parsed:
            stmt_type = statement.get_type()
            if stmt_type and stmt_type.upper() not in _ALLOWED_SQL_TYPES:
                return False, f"Only SELECT queries are allowed. Got: {stmt_type}"
    except Exception as e:
        return False, f"SQL parse error: {e!s}"

    # Keyword check as extra safety layer
    sql_upper = sql_stripped.upper()
    for kw in _BLOCKED_KEYWORDS:
        # Check for keyword as a standalone word (not inside a string)
        tokens = sql_upper.split()
        if kw in tokens:
            return False, f"Blocked keyword detected: {kw}"

    return True, "OK"


def _format_results_as_markdown(columns: list[str], rows: list[tuple], max_display: int = 50) -> str:
    """Format query results as a markdown table."""
    if not rows:
        return "_No results found._"

    display_rows = rows[:max_display]

    # Build header
    header = "| " + " | ".join(str(c) for c in columns) + " |"
    separator = "| " + " | ".join("---" for _ in columns) + " |"

    # Build rows
    row_lines = []
    for row in display_rows:
        cells = []
        for val in row:
            if val is None:
                cells.append("NULL")
            elif isinstance(val, float):
                cells.append(f"{val:,.2f}")
            elif isinstance(val, int) and abs(val) > 999:
                cells.append(f"{val:,}")
            else:
                cells.append(str(val)[:100])  # Truncate long values
        row_lines.append("| " + " | ".join(cells) + " |")

    table = "\n".join([header, separator] + row_lines)

    if len(rows) > max_display:
        table += f"\n\n_...showing {max_display} of {len(rows)} total rows._"

    return table


class NLtoSQLComponent(Node):
    """Talk to Data: Converts natural language questions to SQL queries.

    Uses an LLM to understand the user's question in the context of the database schema,
    generates a safe SQL query, executes it, and returns formatted results.
    """

    display_name = "Talk to Data (NL→SQL)"
    description = "Convert natural language questions to SQL queries, execute them, and return results."
    icon = "message-square-code"
    name = "NLtoSQL"
    hidden = True

    inputs = [
        HandleInput(
            name="llm",
            display_name="Language Model",
            input_types=["LanguageModel"],
            required=True,
            info="The LLM that will generate SQL queries from natural language.",
        ),
        HandleInput(
            name="db_connection",
            display_name="Database Connection",
            input_types=["Data"],
            required=True,
            info="Database connection config from a Database Connector component.",
        ),
        MessageTextInput(
            name="user_query",
            display_name="User Question",
            required=True,
            info="The natural language question to answer using database data.",
        ),
        IntInput(
            name="max_rows",
            display_name="Max Result Rows",
            value=100,
            info="Maximum number of rows to return from the query.",
            advanced=True,
        ),
        BoolInput(
            name="include_sql",
            display_name="Show Generated SQL",
            value=True,
            info="Include the generated SQL query in the response.",
            advanced=True,
        ),
        TableInput(
            name="few_shot_examples",
            display_name="Example Q&A Pairs",
            info="Provide example question-to-SQL pairs to improve accuracy.",
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
            info="Additional context about the data domain to help the LLM generate better SQL.",
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

    outputs = [
        Output(
            display_name="Result",
            name="result",
            method="run_query",
            types=["Message"],
        ),
        Output(
            display_name="Raw Data",
            name="raw_data",
            method="run_query_raw",
            types=["Data"],
        ),
    ]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._cached_result: dict | None = None

    def _build_sql_generation_prompt(self, schema_ddl: str, user_query: str, db_config: dict | None = None) -> str:
        """Build the prompt for SQL generation."""
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

        prompt = f"""You are an expert SQL analyst. Given a database schema and a natural language question,
generate a precise SQL query to answer the question.

**Database Schema:**
```sql
{schema_ddl}
```
{relationships_text}{col_desc_text}{domain_context}{business_rules_text}{few_shot_text}
**User Question:** {user_query}

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

        return prompt

    def _execute_sql(self, db_config: dict, sql: str) -> tuple[list[str], list[tuple]]:
        """Execute SQL against the database and return columns + rows."""
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
            raise ValueError(f"Provider '{provider}' not yet supported for query execution")

    def _run_nl_to_sql(self) -> dict:
        """Core logic: Generate SQL from NL, execute, return structured result."""
        if self._cached_result is not None:
            return self._cached_result

        db_data = self.db_connection
        logger.info(f"NL-to-SQL: db_connection type={type(db_data).__name__}, value={repr(db_data)[:500]}")

        if isinstance(db_data, Data):
            db_config = db_data.data
        elif isinstance(db_data, dict):
            db_config = db_data
        else:
            db_config = {}

        logger.info(f"NL-to-SQL: db_config keys={list(db_config.keys()) if db_config else 'empty'}, schema_ddl length={len(db_config.get('schema_ddl', ''))}")

        schema_ddl = db_config.get("schema_ddl", "")
        if not schema_ddl:
            self._cached_result = {
                "error": True,
                "message": "No schema information available. Please check the Database Connector.",
            }
            return self._cached_result

        user_query = self.user_query
        if not user_query or not user_query.strip():
            self._cached_result = {
                "error": True,
                "message": "No question provided.",
            }
            return self._cached_result

        # Step 1: Generate SQL using LLM
        prompt = self._build_sql_generation_prompt(schema_ddl, user_query, db_config)

        try:
            import asyncio
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    import concurrent.futures
                    with concurrent.futures.ThreadPoolExecutor() as executor:
                        future = executor.submit(asyncio.run, self.llm.ainvoke(prompt))
                        response = future.result()
                else:
                    response = loop.run_until_complete(self.llm.ainvoke(prompt))
            except RuntimeError:
                response = asyncio.run(self.llm.ainvoke(prompt))

            if hasattr(response, "content"):
                generated_sql = response.content
            elif hasattr(response, "text"):
                generated_sql = response.text
            else:
                generated_sql = str(response)
        except Exception as e:
            self._cached_result = {
                "error": True,
                "message": f"LLM SQL generation failed: {e!s}",
            }
            return self._cached_result

        # Clean up SQL (remove markdown code fences if present)
        sql = generated_sql.strip()
        if sql.startswith("```sql"):
            sql = sql[6:]
        if sql.startswith("```"):
            sql = sql[3:]
        if sql.endswith("```"):
            sql = sql[:-3]
        sql = sql.strip()

        # Step 2: Validate SQL safety
        is_valid, validation_msg = _validate_sql(sql)
        if not is_valid:
            self._cached_result = {
                "error": True,
                "message": f"SQL validation failed: {validation_msg}\n\nGenerated SQL:\n```sql\n{sql}\n```",
                "generated_sql": sql,
            }
            return self._cached_result

        # Step 3: Execute SQL
        try:
            start_time = time.time()
            columns, rows = self._execute_sql(db_config, sql)
            exec_time = round((time.time() - start_time) * 1000, 2)
        except Exception as e:
            self._cached_result = {
                "error": True,
                "message": f"Query execution failed: {e!s}\n\nGenerated SQL:\n```sql\n{sql}\n```",
                "generated_sql": sql,
            }
            return self._cached_result

        # Step 4: Format results
        self._cached_result = {
            "error": False,
            "generated_sql": sql,
            "columns": columns,
            "rows": [list(r) for r in rows],
            "row_count": len(rows),
            "execution_time_ms": exec_time,
            "user_query": user_query,
        }
        return self._cached_result

    def run_query(self) -> Message:
        """Return formatted markdown result."""
        result = self._run_nl_to_sql()

        if result.get("error"):
            self.status = "Error"
            return Message(text=result["message"])

        # Build response
        parts = []
        parts.append(f"**Query Results** ({result['row_count']} rows, {result['execution_time_ms']}ms)\n")

        if self.include_sql:
            parts.append(f"**Generated SQL:**\n```sql\n{result['generated_sql']}\n```\n")

        # Markdown table
        md_table = _format_results_as_markdown(result["columns"], [tuple(r) for r in result["rows"]])
        parts.append(md_table)

        self.status = f"{result['row_count']} rows returned"
        return Message(text="\n".join(parts))

    def run_query_raw(self) -> Data:
        """Return raw structured data for visualization."""
        result = self._run_nl_to_sql()

        if result.get("error"):
            self.status = "Error"
            return Data(data={"error": True, "message": result["message"]})

        self.status = f"{result['row_count']} rows (raw)"
        return Data(data={
            "columns": result["columns"],
            "rows": result["rows"],
            "row_count": result["row_count"],
            "execution_time_ms": result["execution_time_ms"],
            "generated_sql": result["generated_sql"],
            "user_query": result["user_query"],
        })