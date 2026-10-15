"""Schritt 4 – Seiten laden: holt die Texte eines Shops und ordnet sie Seitentypen zu.

Zwei Quellen:
  testshop:<name>   erfundener Shop aus data/testshops/<name>/ (eine .md-Datei pro Seite)
  https://…         echter Shop. Geladen werden die Startseite und die rechtlich
                    relevanten Unterseiten (Impressum, Datenschutz, AGB, Versand,
                    Newsletter-Anmeldung, zwei Produkte) – höchstens MAX_PAGES Seiten.

Rechtstexte stehen oft nur im Footer oder gar nicht auf der Startseite. Darum sucht
der Lader an drei Orten, in dieser Reihenfolge:
  1. Links der Startseite (inkl. Footer), eindeutige Treffer wie «Impressum» zuerst
  2. die Sitemap (/sitemap.xml), die fast jeder Shop hat – auch für nicht verlinkte Seiten
  3. bei Shopify die festen Adressen der Rechtstexte; zuletzt übliche Adressen wie /impressum

Menü und Footer stehen auf jeder Seite gleich. Sie werden aus den einzelnen Seiten
entfernt und einmal als eigene Seite «footer» geführt (Newsletter-Anmeldung, Links).

Preise, die erst per JavaScript erscheinen, stehen oft als Produktdaten (JSON-LD) im HTML;
der Lader hängt sie als Zeile «[Strukturierte Produktdaten der Seite: …]» an den Seitentext.

Beim Laden echter Shops gilt: robots.txt wird beachtet, zwischen zwei Abrufen
liegt eine Pause, und der User-Agent nennt das Projekt. Geladen werden nur öffentliche
Adressen, auch bei Weiterleitungen und Links – nie ein Server im internen Netz.

Seitentypen und ihre Stichwörter stehen in data/checks.json unter "page_types".

Test:    python src/crawler.py testshop:bergwiese
         python src/crawler.py https://nuvate.ch
Bauplan: docs/bauplan.html, Art. 9 Abs. 4
"""

import html
import ipaddress
import json
import re
import socket
import sys
import time
from collections import Counter
from html.parser import HTMLParser
from typing import NotRequired, TypedDict
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from catalog import PAGE_TYPES
from config import TESTSHOPS_DIR

USER_AGENT = "kmu-compliance-check/0.1 (Hack Apertus Studienprojekt)"
MAX_CHARS = 60_000          # pro Seite gespeicherter Text; den Auszug für den Prompt wählt prompts.excerpt()
MIN_PAGE_CHARS = 200        # ganze Seite inkl. Menü: kürzer = Fehlerseite, wird verworfen – ausser
                            # Rechtsseiten, die als «nicht einsehbar» bleiben (siehe _usable)
MIN_CONTENT_CHARS = 60      # eigener Text nach Abzug von Menü und Footer: weniger = Inhalt kommt per
                            # JavaScript. Ein knappes Impressum (Firma, Adresse, E-Mail) hat schon ~150 Zeichen.
MAX_REDIRECTS = 5
PAUSE_SECONDS = 0.7
# Kurze Netzwerkfehler und «zu viele Anfragen» (429) bekommen zwei weitere Versuche mit Pause (1 s, 2 s)
RETRY = Retry(total=2, backoff_factor=1, status_forcelist=(429, 500, 502, 503, 504), raise_on_status=False)

# Wie viele Seiten pro Typ bei echten Shops geladen werden
# (Datenschutz zweimal: Viele Shops trennen Datenschutzerklärung und Cookie-Richtlinie)
WANTED = {"impressum": 1, "datenschutz": 2, "agb": 1, "versand": 2, "produkt": 2, "newsletter": 1}
MAX_PAGES = 1 + sum(WANTED.values())       # Startseite + gewünschte Unterseiten
LEGAL_TYPES = ("impressum", "datenschutz", "agb")    # Rechtsseiten: lieber «nicht einsehbar» als «fehlt»

