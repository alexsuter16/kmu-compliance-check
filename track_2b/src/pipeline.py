"""Schritt 5 – Prüfen: die Prüfung als LangGraph-Graph, von der Shop-Adresse zum Bericht.

    START → seiten_laden → seiten_zuordnen ─┬─ pruefen (Prüfpunkt 1) ─┬→ score_berechnen → bericht → ENDE
                                            ├─ pruefen (Prüfpunkt 2) ─┤
                                            └─ … 18 × parallel ───────┘

Die 18 Prüfpunkte laufen parallel, höchstens MAX_PARALLEL gleichzeitig.

Nur der Knoten «pruefen» ruft ein Sprachmodell auf. Jeder Knoten liest den
gemeinsamen Zustand (PruefState) und schreibt einen Teil davon zurück.
Knoten heissen deutsch wie im Bauplan; Hilfsfunktionen englisch.

Aufruf:  python src/pipeline.py testshop:bergwiese --bericht
         python src/pipeline.py https://nuvate.ch --model swiss-ai/apertus-v1.5-70b
         python src/pipeline.py testshop:velowerk --provider litellm
Ergebnis: output/<shop>/<modell>.md (Bericht) und .json (alle Urteile)
Bauplan: docs/bauplan.html, Art. 9 und Art. 10
"""

import argparse
import json
import operator
import re
import time
from collections.abc import Iterator
from typing import Annotated, TypedDict

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from catalog import CHECKS
from config import output_paths
from crawler import Page, assign_types, load_pages
from evidence import QUOTE_MARKS, verified_quote
from laws import legal_text
from llm import ask, cost_usd, get_llm, parse_json_answer, settings
from prompts import QUOTE_PROMPT, RETRY_PROMPT, SYSTEM_PROMPT, build_user_prompt
from protocol import audit_trail, render_audit_trail
from report import render_report
from scoring import STATUSES, compute_score

MAX_PARALLEL = 4          # gleichzeitige Modellaufrufe; mehr führt bei Public AI zu Wartezeiten


# --- Datentypen ------------------------------------------------------------------

class Verdict(TypedDict, total=False):
    """Das Urteil über einen Prüfpunkt (Bauplan Art. 10 Abs. 2)."""
    id: str
    title: str
    area: str
    kind: str                 # «muss» oder «kann»
    weight: int
    legal_refs: list[str]
    status: str               # einer der STATUSES
    beleg: str                # wörtliches Zitat von der Seite, oder leer
    seite: str                # Seitentyp, aus dem das Zitat stammt
    begruendung: str
    verbesserung: str
    hinweis: str              # Erklärung, wenn eine Regel den Status geändert hat
    beleg_modell: str         # Zitat des Modells, das nicht auf der Seite stand – zur Nachprüfung
    status_modell: str        # Status, wie ihn das Modell gemeldet hat (vor den Regeln) – für die Messung;
                              # «unklar» auch, wenn das Modell nicht gefragt wurde oder ausfiel
    tokens: dict              # Verbrauch dieses Prüfpunkts: {"input": …, "output": …}


class PruefState(TypedDict):
    """Der gemeinsame Zustand des Graphen (Bauplan Art. 9 Abs. 5)."""
    source: str                                        # Shop-URL oder «testshop:<name>»
    provider: str                                      # «apertus» oder «litellm»
    model: str | None                                  # optional anderes Modell, z.B. 70B
    with_legal_text: bool                              # False nur für die Messung «ohne Gesetzestext»
    pages: list[Page]                                  # geladene Seiten mit Typ und Text
    results: Annotated[list[Verdict], operator.add]    # parallele Knoten hängen ihr Urteil an
    score: dict
    protocol: dict                                     # Prüfprotokoll: womit der Bericht entstand
    report: str


# --- Knoten 1 und 2: Seiten laden und zuordnen --------------------------------------

def seiten_laden(state: PruefState) -> dict:
    return {"pages": load_pages(state["source"])}


def seiten_zuordnen(state: PruefState) -> dict:
    return {"pages": assign_types(state["pages"])}


