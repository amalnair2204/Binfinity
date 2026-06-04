"""Idempotent migration runner. Applies all SQL files in infra/migrations/ in order."""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import asyncpg

_DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:binfinity@localhost:5432/binfinity",
)

_MIGRATIONS_DIR = Path(__file__).parent / "migrations"

_CREATE_LOG = """
CREATE TABLE IF NOT EXISTS migrations_log (
    id          SERIAL PRIMARY KEY,
    filename    TEXT NOT NULL UNIQUE,
    applied_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""


async def run_migrations() -> None:
    conn = await asyncpg.connect(_DATABASE_URL)
    try:
        await conn.execute(_CREATE_LOG)

        applied: set[str] = {
            row["filename"]
            for row in await conn.fetch("SELECT filename FROM migrations_log ORDER BY id")
        }

        migration_files = sorted(_MIGRATIONS_DIR.glob("*.sql"))
        if not migration_files:
            print("No migration files found in", _MIGRATIONS_DIR)
            return

        for path in migration_files:
            name = path.name
            if name in applied:
                print(f"  skip  {name}")
                continue

            sql = path.read_text(encoding="utf-8")
            try:
                await conn.execute(sql)
                await conn.execute(
                    "INSERT INTO migrations_log (filename) VALUES ($1)", name
                )
                print(f"  apply {name}")
            except Exception as exc:
                print(f"  ERROR {name}: {exc}", file=sys.stderr)
                raise

        print("Migrations complete.")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(run_migrations())
