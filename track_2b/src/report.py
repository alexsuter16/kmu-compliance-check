"""Schritt 7 – Bericht: macht aus Score und Urteilen einen lesbaren Bericht (Markdown).

Reihenfolge wie im Bauplan, Art. 1: zuerst die Muss-Mängel, dann Kann-Mängel,
dann teilweise oder unklare Punkte, am Schluss das, was erfüllt ist.

Bauplan: docs/bauplan.html, Art. 1
"""

STATUS_LABEL = {
    "fehlt": "✕ Fehlt", "teilweise": "◐ Teilweise", "unklar": "? Unklar",
    "erfuellt": "✓ Erfüllt", "nicht_anwendbar": "– Nicht anwendbar",
}
LIGHT_LABEL = {"gruen": "🟢 Grün", "gelb": "🟡 Gelb", "rot": "🔴 Rot"}


def _finding(r: dict) -> str:
    lines = [f"### {STATUS_LABEL[r['status']]} · {r['title']}",
             f"{r['kind'].capitalize()} · {', '.join(r['legal_refs'])}"]
    if r.get("beleg"):
        lines.append(f"> «{r['beleg']}» ({r.get('seite') or 'Seite'})")
    if r.get("begruendung"):
        lines.append(r["begruendung"])
    if r.get("verbesserung"):
        lines.append(f"**→ {r['verbesserung']}**")
    if r.get("hinweis"):
        lines.append(f"_{r['hinweis']}_")
    return "\n\n".join(lines)


def _page_label(page: dict) -> str:
    if page.get("unreadable"):
        return f"{page['type']} (nicht einsehbar: {page.get('reason', 'nicht lesbar')})"
    return f"[{page['type']}]({page['url']})"


def _usage_line(usage: dict) -> str:
    tokens = f"{usage['input'] + usage['output']:,}".replace(",", "'")
    if usage.get("cost_usd") is None:
        return f"Verbrauch: {tokens} Tokens (lokales Modell, keine Kosten pro Aufruf)"
    return f"Verbrauch: {tokens} Tokens · rund USD {usage['cost_usd']:.4f} zum Listenpreis"


def render_report(source: str, model: str, pages: list[dict], results: list[dict], score: dict,
                  usage: dict | None = None) -> str:
    groups = [
        ("Muss-Mängel", [r for r in results if r["status"] == "fehlt" and r["kind"] == "muss"]),
        ("Kann-Mängel", [r for r in results if r["status"] == "fehlt" and r["kind"] == "kann"]),
        ("Teilweise oder unklar", [r for r in results if r["status"] in ("teilweise", "unklar")]),
    ]
    ok = [r for r in results if r["status"] in ("erfuellt", "nicht_anwendbar")]

    parts = [
        f"# Prüfbericht: {source}",
        f"**Score {score['score']} von 100 · {LIGHT_LABEL[score['ampel']]}**  \n"
        f"{score['muss_maengel']} Muss-Mängel · {score['kann_maengel']} Kann-Mängel · "
        f"{score['teilweise_unklar']} teilweise oder unklar  \n"
        f"Berechnung: {score['punkte']:g} ÷ {score['gewichte']} × 100 · Modell: {model}"
        + (f"  \n{_usage_line(usage)}" if usage else ""),
        "Geprüfte Seiten: " + ", ".join(_page_label(p) for p in pages),
    ]
    for title, items in groups:
        if items:
            parts.append(f"## {title}")
            parts.extend(_finding(r) for r in items)
    if ok:
        parts.append("## Erfüllt oder nicht anwendbar")
        parts.append("\n".join(f"- {STATUS_LABEL[r['status']]} · {r['title']}" for r in ok))
    parts.append("---\n_Vorprüfung, keine Rechtsberatung. Gesetzestexte: fedlex.admin.ch._")
    return "\n\n".join(parts) + "\n"
