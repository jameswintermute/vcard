"""checkpoint.py — save and restore in-progress merge state.

A checkpoint consists of two files in cards-wip/:
  - checkpoint.vcf       the full merged card list as a standard vCard file
  - checkpoint.json      metadata: timestamp, review_index, source_files, counts

The review_index records how many cards have been through category review so
that on resume we skip straight to where the user left off.
"""
from __future__ import annotations

import json
from datetime import datetime, UTC
from pathlib import Path

from .exporter import export_vcards
from .io import read_vcards_from_files
from .model import Card
from .normalize import normalize_cards

CHECKPOINT_VCF  = "checkpoint.vcf"
CHECKPOINT_META = "checkpoint.json"


# ── Save ───────────────────────────────────────────────────────────────────────

def save_checkpoint(
    cards: list[Card],
    work_dir: Path,
    review_index: int = 0,
    source_files: list[str] | None = None,
    input_count: int = 0,
    duplicate_clusters: int = 0,
) -> None:
    """Serialise cards to cards-wip/checkpoint.vcf and write metadata."""
    work_dir.mkdir(parents=True, exist_ok=True)
    vcf_path  = work_dir / CHECKPOINT_VCF
    meta_path = work_dir / CHECKPOINT_META

    export_vcards(cards, vcf_path, target_version="4.0")

    meta = {
        "saved_at":          datetime.now(UTC).isoformat(),
        "review_index":      review_index,
        "total_cards":       len(cards),
        "input_count":       input_count,
        "duplicate_clusters": duplicate_clusters,
        "source_files":      source_files or [],
    }
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")


# ── Load ───────────────────────────────────────────────────────────────────────

def load_checkpoint(work_dir: Path) -> tuple[list[Card], dict] | None:
    """Return (cards, meta) if a valid checkpoint exists, else None.

    Resilient: if checkpoint.json is missing or corrupt we still load
    checkpoint.vcf and return a synthetic meta dict so the session resumes.
    """
    vcf_path  = work_dir / CHECKPOINT_VCF
    meta_path = work_dir / CHECKPOINT_META

    if not vcf_path.exists():
        return None

    # Load meta — tolerate missing / corrupt JSON
    meta: dict = {}
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"  [checkpoint] warning: could not read {meta_path.name}: {e}", flush=True)
    else:
        print(f"  [checkpoint] {CHECKPOINT_META} not found — loading {CHECKPOINT_VCF} anyway", flush=True)

    try:
        raw_pairs = read_vcards_from_files([vcf_path])
        cards = normalize_cards(raw_pairs)
        # Fill in synthetic meta if it was missing/empty
        if not meta:
            meta = {
                "saved_at": datetime.fromtimestamp(vcf_path.stat().st_mtime, tz=UTC).isoformat(),
                "review_index": 0,
                "total_cards": len(cards),
                "input_count": len(cards),
                "duplicate_clusters": 0,
                "source_files": [],
            }
        print(f"  [checkpoint] loaded {len(cards)} cards OK", flush=True)
        return cards, meta
    except Exception as e:
        print(f"  [checkpoint] ERROR loading {CHECKPOINT_VCF}: {e}", flush=True)
        return None


# ── Clear ──────────────────────────────────────────────────────────────────────

def clear_checkpoint(work_dir: Path) -> None:
    """Delete checkpoint files after a successful export."""
    for name in (CHECKPOINT_VCF, CHECKPOINT_META):
        p = work_dir / name
        if p.exists():
            p.unlink()


# ── Query ──────────────────────────────────────────────────────────────────────

def checkpoint_info(work_dir: Path) -> dict | None:
    """Return metadata dict if a checkpoint exists, else None. Does not load cards."""
    meta_path = work_dir / CHECKPOINT_META
    if not meta_path.exists():
        return None
    try:
        return json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception:
        return None
