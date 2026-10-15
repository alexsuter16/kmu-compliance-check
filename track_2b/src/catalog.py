"""Der Prüfkatalog als Python-Objekte – gelesen aus data/checks.json.

Alle Module holen Prüfpunkte, Seitentypen und Score-Regeln von hier, statt die
Datei selbst zu lesen. So gibt es genau eine Stelle, an der der Katalog geladen wird.

Bauplan: docs/bauplan.html, Art. 8
"""

import json

from config import CHECKS_FILE

_CATALOG = json.loads(CHECKS_FILE.read_text(encoding="utf-8"))

CHECKS: list[dict] = _CATALOG["checks"]                     # die 18 Prüfpunkte, in Berichtsreihenfolge
CHECK_BY_ID: dict[str, dict] = {check["id"]: check for check in CHECKS}
PAGE_TYPES: dict[str, list[str]] = _CATALOG["page_types"]    # Seitentyp → Stichwörter in URL oder Linktext
SCORING: dict = _CATALOG["scoring"]                         # Punkte pro Status, Ampelgrenzen
