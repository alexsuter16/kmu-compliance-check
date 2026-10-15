"""Prüfprotokoll: hält fest, womit ein Bericht entstanden ist.

Ein Compliance-Bericht ist nur so viel wert wie seine Nachvollziehbarkeit. Darum
steht in jedem Bericht, gegen welche Gesetzesfassung, mit welchem Modell, welchem
Prüfkatalog und welchem Prompt geprüft wurde. Ändert sich eines davon, ändert sich
der Fingerabdruck – zwei Berichte lassen sich so fair vergleichen.

Bauplan: docs/bauplan.html, Art. 13 lit. m
"""

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import prompts
from config import CHECKS_FILE, PROJECT_DIR, SOURCES_FILE
from llm import settings


def _fingerprint(text: str) -> str:
    """Die ersten 12 Zeichen des SHA-256 – kurz, aber eindeutig genug zum Vergleichen."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def _law_versions() -> dict[str, str]:
    """Gesetz → Fassung (Datum), z.B. {"UWG": "2025-01-01", …}."""
    files = json.loads(SOURCES_FILE.read_text(encoding="utf-8"))["laws"]["files"]
    return {f["law"]: f"{f['version'][:4]}-{f['version'][4:6]}-{f['version'][6:]}" for f in files}


def _code_version() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=PROJECT_DIR,
                              capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unbekannt"


def audit_trail(provider: str, model: str) -> dict:
    catalog = CHECKS_FILE.read_text(encoding="utf-8")
    return {
        "zeitpunkt": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "modell": model,
        "modell_server": urlparse(settings(provider)[1]).netloc,      # nur der Server, nie der Schlüssel
        "temperatur": 0,
        "pruefkatalog": f"{json.loads(catalog)['version']} ({_fingerprint(catalog)})",
        "prompt": _fingerprint(Path(prompts.__file__).read_text(encoding="utf-8")),   # alle Prompt-Texte
        "gesetze": _law_versions(),
        "code": _code_version(),
    }


def render_audit_trail(trail: dict) -> str:
    laws = ", ".join(f"{law} {version}" for law, version in sorted(trail["gesetze"].items()))
    return "\n".join([
        "## Prüfprotokoll",
        f"- Zeitpunkt: {trail['zeitpunkt']}",
        f"- Modell: {trail['modell']} auf {trail['modell_server']}, Temperatur {trail['temperatur']}",
        f"- Prüfkatalog: Version {trail['pruefkatalog']} · Prompt: {trail['prompt']} · Code: {trail['code']}",
        f"- Gesetzesfassungen (fedlex): {laws}",
    ])