# Reihenfolge der Zuordnung: spezifische Typen zuerst, damit z.B. «/policies/terms-of-service»
# nicht wegen «service» falsch landet und «/pages/kontakt» nicht vor «datenschutz» gewinnt.
# «checkout» erkennt die Platzhalter-Seite aus crawl(); verlinkte Warenkorb-Seiten werden nie geladen.
TYPE_ORDER = ["datenschutz", "agb", "versand", "checkout", "impressum", "produkt", "newsletter"]

# Eindeutige Treffer werden zuerst geladen: das echte Impressum vor «Über uns»,
# eine Produktseite vor einer Kategorieseite
STRONG_HINTS = ["impressum", "imprint", "legal-notice", "mentions-legales", "/products/"]

# Den Checkout eines echten Shops erreicht man nur mit gefülltem Warenkorb. Er wird als Seite
# «nicht einsehbar» geführt, damit niemand aus seinem Fehlen einen Verstoss ableitet (Bauplan Art. 13 lit. i).
CHECKOUT_REASON = "nur mit gefülltem Warenkorb erreichbar; wird nicht automatisch durchlaufen"
JAVASCRIPT_REASON = "Inhalt wird per JavaScript geladen"
OTHER_SITE_REASON = "auf einer anderen Website, nicht abrufbar"

# Übliche Adressen, falls eine Rechtsseite weder verlinkt noch in der Sitemap steht
GUESSED_PATHS = {
    "impressum": ["/impressum", "/pages/impressum"],
    "datenschutz": ["/datenschutz", "/pages/datenschutz"],
    "agb": ["/agb", "/pages/agb"],
}
SITEMAP_LIMIT = 2_000       # so viele Adressen aus der Sitemap werden höchstens angeschaut
SITEMAP_PARTS = 4           # so viele Teil-Sitemaps eines Sitemap-Index werden höchstens gelesen
SITEMAP_CONTENT_WORDS = ("page", "policies", "seiten", "cms", "static", "content")   # nicht: Produkte

# Ein Impressum nennt eine Postleitzahl mit Ort oder eine E-Mail-Adresse. Eine «Über uns»-Seite
# ohne beides ist kein Impressum, auch wenn ihr Link so aussieht.
IMPRESSUM_CONTENT = re.compile(r"\b\d{4}\s+[A-ZÄÖÜ][\wäöüéè-]+|[\w.+-]+@[\w-]+\.[a-z]{2,}")

# Internationale Marken: <link rel="alternate" hreflang="de-CH" href="…"> zeigt auf die Schweizer Fassung
SWISS_ALTERNATE = re.compile(r'<link[^>]*hreflang="(?:de|fr|it|en)-ch"[^>]*>', re.IGNORECASE)

# Newsletter-Formulare, die erst per JavaScript erscheinen; im HTML steht nur der Anbieter
NEWSLETTER_WIDGET = re.compile(
    r"klaviyo|sibforms\.com|list-manage\.com|mailchimp|omnisend|mailerlite|cleverreach", re.IGNORECASE)

GIFT_CARD = re.compile(r"voucher|gift|gutschein|geschenkkarte|carte-cadeau|buono-regalo")

# Feste Adressen der Rechtstexte in jedem Shopify-Shop
SHOPIFY_POLICIES = ["/policies/legal-notice", "/policies/privacy-policy", "/policies/terms-of-service",
                    "/policies/shipping-policy", "/policies/refund-policy"]


class Page(TypedDict):
    name: str                       # Dateiname oder URL-Pfad
    url: str
    hint: str                       # woraus der Typ abgeleitet wird: Dateiname oder «Pfad Linktext»
    text: str
    type: NotRequired[str]          # gesetzt von assign_types(), z.B. «impressum»
    unreadable: NotRequired[bool]   # Seite existiert, Inhalt ist aber nicht lesbar …
    reason: NotRequired[str]        # … und das ist der Grund (für Prompt und Bericht)


# --- Seitentyp bestimmen --------------------------------------------------------

UMLAUTS = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue"})


