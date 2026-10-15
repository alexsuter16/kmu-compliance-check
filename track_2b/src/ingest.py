"""Schritt 2 – Zerlegen: macht aus den Gesetzestexten zitierbare Passagen.

fedlex liefert jedes Gesetz als XML im Standard «Akoma Ntoso». Der Aufbau ist
immer gleich:

    <article>             Art. 3
      <paragraph>         Abs. 1
        <item>            lit. s
          <item>          Ziff. 1–4 (bleiben im Text von lit. s)

Eine Passage ist die kleinste Einheit, die man zitieren kann: ein Absatz oder,
bei Aufzählungen, ein einzelner Buchstabe. Jede Passage bekommt die
Artikelüberschrift als Kontext mit, damit sie auch allein verständlich ist.

Aufruf:  make index   (Ergebnis: data/processed/chunks.jsonl)
Bauplan: docs/bauplan.html, Art. 6
"""

import json
import re
import xml.etree.ElementTree as ET

from config import CHUNKS_FILE, PROCESSED_DIR, SOURCES_FILE
from download_data import law_path

AKN = "{http://docs.oasis-open.org/legaldocml/ns/akn/3.0}"   # XML-Namensraum von Akoma Ntoso

# Wie Absatz und Buchstabe in der jeweiligen Sprache abgekürzt werden
LABELS = {
    "de": {"paragraph": "Abs.", "item": "lit."},
    "fr": {"paragraph": "al.", "item": "let."},
    "it": {"paragraph": "cpv.", "item": "lett."},
}
REPEALED = re.compile(r"(Aufgehoben|Abrogée?s?|Abrogat[oaie])\.?", re.IGNORECASE)


# --- Text aus dem XML lesen ----------------------------------------------------

def text_of(element: ET.Element | None) -> str:
    """Der lesbare Text eines Elements, ohne Fussnoten."""
    if element is None:
        return ""
    parts: list[str] = []

    def walk(node: ET.Element) -> None:
        if node.tag == AKN + "authorialNote":            # Fussnote: überspringen
            parts.append(node.tail or "")
            return
        parts.append(node.text or "")
        for child in node:
            if child.tag in (AKN + "num", AKN + "item", AKN + "p"):
                parts.append(" ")                       # sonst klebt «unterlässt:1.» zusammen
            walk(child)
        if node is not element:
            parts.append(node.tail or "")

    walk(element)
    return re.sub(r"\s+", " ", "".join(parts)).strip()


def number_of(element: ET.Element) -> str:
    """Die Nummer eines Elements, z.B. «3», «1» oder «s»."""
    raw = text_of(element.find(AKN + "num"))
    return re.sub(r"^(Art\.?|Articolo)\s*", "", raw, flags=re.IGNORECASE).strip().rstrip(".")


# --- Ein Artikel wird zu Passagen ------------------------------------------------

def passages_of_article(article: ET.Element, law: dict) -> list[dict]:
    article_no = number_of(article)
    if not article_no:
        return []
    heading = text_of(article.find(AKN + "heading"))
    labels = LABELS[law["lang"]]

    def passage(ref_suffix: str, body: str, element_id: str) -> dict:
        ref = f"{law['law']} Art. {article_no}{ref_suffix}"          # z.B. «UWG Art. 3 Abs. 1 lit. s»
        return {
            "id": f"{law['law']}_{law['lang']}_{element_id}",
            "ref": ref,
            "law": law["law"],
            "sr": law["sr"],
            "lang": law["lang"],
            "article": article_no,
            "heading": heading,
            "text": f"{ref} – {heading}\n{body}" if heading else f"{ref}\n{body}",
            "source_url": f"https://www.fedlex.admin.ch/eli/{law['eli'].split('/eli/')[1]}/{law['lang']}#{article.get('eId')}",
        }

    paragraphs = article.findall(AKN + "paragraph")

    # Fall 1: Artikel ohne nummerierte Absätze -> eine Passage für den ganzen Artikel
    if not paragraphs:
        body = text_of(article.find(AKN + "content"))
        return [passage("", body, article.get("eId", article_no))] if body else []

    result = []
    for paragraph in paragraphs:
        paragraph_no = number_of(paragraph)
        abs_suffix = f" {labels['paragraph']} {paragraph_no}" if paragraph_no else ""
        items = paragraph.findall(f"{AKN}content/{AKN}blockList/{AKN}item")   # nur direkte Buchstaben

        # Fall 2: Absatz ohne Aufzählung -> eine Passage pro Absatz
        if not items:
            body = text_of(paragraph.find(AKN + "content"))
            if body:
                result.append(passage(abs_suffix, body, paragraph.get("eId")))
            continue

        # Fall 3: Absatz mit Aufzählung -> eine Passage pro Buchstabe,
        # jeweils mit dem Einleitungssatz davor («Unlauter handelt, wer: … »)
        intro = text_of(paragraph.find(f".//{AKN}listIntroduction"))
        for item in items:
            body = " ".join(text_of(child) for child in item if child.tag != AKN + "num")
            if body:
                lit_suffix = f" {labels['item']} {number_of(item)}"
                result.append(passage(abs_suffix + lit_suffix, f"{intro} … {body}".strip(" …"), item.get("eId")))
    return result


def is_repealed(passage: dict) -> bool:
    """Aufgehobene Bestimmungen («Aufgehoben») tragen nichts bei."""
    return bool(REPEALED.fullmatch(passage["text"].split("\n", 1)[1].strip()))


# --- Alle Gesetze verarbeiten ----------------------------------------------------

def main() -> None:
    laws = json.loads(SOURCES_FILE.read_text(encoding="utf-8"))["laws"]["files"]
    all_passages = []

    for law in laws:
        root = ET.parse(law_path(law)).getroot()
        passages = [p for article in root.iter(AKN + "article") for p in passages_of_article(article, law)]
        passages = [p for p in passages if not is_repealed(p)]
        print(f"{law['law']:6} {law['lang']}  {len(passages):5} Passagen")
        all_passages.extend(passages)

    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    with CHUNKS_FILE.open("w", encoding="utf-8") as file:
        for p in all_passages:
            file.write(json.dumps(p, ensure_ascii=False) + "\n")
    print(f"\n{len(all_passages)} Passagen gespeichert in {CHUNKS_FILE.name}")


if __name__ == "__main__":
    main()
