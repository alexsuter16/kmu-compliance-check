"""Schritt 8 – Messen: vergleicht die Urteile mit den Lösungsblättern der Testshops.

Jeder Testshop in data/testshops/ hat in shop.json den erwarteten Status pro
Prüfpunkt. Gemessen wird, ob ein Mangel erkannt wurde:

    Mangel                = Status «fehlt» oder «teilweise»
    Trefferquote (Recall) = gefundene Mängel ÷ eingebaute Mängel
    Präzision             = echte Mängel ÷ gemeldete Mängel

Bereits vorhandene Ergebnisse in output/ werden wiederverwendet (--neu erzwingt neue Läufe).

Messvarianten (Bauplan Art. 12 Abs. 4):
  --lauf 2           Wiederholung; zeigt, wie stark die Ergebnisse schwanken
  --ohne-gesetz      Prompt ohne Gesetzestext; zeigt, was die Rechtsgrundlagen bringen
  --ohne-regeln      Status, wie ihn das Modell gemeldet hat, vor den Regeln im Code;
                     braucht keine neuen Modellaufrufe

Aufruf:  python src/evaluate.py
         python src/evaluate.py --model swiss-ai/apertus-v1.5-70b
         python src/evaluate.py --ohne-gesetz
Ergebnis: output/evaluation/<modell>.md
Bauplan: docs/bauplan.html, Art. 12
"""

import argparse
import json
from dataclasses import dataclass, field

from catalog import CHECK_BY_ID
from config import OUTPUT_DIR, TESTSHOPS_DIR, model_stem, output_paths
from llm import settings
from pipeline import run_check
from scoring import DEFECT, compute_score

INJECTION_SHOP, INJECTION_CHECK = "baerenstark", "irrefuehrende_angaben"   # Testshop mit versteckter Anweisung


@dataclass
class Deviation:
    """Ein Prüfpunkt, bei dem das System anders urteilt als das Lösungsblatt."""
    shop: str
    check_id: str
    expected: str
    measured: str
    kind: str                 # «übersehen» (Mangel nicht gefunden) oder «Fehlalarm»


@dataclass
class ShopMeasurement:
    """Vergleich eines Testshops mit seinem Lösungsblatt."""
    name: str
    expected_score: int
    measured_score: int
    seconds: float
    tokens: int
    cost_usd: float | None
    found: int = 0            # eingebaute Mängel, die erkannt wurden
    missed: int = 0           # eingebaute Mängel, die übersehen wurden
    false_alarms: int = 0     # gemeldete Mängel, die keine sind
    exact: int = 0            # Prüfpunkte mit genau dem erwarteten Status
    deviations: list[Deviation] = field(default_factory=list)


# --- Einen Testshop vergleichen ----------------------------------------------------

def expected_score(expected: dict[str, str]) -> int:
    """Der Score, den das Lösungsblatt ergeben würde."""
    verdicts = [{**CHECK_BY_ID[check_id], "status": status} for check_id, status in expected.items()]
    return compute_score(verdicts)["score"]


def compare(shop_id: str, meta: dict, result: dict, without_rules: bool = False) -> ShopMeasurement:
    status_key = "status_modell" if without_rules else "status"
    measured = {verdict["id"]: verdict.get(status_key, verdict["status"]) for verdict in result["results"]}
    measured_score = compute_score([{**v, "status": measured[v["id"]]} for v in result["results"]])["score"]
    usage = result.get("usage", {"input": 0, "output": 0, "cost_usd": None})
    m = ShopMeasurement(meta["name"], expected_score(meta["erwartet"]), measured_score, result["seconds"],
                        usage["input"] + usage["output"], usage["cost_usd"])
    for check_id, want in meta["erwartet"].items():
        have = measured.get(check_id, "unklar")
        m.exact += have == want
        if want in DEFECT and have in DEFECT:
            m.found += 1
        elif want in DEFECT:
            m.missed += 1
            m.deviations.append(Deviation(shop_id, check_id, want, have, "übersehen"))
        elif have in DEFECT:
            m.false_alarms += 1
            m.deviations.append(Deviation(shop_id, check_id, want, have, "Fehlalarm"))
    return m


def load_or_run(shop_id: str, provider: str, model: str | None, rerun: bool,
                variant: str = "", with_legal_text: bool = True) -> dict:
    """Vorhandenes Ergebnis aus output/ verwenden oder den Testshop neu prüfen."""
    source = f"testshop:{shop_id}"
    _, json_file = output_paths(source, model or settings(provider)[0], variant)
    if json_file.exists() and not rerun:
        return json.loads(json_file.read_text(encoding="utf-8"))
    print(f"Prüfe {source} {variant} …")
    return run_check(source, provider, model, verbose=False, with_legal_text=with_legal_text, variant=variant)


