from __future__ import annotations

import re

import vobject

from .model import Card


def _get_text(v, default=None):
    try:
        return str(v.value).strip()
    except Exception:
        return default

def normalize_cards(vcards: list[vobject.base.Component]) -> list[Card]:
    out: list[Card] = []
    for vc in vcards:
        fn = _get_text(getattr(vc, "fn", None))
        n = _get_text(getattr(vc, "n", None))
        emails = []
        for e in getattr(vc, "email_list", []):
            val = _get_text(e)
            if val:
                emails.append(val.lower())
        tels = []
        for t in getattr(vc, "tel_list", []):
            val = re.sub(r"\s+", "", _get_text(t, ""))
            if val:
                tels.append(val)
        org = None
        if getattr(vc, "org", None):
            try:
                org = " ".join([p for p in vc.org.value if p]).strip()
            except Exception:
                pass
        title = _get_text(getattr(vc, "title", None))
        bday = _get_text(getattr(vc, "bday", None))
        uid = _get_text(getattr(vc, "uid", None))
        rev = _get_text(getattr(vc, "rev", None))

        out.append(Card(raw=vc, fn=fn, n=n, emails=emails, tels=tels, org=org, title=title, bday=bday, uid=uid, rev=rev))
    return out

def strip_proprietary(card: Card) -> Card:
    from .proprietary import DefaultStripper
    return DefaultStripper().strip(card)
