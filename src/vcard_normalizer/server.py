"""server.py — local HTTP server for the vCard Studio web UI.

Uses only Python stdlib (http.server, json, threading, webbrowser).
No new dependencies required.

Starts a server on localhost:8421, opens the browser, and shuts down
cleanly when the browser tab sends a /quit request or the user hits Ctrl-C.
"""
from __future__ import annotations

import json
import mimetypes
import os
import re
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

# ── Resolve project root (2 levels up from this file: src/vcard_normalizer/) ──
_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent.parent   # project root
_VERSION = "3.3.0"
_STATIC = _HERE / "static"    # HTML/CSS/JS lives here

PORT = 8421


# ── Import the processing pipeline ────────────────────────────────────────────

def _get_pipeline():
    """Lazy import of processing modules — keeps startup fast."""
    from .config import ensure_workspace
    from .io import collect_merge_sources, read_vcards_from_files
    from .normalize import normalize_cards
    from .proprietary import DefaultStripper
    from .formatters import (
        normalize_phones_in_cards, classify_entities, auto_tag_categories,
    )
    from .dedupe import find_duplicate_clusters, merge_cluster_auto
    from .exporter import export_vcards
    from .checkpoint import (
        save_checkpoint, load_checkpoint, checkpoint_info, clear_checkpoint,
    )
    return {
        "ensure_workspace": ensure_workspace,
        "collect_merge_sources": collect_merge_sources,
        "read_vcards_from_files": read_vcards_from_files,
        "normalize_cards": normalize_cards,
        "DefaultStripper": DefaultStripper,
        "normalize_phones_in_cards": normalize_phones_in_cards,
        "classify_entities": classify_entities,
        "auto_tag_categories": auto_tag_categories,
        "find_duplicate_clusters": find_duplicate_clusters,
        "merge_cluster_auto": merge_cluster_auto,
        "export_vcards": export_vcards,
        "save_checkpoint": save_checkpoint,
        "load_checkpoint": load_checkpoint,
        "checkpoint_info": checkpoint_info,
        "clear_checkpoint": clear_checkpoint,
    }


# ── State shared with handler ──────────────────────────────────────────────────

_state: dict = {
    "cards": [],          # list[Card] after processing
    "status": "idle",     # idle | loaded | processing | done | error
    "message": "",
    "progress": 0,
    "source_counts": {},
    "input_count": 0,
    "dup_count": 0,
}
_server_ref: HTTPServer | None = None


# ── Helper: card → dict ────────────────────────────────────────────────────────

def _fmt_tel(t: str) -> str:
    """Format a phone number for display using libphonenumber if available."""
    try:
        from .formatters import _format_spaced_e164 as _spaced
        import phonenumbers as _pn
        n = _pn.parse(t, "GB")
        if _pn.is_possible_number(n):
            return _spaced(n)
    except Exception:
        pass
    return t


def _card_to_dict(card) -> dict:
    # Guard against old checkpoint cards that predate NameComponents
    from .model import NameComponents
    name = getattr(card, "name", None) or NameComponents()

    return {
        "fn": card.fn or "",
        "org": card.org or "",
        "emails": card.emails,
        "tels": card.tels,
        "tels_fmt": [_fmt_tel(t) for t in card.tels],  # formatted for display only
        # TYPE-labelled parallel lists: [{value, type}] — type is HOME|WORK|CELL|""
        "typed_emails": [{"value": tv.value, "type": tv.type} for tv in (getattr(card, "typed_emails", None) or [])],
        "typed_tels":   [{"value": tv.value, "type": tv.type} for tv in (getattr(card, "typed_tels",   None) or [])],
        "categories": card.categories,
        "kind": card.kind or ("org" if (card.org and not card.fn) else "individual"),
        "gender": card.gender or "",
        "title": card.title or "",
        "bday": card.bday or "",
        "anniversary": card.anniversary or "",
        "note": card.note or "",
        "uid": card.uid or "",
        "rev": card.rev or "",
        # Structured name components
        "name_prefix":     name.prefix,
        "name_given":      name.given,
        "name_additional": name.additional,
        "name_family":     name.family,
        "name_suffix":     name.suffix,
        "addresses": [
            {
                "street":      a.street or "",
                "locality":    a.locality or "",
                "region":      a.region or "",
                "postal_code": a.postal_code or "",
                "country":     a.country or "",
            }
            for a in card.addresses
        ],
        "related": [
            {"rel_type": r.rel_type, "uid": r.uid or "", "text": r.text or ""}
            for r in (card.related or [])
        ],
        "member": list(getattr(card, "member", None) or []),
        "changes": card._changes,
        "sources": card._source_files,
        "waived": list(getattr(card, "_waived", set()) or set()),
    }


# ── API handlers ───────────────────────────────────────────────────────────────

def _load_existing_output() -> None:
    """On startup, restore the most recent available state.

    Priority:
      1. cards-wip/checkpoint.vcf  — in-progress merge, most current
      2. cards-out/*.vcf           — last exported file, fallback
    """
    p = _get_pipeline()

    # 1. Try checkpoint first
    wip_dir = _ROOT / "cards-wip"
    try:
        result = p["load_checkpoint"](wip_dir)
        if result is not None:
            cards, meta = result
            _state["cards"] = cards
            _state["status"] = "loaded"
            _state["input_count"] = meta.get("input_count", len(cards))
            _state["dup_count"] = meta.get("duplicate_clusters", 0)
            srcs = meta.get("source_files", [])
            _state["source_counts"] = {s: 0 for s in srcs}
            _state["message"] = (
                f"Resumed {len(cards)} contacts from checkpoint "
                f"(saved {meta.get('saved_at','?')[:10]})"
            )
            return
    except Exception as _e:
        import logging
        logging.getLogger(__name__).warning("Checkpoint load failed: %s", _e)
        _state["message"] = f"⚠ Checkpoint load error: {_e}"

    # 2. Legacy: any named .vcf in cards-wip/ (old installs used dated filenames)
    if wip_dir.is_dir():
        legacy_vcfs = sorted(
            [f for f in wip_dir.glob("*.vcf") if f.name != "checkpoint.vcf"],
            key=lambda f: f.stat().st_mtime, reverse=True
        )
        if legacy_vcfs:
            try:
                raw_pairs = p["read_vcards_from_files"]([legacy_vcfs[0]])
                cards = p["normalize_cards"](raw_pairs)
                _state["cards"] = cards
                _state["status"] = "loaded"
                _state["input_count"] = len(cards)
                _state["dup_count"] = 0
                _state["source_counts"] = {legacy_vcfs[0].stem: len(cards)}
                _state["message"] = (
                    f"Loaded {len(cards)} contacts from {legacy_vcfs[0].name}"
                )
                return
            except Exception:
                pass

    # 3. Fall back to most recent export in cards-out/
    clean_dir = _ROOT / "cards-out"
    if not clean_dir.is_dir():
        return
    vcfs = sorted(clean_dir.glob("*.vcf"), key=lambda f: f.stat().st_mtime, reverse=True)
    # 3 cont. — Exclude checkpoint files that may have been exported there
    vcfs = [v for v in vcfs if "checkpoint" not in v.name]
    if not vcfs:
        return

    try:
        raw_pairs = p["read_vcards_from_files"]([vcfs[0]])
        cards = p["normalize_cards"](raw_pairs)

        from .report import build_source_counts
        source_counts = build_source_counts(raw_pairs)

        _state["cards"] = cards
        _state["status"] = "loaded"
        _state["input_count"] = len(cards)
        _state["dup_count"] = 0
        _state["source_counts"] = {vcfs[0].stem: len(cards)}
        _state["message"] = (
            f"Loaded {len(cards)} contacts from last export: {vcfs[0].name}"
        )
    except Exception:
        pass  # Silently skip — don't break startup


def _api_status() -> dict:
    cards = _state["cards"]
    print(f"  [status] cards={len(cards)} status={_state['status']}", flush=True)
    cats: dict[str, int] = {}
    countries: dict[str, int] = {}
    gender_m = gender_f = gender_unset = 0
    for c in cards:
        try:
            for cat in (c.categories or []):
                cats[cat] = cats.get(cat, 0) + 1
            country = ""
            if c.addresses:
                country = (c.addresses[0].country or "").strip()
            if country:
                countries[country] = countries.get(country, 0) + 1
            if c.kind != "org":
                g = (c.gender or "").upper()
                if g == "M":   gender_m += 1
                elif g == "F": gender_f += 1
                else:          gender_unset += 1
        except Exception:
            pass

    # If we have cards but status is still "error" (e.g. stale from a failed re-merge),
    # report "loaded" so the header dot turns green and the UI isn't misleading.
    reported_status = _state["status"]
    if cards and reported_status == "error":
        reported_status = "loaded"
        _state["status"] = "loaded"

    # Find self card for owner name auto-population
    self_card_info = None
    for c in cards:
        if c.kind == "self":
            name = getattr(c, "name", None)
            given  = (name.given  or "").strip() if name else ""
            family = (name.family or "").strip() if name else ""
            fn = c.fn or ""
            self_card_info = {"fn": fn, "given": given, "family": family}
            break

    return {
        "version": _VERSION,
        "status": reported_status,
        "message": _state["message"],
        "progress": _state["progress"],
        "total_cards": len(cards),
        "source_counts": _state["source_counts"],
        "input_count": _state["input_count"],
        "dup_count": _state["dup_count"],
        "category_counts": cats,
        "country_counts": countries,
        "gender_counts": {"M": gender_m, "F": gender_f, "unset": gender_unset},
        "self_card": self_card_info,
        "sources_present": _get_source_filenames(),
        "checkpoint": _get_checkpoint_info(),
        "output_files": _get_output_files(),
    }


def _get_source_filenames() -> list[str]:
    merge_dir = _ROOT / "cards-in"
    if not merge_dir.is_dir():
        return []
    # Exclude placeholder / example files shipped with the project
    _EXCLUDE = {"sample.vcf", "example.vcf", "placeholder.vcf"}
    return sorted(
        p.name for p in merge_dir.iterdir()
        if p.suffix.lower() == ".vcf" and p.name.lower() not in _EXCLUDE
    )


def _get_checkpoint_info() -> dict | None:
    try:
        p = _get_pipeline()
        info = p["checkpoint_info"](_ROOT / "cards-wip")
        return info
    except Exception:
        return None


def _get_output_files() -> list[dict]:
    clean_dir = _ROOT / "cards-out"
    if not clean_dir.is_dir():
        return []
    files = sorted(
        clean_dir.glob("*.vcf"),
        key=lambda f: f.stat().st_mtime,
        reverse=True,
    )
    return [
        {"name": f.name, "size_kb": round(f.stat().st_size / 1024, 1)}
        for f in files[:5]
    ]


def _autosave_checkpoint() -> None:
    """Write current in-memory cards to cards-wip/checkpoint after every mutation.

    This is the key persistence guarantee: every edit, add, delete, or link
    is immediately durable.  Restart the server and all changes are there.
    """
    cards = _state.get("cards")
    if not cards:
        return
    try:
        p = _get_pipeline()
        p["save_checkpoint"](
            cards,
            work_dir=_ROOT / "cards-wip",
            review_index=0,
            source_files=list(_state.get("source_counts", {}).keys()),
            input_count=_state.get("input_count", len(cards)),
            duplicate_clusters=_state.get("dup_count", 0),
        )
    except Exception as exc:
        import sys
        print(f"[autosave] checkpoint write failed: {exc}", file=sys.stderr)


def _api_cards(params: dict) -> dict:
    cards = _state["cards"]
    page = int(params.get("page", ["1"])[0])
    per_page = int(params.get("per_page", ["50"])[0])
    category = params.get("category", [""])[0]
    search = params.get("search", [""])[0].lower()
    quality    = params.get("quality",     [""])[0]
    sort_order = params.get("sort_order",  ["last_name"])[0]  # last_name|first_name|org

    def _quality_match(c) -> bool:
        waived = getattr(c, "_waived", set()) or set()
        if quality == "no_email":    return not c.emails and "email" not in waived
        if quality == "no_phone":    return not c.tels and "phone" not in waived
        if quality == "no_category": return not c.categories and "category" not in waived
        if quality == "no_org":      return not c.org and c.kind != "org" and "org" not in waived
        if quality == "no_address":  return not c.addresses and "address" not in waived
        if quality == "num_prefix":  import re; return bool(re.match(r"^\d", c.fn or ""))
        return True

    # Keep global indices so the UI can address cards for edit/delete
    indexed = list(enumerate(cards))
    if category:
        indexed = [(i,c) for i,c in indexed if category in c.categories]
    if search:
        indexed = [(i,c) for i,c in indexed
                   if search in (c.fn or "").lower()
                   or search in (c.org or "").lower()
                   or any(search in e for e in c.emails)]
    if quality:
        indexed = [(i,c) for i,c in indexed if _quality_match(c)]

    # Sort the results — all kinds integrated lexicographically, no KIND bucketing
    def _sort_key(pair):
        _, c = pair
        fn = (c.fn or "").strip()
        org = (c.org or "").strip()
        # Guard against old checkpoint cards that predate NameComponents
        name = getattr(c, "name", None)
        family = (name.family or "").strip() if name and name.family else ""
        given  = (name.given  or "").strip() if name and name.given  else ""

        if sort_order == "first_name":
            primary = given.lower() or fn.lower() or org.lower()
            secondary = family.lower()
        else:  # last_name (default)
            if family:
                primary = family.lower()
                secondary = given.lower()
            else:
                # No structured name — use fn, or org for org-kind cards
                primary = fn.lower() or org.lower()
                secondary = ""

        return (primary, secondary)

    indexed.sort(key=_sort_key)

    # Pin self card(s) to the top of page 1, with a flag for the UI divider
    self_cards  = [(i, c) for i, c in indexed if c.kind == "self"]
    other_cards = [(i, c) for i, c in indexed if c.kind != "self"]
    indexed = self_cards + other_cards

    total = len(indexed)
    start = (page - 1) * per_page
    page_items = indexed[start:start + per_page]

    def _with_idx(i, c):
        d = _card_to_dict(c)
        d["_idx"] = i
        d["_is_self"] = (c.kind == "self")
        return d

    return {
        "total": total,
        "page": page,
        "per_page": per_page,
        "cards": [_with_idx(i, c) for i, c in page_items],
    }


