"""Messung an echten Shops: Stimmen die Urteile mit einer Prüfung der Live-Website überein?

Die Testshops haben ein Lösungsblatt, echte Shops nicht. Darum wurde jedes Urteil für echte
Shops an der Live-Website nachgeprüft (Audit). Pro Prüfpunkt hält das Audit
fest, welche Status zutreffen (bei strittigen Fällen mehrere). Diese Datei vergleicht ein
Ergebnis des Compliance-Checks damit.

Zwei Gruppen von Shops:
  entwicklung  21 Shops, an denen die Korrekturen entwickelt wurden (Audit nach dem ersten Lauf)
  holdout      10 Shops, die der Check während der Entwicklung nie gesehen hat; ihr Audit
               entstand blind, bevor der Check sie prüfte – das ergibt eine unverzerrte Messung

Das Audit und die Berichte enthalten Inhalte fremder Shops und bleiben lokal:
output/audit[-holdout]/<shop>.json (Audit), output/<shop>/<modell>[__<variante>].json (Ergebnis).

Aufruf:  python src/evaluate_audit.py                      aktuelles Ergebnis, Entwicklungs-Shops
         python src/evaluate_audit.py --variante vor-audit  das Ergebnis vor den Korrekturen
         python src/evaluate_audit.py --gruppe holdout      die nie gesehenen Shops
Ergebnis: output/evaluation/echte-shops[__holdout][__<variante>].md
Bauplan: docs/bauplan.html, Art. 12
"""

import argparse
import json

from config import OUTPUT_DIR
from scoring import DEFECT

AUDIT_DIRS = {"entwicklung": OUTPUT_DIR / "audit", "holdout": OUTPUT_DIR / "audit-holdout"}


def compare(audit: dict, result: dict) -> dict:
    """Zählt Übereinstimmungen, Fehlalarme und übersehene Mängel für einen Shop."""
    measured = {v["id"]: v["status"] for v in result["results"]}
    agree = false_alarms = missed = 0
    for check_id, entry in audit["checks"].items():
        status, acceptable = measured.get(check_id, "unklar"), set(entry["true"])
        agree += status in acceptable
        if status in DEFECT and not acceptable & DEFECT:
            false_alarms += 1                            # Mangel gemeldet, den es auf der Website nicht gibt
        if acceptable <= DEFECT and status not in DEFECT:
            missed += 1                                  # echter Mangel, aber nicht gemeldet
    return {"checks": len(audit["checks"]), "agree": agree, "false_alarms": false_alarms, "missed": missed,
            "score": result["score"]["score"]}


def report_name(group: str, variant: str) -> str:
    """Dateiname der Auswertung, z.B. «echte-shops__holdout» oder «echte-shops__vor-audit»."""
    name = "echte-shops"
    if group == "holdout":
        name += "__holdout"
    if variant:
        name += f"__{variant}"
    return name


def evaluate(variant: str = "", group: str = "entwicklung", model_stem: str = "apertus-v1.5-8b") -> str:
    """Vergleicht für jeden Shop mit Audit das gespeicherte Ergebnis und gibt die Auswertung als Markdown zurück."""
    suffix = f"__{variant}" if variant else ""
    rows = []
    for audit_file in sorted(AUDIT_DIRS[group].glob("*.json")):
        result_file = OUTPUT_DIR / audit_file.stem / f"{model_stem}{suffix}.json"
        if result_file.exists():
            audit = json.loads(audit_file.read_text(encoding="utf-8"))
            rows.append((audit_file.stem, compare(audit, json.loads(result_file.read_text(encoding="utf-8")))))
    return render(f"{group}, {variant or 'aktuell'}", rows)


def render(name: str, rows: list[tuple[str, dict]]) -> str:
    """Gesamtzahlen und eine Zeile pro Shop."""
    total = {key: sum(row[key] for _, row in rows) for key in ("checks", "agree", "false_alarms", "missed")}
    share = total["agree"] / total["checks"] if total["checks"] else 0
    lines = [f"# Echte Shops gegen das Live-Audit: {name}", "",
             f"**Übereinstimmung {share:.0%}** ({total['agree']} von {total['checks']} Urteilen) · "
             f"{total['false_alarms']} Fehlalarme · {total['missed']} übersehene Mängel · {len(rows)} Shops", "",
             "| Shop | Score | übereinstimmend | Fehlalarme | übersehen |", "|---|---:|---:|---:|---:|"]
    lines += [f"| {shop} | {r['score']} | {r['agree']}/{r['checks']} | {r['false_alarms']} | {r['missed']} |"
              for shop, r in rows]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Vergleicht Ergebnisse echter Shops mit dem Live-Audit.")
    parser.add_argument("--variante", default="", help="z.B. «vor-audit» für das Ergebnis vor den Korrekturen")
    parser.add_argument("--gruppe", default="entwicklung", choices=list(AUDIT_DIRS))
    args = parser.parse_args()
    report = evaluate(args.variante, args.gruppe)
    target = OUTPUT_DIR / "evaluation" / f"{report_name(args.gruppe, args.variante)}.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(report, encoding="utf-8")
    print(report)
