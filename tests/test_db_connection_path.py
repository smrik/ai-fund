"""Regression tests for dynamic DB path resolution in db.schema.get_connection.

Guards the --isolated-db safety rail: ALPHA_POD_DB_PATH must be honored at
call time even when it is set after config/db.schema were imported (the
guided-workup import order that leaked rehearsal writes into the live DB on
2026-07-03).
"""
import sqlite3
from pathlib import Path

from db.schema import get_connection


def _connected_file(conn: sqlite3.Connection) -> str:
    rows = conn.execute("PRAGMA database_list").fetchall()
    return rows[0][2]


def test_env_override_set_after_import_wins(tmp_path, monkeypatch):
    target = tmp_path / "isolated.db"
    monkeypatch.setenv("ALPHA_POD_DB_PATH", str(target))
    conn = get_connection()
    try:
        assert Path(_connected_file(conn)).resolve() == target.resolve()
    finally:
        conn.close()


def test_explicit_arg_beats_env_override(tmp_path, monkeypatch):
    env_target = tmp_path / "from-env.db"
    arg_target = tmp_path / "from-arg.db"
    monkeypatch.setenv("ALPHA_POD_DB_PATH", str(env_target))
    conn = get_connection(arg_target)
    try:
        assert Path(_connected_file(conn)).resolve() == arg_target.resolve()
    finally:
        conn.close()


def test_falls_back_to_config_path_without_override(tmp_path, monkeypatch):
    monkeypatch.delenv("ALPHA_POD_DB_PATH", raising=False)
    fallback = tmp_path / "fallback.db"
    monkeypatch.setattr("db.schema.DB_PATH", fallback)
    conn = get_connection()
    try:
        assert Path(_connected_file(conn)).resolve() == fallback.resolve()
    finally:
        conn.close()
