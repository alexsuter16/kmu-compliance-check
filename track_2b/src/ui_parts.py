"""Bausteine der Oberfläche: Aussehen (Theme, CSS) und die HTML-Teile, die app.py anzeigt.

app.py verbindet Knöpfe und Prüfung; hier steht nur, wie Ergebnisse aussehen:
Kopfzeile, Fortschrittsbalken, Score-Karte mit Ampel-Ring, die 18 Prüfpunkte als
Karten nach Rechtsgebiet und die Liste der geladenen Seiten.

Alle Texte aus Shops und vom Modell werden mit html.escape() eingesetzt, damit eine
Shop-Seite kein eigenes HTML in die Oberfläche schmuggeln kann.
Die Farben kommen aus Gradio-Variablen; so passt alles auch im dunklen Modus.
Bauplan: docs/bauplan.html, Art. 16a
"""

import math
from html import escape

import gradio as gr

from catalog import CHECKS
from crawler import MAX_PAGES

RING_RADIUS = 70                         # wie r="70" im SVG der Score-Karte

# Ohne Webschriften aus dem Internet: Die Oberfläche lädt nichts von fremden Servern
THEME = gr.themes.Soft(
    primary_hue="red", neutral_hue="slate", radius_size="lg",
    font=["Inter", "ui-sans-serif", "system-ui", "-apple-system", "Segoe UI", "Helvetica Neue", "sans-serif"],
).set(
    button_primary_background_fill="#d52b1e", button_primary_background_fill_hover="#b32217",
    button_primary_text_color="#ffffff", block_title_background_fill="transparent",
    block_title_text_color="*neutral_700", block_title_text_weight="600", block_title_padding="0",
)

LIGHT_COLOR = {"gruen": "#16a34a", "gelb": "#d97706", "rot": "#dc2626"}
LIGHT_TEXT = {"gruen": "Grün · gut aufgestellt", "gelb": "Gelb · Handlungsbedarf",
              "rot": "Rot · dringender Handlungsbedarf"}
STATUS_CHIP = {                          # Status → (Zeichen, Text)
    "erfuellt": ("✓", "Erfüllt"), "teilweise": ("◐", "Teilweise"), "fehlt": ("✕", "Fehlt"),
    "unklar": ("?", "Unklar"), "nicht_anwendbar": ("–", "Entfällt"),
    "laeuft": ("●", "Läuft"), "wartet": ("·", "Wartet"),
}
PAGE_LABEL = {"startseite": "Startseite", "impressum": "Impressum", "datenschutz": "Datenschutz", "agb": "AGB",
              "versand": "Versand & Rückgabe", "produkt": "Produkt", "newsletter": "Newsletter",
              "footer": "Menü & Footer", "checkout": "Checkout"}

