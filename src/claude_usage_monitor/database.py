"""
Claude Usage Monitor - Database (SQLite)
"""
import csv
import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path

from .config import DB_PATH, EXPORT_DIR

logger = logging.getLogger("monitor.database")

SCHEMA_VERSION = "2.3"


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
        conn.execute("""
            CREATE TABLE IF NOT EXISTS monthly_summaries (
                month TEXT PRIMARY KEY,
                max_all_models INTEGER,
                avg_all_models REAL,
                max_sonnet INTEGER,
                avg_sonnet REAL,
                rate_limit_days INTEGER,
                total_entries INTEGER,
                active_days INTEGER,
                first_entry TEXT,
                last_entry TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS claude_code_sessions (
                session_id TEXT PRIMARY KEY,
                project_path TEXT,
                start_time TEXT NOT NULL,
                end_time TEXT,
                duration_minutes INTEGER,
                total_input_tokens INTEGER DEFAULT 0,
                total_output_tokens INTEGER DEFAULT 0,
                total_cache_read_tokens INTEGER DEFAULT 0,
                total_cache_creation_tokens INTEGER DEFAULT 0,
                total_tokens INTEGER DEFAULT 0,
                cost_usd REAL DEFAULT 0,
                message_count INTEGER DEFAULT 0,
                tool_call_count INTEGER DEFAULT 0,
                primary_model TEXT,
                source_file TEXT,
                created_at TEXT DEFAULT (datetime('now'))
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_cc_start_time ON claude_code_sessions(start_time)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_cc_project ON claude_code_sessions(project_path)"
        )
        conn.execute("""
            CREATE TABLE IF NOT EXISTS claude_code_daily (
                date TEXT PRIMARY KEY,
                sessions_count INTEGER DEFAULT 0,
                total_tokens INTEGER DEFAULT 0,
                input_tokens INTEGER DEFAULT 0,
                output_tokens INTEGER DEFAULT 0,
                cost_usd REAL DEFAULT 0,
                opus_tokens INTEGER DEFAULT 0,
                sonnet_tokens INTEGER DEFAULT 0,
                haiku_tokens INTEGER DEFAULT 0,
                tool_calls INTEGER DEFAULT 0,
                active_projects INTEGER DEFAULT 0,
                created_at TEXT DEFAULT (datetime('now'))
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS schema_info (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        _run_migrations(conn)


def _get_schema_version(conn) -> str:
    try:
        row = conn.execute(
            "SELECT value FROM schema_info WHERE key = 'version'"
        ).fetchone()
        return row["value"] if row else "2.0"
    except sqlite3.OperationalError:
        return "2.0"


def _set_schema_version(conn, version: str):
    conn.execute(
        "INSERT OR REPLACE INTO schema_info (key, value) VALUES ('version', ?)",
        (version,),
    )


MIGRATIONS = {
    "2.0": ("2.1", "_migrate_2_0_to_2_1"),
    "2.1": ("2.2", "_migrate_2_1_to_2_2"),
    "2.2": ("2.3", "_migrate_2_2_to_2_3"),
}


def _run_migrations(conn):
    current = _get_schema_version(conn)
    while current != SCHEMA_VERSION:
        if current not in MIGRATIONS:
            logger.warning(f"No migration path from {current} to {SCHEMA_VERSION}")
            break
        target, func_name = MIGRATIONS[current]
        logger.info(f"Running migration {current} → {target}...")
        globals()[func_name](conn)
        _set_schema_version(conn, target)
        logger.info(f"Migration {current} → {target} complete")
        current = target


def _migrate_2_0_to_2_1(conn):
    """Populate monthly_summaries from existing usage_entries."""
    rows = conn.execute("""
        SELECT DISTINCT strftime('%Y-%m', timestamp) as month
        FROM usage_entries
    """).fetchall()
    for row in rows:
        month = row["month"]
        stats = conn.execute("""
            SELECT
                MAX(all_models_pct) as max_all_models,
                AVG(all_models_pct) as avg_all_models,
                MAX(sonnet_pct) as max_sonnet,
                AVG(sonnet_pct) as avg_sonnet,
                COUNT(*) as total_entries,
                COUNT(DISTINCT date(timestamp)) as active_days,
                MIN(timestamp) as first_entry,
                MAX(timestamp) as last_entry
            FROM usage_entries
            WHERE strftime('%Y-%m', timestamp) = ?
        """, (month,)).fetchone()

        rate_limit_days = conn.execute("""
            SELECT COUNT(DISTINCT date(timestamp))
            FROM usage_entries
            WHERE strftime('%Y-%m', timestamp) = ? AND all_models_pct > 80
        """, (month,)).fetchone()[0]

        conn.execute("""
            INSERT OR REPLACE INTO monthly_summaries
            (month, max_all_models, avg_all_models, max_sonnet, avg_sonnet,
             rate_limit_days, total_entries, active_days, first_entry, last_entry)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            month,
            stats["max_all_models"],
            round(stats["avg_all_models"], 1) if stats["avg_all_models"] else 0,
            stats["max_sonnet"],
            round(stats["avg_sonnet"], 1) if stats["avg_sonnet"] else 0,
            rate_limit_days,
            stats["total_entries"],
            stats["active_days"],
            stats["first_entry"],
            stats["last_entry"],
        ))
    logger.info(f"Populated monthly_summaries for {len(rows)} months")


def _migrate_2_1_to_2_2(conn):
    """Create tables for Claude Code integration."""
    logger.info("Creating Claude Code tables...")
    # Tables already created in init_db(), so this is a no-op
    # Just ensure they exist
    conn.execute("""
        CREATE TABLE IF NOT EXISTS claude_code_sessions (
            session_id TEXT PRIMARY KEY,
            project_path TEXT,
            start_time TEXT NOT NULL,
            end_time TEXT,
            duration_minutes INTEGER,
            total_input_tokens INTEGER DEFAULT 0,
            total_output_tokens INTEGER DEFAULT 0,
            total_cache_read_tokens INTEGER DEFAULT 0,
            total_cache_creation_tokens INTEGER DEFAULT 0,
            total_tokens INTEGER DEFAULT 0,
            cost_usd REAL DEFAULT 0,
            message_count INTEGER DEFAULT 0,
            tool_call_count INTEGER DEFAULT 0,
            primary_model TEXT,
            source_file TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS claude_code_daily (
            date TEXT PRIMARY KEY,
            sessions_count INTEGER DEFAULT 0,
            total_tokens INTEGER DEFAULT 0,
            input_tokens INTEGER DEFAULT 0,
            output_tokens INTEGER DEFAULT 0,
            cost_usd REAL DEFAULT 0,
            opus_tokens INTEGER DEFAULT 0,
            sonnet_tokens INTEGER DEFAULT 0,
            haiku_tokens INTEGER DEFAULT 0,
            tool_calls INTEGER DEFAULT 0,
            active_projects INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)
    logger.info("Claude Code tables created/verified")


def _migrate_2_2_to_2_3(conn):
    """Phase 5.4: Add scan index table for optimization."""
    logger.info("Creating Claude Code scan index table...")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS claude_code_scan_index (
            session_file_path TEXT PRIMARY KEY,
            last_modified INTEGER,
            last_byte_offset INTEGER DEFAULT 0,
            last_scanned_at TEXT DEFAULT (datetime('now'))
        )
    """)
    logger.info("Scan index table created")


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
        _update_monthly_summary(conn, timestamp)
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


def _update_monthly_summary(conn, timestamp: str):
    """Recompute monthly summary for the month of the given timestamp."""
    month_str = timestamp[:7]  # YYYY-MM
    row = conn.execute(
        """SELECT
            MAX(all_models_pct) as max_all_models,
            AVG(all_models_pct) as avg_all_models,
            MAX(sonnet_pct) as max_sonnet,
            AVG(sonnet_pct) as avg_sonnet,
            COUNT(*) as total_entries,
            COUNT(DISTINCT date(timestamp)) as active_days,
            MIN(timestamp) as first_entry,
            MAX(timestamp) as last_entry
        FROM usage_entries
        WHERE strftime('%Y-%m', timestamp) = ?""",
        (month_str,),
    ).fetchone()

    if not row or row["total_entries"] == 0:
        return

    # Count rate-limit days (days where any measurement > 80%)
    rate_limit_days = conn.execute(
        """SELECT COUNT(DISTINCT date(timestamp))
        FROM usage_entries
        WHERE strftime('%Y-%m', timestamp) = ? AND all_models_pct > 80""",
        (month_str,),
    ).fetchone()[0]

    conn.execute(
        """INSERT OR REPLACE INTO monthly_summaries
           (month, max_all_models, avg_all_models, max_sonnet, avg_sonnet,
            rate_limit_days, total_entries, active_days, first_entry, last_entry)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            month_str,
            row["max_all_models"],
            round(row["avg_all_models"], 1) if row["avg_all_models"] else 0,
            row["max_sonnet"],
            round(row["avg_sonnet"], 1) if row["avg_sonnet"] else 0,
            rate_limit_days,
            row["total_entries"],
            row["active_days"],
            row["first_entry"],
            row["last_entry"],
        ),
    )


def get_monthly_summaries(months: int = 6) -> list[dict]:
    with get_db() as conn:
        since = (datetime.now() - timedelta(days=months * 31)).strftime("%Y-%m")
        rows = conn.execute(
            "SELECT * FROM monthly_summaries WHERE month >= ? ORDER BY month ASC",
            (since,),
        ).fetchall()
        return [dict(r) for r in rows]


def get_monthly_peaks(months: int = 6) -> list[dict]:
    with get_db() as conn:
        since = (datetime.now() - timedelta(days=months * 31)).isoformat()
        rows = conn.execute(
            """SELECT
                strftime('%Y-%m', timestamp) as month,
                MAX(all_models_pct) as max_all_models,
                ROUND(AVG(all_models_pct), 1) as avg_all_models,
                MAX(sonnet_pct) as max_sonnet,
                ROUND(AVG(sonnet_pct), 1) as avg_sonnet,
                COUNT(DISTINCT date(timestamp)) as active_days,
                COUNT(*) as entries_count
            FROM usage_entries
            WHERE timestamp >= ?
            GROUP BY month
            ORDER BY month ASC""",
            (since,),
        ).fetchall()
        return [dict(r) for r in rows]


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
        conn.execute("DELETE FROM monthly_summaries")


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


# Claude Code session functions
def upsert_claude_code_session(session: dict) -> None:
    """Insert or update a Claude Code session."""
    with get_db() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO claude_code_sessions
               (session_id, project_path, start_time, end_time, duration_minutes,
                total_input_tokens, total_output_tokens, total_cache_read_tokens,
                total_cache_creation_tokens, total_tokens, cost_usd, message_count,
                tool_call_count, primary_model, source_file)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                session.get("session_id"),
                session.get("project_path"),
                session.get("start_time"),
                session.get("end_time"),
                session.get("duration_minutes"),
                session.get("total_input_tokens", 0),
                session.get("total_output_tokens", 0),
                session.get("total_cache_read_tokens", 0),
                session.get("total_cache_creation_tokens", 0),
                session.get("total_tokens", 0),
                session.get("cost_usd", 0),
                session.get("message_count", 0),
                session.get("tool_call_count", 0),
                session.get("primary_model"),
                session.get("source_file"),
            ),
        )


def get_claude_code_sessions(days: int = 90, project: str | None = None) -> list[dict]:
    """Get Claude Code sessions, optionally filtered by project."""
    with get_db() as conn:
        since = (datetime.now() - timedelta(days=days)).isoformat()
        query = "SELECT * FROM claude_code_sessions WHERE start_time >= ?"
        params = [since]

        if project:
            query += " AND project_path = ?"
            params.append(project)

        query += " ORDER BY start_time DESC"
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]


