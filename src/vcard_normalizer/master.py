"""master.py — persistent master contact database.

Replaces the old cards-wip/checkpoint model with a proper permanent store:

  cards-master/
    master.vcf          compiled master — all contacts in one file (fast load)
    master.json         metadata: saved_at, total_cards, source_files, etc.
    contacts/           one .vcf per contact, named by UID
      vcard-studio-<uuid>.vcf

On every save:
  1. Each changed contact is written to contacts/<uid>.vcf
  2. master.vcf is rewritten from in-memory state
  3. master.json is updated

On load (startup):
  1. Load master.vcf if present — fast path
  2. Reconstruct from contacts/ if master.vcf is missing or corrupt
  3. Legacy fallback: cards-wip/checkpoint.vcf (migration path)

The contacts/ folder gives individual-file durability and clean git diffs.
master.vcf is a compiled view for O(1) startup.
"""
from __future__ import annotations

import json
import re
import shutil
from datetime import datetime, UTC
from pathlib import Path

from .exporter import export_vcards, card_to_vcf_text
from .io import read_vcards_from_files
from .model import Card
from .normalize import normalize_cards

MASTER_DIR      = "cards-master"
MASTER_VCF      = "master.vcf"
MASTER_META     = "master.json"
CONTACTS_DIR    = "contacts"


# ── Helpers ────────────────────────────────────────────────────────────────────

def _master_dir(root: Path) -> Path:
    d = root / MASTER_DIR
    d.mkdir(parents=True, exist_ok=True)
    return d


def _contacts_dir(root: Path) -> Path:
    d = root / MASTER_DIR / CONTACTS_DIR
    d.mkdir(parents=True, exist_ok=True)
    return d


def _safe_filename(uid: str) -> str:
    """Turn a UID into a safe filename — strip path chars."""
    return re.sub(r"[^\w\-]", "_", uid)[:120] + ".vcf"


# ── Save ───────────────────────────────────────────────────────────────────────

def save_master(
    cards: list[Card],
    root: Path,
    source_files: list[str] | None = None,
    input_count: int = 0,
    duplicate_clusters: int = 0,
    changed_indices: list[int] | None = None,
) -> None:
    """Write master state to cards-master/.

    changed_indices: if provided, only rewrite those contact files.
                     If None, rewrite all contact files (e.g. after Unify).
    Always rewrites master.vcf and master.json.
    """
    mdir = _master_dir(root)
    cdir = _contacts_dir(root)

    # 1. Write individual contact files
    if changed_indices is None:
        # Full rewrite — Unify or first import
        to_write = list(enumerate(cards))
    else:
        to_write = [(i, cards[i]) for i in changed_indices if 0 <= i < len(cards)]

    for _, card in to_write:
        uid = card.uid or ""
        if uid:
            fname = cdir / _safe_filename(uid)
            try:
                text = card_to_vcf_text(card, target_version="4.0")
                fname.write_text(text, encoding="utf-8")
            except Exception as e:
                print(f"  [master] warning: could not write {fname.name}: {e}", flush=True)

    # 2. Rewrite compiled master.vcf
    vcf_path = mdir / MASTER_VCF
    try:
        export_vcards(cards, vcf_path, target_version="4.0")
    except Exception as e:
        print(f"  [master] ERROR writing master.vcf: {e}", flush=True)
        raise

    # 3. Write metadata
    meta = {
        "saved_at":            datetime.now(UTC).isoformat(),
        "total_cards":         len(cards),
        "input_count":         input_count or len(cards),
        "duplicate_clusters":  duplicate_clusters,
        "source_files":        source_files or [],
        "schema_version":      "2",
    }
    (mdir / MASTER_META).write_text(json.dumps(meta, indent=2), encoding="utf-8")


# ── Load ───────────────────────────────────────────────────────────────────────

def load_master(root: Path) -> tuple[list[Card], dict] | None:
    """Return (cards, meta) from cards-master/, or None if not present.

    Priority:
      1. master.vcf fast path
      2. Reconstruct from contacts/ if master.vcf is missing/corrupt
    """
    mdir = root / MASTER_DIR
    vcf_path  = mdir / MASTER_VCF
    meta_path = mdir / MASTER_META

    # Load metadata
    meta: dict = {}
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"  [master] warning: could not read master.json: {e}", flush=True)

    # Fast path — load master.vcf
    if vcf_path.exists() and vcf_path.stat().st_size > 10:
        try:
            raw_pairs = read_vcards_from_files([vcf_path])
            cards = normalize_cards(raw_pairs)
            if not meta:
                meta = _synthetic_meta(vcf_path, cards)
            print(f"  [master] loaded {len(cards)} cards from master.vcf", flush=True)
            return cards, meta
        except Exception as e:
            print(f"  [master] master.vcf failed ({e}), trying contacts/…", flush=True)

    # Fallback — reconstruct from individual contact files
    cdir = mdir / CONTACTS_DIR
    if cdir.is_dir():
        vcf_files = sorted(cdir.glob("*.vcf"))
        if vcf_files:
            try:
                raw_pairs = read_vcards_from_files(vcf_files)
                cards = normalize_cards(raw_pairs)
                if not meta:
                    meta = _synthetic_meta(None, cards)
                print(f"  [master] reconstructed {len(cards)} cards from {len(vcf_files)} contact files", flush=True)
                # Rebuild master.vcf from contacts
                try:
                    export_vcards(cards, mdir / MASTER_VCF, target_version="4.0")
                    print(f"  [master] rebuilt master.vcf", flush=True)
                except Exception:
                    pass
                return cards, meta
            except Exception as e:
                print(f"  [master] ERROR reconstructing from contacts/: {e}", flush=True)

    return None