def _matches(keyword: str, hint: str, words: list[str]) -> bool:
    """Kurze Stichwörter («agb», «faq») nur als ganzes Wort – sonst wäre «Abschlagboxen» eine AGB-Seite.

    «ueber-uns» passt auch auf den Linktext «Über uns»: Bindestrich und Leerzeichen gelten gleich.
    """
    if "/" in keyword or "-" in keyword:
        return keyword in hint or keyword.replace("-", " ") in hint
    if len(keyword) <= 4:
        return keyword in words
    return any(word.startswith(keyword) for word in words)


def page_type_of(hint: str) -> str | None:
    """Seitentyp aus Dateiname, URL-Pfad oder Linktext, z.B. «produkt-1» oder «/policies/privacy-policy»."""
    hint = hint.lower()
    if hint != hint.translate(UMLAUTS):             # «über uns» passt auch auf das Stichwort «ueber-uns»
        hint = f"{hint} {hint.translate(UMLAUTS)}"
    if hint in ("", "/", "startseite"):
        return "startseite"
    if hint == "footer":                    # nur die vom Lader gebaute Seite – «/footer/agb» ist eine AGB-Seite
        return "footer"
    words = re.findall(r"[a-zäöüéèà0-9]+", hint)
    for page_type in TYPE_ORDER:
        if hint.split("-")[0] == page_type or any(_matches(k, hint, words) for k in PAGE_TYPES[page_type]):
            return page_type
    return None


# --- Erfundene Testshops --------------------------------------------------------

def load_testshop(name: str) -> list[Page]:
    folder = TESTSHOPS_DIR / name
    if not folder.is_dir():
        raise FileNotFoundError(f"Testshop «{name}» nicht gefunden in {TESTSHOPS_DIR}")
    return [
        Page(name=file.stem, url=f"testshop:{name}/{file.name}", hint=file.stem,
             text=file.read_text(encoding="utf-8"))
        for file in sorted(folder.glob("*.md"))
    ]


# --- Echte Shops ---------------------------------------------------------------------

CLOUDFLARE_EMAIL = re.compile(r'<(a|span)[^>]*data-cfemail="([0-9a-fA-F]+)"[^>]*>.*?</\1>', re.DOTALL)
PASSWORD_PAGE = re.compile(r'template-password|action="/password"|Mit Passwort betreten|Enter using password')


def decode_cloudflare_emails(html: str) -> str:
    """Macht von Cloudflare versteckte E-Mail-Adressen («[email protected]») wieder lesbar.

    Cloudflare ersetzt Adressen durch einen Platzhalter und setzt sie erst im Browser per
    JavaScript ein. Die Adresse steht verschlüsselt im Attribut data-cfemail: Das erste Byte
    ist der Schlüssel, jedes weitere Byte ist mit ihm XOR-verknüpft. Ohne diese Entschlüsselung
    hielte das Modell ein vollständiges Impressum für eines ohne E-Mail.
    """
    def decode(match: re.Match) -> str:
        data = bytes.fromhex(match.group(2))
        return bytes(b ^ data[0] for b in data[1:]).decode("utf-8", errors="replace")
    return CLOUDFLARE_EMAIL.sub(decode, html)


