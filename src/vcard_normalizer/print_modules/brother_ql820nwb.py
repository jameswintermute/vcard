"""
Print module: Brother QL-820NWB / QL-820NWBc label printer
===========================================================

Supports DK-series rolls for address label printing.

Compatible models: QL-820NWB, QL-820NWBc, QL-810W(c), QL-800, QL-710W, QL-700
(any Brother QL printer with a 720-pin / 300 dpi head that accepts DK rolls)

Geometry source
---------------
All dimensions below come from Brother's *QL-800/810W/820NWB Raster Command
Reference* (cv_ql800_eng_raster_101), §2.3 "Print area":

  * The head is 300 dpi, 720 pins; max print width 58.9 mm (696 dots).
  * Continuous tape: 1.5 mm unprintable strip on each long edge
    (54 mm tape: 1.9 mm). Minimum feed margin 3 mm at each end.
  * Die-cut labels: 1.5 mm unprintable on each long edge and 3.0 mm at each
    end of the label (the "length offset").

A page is described in *browser* terms:
  page_w_mm  — width of the printed page as the browser lays it out
  page_h_mm  — height of the printed page as the browser lays it out
  pad_mm     — [top, right, bottom, left] quiet zone inside the page.
               Must be ≥ the hardware unprintable strips listed above, or
               text will be clipped by the printer.

Orientation rule: the browser page's *width* must equal the physical width
of the label **as it is read**. For continuous tape and the 62 × 29 mm
die-cut, text runs across the tape (portrait). For the 29 × 90 mm and
38 × 90 mm die-cut labels, text must run along the label (landscape page),
otherwise every line is limited to ~25 mm.

To add another DK roll, copy a profile and change the numbers. The legacy
keys page_css / label_css / name_size are generated automatically so older
code that reads them keeps working.

See print_modules/README.md for the full module specification.
"""

# ── Module metadata ──────────────────────────────────────────────────────────

PRINTER_ID   = "brother_ql820nwb"
PRINTER_NAME = "Brother QL-820NWB / QL-820NWBc"
PRINTER_DESC = "Brother QL-series label printer · DK rolls · 300 dpi · max 58.9 mm print width"


def _profile(*, id, name, media, page_w_mm, page_h_mm, pad_mm, font_pt, name_pt,
             line_height, driver_paper, hint_extra=""):
    """Build a profile dict with both the new numeric keys and the legacy CSS keys."""
    t, r, b, l = pad_mm
    content_w = round(page_w_mm - l - r, 2)
    content_h = round(page_h_mm - t - b, 2)
    return {
        "id":           id,
        "name":         name,
        # ── numeric geometry (used by the roll-label engine) ──
        "layout":       "roll",            # one label per page, cut after each
        "media":        media,             # "continuous" | "die-cut"
        "page_w_mm":    page_w_mm,
        "page_h_mm":    page_h_mm,
        "pad_mm":       [t, r, b, l],
        "content_w_mm": content_w,
        "content_h_mm": content_h,
        "font_pt":      font_pt,
        "name_pt":      name_pt,
        "line_height":  line_height,
        "driver_paper": driver_paper,
        # ── legacy keys (kept for backwards compatibility) ──
        "page_css":     f"size: {page_w_mm}mm {page_h_mm}mm; margin: 0;",
        "label_css":    (f"width: {content_w}mm; height: {content_h}mm; "
                         f"font-size: {font_pt}pt; line-height: {line_height};"),
        "name_size":    f"{name_pt}pt",
        "hint":         (f"Printer paper: {driver_paper} · Margins: None · "
                         f"Scale: 100% / Actual size · Headers & footers: off"
                         + (f" · {hint_extra}" if hint_extra else "")),
    }


# ── Label profiles ────────────────────────────────────────────────────────────
# Quiet zones: continuous tape uses ≥2 mm on the cut ends and ≥2.5 mm on the
# long edges (hardware needs 1.5 mm); die-cut uses ≥3.2 mm on the label ends
# (hardware 3.0 mm) and ≥1.7 mm on the long edges (hardware 1.5 mm).

