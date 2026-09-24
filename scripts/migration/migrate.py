"""Versioned database migration runner for spatial schema setups."""
import os
import glob
from typing import Any
from sqlalchemy import text, Engine
from sqlalchemy.exc import SQLAlchemyError


def _is_idempotent_error(message: str) -> bool:
    """Return True when a DDL failure means the object already exists."""
    lowered = message.lower()
    return "already exists" in lowered or "duplicate column" in lowered


def run_migrations(engine: Engine) -> list[str]:
    """Execute all pending versioned SQL migration scripts in order."""
    migrations_dir = os.path.dirname(__file__)
    sql_files = sorted(glob.glob(os.path.join(migrations_dir, "V*.sql")))

    executed_versions: list[str] = []

    with engine.connect() as conn:
        # 1. Create schema_migrations tracking table if not exists
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version VARCHAR(64) PRIMARY KEY,
                    executed_at DATETIME DEFAULT CURRENT_TIMESTAMP
                );
                """
            )
        )
        conn.commit()

        # 2. Get already applied versions
        result = conn.execute(text("SELECT version FROM schema_migrations;"))
        applied_versions = {row[0] for row in result.fetchall()}

        # 3. Apply pending migrations
        for file_path in sql_files:
            version_name = os.path.basename(file_path).split("__")[0]
            if version_name not in applied_versions:
                with open(file_path, "r", encoding="utf-8") as file:
                    sql_content = file.read()

                # Execute statements separated by semicolons. Each statement runs
                # in its own savepoint so an already-present object/column (for
                # example when migrating a schema that the ORM already created)
                # is skipped rather than aborting the whole migration.
                statements = [
                    stmt.strip() for stmt in sql_content.split(";") if stmt.strip()
                ]
                for stmt in statements:
                    try:
                        with conn.begin_nested():
                            conn.execute(text(stmt))
                    except SQLAlchemyError as exc:
                        if not _is_idempotent_error(str(exc)):
                            raise

                conn.execute(
                    text("INSERT INTO schema_migrations (version) VALUES (:v)"),
                    {"v": version_name},
                )
                conn.commit()
                executed_versions.append(version_name)

    return executed_versions