class _TextAndLinks(HTMLParser):
    """Liest sichtbaren Text, alle Links und eingebettete Produktdaten (JSON-LD) aus HTML, ohne Zusatzbibliothek."""

    SKIP = {"script", "style", "noscript", "svg", "template", "head", "iframe"}
    BLOCK = {"p", "div", "li", "br", "tr", "section", "article", "header", "footer", "nav",
             "h1", "h2", "h3", "h4", "h5", "h6", "td", "dd", "dt", "table", "ul", "ol", "form"}
    # Zwischen diesen Elementen steht im Browser ein Abstand; ohne Leerzeichen würde aus
    # «Datenschutz» und «Cookie-Einstellungen» das Wort «DatenschutzCookie-Einstellungen»
    INLINE = {"a", "span", "strong", "b", "em", "small", "sup", "label", "button", "s", "del"}
    # Unsichtbare Beschriftungen: Shopify-Themes enthalten auf jeder Produktseite «Sale» und
    # «Ausverkauft» als Abzeichen und «Regular price» für Screenreader – per CSS ausgeblendet
    HIDDEN_CLASS = re.compile(r"visually-hidden|sr-only|screen-reader|\bbadge\b")

    def __init__(self):
        super().__init__()
        self.text: list[str] = []
        self.links: list[tuple[str, str]] = []      # (href, Linktext)
        self._skip_depth = 0
        self._hidden_spans = 0                       # offene <span>, solange ein unsichtbares <span> läuft
        self._link: list | None = None
        self.json_ld_blocks: list[str] = []          # fertig gelesene <script type="application/ld+json">
        self._open_json_ld: str | None = None        # das gerade offene davon (None: keines)

    def _is_hidden(self, attrs: dict) -> bool:
        return ("hidden" in attrs or attrs.get("aria-hidden") == "true"
                or bool(self.HIDDEN_CLASS.search(attrs.get("class") or "")))

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "script" and attrs.get("type") == "application/ld+json":
            self._open_json_ld = ""
        if tag in self.SKIP:
            self._skip_depth += 1
        elif tag == "span" and (self._hidden_spans or self._is_hidden(attrs)):
            self._hidden_spans += 1                  # nur <span>: bei ihnen fehlt nie ein schliessendes Tag
        elif tag == "a":
            self._link = [attrs.get("href") or "", ""]
        if tag in self.BLOCK:
            self.text.append("\n")
        elif tag in self.INLINE:
            self.text.append(" ")

    def handle_endtag(self, tag):
        if tag == "script" and self._open_json_ld is not None:
            self.json_ld_blocks.append(self._open_json_ld)
            self._open_json_ld = None
        if tag in self.SKIP and self._skip_depth:
            self._skip_depth -= 1
        elif tag == "span" and self._hidden_spans:
            self._hidden_spans -= 1
        elif tag == "a" and self._link is not None:
            self.links.append((self._link[0], self._link[1].strip()))
            self._link = None
        if tag in self.BLOCK:
            self.text.append("\n")
        elif tag in self.INLINE:
            self.text.append(" ")

    def handle_data(self, data):
        if self._open_json_ld is not None:
            self._open_json_ld += data
            return
        if self._skip_depth or self._hidden_spans:
            return
        self.text.append(data)
        if self._link is not None:
            self._link[1] += data

    def result(self) -> tuple[str, list[tuple[str, str]]]:
        lines = [" ".join(line.split()) for line in "".join(self.text).splitlines()]
        lines += structured_product_lines(self.json_ld_blocks)
        return "\n".join(line for line in lines if line), self.links


AVAILABILITY = {"InStock": "an Lager", "OutOfStock": "ausverkauft", "PreOrder": "vorbestellbar",
                "LimitedAvailability": "begrenzt verfügbar"}
MAX_STRUCTURED_PRODUCTS = 3               # eine Übersichtsseite listet viele; für die Preisprüfung reichen wenige


def structured_product_lines(blocks: list[str]) -> list[str]:
    """Produktdaten, die der Shop maschinenlesbar einbettet (JSON-LD nach schema.org), als Textzeilen.

    Viele Shops zeigen den Preis erst per JavaScript an, betten ihn aber für Suchmaschinen als
    JSON-LD ein. So sieht das Modell Name, Preis, Währung und Verfügbarkeit trotzdem, z.B.:
    «[Strukturierte Produktdaten der Seite: Bantam Alox · CHF 27.00 · an Lager]»
    """
    lines = []
    for block in blocks:
        try:
            data = json.loads(block)
        except ValueError:
            continue
        for item in _json_objects(data):
            types = item.get("@type")
            if "Product" not in (types if isinstance(types, list) else [types]):
                continue
            offer = item.get("offers") or {}
            if isinstance(offer, list):                 # mehrere Angebote (z.B. Varianten): das erste genügt
                offer = offer[0] if offer else {}
            if not isinstance(offer, dict):
                continue
            price = offer.get("price") or offer.get("lowPrice")       # lowPrice: Preisspanne (AggregateOffer)
            currency = offer.get("priceCurrency", "")
            if not price:
                continue
            available = AVAILABILITY.get(str(offer.get("availability", "")).rsplit("/", 1)[-1], "")
            parts = [str(item.get("name", "")).strip(), f"{currency} {price}".strip(), available]
            lines.append("[Strukturierte Produktdaten der Seite: " + " · ".join(p for p in parts if p) + "]")
    return list(dict.fromkeys(lines))[:MAX_STRUCTURED_PRODUCTS]


