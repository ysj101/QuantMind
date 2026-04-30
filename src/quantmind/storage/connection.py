"""DuckDB 接続管理とスキーマ初期化."""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import duckdb

DEFAULT_DATA_DIR = Path.home() / ".quantmind"
DB_FILENAME = "quantmind.duckdb"
MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def data_dir() -> Path:
    """データ保存ディレクトリを返す（環境変数 QUANTMIND_DATA_DIR 優先）."""
    raw = os.environ.get("QUANTMIND_DATA_DIR")
    base = Path(raw).expanduser() if raw else DEFAULT_DATA_DIR
    base.mkdir(parents=True, exist_ok=True)
    return base


def db_path() -> Path:
    return data_dir() / DB_FILENAME


def connect(read_only: bool = False) -> duckdb.DuckDBPyConnection:
    """DuckDB に接続する（呼び出し側で close 責任）."""
    path = db_path()
    return duckdb.connect(str(path), read_only=read_only)


@contextmanager
def get_conn(read_only: bool = False) -> Iterator[duckdb.DuckDBPyConnection]:
    """コンテキストマネージャ版接続."""
    conn = connect(read_only=read_only)
    try:
        yield conn
    finally:
        conn.close()


def _migration_files() -> list[Path]:
    if not MIGRATIONS_DIR.exists():
        return []
    return sorted(MIGRATIONS_DIR.glob("*.sql"))


def init_db(verbose: bool = False) -> Path:
    """全マイグレーションを順次適用して DB/スキーマを初期化する."""
    path = db_path()
    with get_conn() as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            "  version VARCHAR PRIMARY KEY,"
            "  applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP"
            ")"
        )
        applied = {row[0] for row in conn.execute("SELECT version FROM schema_migrations").fetchall()}
        for migration in _migration_files():
            version = migration.stem
            if version in applied:
                continue
            sql = migration.read_text(encoding="utf-8")
            if verbose:
                print(f"[migrate] applying {version}")
            conn.execute(sql)
            conn.execute("INSERT INTO schema_migrations(version) VALUES (?)", [version])
    return path
