"""
Claude Usage Monitor - Claude Code Reader

Parser for Claude Code JSONL session files stored in ~/.claude/
Extracts tokens, models, costs, and projects without loading files into memory.
"""

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Generator

logger = logging.getLogger("monitor.claude_code_reader")

# Constants
JSONL_PATTERN = "*.jsonl"

# Model pricing (USD per 1M tokens)
# Updated 2026-03-20 - verify against https://www.anthropic.com/pricing
MODEL_PRICING = {
    "claude-opus-4": {
        "input": 5.0,
        "output": 25.0,
        "cache_read": 0.50,
        "cache_creation": 6.25,
    },
    "claude-sonnet-4": {
        "input": 3.0,
        "output": 15.0,
        "cache_read": 0.30,
        "cache_creation": 3.75,
    },
    "claude-haiku-4.5": {
        "input": 0.80,
        "output": 4.0,
        "cache_read": 0.08,
        "cache_creation": 1.0,
    },
}


def find_claude_code_dir() -> Path | None:
    """
    Locate the ~/.claude/ directory.

    Returns:
        Path to ~/.claude/ if it exists, None otherwise.
    """
    claude_dir = Path.home() / ".claude"
    if claude_dir.exists() and claude_dir.is_dir():
        return claude_dir
    logger.warning(f"Claude Code directory not found at {claude_dir}")
    return None


def _decode_project_path(encoded: str) -> str:
    """
    Decode a Claude Code project path from its encoded directory name.

    Example: "-Users-spfeiffer-VS_Code_Projects-my-app" -> "C:\\Users\\spfeiffer\\VS Code Projects\\my-app"
    """
    # Claude Code encodes paths as: /Volumes/path/to/project -> -Volumes-path-to-project
    # Replace leading dash with the first path component, replace remaining dashes with slashes/backslashes
    parts = encoded.split("-")
    if not parts:
        return encoded

    # First component often represents drive/volume; reconstruct intelligently
    # For now, return a readable version by replacing dashes with forward slashes
    decoded = "/".join(parts)
    return decoded


def list_projects(claude_dir: Path) -> list[dict]:
    """
    List projects in ~/.claude/projects/ with their metadata.

    Returns:
        List of dicts: {"encoded_name": str, "decoded_path": str, "session_count": int}
    """
    projects_dir = claude_dir / "projects"
    if not projects_dir.exists():
        logger.warning(f"Projects directory not found at {projects_dir}")
        return []

    projects = []
    for project_dir in projects_dir.iterdir():
        if not project_dir.is_dir():
            continue

        sessions_dir = project_dir / "sessions"
        session_count = 0
        if sessions_dir.exists():
            # Count .jsonl files (exclude sessions-index.json)
            session_count = len(list(sessions_dir.glob(JSONL_PATTERN)))

        projects.append(
            {
                "encoded_name": project_dir.name,
                "decoded_path": _decode_project_path(project_dir.name),
                "session_count": session_count,
            }
        )

    return sorted(projects, key=lambda p: p["session_count"], reverse=True)


def _get_model_pricing(model_id: str) -> dict:
    """
    Get pricing for a model ID by prefix matching.

    Example: "claude-sonnet-4-20250514" matches "claude-sonnet-4"
    """
    for model_key, pricing in MODEL_PRICING.items():
        if model_id.startswith(model_key):
            return pricing
    logger.warning(f"Unknown model: {model_id}, using Haiku pricing")
    return MODEL_PRICING["claude-haiku-4.5"]