def _json_objects(data):
    """Alle JSON-Objekte in beliebiger Verschachtelung (Listen, «@graph»)."""
    if isinstance(data, dict):
        yield data
        for value in data.values():
            if isinstance(value, (dict, list)):
                yield from _json_objects(value)
    elif isinstance(data, list):
        for value in data:
            yield from _json_objects(value)


MIN_PAGES_FOR_BOILERPLATE = 3   # erst ab drei Seiten lässt sich sagen, was «auf fast allen» steht
BOILERPLATE_SHARE = 0.6         # eine Zeile auf mindestens 60 % der Seiten gehört zu Menü oder Footer


def remove_boilerplate(pages: list[Page]) -> list[Page]:
    """Zieht Menü, Warenkorb und Footer aus den Seiten heraus und führt sie einmal als Seite «footer».

    Zeilen, die auf fast allen Seiten gleich sind, stören bei den einzelnen Seiten: Sonst
    beurteilt das Modell z.B. den Preis anhand von «Warenkorb: CHF 0.00» aus dem Menü.
    Als eigene Seite bleiben sie aber erhalten – mit Newsletter-Anmeldung und Footer-Links.
    Bleibt von einer Seite fast nichts übrig, lädt sie ihren Inhalt per JavaScript; sie wird
    als «unreadable» markiert – das ist kein leerer Rechtstext.
    """
    if len(pages) < MIN_PAGES_FOR_BOILERPLATE:
        return pages
    counts = [Counter(page["text"].splitlines()) for page in pages if page["text"].strip()]
    shared = [line for line in set().union(*counts)
              if sum(line in count for count in counts) >= BOILERPLATE_SHARE * len(counts)]
    # Wie oft eine Zeile auf jeder Seite steht. Nur so oft wird sie entfernt; ein weiteres Vorkommen
    # ist Inhalt der Seite – z.B. der Preis auf der eigenen Produktseite, der auch im Suchfeld steht.
    common = {line: min(count[line] for count in counts if line in count) for line in shared}
    start = pages[0]
    footer_lines = list(dict.fromkeys(line for line in start["text"].splitlines() if line in common))
    footer = Page(name="menü-und-footer", url=start["url"], hint="footer",
                  text="\n".join(footer_lines)[:MAX_CHARS])
    cleaned = []
    for page in pages:
        if page.get("unreadable"):                      # schon beim Laden als nicht einsehbar erkannt: Grund behalten
            cleaned.append(page)
            continue
        text = "\n".join(_without_lines(page["text"].splitlines(), common))[:MAX_CHARS]
        if page["hint"] != "startseite" and len(text) < MIN_CONTENT_CHARS:
            cleaned.append({**page, "text": "", "unreadable": True, "reason": JAVASCRIPT_REASON})
        else:
            cleaned.append({**page, "text": text})
    return cleaned + [footer]


def _without_lines(lines: list[str], to_remove: dict[str, int]) -> list[str]:
    """Die Zeilen ohne die ersten n Vorkommen jeder Zeile aus to_remove (Zeile → n)."""
    remaining, kept = dict(to_remove), []
    for line in lines:
        if remaining.get(line, 0) > 0:
            remaining[line] -= 1
        else:
            kept.append(line)
    return kept


def is_public_url(url: str) -> bool:
    """Nur öffentliche Adressen: Über Links oder Weiterleitungen darf kein interner Server abgefragt werden."""
    try:
        addresses = {info[4][0] for info in socket.getaddrinfo(urlparse(url).hostname or "", 443)}
    except (socket.gaierror, UnicodeError):
        return False
    return bool(addresses) and all(ipaddress.ip_address(address).is_global for address in addresses)