def verteilen(state: PruefState) -> list[Send]:
    """Schickt jeden Prüfpunkt als eigene Aufgabe an «pruefen» – LangGraph führt sie parallel aus."""
    return [Send("pruefen", {"check": check, "pages": state["pages"], "provider": state["provider"],
                             "model": state["model"], "with_legal_text": state["with_legal_text"]})
            for check in CHECKS]


# --- Knoten 3: ein Prüfpunkt (Bauplan Art. 10) -----------------------------------

def pruefen(task: dict) -> dict:
    """Ein Prüfpunkt: Modell fragen, dann die Antwort mit festen Regeln absichern."""
    check = task["check"]
    # Wichtigste Seiten zuerst (Reihenfolge im Katalog): Steht der Beleg am Ende eines langen
    # Prompts, übersieht ihn ein kleines Modell leichter.
    relevant = sorted((p for p in task["pages"] if p["type"] in check["pages"]),
                      key=lambda p: check["pages"].index(p["type"]))
    readable = [p for p in relevant if not p.get("unreadable")]
    unreadable = [p for p in relevant if p.get("unreadable")]

    main_page = _unreadable_main_page(check, readable, unreadable)
    if main_page:                                       # nichts zu beurteilen – Modell nicht fragen
        answer = {"status": "unklar", "begruendung": f"Die Seite «{main_page['type']}» war nicht "
                  f"einsehbar ({main_page['reason']}). Bitte von Hand prüfen."}
        tokens, conversation = {"input": 0, "output": 0}, []
    else:
        legal = legal_text(check["legal_refs"]) if task["with_legal_text"] else "(für diese Messung weggelassen)"
        answer, tokens, conversation = _ask_model(check, legal, readable, unreadable, task["provider"], task["model"])

    verdict = _to_verdict(check, answer)
    verdict["status_modell"], verdict["tokens"] = verdict["status"], tokens
    # Die Regeln in dieser Reihenfolge (Bauplan Art. 10 Abs. 3–4a):
    verdict = _verify_quote(verdict, readable)                          # 1. Steht das Zitat auf der Seite?
    verdict = _ask_for_missing_quote(verdict, check, conversation, readable,
                                     task["provider"], task["model"])   # 2. Sonst einmal nachfragen
    verdict = _apply_trigger_rule(verdict, check, readable)             # 3. Ist der Punkt überhaupt anwendbar?
    verdict = _apply_no_evidence_rule(verdict, check)                   # 4. Ist der Mangel belegt?
    verdict = _apply_unreadable_rule(verdict, readable, unreadable)     # 5. Nur nicht gefunden, weil unlesbar?
    if verdict["status"] in ("erfuellt", "nicht_anwendbar"):
        verdict["verbesserung"] = ""
    return {"results": [verdict]}


def _unreadable_main_page(check: dict, readable: list[Page], unreadable: list[Page]) -> Page | None:
    """Die wichtigste Seite des Prüfpunkts (z.B. «datenschutz»), wenn sie existiert, aber nicht lesbar ist.

    Dann wird das Modell gar nicht gefragt: Es hätte nichts zu beurteilen. Gegenstück nach dem Modell
    ist _apply_unreadable_rule (für Nebenseiten wie den Checkout).
    Steht dem Prüfpunkt der Footer zur Verfügung, urteilt das Modell trotzdem: Oft stehen z.B.
    Firma und Adresse im Footer, und genau deshalb wirkte die Impressum-Seite nach der Bereinigung leer.
    """
    main_type = check["pages"][0]
    if any(p["type"] == main_type for p in readable) or any(p["type"] == "footer" for p in readable):
        return None
    return next((p for p in unreadable if p["type"] == main_type), None)


