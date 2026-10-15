"""Zentrale Einstellungen: alle Pfade und Umgebungsvariablen an einem Ort.

Jedes andere Modul importiert von hier, statt eigene Pfade zu bauen.
Erklärung im Bauplan: docs/bauplan.html, Art. 15.
"""

import os
import re
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

# --- Ordner ------------------------------------------------------------------
PROJECT_DIR = Path(__file__).resolve().parent.parent    # track_2b/
DATA_DIR = PROJECT_DIR / "data"
LAWS_DIR = DATA_DIR / "laws"                            # Rohdaten, von download_data.py
PROCESSED_DIR = DATA_DIR / "processed"                  # abgeleitet, von ingest.py / retrieval.py
TESTSHOPS_DIR = DATA_DIR / "testshops"                  # erfundene Shops mit Lösungsblatt
OUTPUT_DIR = PROJECT_DIR / "output"                     # Berichte und Messungen (nur lokal)

# --- Dateien -----------------------------------------------------------------
SOURCES_FILE = DATA_DIR / "sources.json"                # welche Gesetze, von wo
CHECKS_FILE = DATA_DIR / "checks.json"                  # der Prüfkatalog
CHUNKS_FILE = PROCESSED_DIR / "chunks.jsonl"            # Gesetzespassagen, eine pro Zeile
EMBEDDINGS_FILE = PROCESSED_DIR / "embeddings.npy"      # Vektoren zu den Passagen

# --- Umgebungsvariablen (aus track_2b/.env, siehe .env.example) ----------------
load_dotenv(PROJECT_DIR / ".env")
EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "intfloat/multilingual-e5-small")


def _safe(name: str) -> str:
    """Ein Name, der als Datei- oder Ordnername taugt."""
    return re.sub(r"[^\w.-]", "_", name)


def model_stem(model: str) -> str:
    """Kurzname eines Modells für Dateinamen: «swiss-ai/apertus-v1.5-8b» → «apertus-v1.5-8b»."""
    return _safe(model.split("/")[-1])


def output_paths(source: str, model: str, variant: str = "") -> tuple[Path, Path]:
    """Wo Bericht (.md) und Urteile (.json) einer Prüfung liegen.

    Beispiel: («testshop:bergwiese», «swiss-ai/apertus-v1.5-8b», «lauf2»)
           → output/bergwiese/apertus-v1.5-8b__lauf2.md und .json
    """
    shop = source.split(":", 1)[1] if source.startswith("testshop:") else urlparse(source).netloc or source
    stem = model_stem(model) + (f"__{_safe(variant)}" if variant else "")
    folder = OUTPUT_DIR / _safe(shop)
    return folder / f"{stem}.md", folder / f"{stem}.json"