class LiveShop:
    """Ein echter Shop im Internet. crawl() liefert seine rechtlich relevanten Seiten."""

    def __init__(self, start_url: str):
        self.session = requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT
        self.session.mount("https://", HTTPAdapter(max_retries=RETRY))
        self.session.mount("http://", HTTPAdapter(max_retries=RETRY))
        self.robots = RobotFileParser()
        self.start_url = start_url if start_url.startswith("http") else "https://" + start_url

    def crawl(self) -> list[Page]:
        home = self._get_home(self.start_url)
        swiss = self._swiss_alternate(home)
        if swiss:                                       # z.B. sigg.com (Euro) → sigg.ch (Franken)
            print(f"  Schweizer Fassung des Shops: {swiss}", file=sys.stderr)
            home = self._get_home(swiss)
        base = f"{urlparse(home.url).scheme}://{urlparse(home.url).netloc}"
        self._read_robots(base)

        if PASSWORD_PAGE.search(home.text):
            raise RuntimeError("Der Shop ist mit einem Passwort geschützt und noch nicht öffentlich – "
                               "es gibt nichts zu prüfen.")
        start_page, links = self._fetch_page(home.url, "startseite")
        if start_page is None:
            raise RuntimeError(f"Startseite nicht lesbar: {self.start_url}")
        if widget := NEWSLETTER_WIDGET.search(home.text):
            start_page["text"] += f"\n[Newsletter-Anmeldeformular, per JavaScript geladen ({widget.group(0)})]"

        is_shopify = "cdn.shopify.com" in home.text
        candidates = self._candidate_links(home.url, base, links, is_shopify)
        subpages = self._select_pages(candidates, base, already=home.url)
        subpages += self._guess_missing(home.url, subpages)
        pages = remove_boilerplate([start_page] + subpages)

        pages.append(Page(name="/checkout", url=base + "/checkout", hint="checkout", text="",
                          unreadable=True, reason=CHECKOUT_REASON))
        return pages

    # --- die einzelnen Schritte von crawl() ---------------------------------------

    def _get_home(self, url: str) -> requests.Response:
        """Die Startseite; antwortet «shop.ch» nicht, wird «www.shop.ch» versucht (wie im Browser)."""
        host = urlparse(url).netloc
        attempts = [url] if host.startswith("www.") else [url, url.replace(host, "www." + host, 1)]
        for attempt in attempts:
            try:
                return self._request(attempt)
            except requests.RequestException as error:
                last_error = error
        raise RuntimeError(f"Shop nicht erreichbar: {url} ({last_error.__class__.__name__})") from last_error

    def _swiss_alternate(self, home: requests.Response) -> str | None:
        """Die Adresse der Schweizer Fassung – nur wenn die Startseite selbst keine Schweizer Fassung ist."""
        head = home.text[:200_000]                      # die <link>-Angaben stehen im Kopf der Seite
        swiss = [html.unescape(m.group(1)).rstrip("/") for tag in SWISS_ALTERNATE.findall(head)
                 if (m := re.search(r'href="(https?://[^"]+)"', tag))]
        return swiss[0] if swiss and home.url.rstrip("/") not in swiss else None

    def _read_robots(self, base: str) -> None:
        """robots.txt lesen (mit requests, damit Zertifikate wie überall funktionieren)."""
        try:
            robots = self._request(base + "/robots.txt")
        except requests.RequestException:
            robots = None                               # nicht erreichbar: wie ein Shop ohne robots.txt
        self.robots.parse(robots.text.splitlines() if robots is not None and robots.ok else [])

    def _candidate_links(self, home_url: str, base: str, links: list, is_shopify: bool) -> list[tuple[str, str]]:
        """Mögliche Unterseiten als (URL, Hinweis): Startseite, Sitemap, Shopify. Eindeutige Treffer zuerst."""
        candidates = [(urljoin(home_url, href), f"{urlparse(urljoin(home_url, href)).path} {label}")
                      for href, label in links]
        candidates += [(url, urlparse(url).path) for url in self._sitemap_urls(base)]
        if is_shopify:
            candidates += [(base + path, path) for path in SHOPIFY_POLICIES]
            candidates += [(base + "/products/" + handle, "/products/") for handle in self._shopify_products(base)]
        candidates.sort(key=lambda c: not any(word in c[1].lower() for word in STRONG_HINTS))
        return candidates

    def _sitemap_urls(self, base: str) -> list[str]:
        """Seiten aus /sitemap.xml, die nach einem Rechtstext oder Versand aussehen.

        Viele Shops verlinken ihre Rechtstexte nicht auf der Startseite, aber jede Seite steht in
        der Sitemap. Bei einem Sitemap-Index (z.B. Shopify) werden nur Teil-Sitemaps für Seiten gelesen.
        """
        def locations(xml: str) -> list[str]:
            return [html.unescape(u) for u in re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", xml)][:SITEMAP_LIMIT]

        urls = []
        for sitemap_url in dict.fromkeys([base + "/sitemap.xml"] + (self.robots.site_maps() or [])):
            response = self._get(sitemap_url)                # robots.txt nennt oft eine andere Adresse
            if response is None:
                continue
            found = locations(response.text)
            if "<sitemapindex" in response.text:          # Index: nur die Teil-Sitemaps für Seiten lesen
                content_maps = [u for u in found if any(w in u.lower() for w in SITEMAP_CONTENT_WORDS)]
                found = []
                for sitemap in content_maps[:SITEMAP_PARTS]:
                    if (part := self._get(sitemap)) is not None:
                        found += locations(part.text)
            urls += found
        legal = [u for u in urls if page_type_of(urlparse(u).path) in {"impressum", "datenschutz", "agb", "versand"}]
        # Internationale Shops listen jede Länderfassung; die Schweizer zuerst nehmen
        return sorted(legal, key=lambda u: not re.search(r"[_/-]ch\b|/ch/|de-ch|fr-ch|it-ch", u.lower()))

    def _guess_missing(self, home_url: str, found: list[Page]) -> list[Page]:
        """Probiert übliche Adressen (z.B. /impressum) für Rechtsseiten, die noch fehlen."""
        found_types = {page_type_of(page["hint"]) for page in found}
        prefix = urlparse(home_url).path.rstrip("/")             # z.B. «/de-ch» bei mehrsprachigen Shops
        base = f"{urlparse(home_url).scheme}://{urlparse(home_url).netloc}"
        guessed = []
        for page_type, paths in GUESSED_PATHS.items():
            if page_type in found_types:
                continue
            for path in paths:
                page, _ = self._fetch_page(base + prefix + path, path)
                if page and len(page["text"]) > MIN_PAGE_CHARS:
                    guessed.append(page)
                    break
        return guessed

    def _select_pages(self, candidates: list[tuple[str, str]], base: str, already: str) -> list[Page]:
        """Lädt pro Seitentyp so viele Seiten wie in WANTED (zusammen mit der Startseite MAX_PAGES)."""
        seen, pages = {already.rstrip("/")}, []
        count = dict.fromkeys(WANTED, 0)
        for url, hint in candidates:
            url = url.split("#")[0].rstrip("/")
            page_type = page_type_of(hint)
            wanted = page_type in WANTED and count[page_type] < WANTED[page_type]
            if page_type == "produkt" and GIFT_CARD.search(url):
                continue                                    # ein Gutschein zeigt keine normale Preisangabe
            # Von anderen Websites nur Datenschutz und AGB (z.B. liegt eine Datenschutzerklärung beim Mutterkonzern)
            other_site = urlparse(url).netloc != urlparse(base).netloc
            if url in seen or not wanted or (other_site and page_type not in ("datenschutz", "agb")):
                continue
            seen.add(url)
            page, _ = self._fetch_page(url, hint)
            if page is None and other_site:                 # die andere Website weist den Abruf ab
                page = Page(name=url, url=url, hint=hint, text="", unreadable=True, reason=OTHER_SITE_REASON)
            elif page is not None:
                page = _usable(page, page_type)
            if page is None:
                continue
            pages.append(page)
            count[page_type] += 1
            if count == WANTED:                             # alle gewünschten Seiten gefunden
                break
        return pages

    # --- Hilfsfunktionen ----------------------------------------------------------

    def _get(self, url: str) -> requests.Response | None:
        if not self.robots.can_fetch(USER_AGENT, url):
            print(f"  übersprungen (robots.txt): {url}", file=sys.stderr)
            return None
        time.sleep(PAUSE_SECONDS)
        try:
            response = self._request(url)
        except requests.RequestException as error:
            print(f"  nicht erreichbar: {url} ({error.__class__.__name__})", file=sys.stderr)
            return None
        return response if response.ok else None

    def _request(self, url: str) -> requests.Response:
        """GET, Weiterleitungen von Hand: Jede Station muss eine öffentliche Adresse sein."""
        for _ in range(MAX_REDIRECTS + 1):
            if not is_public_url(url):
                raise requests.RequestException(f"keine öffentliche Adresse: {url}")
            response = self.session.get(url, timeout=20, allow_redirects=False)
            if not response.is_redirect:
                return response
            url = urljoin(url, response.headers["location"])
        raise requests.TooManyRedirects(url)

    def _fetch_page(self, url: str, hint: str) -> tuple[Page | None, list[tuple[str, str]]]:
        response = self._get(url)
        if response is None or "html" not in response.headers.get("content-type", ""):
            return None, []
        parser = _TextAndLinks()
        parser.feed(decode_cloudflare_emails(response.text))
        text, links = parser.result()
        return Page(name=urlparse(response.url).path or "/", url=response.url, hint=hint, text=text), links

    def _shopify_products(self, base: str, limit: int = WANTED["produkt"]) -> list[str]:
        """Produkte aus Shopifys öffentlicher Produktliste, ohne Gutscheine; reduzierte zuerst.

        Ein reduziertes Produkt (Vergleichspreis höher als Preis) zeigt, wie der Shop Streichpreise angibt.
        """
        response = self._get(base + "/products.json?limit=30")
        try:
            products = response.json()["products"] if response else []
        except (ValueError, KeyError, TypeError):           # keine oder eine unerwartete Produktliste
            return []

        def reduced(product: dict) -> bool:
            return any(float(v.get("compare_at_price") or 0) > float(v.get("price") or 0)
                       for v in product.get("variants", []))

        products = [p for p in products if p.get("handle") and not GIFT_CARD.search(p["handle"])]
        products.sort(key=lambda p: not reduced(p))
        return [p["handle"] for p in products][:limit]


def _usable(page: Page, page_type: str) -> Page | None:
    """Die geladene Seite, eine fast leere Rechtsseite als «nicht einsehbar» – oder None, wenn sie nicht taugt."""
    too_short = len(page["text"]) <= MIN_PAGE_CHARS
    if page_type == "impressum" and not too_short and not IMPRESSUM_CONTENT.search(page["text"]):
        return None                                     # z.B. «About»-Seite ohne Adresse
    if too_short and page_type in LEGAL_TYPES:          # existiert, liefert aber (fast) keinen Text
        return {**page, "text": "", "unreadable": True, "reason": JAVASCRIPT_REASON}
    return None if too_short else page


# --- Einstieg ------------------------------------------------------------------------

def load_pages(source: str) -> list[Page]:
    """Seiten einer Quelle laden (Knoten seiten_laden)."""
    if source.startswith("testshop:"):
        return load_testshop(source.split(":", 1)[1])
    return LiveShop(source).crawl()


def assign_types(pages: list[Page]) -> list[Page]:
    """Jeder Seite ihren Typ geben (Knoten seiten_zuordnen). Unbekannte Seiten fallen weg."""
    typed = [{**page, "type": page_type_of(page["hint"])} for page in pages]
    return [page for page in typed if page["type"]]


if __name__ == "__main__":
    for page in assign_types(load_pages(sys.argv[1] if len(sys.argv) > 1 else "testshop:bergwiese")):
        flag = f"  (nicht einsehbar: {page['reason']})" if page.get("unreadable") else ""
        print(f"{page['type']:12} {len(page['text']):6} Zeichen  {page['url']}{flag}")