def _calculate_cost(usage: dict, model_id: str) -> float:
    """
    Calculate cost in USD for a single message's token usage.

    Args:
        usage: {"input_tokens": N, "output_tokens": N, "cache_creation_input_tokens": N, "cache_read_input_tokens": N}
        model_id: e.g., "claude-sonnet-4-20250514"

    Returns:
        Cost in USD
    """
    pricing = _get_model_pricing(model_id)

    input_tokens = usage.get("input_tokens", 0)
    output_tokens = usage.get("output_tokens", 0)
    cache_creation = usage.get("cache_creation_input_tokens", 0)
    cache_read = usage.get("cache_read_input_tokens", 0)

    cost = (
        input_tokens * pricing["input"]
        + output_tokens * pricing["output"]
        + cache_creation * pricing["cache_creation"]
        + cache_read * pricing["cache_read"]
    ) / 1_000_000

    return round(cost, 4)


def _parse_session_jsonl(session_path: Path) -> dict | None:
    """
    Parse a session JSONL file and aggregate metrics.

    Returns:
        Dict with aggregated metrics, or None if parsing fails.
    """
    messages = []
    tool_calls_by_type = {}
    model_usage = {}
    start_time = None
    end_time = None

    try:
        with open(session_path, "r", encoding="utf-8") as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue

                try:
                    msg = json.loads(line)
                except json.JSONDecodeError as e:
                    logger.warning(f"Malformed JSON in {session_path}:{line_num}: {e}")
                    continue

                # Extract message metadata
                if msg.get("type") == "message" and msg.get("role") == "assistant":
                    messages.append(msg)

                    # Track timestamps
                    if "timestamp" in msg:
                        ts = datetime.fromisoformat(msg["timestamp"].replace("Z", "+00:00"))
                        if start_time is None or ts < start_time:
                            start_time = ts
                        if end_time is None or ts > end_time:
                            end_time = ts

                    # Track model usage
                    model = msg.get("model", "unknown")
                    usage = msg.get("usage", {})
                    if model not in model_usage:
                        model_usage[model] = {
                            "input_tokens": 0,
                            "output_tokens": 0,
                            "cache_read": 0,
                            "cache_creation": 0,
                            "message_count": 0,
                        }

                    model_usage[model]["input_tokens"] += usage.get("input_tokens", 0)
                    model_usage[model]["output_tokens"] += usage.get("output_tokens", 0)
                    model_usage[model]["cache_read"] += usage.get("cache_read_input_tokens", 0)
                    model_usage[model]["cache_creation"] += usage.get(
                        "cache_creation_input_tokens", 0
                    )
                    model_usage[model]["message_count"] += 1

                # Track tool calls (Claude Code-specific)
                if msg.get("type") == "tool_result":
                    tool_name = msg.get("tool_name", "unknown")
                    tool_calls_by_type[tool_name] = tool_calls_by_type.get(tool_name, 0) + 1

    except Exception as e:
        logger.error(f"Error parsing {session_path}: {e}")
        return None

    if not messages:
        return None

    # Calculate totals
    total_input = sum(m["usage"].get("input_tokens", 0) for m in messages)
    total_output = sum(m["usage"].get("output_tokens", 0) for m in messages)
    total_cache_read = sum(m["usage"].get("cache_read_input_tokens", 0) for m in messages)
    total_cache_creation = sum(
        m["usage"].get("cache_creation_input_tokens", 0) for m in messages
    )
    total_tokens = total_input + total_output + total_cache_read + total_cache_creation

    # Calculate cost
    total_cost = sum(
        _calculate_cost(msg.get("usage", {}), msg.get("model", "")) for msg in messages
    )

    # Duration
    duration_minutes = 0
    if start_time and end_time:
        duration_minutes = int((end_time - start_time).total_seconds() / 60)

    # Determine primary model (most-used)
    primary_model = max(model_usage.items(), key=lambda x: x[1]["message_count"])[0] if model_usage else "unknown"

    return {
        "session_id": session_path.stem,
        "project_path": None,  # Will be set by caller
        "start_time": start_time.isoformat() if start_time else None,
        "end_time": end_time.isoformat() if end_time else None,
        "duration_minutes": duration_minutes,
        "total_input_tokens": total_input,
        "total_output_tokens": total_output,
        "total_cache_read_tokens": total_cache_read,
        "total_cache_creation_tokens": total_cache_creation,
        "total_tokens": total_tokens,
        "cost_usd": round(total_cost, 2),
        "message_count": len(messages),
        "tool_call_count": sum(tool_calls_by_type.values()),
        "tool_calls": tool_calls_by_type,
        "model_usage": model_usage,
        "primary_model": primary_model,
        "source_file": str(session_path),
    }


