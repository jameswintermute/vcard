"""activitylog.py — syslog-style activity log for vCard Studio.

Writes to log/activity.log in the project root.
Format: YYYY-MM-DD HH:MM:SS  EVENT  message

No sensitive data is ever written — only counts, UIDs, and event types.
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path


_log_path: Path | None = None


def init_log(root: Path) -> None:
    """Initialise the log file path. Call once at server startup."""
    global _log_path
    log_dir = root / "log"
    log_dir.mkdir(parents=True, exist_ok=True)
    _log_path = log_dir / "activity.log"


def _write(event: str, message: str) -> None:
    if _log_path is None:
        return
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"{ts}  {event:<20}  {message}\n"
    try:
        with _log_path.open("a", encoding="utf-8") as f:
            f.write(line)
    except Exception as e:
        print(f"  [log] warning: could not write log: {e}", file=sys.stderr)


# ── Public log events ──────────────────────────────────────────────────────────

def log_startup(card_count: int, source: str) -> None:
    _write("STARTUP", f"loaded {card_count} contacts from {source}")


def log_import(file_count: int, card_count: int, added: int, updated: int) -> None:
    _write("IMPORT", f"imported {file_count} file(s) with {card_count} contacts — {added} added, {updated} updated")


def log_unify(card_count: int, dup_count: int) -> None:
    _write("UNIFY", f"processed {card_count} contacts, {dup_count} duplicate cluster(s) merged")


def log_card_edit(uid: str, change_count: int) -> None:
    safe_uid = uid[:40] if uid else "unknown"
    _write("EDIT", f"wrote {change_count} change(s) to card UID {safe_uid}")


def log_card_add(uid: str, fn_hint: str) -> None:
    """fn_hint is only used to describe the card type (e.g. 'individual', 'org') — no names."""
    safe_uid = uid[:40] if uid else "unknown"
    _write("ADD", f"added new contact UID {safe_uid} ({fn_hint})")


def log_card_delete(uid: str) -> None:
    safe_uid = uid[:40] if uid else "unknown"
    _write("DELETE", f"deleted contact UID {safe_uid}")


def log_export(card_count: int, filename: str, format_: str) -> None:
    _write("EXPORT", f"exported {card_count} contacts to {filename} ({format_})")


def log_bulk_category(category: str, count: int) -> None:
    _write("BULK_CATEGORY", f"added category '{category}' to {count} contact(s)")


def log_merge(count: int, into_uid: str) -> None:
    safe_uid = into_uid[:40] if into_uid else "unknown"
    _write("MERGE", f"merged {count} contacts into UID {safe_uid}")


def log_save_master(card_count: int, changed: int | None) -> None:
    if changed is not None:
        _write("SAVE", f"master saved — {changed} contact file(s) updated, {card_count} total")
    else:
        _write("SAVE", f"master saved — full rewrite, {card_count} contacts")


def log_error(context: str, message: str) -> None:
    _write("ERROR", f"[{context}] {message}")
