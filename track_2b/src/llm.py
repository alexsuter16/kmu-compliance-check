"""Sprachmodelle: ein einheitlicher Zugang zu Apertus und zum Vergleichsmodell.

Beide Anbieter sprechen die OpenAI-Schnittstelle. Darum genügt eine Klasse
(ChatOpenAI); nur Adresse, Modellname und Schlüssel unterscheiden sich.

  apertus   Apertus 1.5 – Pflicht im Hackathon. Variablen LLM_NAME,
            LLM_BASE_URL, LLM_API_KEY (Namen von Hack Apertus vorgegeben).
  litellm   LiteLLM-Proxy, z.B. gpt-oss-120b – zum Entwickeln und als Vergleich.

Verbindungstest:  python src/llm.py apertus    (oder: litellm)
Bauplan: docs/bauplan.html, Art. 14
"""

import json
import os
import re
import sys

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

import config  # noqa: F401  (lädt .env)

# Welche Umgebungsvariablen gehören zu welchem Anbieter: (Modell, Adresse, Schlüssel)
PROVIDERS = {
    "apertus": ("LLM_NAME", "LLM_BASE_URL", "LLM_API_KEY"),
    "litellm": ("LITELLM_MODEL", "LITELLM_BASE_URL", "LITELLM_API_KEY"),
}

# Public AI verlangt einen eigenen User-Agent; andere Anbieter stört er nicht.
HEADERS = {"User-Agent": "kmu-compliance-check/0.1"}

# Listenpreise von Public AI in USD pro Million Tokens (Eingabe, Ausgabe), Stand Oktober 2026.
# Ein lokal betriebenes Modell kostet pro Aufruf nichts (nur Strom und Hardware).
PRICES_USD_PER_MILLION = {
    "swiss-ai/apertus-v1.5-8b": (0.10, 0.20),
    "swiss-ai/apertus-v1.5-70b": (0.82, 2.92),
}


def settings(provider: str) -> tuple[str, str, str]:
    """(Modell, Adresse, Schlüssel) eines Anbieters aus der Umgebung."""
    names = PROVIDERS[provider]
    missing = [name for name in names if not os.environ.get(name)]
    if missing:
        raise RuntimeError(f"Für «{provider}» fehlt in .env: {', '.join(missing)} (Vorlage: .env.example)")
    return tuple(os.environ[name] for name in names)


def get_llm(provider: str = "apertus", model: str | None = None, temperature: float = 0.0) -> ChatOpenAI:
    """Ein LangChain-Chatmodell. temperature=0 macht die Prüfungen reproduzierbar.

    model überschreibt den Modellnamen aus .env, z.B. "swiss-ai/apertus-v1.5-70b".
    """
    default_model, base_url, api_key = settings(provider)
    return ChatOpenAI(model=model or default_model, base_url=base_url, api_key=api_key,
                      temperature=temperature, max_tokens=1500, max_retries=4,
                      timeout=120, default_headers=HEADERS)


def ask(llm: ChatOpenAI, messages: list) -> tuple[str, dict]:
    """Ein Modellaufruf. Gibt (Antworttext, Token-Verbrauch) zurück.

    Fängt eine Eigenheit von Public AI ab: Einzelne Server lehnen die System-Nachricht
    manchmal ab («only accepts a system message … as a plain string»). Dann geht dieselbe
    Anfrage als reine User-Nachricht.

    Bewusst ohne JSON-Modus (response_format): Bei Public AI schrieb Apertus darin bis zur
    Längengrenze weiter. Kaputtes JSON fängt parse_json_answer() ab, sonst fragt pipeline.py nach.
    """
    try:
        reply = llm.invoke(messages)
    except Exception as error:
        if "system message" not in str(error):
            raise
        merged = "\n\n".join(m.content for m in messages if isinstance(m, (SystemMessage, HumanMessage)))
        reply = llm.invoke([HumanMessage(merged)])
    usage = reply.usage_metadata or {}
    return reply.content, {"input": usage.get("input_tokens", 0), "output": usage.get("output_tokens", 0)}


def cost_usd(model: str, tokens: dict) -> float | None:
    """Kosten eines Verbrauchs zum Listenpreis; None, wenn für das Modell kein Preis bekannt ist."""
    if model not in PRICES_USD_PER_MILLION:
        return None
    price_in, price_out = PRICES_USD_PER_MILLION[model]
    return (tokens["input"] * price_in + tokens["output"] * price_out) / 1_000_000


# Deutsche Anführungszeichen, die das Modell mit einem geraden " schliesst: „nur noch 2 Stück!"
# Das gerade " beendet in JSON den Text zu früh; es wird durch das passende “ ersetzt.
GERMAN_QUOTE_CLOSED_STRAIGHT = re.compile(r'„([^"“”„\n]{1,200})"')


def parse_json_answer(text: str) -> dict | None:
    """Das JSON-Objekt aus einer Modellantwort, auch wenn Text oder ```json drumherum steht."""
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None
    for candidate in (match.group(0), GERMAN_QUOTE_CLOSED_STRAIGHT.sub(r"„\1“", match.group(0))):
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    return None


if __name__ == "__main__":
    provider = sys.argv[1] if len(sys.argv) > 1 else "apertus"
    model, _, _ = settings(provider)
    reply = get_llm(provider).invoke("Antworte in einem Satz: Welches Modell bist du?")
    print(f"{provider} ({model}): {reply.content}")
