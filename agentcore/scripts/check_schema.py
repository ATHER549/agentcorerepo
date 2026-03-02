import psycopg
from psycopg.rows import dict_row

url = "postgresql://postgres:postgres@localhost:5432/agentcore"

with psycopg.connect(url, row_factory=dict_row) as conn:
    cur = conn.cursor()
    def exists(table: str) -> bool:
        cur.execute("SELECT to_regclass(%s) IS NOT NULL AS exists", (f"public.{table}",))
        return cur.fetchone()["exists"]

    def find_in_all_schemas(table: str) -> list[str]:
        cur.execute(
            "SELECT table_schema FROM information_schema.tables WHERE table_name = %s ORDER BY table_schema",
            (table,),
        )
        return [r["table_schema"] for r in cur.fetchall()]

    def find_in_pg_catalog(table: str) -> list[str]:
        cur.execute(
            """
            SELECT n.nspname
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE c.relname = %s
            ORDER BY n.nspname
            """,
            (table,),
        )
        return [r["nspname"] for r in cur.fetchall()]

    print("agent_edit_lock exists:", exists("agent_edit_lock"))
    print("agent_edit_lock schemas:", find_in_all_schemas("agent_edit_lock"))
    print("agent_edit_lock pg_catalog:", find_in_pg_catalog("agent_edit_lock"))
    print("teams_app exists:", exists("teams_app"))
    print("teams_app schemas:", find_in_all_schemas("teams_app"))
    print("teams_app pg_catalog:", find_in_pg_catalog("teams_app"))
    print("evaluator exists:", exists("evaluator"))
    print("evaluator schemas:", find_in_all_schemas("evaluator"))
    print("evaluator pg_catalog:", find_in_pg_catalog("evaluator"))
    print("vertex_build exists:", exists("vertex_build"))
    print("vertex_build schemas:", find_in_all_schemas("vertex_build"))
    print("vertex_build pg_catalog:", find_in_pg_catalog("vertex_build"))

    cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name='agent' ORDER BY column_name")
    cols = [r["column_name"] for r in cur.fetchall()]
    print("agent has action_name:", "action_name" in cols)
    print("agent has action_description:", "action_description" in cols)
    print("agent has mcp_enabled:", "mcp_enabled" in cols)

    cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name='guardrail_catalogue' ORDER BY column_name")
    gcols = [r["column_name"] for r in cur.fetchall()]
    print("guardrail_catalogue has model_registry_id:", "model_registry_id" in gcols)

    cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name='knowledge_base' ORDER BY column_name")
    kcols = [r["column_name"] for r in cur.fetchall()]
    print("knowledge_base has visibility:", "visibility" in kcols)