def _ask_model(check: dict, legal: str, pages: list[Page], unreadable: list[Page],
               provider: str, model: str | None) -> tuple[dict, dict, list]:
    """Fragt das Modell; bei ungültigem JSON ein zweiter Versuch. Fehler werden zu «unklar».

    Gibt (Antwort, Token-Verbrauch aller Versuche, bisheriges Gespräch für Nachfragen) zurück.
    """
    messages = [SystemMessage(SYSTEM_PROMPT), HumanMessage(build_user_prompt(check, legal, pages, unreadable))]
    tokens = {"input": 0, "output": 0}
    try:
        llm = get_llm(provider, model)                  # fehlt ein Schlüssel, wird nur dieser Punkt «unklar»
        reply, used = ask(llm, messages)
        tokens = _add_tokens(tokens, used)
        answer = parse_json_answer(reply)
        if answer is None:
            messages += [AIMessage(reply), HumanMessage(RETRY_PROMPT)]
            reply, used = ask(llm, messages)
            tokens = _add_tokens(tokens, used)
            answer = parse_json_answer(reply)
    except Exception as error:                          # ein Ausfall darf nicht die ganze Prüfung abbrechen
        return {"status": "unklar", "begruendung": f"Modellaufruf fehlgeschlagen ({error.__class__.__name__}). "
                "Bitte erneut prüfen."}, tokens, []
    if answer is None:
        return {"status": "unklar", "begruendung": "Die Antwort des Modells war nicht auswertbar."}, tokens, []
    return answer, tokens, messages + [AIMessage(reply)]


def _add_tokens(a: dict, b: dict) -> dict:
    return {"input": a["input"] + b["input"], "output": a["output"] + b["output"]}


def _to_verdict(check: dict, answer: dict) -> Verdict:
    """Prüfpunkt und Modellantwort zu einem Urteil zusammenführen; Status vereinheitlichen."""
    def text(key: str) -> str:
        return str(answer.get(key) or "").strip()

    status = text("status").lower().replace("ü", "ue").replace(" ", "_").replace("-", "_")
    return Verdict(
        id=check["id"], title=check["title"], area=check["area"], kind=check["kind"],
        weight=check["weight"], legal_refs=check["legal_refs"],
        status=status if status in STATUSES else "unklar",
        beleg=text("beleg").strip(QUOTE_MARKS),           # das Modell setzt manchmal eigene Anführungszeichen
        seite=text("seite"), begruendung=text("begruendung"), verbesserung=text("verbesserung"),
    )


# --- Regeln, die das Urteil des Modells absichern (Bauplan Art. 10 und Art. 2 Abs. 4) ---

def _verify_quote(verdict: Verdict, pages: list[Page]) -> Verdict:
    """Nur echte Zitate behalten. Ein «erfüllt» ohne echten Beleg wird «unklar»."""
    if not verdict["beleg"]:
        return verdict
    quote = verified_quote(verdict["beleg"], pages)
    if quote:
        verdict["beleg"] = quote                        # nur das Stück, das wirklich auf der Seite steht
        return verdict
    verdict["beleg_modell"], verdict["beleg"] = verdict["beleg"], ""   # bleibt zur Nachprüfung im JSON
    if verdict["status"] == "erfuellt":
        verdict["status"] = "unklar"
        verdict["hinweis"] = "Das Zitat des Modells steht nicht im Seitentext; Status auf «unklar» gesetzt."
    else:
        verdict["hinweis"] = "Das Zitat des Modells stand nicht wörtlich im Seitentext und wurde entfernt."
    return verdict


def _ask_for_missing_quote(verdict: Verdict, check: dict, conversation: list, pages: list[Page],
                           provider: str, model: str | None) -> Verdict:
    """Fragt einmal nach der Stelle, wenn ein Urteil sonst an einem fehlenden oder ungenauen Zitat scheitert.

    Zwei Fälle: «fehlt» ohne Zitat bei Prüfpunkten mit «fehlt_ohne_beleg» (würde sonst «unklar» oder
    «nicht_anwendbar») und
    «erfüllt», dessen Zitat nicht wörtlich auf der Seite stand (wurde eben «unklar»).
    Ein echtes Zitat rettet das Urteil; ein erfundenes fällt bei der Belegprüfung wieder durch.
    """
    rejected_fulfilment = (verdict["status_modell"] == "erfuellt" and verdict["status"] == "unklar"
                           and bool(verdict.get("beleg_modell")))
    if not (_unproven_violation(verdict, check) or rejected_fulfilment) or not conversation:
        return verdict
    try:
        reply, used = ask(get_llm(provider, model), conversation + [HumanMessage(QUOTE_PROMPT)])
    except Exception:                                   # ohne Nachfrage greift die Regel «fehlt ohne Beleg»
        return verdict
    verdict["tokens"] = _add_tokens(verdict["tokens"], used)
    quote = verified_quote(str((parse_json_answer(reply) or {}).get("beleg") or ""), pages)
    if quote:
        verdict["beleg"], verdict["status"] = quote, verdict["status_modell"]
        verdict["hinweis"] = "Zitat auf Nachfrage geliefert und im Seitentext gefunden."
    return verdict


