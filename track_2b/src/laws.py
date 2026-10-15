"""Gesetzestext nachschlagen: den Wortlaut einer Fundstelle, z.B. «UWG Art. 3 Abs. 1 lit. s».

Jeder Prüfschritt bekommt seinen Gesetzestext exakt aus data/processed/chunks.jsonl,
ohne die unsichere Suche (Bauplan Art. 7 Abs. 4). Das Modul braucht nur die
Standardbibliothek; darum läuft die Prüfung auch ohne die schweren Suchpakete.

Bauplan: docs/bauplan.html, Art. 7 und Art. 10
"""

import json
from functools import cache

from config import CHUNKS_FILE

MAX_CHARS = 4_000          # mehr Gesetzestext pro Prüfpunkt bringt dem Modell nichts


@cache
def _passages(lang: str) -> tuple[dict, ...]:
    """Alle Passagen einer Sprache, einmal gelesen und dann im Speicher."""
    if not CHUNKS_FILE.exists():
        raise FileNotFoundError(f"{CHUNKS_FILE.name} fehlt – zuerst `python src/ingest.py` (oder `make index`) ausführen.")
    with CHUNKS_FILE.open(encoding="utf-8") as file:
        return tuple(p for line in file if (p := json.loads(line))["lang"] == lang)


def legal_text(refs: list[str], lang: str = "de") -> str:
    """Wortlaut der Fundstellen. «PBV Art. 16» ohne Absatz liefert alle Absätze des Artikels."""
    texts = [p["text"] for ref in refs for p in _passages(lang)
             if p["ref"] == ref or p["ref"].startswith(ref + " ")]
    return "\n\n".join(texts)[:MAX_CHARS]


if __name__ == "__main__":
    print(legal_text(["UWG Art. 3 Abs. 1 lit. s"]))