def _api_process(body: dict) -> dict:
    """Run the full pipeline in a background thread."""
    def _run():
        try:
            p = _get_pipeline()
            _state["status"] = "processing"
            _state["progress"] = 5
            _state["message"] = "Reading source files…"

            paths, settings = p["ensure_workspace"](_ROOT)
            merge_dir = _ROOT / "cards-in"
            files = p["collect_merge_sources"](merge_dir)

            if not files:
                _state["status"] = "error"
                _state["message"] = "No .vcf files found in cards-in/"
                return

            _state["progress"] = 15
            _state["message"] = f"Parsing {len(files)} file(s)…"
            raw_pairs = p["read_vcards_from_files"](files)

            from .report import build_source_counts
            source_counts = build_source_counts(raw_pairs)
            _state["input_count"] = len(raw_pairs)
            _state["source_counts"] = source_counts

            _state["progress"] = 30
            _state["message"] = "Normalising fields…"
            cards = p["normalize_cards"](raw_pairs)

            stripper = p["DefaultStripper"](keep_unknown=False)
            cards = [stripper.strip(c) for c in cards]

            _state["progress"] = 45
            _state["message"] = "Normalising phone numbers…"
            region = body.get("region", settings.default_region)
            p["normalize_phones_in_cards"](cards, default_region=region, infer_from_adr=True)

            _state["progress"] = 55
            _state["message"] = "Classifying contacts…"
            p["classify_entities"](cards)
            p["auto_tag_categories"](cards)

            _state["progress"] = 65
            _state["message"] = "Finding duplicates…"
            clusters = p["find_duplicate_clusters"](cards)
            dup_clusters = [cl for cl in clusters if len(cl) > 1]
            _state["dup_count"] = len(dup_clusters)

            _state["progress"] = 80
            _state["message"] = f"Merging {len(dup_clusters)} duplicate cluster(s)…"
            merged = []
            for cluster in clusters:
                if len(cluster) == 1:
                    merged.append(cluster[0])
                else:
                    merged.append(p["merge_cluster_auto"](cluster))

            _state["progress"] = 95
            _state["message"] = "Saving checkpoint…"
            p["save_checkpoint"](
                merged,
                work_dir=_ROOT / "cards-wip",
                review_index=0,
                source_files=list(source_counts.keys()),
                input_count=len(raw_pairs),
                duplicate_clusters=len(dup_clusters),
            )

            _state["cards"] = merged
            _state["status"] = "loaded"
            _state["progress"] = 100
            _state["message"] = (
                f"Loaded {len(merged)} contacts "
                f"({len(dup_clusters)} duplicates merged)"
            )

        except Exception as exc:
            _state["status"] = "error"
            _state["message"] = str(exc)
            _state["progress"] = 0

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return {"ok": True, "message": "Processing started"}


def _get_apple_name_warnings(cards) -> list:
    """Return list of (uid, fn) for contacts that will render badly on Apple/iOS.

    Apple ignores the FN field and builds the display name from the structured
    N field (given + family).  If both are empty the contact appears as just
    the prefix (e.g. 'Ms').  Flag: kind==individual, fn set, no given/family.
    """
    bad = []
    for c in cards:
        kind = (c.kind or "individual").lower()
        if kind not in ("individual", "self"):
            continue
        fn = (c.fn or "").strip()
        if not fn:
            continue
        name = c.name if hasattr(c, "name") else None
        given  = (name.given  or "").strip() if name else ""
        family = (name.family or "").strip() if name else ""
        if not given and not family:
            # X-IOS override already set — won't render badly on Apple
            if getattr(c, "x_ios_given", None) or getattr(c, "x_ios_family", None):
                continue
            bad.append({"uid": c.uid, "fn": fn})
    return bad


def _api_export(body: dict) -> dict:
    """Export current cards to cards-out/."""
    cards = _state["cards"]
    if not cards:
        return {"ok": False, "error": "No cards loaded — run process first"}

    try:
        p = _get_pipeline()
        from datetime import date
        _, settings = p["ensure_workspace"](_ROOT)
        owner = body.get("owner_name", settings.owner_name)
        version = body.get("version", "4.0")
        apple_compat = bool(body.get("apple_compat", False))
        if apple_compat:
            version = "3.0"  # force 3.0 for apple mode
        category_filter = body.get("category", "")
        categories_filter = body.get("categories", [])  # multi-select list, [] = all

        if categories_filter:
            export_cards = [c for c in cards if any(cat in c.categories for cat in categories_filter)]
        elif category_filter:
            export_cards = [c for c in cards if category_filter in c.categories]
        else:
            export_cards = cards

        from datetime import datetime
        iso = datetime.now().strftime('%Y-%m-%d-%H%M')
        safe = owner.replace(" ", "-")
        if categories_filter:
            safe_cat = "-".join(re.sub(r"[^\w-]", "-", c).strip("-") for c in sorted(categories_filter)[:2])
            if len(categories_filter) > 2:
                safe_cat += f"-and{len(categories_filter)-2}more"
        elif category_filter:
            safe_cat = re.sub(r"[^\w-]", "-", category_filter).strip("-")
        else:
            safe_cat = "All"
        out_label = "apple" if apple_compat else safe_cat
        out_path = _ROOT / "cards-out" / f"{iso}-{out_label}-{safe}.vcf"

        # Save a fresh checkpoint first so in-memory state is always durable
        # before we write the export (belt-and-suspenders durability)
        _autosave_checkpoint()

        # Apple/iOS name warning — check before writing so the user can fix first
        apple_name_warn = None
        if apple_compat:
            bad = _get_apple_name_warnings(export_cards)
            if bad:
                apple_name_warn = {
                    "count": len(bad),
                    "contacts": [b["fn"] for b in bad],
                }

        count = p["export_vcards"](export_cards, out_path, target_version=version, apple_compat=apple_compat)

        # Verify the export actually wrote to disk and contains the right count
        if not out_path.exists() or out_path.stat().st_size == 0:
            return {"ok": False, "error": "Export file was not written to disk — please retry"}

        if count != len(export_cards):
            import logging
            logging.getLogger(__name__).warning(
                "Export written=%d expected=%d — some cards skipped", count, len(export_cards)
            )
            # Still return ok but surface the discrepancy
            return {
                "ok": True, "count": count, "file": out_path.name,
                "warning": f"{len(export_cards) - count} contact(s) were skipped during export due to data errors",
                "apple_name_warning": apple_name_warn,
            }

        # Only clear checkpoint once we have verified the export is complete
        p["clear_checkpoint"](_ROOT / "cards-wip")

        return {"ok": True, "count": count, "file": out_path.name, "apple_name_warning": apple_name_warn}

    except Exception as exc:
        import traceback
        print(f"[export error] {traceback.format_exc()}", flush=True)
        return {"ok": False, "error": str(exc)}


def _api_export_csv(body: dict) -> dict:
    """Export current cards to a CSV file in cards-out/."""
    cards = _state["cards"]
    if not cards:
        return {"ok": False, "error": "No cards loaded — run process first"}
    try:
        import csv
        from datetime import date
        p = _get_pipeline()
        _, settings = p["ensure_workspace"](_ROOT)
        owner = body.get("owner_name", settings.owner_name)
        category_filter = body.get("category", "")
        categories_filter = body.get("categories", [])

        if categories_filter:
            export_cards = [c for c in cards if any(cat in c.categories for cat in categories_filter)]
        elif category_filter:
            export_cards = [c for c in cards if category_filter in c.categories]
        else:
            export_cards = cards

        from datetime import datetime
        iso = datetime.now().strftime('%Y-%m-%d-%H%M')
        safe = owner.replace(" ", "-")
        if categories_filter:
            safe_cat = "-".join(re.sub(r"[^\w-]", "-", c).strip("-") for c in sorted(categories_filter)[:2])
            if len(categories_filter) > 2:
                safe_cat += f"-and{len(categories_filter)-2}more"
        elif category_filter:
            safe_cat = re.sub(r"[^\w-]", "-", category_filter).strip("-")
        else:
            safe_cat = "All"
        out_path = _ROOT / "cards-out" / f"{iso}-{safe_cat}-{safe}.csv"
        out_path.parent.mkdir(parents=True, exist_ok=True)

        fields = ["fn", "org", "title", "email1", "email2", "tel1", "tel2",
                  "categories", "kind", "street", "city", "region", "postal", "country"]
        rows = []
        for c in sorted(export_cards, key=lambda x: (x.fn or "", x.org or "")):
            adr = c.addresses[0] if c.addresses else None
            rows.append({
                "fn": c.fn or "", "org": c.org or "", "title": c.title or "",
                "email1": c.emails[0] if len(c.emails) > 0 else "",
                "email2": c.emails[1] if len(c.emails) > 1 else "",
                "tel1": c.tels[0] if len(c.tels) > 0 else "",
                "tel2": c.tels[1] if len(c.tels) > 1 else "",
                "categories": ", ".join(c.categories),
                "kind": c.kind or "",
                "street": adr.street or "" if adr else "",
                "city": adr.locality or "" if adr else "",
                "region": adr.region or "" if adr else "",
                "postal": adr.postal_code or "" if adr else "",
                "country": adr.country or "" if adr else "",
            })

        with out_path.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            w.writerows(rows)

        return {"ok": True, "count": len(rows), "file": out_path.name}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _api_update_card(body: dict) -> dict:
    """Update a single card field by index."""
    cards = _state["cards"]
    idx = body.get("index")
    field = body.get("field")
    value = body.get("value")

    if idx is None or not field:
        return {"ok": False, "error": "Missing index or field"}
    if idx < 0 or idx >= len(cards):
        return {"ok": False, "error": "Index out of range"}

    card = cards[idx]
    if field == "fn":
        card.fn = value
    elif field == "org":
        card.org = value
    elif field == "title":
        card.title = value
    elif field == "categories":
        card.categories = [v.strip() for v in value.split(",") if v.strip()]
    elif field == "delete":
        _state["cards"].pop(idx)
        return {"ok": True, "deleted": True}
    else:
        return {"ok": False, "error": f"Unknown field: {field}"}

    card.log_change(f"Edited {field} via web UI")
    return {"ok": True}


def _api_search_cards(params: dict) -> dict:
    """Quick search for spouse/related picker — returns name+uid of matching contacts."""
    q = params.get("q", [""])[0].lower().strip()
    if len(q) < 2:
        return {"results": []}
    cards = _state["cards"]
    results = []
    for i, c in enumerate(cards):
        fn = (c.fn or "").lower()
        org = (c.org or "").lower()
        if q in fn or q in org:
            results.append({
                "_idx": i,
                "fn": c.fn or "",
                "org": c.org or "",
                "uid": c.uid or "",
                "emails": c.emails[:1],
                "tels": c.tels[:1],
                "address": _card_to_dict(c)["addresses"][0] if c.addresses else {},
            })
        if len(results) >= 12:
            break
    return {"results": results}


