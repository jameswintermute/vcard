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

### Getting the dimensions right

Label dimensions in the `@page` size rule must match the physical label size
**exactly**. Measure your label or check the manufacturer spec sheet.

At 300 dpi (the QL-820NWB's resolution):
- 1mm = ~11.8 pixels
- 29mm wide = ~342 px
- 62mm wide = ~732 px

Use the **test mode** button (generates 3 labels) to verify layout before
printing a full roll.

---

## Included Modules

| File | Printer | Formats |
|---|---|---|
| `brother_ql820nwb.py` | Brother QL-820NWB (and compatible QL series) | DK-22205 (62mm), DK-11201 (29×90mm), DK-11209 (29×62mm) |
| `generic_a4.py` | Any office printer | A4 2-column grid, A4 list, US Letter 2-column grid |

---

## Sharing Your Module

If you add a module and it works well, please consider opening a pull request
on the main repository so others with the same printer can benefit.

Include in your PR:
- The `.py` module file
- The printer model and tape/label spec you tested with
- A brief note in this README table above