CSS = """
:root { --kmu-red: #d52b1e; --kmu-radius: 16px; }
/* «clip» statt Gradios «hidden»: schneidet gleich ab, lässt aber die mitlaufende Score-Karte zu */
.gradio-container { max-width: 1180px !important; margin: 0 auto !important; overflow: clip !important; }
footer { display: none !important; }

/* Kopfzeile */
.kmu-hero { padding: 28px 30px; border-radius: var(--kmu-radius); color: #fff;
  background: radial-gradient(120% 140% at 0% 0%, #e8473b 0%, #d52b1e 45%, #9f1d14 100%);
  box-shadow: 0 12px 30px -12px rgba(213, 43, 30, .45); }
.kmu-hero-top { display: flex; align-items: center; gap: 14px; }
.kmu-cross { width: 44px; height: 44px; border-radius: 10px; background: #fff; flex: none;
  display: grid; place-items: center; }
.kmu-cross span { position: relative; width: 26px; height: 26px; }
.kmu-cross span::before, .kmu-cross span::after { content: ""; position: absolute; background: var(--kmu-red);
  border-radius: 1px; }
.kmu-cross span::before { left: 9px; top: 2px; width: 8px; height: 22px; }
.kmu-cross span::after { left: 2px; top: 9px; width: 22px; height: 8px; }
.kmu-hero h1 { margin: 0; font-size: 28px; font-weight: 750; letter-spacing: -.02em; color: #fff; }
.kmu-hero p { margin: 10px 0 0; max-width: 760px; font-size: 15px; line-height: 1.5; color: rgba(255,255,255,.92); }
.kmu-badges { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 16px; }
.kmu-badge { font-size: 12.5px; font-weight: 600; padding: 5px 11px; border-radius: 999px;
  background: rgba(255,255,255,.16); border: 1px solid rgba(255,255,255,.28); color: #fff; }

/* Eingabe */
.kmu-input { border-radius: var(--kmu-radius) !important; }
.kmu-start button, button.kmu-start { min-height: 44px; font-weight: 700; font-size: 15px; }

/* Fortschritt */
.kmu-progress { padding: 14px 18px; border-radius: var(--kmu-radius); border: 1px solid var(--border-color-primary);
  background: var(--block-background-fill); }
.kmu-progress-text { display: flex; justify-content: space-between; gap: 12px; font-size: 14px;
  color: var(--body-text-color); }
.kmu-progress-text b { font-weight: 650; }
.kmu-progress-track { height: 8px; margin-top: 10px; border-radius: 999px; overflow: hidden;
  background: var(--background-fill-secondary); }
.kmu-progress-bar { height: 100%; border-radius: 999px; background: linear-gradient(90deg, #e8473b, #d52b1e);
  transition: width .4s ease; }
.kmu-muted { color: var(--body-text-color-subdued); }

/* Score-Karte */
.kmu-sticky { position: sticky; top: 16px; align-self: flex-start; }
.kmu-score { display: flex; flex-direction: column; align-items: center; text-align: center; gap: 12px;
  padding: 22px 18px; border-radius: var(--kmu-radius); border: 1px solid var(--border-color-primary);
  background: var(--block-background-fill); height: 100%; box-sizing: border-box; }
.kmu-ring { position: relative; width: 168px; height: 168px; }
.kmu-ring svg { transform: rotate(-90deg); }
.kmu-ring-value { position: absolute; inset: 0; display: grid; place-content: center; }
.kmu-ring-value b { font-size: 46px; font-weight: 800; line-height: 1; letter-spacing: -.03em;
  color: var(--body-text-color); }
.kmu-ring-value span { font-size: 13px; color: var(--body-text-color-subdued); margin-top: 4px; }
.kmu-light { font-weight: 700; font-size: 15px; padding: 6px 14px; border-radius: 999px; }
.kmu-counts { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; width: 100%; }
.kmu-count { padding: 10px 6px; border-radius: 12px; background: var(--background-fill-secondary); }
.kmu-count b { display: block; font-size: 22px; font-weight: 750; color: var(--body-text-color); }
.kmu-count span { font-size: 12px; color: var(--body-text-color-subdued); }
.kmu-meta { font-size: 12.5px; color: var(--body-text-color-subdued); line-height: 1.5; }
.kmu-empty { color: var(--body-text-color-subdued); font-size: 14px; padding: 40px 10px; }

/* Prüfpunkte */
.kmu-area { margin: 4px 0 14px; }
.kmu-area h4 { margin: 0 0 8px; font-size: 12px; font-weight: 700; letter-spacing: .06em; text-transform: uppercase;
  color: var(--body-text-color-subdued); }
.kmu-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(250px, 1fr)); gap: 8px; }
.kmu-check { display: flex; align-items: flex-start; gap: 10px; padding: 10px 12px; border-radius: 12px;
  border: 1px solid var(--border-color-primary); background: var(--block-background-fill); }
.kmu-check > div { min-width: 0; }
.kmu-check-title { font-size: 13.5px; line-height: 1.35; color: var(--body-text-color); overflow-wrap: anywhere; }
.kmu-kind { display: inline-block; margin-top: 4px; font-size: 11px; font-weight: 600; padding: 1px 7px;
  border-radius: 6px; background: var(--background-fill-secondary); color: var(--body-text-color-subdued); }
.kmu-chip { flex: none; display: inline-flex; align-items: center; gap: 5px; font-size: 12px; font-weight: 700;
  padding: 3px 9px; border-radius: 999px; white-space: nowrap; }
.st-erfuellt { background: rgba(22,163,74,.13); color: #15803d; }
.st-teilweise { background: rgba(217,119,6,.14); color: #b45309; }
.st-fehlt { background: rgba(220,38,38,.13); color: #b91c1c; }
.st-unklar { background: rgba(100,116,139,.16); color: #475569; }
.st-nicht_anwendbar, .st-wartet { background: var(--background-fill-secondary); color: var(--body-text-color-subdued); }
.st-laeuft { background: rgba(213,43,30,.10); color: var(--kmu-red); animation: kmu-pulse 1.2s ease-in-out infinite; }
@keyframes kmu-pulse { 50% { opacity: .45; } }
.dark .st-erfuellt { color: #4ade80; } .dark .st-teilweise { color: #fbbf24; }
.dark .st-fehlt { color: #f87171; } .dark .st-unklar { color: #cbd5e1; }

/* Bericht */
.kmu-report { padding: 8px 26px 18px !important; border-radius: var(--kmu-radius);
  border: 1px solid var(--border-color-primary); background: var(--block-background-fill); }
.kmu-report h1 { font-size: 22px; letter-spacing: -.01em; }
.kmu-report h2 { font-size: 17px; margin-top: 26px; padding-top: 14px;
  border-top: 1px solid var(--border-color-primary); }
.kmu-report h3 { font-size: 15px; margin-top: 18px; }
.kmu-report blockquote { margin: 8px 0; padding: 8px 14px; border-left: 3px solid var(--kmu-red);
  background: var(--background-fill-secondary); border-radius: 0 10px 10px 0; font-style: normal; }

/* Geladene Seiten */
.kmu-pages { display: flex; flex-wrap: wrap; gap: 8px; }
.kmu-page { font-size: 13px; padding: 6px 10px; border-radius: 10px; border: 1px solid var(--border-color-primary);
  background: var(--block-background-fill); color: var(--body-text-color); text-decoration: none; }
.kmu-page.hidden-page { opacity: .65; border-style: dashed; }

/* Hinweis unten */
.kmu-note { font-size: 12.5px; line-height: 1.5; color: var(--body-text-color-subdued); text-align: center;
  padding: 8px 20px 4px; }
"""


