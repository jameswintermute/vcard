"""
Print module: Brother QL-820NWB label printer
==============================================

Supports DK-series tape rolls for address label printing.

Compatible models: QL-820NWB, QL-810W, QL-800, QL-710W, QL-700
(any Brother QL printer that accepts DK tape)

To add support for a different Brother QL tape size, copy one of the
LABEL_PROFILES entries below and adjust the dimensions.

See print_modules/README.md for the full module specification.
"""

# ── Module metadata ──────────────────────────────────────────────────────────

PRINTER_ID   = "brother_ql820nwb"
PRINTER_NAME = "Brother QL-820NWB"
PRINTER_DESC = "Brother QL-series label printer · DK tape · up to 62mm wide · AirPrint"

# ── Label profiles ────────────────────────────────────────────────────────────
# Each profile defines one tape/label size.
# Keys used by the core label engine:
#   id          str   — unique identifier, used in API calls
#   name        str   — display name shown in the UI dropdown
#   page_css    str   — CSS @page rule content (size + margins)
#   label_css   str   — CSS for each .label div (width, min-height, font-size, line-height)
#   name_size   str   — CSS font-size for the recipient name line
#   hint        str   — short print-dialog instruction shown to the user

LABEL_PROFILES = [
    {
        "id":         "DK22205",
        "name":       "DK-22205 · 62mm wide continuous (recommended for addresses)",
        "page_css":   "size: 62mm 38mm; margin: 1.5mm 2.5mm;",
        "label_css":  "width: 57mm; min-height: 33mm; font-size: 8.5pt; line-height: 1.5;",
        "name_size":  "10pt",
        "hint":       "Paper size: 62 × 38 mm · Margins: None · Scale: 100%",
    },
    {
        "id":         "DK11201",
        "name":       "DK-11201 · 29 × 90mm die-cut standard address label",
        "page_css":   "size: 29mm 90mm; margin: 1.5mm 2mm;",
        "label_css":  "width: 25mm; min-height: 85mm; font-size: 7.5pt; line-height: 1.45;",
        "name_size":  "8.5pt",
        "hint":       "Paper size: 29 × 90 mm · Margins: Minimum · Scale: 100%",
    },
    {
        "id":         "DK11209",
        "name":       "DK-11209 · 29 × 62mm small address label",
        "page_css":   "size: 29mm 62mm; margin: 1mm 2mm;",
        "label_css":  "width: 25mm; min-height: 58mm; font-size: 7pt; line-height: 1.4;",
        "name_size":  "8pt",
        "hint":       "Paper size: 29 × 62 mm · Margins: Minimum · Scale: 100%",
    },
]

# ── Printer-specific printing instructions ────────────────────────────────────
# Shown in the Labels panel and embedded in the generated HTML file.

PRINT_STEPS = [
    "Open the generated HTML file in your browser (it opens automatically).",
    "Press <strong>Ctrl+P</strong> (Windows/Linux) or <strong>⌘P</strong> (macOS).",
    "Printer: select <strong>Brother QL-820NWB</strong>.",
    "Paper/label size: match the tape roll loaded (see label type above).",
    "Margins: <strong>None</strong> or <strong>Minimum</strong>.",
    "Scale: <strong>100% / Actual size</strong> — do not fit to page.",
    "Print.",
]

# ── Optional: default profile to pre-select in the UI ─────────────────────────
DEFAULT_PROFILE_ID = "DK22205"
