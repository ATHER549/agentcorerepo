# noqa: INP001
import asyncio
import os
from logging.config import fileConfig
from dotenv import load_dotenv, find_dotenv
load_dotenv(find_dotenv())
from alembic import context
from sqlalchemy import pool, text
from sqlalchemy.ext.asyncio import create_async_engine
 
# Lazy import to avoid Python 3.9 compatibility issues with TypeVar syntax
def get_target_metadata():
    """Lazy load target metadata to avoid import errors on Python 3.9."""
    try:
        from agentcore.services.database.service import SQLModel
        NAMING_CONVENTION = {
            "ix": "ix_%(column_0_label)s",
            "uq": "uq_%(table_name)s_%(column_0_name)s",
            "ck": "ck_%(table_name)s_%(constraint_name)s",
            "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
            "pk": "pk_%(table_name)s",
        }
        SQLModel.metadata.naming_convention = NAMING_CONVENTION
        return SQLModel.metadata
    except Exception as e:
        print(f"Warning: Could not import SQLModel metadata: {e}")
        print("Creating empty MetaData object instead")
        from sqlalchemy import MetaData
        return MetaData()
 
# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config
 
# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)
 
target_metadata = None  # Will be loaded lazily in run_migrations_online
# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.
 
 
def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.
 
    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.
 
    Calls to context.execute() here emit the given string to the
    script output.
 
    """
    url = config.get_main_option("sqlalchemy.url")
    target_metadata = get_target_metadata()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
        prepare_threshold=None,
    )
 
    with context.begin_transaction():
        context.run_migrations()
 
 
def _do_run_migrations(connection):
    target_metadata = get_target_metadata()
    context.configure(
        connection=connection, target_metadata=target_metadata, render_as_batch=True, prepare_threshold=None
    )
    with context.begin_transaction():
        if connection.dialect.name == "postgresql":
            connection.execute(text("SET LOCAL lock_timeout = '60s';"))
            connection.execute(text("SELECT pg_advisory_xact_lock(112233);"))
        context.run_migrations()
 
 
async def _run_async_migrations() -> None:
    # Use get_main_option FIRST to respect programmatic overrides from service.py
    # (which sanitizes the URL for async compatibility)
    # Only fallback to environment variables if config option is not set
    url = config.get_main_option("sqlalchemy.url") or os.getenv("DATABASE_URL") or os.getenv("AGENTCORE_DATABASE_URL")
    # Validate that we have a real URL
    if not url or url.startswith("driver://"):
        url = os.getenv("DATABASE_URL")
   
    connectable = create_async_engine(url, poolclass=pool.NullPool)
 
    async with connectable.connect() as connection:
        await connection.run_sync(_do_run_migrations)
 
    await connectable.dispose()
 
 
def run_migrations_online() -> None:
    """Run migrations in 'online' mode.
 
    In this scenario we need to create an Engine
    and associate a connection with the context.
 
    """
    asyncio.run(_run_async_migrations())
 
 
if context.is_offline_mode():
    run_migrations_offline()
else: 
    run_migrations_online()