def header_html() -> str:
    return f"""<div class="kmu-hero">
  <div class="kmu-hero-top"><div class="kmu-cross"><span></span></div><h1>KMU-Compliance-Check</h1></div>
  <p>Prüft die Website eines Schweizer Online-Shops auf {len(CHECKS)} rechtliche Punkte – Impressum, Bestellablauf,
  Preise, Datenschutz, Werbeaussagen und AGB. Jede Feststellung mit Zitat von der Website, Rechtsgrundlage
  und konkretem Verbesserungsvorschlag.</p>
  <div class="kmu-badges"><span class="kmu-badge">Apertus 1.5 · Schweizer Open-Source-Modell</span>
  <span class="kmu-badge">Gesetzestexte von fedlex</span><span class="kmu-badge">{len(CHECKS)} Prüfpunkte</span>
  <span class="kmu-badge">Belege im Code geprüft</span></div>
</div>"""


def progress_html(text: str, done: int = 0, total: int = len(CHECKS), detail: str = "") -> str:
    percent = round(100 * done / total) if total else 0
    return f"""<div class="kmu-progress">
  <div class="kmu-progress-text"><span><b>{escape(text)}</b></span><span class="kmu-muted">{escape(detail)}</span></div>
  <div class="kmu-progress-track"><div class="kmu-progress-bar" style="width:{percent}%"></div></div>
</div>"""