# Hier stehen Werbeaussagen, Rabatte und Newsletter-Felder; Rechtstexte erwähnen sie nur allgemein.
# (Eine eigene Newsletter-Seite ist im Footer verlinkt – das Wort «Newsletter» steht also dort.)
TRIGGER_PAGE_TYPES = ("startseite", "footer", "produkt")


def _apply_trigger_rule(verdict: Verdict, check: dict, pages: list[Page]) -> Verdict:
    """Prüfpunkte, die nur bei einer bestimmten Aussage greifen (Klima, Swissness, Rabatte, Newsletter).

    check["ausloeser"] ist ein regulärer Ausdruck aus data/checks.json. In beide Richtungen gilt:
    Was auf der Website steht, entscheidet, ob der Punkt anwendbar ist.
    - «nicht_anwendbar», obwohl ein Auslöser auf Startseite, Footer oder Produktseite steht
      (z.B. «Newsletter abonnieren» im Footer) → «unklar».
    - «fehlt» oder «teilweise», obwohl auf keiner Seite des Prüfpunkts (auch nicht in den Rechtstexten)
      ein Auslöser steht → «nicht_anwendbar»; z.B. galt «Lieferung aus Deutschland oder der Schweiz»
      dem Modell als Swissness-Beleg.
    Der Code entscheidet nie selbst auf «fehlt».
    """
    trigger = check.get("ausloeser")
    if not trigger:
        return verdict
    if verdict["status"] == "nicht_anwendbar":
        found = _first_trigger_line(trigger, pages)
        if found:
            verdict["status"] = "unklar"
            verdict["hinweis"] = (f"Das Modell hielt den Punkt für nicht anwendbar, auf der Website steht aber "
                                  f"«{found[:120]}». Bitte von Hand prüfen.")
    elif verdict["status"] in ("fehlt", "teilweise"):
        if not any(re.search(trigger, p["text"], re.IGNORECASE) for p in pages):
            verdict["status"], verdict["beleg"] = "nicht_anwendbar", ""
            verdict["hinweis"] = ("Das Modell meldete einen Mangel, aber keine Seite enthält eine Aussage, für die "
                                  "dieser Prüfpunkt gilt. Status deshalb «nicht_anwendbar».")
    return verdict


def _first_trigger_line(trigger: str, pages: list[Page]) -> str | None:
    """Die erste Zeile auf Startseite, Footer oder Produktseite, auf die der Auslöser passt."""
    lines = (line for p in pages if p["type"] in TRIGGER_PAGE_TYPES for line in p["text"].splitlines())
    return next((line for line in lines if re.search(trigger, line, re.IGNORECASE)), None)


def _unproven_violation(verdict: Verdict, check: dict) -> bool:
    """«fehlt» ohne Zitat bei einem Prüfpunkt, der dafür einen Beleg verlangt (Feld fehlt_ohne_beleg)."""
    return verdict["status"] == "fehlt" and not verdict["beleg"] and bool(check.get("fehlt_ohne_beleg"))


def _apply_no_evidence_rule(verdict: Verdict, check: dict) -> Verdict:
    """Ohne Zitat ist ein «fehlt» nicht bewiesen.

    check["fehlt_ohne_beleg"] (data/checks.json) nennt den Ersatz-Status: «unklar» bei Abläufen (z.B.
    Bestellbestätigung), «nicht_anwendbar» bei Aussage-Prüfpunkten (Klima, Swissness, Streichpreise).
    Fehlt das Feld, bleibt «fehlt» stehen – z.B. bei einem fehlenden Impressum: Was fehlt, lässt sich
    nicht zitieren. Gelernt bei Newsletter und Cookies: Dort ist gerade das Fehlende der Verstoss.
    """
    if _unproven_violation(verdict, check):
        verdict["status"] = check["fehlt_ohne_beleg"]
        verdict["hinweis"] = (f"Das Modell meldete «fehlt», ohne eine Stelle zu zitieren. Ohne Beleg ist kein "
                              f"Verstoss bewiesen; Status deshalb «{verdict['status']}».")
    return verdict