# --- Bericht über die Messung --------------------------------------------------------

def render_evaluation(title: str, shops: list[ShopMeasurement]) -> str:
    found, missed = sum(s.found for s in shops), sum(s.missed for s in shops)
    false_alarms, exact = sum(s.false_alarms for s in shops), sum(s.exact for s in shops)
    total = len(shops) * len(CHECK_BY_ID)
    recall = found / max(found + missed, 1)
    precision = found / max(found + false_alarms, 1)
    deviations = [d for s in shops for d in s.deviations]
    injection_failed = any(d.shop == INJECTION_SHOP and d.check_id == INJECTION_CHECK for d in deviations)

    summary = (f"**Trefferquote {recall:.0%}** ({found} von {found + missed} eingebauten Mängeln gefunden) · "
               f"**Präzision {precision:.0%}** ({false_alarms} Fehlalarme) · "
               f"genauer Status in {exact} von {total} Fällen ({exact / total:.0%})")
    injection = ("nicht bestanden – Heilversprechen übersehen" if injection_failed
                 else "bestanden – Heilversprechen erkannt")
    costs = [s.cost_usd for s in shops if s.cost_usd is not None]
    usage = (f"Verbrauch pro Shop: Ø {sum(s.tokens for s in shops) / len(shops):,.0f} Tokens".replace(",", "'")
             + (f" · Ø USD {sum(costs) / len(costs):.4f} zum Listenpreis" if costs else " · lokales Modell")
             + f" · Ø {sum(s.seconds for s in shops) / len(shops):.0f} s")

    shop_table = [
        "| Shop | Score erwartet | Score gemessen | Mängel gefunden | Fehlalarme | Status exakt | Sekunden |",
        "|---|---:|---:|---:|---:|---:|---:|",
        *[f"| {s.name} | {s.expected_score} | {s.measured_score} | "
          f"{f'{s.found}/{s.found + s.missed}' if s.found + s.missed else '–'} | {s.false_alarms} | "
          f"{s.exact}/{len(CHECK_BY_ID)} | {s.seconds} |" for s in shops],
    ]
    deviation_table = [
        "| Shop | Prüfpunkt | erwartet | gemessen | Art |",
        "|---|---|---|---|---|",
        *[f"| {d.shop} | {CHECK_BY_ID[d.check_id]['title']} | {d.expected} | {d.measured} | {d.kind} |"
          for d in deviations],
    ]
    sections = [
        f"# Evaluation: {title}",
        summary,
        f"Prompt-Injection-Test (Bärenstark): {injection}",
        usage,
        "## Pro Testshop\n\n" + "\n".join(shop_table),
        "## Abweichungen\n\n" + "\n".join(deviation_table),
    ]
    return "\n\n".join(sections) + "\n"


def evaluate(provider: str, model: str | None, rerun: bool, run: int = 1,
             with_legal_text: bool = True, without_rules: bool = False) -> str:
    model_name = model or settings(provider)[0]
    variant = "ohne-gesetz" if not with_legal_text else (f"lauf{run}" if run > 1 else "")
    shops = []
    for folder in sorted(path for path in TESTSHOPS_DIR.iterdir() if path.is_dir()):
        meta = json.loads((folder / "shop.json").read_text(encoding="utf-8"))
        result = load_or_run(folder.name, provider, model, rerun, variant, with_legal_text)
        shops.append(compare(folder.name, meta, result, without_rules))

    label = "__".join(part for part in (variant, "ohne-regeln" if without_rules else "") if part)
    report = render_evaluation(f"{model_name} {label}".strip(), shops)
    out_file = OUTPUT_DIR / "evaluation" / f"{model_stem(model_name)}{'__' + label if label else ''}.md"
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(report, encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Misst den Compliance-Check an den Testshops.")
    parser.add_argument("--provider", default="apertus", choices=["apertus", "litellm"])
    parser.add_argument("--model", default=None)
    parser.add_argument("--neu", action="store_true", help="alle Testshops neu prüfen")
    parser.add_argument("--lauf", type=int, default=1, help="Nummer einer Wiederholung (2, 3, …)")
    parser.add_argument("--ohne-gesetz", action="store_true", help="Prompt ohne Gesetzestext")
    parser.add_argument("--ohne-regeln", action="store_true", help="Status des Modells vor den Regeln")
    args = parser.parse_args()
    print(evaluate(args.provider, args.model, args.neu, args.lauf, not args.ohne_gesetz, args.ohne_regeln))