def score_html(result: dict | None, note: str = "") -> str:
    """Score-Karte: Ring in Ampelfarbe, Zahl, Ampeltext, Anzahl Mängel, Modell, Dauer und Kosten."""
    if not result:
        return ('<div class="kmu-score"><div class="kmu-empty">Der Score erscheint hier, sobald alle '
                f'{len(CHECKS)} Prüfpunkte beurteilt sind.</div></div>')
    score, usage = result["score"], result.get("usage", {})
    color, value = LIGHT_COLOR[score["ampel"]], score["score"]
    circumference = 2 * math.pi * RING_RADIUS
    cost = (f"USD {usage['cost_usd']:.4f}" if usage.get("cost_usd") is not None
            else "lokal, keine Kosten pro Aufruf")
    failed = sum("Modellaufruf fehlgeschlagen" in v.get("begruendung", "") for v in result["results"])
    warning = (f'<div class="kmu-meta" style="color:#b91c1c">⚠ {failed} Prüfpunkte nicht erreichbar – '
               'bitte erneut prüfen.</div>' if failed else "")
    return f"""<div class="kmu-score">
  <div class="kmu-ring">
    <svg width="168" height="168" viewBox="0 0 168 168">
      <circle cx="84" cy="84" r="70" fill="none" stroke="var(--background-fill-secondary)" stroke-width="14"/>
      <circle cx="84" cy="84" r="70" fill="none" stroke="{color}" stroke-width="14" stroke-linecap="round"
              stroke-dasharray="{circumference * value / 100:.1f} {circumference:.1f}"/>
    </svg>
    <div class="kmu-ring-value"><b>{value}</b><span>von 100</span></div>
  </div>
  <div class="kmu-light" style="background:{color}1f;color:{color}">{LIGHT_TEXT[score['ampel']]}</div>
  <div class="kmu-counts">
    <div class="kmu-count"><b>{score['muss_maengel']}</b><span>Muss-Mängel</span></div>
    <div class="kmu-count"><b>{score['kann_maengel']}</b><span>Kann-Mängel</span></div>
    <div class="kmu-count"><b>{score['teilweise_unklar']}</b><span>teilweise / unklar</span></div>
  </div>
  <div class="kmu-meta">{escape(result['model'])}<br>{result['seconds']} s · {cost} {escape(note)}</div>
  {warning}
</div>"""


def checks_html(verdicts: dict[str, dict], running: bool = False) -> str:
    """Die 18 Prüfpunkte als Karten, gruppiert nach Rechtsgebiet, mit farbigem Status."""
    areas: dict[str, list[str]] = {}
    for check in CHECKS:
        verdict = verdicts.get(check["id"])
        status = verdict["status"] if verdict else ("laeuft" if running else "wartet")
        symbol, label = STATUS_CHIP[status]
        areas.setdefault(check["area"], []).append(
            f'<div class="kmu-check"><span class="kmu-chip st-{status}">{symbol} {label}</span>'
            f'<div><div class="kmu-check-title">{escape(check["title"])}</div>'
            f'<span class="kmu-kind">{"Pflicht" if check["kind"] == "muss" else "Empfehlung"}</span></div></div>')
    return "".join(f'<div class="kmu-area"><h4>{escape(area)}</h4><div class="kmu-grid">{"".join(cards)}</div></div>'
                   for area, cards in areas.items())


def pages_html(pages: list[dict]) -> str:
    """Welche Seiten der Check gelesen hat – nicht einsehbare gestrichelt, mit Grund."""
    if not pages:
        return '<div class="kmu-muted">Noch keine Seiten geladen.</div>'
    items = []
    for page in pages:
        label = PAGE_LABEL.get(page["type"], page["type"])
        if page.get("unreadable"):
            items.append(f'<span class="kmu-page hidden-page" title="{escape(page.get("reason", ""))}">'
                         f'{escape(label)} · nicht einsehbar</span>')
        elif page["url"].startswith("http"):
            items.append(f'<a class="kmu-page" href="{escape(page["url"])}" target="_blank" rel="noopener">'
                         f'{escape(label)} ↗</a>')
        else:
            items.append(f'<span class="kmu-page">{escape(label)}</span>')
    return f'<div class="kmu-pages">{"".join(items)}</div>'


NOTE_HTML = f"""<div class="kmu-note"><b>Vorprüfung, keine Rechtsberatung.</b> Bei echten Shops werden höchstens
{MAX_PAGES} öffentliche Seiten schonend geladen (robots.txt wird beachtet); den Checkout öffnet der Check nicht.
Die Seitentexte gehen zur Beurteilung an das eingestellte Apertus-Modell.</div>"""