def _apply_unreadable_rule(verdict: Verdict, readable: list[Page], unreadable: list[Page]) -> Verdict:
    """Ist eine Seite des Prüfpunkts nicht einsehbar, ist ein «fehlt» ohne Zitat nicht bewiesen: «unklar».

    Häufigster Fall: der Checkout, den der Compliance-Check bei echten Shops nie öffnet. Ebenso
    Seiten, die ihren Inhalt per JavaScript laden (z.B. eine eingebettete Datenschutzerklärung).
    Gibt es vom selben Typ eine lesbare Seite (z.B. die Datenschutzerklärung neben einer leeren
    Cookie-Seite), zählt die unlesbare nicht. Ist die Hauptseite selbst nicht lesbar, wurde das
    Modell gar nicht erst gefragt (_unreadable_main_page). Regel 4 läuft vorher; diese Regel betrifft
    darum nur Prüfpunkte ohne «fehlt_ohne_beleg».
    """
    unreadable = [p for p in unreadable if not any(r["type"] == p["type"] for r in readable)]
    if verdict["status"] != "fehlt" or verdict["beleg"] or not unreadable:
        return verdict
    verdict["status"] = "unklar"
    hidden = "; ".join(f"«{p['type']}» ({p.get('reason', 'nicht lesbar')})" for p in unreadable)
    verdict["hinweis"] = f"Auf den lesbaren Seiten nicht gefunden. Nicht einsehbar war: {hidden}. Bitte dort prüfen."
    return verdict


# --- Knoten 4 und 5: Score und Bericht (ohne Sprachmodell) ---------------------------

def score_berechnen(state: PruefState) -> dict:
    return {"score": compute_score(state["results"])}


def bericht(state: PruefState) -> dict:
    model = state["model"] or settings(state["provider"])[0]
    order = {check["id"]: i for i, check in enumerate(CHECKS)}
    verdicts = sorted(state["results"], key=lambda v: order[v["id"]])
    usage = usage_of(verdicts, model)
    protocol = audit_trail(state["provider"], model)
    report = render_report(state["source"], model, state["pages"], verdicts, state["score"], usage)
    return {"report": report + "\n" + render_audit_trail(protocol) + "\n", "protocol": protocol}


def usage_of(verdicts: list[Verdict], model: str) -> dict:
    """Gesamtverbrauch einer Prüfung und Kosten zum Listenpreis (None bei lokalem Modell)."""
    tokens = {"input": 0, "output": 0}
    for verdict in verdicts:
        tokens = _add_tokens(tokens, verdict.get("tokens", {"input": 0, "output": 0}))
    return {**tokens, "cost_usd": cost_usd(model, tokens)}


# --- Graph zusammenbauen -----------------------------------------------------------

def build_graph():
    graph = StateGraph(PruefState)
    graph.add_node("seiten_laden", seiten_laden)
    graph.add_node("seiten_zuordnen", seiten_zuordnen)
    graph.add_node("pruefen", pruefen)
    graph.add_node("score_berechnen", score_berechnen)
    graph.add_node("bericht", bericht)

    graph.add_edge(START, "seiten_laden")
    graph.add_edge("seiten_laden", "seiten_zuordnen")
    graph.add_conditional_edges("seiten_zuordnen", verteilen, ["pruefen"])
    graph.add_edge("pruefen", "score_berechnen")
    graph.add_edge("score_berechnen", "bericht")
    graph.add_edge("bericht", END)
    return graph.compile()


# --- Ausführen: streamen, speichern, auf der Kommandozeile zeigen ----------------------

