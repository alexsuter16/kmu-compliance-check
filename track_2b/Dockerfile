# KMU-Compliance-Check – startet die Oberfläche auf Port 7860.
# Bauen und starten: make run  (Bauplan Art. 16a)

FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    GRADIO_ANALYTICS_ENABLED=False \
    GRADIO_SERVER_NAME=0.0.0.0 \
    GRADIO_SERVER_PORT=7860

WORKDIR /app

# 1. Pakete (eigene Schicht, damit Code-Änderungen keinen Neu-Download auslösen)
COPY requirements.txt .
RUN pip install -r requirements.txt

# 2. Code und Daten – ausdrücklich einzeln, damit .env nie im Image landen kann
COPY src/ src/
COPY data/ data/

# 3. Gesetze liegen im Repository; die Passagen entstehen hier, ohne Internet.
#    Danach ein eigener Nutzer ohne Root-Rechte, der nur in output/ schreiben darf.
RUN python src/ingest.py \
 && useradd --create-home --uid 10001 pruefer \
 && mkdir -p output && chown pruefer output

USER pruefer
EXPOSE 7860
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:7860/', timeout=4)"

CMD ["python", "src/app.py"]