def _synthetic_meta(vcf_path: Path | None, cards: list[Card]) -> dict:
    mtime = vcf_path.stat().st_mtime if vcf_path else 0
    return {
        "saved_at": datetime.fromtimestamp(mtime, tz=UTC).isoformat() if mtime else datetime.now(UTC).isoformat(),
        "total_cards": len(cards),
        "input_count": len(cards),
        "duplicate_clusters": 0,
        "source_files": [],
        "schema_version": "2",
    }


# ── Additive import (merge new cards-in into master) ──────────────────────────

def merge_import_into_master(
    new_cards: list[Card],
    existing_cards: list[Card],
) -> tuple[list[Card], int, int]:
    """Merge newly imported cards into the existing master.

    Returns (merged_list, added_count, updated_count).

    Strategy:
    - Match by UID first (exact)
    - Match by normalised FN + primary email as fallback
    - New cards with no match are appended
    - Existing cards with a match are updated only if the new card is richer
      (more fields populated) — never silently overwrite user edits
    """
    existing_by_uid:   dict[str, int] = {}
    existing_by_email: dict[str, int] = {}

    for i, c in enumerate(existing_cards):
        if c.uid:
            existing_by_uid[c.uid] = i
        for e in (c.emails or []):
            existing_by_email[e.lower()] = i

    result = list(existing_cards)
    added = updated = 0

    for nc in new_cards:
        idx = None
        # 1. Match by UID
        if nc.uid and nc.uid in existing_by_uid:
            idx = existing_by_uid[nc.uid]
        # 2. Match by primary email
        elif nc.emails:
            idx = existing_by_email.get(nc.emails[0].lower())

        if idx is not None:
            # Only update if new card has more information
            ec = result[idx]
            if _card_richness(nc) > _card_richness(ec):
                result[idx] = nc
                updated += 1
        else:
            result.append(nc)
            if nc.uid:
                existing_by_uid[nc.uid] = len(result) - 1
            for e in (nc.emails or []):
                existing_by_email[e.lower()] = len(result) - 1
            added += 1

    return result, added, updated


def _card_richness(c: Card) -> int:
    """Simple score — more populated fields = richer card."""
    score = 0
    if c.fn:           score += 2
    if c.emails:       score += len(c.emails)
    if c.tels:         score += len(c.tels)
    if c.addresses:    score += 2
    if c.org:          score += 1
    if c.bday:         score += 1
    if c.categories:   score += len(c.categories)
    if c.related:      score += len(c.related)
    if c.note:         score += 1
    return score


# ── Info ───────────────────────────────────────────────────────────────────────

def master_info(root: Path) -> dict | None:
    """Return metadata dict without loading cards. Used by status API."""
    meta_path = root / MASTER_DIR / MASTER_META
    if not meta_path.exists():
        return None
    try:
        return json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception:
        return None


# ── Migration ──────────────────────────────────────────────────────────────────

def migrate_from_checkpoint(root: Path) -> bool:
    """If cards-wip/checkpoint.vcf exists and cards-master/ does not, migrate.

    Returns True if migration was performed.
    """
    wip_vcf  = root / "cards-wip" / "checkpoint.vcf"
    wip_meta = root / "cards-wip" / "checkpoint.json"
    master_vcf = root / MASTER_DIR / MASTER_VCF

    if master_vcf.exists() or not wip_vcf.exists():
        return False

    print("  [master] migrating checkpoint → cards-master/", flush=True)
    try:
        mdir = _master_dir(root)
        shutil.copy2(wip_vcf, mdir / MASTER_VCF)
        if wip_meta.exists():
            old_meta = json.loads(wip_meta.read_text(encoding="utf-8"))
            old_meta["schema_version"] = "2"
            old_meta.setdefault("source_files", [])
            (mdir / MASTER_META).write_text(json.dumps(old_meta, indent=2), encoding="utf-8")
        print("  [master] migration complete", flush=True)
        return True
    except Exception as e:
        print(f"  [master] migration failed: {e}", flush=True)
        return False
