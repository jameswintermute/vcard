"""
Print module: Generic A4 / US Letter label sheet
=================================================

Produces a 2-column label grid on standard A4 or US Letter paper.
Suitable for printing on Avery-style sticky label sheets, or simply as
a plain address list on any office printer.

This module exists as a reference implementation for contributors who
want to add support for their own printer or label format.

See print_modules/README.md for the full module specification.
"""

PRINTER_ID   = "generic_a4"
PRINTER_NAME = "Generic A4 / Letter"
PRINTER_DESC = "Standard office printer · A4 or US Letter · 2-column label grid"

LABEL_PROFILES = [
    {
        "id":        "A4_2col",
        "name":      "A4 · 2-column label grid (e.g. Avery L7160 / 63.5 × 38.1mm)",
        "page_css":  "size: A4 portrait; margin: 10mm 7mm;",
        "label_css": (
            "width: 90mm; min-height: 36mm; font-size: 9pt; line-height: 1.55;"
            "display: inline-block; vertical-align: top;"
            "margin: 1mm 2mm; padding: 2mm 3mm;"
        ),
        "name_size": "10pt",
        "hint":      "Paper: A4 · Margins: None · Scale: 100% · 2 columns per row",
    },
    {
        "id":        "A4_list",
        "name":      "A4 · plain address list (one contact per row, no labels)",
        "page_css":  "size: A4 portrait; margin: 15mm 20mm;",
        "label_css": (
            "width: 100%; font-size: 9pt; line-height: 1.55;"
            "border-bottom: 0.5pt solid #ccc; padding: 4pt 0;"
        ),
        "name_size": "10pt",
        "hint":      "Paper: A4 · Standard margins · Any office printer",
    },
    {
        "id":        "Letter_2col",
        "name":      "US Letter · 2-column label grid (e.g. Avery 5160 / 1\" × 2⅝\")",
        "page_css":  "size: letter portrait; margin: 12.7mm 4.8mm;",
        "label_css": (
            "width: 88mm; min-height: 25.4mm; font-size: 8.5pt; line-height: 1.5;"
            "display: inline-block; vertical-align: top;"
            "margin: 0; padding: 1.5mm 2mm;"
        ),
        "name_size": "9.5pt",
        "hint":      "Paper: US Letter · Margins: None · Scale: 100%",
    },
]

PRINT_STEPS = [
    "Open the generated HTML file in your browser (it opens automatically).",
    "Press <strong>Ctrl+P</strong> (Windows/Linux) or <strong>⌘P</strong> (macOS).",
    "Select your office printer.",
    "Paper: <strong>A4</strong> (or US Letter).",
    "Margins: <strong>None</strong>.",
    "Scale: <strong>100% / Actual size</strong>.",
    "Print.",
]

DEFAULT_PROFILE_ID = "A4_2col"
