"""Lưu trữ SQLite: runs / events / rounds."""
import sqlite3
from pathlib import Path

from core.time_utils import utcnow_iso

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
  run_id TEXT PRIMARY KEY,
  group_name TEXT,
  scenario TEXT,
  status TEXT,
  started_at TEXT,
  finished_at TEXT,
  total_rounds INT DEFAULT 0,
  main_first INT DEFAULT 0,
  main_not_first INT DEFAULT 0,
  first_move_accuracy REAL DEFAULT 0,
  join_ok INT DEFAULT 0,
  join_fail INT DEFAULT 0,
  timeouts INT DEFAULT 0,
  reconnects INT DEFAULT 0,
  pass INT DEFAULT 0,
  fail INT DEFAULT 0
);
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id TEXT,
  group_name TEXT,
  session_id TEXT,
  event_id TEXT,
  state_from TEXT,
  state_to TEXT,
  message TEXT,
  ts TEXT
);
CREATE TABLE IF NOT EXISTS rounds (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id TEXT,
  group_name TEXT,
  round_no INT,
  first_player TEXT,
  winner TEXT,
  expected_first TEXT,
  pass INT,
  ts TEXT
);
"""


class Storage:
    def __init__(self, db_path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as conn:
            conn.executescript(_SCHEMA)

    def _conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def create_run(self, run_id, group_name, scenario):
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO runs (run_id, group_name, scenario, status, started_at) VALUES (?,?,?,?,?)",
                (run_id, group_name, scenario, "running", utcnow_iso()),
            )

    def finish_run(self, run_id, metrics: dict, status="finished"):
        with self._conn() as conn:
            conn.execute(
                """UPDATE runs SET status=?, finished_at=?, total_rounds=?, main_first=?,
                   main_not_first=?, first_move_accuracy=?, join_ok=?, join_fail=?,
                   timeouts=?, reconnects=?, pass=?, fail=? WHERE run_id=?""",
                (
                    status,
                    utcnow_iso(),
                    metrics.get("total_rounds", 0),
                    metrics.get("main_first", 0),
                    metrics.get("main_not_first", 0),
                    metrics.get("first_move_accuracy", 0),
                    metrics.get("join_ok", 0),
                    metrics.get("join_fail", 0),
                    metrics.get("timeouts", 0),
                    metrics.get("reconnects", 0),
                    metrics.get("pass_count", 0),
                    metrics.get("fail_count", 0),
                    run_id,
                ),
            )

    def add_event(self, run_id, group_name, session_id, event_id, state_from, state_to, message):
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO events (run_id, group_name, session_id, event_id, state_from, state_to, message, ts) VALUES (?,?,?,?,?,?,?,?)",
                (run_id, group_name, session_id, event_id, state_from, state_to, message, utcnow_iso()),
            )

    def add_round(self, run_id, group_name, round_no, first_player, winner, expected_first, pass_ok):
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO rounds (run_id, group_name, round_no, first_player, winner, expected_first, pass, ts) VALUES (?,?,?,?,?,?,?,?)",
                (run_id, group_name, round_no, first_player, winner, expected_first, 1 if pass_ok else 0, utcnow_iso()),
            )

    def recent_events(self, limit=50):
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
            return [dict(r) for r in rows]
