"""Belegprüfung: Steht das Zitat des Modells wirklich auf der geprüften Seite?

Sprachmodelle erfinden manchmal Zitate. Darum vergleicht gewöhnlicher Code jedes
Zitat mit dem Seitentext. Kleine Unterschiede (Anführungszeichen, Markdown,
Leerzeichen, Gross-/Kleinschreibung) werden vorher ausgeglichen; Auslassungen
mit «…» sind erlaubt.

Oft verpackt das Modell ein echtes Zitat in eigene Worte, z.B.
    Startseite: "heilt Gelenkschmerzen in 7 Tagen."
    „nur noch 2 Stück!" als Hinweis auf künstliche Verknappung
Darum werden auch die Teile in Anführungszeichen und der Text ohne Vorsatz geprüft;
behalten wird nur das Stück, das wirklich auf der Seite steht.

Fasst das Modell mehrere Zeilen zusammen («Firma, Strasse, Ort, E-Mail»), gilt das Zitat,
wenn jeder Teil als ganze Wörter auf derselben Seite steht.

Manchmal ändert das Modell beim Abschreiben ein einzelnes Wort («Mit der Bestellung …»
statt «Mit Ihrer Bestellung …»). Stimmen mindestens 90 % der Wörter mit einer Stelle der
Seite überein, gilt das Zitat als gefunden – übernommen wird dann der Wortlaut der Seite.

Bauplan: docs/bauplan.html, Art. 10 Abs. 3
"""

import re
from difflib import SequenceMatcher

MIN_PART_CHARS = 12        # kürzere Bruchstücke zwischen «…» sind zu unspezifisch zum Vergleichen …
MIN_EXACT_CHARS = 6        # … ein kurzes Zitat wie «CHF 119.00» oder «MUSTER AG» muss als ganze Wörter passen
MAX_QUOTE_CHARS = 200      # so lang darf «beleg» laut SYSTEM_PROMPT sein
QUOTE_MARKS = "\"'„“”«»"  # Anführungszeichen, die das Modell um ein Zitat setzt
MIN_FUZZY_WORDS = 8        # erst ab dieser Länge darf ein Zitat leicht abweichen …
FUZZY_RATIO = 0.9          # … und dann muss es zu mindestens 90 % Wort für Wort übereinstimmen


def normalize(text: str) -> str:
    """Vergleichsform: klein, ohne Anführungszeichen, Markdown und unsichtbare Zeichen, einheitliche Leerzeichen."""
    text = text.lower()
    text = re.sub(r"[\u200b-\u200d\u2060\ufeff\u00ad]", "", text)  # unsichtbare Zeichen aus dem HTML
    text = re.sub(r"[«»„“”\"'’`*#_>\[\]]", "", text)        # Anführungszeichen und Markdown
    text = re.sub(r"[–—]", "-", text)
    text = re.sub(r"\bch\s?-\s?(?=\d{4}\b)", "", text)          # «CH-8953 Dietikon» = «8953 Dietikon»
    text = re.sub(r"[,;/·|]", " ", text)                    # «Graben 33, 5000 Aarau» = zwei Zeilen der Seite
    return re.sub(r"\s+", " ", text).strip(" .…")


# Text in "…", „…“ (auch mit ” oder " geschlossen), «…» oder “…”
QUOTED_PARTS = re.compile(r'"([^"]+)"|„([^“”"]+)[“”"]|«([^»]+)»|“([^”]+)”')
LABEL_PREFIX = re.compile(r"^\s*[\w äöüÄÖÜ-]{3,25}:\s*")     # «Startseite: …», «Impressum: …»


def quote_found(quote: str, pages: list[dict]) -> bool:
    """Auslassungen («…», «...») teilen das Zitat; jeder Teil ab MIN_PART_CHARS muss auf den Seiten stehen."""
    haystack = normalize(" ".join(page["text"] for page in pages))
    parts = [part.strip() for part in re.split(r"\.\.\.|…", normalize(quote)) if len(part.strip()) >= MIN_PART_CHARS]
    return all(part in haystack for part in parts or [normalize(quote)])


