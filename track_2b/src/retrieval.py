"""Schritt 3 – Suchen (optional): findet passende Gesetzespassagen zu einer freien Frage.

Die Prüfung selbst braucht diese Suche nicht; sie holt den Gesetzestext exakt über
laws.py. Die Suche ist für freie Fragen und einen späteren Ausbau gedacht und braucht
die Zusatzpakete aus requirements-search.txt.

Zwei Suchverfahren laufen parallel, weil jedes die Schwäche des anderen ausgleicht:

  BM25        sucht nach gleichen Wörtern. Stark bei Fachbegriffen
              («Detailpreis»), blind für Synonyme.
  Embeddings  vergleichen die Bedeutung als Vektoren. Finden auch
              «Artenvielfalt» für «Biodiversität» und arbeiten über Sprachen hinweg.

Beide Ranglisten werden mit Reciprocal Rank Fusion (RRF) zusammengeführt:
Jede Passage bekommt pro Liste 1 / (60 + Rang) Punkte, die Summe entscheidet.

Das Embedding-Modell läuft lokal; die Vektoren werden beim ersten Aufruf
berechnet und in data/processed/embeddings.npy gespeichert.

Aufruf:  make index, danach z.B.
         python src/retrieval.py "Preis in Franken inklusive Mehrwertsteuer"
Bauplan: docs/bauplan.html, Art. 7
"""

import json
import re
import sys
from dataclasses import dataclass

import numpy as np
from rank_bm25 import BM25Okapi

from config import CHUNKS_FILE, EMBEDDING_MODEL, EMBEDDINGS_FILE

RRF_K = 60            # Dämpfung in 1 / (K + Rang); 60 ist der übliche Wert aus der Literatur
CANDIDATES = 50       # wie viele Treffer pro Verfahren in die Fusion eingehen


@dataclass
class Hit:
    passage: dict      # eine Zeile aus chunks.jsonl
    score: float       # RRF-Punkte, höher ist besser

    @property
    def ref(self) -> str:
        return self.passage["ref"]


def tokenize(text: str) -> list[str]:
    return re.findall(r"\w+", text.lower())


class Retriever:
    def __init__(self):
        self.passages = [json.loads(line) for line in CHUNKS_FILE.open(encoding="utf-8")]
        self.bm25 = BM25Okapi([tokenize(p["text"]) for p in self.passages])
        self._model = None
        self.vectors = self._load_or_build_vectors()

    # --- Embeddings ------------------------------------------------------------

    @property
    def model(self):
        """Lädt das Embedding-Modell erst, wenn es gebraucht wird."""
        if self._model is None:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(EMBEDDING_MODEL)
        return self._model

    def _load_or_build_vectors(self) -> np.ndarray:
        if EMBEDDINGS_FILE.exists():
            vectors = np.load(EMBEDDINGS_FILE)
            if len(vectors) == len(self.passages):       # passt zu den aktuellen Passagen
                return vectors

        print(f"Berechne Vektoren für {len(self.passages)} Passagen …", file=sys.stderr)
        # e5-Modelle erwarten die Präfixe «passage: » und «query: »
        vectors = self.model.encode(
            ["passage: " + p["text"] for p in self.passages],
            batch_size=64, normalize_embeddings=True, show_progress_bar=True,
        ).astype(np.float32)
        np.save(EMBEDDINGS_FILE, vectors)
        return vectors

    # --- Suche -----------------------------------------------------------------

    def search(self, query: str, k: int = 5, lang: str = "de", laws: list[str] | None = None) -> list[Hit]:
        """Die k besten Passagen, optional beschränkt auf Sprache und Gesetze (z.B. ["UWG", "PBV"])."""
        allowed = np.array([
            p["lang"] == lang and (laws is None or p["law"] in laws) for p in self.passages
        ])
        allowed_idx = np.flatnonzero(allowed)
        if allowed_idx.size == 0:
            return []

        keyword_scores = self.bm25.get_scores(tokenize(query))[allowed_idx]
        query_vector = self.model.encode(["query: " + query], normalize_embeddings=True)[0]
        meaning_scores = self.vectors[allowed_idx] @ query_vector      # Kosinus-Ähnlichkeit

        fused: dict[int, float] = {}
        for scores in (keyword_scores, meaning_scores):
            ranking = np.argsort(-scores)[:CANDIDATES]
            for rank, local_idx in enumerate(ranking, start=1):
                passage_idx = int(allowed_idx[local_idx])
                fused[passage_idx] = fused.get(passage_idx, 0.0) + 1.0 / (RRF_K + rank)

        best = sorted(fused.items(), key=lambda item: -item[1])[:k]
        return [Hit(self.passages[i], score) for i, score in best]


if __name__ == "__main__":
    question = " ".join(sys.argv[1:]) or "Preis in Franken inklusive Mehrwertsteuer"
    for hit in Retriever().search(question):
        print(f"\n[{hit.score:.4f}] {hit.ref}")
        print("  ", hit.passage["text"].split("\n", 1)[1][:240], "…")
