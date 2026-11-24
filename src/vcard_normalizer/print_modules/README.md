# Print Modules

This directory contains pluggable printer and label-format modules for
vCard Studio's **Labels** feature.

Each module teaches vCard Studio how to lay out address labels for a
specific printer or paper format. The core label engine handles everything
else — contact selection, couple merging, name formatting, address lines,
test mode, and the generated HTML file.

---

## Adding Your Own Printer or Format

1. **Copy** `generic_a4.py` to a new file, e.g. `dymo_labelwriter.py`.
2. **Edit** the six required attributes:

```python
PRINTER_ID   = "dymo_labelwriter"           # unique snake_case id
PRINTER_NAME = "DYMO LabelWriter 450"       # shown in UI
PRINTER_DESC = "DYMO LabelWriter · 28mm or 36mm address tape"

LABEL_PROFILES = [
    {
        "id":        "36mm",
        "name":      "36mm address label",
        "page_css":  "size: 89mm 36mm; margin: 1mm 2mm;",
        "label_css": "width: 85mm; min-height: 32mm; font-size: 8pt; line-height: 1.5;",
        "name_size": "9.5pt",
        "hint":      "Paper size: 89 × 36mm · Margins: None · Scale: 100%",
    },
]

PRINT_STEPS = [
    "Open the generated HTML in your browser.",
    "Press Ctrl+P.",
    "Select your DYMO LabelWriter.",
    "Paper: 36mm address label.",
    "Scale: 100%. Print.",
]

DEFAULT_PROFILE_ID = "36mm"
```

3. **Restart** vCard Studio. Your module is auto-discovered — no registration needed.

---

## Label Profile Keys

| Key | Type | Description |
|---|---|---|
| `id` | str | Unique identifier within this module |
| `name` | str | Display name in the UI dropdown |
| `page_css` | str | CSS `@page` rule content (`size` + `margin`) |
| `label_css` | str | CSS applied to each `.label` div |
| `name_size` | str | CSS `font-size` for the recipient name line |
| `hint` | str | Short instruction shown next to the print button |

### Roll printers: numeric geometry (recommended)

For label-roll printers (one label per page, cut after each), add these keys
and the engine uses its roll layout: exact page size, `@page` margin 0, a
quiet zone inside each label, **auto-fit** (shrinks text to 72%, then wraps,
then flags the label red instead of silently clipping it) and identical
geometry on screen and in print.

| Key | Type | Description |
|---|---|---|
| `layout` | str | `"roll"` |
| `media` | str | `"continuous"` or `"die-cut"` |
| `page_w_mm`, `page_h_mm` | float | Browser page size. Width = label width **as read** |
| `pad_mm` | list | `[top, right, bottom, left]` quiet zone; must be ≥ the hardware unprintable strips |
| `font_pt`, `name_pt`, `line_height` | float | Base text sizes before auto-fit |
| `driver_paper` | str | Paper size to choose in the print dialog |

Profiles without these keys (e.g. `generic_a4.py`) use the flow layout:
labels run down the page and are never split across a page break.

### Getting the dimensions right

Use the manufacturer's print-area table, not the label size. For Brother QL
(QL-800/810W/820NWB Raster Command Reference §2.3, 300 dpi, 720-pin head):

| Roll | Across head | Printable across | Unprintable |
|---|---|---|---|
| 62 mm continuous (DK-22205) | 62 mm | 58.9 mm | 1.5 mm each long edge; ≥3 mm feed |
| 50 mm continuous (DK-22223) | 50 mm | 46.9 mm | 1.5 mm each long edge; ≥3 mm feed |
| 62 × 29 die-cut (DK-11209) | 62 mm | 58.9 × 22.9 mm | 1.5 mm edges, 3 mm ends |
| 29 × 90 die-cut (DK-11201) | 29 mm | 25.9 × 83.9 mm | 1.5 mm edges, 3 mm ends |
| 38 × 90 die-cut (DK-11208) | 38 mm | 35.0 × 83.9 mm | 1.5 mm edges, 3 mm ends |

For 29 × 90 and 38 × 90 labels the text must run *along* the label, so the
browser page is landscape (90 × 29 / 90 × 38) and the driver orientation is
Landscape. Otherwise each line is limited to ~25 mm.

Use the **test** button before a full run: it prints the 3 *hardest* labels
(most lines, longest line, longest name), not the first three.

---

## Included Modules

| File | Printer | Formats |
|---|---|---|
| `brother_ql820nwb.py` | Brother QL-820NWB / QL-820NWBc (and compatible QL series) | DK-22205 (62 mm), DK-22223 (50 mm), DK-11208 (38×90), DK-11201 (29×90), DK-11209 (62×29) |
| `generic_a4.py` | Any office printer | A4 2-column grid, A4 list, US Letter 2-column grid |

---

## Sharing Your Module

If you add a module and it works well, please consider opening a pull request
on the main repository so others with the same printer can benefit.

Include in your PR:
- The `.py` module file
- The printer model and tape/label spec you tested with
- A brief note in this README table above
