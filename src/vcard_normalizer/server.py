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
_VERSION = "3.1.6"
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

def _card_to_dict(card) -> dict:
    # Guard against old checkpoint cards that predate NameComponents
    from .model import NameComponents
    name = getattr(card, "name", None) or NameComponents()

    # Format phone numbers using libphonenumber for display
    def _fmt_tel(t: str) -> str:
        try:
            import phonenumbers as _pn
            n = _pn.parse(t, None)  # E.164 doesn't need region hint
            return _pn.format_number(n, _pn.PhoneNumberFormat.INTERNATIONAL)
        except Exception:
            return t

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
        "kind": card.kind or "individual",
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
    cats: dict[str, int] = {}
    countries: dict[str, int] = {}
    for c in cards:
        for cat in c.categories:
            cats[cat] = cats.get(cat, 0) + 1
        country = (c.addresses[0].country or "").strip() if c.addresses else ""
        if country:
            countries[country] = countries.get(country, 0) + 1

    # If we have cards but status is still "error" (e.g. stale from a failed re-merge),
    # report "loaded" so the header dot turns green and the UI isn't misleading.
    reported_status = _state["status"]
    if cards and reported_status == "error":
        reported_status = "loaded"
        _state["status"] = "loaded"

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

    total = len(indexed)
    start = (page - 1) * per_page
    page_items = indexed[start:start + per_page]

    def _with_idx(i, c):
        d = _card_to_dict(c)
        d["_idx"] = i
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
        out_path = _ROOT / "cards-out" / f"{iso}-{safe_cat}-{safe}.vcf"

        # Save a fresh checkpoint first so in-memory state is always durable
        # before we write the export (belt-and-suspenders durability)
        _autosave_checkpoint()

        count = p["export_vcards"](export_cards, out_path, target_version=version)

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
                "warning": f"{len(export_cards) - count} contact(s) were skipped during export due to data errors"
            }

        # Only clear checkpoint once we have verified the export is complete
        p["clear_checkpoint"](_ROOT / "cards-wip")

        return {"ok": True, "count": count, "file": out_path.name}

    except Exception as exc:
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
        raw_tels = [t for t in re.split(r"[\n,]+", body.get("tel",""))]
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
    # overwrite the server's RELATED list (which may contain bidirectional links
    # created by link_related on the OTHER card that the modal knows nothing about).
    # Exception: if a rel entry has no UID (text-only), it was added manually in the
    # modal and must be preserved. We merge: keep all server UIDs, add any new text-only.
    incoming_related = []
    for r in body.get("related", []):
        rt = r.get("rel_type", "spouse")
        incoming_related.append(Related(rel_type=rt, uid=r.get("uid") or None, text=r.get("text") or None))

    # Merge: server UID-links are authoritative; absorb new text-only entries from modal
    server_related = list(card.related or [])
    server_uids = {r.uid for r in server_related if r.uid}
    for r in incoming_related:
        if not r.uid:
            # Text-only entry — add if not already present
            if not any(x.text == r.text and x.rel_type == r.rel_type for x in server_related):
                server_related.append(r)
        # UID-linked entries: only add if server doesn't already have this UID
        elif r.uid not in server_uids:
            server_related.append(r)
            server_uids.add(r.uid)
    card.related = server_related

    # MEMBER — list of UID strings (org/group cards)
    card.member = [m.strip() for m in body.get("member", []) if m and m.strip()]

    # Stamp REV with current UTC time on every save
    from datetime import UTC as _UTC, datetime as _dt
    card.rev = _dt.now(_UTC).strftime("%Y%m%dT%H%M%SZ")

    card.log_change("Edited via web UI")
    _autosave_checkpoint()
    return {"ok": True, "normalised_tels": normalised}




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

    events = []
    for idx, card in enumerate(cards):
        # Apply category filter if specified
        if filter_cats:
            card_cats = {c.lower() for c in (card.categories or [])}
            if not card_cats.intersection({c.lower() for c in filter_cats}):
                continue

        for date_str, event_type in [(card.bday, "birthday"), (card.anniversary, "anniversary")]:
            if not date_str:
                continue
            month, day, year = _parse_date(date_str)
            if month < 1 or month > 12:
                continue
            age = None
            if year and year > 1800 and year < this_year + 1:
                age = this_year - year
            events.append({
                "_idx": idx,
                "fn": card.fn or card.org or "Unknown",
                "categories": card.categories,
                "event_type": event_type,
                "date_str": date_str,
                "month": month,
                "day": day,
                "year": year,
                "age": age,
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
        categories_filter = body.get("categories", [])
        export_cards = [c for c in cards if any(cat in c.categories for cat in categories_filter)] if categories_filter else cards

        from .exporter import export_vcards_individual
        from datetime import datetime as _dt2
        iso = _dt2.now().strftime("%Y-%m-%d-%H%M")
        out_dir = _ROOT / "cards-out" / f"vcard-studio-{iso}"

        _autosave_checkpoint()
        written, skipped = export_vcards_individual(export_cards, out_dir, target_version=version)
        result = {"ok": True, "written": written, "skipped": skipped, "folder": out_dir.name}
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


def _api_print_cards(params: dict) -> dict:
    """Return all cards formatted for the print/PDF view."""
    cards = _state["cards"]
    category = params.get("category", [""])[0]
    sort_order = params.get("sort_order", ["last_name"])[0]

    indexed = list(enumerate(cards))
    if category:
        indexed = [(i,c) for i,c in indexed if category in c.categories]

    def _sk(pair):
        _, c = pair
        name = getattr(c, "name", None)
        fn = (c.fn or "").strip()
        org = (c.org or "").strip()
        family = (name.family or "").strip() if name and name.family else ""
        given  = (name.given  or "").strip() if name and name.given  else ""
        if c.kind == "org":
            return (0, org.lower() or fn.lower(), "")
        if sort_order == "first_name":
            return (1, given.lower() or fn.lower(), family.lower())
        return (1, family.lower() or fn.lower(), given.lower())

    indexed.sort(key=_sk)
    result = [_card_to_dict(c) for _, c in indexed]
    from datetime import datetime as _dt
    return {
        "ok": True,
        "cards": result,
        "total": len(result),
        "generated": _dt.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
        "version": _VERSION,
    }


def _api_reformat_phones(body: dict) -> dict:
    """Reformat all phone numbers in loaded cards to E.164 international spacing.

    Uses phonenumbers library with the configured default_region as fallback.
    Returns count of numbers reformatted.
    """
    cards = _state["cards"]
    try:
        import phonenumbers
        p = _get_pipeline()
        _, settings = p["ensure_workspace"](_ROOT)
        region = settings.default_region or "GB"

        reformatted = 0
        unchanged = 0
        failed = 0
        for card in cards:
            new_tels = []
            for raw in (card.tels or []):
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    parsed = phonenumbers.parse(raw, region)
                    if phonenumbers.is_valid_number(parsed):
                        formatted = phonenumbers.format_number(
                            parsed, phonenumbers.PhoneNumberFormat.INTERNATIONAL
                        )
                        if formatted != raw:
                            reformatted += 1
                        else:
                            unchanged += 1
                        new_tels.append(formatted)
                    else:
                        new_tels.append(raw)
                        failed += 1
                except Exception:
                    new_tels.append(raw)
                    failed += 1
            card.tels = new_tels
        if reformatted:
            _autosave_checkpoint()
        return {"ok": True, "reformatted": reformatted, "unchanged": unchanged, "failed": failed}
    except ImportError:
        return {"ok": False, "error": "phonenumbers library not available"}
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
        # Direct lookup only — no fuzzy/prefix matching (that caused wrong suggestions)
        canonical = CANONICAL.get(lo)
        suggestions.append({
            "raw": raw,
            "count": count,
            "suggested": canonical or raw,
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
        elif path == "/api/print_cards":
            self._send_json(_api_print_cards(params))
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
        elif path == "/api/reformat_phones":
            self._send_json(_api_reformat_phones(body))
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
        elif path == "/api/unwaive_field":
            self._send_json(_api_unwaive_field(body))
        elif path == "/api/strip_proprietary":
            self._send_json(_api_strip_proprietary(body))
        elif path == "/api/birthdays":
            self._send_json(_api_birthdays(body))
        elif path == "/api/merge_cards":
            self._send_json(_api_merge_cards(body))
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
    _ckpt = _ROOT / "cards-wip" / "checkpoint.vcf"
    if _ckpt.exists():
        print(f"  checkpoint   : {_ckpt.stat().st_size // 1024} KB")
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