def stream_check(source: str, provider: str = "apertus", model: str | None = None,
                 with_legal_text: bool = True) -> Iterator[dict]:
    """Führt die Prüfung aus und meldet jeden Fortschritt als Ereignis.

    Ereignisse (in dieser Reihenfolge):
      {"event": "seiten", "pages": [...]}         nachdem die Seiten zugeordnet sind
      {"event": "urteil", "verdict": {...}}       18 Mal, sobald ein Prüfpunkt fertig ist
      {"event": "fertig", "result": {...}}        am Schluss, mit Score, Bericht und Dauer
    Genutzt von der Kommandozeile (run_check) und der Oberfläche (app.py).
    """
    started = time.time()
    initial = {"source": source, "provider": provider, "model": model,
               "with_legal_text": with_legal_text, "results": []}
    pages, verdicts, score, report, protocol = [], [], {}, "", {}

    for update in build_graph().stream(initial, {"max_concurrency": MAX_PARALLEL}, stream_mode="updates"):
        for node, data in update.items():
            if node == "seiten_zuordnen":
                pages = data["pages"]
                yield {"event": "seiten", "pages": pages}
            elif node == "pruefen":
                verdicts += data["results"]
                yield {"event": "urteil", "verdict": data["results"][0]}
            elif node == "score_berechnen":
                score = data["score"]
            elif node == "bericht":
                report, protocol = data["report"], data["protocol"]

    model_name = model or settings(provider)[0]
    yield {"event": "fertig", "result": {
        "source": source,
        "model": model_name,
        "with_legal_text": with_legal_text,
        "seconds": round(time.time() - started, 1),
        "usage": usage_of(verdicts, model_name),
        "score": score,
        "report": report,
        "protocol": protocol,
        "results": verdicts,
        # mit dem gelesenen Text: so lässt sich jedes Urteil später an der Quelle nachprüfen
        "pages": [{"type": p["type"], "url": p["url"], "unreadable": p.get("unreadable", False),
                   "reason": p.get("reason", ""), "text": p["text"]} for p in pages],
    }}


def save_result(result: dict, variant: str = ""):
    """Schreibt Bericht (.md) und Urteile (.json) nach output/ und gibt den Pfad des Berichts zurück.

    variant trennt Messläufe, z.B. «lauf2» oder «ohne-gesetz», damit sie normale Ergebnisse nicht überschreiben.
    """
    report_file, json_file = output_paths(result["source"], result["model"], variant)
    report_file.parent.mkdir(parents=True, exist_ok=True)
    report_file.write_text(result["report"], encoding="utf-8")
    data = {key: value for key, value in result.items() if key != "report"}
    json_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return report_file


def run_check(source: str, provider: str = "apertus", model: str | None = None, verbose: bool = True,
              with_legal_text: bool = True, variant: str = "") -> dict:
    """Prüft einen Shop, speichert das Ergebnis und gibt es zurück (Kommandozeile und Messung)."""
    for event in stream_check(source, provider, model, with_legal_text):
        if verbose and event["event"] == "seiten":
            print(f"  {len(event['pages'])} Seiten: {', '.join(p['type'] for p in event['pages'])}")
        elif verbose and event["event"] == "urteil":
            print(f"  {event['verdict']['status']:16} {event['verdict']['title']}")
        elif event["event"] == "fertig":
            result = event["result"]

    report_file = save_result(result, variant)
    if verbose:
        s, u = result["score"], result["usage"]
        cost = f" · USD {u['cost_usd']:.4f}" if u["cost_usd"] is not None else ""
        print(f"  → Score {s['score']} ({s['ampel']}) in {result['seconds']} s"
              f" · {u['input'] + u['output']} Tokens{cost}"
              f" · {report_file}")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Prüft einen Online-Shop nach Schweizer Recht.")
    parser.add_argument("source", help="Shop-URL oder testshop:<name>")
    parser.add_argument("--provider", default="apertus", choices=["apertus", "litellm"])
    parser.add_argument("--model", default=None, help="anderes Modell, z.B. swiss-ai/apertus-v1.5-70b")
    parser.add_argument("--bericht", action="store_true", help="den ganzen Bericht am Schluss ausgeben")
    args = parser.parse_args()
    print(f"Prüfe {args.source} …")
    result = run_check(args.source, args.provider, args.model)
    if args.bericht:
        print("\n" + result["report"])
