# Alle Befehle des Projekts. Aufruf im Ordner track_2b/, z.B. `make run`.
# Bauplan: docs/bauplan.html, Art. 16

PYTHON = .venv/bin/python
IMAGE  = kmu-compliance-check
PORT  ?= 7860
SHOP  ?= testshop:bergwiese

# Schlüssel für Docker: aus .env (lokal) und/oder aus der Umgebung (Jury).
# -e NAME übernimmt eine gesetzte Umgebungsvariable und hat Vorrang vor .env.
DOCKER_ENV = $(if $(wildcard .env),--env-file .env) -e LLM_NAME -e LLM_BASE_URL -e LLM_API_KEY

.PHONY: run demo build setup setup-search data index search check eval test app report

# --- Für die Jury: alles in Docker ----------------------------------------------

# Baut das Image und startet die Oberfläche auf http://localhost:7860 (Ctrl-C beendet)
run: build
	@echo "→ Oberfläche: http://localhost:$(PORT)"
	docker run --rm --init -p $(PORT):7860 $(DOCKER_ENV) $(IMAGE)

# Prüft einen Shop ohne Oberfläche und gibt den Bericht aus, z.B. `make demo SHOP=testshop:velowerk`
demo: build
	docker run --rm --init $(DOCKER_ENV) $(IMAGE) python src/pipeline.py $(SHOP) --bericht

build:
	docker build -t $(IMAGE) .

# --- Für die Entwicklung: lokal ohne Docker ---------------------------------------

# Einmalig: virtuelle Umgebung mit allen Paketen für Prüfung und Oberfläche
setup:
	python3 -m venv .venv
	$(PYTHON) -m pip install -r requirements.txt

# Zusätzlich: Suche und Report-PDF (lädt u.a. PyTorch, rund 1 GB)
setup-search: setup
	$(PYTHON) -m pip install -r requirements-search.txt

# Schritt 1: Gesetzestexte von fedlex laden (liegen bereits im Repository)
data:
	$(PYTHON) src/download_data.py

# Schritt 2: Gesetze in Passagen zerlegen (data/processed/chunks.jsonl)
index:
	$(PYTHON) src/ingest.py

# Schritt 3 (optional): Suchindex bauen und ausprobieren – braucht `make setup-search`
search: index
	$(PYTHON) src/retrieval.py "Preis in Franken inklusive Mehrwertsteuer"

# Einen Shop prüfen, z.B. `make check SHOP=https://nuvate.ch`
check:
	$(PYTHON) src/pipeline.py $(SHOP)

# Alle Testshops prüfen und mit den Lösungsblättern vergleichen
eval:
	$(PYTHON) src/evaluate.py

# Tests für alles, was ohne Sprachmodell funktioniert (Score, Belegprüfung, Regeln) – ohne Schlüssel
test:
	$(PYTHON) -m unittest discover -s tests -v

# Oberfläche lokal starten: http://localhost:7860
app:
	$(PYTHON) src/app.py

# Technical Report als PDF (max. 6 Seiten) – braucht `make setup-search` und Google Chrome
report:
	$(PYTHON) docs/report_pdf.py