def short_quote_found(quote: str, pages: list[dict]) -> bool:
    """Ein kurzes Zitat («CHF 119.00») zählt nur als ganze Wörter: «CHF 19.00» steckt nicht in «CHF 119.00»."""
    haystack = normalize(" ".join(page["text"] for page in pages))
    return re.search(rf"(?<!\w){re.escape(normalize(quote))}(?!\w)", haystack) is not None


def verified_quote(quote: str, pages: list[dict]) -> str | None:
    """Das Stück des Zitats, das wirklich auf einer Seite steht – oder None.

    Kandidaten: die Teile in Anführungszeichen (am genausten), das Zitat ohne Vorsatz wie
    «Startseite:» und das ganze Zitat. Für sie gilt, in dieser Reihenfolge:
      1. wörtlich (kurze Zitate ab MIN_EXACT_CHARS als ganze Wörter),
      2. fast wörtlich (closest_passage; zurück kommt der Wortlaut der Seite),
      3. Teil für Teil auf derselben Seite (all_parts_on_one_page).
    """
    candidates = [next(g for g in match.groups() if g) for match in QUOTED_PARTS.finditer(quote)]
    candidates += [LABEL_PREFIX.sub("", quote), quote]
    candidates = [c.strip().strip(QUOTE_MARKS).strip() for c in candidates]
    for candidate in candidates:
        if _found_word_for_word(candidate, pages):
            return candidate
    long_candidates = [c for c in candidates if len(c) >= MIN_PART_CHARS]
    for find in (closest_passage, all_parts_on_one_page):
        for candidate in long_candidates:
            if found := find(candidate, pages):
                return found
    return None


def _found_word_for_word(candidate: str, pages: list[dict]) -> bool:
    if len(candidate) >= MIN_PART_CHARS:
        return quote_found(candidate, pages)
    return len(candidate) >= MIN_EXACT_CHARS and short_quote_found(candidate, pages)


def all_parts_on_one_page(quote: str, pages: list[dict]) -> str | None:
    """Ein Zitat aus mehreren Zeilen oder Sätzen («Muster AG, Seestrasse 1, 8000 Zürich, info@muster.example»):
    Stehen alle Teile als ganze Wörter auf derselben Seite, gilt es – mit «…» zwischen den Teilen.

    Das Modell überspringt dabei manchmal einen Satz und bricht bei 200 Zeichen mitten im Wort ab
    («… gilt Fraue»); das angeschnittene letzte Wort zählt darum nicht mit.
    """
    if len(quote) >= MAX_QUOTE_CHARS - 10:              # an der Längengrenze abgebrochen
        quote = re.sub(r"\s+\S*$", "", quote)
    # Teile: getrennt durch Komma, Semikolon, Zeilenumbruch, Auslassung oder Satzende
    pieces = re.split(r"[,;\n]|\.\.\.|…|(?<=[.!?])\s+", quote)
    parts = [p.strip() for p in pieces if len(p.strip()) >= MIN_EXACT_CHARS]
    if len(parts) < 2:
        return None
    for page in pages:
        if all(short_quote_found(part, [page]) for part in parts):
            return " … ".join(parts)
    return None


def closest_passage(quote: str, pages: list[dict]) -> str | None:
    """Die Stelle einer Seite, die fast wörtlich dem Zitat entspricht (≥ FUZZY_RATIO) – im Wortlaut der Seite."""
    quote_words = normalize(quote).split()
    if len(quote_words) < MIN_FUZZY_WORDS:
        return None
    for page in pages:
        words = page["text"].split()
        normalized = [normalize(word) for word in words]
        for start in range(len(words) - len(quote_words) + 1):
            window = normalized[start:start + len(quote_words)]
            if SequenceMatcher(None, quote_words, window).ratio() >= FUZZY_RATIO:
                return " ".join(words[start:start + len(quote_words)])
    return None
