"""Schritt 1 – Beschaffen: lädt die Gesetzestexte von fedlex herunter.

Welche Erlasse in welcher Fassung geladen werden, steht in data/sources.json.
Bereits vorhandene Dateien werden übersprungen; das Skript kann also beliebig
oft laufen.

Aufruf:  make data
Bauplan: docs/bauplan.html, Art. 5
"""

import json
import sys
from pathlib import Path

import requests

from config import DATA_DIR, LAWS_DIR, SOURCES_FILE


def law_path(law: dict) -> Path:
    """Ablageort einer Gesetzesdatei, z.B. data/laws/de/UWG_20250101_de.xml."""
    return LAWS_DIR / law["lang"] / f"{law['law']}_{law['version']}_{law['lang']}.xml"


def download(url: str, target: Path) -> bool:
    """Lädt eine Datei herunter. Gibt False zurück, wenn sie schon da war."""
    if target.exists() and target.stat().st_size > 0:
        return False

    response = requests.get(url, timeout=60)
    response.raise_for_status()
    if not response.content.lstrip().startswith(b"<?xml"):
        raise ValueError(f"Keine XML-Datei: {url}")

    # Erst in eine Hilfsdatei schreiben: bricht der Download ab,
    # bleibt keine halbe Datei liegen, die beim nächsten Lauf übersprungen würde.
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_suffix(".part")
    partial.write_bytes(response.content)
    partial.rename(target)
    return True


def main() -> int:
    laws = json.loads(SOURCES_FILE.read_text(encoding="utf-8"))["laws"]["files"]
    failed = 0

    for i, law in enumerate(laws, start=1):
        target = law_path(law)
        try:
            status = "neu " if download(law["url"], target) else "da  "
        except Exception as error:      # weitermachen, Fehler am Schluss melden
            status, failed = f"FEHLER ({error})", failed + 1
        print(f"[{i:2}/{len(laws)}] {status} {target.relative_to(DATA_DIR)}")

    print(f"\n{failed} Download(s) fehlgeschlagen." if failed else "\nAlle Gesetzestexte vorhanden.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