LABEL_PROFILES = [
    _profile(
        id="DK22205",
        name="DK-22205 · 62 mm continuous paper → 62 × 38 mm labels",
        media="continuous",
        page_w_mm=62, page_h_mm=38,
        pad_mm=[2.5, 3.0, 2.5, 3.0],          # content 56 × 33 mm (printable 58.9 mm)
        font_pt=9, name_pt=10.5, line_height=1.3,
        driver_paper="62 mm continuous, length 38 mm (custom size 62 × 38 mm)",
    ),
    _profile(
        id="DK22223",
        name="DK-22223 · 50 mm continuous paper → 50 × 36 mm labels",
        media="continuous",
        page_w_mm=50, page_h_mm=36,
        pad_mm=[2.5, 2.5, 2.5, 2.5],          # content 45 × 31 mm (printable 46.9 mm)
        font_pt=8.5, name_pt=9.5, line_height=1.3,
        driver_paper="50 mm continuous, length 36 mm (custom size 50 × 36 mm)",
    ),
    _profile(
        id="DK11208",
        name="DK-11208 · 38 × 90 mm die-cut large address label",
        media="die-cut",
        page_w_mm=90, page_h_mm=38,           # landscape: text runs along the label
        pad_mm=[1.8, 3.3, 1.8, 3.3],          # content 83.4 × 34.4 mm (printable 83.9 × 35.0)
        font_pt=10, name_pt=11.5, line_height=1.3,
        driver_paper="38 mm × 90 mm, orientation Landscape",
    ),
    _profile(
        id="DK11201",
        name="DK-11201 · 29 × 90 mm die-cut standard address label",
        media="die-cut",
        page_w_mm=90, page_h_mm=29,           # landscape: text runs along the label
        pad_mm=[1.7, 3.3, 1.7, 3.3],          # content 83.4 × 25.6 mm (printable 83.9 × 25.9)
        font_pt=8, name_pt=9, line_height=1.2,
        driver_paper="29 mm × 90 mm, orientation Landscape",
    ),
    _profile(
        id="DK11209",
        name="DK-11209 · 62 × 29 mm die-cut small address label",
        media="die-cut",
        page_w_mm=62, page_h_mm=29,           # 62 mm across the head, 29 mm along the feed
        pad_mm=[3.2, 1.8, 3.2, 1.8],          # content 58.4 × 22.6 mm (printable 58.9 × 22.9)
        font_pt=7.5, name_pt=8.5, line_height=1.18,
        driver_paper="62 mm × 29 mm, orientation Portrait",
    ),
]

# ── Printer-specific printing instructions ────────────────────────────────────
# Shown in the Labels panel and embedded in the generated HTML file.

PRINT_STEPS = [
    "Check the printer's LCD shows the same roll as the label type you generated "
    "(a mismatch gives an <em>Incorrect media</em> error).",
    "On the printer: <strong>Menu → Settings → Auto Cut → Auto Cut</strong> "
    "(cuts after every label).",
    "Open the generated file in <strong>Chrome</strong> (Safari may ignore the page size).",
    "Fix any label outlined <strong style='color:#c00'>red</strong> before printing.",
    "Press <strong>Ctrl+P</strong> / <strong>⌘P</strong> and choose the Brother QL-820NWB(c).",
    "Paper size: exactly the size shown in the header (custom size for continuous rolls).",
    "Margins: <strong>None</strong> · Scale: <strong>100% / Actual size</strong> · "
    "Headers and footers: <strong>off</strong>.",
    "Print the <strong>TEST</strong> file first (3 hardest labels), check it, then print all.",
]

# ── Optional: default profile to pre-select in the UI ─────────────────────────
DEFAULT_PROFILE_ID = "DK22205"