def _api_add_card(body: dict) -> dict:
    """Add a brand new contact to the in-memory list."""
    import uuid as _uuid
    from .model import Card, Address, NameComponents, Related

    try:
        fn = body.get("fn","").strip()
        if not fn:
            return {"ok": False, "error": "Name is required"}

        # Build structured name
        name = NameComponents(
            prefix=body.get("name_prefix","").strip(),
            given=body.get("name_given","").strip(),
            additional=body.get("name_additional","").strip(),
            family=body.get("name_family","").strip(),
            suffix=body.get("name_suffix","").strip(),
        )

        # Normalise phones
        import re as _re
        raw_tels = [t for t in _re.split(r"[\n,]+", body.get("tel",""))]
        normalised_tels = []
        for raw in raw_tels:
            raw = raw.strip()
            if not raw: continue
            try:
                import phonenumbers
                p = _get_pipeline()
                _, settings = p["ensure_workspace"](_ROOT)
                parsed = phonenumbers.parse(raw, settings.default_region)
                if phonenumbers.is_valid_number(parsed):
                    normalised_tels.append(phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.INTERNATIONAL))
                else:
                    normalised_tels.append(raw)
            except Exception:
                normalised_tels.append(raw)

        emails = [e.strip().lower() for e in _re.split(r"[\n,]+", body.get("email","")) if e.strip()]

        adr = None
        if any(body.get(k,"").strip() for k in ("street","city","region","postal","country")):
            adr = Address(
                street=body.get("street","").strip() or None,
                locality=body.get("city","").strip() or None,
                region=body.get("region","").strip() or None,
                postal_code=body.get("postal","").strip() or None,
                country=body.get("country","").strip() or None,
            )

        # Related people
        related = []
        for r in body.get("related", []):
            rt = r.get("rel_type","spouse")
            related.append(Related(rel_type=rt, uid=r.get("uid") or None, text=r.get("text") or None))

        cats = [c.strip() for c in body.get("categories","").split(",") if c.strip()]

        card = Card(
            raw=None, fn=fn, name=name,
            org=body.get("org","").strip() or None,
            title=body.get("title","").strip() or None,
            bday=body.get("bday","").strip() or None,
            anniversary=body.get("anniversary","").strip() or None,
            note=body.get("note","").strip() or None,
            emails=emails, tels=normalised_tels,
            categories=cats,
            addresses=[adr] if adr else [],
            kind=body.get("kind","individual"),
            gender=body.get("gender","").strip().upper() or None,
            related=related,
            uid=str(_uuid.uuid4()),
        )
        card.log_change("Added via web UI")
        card._source_files = ["manual"]

        _state["cards"].append(card)
        _autosave_checkpoint()
        return {"ok": True, "total": len(_state["cards"]), "normalised_tels": normalised_tels}

    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _api_full_update_card(body: dict) -> dict:
    """Replace all fields on a card (used by the edit modal)."""
    from .model import Address, NameComponents, Related
    import re

    cards = _state["cards"]
    idx = body.get("index")
    if idx is None or idx < 0 or idx >= len(cards):
        return {"ok": False, "error": "Invalid index"}

    card = cards[idx]

    fn = body.get("fn","").strip()
    if not fn:
        return {"ok": False, "error": "Name is required"}

    card.fn    = fn
    card.org   = body.get("org","").strip() or None
    card.title = body.get("title","").strip() or None
    card.bday  = body.get("bday","").strip() or None
    card.anniversary = body.get("anniversary","").strip() or None
    card.note  = body.get("note","").strip() or None
    card.kind  = body.get("kind","individual")
    card.gender = body.get("gender","").strip().upper() or None

    # Structured name
    card.name = NameComponents(
        prefix=body.get("name_prefix","").strip(),
        given=body.get("name_given","").strip(),
        additional=body.get("name_additional","").strip(),
        family=body.get("name_family","").strip(),
        suffix=body.get("name_suffix","").strip(),
    )

    # Emails — support typed format [{value, type}] or plain list/string
    from .model import TypedValue
    raw_emails_typed = body.get("typed_emails", [])  # [{value, type}]
    if raw_emails_typed:
        typed_emails = []
        for item in raw_emails_typed:
            if isinstance(item, dict):
                val = item.get("value", "").strip().lower()
                if val:
                    typed_emails.append(TypedValue(value=val, type=item.get("type","").upper()))
        card.emails = [tv.value for tv in typed_emails]
        card.typed_emails = typed_emails
    else:
        raw_emails = re.split(r"[,\n]+", body.get("emails",""))
        card.emails = [e.strip().lower() for e in raw_emails if e.strip()]
        card.typed_emails = [TypedValue(value=e, type="") for e in card.emails]

    # Phones — support typed format [{value, type}] or plain list/string
    raw_tels_typed = body.get("typed_tels", [])  # [{value, type}]
    normalised = []  # always defined; populated by whichever branch runs
    if raw_tels_typed:
        typed_tels = []
        for item in raw_tels_typed:
            if isinstance(item, dict):
                raw = item.get("value", "").strip()
                if not raw:
                    continue
                ttype = item.get("type","").upper()
                try:
                    import phonenumbers
                    p2 = _get_pipeline()
                    _, settings = p2["ensure_workspace"](_ROOT)
                    parsed = phonenumbers.parse(raw, settings.default_region)
                    if phonenumbers.is_valid_number(parsed):
                        raw = phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.INTERNATIONAL)
                except Exception:
                    pass
                typed_tels.append(TypedValue(value=raw, type=ttype))
        card.tels = [tv.value for tv in typed_tels]
        card.typed_tels = typed_tels
        normalised = card.tels  # return the formatted values
    else:
        raw_tels = re.split(r"[,\n]+", body.get("tels",""))
        normalised = []
        for raw in raw_tels:
            raw = raw.strip()
            if not raw:
                continue
            try:
                import phonenumbers
                p3 = _get_pipeline()
                _, settings = p3["ensure_workspace"](_ROOT)
                parsed = phonenumbers.parse(raw, settings.default_region)
                if phonenumbers.is_valid_number(parsed):
                    normalised.append(phonenumbers.format_number(
                        parsed, phonenumbers.PhoneNumberFormat.INTERNATIONAL))
                else:
                    normalised.append(raw)
            except Exception:
                normalised.append(raw)
        card.tels = normalised
        card.typed_tels = [TypedValue(value=t, type="") for t in normalised]
    card.categories = [c.strip() for c in body.get("categories","").split(",") if c.strip()]

    # Address
    if any(body.get(k,"").strip() for k in ("street","city","region","postal","country")):
        adr = Address(
            street=body.get("street","").strip() or None,
            locality=body.get("city","").strip() or None,
            region=body.get("region","").strip() or None,
            postal_code=body.get("postal","").strip() or None,
            country=body.get("country","").strip() or None,
        )
        card.addresses = [adr]

    # Related people — server state is authoritative; only link_related() mutates this.
    # The edit modal sends _editRelated as a convenience display, but we never let it
    # RELATED merge strategy:
    #   UID-linked entries: server is authoritative — never remove via saveEdit.
    #     Use /api/unlink_related which handles both directions.
    #     New UID entries from the modal are added if not already present.
    #   Text-only entries: modal is authoritative — user deleted "Laura" so honour it.
    incoming_related = []
    for r in body.get("related", []):
        rt = r.get("rel_type", "spouse")
        incoming_related.append(Related(rel_type=rt, uid=r.get("uid") or None, text=r.get("text") or None))

    # Keep all existing UID-linked entries from the server
    server_uid_rels = [r for r in (card.related or []) if r.uid]
    server_uids = {r.uid for r in server_uid_rels}

    # Add any new UID-linked entries from the modal
    for r in incoming_related:
        if r.uid and r.uid not in server_uids:
            server_uid_rels.append(r)
            server_uids.add(r.uid)

    # Text-only entries: use exactly what the modal sent (deletions are honoured)
    incoming_text_rels = [r for r in incoming_related if not r.uid]

    card.related = server_uid_rels + incoming_text_rels

    # MEMBER — list of UID strings (org/group cards)
    card.member = [m.strip() for m in body.get("member", []) if m and m.strip()]

    # Stamp REV with current UTC time on every save
    from datetime import UTC as _UTC, datetime as _dt
    card.rev = _dt.now(_UTC).strftime("%Y%m%dT%H%M%SZ")

    card.log_change("Edited via web UI")
    _autosave_checkpoint()
    return {"ok": True, "normalised_tels": normalised}




def _api_bulk_add_category(body: dict) -> dict:
    """Add a category to multiple cards by their global _idx values."""
    cards = _state["cards"]
    if not cards:
        return {"ok": False, "error": "No contacts loaded"}
    cat = (body.get("category") or "").strip()
    if not cat:
        return {"ok": False, "error": "Category name is required"}
    indices = body.get("indices", [])
    if not indices:
        return {"ok": False, "error": "No contacts selected"}
    changed = 0
    for idx in indices:
        if 0 <= idx < len(cards):
            c = cards[idx]
            if cat not in c.categories:
                c.categories = sorted(set(c.categories) | {cat})
                changed += 1
    if changed:
        _autosave_checkpoint()
    return {"ok": True, "changed": changed, "category": cat}


