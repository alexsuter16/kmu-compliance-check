"""Macht aus technical_report.md das PDF für die Abgabe (max. 6 Seiten).

Weg: Markdown → HTML mit Druck-Layout → Google Chrome druckt ohne Fenster ein PDF →
pypdf zählt die Seiten. Braucht `make setup-search` (markdown-it-py, pypdf) und Chrome.

Aufruf:  make report
Ergebnis: AlexSuter_Report.pdf im Ordner track_2b/
"""

import subprocess
import sys
from pathlib import Path

from markdown_it import MarkdownIt
from pypdf import PdfReader

PROJECT_DIR = Path(__file__).resolve().parent.parent
SOURCE = PROJECT_DIR / "technical_report.md"
HTML_FILE = PROJECT_DIR / "output" / "report.html"
PDF_FILE = PROJECT_DIR / "AlexSuter_Report.pdf"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
MAX_PAGES = 6

PRINT_CSS = """
@page { size: A4; margin: 13mm 15mm; }
body { font: 9.2pt/1.38 "Helvetica Neue", Arial, sans-serif; color: #17191c; }
h1 { font-size: 17pt; margin: 0 0 4pt; }
h2 { font-size: 12pt; margin: 12pt 0 4pt; border-bottom: 1px solid #c9ccd1; padding-bottom: 2pt; }
h3 { font-size: 10.5pt; margin: 9pt 0 3pt; }
p, ul, ol { margin: 0 0 5pt; }
li { margin-bottom: 1.5pt; }
table { border-collapse: collapse; width: 100%; margin: 4pt 0 7pt; font-size: 8.6pt; break-inside: avoid; }
th, td { border-bottom: 1px solid #dcdfe3; padding: 2.5pt 5pt 2.5pt 0; text-align: left; vertical-align: top; }
th { border-bottom: 1px solid #17191c; }
code { font: 8.4pt "SF Mono", Menlo, monospace; background: #f2f3f5; padding: 0 2pt; }
pre { background: #f2f3f5; padding: 5pt 7pt; font-size: 7.8pt; line-height: 1.35; break-inside: avoid; white-space: pre-wrap; }
pre code { background: none; padding: 0; }
a { color: #b42318; text-decoration: none; }
"""


def build_html() -> str:
    markdown = MarkdownIt("commonmark", {"html": True}).enable("table")
    body = markdown.render(SOURCE.read_text(encoding="utf-8"))
    return f'<!doctype html><html lang="en"><head><meta charset="utf-8"><style>{PRINT_CSS}</style></head><body>{body}</body></html>'


def print_pdf() -> None:
    HTML_FILE.parent.mkdir(exist_ok=True)
    HTML_FILE.write_text(build_html(), encoding="utf-8")
    subprocess.run([CHROME, "--headless", "--disable-gpu", "--no-pdf-header-footer",
                    f"--print-to-pdf={PDF_FILE}", HTML_FILE.as_uri()],
                   check=True, capture_output=True)


if __name__ == "__main__":
    print_pdf()
    pages = len(PdfReader(PDF_FILE).pages)
    print(f"{PDF_FILE.name}: {pages} Seiten")
    if pages > MAX_PAGES:
        sys.exit(f"Zu lang: höchstens {MAX_PAGES} Seiten erlaubt.")
