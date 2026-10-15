"""Schritt 6 – Score: rechnet aus den 18 Urteilen einen Score von 0 bis 100.

Bewusst ohne Sprachmodell: Gleiche Urteile ergeben immer den gleichen Score.
Punkte pro Status, Ampelgrenzen und Gewichte stehen in data/checks.json.

    Score = Σ (Gewicht × Punkte) ÷ Σ Gewicht × 100      («nicht_anwendbar» zählt nicht)

Bauplan: docs/bauplan.html, Art. 11
"""

from catalog import SCORING

# Die fünf möglichen Urteile über einen Prüfpunkt
STATUSES = ("erfuellt", "teilweise", "fehlt", "unklar", "nicht_anwendbar")

# Diese Urteile zählen als Mangel – im Bericht und in der Messung (Art. 12)
DEFECT = {"fehlt", "teilweise"}


def compute_score(verdicts: list[dict]) -> dict:
    points = SCORING["status_points"]
    counted = [v for v in verdicts if v["status"] not in SCORING["excluded_status"]]
    weight_sum = sum(v["weight"] for v in counted)
    point_sum = sum(v["weight"] * points.get(v["status"], 0.5) for v in counted)
    score = round(point_sum / weight_sum * 100) if weight_sum else 100

    lights = SCORING["traffic_light"]
    light = "gruen" if score >= lights["gruen"] else "gelb" if score >= lights["gelb"] else "rot"
    return {
        "score": score,
        "ampel": light,
        "punkte": point_sum,
        "gewichte": weight_sum,
        "muss_maengel": sum(v["status"] == "fehlt" and v["kind"] == "muss" for v in verdicts),
        "kann_maengel": sum(v["status"] == "fehlt" and v["kind"] == "kann" for v in verdicts),
        "teilweise_unklar": sum(v["status"] in ("teilweise", "unklar") for v in verdicts),
    }