def _api_waive_field(body: dict) -> dict:
    """Mark a field as 'not required' for a card — removes it from quality scan.

    body: {index, field}  field is one of: email phone address category org
    """
    cards = _state["cards"]
    try:
        idx = int(body["index"])
        field = str(body.get("field", "")).strip().lower()
        valid = {"email", "phone", "address", "category", "org"}
        if field not in valid:
            return {"ok": False, "error": f"Unknown field '{field}'"}
        if idx < 0 or idx >= len(cards):
            return {"ok": False, "error": "Invalid index"}
        card = cards[idx]
        if not hasattr(card, "_waived") or card._waived is None:
            card._waived = set()
        card._waived.add(field)
        card.log_change(f"Marked '{field}' as not required")
        _autosave_checkpoint()
        return {"ok": True, "waived": list(card._waived)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _api_unwaive_field(body: dict) -> dict:
    """Remove a 'not required' marker from a field."""
    cards = _state["cards"]
    try:
        idx = int(body["index"])
        field = str(body.get("field", "")).strip().lower()
        if idx < 0 or idx >= len(cards):
            return {"ok": False, "error": "Invalid index"}
        card = cards[idx]
        if hasattr(card, "_waived") and card._waived:
            card._waived.discard(field)
        _autosave_checkpoint()
        return {"ok": True, "waived": list(getattr(card, "_waived", set()) or set())}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _api_strip_proprietary(body: dict) -> dict:
    """Strip all proprietary/vendor X- fields from all cards and optionally reset waived markers.

    body: {reset_waived: bool}
    Removes: all X-* properties, PRODID, and optionally _waived.
    """
    cards = _state["cards"]
    try:
        reset_waived = bool(body.get("reset_waived", False))
        stripped_cards = 0
        stripped_fields = 0

        # Proprietary X- field names to always strip (added by various vendors)
        _VENDOR_X = re.compile(
            r"^X-(?!VCARD-STUDIO)",  # keep our own X-VCARD-STUDIO-* fields
            re.I,
        )

        for card in cards:
            changed = False
            # Strip vendor X- properties from the raw vobject
            if card.raw is not None:
                try:
                    to_remove = [
                        child for child in list(card.raw.getChildren())
                        if _VENDOR_X.match(getattr(child, "name", "") or "")
                        or getattr(child, "name", "").upper() == "PRODID"
                    ]
                    for child in to_remove:
                        card.raw.remove(child)
                        stripped_fields += 1
                        changed = True
                except Exception:
                    pass
            if reset_waived:
                if hasattr(card, "_waived") and card._waived:
                    card._waived = set()
                    changed = True
            if changed:
                stripped_cards += 1
                card.log_change("Proprietary fields stripped" + (" + waived reset" if reset_waived else ""))

        if stripped_cards:
            _autosave_checkpoint()
        return {
            "ok": True,
            "stripped_cards": stripped_cards,
            "stripped_fields": stripped_fields,
            "waived_reset": reset_waived,
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


        return {"ok": False, "error": str(exc)}


def _api_print_cards(params: dict) -> dict:
    """Generate a structured printable HTML address book.

    Structure:
      Page 1  — Cover: owner name, date, contact count
      Page 2  — Birthdays & anniversaries (all months)
      Page 3+ — Contacts A–Z, two-column, with letter dividers
    """
    cards = _state["cards"]
    if not cards:
        return {"ok": False, "error": "No contacts loaded"}
    try:
        category   = params.get("category",  [""])[0]
        paper      = params.get("paper",     ["A5"])[0]
        incl_email = params.get("email",     ["1"])[0] == "1"
        incl_phone = params.get("phone",     ["1"])[0] == "1"
        incl_addr  = params.get("address",   ["1"])[0] == "1"
        incl_org   = params.get("org",       ["1"])[0] == "1"
        incl_note  = params.get("note",      ["0"])[0] == "1"
        incl_rels  = params.get("rels",      ["1"])[0] == "1"
        incl_cats  = params.get("cats",      ["1"])[0] == "1"

        # Self card → owner name
        owner_name = ""
        for c in cards:
            if c.kind == "self":
                owner_name = c.fn or ""
                break

        # Contact pool
        pool = [c for c in cards if category in (c.categories or [])] if category else list(cards)
        pool = [c for c in pool if c.kind != "self"]
        pool.sort(key=lambda c: (
            (c.name.family or c.fn or "").lower(),
            (c.name.given  or "").lower()
        ))

        from datetime import datetime, date as _date
        generated   = datetime.now().strftime("%d %B %Y")
        cat_label   = category or "All Contacts"
        paper_dims  = {"A5": "148mm 210mm", "A4": "210mm 297mm",
                       "Letter": "8.5in 11in"}.get(paper, "148mm 210mm")

        # ── Page 1: Cover ────────────────────────────────────────────────────
        cover_owner = f"<div class='cov-owner'>{_esc_html(owner_name)}</div>" if owner_name else ""
        cover = f"""<div class='cover'>
  <div class='cov-logo'>vCard Studio</div>
  <div class='cov-title'>{_esc_html(cat_label)}</div>
  {cover_owner}
  <div class='cov-meta'>{len(pool)} contact{'s' if len(pool)!=1 else ''}</div>
  <div class='cov-meta'>Generated {generated}</div>
  <div class='cov-foot'>local · no cloud · GNU GPL v3</div>
</div>"""

        # ── Page 2: Birthdays & anniversaries ────────────────────────────────
        MONTH_NAMES = ["January","February","March","April","May","June",
                       "July","August","September","October","November","December"]

        def _parse_bday(s):
            if not s: return None, None
            s = s.strip()
            for fmt in ("%Y-%m-%d", "%Y%m%d", "--%m%d", "%m-%d"):
                try:
                    d = datetime.strptime(s, fmt)
                    return d.month, d.day
                except ValueError:
                    pass
            return None, None

        _COUPLE_TYPES_PRINT = frozenset({
            "spouse", "partner", "husband", "wife",
            "co-habitant", "cohabitant", "domestic partner",
        })
        pool_uid_map = {c.uid: c for c in pool if c.uid}

        def _couple_anniv_name(c1, c2):
            def _gv(c): return (c.name.given or "").strip() if c.name else ""
            def _fm(c): return (c.name.family or "").strip() if c.name else ((c.fn or "").split()[-1] if c.fn and len((c.fn or "").split())>1 else "")
            fam = _fm(c1) or _fm(c2)
            names = sorted([n for n in [_gv(c1), _gv(c2)] if n])
            return f"{' & '.join(names)} {fam}".strip()

        bday_by_month: dict[int, list] = {}
        seen_anniv_print: set = set()

        for c in sorted(pool, key=lambda c: c.fn or ""):
            name = c.fn or c.org or "Unknown"
            if c.bday:
                m, d = _parse_bday(c.bday)
                if m:
                    bday_by_month.setdefault(m, []).append((d or 0, name, "birthday"))
            if c.anniversary:
                m, d = _parse_bday(c.anniversary)
                if m:
                    # Check for spouse with matching anniversary
                    partner = None
                    for rel in (c.related or []):
                        if (rel.rel_type or "").lower() not in _COUPLE_TYPES_PRINT: continue
                        if not rel.uid: continue
                        pc = pool_uid_map.get(rel.uid)
                        if not pc or not pc.anniversary: continue
                        pm, pd = _parse_bday(pc.anniversary)
                        if pm == m and pd == d:
                            partner = pc
                            break
                    if partner:
                        pair = frozenset([id(c), id(partner)])
                        if pair not in seen_anniv_print:
                            seen_anniv_print.add(pair)
                            bday_by_month.setdefault(m, []).append(
                                (d or 0, _couple_anniv_name(c, partner), "anniversary"))
                    else:
                        bday_by_month.setdefault(m, []).append((d or 0, name, "anniversary"))

        bday_rows = ""
        this_year = datetime.now().year
        for m in range(1, 13):
            entries = sorted(bday_by_month.get(m, []))
            if not entries:
                continue
            bday_rows += f"<div class='bd-month'>{MONTH_NAMES[m-1]}</div>"
            for (day, name, etype) in entries:
                day_str = f"{day:02d}" if day else "—"
                badge = "<span class='bd-anniv'>anniv</span>" if etype == "anniversary" \
                        else "<span class='bd-bday'>bday</span>"
                bday_rows += f"<div class='bd-row'><span class='bd-day'>{day_str}</span>" \
                             f"<span class='bd-name'>{_esc_html(name)}</span>{badge}</div>"

        if not bday_rows:
            bday_rows = "<div style='color:#888;font-size:8pt'>No birthdays or anniversaries recorded.</div>"

        bday_page = f"""<div class='page-break'></div>
<div class='section-title'>Birthdays &amp; Anniversaries</div>
<div class='bd-grid'>{bday_rows}</div>"""

        # ── Page 3+: Contacts A–Z ─────────────────────────────────────────────
        # Build UID→display name map for resolving linked relationships
        uid_to_name: dict[str, str] = {}
        for c in cards:
            if c.uid:
                uid_to_name[c.uid] = c.fn or c.org or ""

        def _fmt_card(c) -> str:
            name = c.fn or c.org or "Unknown"
            if c.name and c.name.prefix and not name.startswith(c.name.prefix):
                name = f"{c.name.prefix} {name}"
            rows = [f"<div class='cn'>{_esc_html(name)}</div>"]
            if incl_org and c.org and c.kind != "org":
                org_line = _esc_html(c.org)
                if c.title: org_line += f" · {_esc_html(c.title)}"
                rows.append(f"<div class='cd org'>{org_line}</div>")
            if incl_rels and c.related:
                for r in c.related:
                    # Resolve UID to name, fall back to stored text
                    if r.uid:
                        rname = uid_to_name.get(r.uid, r.text or r.uid)
                    else:
                        rname = r.text or ""
                    if not rname:
                        continue
                    rtype = (r.rel_type or "").capitalize()
                    rows.append(f"<div class='cd rel'>"
                                f"<span class='rel-type'>{_esc_html(rtype)}</span> "
                                f"{_esc_html(rname)}</div>")
            if incl_addr and c.addresses:
                a = c.addresses[0]
                parts = [p for p in [a.street, a.extended, a.locality,
                                      a.region, a.postal_code, a.country] if p]
                if parts:
                    rows.append("<div class='cd adr'>" +
                                ", ".join(_esc_html(p) for p in parts) + "</div>")
            if incl_phone:
                for t in c.tels[:2]:
                    rows.append(f"<div class='cd ph'>{_esc_html(_fmt_tel(t))}</div>")
            if incl_email:
                for e in c.emails[:2]:
                    rows.append(f"<div class='cd em'>{_esc_html(e)}</div>")
            if incl_cats and c.categories:
                pills = "".join(f"<span class='cpill'>{_esc_html(x)}</span>"
                                for x in sorted(c.categories))
                rows.append(f"<div class='cd ct'>{pills}</div>")
            if incl_note and c.note:
                # Strip vCS metadata block from visible note
                import re as _re
                note = _re.sub(r'\s*\[vCS:[^\]]*\]', '', c.note).strip()
                if note:
                    rows.append(f"<div class='cd nt'>{_esc_html(note)}</div>")
            return "<div class='card'>" + "".join(rows) + "</div>"

        contacts_html = "<div class='page-break'></div><div class='contact-grid'>"
        cur_letter = ""
        for c in pool:
            first = (c.name.family or c.fn or c.org or "?")[0].upper()
            if first != cur_letter:
                cur_letter = first
                contacts_html += f"<div class='letter-div'>{_esc_html(first)}</div>"
            contacts_html += _fmt_card(c)
        contacts_html += "</div>"

        # ── CSS ───────────────────────────────────────────────────────────────
        css = f"""
@page {{ size: {paper_dims}; margin: 12mm 14mm; }}
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ font-family: Arial, Helvetica, sans-serif; font-size: 8pt; color: #111; background: white; }}

/* Cover */
.cover {{ height: 100vh; display: flex; flex-direction: column; justify-content: center;
          align-items: center; text-align: center; page-break-after: always; gap: 8mm; }}
.cov-logo {{ font-size: 10pt; color: #888; letter-spacing: .15em; text-transform: uppercase; }}
.cov-title {{ font-size: 22pt; font-weight: bold; color: #111; }}
.cov-owner {{ font-size: 13pt; color: #333; }}
.cov-meta  {{ font-size: 9pt; color: #666; }}
.cov-foot  {{ font-size: 7pt; color: #bbb; margin-top: 12mm; }}

/* Page breaks */
.page-break {{ page-break-before: always; }}

/* Section title */
.section-title {{ font-size: 12pt; font-weight: bold; color: #111;
                  border-bottom: 1pt solid #ccc; padding-bottom: 2mm; margin-bottom: 4mm; }}

/* Birthdays */
.bd-grid {{ columns: 2; column-gap: 8mm; }}
.bd-month {{ font-weight: bold; font-size: 8.5pt; color: #333; margin: 3mm 0 1mm;
             break-inside: avoid; border-bottom: 0.5pt solid #eee; padding-bottom: 1pt; }}
.bd-row {{ display: flex; align-items: baseline; gap: 3mm; padding: 1.5pt 0;
           border-bottom: 0.3pt solid #f0f0f0; break-inside: avoid; }}
.bd-day  {{ font-size: 8pt; color: #888; min-width: 10mm; text-align: right; flex-shrink: 0; }}
.bd-name {{ flex: 1; font-size: 8pt; }}
.bd-bday   {{ font-size: 6.5pt; color: #1a7abf; background: #e8f3fb;
              padding: 0 3pt; border-radius: 2pt; flex-shrink: 0; }}
.bd-anniv  {{ font-size: 6.5pt; color: #7a3fbf; background: #f3ebfb;
              padding: 0 3pt; border-radius: 2pt; flex-shrink: 0; }}

/* Contact grid */
.contact-grid {{ columns: 2; column-gap: 8mm; }}
.letter-div {{ font-size: 14pt; font-weight: bold; color: #ccc;
               border-bottom: 1pt solid #eee; margin: 4mm 0 2mm;
               break-inside: avoid; break-after: avoid; column-span: all; }}
.card {{ break-inside: avoid; padding: 2.5pt 0 3.5pt; border-bottom: 0.4pt solid #e8e8e8; }}
.cn  {{ font-size: 8.5pt; font-weight: bold; color: #000; margin-bottom: 1pt; }}
.cd  {{ color: #333; margin-top: 1pt; font-size: 7.5pt; }}
.org {{ color: #555; font-style: italic; }}
.rel {{ color: #333; }}
.rel-type {{ font-size: 6.5pt; color: #7a3fbf; background: #f3ebfb;
             padding: 0 3pt; border-radius: 2pt; margin-right: 2pt;
             text-transform: lowercase; font-variant: small-caps; }}
.ph  {{ color: #1a6ea8; }}
.em  {{ color: #1a6ea8; }}
.ct  {{ margin-top: 1.5pt; }}
.cpill {{ font-size: 6.5pt; color: #555; background: #f0f0f0;
          padding: 0 3pt; border-radius: 2pt; margin-right: 2pt; }}
.nt  {{ color: #777; font-size: 7pt; font-style: italic; }}

/* Screen preview */
@media screen {{
  body {{ background: #ddd; padding: 20px; }}
  .cover, .contact-grid, .bd-grid {{ background: white; padding: 20px 24px;
    margin-bottom: 12px; box-shadow: 0 1px 6px rgba(0,0,0,.2); max-width: 600px; }}
  .cover {{ min-height: 400px; }}
  .section-title {{ margin-top: 8px; }}
  .page-break {{ height: 0; }}
  .contact-grid {{ columns: 2; }}
}}
@media print {{
  body {{ background: white; }}
}}"""

        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>{_esc_html(cat_label)} — Address Book</title>
<style>{css}</style>
</head>
<body>
{cover}
{bday_page}
{contacts_html}
</body>
</html>"""

        out_dir = _ROOT / "print"
        out_dir.mkdir(exist_ok=True)
        ts = datetime.now().strftime("%Y-%m-%d-%H%M")
        safe_cat = re.sub(r"[^\w-]", "-", category or "all").strip("-")
        out_path = out_dir / f"addressbook-{safe_cat}-{ts}.html"
        out_path.write_text(html, encoding="utf-8")
        return {"ok": True, "filename": out_path.name, "count": len(pool)}

    except Exception as exc:
        import traceback
        print(f"[print_cards error] {traceback.format_exc()}", flush=True)
        return {"ok": False, "error": str(exc)}


def _api_label_options(body: dict) -> dict:
    """For a list of card indices, return the formatted single and couple label options.

    Used by the print label modal so the user can choose per-contact.
    """
    cards = _state["cards"]
    if not cards:
        return {"ok": False, "error": "No contacts loaded"}

    indices  = body.get("indices", [])
    style    = body.get("style", "british_formal")
    include_country = bool(body.get("include_country", True))

    # Build a minimal label record pass — reuse _build_label_records internals
    # by calling it with indices and extracting the merged/unmerged names
    uid_map: dict[str, object] = {c.uid: c for c in cards if c.uid}

    _COUPLE_TYPES = frozenset({
        "spouse", "partner", "husband", "wife",
        "co-habitant", "cohabitant", "domestic partner",
    })

    def _prefix(c):
        if c.name and c.name.prefix: return c.name.prefix.strip()
        return ""

    def _given(c):
        if c.name and c.name.given: return c.name.given.strip()
        return (c.fn or "").split()[0] if c.fn else ""

    def _family(c):
        if c.name and c.name.family: return c.name.family.strip()
        parts = (c.fn or "").split()
        return parts[-1] if len(parts) > 1 else ""

    def _initial(c):
        g = _given(c)
        return g[0].upper() if g else ""

    def _addr_key(c):
        if not c.addresses: return None
        a = c.addresses[0]
        s = (a.street or "").strip().lower()
        p = (a.postal_code or "").strip().lower()
        return (s, p) if s or p else None

    def _fmt_single(c):
        p = _prefix(c)
        if c.kind == "org" or not c.name or (not _family(c) and not c.name.given):
            return c.fn or c.org or "Unknown"
        fn = c.fn or ""
        return f"{p} {fn}".strip() if p and not fn.startswith(p) else fn

    def _fmt_couple_names(c1, c2):
        """Simplified couple formatter using the user's style preference."""
        fam = _family(c1) or _family(c2)
        _MALE = {"mr", "master", "sir", "lord"}
        _FEMALE = {"mrs", "ms", "miss", "lady", "dame"}

        def _is_male(c):
            if c.gender == "M": return True
            if c.gender == "F": return False
            return _prefix(c).lower() in _MALE

        def _is_female(c):
            if c.gender == "F": return True
            if c.gender == "M": return False
            return _prefix(c).lower() in _FEMALE

        both_male = _is_male(c1) and _is_male(c2)
        both_female = _is_female(c1) and _is_female(c2)

        if both_male or both_female:
            a, b = (c1, c2) if (_given(c1) or "") <= (_given(c2) or "") else (c2, c1)
            p_a, p_b = _prefix(a), _prefix(b)
            if style == "informal": return f"{_given(a)} & {_given(b)} {fam}".strip()
            if style == "family": return f"The {fam} Family".strip()
            if style == "formal_no_initial":
                return f"{p_a or _initial(a)} & {p_b or _initial(b)} {fam}".strip()
            if p_a and p_b:
                return f"{p_a} {_initial(a)} & {p_b} {_initial(b)} {fam}".strip()
            return f"{_initial(a)} & {_initial(b)} {fam}".strip()

        male = c1 if _is_male(c1) else (c2 if _is_male(c2) else c1)
        female = c2 if male is c1 else c1
        p_m, p_f = _prefix(male), _prefix(female)

        if style == "informal": return f"{_given(male)} & {_given(female)} {fam}".strip()
        if style == "family": return f"The {fam} Family".strip()
        if style == "formal_no_initial":
            if p_m and p_f: return f"{p_m} & {p_f} {fam}".strip()
            return f"{p_m or p_f} {fam}".strip()
        if style == "formal_both":
            if p_m and p_f: return f"{p_m} {_initial(male)} & {p_f} {_initial(female)} {fam}".strip()
            return f"{_initial(male)} & {_initial(female)} {fam}".strip()
        # british_formal default
        if p_m and p_f: return f"{p_m} & {p_f} {_initial(male)} {fam}".strip()
        if p_m: return f"{p_m} {_initial(male)} {fam}".strip()
        return f"{_initial(male)} & {_initial(female)} {fam}".strip()

    results = []
    for idx in indices:
        if not (0 <= idx < len(cards)):
            continue
        card = cards[idx]
        single_name = _fmt_single(card)
        couple_name = None
        couple_idx  = None

        # Check for a spouse/partner — UID-linked first, text-only as fallback
        card_addr = _addr_key(card)
        sorted_rels = sorted(card.related or [],
                             key=lambda r: 0 if (r.rel_type or "").lower() in _COUPLE_TYPES else 1)
        for rel in sorted_rels:
            if (rel.rel_type or "").lower() not in _COUPLE_TYPES: continue
            if rel.uid:
                # UID-linked partner — must share address
                if not card_addr: continue
                partner = uid_map.get(rel.uid)
                if not partner: continue
                if not (partner.addresses and partner.addresses[0].street): continue
                if _addr_key(partner) == card_addr:
                    couple_name = _fmt_couple_names(card, partner)
                    couple_idx  = next((i for i, c in enumerate(cards) if c is partner), None)
                    break
            elif rel.text and rel.text.strip():
                # Text-only spouse — address check not possible, always offer
                sp_text = rel.text.strip()
                # Reuse the same inference logic as _build_label_records
                _KNOWN_PREFIXES = ("mr", "mrs", "ms", "miss", "dr", "prof", "rev",
                                   "capt", "maj", "col", "lt", "sgt", "cpl")
                _MALE_PREFIXES   = {"mr", "master", "sir", "lord"}
                _FEMALE_PREFIXES = {"mrs", "ms", "miss", "lady", "dame"}
                parts = sp_text.split()
                sp_prefix = ""
                if parts and parts[0].rstrip(".").lower() in _KNOWN_PREFIXES:
                    sp_prefix = parts[0]
                p_card = _prefix(card)
                card_is_male = p_card.lower() in _MALE_PREFIXES or card.gender == "M"
                card_is_female = p_card.lower() in _FEMALE_PREFIXES or card.gender == "F"
                sp_is_male = sp_prefix.lower() in _MALE_PREFIXES if sp_prefix else None
                sp_is_female = sp_prefix.lower() in _FEMALE_PREFIXES if sp_prefix else None
                same_sex = (card_is_male and sp_is_male) or (card_is_female and sp_is_female)
                # Infer prefix if none stored
                if not sp_prefix and not same_sex:
                    if card_is_male:   sp_prefix = "Mrs"
                    elif card_is_female: sp_prefix = "Mr"
                # Build a minimal couple name
                fam = _family(card)
                sp_given = parts[1] if sp_prefix and len(parts) > 1 else (parts[0] if parts else "")
                sp_initial = sp_given[0].upper() if sp_given else ""
                card_initial = _initial(card)
                p_c = _prefix(card)
                if style == "informal":
                    couple_name = f"{_given(card)} & {sp_given} {fam}".strip()
                elif style == "family":
                    couple_name = f"The {fam} Family".strip()
                elif style == "formal_no_initial":
                    couple_name = f"{p_c} & {sp_prefix} {fam}".strip() if p_c and sp_prefix else f"{p_c or sp_prefix} {fam}".strip()
                elif style == "formal_both":
                    couple_name = f"{p_c} {card_initial} & {sp_prefix} {sp_initial} {fam}".strip() if p_c and sp_prefix else f"{_fmt_single(card)} & {sp_text}".strip()
                else:  # british_formal
                    couple_name = f"{p_c} & {sp_prefix} {card_initial} {fam}".strip() if p_c and sp_prefix else f"{_fmt_single(card)} & {sp_text}".strip()
                couple_idx = None  # no card to reference
                break

        results.append({
            "_idx":        idx,
            "fn":          card.fn or card.org or "Unknown",
            "single_name": single_name,
            "couple_name": couple_name,   # None if no eligible partner
            "couple_idx":  couple_idx,
        })

    return {"ok": True, "options": results}


def _api_print_modules() -> dict:
    """Return all discovered print modules and their label profiles."""
    from .print_modules import get_all_modules
    try:
        modules = get_all_modules()
        print(f"[print_modules] {len(modules)} module(s): {[m['printer_id'] for m in modules]}", flush=True)
        return {"ok": True, "modules": modules}
    except Exception as exc:
        import traceback
        print(f"[print_modules error] {traceback.format_exc()}", flush=True)
        return {"ok": False, "modules": [], "error": str(exc)}


def _build_label_records(cards, category: str, style: str, include_country: bool,
                         indices: list | None = None) -> list:
    """Shared helper: build sorted label records with couple merging.

    Returns list of {"name": str, "address": [str], "merged": bool}.
    If indices is provided, use those specific card indices instead of category filter.
    """
    uid_map: dict[str, object] = {c.uid: c for c in cards if c.uid}

    # Filter pool — specific indices override category
    if indices is not None:
        pool = [cards[i] for i in indices if 0 <= i < len(cards)]
    elif category:
        pool = [c for c in cards if category in (c.categories or [])]
    else:
        pool = list(cards)
    pool = [c for c in pool if c.addresses and c.addresses[0].street]

    def _addr_key(card):
        if not card.addresses: return None
        a = card.addresses[0]
        s = (a.street or "").strip().lower()
        p = (a.postal_code or "").strip().lower()
        return (s, p) if s or p else None

    def _initial(card):
        return card.name.given[0].upper() if card.name and card.name.given else ""

    def _prefix(card):
        if card.name and card.name.prefix: return card.name.prefix.strip()
        if card.gender == "M": return "Mr"
        if card.gender == "F": return "Mrs"
        return ""

    def _given(card):
        return (card.name.given.strip() if card.name and card.name.given else card.fn or "")

    def _family(card):
        return (card.name.family.strip() if card.name and card.name.family else "")

    def _format_couple_from_text(card, spouse_name: str) -> str:
        """Format a couple name when we have one full card and a text-only spouse name.

        Opposite-gender inference (covers ~95% of cases):
          Mr Smith + "Laura"  → infers Mrs → Mr & Mrs B Smith
          Mrs Smith + "James" → infers Mr  → Mr & Mrs J Brown

        Same-sex detection: if the stored text includes an explicit prefix that matches
        the card holder's gender (e.g. card is Mr, text is "Mr Tom"), the inference is
        skipped and both initials are shown: Mr J & Mr T Smith.

        Override inference by storing a prefix via the edit modal prefix dropdown.
        """
        fam = _family(card)

        _KNOWN_PREFIXES = ("mr", "mrs", "ms", "miss", "dr", "prof", "rev",
                           "capt", "maj", "col", "lt", "sgt", "cpl")
        _MALE_PREFIXES   = {"mr", "master", "sir", "lord"}
        _FEMALE_PREFIXES = {"mrs", "ms", "miss", "lady", "dame"}

        parts = spouse_name.strip().split()
        sp_prefix, sp_given, sp_initial = "", "", ""
        if parts:
            first = parts[0].rstrip(".").lower()
            if first in _KNOWN_PREFIXES:
                sp_prefix = parts[0]
                sp_given  = parts[1] if len(parts) > 1 else ""
            else:
                sp_given = parts[0]
            sp_initial = sp_given[0].upper() if sp_given else ""

        def _is_male(c):
            if c.gender == "M": return True
            if c.gender == "F": return False
            return _prefix(c).lower() in _MALE_PREFIXES

        card_is_male   = _is_male(card)
        card_is_female = not card_is_male and _prefix(card).lower() in _FEMALE_PREFIXES
        p_card       = _prefix(card)
        card_initial = _initial(card)

        # Detect same-sex from explicit prefix on the stored text
        sp_is_male   = sp_prefix.lower() in _MALE_PREFIXES   if sp_prefix else None
        sp_is_female = sp_prefix.lower() in _FEMALE_PREFIXES if sp_prefix else None
        same_sex = (card_is_male and sp_is_male) or (card_is_female and sp_is_female)

        # Infer opposite-gender prefix only for mixed-sex couples with no stored prefix
        if not sp_prefix and not same_sex and style not in ("informal", "family"):
            if card_is_male:
                sp_prefix  = "Mrs"
                sp_is_male = False
            elif card_is_female:
                sp_prefix  = "Mr"
                sp_is_male = True

        if style == "informal":
            card_first = _given(card)
            sp_name    = sp_given or spouse_name
            return f"{card_first} & {sp_name} {fam}".strip() if fam else                    f"{card_first} & {sp_name}".strip()

        if style == "family":
            return f"The {fam} Family".strip() if fam else spouse_name

        if same_sex:
            # Both initials shown — alphabetical by initial within the couple
            a_init, b_init = sorted([card_initial, sp_initial])
            a_pref = p_card  # both should be same prefix
            if style == "formal_no_initial":
                return f"{p_card} & {sp_prefix or p_card} {fam}".strip()
            # formal_both and british_formal both show initials for same-sex
            if p_card and sp_prefix:
                # Order by initial alphabetically
                if card_initial <= sp_initial:
                    return f"{p_card} {card_initial} & {sp_prefix} {sp_initial} {fam}".strip()
                else:
                    return f"{sp_prefix} {sp_initial} & {p_card} {card_initial} {fam}".strip()
            return f"{_format_single(card)} & {spouse_name}".strip()

        if style == "formal_no_initial":
            if p_card and sp_prefix:
                pair = (f"{p_card} & {sp_prefix}") if card_is_male else (f"{sp_prefix} & {p_card}")
                return f"{pair} {fam}".strip()
            return f"{p_card or sp_prefix} {fam}".strip()

        if style == "formal_both":
            if p_card and sp_prefix:
                if card_is_male:
                    return f"{p_card} {card_initial} & {sp_prefix} {sp_initial} {fam}".strip()
                else:
                    return f"{sp_prefix} {sp_initial} & {p_card} {card_initial} {fam}".strip()
            return f"{_format_single(card)} & {spouse_name}".strip()

        # Default: british_formal — "Mr & Mrs B Smith" (husband's initial only)
        if p_card and sp_prefix:
            if card_is_male:
                return f"{p_card} & {sp_prefix} {card_initial} {fam}".strip()
            else:
                return f"{sp_prefix} & {p_card} {sp_initial} {fam}".strip()
        return f"{_format_single(card)} & {spouse_name}".strip()

    def _format_couple(c1, c2):
        fam = _family(c1) or _family(c2)

        def _is_male(c):
            if c.gender == "M": return True
            if c.gender == "F": return False
            return _prefix(c).lower() in ("mr", "master", "sir", "lord")

        def _is_female(c):
            if c.gender == "F": return True
            if c.gender == "M": return False
            return _prefix(c).lower() in ("mrs", "ms", "miss", "lady", "dame")

        both_male   = _is_male(c1)   and _is_male(c2)
        both_female = _is_female(c1) and _is_female(c2)
        same_sex    = both_male or both_female

        if same_sex:
            # Same-sex couple: use both initials, alphabetical by given name
            a, b = (c1, c2) if (_given(c1) or "") <= (_given(c2) or "") else (c2, c1)
            p_a, p_b = _prefix(a), _prefix(b)
            if style == "informal":
                return f"{_given(a)} & {_given(b)} {fam}".strip()
            if style == "family":
                return f"The {fam} Family".strip()
            if style == "formal_no_initial":
                if p_a and p_b and p_a == p_b:
                    return f"{p_a} & {p_b} {fam}".strip()  # Mr & Mr Smith
                return f"{p_a or _initial(a)} & {p_b or _initial(b)} {fam}".strip()
            # formal_both and british_formal: both initials
            if p_a and p_b:
                return f"{p_a} {_initial(a)} & {p_b} {_initial(b)} {fam}".strip()
            return f"{_initial(a)} & {_initial(b)} {fam}".strip()

        # Mixed-sex couple: order male then female
        male   = c1 if _is_male(c1) else (c2 if _is_male(c2) else c1)
        female = c2 if male is c1 else c1
        p_m, p_f = _prefix(male), _prefix(female)

        if style == "informal":
            return f"{_given(male)} & {_given(female)} {fam}".strip()

        if style == "family":
            return f"The {fam} Family".strip()

        if style == "formal_no_initial":
            if p_m and p_f: return f"{p_m} & {p_f} {fam}".strip()
            if p_m:         return f"{p_m} & {fam}".strip()
            if p_f:         return f"{p_f} {fam}".strip()
            return fam

        if style == "formal_both":
            if p_m and p_f: return f"{p_m} {_initial(male)} & {p_f} {_initial(female)} {fam}".strip()
            if p_m:         return f"{p_m} & {_initial(female)} {fam}".strip()
            if p_f:         return f"{_initial(male)} & {p_f} {fam}".strip()
            return f"{_initial(male)} & {_initial(female)} {fam}".strip()

        # Default: british_formal — "Mr & Mrs B Smith" (husband's initial only)
        if p_m and p_f: return f"{p_m} & {p_f} {_initial(male)} {fam}".strip()
        if p_m:         return f"{p_m} {_initial(male)} {fam}".strip()
        if p_f:         return f"{p_f} {_initial(female)} {fam}".strip()
        return f"{_initial(male)} & {_initial(female)} {fam}".strip()

    def _format_single(card):
        p = _prefix(card)
        if card.kind == "org" or not card.name or (not _family(card) and not card.name.given):
            return card.fn or card.org or "Unknown"
        fn = card.fn or ""
        return f"{p} {fn}".strip() if p and not fn.startswith(p) else fn

    def _format_address(card):
        if not card.addresses: return []
        a = card.addresses[0]
        lines = []
        if a.street:      lines.append(a.street.strip())
        if a.extended:    lines.append(a.extended.strip())
        if a.locality:    lines.append(a.locality.strip())
        if a.region:      lines.append(a.region.strip())
        if a.postal_code: lines.append(a.postal_code.strip())
        if include_country and a.country and a.country.strip().lower() not in (
            "uk", "united kingdom", "england", "scotland", "wales", "gb"
        ):
            lines.append(a.country.strip())
        return lines

    used_uids: set = set()
    pool_by_uid = {c.uid: c for c in pool if c.uid}
    records = []

    # Relationship types that qualify as a couple for label merging
    _COUPLE_TYPES = frozenset({
        "spouse", "partner", "husband", "wife",
        "co-habitant", "cohabitant", "domestic partner",
    })

    def _couple_priority(rel):
        """Lower number = checked first. Spouse/partner always checked before others."""
        rt = (rel.rel_type or "").lower().strip()
        return 0 if rt in _COUPLE_TYPES else 1

    for card in pool:
        if card.uid in used_uids:
            continue
        partner = None
        partner_text = None  # name from text-only RELATED (no full card)

        # style='individual' means the user explicitly wants no couple merging
        if style != "individual":
            # Sort relations so spouse/partner types are tried before any other type
            sorted_rels = sorted(card.related or [], key=_couple_priority)
            for rel in sorted_rels:
                if (rel.rel_type or "").lower().strip() not in _COUPLE_TYPES:
                    continue
                if rel.uid:
                    # ── UID-linked partner (full card) ────────────────────────────
                    candidate = pool_by_uid.get(rel.uid) or uid_map.get(rel.uid)
                    if not candidate or candidate.uid in used_uids: continue
                    if not candidate.addresses or not candidate.addresses[0].street: continue
                    if _family(card) and _family(card) == _family(candidate):
                        if _addr_key(card) and _addr_key(card) == _addr_key(candidate):
                            partner = candidate
                            break
                elif rel.text and rel.text.strip():
                    # ── Text-only spouse name — no separate card needed ───────────
                    if partner_text is None:
                        partner_text = rel.text.strip()

        if partner:
            # Full card merge
            used_uids.add(card.uid)
            used_uids.add(partner.uid)
            records.append({"name": _format_couple(card, partner),
                            "address": _format_address(card), "merged": True})
        elif partner_text:
            # Text-only spouse: compose name from card + spouse name string
            used_uids.add(card.uid) if card.uid else None
            couple_name = _format_couple_from_text(card, partner_text)
            records.append({"name": couple_name,
                            "address": _format_address(card), "merged": True})
        else:
            if card.uid: used_uids.add(card.uid)
            records.append({"name": _format_single(card),
                            "address": _format_address(card), "merged": False})

    def _surname_sort_key(r):
        # Sort by surname (last word of name) then full name — handles
        # "Mr & Mrs B Smith" correctly by sorting on "smith" not "mr"
        words = r["name"].split()
        surname = words[-1].lower() if words else ""
        return (surname, r["name"].lower())
    records.sort(key=_surname_sort_key)
    return records


def _api_preview_labels(body: dict) -> dict:
    """Return label records for preview, plus contacts with no address as warnings."""
    cards = _state["cards"]
    if not cards:
        return {"ok": False, "error": "No contacts loaded"}
    try:
        category = body.get("category", "")

        # Find contacts in category with no usable street address
        if category:
            pool_all = [c for c in cards if category in (c.categories or [])]
        else:
            pool_all = [c for c in cards if c.kind != "self"]

        no_address = sorted([
            {"fn": c.fn or c.org or "Unknown",
             "_idx": next((i for i, x in enumerate(cards) if x is c), -1)}
            for c in pool_all
            if not c.addresses or not c.addresses[0].street
        ], key=lambda x: x["fn"].lower())

        indices = body.get("indices") or None  # list of global _idx values, or None
        records = _build_label_records(
            cards,
            category        = category,
            style           = body.get("style", "formal"),
            include_country = bool(body.get("include_country", True)),
            indices         = indices,
        )
        merged = sum(1 for r in records if r["merged"])
        return {
            "ok": True,
            "records": records,
            "total": len(records),
            "merged": merged,
            "no_address": no_address,
        }
    except Exception as exc:
        import traceback
        print(f"[preview_labels error] {traceback.format_exc()}", flush=True)
        return {"ok": False, "error": str(exc)}


def _api_print_labels(body: dict) -> dict:
    """Generate an address-label HTML file for a given category."""
    cards = _state["cards"]
    if not cards:
        return {"ok": False, "error": "No contacts loaded"}

    try:
        from .print_modules import get_profile, get_all_modules
        category    = body.get("category", "")
        style       = body.get("style", "formal")
        printer_id  = body.get("printer_id", "") or "brother_ql820nwb"
        profile_id  = body.get("profile_id", "") or "DK22205"
        test_mode   = bool(body.get("test_mode", False))
        include_country = bool(body.get("include_country", True))

        # Fallback: if ids are missing/invalid, use first available module+profile
        profile = get_profile(printer_id, profile_id)
        if not profile:
            modules = get_all_modules()
            if not modules:
                return {"ok": False, "error": "No print modules found in print_modules/"}
            printer_id = modules[0]["printer_id"]
            profile_id = modules[0]["default_profile"]
            profile    = get_profile(printer_id, profile_id)
        if not profile:
            return {"ok": False, "error": f"Could not resolve a print profile"}

        page_css   = profile["page_css"]
        label_css  = profile["label_css"]
        name_size  = profile["name_size"]
        print_hint = profile["hint"]

        indices = body.get("indices") or None  # specific card indices, overrides category
        records = _build_label_records(cards, category, style, include_country, indices=indices)

        if test_mode:
            records = records[:3]

        total = len(records)
        merged_count = sum(1 for r in records if r["merged"])

        # Generate HTML
        label_htmls = []
        for r in records:
            addr_lines = "".join(f"<div class='aline'>{_esc_html(l)}</div>" for l in r["address"])
            merged_mark = " <span class='mmark'>⚭</span>" if r["merged"] else ""
            label_htmls.append(f"""<div class='label'>
  <div class='name'>{_esc_html(r['name'])}{merged_mark}</div>
  <div class='addr'>{addr_lines}</div>
</div>""")

        test_banner = """<div style='position:fixed;top:0;left:0;right:0;background:#ff0;color:#000;
            text-align:center;font-size:10pt;padding:4px;font-family:sans-serif;
            print-color-adjust:exact;-webkit-print-color-adjust:exact'>
            ⚠ TEST MODE — first 3 labels only</div>
            <div style='height:24pt'></div>""" if test_mode else ""

        from datetime import datetime
        generated = datetime.now().strftime("%Y-%m-%d %H:%M")
        cat_label = category or "all contacts"

        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Address Labels — {_esc_html(cat_label)}</title>
<style>
@page {{ {page_css} }}
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ font-family: Arial, Helvetica, sans-serif; background: white; }}
.label {{
  {label_css}
  display: flex;
  flex-direction: column;
  justify-content: center;
  page-break-after: always;
  break-after: page;
  padding: 1mm;
}}
.name {{
  font-size: {name_size};
  font-weight: bold;
  color: #000;
  margin-bottom: 1.5mm;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}}
