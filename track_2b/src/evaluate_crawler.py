"""Messung der Seitensuche: Findet der Lader bei echten Shops die rechtlich wichtigen Seiten?

Für jeden Shop wird nur geladen (kein Sprachmodell, keine Kosten) und notiert, welche
Seitentypen gefunden wurden. So lässt sich eine Änderung am Lader vorher/nachher messen.

Die Liste der Shops liegt bewusst ausserhalb des Repositorys (z.B. output/shops.txt),
eine Adresse pro Zeile; Zeilen mit # werden übersprungen.

Aufruf:  python src/evaluate_crawler.py output/shops.txt --name vorher
Ergebnis: output/evaluation/seitensuche__<name>.md
Bauplan: docs/bauplan.html, Art. 9 Abs. 4
"""

import argparse
import sys
import time
from pathlib import Path

from config import OUTPUT_DIR
from crawler import assign_types, load_pages

TYPES = ["impressum", "datenschutz", "agb", "versand", "produkt", "footer"]


def measure(url: str) -> dict:
    started = time.time()
    try:
        pages = assign_types(load_pages(url))
    except Exception as error:
        return {"url": url, "error": f"{error.__class__.__name__}: {str(error)[:60]}", "found": set(), "seconds": 0}
    readable = {p["type"] for p in pages if not p.get("unreadable")}
    unreadable = {p["type"] for p in pages if p.get("unreadable") and p["type"] != "checkout"}
    return {"url": url, "found": readable, "unreadable": unreadable, "pages": len(pages),
            "seconds": round(time.time() - started, 1)}


def render(name: str, rows: list[dict]) -> str:
    reachable = [r for r in rows if "error" not in r]
    lines = [f"# Seitensuche: {name}", "",
             f"{len(reachable)} von {len(rows)} Shops erreichbar.", "",
             "| Seitentyp | gefunden |", "|---|---:|"]
    for page_type in TYPES:
        hits = sum(page_type in r["found"] for r in reachable)
        lines.append(f"| {page_type} | {hits}/{len(reachable)} |")
    lines += ["", "| Shop | " + " | ".join(TYPES) + " | Seiten | Sekunden |",
              "|---|" + "---|" * len(TYPES) + "---:|---:|"]
    for r in rows:
        if "error" in r:
            lines.append(f"| {r['url']} | " + " | ".join("–" for _ in TYPES) + f" | {r['error']} | |")
            continue
        marks = ["✓" if t in r["found"] else ("JS" if t in r["unreadable"] else "✗") for t in TYPES]
        lines.append(f"| {r['url']} | " + " | ".join(marks) + f" | {r['pages']} | {r['seconds']} |")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Misst, welche Rechtsseiten der Lader bei echten Shops findet.")
    parser.add_argument("shops", help="Datei mit einer Shop-Adresse pro Zeile")
    parser.add_argument("--name", default="aktuell", help="Name der Messung, z.B. vorher oder nachher")
    args = parser.parse_args()

    urls = [line.strip() for line in Path(args.shops).read_text().splitlines()
            if line.strip() and not line.startswith("#")]
    rows = []
    for url in urls:
        row = measure(url)
        rows.append(row)
        print(f"{url:32} {', '.join(sorted(row['found'])) or row.get('error', '')}", file=sys.stderr)

    report = render(args.name, rows)
    out = OUTPUT_DIR / "evaluation" / f"seitensuche__{args.name}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report, encoding="utf-8")
    print(report)