def parse_sessions(claude_dir: Path, days: int = 90) -> Generator[dict, None, None]:
    """
    Generator that yields parsed sessions from all projects.

    Filters by age (default 90 days).

    Args:
        claude_dir: Path to ~/.claude/
        days: Only include sessions from the last N days

    Yields:
        Parsed session dicts
    """
    cutoff = datetime.now() - timedelta(days=days)

    projects_dir = claude_dir / "projects"
    if not projects_dir.exists():
        return

    for project_dir in projects_dir.iterdir():
        if not project_dir.is_dir():
            continue

        project_name = _decode_project_path(project_dir.name)
        sessions_dir = project_dir / "sessions"

        if not sessions_dir.exists():
            continue

        for session_file in sessions_dir.glob(JSONL_PATTERN):
            # Skip non-session files
            if session_file.name.startswith("sessions-index"):
                continue

            # Check file modification time
            mtime = datetime.fromtimestamp(session_file.stat().st_mtime)
            if mtime < cutoff:
                continue

            parsed = _parse_session_jsonl(session_file)
            if parsed:
                parsed["project_path"] = project_name
                yield parsed


def get_daily_usage(claude_dir: Path, days: int = 90) -> list[dict]:
    """
    Aggregate usage by day from all sessions.

    Returns:
        List of dicts: {"date": "YYYY-MM-DD", "sessions": N, "total_tokens": N, "cost_usd": float, ...}
    """
    daily_stats = {}

    for session in parse_sessions(claude_dir, days=days):
        if not session["start_time"]:
            continue

        date = session["start_time"].split("T")[0]
        if date not in daily_stats:
            daily_stats[date] = {
                "date": date,
                "sessions": 0,
                "total_tokens": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "cache_read_tokens": 0,
                "cache_creation_tokens": 0,
                "cost_usd": 0.0,
                "tool_calls": 0,
                "projects": set(),
                "models": {},
            }

        daily = daily_stats[date]
        daily["sessions"] += 1
        daily["total_tokens"] += session["total_tokens"]
        daily["input_tokens"] += session["total_input_tokens"]
        daily["output_tokens"] += session["total_output_tokens"]
        daily["cache_read_tokens"] += session["total_cache_read_tokens"]
        daily["cache_creation_tokens"] += session["total_cache_creation_tokens"]
        daily["cost_usd"] += session["cost_usd"]
        daily["tool_calls"] += session["tool_call_count"]
        daily["projects"].add(session["project_path"] or "unknown")

        # Track model usage
        for model_id, usage in session["model_usage"].items():
            if model_id not in daily["models"]:
                daily["models"][model_id] = {"tokens": 0, "messages": 0}
            daily["models"][model_id]["tokens"] += (
                usage["input_tokens"]
                + usage["output_tokens"]
                + usage["cache_read"]
                + usage["cache_creation"]
            )
            daily["models"][model_id]["messages"] += usage["message_count"]

    # Convert sets to counts
    result = []
    for daily in daily_stats.values():
        daily["active_projects"] = len(daily["projects"])
        del daily["projects"]
        result.append(daily)

    return sorted(result, key=lambda x: x["date"])