def get_claude_code_daily(days: int = 90) -> list[dict]:
    """Get daily Claude Code aggregates."""
    with get_db() as conn:
        since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        rows = conn.execute(
            "SELECT * FROM claude_code_daily WHERE date >= ? ORDER BY date ASC",
            (since,),
        ).fetchall()
        return [dict(r) for r in rows]


def get_claude_code_monthly(months: int = 6) -> list[dict]:
    """Get monthly Claude Code aggregates."""
    with get_db() as conn:
        since = (datetime.now() - timedelta(days=months * 31)).strftime("%Y-%m")
        rows = conn.execute(
            """SELECT
                strftime('%Y-%m', date) as month,
                SUM(sessions_count) as sessions,
                SUM(total_tokens) as total_tokens,
                SUM(cost_usd) as cost_usd,
                SUM(opus_tokens) as opus_tokens,
                SUM(sonnet_tokens) as sonnet_tokens,
                SUM(haiku_tokens) as haiku_tokens,
                COUNT(DISTINCT date) as active_days
            FROM claude_code_daily
            WHERE date >= ?
            GROUP BY strftime('%Y-%m', date)
            ORDER BY month ASC""",
            (since,),
        ).fetchall()
        return [dict(r) for r in rows]


# ============================================================
# Phase 5.2: Scan Index Management (Incremental Parsing)
# ============================================================
def get_scan_index(session_file_path: str) -> dict | None:
    """Get scan index entry for a session file."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT session_file_path, last_modified, last_byte_offset, last_scanned_at FROM claude_code_scan_index WHERE session_file_path = ?",
            (session_file_path,),
        ).fetchone()
        return dict(row) if row else None


def update_scan_index(session_file_path: str, last_modified: int, last_byte_offset: int) -> None:
    """Update scan index after processing a session file."""
    with get_db() as conn:
        conn.execute(
            """INSERT INTO claude_code_scan_index (session_file_path, last_modified, last_byte_offset, last_scanned_at)
               VALUES (?, ?, ?, datetime('now'))
               ON CONFLICT(session_file_path) DO UPDATE SET
                 last_modified = excluded.last_modified,
                 last_byte_offset = excluded.last_byte_offset,
                 last_scanned_at = datetime('now')
            """,
            (session_file_path, last_modified, last_byte_offset),
        )
        conn.commit()


def clear_scan_index() -> None:
    """Clear all scan index entries (forces full re-scan on next run)."""
    with get_db() as conn:
        conn.execute("DELETE FROM claude_code_scan_index")
        conn.commit()
