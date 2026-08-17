#!/usr/bin/env python3
"""Rendert SX1302_PRIVATE_SYNCWORD_EN.md als PDF im Stil des Brauneck-Handbuchs.

Die Markdown-Fassung ist das Original -- sie laesst sich direkt ins TTN-Forum
einfuegen. Das PDF ist nur die druckbare Zweitfassung; wer den Text aendert,
aendert die .md und laesst das hier neu laufen.

    python3 build_guide_en.py
"""
import subprocess
import sys
from pathlib import Path

import markdown

HIER = Path(__file__).resolve().parent
QUELLE = HIER / "SX1302_PRIVATE_SYNCWORD_EN.md"
ZIEL = HIER / "SX1302_Private_Syncword_Guide_EN.pdf"

CSS = """
@page { size: A4; margin: 16mm 14mm; }
body { font-family: "Helvetica Neue", Helvetica, Arial, sans-serif;
       font-size: 10.5pt; line-height: 1.45; color: #222; }
h1 { font-size: 19pt; margin: 0 0 3mm 0; line-height: 1.2; }
h2 { font-size: 13pt; margin: 7mm 0 2mm 0; padding-bottom: 1mm;
     border-bottom: 1.5px solid #c8922a; page-break-after: avoid; }
h3 { font-size: 11pt; margin: 4mm 0 1.5mm 0; page-break-after: avoid; }
p, li { orphans: 2; widows: 2; }
em { color: #555; }
table { border-collapse: collapse; width: 100%; margin: 2mm 0 3mm 0;
        font-size: 9.5pt; page-break-inside: avoid; }
th { background: #fdf3e3; text-align: left; padding: 1.4mm 2mm;
     border-bottom: 1.5px solid #c8922a; }
td { padding: 1.2mm 2mm; border-bottom: 0.5px solid #ddd; vertical-align: top; }
code { font-family: "DejaVu Sans Mono", Consolas, monospace; font-size: 9pt;
       background: #f4f4f4; padding: 0.3mm 1mm; border-radius: 2px; }
pre { background: #f7f7f7; border-left: 3px solid #c8922a; padding: 2mm 3mm;
      font-family: "DejaVu Sans Mono", Consolas, monospace; font-size: 8.5pt;
      overflow-wrap: anywhere; white-space: pre-wrap; page-break-inside: avoid; }
pre code { background: none; padding: 0; font-size: inherit; }
blockquote { border-left: 3px solid #ccc; margin: 3mm 0; padding: 0 0 0 3mm;
             color: #555; }
hr { border: 0; border-top: 0.5px solid #ccc; margin: 5mm 0; }
a { color: #1b6ec2; word-break: break-all; }
"""


def main():
    if not QUELLE.exists():
        print("fehlt: %s" % QUELLE, file=sys.stderr)
        return 1

    koerper = markdown.markdown(
        QUELLE.read_text(encoding="utf-8"),
        extensions=["tables", "fenced_code", "sane_lists"],
    )
    html = (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        "<title>SX1302 private sync word on the raw channel</title>"
        "<style>%s</style></head><body>%s</body></html>" % (CSS, koerper)
    )
    zwischen = HIER / "guide_en.html"
    zwischen.write_text(html, encoding="utf-8")

    r = subprocess.run(
        ["chromium", "--headless=new", "--disable-gpu", "--no-sandbox",
         "--no-pdf-header-footer", "--print-to-pdf=%s" % ZIEL,
         "file://%s" % zwischen],
        capture_output=True, text=True, timeout=180,
    )
    if not ZIEL.exists():
        print(r.stderr[-1500:], file=sys.stderr)
        return 1
    print("erzeugt: %s (%d Byte)" % (ZIEL, ZIEL.stat().st_size))
    return 0


if __name__ == "__main__":
    sys.exit(main())