def get_monthly_usage(claude_dir: Path, months: int = 6) -> list[dict]:
    """
    Aggregate usage by month from all sessions.

    Returns:
        List of dicts: {"month": "YYYY-MM", "sessions": N, "total_tokens": N, ...}
    """
    monthly_stats = {}
    days_cutoff = months * 31

    for session in parse_sessions(claude_dir, days=days_cutoff):
        if not session["start_time"]:
            continue

        month = session["start_time"].split("-")[0] + "-" + session["start_time"].split("-")[1]
        if month not in monthly_stats:
            monthly_stats[month] = {
                "month": month,
                "sessions": 0,
                "total_tokens": 0,
                "cost_usd": 0.0,
                "active_days": set(),
                "models": {},
                "projects": set(),
            }

        monthly = monthly_stats[month]
        monthly["sessions"] += 1
        monthly["total_tokens"] += session["total_tokens"]
        monthly["cost_usd"] += session["cost_usd"]
        monthly["active_days"].add(session["start_time"].split("T")[0])
        monthly["projects"].add(session["project_path"] or "unknown")

        for model_id, usage in session["model_usage"].items():
            if model_id not in monthly["models"]:
                monthly["models"][model_id] = {"tokens": 0, "messages": 0}
            monthly["models"][model_id]["tokens"] += (
                usage["input_tokens"]
                + usage["output_tokens"]
                + usage["cache_read"]
                + usage["cache_creation"]
            )
            monthly["models"][model_id]["messages"] += usage["message_count"]

    # Convert sets to counts
    result = []
    for monthly in monthly_stats.values():
        monthly["active_days"] = len(monthly["active_days"])
        monthly["active_projects"] = len(monthly["projects"])
        del monthly["projects"]
        result.append(monthly)

    return sorted(result, key=lambda x: x["month"])


# ============================================================
# Phase 5.2: Incremental Parsing with Scan Index
# ============================================================
def _should_skip_file(file_path_str: str, file_mtime_int: int, db_module) -> bool:
    """Check if file should be skipped (unchanged since last scan)."""
    scan_entry = db_module.get_scan_index(file_path_str)
    return scan_entry and scan_entry["last_modified"] == file_mtime_int


def _is_session_recent(session: dict, cutoff: datetime) -> bool:
    """Check if session is within the time cutoff."""
    try:
        session_time = datetime.fromisoformat(session["start_time"].replace("Z", "+00:00"))
        return session_time >= cutoff
    except (KeyError, ValueError):
        return False


def _process_session_file(session_file: Path, db_module, cutoff: datetime) -> dict | None:
    """Process a single session file, returning parsed session or None."""
    try:
        file_mtime_int = int(session_file.stat().st_mtime)
        file_path_str = str(session_file)

        if _should_skip_file(file_path_str, file_mtime_int, db_module):
            logger.debug(f"Skipping unchanged file: {session_file.name}")
            return None

        session = _parse_session_jsonl(session_file)
        if not session or not _is_session_recent(session, cutoff):
            return None

        db_module.update_scan_index(file_path_str, file_mtime_int, session_file.stat().st_size)
        return session
    except Exception as e:
        logger.warning(f"Error processing {session_file}: {e}")
        return None


def parse_sessions_incremental(
    claude_dir: Path, db_module, days: int = 90
) -> Generator[dict, None, None]:
    """
    Generator that yields parsed sessions with incremental scanning.

    Uses scan_index table to avoid re-parsing unchanged files.
    Only re-parses files that have been modified since last scan.

    Args:
        claude_dir: Path to ~/.claude/
        db_module: Database module with scan_index functions
        days: Only include sessions from the last N days

    Yields:
        Parsed session dicts
    """
    cutoff = datetime.now() - timedelta(days=days)
    projects_dir = claude_dir / "projects"
    if not projects_dir.exists():
        return

    for project_dir in projects_dir.iterdir():
        if not project_dir.is_dir():
            continue

        sessions_dir = project_dir / "sessions"
        if not sessions_dir.exists():
            continue

        for session_file in sessions_dir.glob(JSONL_PATTERN):
            session = _process_session_file(session_file, db_module, cutoff)
            if session:
                yield session
