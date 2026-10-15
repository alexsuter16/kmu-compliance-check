"""Schritt 9 – Oberfläche: der Compliance-Check im Browser (Gradio).

Eingabe ist ein erfundener Testshop oder die Adresse eines echten Shops. Während
der Prüfung füllen sich Fortschrittsbalken und die 18 Prüfpunkte live; danach
erscheinen Score mit Ampel, der ganze Bericht und die geladenen Seiten.
Wie die Teile aussehen (HTML und CSS), steht in ui_parts.py.

Die Prüfung läuft in einem eigenen Thread und meldet ihre Fortschritte über eine
Warteschlange. So kommen sich Gradio und LangGraph nicht in die Quere.

Aufruf:  make app    →  http://localhost:7860
Bauplan: docs/bauplan.html, Art. 16a
"""

import os
import queue
import threading
import time
from collections.abc import Iterator
from urllib.parse import urlparse

import gradio as gr

from catalog import CHECKS
from config import TESTSHOPS_DIR
from crawler import is_public_url
from drafts import draft_all, render_drafts
from laws import legal_text
from llm import settings
from pipeline import save_result, stream_check
from ui_parts import CSS, NOTE_HTML, THEME, checks_html, header_html, pages_html, progress_html, score_html

TESTSHOPS = sorted(path.name for path in TESTSHOPS_DIR.iterdir() if path.is_dir())
DEFAULT_SOURCE = "testshop:bergwiese"
MODELS = list(dict.fromkeys(m for m in (os.environ.get("LLM_NAME"),
                                        "swiss-ai/apertus-v1.5-8b", "swiss-ai/apertus-v1.5-70b") if m))
CACHE_SECONDS = 15 * 60       # echte Shops nicht bei jedem Klick erneut laden
REPORT_EMPTY = "_Der Bericht mit Belegen, Rechtsgrundlagen und Vorschlägen erscheint nach der Prüfung._"
DRAFTS_EMPTY = "_Nach einer Prüfung mit Mängeln erscheint hier der Knopf für die Entwürfe._"


# --- Eingabe prüfen ---------------------------------------------------------------

def normalize_source(raw: str) -> str:
    """Macht aus der Eingabe eine gültige Quelle: «testshop:<name>» oder eine https-Adresse."""
    raw = (raw or DEFAULT_SOURCE).strip()
    if raw.startswith("testshop:"):
        if raw.split(":", 1)[1] not in TESTSHOPS:
            raise gr.Error(f"Unbekannter Testshop. Vorhanden: {', '.join(TESTSHOPS)}")
        return raw

    url = raw if raw.startswith(("http://", "https://")) else "https://" + raw
    host = urlparse(url).hostname or ""
    if "." not in host:
        raise gr.Error("Bitte eine vollständige Adresse eingeben, z.B. https://nuvate.ch")
    if not is_public_url(url):                      # auch der Lader prüft jede Weiterleitung so
        raise gr.Error(f"«{host}» ist nicht erreichbar oder keine öffentliche Website.")
    return url


def _require_model_settings() -> None:
    try:
        settings("apertus")
    except RuntimeError:
        raise gr.Error("Kein Apertus-Modell eingestellt. Setze LLM_NAME, LLM_BASE_URL und LLM_API_KEY "
                       "(in .env oder als Umgebungsvariablen) und starte neu.")


# --- Prüfung im Hintergrund und Zwischenspeicher --------------------------------------

def run_in_thread(source: str, model: str) -> Iterator[dict]:
    """Führt stream_check() in einem eigenen Thread aus und gibt dessen Ereignisse weiter."""
    events: queue.Queue = queue.Queue()

    def worker() -> None:
        try:
            for event in stream_check(source, "apertus", model):
                events.put(event)
        except Exception as error:
            events.put({"event": "fehler", "message": f"{error.__class__.__name__}: {error}"})
        finally:
            events.put(None)                            # Ende der Prüfung

    threading.Thread(target=worker, daemon=True).start()
    while (event := events.get()) is not None:
        yield event


_cache: dict[tuple[str, str], tuple[float, dict]] = {}      # (Quelle, Modell) → (Zeit, fertige Prüfung)
_cache_lock = threading.Lock()


def _cached(source: str, model: str) -> dict | None:
    with _cache_lock:
        entry = _cache.get((source, model))
    if entry and time.time() - entry[0] < CACHE_SECONDS:
        return entry[1]
    return None


def _remember(source: str, model: str, checked: dict) -> None:
    if not source.startswith("testshop:"):                  # Testshops sollen immer live laufen
        with _cache_lock:
            _cache[(source, model)] = (time.time(), checked)


# --- Anzeige ------------------------------------------------------------------------

def _ui(progress=None, score=None, checks=None, pages=None, report=None, download=None,
        checked=None, drafts=None, drafts_text=None) -> tuple:
    """Eine Aktualisierung der Oberfläche. Nicht genannte Teile bleiben, wie sie sind."""
    values = (progress, score, checks, pages, report, download, checked, drafts, drafts_text)
    return tuple(gr.skip() if value is None else value for value in values)


def _finished_ui(checked: dict, note: str = "") -> tuple:
    result = checked["result"]
    verdicts = {v["id"]: v for v in result["results"]}
    has_defects = any(v["status"] in ("fehlt", "teilweise") for v in result["results"])
    done = f"Fertig · {result['source']}"
    return _ui(progress=progress_html(done, len(CHECKS), detail=f"{len(CHECKS)}/{len(CHECKS)} Prüfpunkte {note}"),
               score=score_html(result, note), checks=checks_html(verdicts), pages=pages_html(checked["pages"]),
               report=result["report"], download=gr.DownloadButton(value=checked["report_file"], visible=True),
               checked=checked, drafts=gr.Button(visible=has_defects))