.addr {{ color: #111; }}
.aline {{ white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
.mmark {{ font-size: 7pt; color: #555; font-weight: normal; }}
/* Screen preview — show label outlines */
@media screen {{
  body {{
    background: #eee;
    padding: 10px;
    font-family: Arial, sans-serif;
  }}
  .label {{
    background: white;
    border: 1px solid #bbb;
    border-radius: 3px;
    margin: 8px auto;
    box-shadow: 0 1px 4px rgba(0,0,0,.15);
    padding: 4mm 5mm;
  }}
  .screen-header {{
    text-align: center;
    font-family: monospace;
    font-size: 11px;
    color: #555;
    margin-bottom: 16px;
    padding: 8px;
    background: #fff;
    border: 1px solid #ddd;
    border-radius: 3px;
  }}
  .screen-header strong {{ color: #222; }}
}}
@media print {{
  .screen-header {{ display: none; }}
  body {{ background: white; }}
}}
</style>
</head>
<body>
{test_banner}
<div class="screen-header">
  <strong>vCard Studio — Address Labels</strong><br>
  Category: <strong>{_esc_html(cat_label)}</strong> &nbsp;|&nbsp;
  {total} label{'s' if total != 1 else ''} &nbsp;|&nbsp;
  {merged_count} couple{'s' if merged_count != 1 else ''} merged &nbsp;|&nbsp;
  Label: <strong>{profile_id}</strong> &nbsp;|&nbsp;
  Style: <strong>{style}</strong> &nbsp;|&nbsp;
  Generated: {generated}<br><br>
  <strong>Print:</strong> Ctrl+P / ⌘P &nbsp;·&nbsp;
  Select printer: <strong>{printer_id}</strong> &nbsp;·&nbsp;
  {print_hint} &nbsp;·&nbsp;
  Margins: <strong>None / Minimum</strong>
</div>
{''.join(label_htmls)}
</body>
</html>"""

        # Write to print/ folder
        out_dir = _ROOT / "print"
        out_dir.mkdir(exist_ok=True)
        from datetime import datetime as _dt
        ts = _dt.now().strftime("%Y-%m-%d-%H%M")
        safe_cat = re.sub(r"[^\w-]", "-", category or "all").strip("-")
        mode_sfx = "-TEST" if test_mode else ""
        out_path = out_dir / f"labels-{safe_cat}-{ts}{mode_sfx}.html"
        out_path.write_text(html, encoding="utf-8")

        return {
            "ok": True,
            "file": str(out_path),
            "filename": out_path.name,
            "total": total,
            "merged": merged_count,
            "test_mode": test_mode,
        }

    except Exception as exc:
        import traceback
        print(f"[print_labels error] {traceback.format_exc()}", flush=True)
        return {"ok": False, "error": str(exc)}


def _esc_html(s: str) -> str:
    """Minimal HTML escaping for label output."""
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def _api_birthdays(body: dict) -> dict:
    """Return all contacts that have a birthday or anniversary, sorted month-first.

    Returns list of {fn, bday, anniversary, categories, _idx} dicts.
    Optionally filtered to specific categories.
    """
    cards = _state["cards"]
    import re as _re
    filter_cats = set(body.get("categories", []))  # empty = all

    def _parse_date(ds: str) -> tuple[int, int, int | None]:
        """Parse vCard date → (month, day, year|None). Returns (0,0,None) on failure."""
        if not ds:
            return (0, 0, None)
        ds = ds.strip()
        # --MMDD format (no year)
        m = _re.match(r"^--(\d{2})(\d{2})$", ds)
        if m:
            return (int(m.group(1)), int(m.group(2)), None)
        # YYYYMMDD
        m = _re.match(r"^(\d{4})(\d{2})(\d{2})$", ds)
        if m:
            return (int(m.group(2)), int(m.group(3)), int(m.group(1)))
        # YYYY-MM-DD
        m = _re.match(r"^(\d{4})-(\d{2})-(\d{2})", ds)
        if m:
            return (int(m.group(2)), int(m.group(3)), int(m.group(1)))
        # YYYYMM
        m = _re.match(r"^(\d{4})(\d{2})$", ds)
        if m:
            return (int(m.group(2)), 0, int(m.group(1)))
        return (0, 0, None)

    import datetime as _dt
    this_year = _dt.date.today().year

    _COUPLE_TYPES = frozenset({
        "spouse", "partner", "husband", "wife",
        "co-habitant", "cohabitant", "domestic partner",
    })
    uid_map = {c.uid: (i, c) for i, c in enumerate(cards) if c.uid}

    def _fmt_couple_name(c1, c2):
        """Minimal couple name for anniversary display: 'Alice & Bob Smith'."""
        def _given(c): return (c.name.given if c.name and c.name.given else (c.fn or "").split()[0] if c.fn else "").strip()
        def _family(c): return (c.name.family if c.name and c.name.family else ((c.fn or "").split()[-1] if c.fn and len(c.fn.split())>1 else "")).strip()
        fam = _family(c1) or _family(c2)
        g1, g2 = _given(c1), _given(c2)
        # Put names in alphabetical order
        names = sorted([g1, g2]) if g1 and g2 else [g1 or g2]
        return f"{' & '.join(n for n in names if n)} {fam}".strip()

    events = []
    seen_anniv_pairs: set = set()  # frozensets of idx pairs already merged

    for idx, card in enumerate(cards):
        # Apply category filter if specified
        if filter_cats:
            card_cats = {c.lower() for c in (card.categories or [])}
            if not card_cats.intersection({c.lower() for c in filter_cats}):
                continue

        # ── Anniversaries: merge couples onto one line ────────────────────────
        if card.anniversary:
            month, day, year = _parse_date(card.anniversary)
            if 1 <= month <= 12:
                age = (this_year - year) if year and 1800 < year < this_year + 1 else None
                partner_idx = None
                partner_card = None
                # Find a spouse/partner who shares the same anniversary date
                for rel in (card.related or []):
                    if (rel.rel_type or "").lower().strip() not in _COUPLE_TYPES: continue
                    if not rel.uid: continue
                    result = uid_map.get(rel.uid)
                    if not result: continue
                    pidx, pc = result
                    if not pc.anniversary: continue
                    pm, pd, py = _parse_date(pc.anniversary)
                    if pm == month and pd == day:
                        partner_idx = pidx
                        partner_card = pc
                        break
                if partner_card and partner_idx is not None:
                    pair_key = frozenset([idx, partner_idx])
                    if pair_key not in seen_anniv_pairs:
                        seen_anniv_pairs.add(pair_key)
                        events.append({
                            "_idx":       idx,
                            "_idx2":      partner_idx,
                            "fn":         _fmt_couple_name(card, partner_card),
                            "categories": card.categories,
                            "event_type": "anniversary",
                            "date_str":   card.anniversary,
                            "month":      month,
                            "day":        day,
                            "year":       year,
                            "age":        age,
                            "merged":     True,
                        })
                else:
                    # Solo anniversary (no matched spouse)
                    events.append({
                        "_idx": idx, "_idx2": None,
                        "fn": card.fn or card.org or "Unknown",
                        "categories": card.categories,
                        "event_type": "anniversary",
                        "date_str": card.anniversary,
                        "month": month, "day": day, "year": year, "age": age,
                        "merged": False,
                    })

        # ── Birthdays: always individual ──────────────────────────────────────
        if card.bday:
            month, day, year = _parse_date(card.bday)
            if 1 <= month <= 12:
                age = (this_year - year) if year and 1800 < year < this_year + 1 else None
                events.append({
                    "_idx": idx, "_idx2": None,
                    "fn": card.fn or card.org or "Unknown",
                    "categories": card.categories,
                    "event_type": "birthday",
                    "date_str": card.bday,
                    "month": month, "day": day, "year": year, "age": age,
                    "merged": False,
                })

    # Sort by month, then day
    events.sort(key=lambda e: (e["month"], e["day"] or 0))
    return {"ok": True, "events": events, "total": len(events)}


def _api_unlink_related(body: dict) -> dict:
    """Remove a bidirectional RELATED link between two cards.

    body: {from_idx, uid}  — uid is the UID of the card to unlink from from_idx.
    Removes the link on both cards.
    """
    cards = _state["cards"]
    try:
        fi = int(body["from_idx"])
        target_uid = str(body.get("uid", "")).strip()
        if not target_uid or fi < 0 or fi >= len(cards):
            return {"ok": False, "error": "Invalid parameters"}

        from_card = cards[fi]
        from_card.related = [r for r in (from_card.related or [])
                             if r.uid != target_uid]

        # Remove reciprocal link on the target card
        from_uid = from_card.uid or ""
        for card in cards:
            if (card.uid == target_uid) or any(r.uid == target_uid for r in (card.related or [])):
                if card.uid == target_uid:
                    card.related = [r for r in (card.related or [])
                                   if r.uid != from_uid]

        from_card.log_change(f"Unlinked UID {target_uid}")
        _autosave_checkpoint()
        return {"ok": True}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _api_link_related(body: dict) -> dict:
    """Create a bidirectional RELATED link between two cards.

    body: {from_idx, to_idx, rel_type}
    Adds RELATED on from→to and the reciprocal type on to→from.
    """
    from .model import Related
    RECIPROCAL = {
        "spouse": "spouse", "partner": "partner",
        "sibling": "sibling", "parent": "child", "child": "parent",
        "friend": "friend", "co-worker": "co-worker", "colleague": "colleague",
        "emergency": "emergency", "kin": "kin",
    }
    cards = _state["cards"]
    try:
        fi = int(body["from_idx"])
        ti = int(body["to_idx"])
        if fi == ti or fi < 0 or ti < 0 or fi >= len(cards) or ti >= len(cards):
            return {"ok": False, "error": "Invalid indices"}

        from_card = cards[fi]
        to_card   = cards[ti]
        rel_type  = body.get("rel_type", "spouse")
        recip     = RECIPROCAL.get(rel_type, rel_type)

        # Add forward link (from → to)
        to_uid  = to_card.uid   or to_card.fn  or ""
        fr_uid  = from_card.uid or from_card.fn or ""
        # Remove any existing link between these two first (avoid duplicates)
        from_card.related = [r for r in from_card.related
                             if not (r.uid and r.uid == to_card.uid)
                             and not (r.text and r.text == (to_card.fn or ""))]
        to_card.related   = [r for r in to_card.related
                             if not (r.uid and r.uid == from_card.uid)
                             and not (r.text and r.text == (from_card.fn or ""))]

        from_card.related.append(Related(
            rel_type=rel_type,
            uid=to_card.uid or None,
            text=to_card.fn or to_card.org or "",
        ))
        to_card.related.append(Related(
            rel_type=recip,
            uid=from_card.uid or None,
            text=from_card.fn or from_card.org or "",
        ))

        from_card.log_change(f"Linked {rel_type} → {to_card.fn or to_card.org}")
        to_card.log_change(f"Linked {recip} → {from_card.fn or from_card.org}")

        _autosave_checkpoint()
        return {"ok": True,
                "from_name": from_card.fn or "",
                "to_name": to_card.fn or "",
                "rel_type": rel_type, "recip": recip}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _api_merge_cards(body: dict) -> dict:
    """Manually merge 2+ cards by index into a single card.

    body: { indices: [i, j, ...], keep_idx: i (optional — which card is the base) }
    Uses merge_cluster_auto from dedupe: richest card wins, fields unioned.
    Removes all but the merged card from the list.
    """
    from .dedupe import merge_cluster_auto
    cards = _state["cards"]
    try:
        indices = [int(x) for x in body.get("indices", [])]
        if len(indices) < 2:
            return {"ok": False, "error": "Need at least 2 cards to merge"}
        if any(i < 0 or i >= len(cards) for i in indices):
            return {"ok": False, "error": "Invalid card index"}
        if len(set(indices)) != len(indices):
            return {"ok": False, "error": "Duplicate indices"}

        cluster = [cards[i] for i in indices]
        merged  = merge_cluster_auto(cluster)

        # Determine where to put the merged card — lowest index wins
        keep_pos = min(indices)
        merged.log_change(f"Manually merged {len(indices)} cards via web UI")

        # Remove all cluster members (highest index first to preserve positions)
        for i in sorted(indices, reverse=True):
            cards.pop(i)

        # Re-insert merged card at the lowest original position
        # (positions shift after pops, so recalculate)
        insert_at = keep_pos - sum(1 for i in indices if i < keep_pos)
        insert_at = max(0, min(insert_at, len(cards)))
        cards.insert(insert_at, merged)

        _autosave_checkpoint()
        return {
            "ok":      True,
            "merged":  len(indices),
            "fn":      merged.fn or merged.org or "Merged contact",
            "new_idx": insert_at,
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _api_delete_card(body: dict) -> dict:
    """Remove a card by global index."""
    cards = _state["cards"]
    idx = body.get("index")
    if idx is None or idx < 0 or idx >= len(cards):
        return {"ok": False, "error": "Invalid index"}
    removed = cards.pop(idx)
    _autosave_checkpoint()
    return {"ok": True, "removed": removed.fn or removed.org or "Unnamed"}


def _api_settings() -> dict:
    """Return current server-side settings."""
    try:
        p = _get_pipeline()
        _, settings = p["ensure_workspace"](_ROOT)
        return {
            "ok": True,
            "default_region": settings.default_region,
            "owner_name": settings.owner_name,
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _api_apple_name_unset(params: dict) -> dict:
    """Return individuals with fn set but no given/family name AND no X-IOS override, for the quick-fix UI."""
    cards = _state.get("cards", [])
    results = []
    for i, c in enumerate(cards):
        kind = (c.kind or "individual").lower()
        if kind == "org":
            continue
        fn = (c.fn or "").strip()
        if not fn:
            continue
        name = c.name if hasattr(c, "name") else None
        given  = (name.given  or "").strip() if name else ""
        family = (name.family or "").strip() if name else ""
        # Already fixed via X-IOS override — skip
        if getattr(c, "x_ios_given", None) or getattr(c, "x_ios_family", None):
            continue
        if not given and not family:
            prefix = (name.prefix or "").strip() if name else ""
            results.append({"_idx": i, "fn": fn, "prefix": prefix})
    return {"ok": True, "cards": results, "total": len(results)}


def _api_set_structured_name(body: dict) -> dict:
    """Set iOS display name override on a single card by _idx.

    Writes X-IOS-GIVEN / X-IOS-FAMILY — never touches name.given / name.family,
    so the card's real structured name (and KIND) is preserved.
    """
    cards = _state.get("cards", [])
    idx = body.get("idx")
    given  = (body.get("given")  or "").strip()
    family = (body.get("family") or "").strip()
    if idx is None:
        return {"ok": False, "error": "Invalid request"}
    idx = int(idx)
    if idx < 0 or idx >= len(cards):
        return {"ok": False, "error": "Card not found"}
    card = cards[idx]
    if given:
        card.x_ios_given  = given
    elif hasattr(card, "x_ios_given"):
        del card.x_ios_given
    if family:
        card.x_ios_family = family
    elif hasattr(card, "x_ios_family"):
        del card.x_ios_family
    _autosave_checkpoint()
    return {"ok": True}



    """Return individuals with no gender set, for the quick-assign UI."""
    cards = _state.get("cards", [])
    results = [
        {"_idx": i, "fn": c.fn or c.org or "(unnamed)", "prefix": (c.name.prefix if c.name else "") or ""}
        for i, c in enumerate(cards)
        if c.kind != "org" and not (c.gender or "").strip()
    ]
    return {"ok": True, "cards": results, "total": len(results)}


def _api_set_gender(body: dict) -> dict:
    """Set gender on a single card by _idx."""
    cards = _state.get("cards", [])
    idx = body.get("idx")
    gender = (body.get("gender") or "").strip().upper()
    if idx is None or gender not in ("M", "F", ""):
        return {"ok": False, "error": "Invalid request"}
    idx = int(idx)
    if idx < 0 or idx >= len(cards):
        return {"ok": False, "error": "Card not found"}
    cards[idx].gender = gender or None
    _autosave_checkpoint()
    return {"ok": True}


def _api_auto_prefix(body: dict) -> dict:
    """Set name prefix from gender for individuals missing a prefix.

    Rules:
      gender M + no prefix → Mr
      gender F + no prefix → Ms

    Only sets prefix where it is not already recorded. Skips organisations.
    """
    cards = _state.get("cards")
    if not cards:
        return {"ok": False, "error": "No cards loaded"}

    log = []
    changed = 0
    for card in cards:
        if card.kind == "org":
            continue
        if (card.name.prefix or "").strip():   # already has a prefix
            continue
        gender = (card.gender or "").upper()
        if gender == "M":
            card.name.prefix = "Mr"
            changed += 1
            log.append(f"Mr  {card.fn or '(unnamed)'}")
        elif gender == "F":
            card.name.prefix = "Ms"
            changed += 1
            log.append(f"Ms  {card.fn or '(unnamed)'}")

    if changed:
        _autosave_checkpoint()

    return {"ok": True, "changed": changed, "log": log}



    """Infer gender from name prefix for all loaded individual contacts.

    Rules:
      Mr, Master  → M
      Mrs, Ms, Miss → F

    Only sets gender where it is not already recorded. Skips organisations.
    """
    cards = _state.get("cards")
    if not cards:
        return {"ok": False, "error": "No cards loaded"}

    MALE_PREFIXES   = {"mr", "master"}
    FEMALE_PREFIXES = {"mrs", "ms", "miss"}

    log = []
    changed = 0
    for card in cards:
        if card.kind == "org":
            continue
        if card.gender:          # already set — leave it alone
            continue
        prefix = (card.name.prefix or "").strip().rstrip(".").lower()
        if not prefix:
            continue
        if prefix in MALE_PREFIXES:
            card.gender = "M"
            changed += 1
            log.append(f"M  {card.fn or card.org or '(unnamed)'}")
        elif prefix in FEMALE_PREFIXES:
            card.gender = "F"
            changed += 1
            log.append(f"F  {card.fn or card.org or '(unnamed)'}")

    if changed:
        _autosave_checkpoint()

    return {"ok": True, "changed": changed, "log": log}


def _api_reformat_phones(body: dict) -> dict:
    """Re-run phone normalisation on all loaded cards and return a log of changes.

    Uses the same GOV.UK-style spaced-E.164 formatter as the normalise step,
    so +44 193 2 2 69627 becomes +44 1932 269627, etc.
    Marks the workspace as dirty so the next export/save picks up the changes.
    """
    cards = _state.get("cards")
    if not cards:
        return {"ok": False, "error": "No cards loaded"}

    try:
        from .formatters import normalize_phones_in_cards
        p = _get_pipeline()
        _, settings = p["ensure_workspace"](_ROOT)
        region = settings.default_region or "GB"

        # Snapshot before
        before = {id(c): list(c.tels) for c in cards}

        normalize_phones_in_cards(cards, default_region=region, infer_from_adr=True)

        # Build change log
        log = []
        changed = 0
        for card in cards:
            old_tels = before[id(card)]
            if old_tels != card.tels:
                changed += 1
                name = card.fn or card.org or "(unnamed)"
                for old, new in zip(old_tels, card.tels):
                    if old != new:
                        log.append(f"{name}: {old!r} → {new!r}")
                # Handle length differences
                for extra in card.tels[len(old_tels):]:
                    log.append(f"{name}: (new) {extra!r}")

        # Mark dirty so next save/export picks up changes
        _state["dirty"] = True
        _autosave_checkpoint()

        return {"ok": True, "changed": changed, "log": log}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _api_save_settings(body: dict) -> dict:
    """Persist updated settings to local/vcard.conf."""
    import re
    try:
        p = _get_pipeline()
        paths, settings = p["ensure_workspace"](_ROOT)
        conf_path = paths.conf_file

        # Read existing config text to preserve comments and other keys
        try:
            conf_text = conf_path.read_text(encoding="utf-8")
        except Exception:
            conf_text = ""

        updated_keys = {}
        if "default_region" in body:
            updated_keys["default_region"] = body["default_region"]
        if "owner_name" in body:
            updated_keys["owner_name"] = body["owner_name"]

        for key, val in updated_keys.items():
            quoted = f'"{val}"'
            pattern = rf'^{re.escape(key)}\s*=.*$'
            replacement = f'{key} = {quoted}'
            if re.search(pattern, conf_text, re.MULTILINE):
                conf_text = re.sub(pattern, replacement, conf_text, flags=re.MULTILINE)
            else:
                conf_text = conf_text.rstrip('\n') + f'\n{key} = {quoted}\n'

        conf_path.write_text(conf_text, encoding="utf-8")
        return {"ok": True}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _api_export_individual(body: dict) -> dict:
    """Export each card as a separate .vcf file in cards-out/vcard-studio-<iso>/."""
    cards = _state["cards"]
    if not cards:
        return {"ok": False, "error": "No cards loaded"}
    try:
        version = body.get("version", "4.0")
        apple_compat = bool(body.get("apple_compat", False))
        if apple_compat:
            version = "3.0"
        categories_filter = body.get("categories", [])
        export_cards = [c for c in cards if any(cat in c.categories for cat in categories_filter)] if categories_filter else cards

        from .exporter import export_vcards_individual
        from datetime import datetime as _dt2
        iso = _dt2.now().strftime("%Y-%m-%d-%H%M")
        label = "apple" if apple_compat else "vcard-studio"
        out_dir = _ROOT / "cards-out" / f"{label}-{iso}"

        _autosave_checkpoint()

        # Apple/iOS name warning
        apple_name_warn = None
        if apple_compat:
            bad = _get_apple_name_warnings(export_cards)
            if bad:
                apple_name_warn = {
                    "count": len(bad),
                    "contacts": [b["fn"] for b in bad],
                }

        written, skipped = export_vcards_individual(export_cards, out_dir, target_version=version, apple_compat=apple_compat)
        result = {"ok": True, "written": written, "skipped": skipped, "folder": out_dir.name, "apple_name_warning": apple_name_warn}
        if skipped:
            result["warning"] = f"{skipped} card(s) skipped due to data errors"
        return result
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _api_card_raw(params: dict) -> dict:
    """Return serialised vCard text for one card (raw viewer)."""
    cards = _state["cards"]
    try:
        idx = int(params.get("idx", ["-1"])[0])
        version = params.get("version", ["4.0"])[0]
        if idx < 0 or idx >= len(cards):
            return {"ok": False, "error": "Index out of range"}
        from .exporter import card_to_vcf_text
        text = card_to_vcf_text(cards[idx], target_version=version)
        return {"ok": True, "text": text, "fn": cards[idx].fn or "", "idx": idx}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _api_normalise_countries(body: dict) -> dict:
    """Analyse or apply country name normalisation.

    GET-style (body={dry_run:true}): returns preview of what would change.
    POST-style (body={replacements:{old:new,...}}): applies the replacements.
    """
    cards = _state["cards"]

    # Canonical country names we map TO — ISO 3166-1 official English names
    CANONICAL = {
        # British Isles variants
        "uk": "United Kingdom",
        "u.k.": "United Kingdom",
        "great britain": "United Kingdom",
        "britain": "United Kingdom",
        "england": "United Kingdom",
        "scotland": "United Kingdom",
        "wales": "United Kingdom",
        "northern ireland": "United Kingdom",
        "united kingdom of great britain": "United Kingdom",
        # US variants
        "us": "United States",
        "u.s.": "United States",
        "usa": "United States",
        "u.s.a.": "United States",
        "united states of america": "United States",
        "america": "United States",
        # Common others
        "nederland": "Netherlands",
        "the netherlands": "Netherlands",
        "holland": "Netherlands",
        "deutschland": "Germany",
        "espana": "Spain",
        "españa": "Spain",
        "suisse": "Switzerland",
        "schweiz": "Switzerland",
        "svizzera": "Switzerland",
        "eire": "Ireland",
        "republic of ireland": "Ireland",
        "aotearoa": "New Zealand",
        "nz": "New Zealand",
        "aus": "Australia",
        "oz": "Australia",
        "ca": "Canada",
        "fr": "France",
        "de": "Germany",
        "it": "Italy",
        "es": "Spain",
        "pt": "Portugal",
        "pl": "Poland",
        "se": "Sweden",
        "no": "Norway",
        "dk": "Denmark",
        "fi": "Finland",
        "be": "Belgium",
        "at": "Austria",
        "ch": "Switzerland",
        "nl": "Netherlands",
        "ie": "Ireland",
        "jp": "Japan",
        "cn": "China",
        "in": "India",
        "br": "Brazil",
        "za": "South Africa",
        "sg": "Singapore",
        "ae": "United Arab Emirates",
        "uae": "United Arab Emirates",
    }

    if body.get("apply"):
        # Apply supplied replacements {old_name: new_name}
        replacements = body.get("replacements", {})
        changed = 0
        for card in cards:
            for adr in (card.addresses or []):
                old = (adr.country or "").strip()
                if old in replacements:
                    adr.country = replacements[old]
                    changed += 1
        if changed:
            _autosave_checkpoint()
        return {"ok": True, "changed": changed}

    # Dry-run: find all unique country values and suggest canonical forms
    seen: dict[str, int] = {}
    for card in cards:
        for adr in (card.addresses or []):
            c = (adr.country or "").strip()
            if c:
                seen[c] = seen.get(c, 0) + 1

    suggestions = []
    for raw, count in sorted(seen.items(), key=lambda x: -x[1]):
        lo = raw.lower().strip()
        canonical = CANONICAL.get(lo)
        # If no direct match, try prefix/contains match
        if not canonical:
            for k, v in CANONICAL.items():
                if lo.startswith(k) or k.startswith(lo):
                    canonical = v
                    break
        suggestions.append({
            "raw": raw,
            "count": count,
            "suggested": canonical or raw,  # suggest self if no match (already canonical)
            "needs_fix": canonical is not None and canonical != raw,
        })

    return {"ok": True, "countries": suggestions}


def _api_reissue_uids(body: dict) -> dict:
    """Replace all vendor-issued UIDs with clean vcard-studio-<uuid> ones.

    Also assigns new UIDs to any card that still has none.
    Returns counts of replaced and assigned UIDs.
    """
    from .normalize import _is_vendor_uid, new_vs_uid
    cards = _state["cards"]
    replaced = 0
    assigned = 0
    for card in cards:
        if not card.uid or _is_vendor_uid(card.uid):
            old = card.uid or "(none)"
            card.uid = new_vs_uid()
            if card.uid:
                card.log_change(f"UID reissued: {old} → {card.uid}")
                replaced += 1
            else:
                card.log_change(f"UID assigned: {card.uid}")
                assigned += 1
    _autosave_checkpoint()
    return {"ok": True, "replaced": replaced, "assigned": assigned,
            "total": len(cards)}


def _api_search_orgs(params: dict) -> dict:
    """Search org/group KIND cards for the MEMBER picker."""
    q = params.get("q", [""])[0].lower().strip()
    cards = _state["cards"]
    results = []
    for i, c in enumerate(cards):
        if c.kind not in ("org", "group"):
            continue
        name = (c.org or c.fn or "").lower()
        if not q or q in name:
            results.append({
                "_idx": i, "fn": c.fn or c.org or "",
                "org": c.org or "", "uid": c.uid or "",
                "kind": c.kind or "org",
                "member_count": len(c.member or []),
            })
        if len(results) >= 20:
            break
    return {"results": results}


def _api_quit() -> dict:
    """Shut down the server gracefully."""
    def _stop():
        time.sleep(0.3)
        if _server_ref:
            _server_ref.shutdown()
    threading.Thread(target=_stop, daemon=True).start()
    return {"ok": True, "message": "Server shutting down"}


# ── Request handler ────────────────────────────────────────────────────────────

class VCardHandler(BaseHTTPRequestHandler):

    def log_message(self, fmt, *args):
        # Suppress default access log noise
        pass

    def _send_json(self, data: dict, status: int = 200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path: Path):
        try:
            data = path.read_bytes()
            mime, _ = mimetypes.guess_type(str(path))
            mime = mime or "application/octet-stream"
            self.send_response(200)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
            self.send_header("Pragma", "no-cache")
            self.end_headers()
            self.wfile.write(data)
        except FileNotFoundError:
            self.send_response(404)
            self.end_headers()

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        params = parse_qs(parsed.query)

        if path == "/" or path == "/index.html":
            self._send_file(_STATIC / "index.html")
        elif path == "/api/status":
            self._send_json(_api_status())
        elif path == "/api/cards":
            self._send_json(_api_cards(params))
        elif path == "/api/search_cards":
            self._send_json(_api_search_cards(params))
        elif path == "/api/settings":
            self._send_json(_api_settings())
        elif path == "/api/card_raw":
            self._send_json(_api_card_raw(params))
        elif path == "/api/gender_unset":
            self._send_json(_api_gender_unset(params))
        elif path == "/api/apple_name_unset":
            self._send_json(_api_apple_name_unset(params))
        elif path == "/api/print_cards":
            self._send_json(_api_print_cards(params))
        elif path == "/api/print_modules":
            print("[DEBUG] /api/print_modules called", flush=True)
            self._send_json(_api_print_modules())
        elif path == "/api/search_orgs":
            self._send_json(_api_search_orgs(params))
        elif path == "/api/birthdays":
            # Support GET with query param categories=friends,family etc
            cats = [c for c in params.get("categories", [""])[0].split(",") if c.strip()]
            self._send_json(_api_birthdays({"categories": cats}))
        elif path == "/api/quit":
            self._send_json(_api_quit())
        elif path.startswith("/static/"):
            self._send_file(_STATIC / path[8:])
        elif path.startswith("/print/"):
            self._send_file(_ROOT / "print" / path[7:])
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body_raw = self.rfile.read(length)
        try:
            body = json.loads(body_raw) if body_raw else {}
        except Exception:
            body = {}

        path = urlparse(self.path).path

        if path == "/api/process":
            self._send_json(_api_process(body))
        elif path == "/api/export":
            self._send_json(_api_export(body))
        elif path == "/api/export_individual":
            self._send_json(_api_export_individual(body))
        elif path == "/api/reissue_uids":
            self._send_json(_api_reissue_uids(body))
        elif path == "/api/normalise_countries":
            self._send_json(_api_normalise_countries(body))
        elif path == "/api/export_csv":
            self._send_json(_api_export_csv(body))
        elif path == "/api/update_card":
            self._send_json(_api_update_card(body))
        elif path == "/api/full_update_card":
            self._send_json(_api_full_update_card(body))
        elif path == "/api/add_card":
            self._send_json(_api_add_card(body))
        elif path == "/api/delete_card":
            self._send_json(_api_delete_card(body))
        elif path == "/api/link_related":
            self._send_json(_api_link_related(body))
        elif path == "/api/unlink_related":
            self._send_json(_api_unlink_related(body))
        elif path == "/api/waive_field":
            self._send_json(_api_waive_field(body))
        elif path == "/api/bulk_add_category":
            self._send_json(_api_bulk_add_category(body))
        elif path == "/api/label_options":
            self._send_json(_api_label_options(body))
        elif path == "/api/unwaive_field":
            self._send_json(_api_unwaive_field(body))
        elif path == "/api/strip_proprietary":
            self._send_json(_api_strip_proprietary(body))
        elif path == "/api/birthdays":
            self._send_json(_api_birthdays(body))
        elif path == "/api/print_labels":
            self._send_json(_api_print_labels(body))
        elif path == "/api/preview_labels":
            self._send_json(_api_preview_labels(body))
        elif path == "/api/merge_cards":
            self._send_json(_api_merge_cards(body))
        elif path == "/api/reformat_phones":
            self._send_json(_api_reformat_phones(body))
        elif path == "/api/auto_gender":
            self._send_json(_api_auto_gender(body))
        elif path == "/api/auto_prefix":
            self._send_json(_api_auto_prefix(body))
        elif path == "/api/set_gender":
            self._send_json(_api_set_gender(body))
        elif path == "/api/gender_unset":
            self._send_json(_api_gender_unset(params))
        elif path == "/api/apple_name_unset":
            self._send_json(_api_apple_name_unset(params))
        elif path == "/api/set_structured_name":
            self._send_json(_api_set_structured_name(body))
        elif path == "/api/save_settings":
            self._send_json(_api_save_settings(body))
        elif path == "/api/quit":
            self._send_json(_api_quit())
        else:
            self._send_json({"error": "Not found"}, 404)


# ── Entry point ────────────────────────────────────────────────────────────────

def main():
    global _server_ref

    # ── Startup diagnostics ────────────────────────────────────────────────────
    print(f"\n  vCard Studio v{_VERSION}")
    print(f"  Project root : {_ROOT}")
    print(f"  cards-in     : {_ROOT / 'cards-in'}")
    print(f"  cards-wip    : {_ROOT / 'cards-wip'}")
    print(f"  cards-out    : {_ROOT / 'cards-out'}")
    _ckpt_vcf  = _ROOT / "cards-wip" / "checkpoint.vcf"
    _ckpt_json = _ROOT / "cards-wip" / "checkpoint.json"
    if _ckpt_vcf.exists():
        print(f"  checkpoint.vcf  : {_ckpt_vcf.stat().st_size // 1024} KB")
        print(f"  checkpoint.json : {'OK' if _ckpt_json.exists() else 'MISSING — will synthesise'}")
    else:
        _in_vcfs = list((_ROOT / "cards-in").glob("*.vcf")) if (_ROOT / "cards-in").is_dir() else []
        if _in_vcfs:
            print(f"  source files : {', '.join(f.name for f in _in_vcfs)}")
        else:
            print(f"  source files : (none — drop .vcf files into cards-in/)")

    # Ensure static dir exists
    _STATIC.mkdir(parents=True, exist_ok=True)

    # Ensure cards-in exists so the UI can show the drop zone
    (_ROOT / "cards-in").mkdir(parents=True, exist_ok=True)
    (_ROOT / "cards-out").mkdir(parents=True, exist_ok=True)
    (_ROOT / "print").mkdir(parents=True, exist_ok=True)

    # Auto-detect any existing output from a previous merge
    _load_existing_output()

    # Kill any stale process on the port from a previous run
    import socket as _sock
    _probe = _sock.socket(_sock.AF_INET, _sock.SOCK_STREAM)
    _in_use = _probe.connect_ex(("127.0.0.1", PORT)) == 0
    _probe.close()
    if _in_use:
        try:
            import subprocess, signal
            result = subprocess.run(
                ["lsof", "-ti", f"tcp:{PORT}"],
                capture_output=True, text=True,
            )
            pids = [p for p in result.stdout.strip().split() if p.isdigit()]
            for pid in pids:
                os.kill(int(pid), signal.SIGTERM)
            time.sleep(0.6)
        except Exception:
            print(f"\n  Port {PORT} is already in use.")
            print(f"  Run:  kill $(lsof -ti tcp:{PORT})\n")
            sys.exit(1)

    class _Server(HTTPServer):
        allow_reuse_address = True

    print(f"\n  http://localhost:{PORT}\n")
    print("  Press Ctrl-C to stop\n")

    server = _Server(("127.0.0.1", PORT), VCardHandler)
    _server_ref = server

    # Open browser after short delay so server is ready
    def _open():
        time.sleep(0.6)
        webbrowser.open(f"http://localhost:{PORT}")
    threading.Thread(target=_open, daemon=True).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  Bye.\n")


if __name__ == "__main__":
    main()
