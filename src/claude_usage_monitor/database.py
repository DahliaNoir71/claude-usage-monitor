"""
Claude Usage Monitor - Database (SQLite)
"""
import csv
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path

from .config import DB_PATH, EXPORT_DIR


@contextmanager
def get_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS usage_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                all_models_pct INTEGER,
                sonnet_pct INTEGER,
                reset_all_models TEXT,
                reset_sonnet TEXT,
                source TEXT DEFAULT 'scraper',
                created_at TEXT DEFAULT (datetime('now'))
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_timestamp ON usage_entries(timestamp)"
        )
        conn.execute("""
            CREATE TABLE IF NOT EXISTS daily_summaries (
                date TEXT PRIMARY KEY,
                max_all_models INTEGER,
                max_sonnet INTEGER,
                min_all_models INTEGER,
                delta_all_models INTEGER,
                entries_count INTEGER,
                first_entry_time TEXT,
                last_entry_time TEXT
            )
        """)


def add_entry(
    all_models_pct: int,
    sonnet_pct: int = 0,
    reset_all_models: str | None = None,
    reset_sonnet: str | None = None,
    source: str = "scraper",
    timestamp: str | None = None,
) -> int:
    if timestamp is None:
        timestamp = datetime.now().isoformat()
    with get_db() as conn:
        cursor = conn.execute(
            """INSERT INTO usage_entries
               (timestamp, all_models_pct, sonnet_pct, reset_all_models, reset_sonnet, source)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (timestamp, all_models_pct, sonnet_pct, reset_all_models, reset_sonnet, source),
        )
        _update_daily_summary(conn, timestamp, all_models_pct, sonnet_pct)
        return cursor.lastrowid


def _update_daily_summary(conn, timestamp: str, all_models: int, sonnet: int):
    date_str = timestamp[:10]
    existing = conn.execute(
        "SELECT * FROM daily_summaries WHERE date = ?", (date_str,)
    ).fetchone()

    if existing:
        conn.execute(
            """UPDATE daily_summaries SET
                max_all_models = MAX(max_all_models, ?),
                max_sonnet = MAX(max_sonnet, ?),
                min_all_models = MIN(min_all_models, ?),
                delta_all_models = MAX(max_all_models, ?) - MIN(min_all_models, ?),
                entries_count = entries_count + 1,
                last_entry_time = ?
            WHERE date = ?""",
            (all_models, sonnet, all_models, all_models, all_models, timestamp, date_str),
        )
    else:
        conn.execute(
            """INSERT INTO daily_summaries
               (date, max_all_models, max_sonnet, min_all_models, delta_all_models,
                entries_count, first_entry_time, last_entry_time)
               VALUES (?, ?, ?, ?, 0, 1, ?, ?)""",
            (date_str, all_models, sonnet, all_models, timestamp, timestamp),
        )


def get_entries(days: int | None = None, limit: int | None = None) -> list[dict]:
    with get_db() as conn:
        query = "SELECT * FROM usage_entries"
        params: list = []
        if days:
            since = (datetime.now() - timedelta(days=days)).isoformat()
            query += " WHERE timestamp >= ?"
            params.append(since)
        query += " ORDER BY timestamp ASC"
        if limit:
            query += " LIMIT ?"
            params.append(limit)
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]


def get_latest_entry() -> dict | None:
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM usage_entries ORDER BY timestamp DESC LIMIT 1"
        ).fetchone()
        return dict(row) if row else None


def get_daily_summaries(days: int = 90) -> list[dict]:
    with get_db() as conn:
        since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        rows = conn.execute(
            "SELECT * FROM daily_summaries WHERE date >= ? ORDER BY date ASC",
            (since,),
        ).fetchall()
        return [dict(r) for r in rows]


def get_weekly_peaks(weeks: int = 12) -> list[dict]:
    with get_db() as conn:
        since = (datetime.now() - timedelta(weeks=weeks)).isoformat()
        rows = conn.execute(
            """SELECT
                strftime('%Y-W%W', timestamp) as week,
                MAX(all_models_pct) as max_all_models,
                MAX(sonnet_pct) as max_sonnet,
                COUNT(*) as entries_count,
                MIN(timestamp) as week_start,
                MAX(timestamp) as week_end
            FROM usage_entries
            WHERE timestamp >= ?
            GROUP BY week
            ORDER BY week ASC""",
            (since,),
        ).fetchall()
        return [dict(r) for r in rows]


def detect_resets() -> list[dict]:
    entries = get_entries()
    resets = []
    for i in range(1, len(entries)):
        prev = entries[i - 1]["all_models_pct"]
        curr = entries[i]["all_models_pct"]
        if prev is not None and curr is not None and curr < prev - 2:
            resets.append(
                {
                    "timestamp": entries[i]["timestamp"],
                    "from_pct": prev,
                    "to_pct": curr,
                    "drop": prev - curr,
                }
            )
    return resets


def get_sonnet_cycles() -> list[dict]:
    entries = get_entries()
    cycles = []
    peak = 0
    cycle_start = entries[0]["timestamp"] if entries else None

    for i in range(1, len(entries)):
        prev_s = entries[i - 1].get("sonnet_pct") or 0
        curr_s = entries[i].get("sonnet_pct") or 0
        peak = max(peak, prev_s)

        if curr_s < prev_s - 5:
            cycles.append({"start": cycle_start, "end": entries[i - 1]["timestamp"], "peak": peak})
            peak = curr_s
            cycle_start = entries[i]["timestamp"]

    if entries:
        last_s = entries[-1].get("sonnet_pct") or 0
        cycles.append(
            {"start": cycle_start, "end": entries[-1]["timestamp"], "peak": max(peak, last_s)}
        )

    return [c for c in cycles if c["peak"] > 0]


def delete_entry(entry_id: int):
    with get_db() as conn:
        conn.execute("DELETE FROM usage_entries WHERE id = ?", (entry_id,))


def clear_all():
    with get_db() as conn:
        conn.execute("DELETE FROM usage_entries")
        conn.execute("DELETE FROM daily_summaries")


def entry_count() -> int:
    with get_db() as conn:
        return conn.execute("SELECT COUNT(*) FROM usage_entries").fetchone()[0]


def export_csv(filepath: str | None = None) -> str | None:
    if filepath is None:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        filepath = str(EXPORT_DIR / f"claude_usage_{ts}.csv")

    entries = get_entries()
    if not entries:
        return None

    fieldnames = [
        "timestamp",
        "all_models_pct",
        "sonnet_pct",
        "reset_all_models",
        "reset_sonnet",
        "source",
    ]
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for e in entries:
            writer.writerow({k: e.get(k) for k in fieldnames})

    return filepath


def import_csv(filepath: str, date_format: str = "%d/%m/%Y") -> int:
    """Import from the user's manual CSV format."""
    count = 0
    with open(filepath, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                date_str = row.get("Date", "")
                time_str = row.get("Heure", "")
                dt = datetime.strptime(f"{date_str} {time_str}", f"{date_format} %H:%M:%S")
                timestamp = dt.isoformat()

                add_entry(
                    all_models_pct=int(row.get("All Models %", 0)),
                    sonnet_pct=int(row.get("Sonnet %", 0)),
                    reset_all_models=row.get("Reset All Models") or None,
                    reset_sonnet=row.get("Reset Sonnet") or None,
                    source="csv_import",
                    timestamp=timestamp,
                )
                count += 1
            except (ValueError, KeyError) as e:
                print(f"Skipping row: {e}")
                continue
    return count