def run_check_in_ui(raw_source: str, model: str):
    """Der Knopf «Prüfen»: aktualisiert laufend Fortschritt und Prüfpunkte, am Schluss Score und Bericht."""
    source = normalize_source(raw_source)
    _require_model_settings()

    cached = _cached(source, model)
    if cached:
        yield _finished_ui(cached, "· aus dem Zwischenspeicher")
        return

    started, verdicts, pages = time.time(), {}, []
    yield _ui(progress=progress_html(f"Prüfe {source}", detail="Seiten werden geladen …"),
              score=score_html(None), checks=checks_html(verdicts, running=True), pages=pages_html([]), report="",
              download=gr.DownloadButton(visible=False), drafts=gr.Button(visible=False), drafts_text=DRAFTS_EMPTY)

    for event in run_in_thread(source, model):
        if event["event"] == "fehler":
            raise gr.Error(f"Die Prüfung ist abgebrochen: {event['message']}")
        if event["event"] == "seiten":
            pages = event["pages"]
            loaded = f"{len(pages)} Seiten geladen · Apertus urteilt …"
            yield _ui(progress=progress_html(f"Prüfe {source}", detail=loaded), pages=pages_html(pages))
        elif event["event"] == "urteil":
            verdicts[event["verdict"]["id"]] = event["verdict"]
            count = f"{len(verdicts)}/{len(CHECKS)} Prüfpunkte · {time.time() - started:.0f} s"
            yield _ui(progress=progress_html(f"Prüfe {source}", len(verdicts), detail=count),
                      checks=checks_html(verdicts, running=True))
        elif event["event"] == "fertig":
            checked = {"result": event["result"], "pages": pages, "model": model,
                       "report_file": str(save_result(event["result"]))}
            _remember(source, model, checked)
            yield _finished_ui(checked)


def create_drafts_in_ui(checked: dict):
    """Der Knopf «Textvorschläge erstellen»: Apertus entwirft für jeden Mangel einen Textbaustein."""
    if not checked:
        raise gr.Error("Zuerst einen Shop prüfen.")
    yield "_Apertus schreibt Textvorschläge für die Mängel …_"
    drafts = draft_all(checked["result"]["results"], checked["pages"], "apertus", checked["model"])
    yield render_drafts(drafts)


# --- Aufbau der Seite -------------------------------------------------------------

def build_app() -> gr.Blocks:
    with gr.Blocks(title="KMU-Compliance-Check", analytics_enabled=False) as app:
        gr.HTML(header_html())
        with gr.Group(elem_classes="kmu-input"):
            with gr.Row(equal_height=True):
                source = gr.Textbox(value=DEFAULT_SOURCE, label="Shop", scale=4, show_label=True,
                                    placeholder="https://nuvate.ch oder testshop:bergwiese",
                                    info="Adresse eines Shops oder einer der erfundenen Testshops")
                model = gr.Dropdown(MODELS, value=MODELS[0] if MODELS else None, label="Modell",
                                    allow_custom_value=True, scale=2)
                start = gr.Button("Prüfen", variant="primary", scale=1, elem_classes="kmu-start")
        gr.Examples([["testshop:bergwiese"], ["testshop:velowerk"], ["testshop:baerenstark"], ["https://nuvate.ch"]],
                    inputs=[source], label="Beispiele")

        progress = gr.HTML(progress_html("Bereit", detail="Shop eingeben und «Prüfen» klicken"))
        with gr.Row(equal_height=False):
            with gr.Column(scale=1, min_width=280, elem_classes="kmu-sticky"):   # bleibt beim Scrollen sichtbar
                score = gr.HTML(score_html(None))
            with gr.Column(scale=3):
                checks = gr.HTML(checks_html({}))

        with gr.Tabs():
            with gr.Tab("Bericht"):
                report = gr.Markdown(REPORT_EMPTY, elem_classes="kmu-report")
                download = gr.DownloadButton("Bericht herunterladen (Markdown)", visible=False)
            with gr.Tab("Textvorschläge"):
                gr.Markdown("Apertus entwirft für jeden Mangel einen Textbaustein mit den echten Angaben des Shops. "
                            "Erfundene Kontaktangaben ersetzt der Code durch Platzhalter.")
                drafts_button = gr.Button("Textvorschläge für die Mängel erstellen", visible=False)
                drafts = gr.Markdown(DRAFTS_EMPTY, elem_classes="kmu-report")
            with gr.Tab("Geladene Seiten"):
                pages = gr.HTML(pages_html([]))
        checked = gr.State()                       # die letzte fertige Prüfung: Ergebnis, Seiten, Modell
        gr.HTML(NOTE_HTML)

        gr.on(triggers=[start.click, source.submit], fn=run_check_in_ui, inputs=[source, model],
              outputs=[progress, score, checks, pages, report, download, checked, drafts_button, drafts],
              concurrency_limit=2, show_progress="hidden")       # eigener Fortschrittsbalken statt Gradios
        drafts_button.click(create_drafts_in_ui, inputs=[checked], outputs=[drafts], concurrency_limit=2)
    return app


if __name__ == "__main__":
    legal_text(["UWG Art. 3 Abs. 1 lit. s"])               # bricht sofort ab, wenn die Passagen fehlen
    if not os.environ.get("LLM_API_KEY"):
        print("Hinweis: LLM_NAME, LLM_BASE_URL und LLM_API_KEY sind nicht gesetzt – Prüfungen werden scheitern.")
    build_app().queue(max_size=10).launch(
        server_name=os.environ.get("GRADIO_SERVER_NAME", "127.0.0.1"),
        server_port=int(os.environ.get("GRADIO_SERVER_PORT", "7860")),
        theme=THEME, css=CSS,
    )
