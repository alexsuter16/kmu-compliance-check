"""Tests für alles, was ohne Sprachmodell funktioniert: Score, Belegprüfung, Seitentypen, Regeln.

Diese Teile entscheiden mit, ob ein Shop «rot» oder «grün» wird. Darum sind sie
gewöhnlicher Code mit festen Erwartungen – und hier getestet.

Aufruf:  make test
Bauplan: docs/bauplan.html, Art. 10, 11 und 13
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from catalog import CHECK_BY_ID, CHECKS  # noqa: E402
from crawler import (PASSWORD_PAGE, _TextAndLinks, decode_cloudflare_emails, is_public_url,  # noqa: E402
                     page_type_of, remove_boilerplate)
from drafts import PLACEHOLDER, guard_facts  # noqa: E402
from evidence import quote_found, verified_quote  # noqa: E402
from llm import cost_usd, parse_json_answer  # noqa: E402
from prompts import excerpt  # noqa: E402
from pipeline import (_apply_no_evidence_rule, _apply_trigger_rule, _apply_unreadable_rule,  # noqa: E402
                      _to_verdict, _verify_quote)
from scoring import compute_score  # noqa: E402


def verdict(check_id: str, status: str, beleg: str = "") -> dict:
    return _to_verdict(CHECK_BY_ID[check_id], {"status": status, "beleg": beleg})


class ScoreTest(unittest.TestCase):
    """Bauplan Art. 11: Score = Σ (Gewicht × Punkte) ÷ Σ Gewicht × 100."""

    def test_everything_fulfilled_is_100_and_green(self):
        score = compute_score([verdict(c["id"], "erfuellt") for c in CHECKS])
        self.assertEqual((score["score"], score["ampel"]), (100, "gruen"))

    def test_not_applicable_does_not_count(self):
        verdicts = [verdict(c["id"], "erfuellt") for c in CHECKS]
        verdicts[0] = verdict(CHECKS[0]["id"], "nicht_anwendbar")
        self.assertEqual(compute_score(verdicts)["score"], 100)

    def test_example_shop_from_bauplan_scores_56(self):
        """Der erfundene Shop aus Bauplan Art. 1 und 11: 18.5 ÷ 33 × 100 = 56."""
        statuses = {
            "impressum_identitaet": "fehlt", "firma_handelsregister": "teilweise", "eingabefehler": "unklar",
            "preise_zuschlaege": "teilweise", "streichpreise": "fehlt", "datenschutz_ausland": "fehlt",
            "tracking_transparenz": "teilweise", "irrefuehrende_angaben": "teilweise", "klima_claims": "fehlt",
            "swissness": "nicht_anwendbar", "eu_vorlagen": "fehlt",
        }
        score = compute_score([verdict(c["id"], statuses.get(c["id"], "erfuellt")) for c in CHECKS])
        self.assertEqual((score["score"], score["ampel"], score["muss_maengel"]), (56, "gelb", 4))


class EvidenceTest(unittest.TestCase):
    """Bauplan Art. 10 Abs. 3: Zitate werden mit dem Seitentext verglichen."""

    pages = [{"text": "Haben Sie Fragen? Schreiben Sie uns über das **Kontaktformular**."}]

    def test_exact_quote_is_found(self):
        self.assertTrue(quote_found("Schreiben Sie uns über das Kontaktformular.", self.pages))

    def test_quote_marks_and_markdown_are_ignored(self):
        self.assertTrue(quote_found("«schreiben sie uns über das kontaktformular»", self.pages))

    def test_invented_quote_is_not_found(self):
        self.assertFalse(quote_found("Rufen Sie uns jederzeit unter 044 000 00 00 an.", self.pages))

    def test_quote_wrapped_in_own_words_is_extracted(self):
        """Das Modell schreibt oft «Startseite: "…"» oder hängt eine Erklärung an."""
        pages = [{"text": "Bärenstark Gelenk-Kapseln – heilt Gelenkschmerzen in 7 Tagen. Klinisch bewiesen."}]
        self.assertEqual(verified_quote('Startseite: "heilt Gelenkschmerzen in 7 Tagen. Klinisch bewiesen."', pages),
                         "heilt Gelenkschmerzen in 7 Tagen. Klinisch bewiesen.")
        self.assertEqual(verified_quote("„heilt Gelenkschmerzen in 7 Tagen“ als unbelegtes Versprechen", pages),
                         "heilt Gelenkschmerzen in 7 Tagen")

    def test_wrapped_invented_quote_is_still_rejected(self):
        pages = [{"text": "Bärenstark Gelenk-Kapseln"}]
        self.assertIsNone(verified_quote('Startseite: "heilt alles sofort und garantiert"', pages))

    def test_long_quote_with_one_changed_word_gets_the_page_wording(self):
        """Echter Fall aus der Messung: Apertus schrieb «der» statt «Ihrer»."""
        pages = [{"text": "Versand gratis. Mit Ihrer Bestellung melden wir Sie automatisch für unseren Newsletter an."}]
        self.assertEqual(verified_quote("Mit der Bestellung melden wir Sie automatisch für unseren Newsletter an.", pages),
                         "Mit Ihrer Bestellung melden wir Sie automatisch für unseren Newsletter an.")

    def test_short_quote_with_a_number_is_checked(self):
        """Echter Fall: «CHF 119.00» war mit 10 Zeichen zu kurz und wurde verworfen."""
        pages = [{"text": "ZENO\nCHF 119.00\nInkl. Steuern."}]
        self.assertEqual(verified_quote("CHF 119.00", pages), "CHF 119.00")
        self.assertIsNone(verified_quote("CHF 99.00", pages))

    def test_invisible_characters_and_joined_lines_are_ignored(self):
        """Echte Fälle: Null-Breite-Leerzeichen im Impressum; Adresszeilen vom Modell mit Komma verbunden."""
        pages = [{"text": "Beispiel Foods AG\u200b\nIndustriestrasse 32/34\n8310 Musterdorf"}]
        self.assertTrue(quote_found("Beispiel Foods AG, Industriestrasse 32/34, 8310 Musterdorf", pages))
        self.assertEqual(verified_quote("MUSTER AG", [{"text": "MUSTER AG\nGraben 33"}]), "MUSTER AG")

    def test_address_from_separate_lines_is_accepted_part_by_part(self):
        """Echter Fall: Das Modell fasst Firma, Adresse und E-Mail aus verschiedenen Zeilen zusammen."""
        pages = [{"text": "Sport Muster AG\nMusterweg 25\n8953 Musterhausen\nTelefon 044 000 00 00\nservice@sport-muster.example"}]
        self.assertEqual(verified_quote("Sport Muster AG, Musterweg 25, CH-8953 Musterhausen, service@sport-muster.example", pages),
                         "Sport Muster AG … Musterweg 25 … CH-8953 Musterhausen … service@sport-muster.example")
        self.assertIsNone(verified_quote("Sport Muster AG, Bahnhofstrasse 1, 8001 Zürich", pages))

    def test_short_or_clearly_different_quotes_must_match_exactly(self):
        pages = [{"text": "Versand gratis. Mit Ihrer Bestellung melden wir Sie automatisch für unseren Newsletter an."}]
        self.assertIsNone(verified_quote("Mit der Bestellung melden wir", pages))                    # zu kurz
        self.assertIsNone(verified_quote("Mit der Anmeldung melden wir Sie nie für unseren Newsletter an.", pages))

    def test_ellipsis_between_real_parts_is_allowed(self):
        self.assertTrue(quote_found("Haben Sie Fragen? … über das Kontaktformular", self.pages))


class PageTypeTest(unittest.TestCase):
    """Bauplan Art. 9 Abs. 4: Seitentyp aus URL und Linktext."""

    def test_shopify_policy_urls(self):
        self.assertEqual(page_type_of("/policies/privacy-policy"), "datenschutz")
        self.assertEqual(page_type_of("/policies/terms-of-service"), "agb")
        self.assertEqual(page_type_of("/policies/legal-notice"), "impressum")

    def test_short_keyword_must_be_a_whole_word(self):
        """«Abschlagboxen» enthält «agb», ist aber keine AGB-Seite."""
        self.assertIsNone(page_type_of("/collections/abschlagboxen Abschlagboxen"))

    def test_testshop_file_names(self):
        self.assertEqual(page_type_of("produkt-1"), "produkt")
        self.assertEqual(page_type_of("startseite"), "startseite")


class BoilerplateTest(unittest.TestCase):
    """Bauplan Art. 9 Abs. 4: Menü und Footer werden eine eigene Seite; leere Seiten gelten als nicht einsehbar."""

    menu = "Warenkorb CHF 0.00\nNewsletter: 10 % Rabatt, jederzeit abmelden\nImpressum · AGB"

    def cleaned(self):
        return remove_boilerplate([
            {"url": "https://shop.example/", "hint": "startseite", "text": self.menu + "\nWillkommen im Shop"},
            {"url": "https://shop.example/agb", "hint": "/agb", "text": self.menu + "\n" + "Geschäftsbedingungen. " * 15},
            {"url": "https://shop.example/datenschutz", "hint": "/datenschutz", "text": self.menu},
        ])

    def test_repeated_lines_leave_the_pages(self):
        self.assertNotIn("Warenkorb", self.cleaned()[1]["text"])

    def test_footer_page_keeps_newsletter_and_links(self):
        footer = self.cleaned()[-1]
        self.assertEqual(footer["hint"], "footer")
        self.assertIn("Newsletter", footer["text"])
        self.assertIn("Impressum · AGB", footer["text"])

    def test_empty_page_is_unreadable_not_missing(self):
        self.assertTrue(self.cleaned()[2]["unreadable"])

    def test_reason_of_an_unreadable_page_is_kept(self):
        """Echter Fall: Die Datenschutzerklärung lag auf einer anderen Website, die Bots abweist."""
        elsewhere = {"url": "https://other.example/privacy", "hint": "/privacy Datenschutz", "text": "",
                     "unreadable": True, "reason": "auf einer anderen Website, nicht abrufbar"}
        pages = remove_boilerplate([
            {"url": "https://shop.example/", "hint": "startseite", "text": self.menu + "\nWillkommen im Shop"},
            {"url": "https://shop.example/agb", "hint": "/agb", "text": self.menu + "\n" + "Geschäftsbedingungen. " * 15},
            elsewhere,
        ])
        self.assertEqual(pages[2]["reason"], "auf einer anderen Website, nicht abrufbar")

    def test_own_copy_of_a_repeated_line_stays(self):
        """Echter Fall: Titel und Preis standen im Suchfeld jeder Seite – und auf der eigenen Produktseite."""
        widget = "Waschlappen Löwe\nCHF 16.90"
        pages = remove_boilerplate([
            {"url": "https://shop.example/", "hint": "startseite", "text": widget + "\nWillkommen im Shop"},
            {"url": "https://shop.example/p", "hint": "/products/p", "text": widget + "\nWaschlappen Löwe\nCHF 16.90\nAus Bio-Baumwolle, gewaschen bei 60 Grad."},
            {"url": "https://shop.example/agb", "hint": "/agb", "text": widget + "\n" + "Geschäftsbedingungen. " * 15},
        ])
        self.assertEqual(pages[1]["text"], "Waschlappen Löwe\nCHF 16.90\nAus Bio-Baumwolle, gewaschen bei 60 Grad.")
        self.assertNotIn("CHF 16.90", pages[2]["text"])


class LiveShopTest(unittest.TestCase):
    """Bauplan Art. 9 Abs. 4: Besonderheiten echter Shops."""

    def test_internal_addresses_are_never_fetched(self):
        """Ein Link oder eine Weiterleitung auf ein internes Netz darf nicht abgefragt werden."""
        for url in ["http://127.0.0.1/admin", "http://10.0.0.5/datenschutz", "http://169.254.169.254/latest",
                    "http://192.168.1.1/"]:
            self.assertFalse(is_public_url(url), url)

    def test_structured_product_data_is_read(self):
        """Der Preis erscheint erst per JavaScript, steht aber als JSON-LD im HTML."""
        parser = _TextAndLinks()
        parser.feed('<script type="application/ld+json">{"@graph": [{"@type": "Product", "name": "Bantam", '
                    '"offers": {"price": "27.00", "priceCurrency": "CHF", "availability": "https://schema.org/InStock"}}]}'
                    '</script><div id="app"></div>')
        self.assertEqual(parser.result()[0], "[Strukturierte Produktdaten der Seite: Bantam · CHF 27.00 · an Lager]")

    def test_hidden_badges_are_not_read(self):
        """Shopify-Themes enthalten «Sale» und «Ausverkauft» auf jeder Produktseite, per CSS versteckt."""
        parser = _TextAndLinks()
        parser.feed('<p>CHF 14.90<span class="badge price__badge-sale">Sale</span>'
                    '<span class="visually-hidden">Regular price</span></p><a href="/d">Datenschutz</a><a href="/c">Cookies</a>')
        self.assertEqual(parser.result()[0], "CHF 14.90\nDatenschutz Cookies")

    def test_cloudflare_email_protection_is_decoded(self):
        key = 0x42
        encoded = (bytes([key]) + bytes(b ^ key for b in b"info@shop.ch")).hex()
        html = f'E-Mail: <a class="__cf_email__" data-cfemail="{encoded}">[email&#160;protected]</a>'
        self.assertEqual(decode_cloudflare_emails(html), "E-Mail: info@shop.ch")

    def test_password_protected_shopify_shop_is_detected(self):
        self.assertTrue(PASSWORD_PAGE.search('<body class="template-password">'))
        self.assertFalse(PASSWORD_PAGE.search('<body class="template-index">'))


class RuleTest(unittest.TestCase):
    """Bauplan Art. 10 Abs. 4: Regeln, die das Urteil des Modells absichern."""

    def test_invented_quote_turns_fulfilled_into_unclear(self):
        result = _verify_quote(verdict("impressum_identitaet", "erfuellt", "E-Mail: info@erfunden.example"),
                               [{"text": "Bergwiese Naturkosmetik"}])
        self.assertEqual((result["status"], result["beleg"]), ("unklar", ""))

    def test_missing_without_quote_becomes_not_applicable_for_claim_checks(self):
        result = _apply_no_evidence_rule(verdict("klima_claims", "fehlt"), CHECK_BY_ID["klima_claims"])
        self.assertEqual(result["status"], "nicht_anwendbar")

    def test_missing_with_quote_stays_missing(self):
        result = _apply_no_evidence_rule(verdict("klima_claims", "fehlt", "100 % klimaneutral"),
                                         CHECK_BY_ID["klima_claims"])
        self.assertEqual(result["status"], "fehlt")

    def test_hidden_checkout_turns_missing_order_steps_into_unclear(self):
        checkout = [{"type": "checkout", "unreadable": True, "reason": "nur mit gefülltem Warenkorb erreichbar"}]
        self.assertEqual(_apply_unreadable_rule(verdict("bestellschritte", "fehlt"), [], checkout)["status"], "unklar")

    def test_missing_stays_missing_when_every_page_was_readable(self):
        """Testshops haben keinen versteckten Checkout; ihr Lösungsblatt erwartet «fehlt»."""
        self.assertEqual(_apply_unreadable_rule(verdict("bestellschritte", "fehlt"), [], [])["status"], "fehlt")

    def test_trigger_on_the_page_rules_out_not_applicable(self):
        footer = [{"type": "footer", "text": "Jetzt Newsletter abonnieren und 10 % sparen"}]
        result = _apply_trigger_rule(verdict("newsletter_einwilligung", "nicht_anwendbar"),
                                     CHECK_BY_ID["newsletter_einwilligung"], footer)
        self.assertEqual(result["status"], "unklar")

    def test_defect_without_any_trigger_is_not_applicable(self):
        """Echter Fall: «Lieferung aus Deutschland oder der Schweiz» galt dem Modell als Swissness-Beleg."""
        product = [{"type": "produkt", "text": "Lieferung aus Deutschland oder der Schweiz"}]
        result = _apply_trigger_rule(verdict("swissness", "fehlt", "Lieferung aus Deutschland oder der Schweiz"),
                                     CHECK_BY_ID["swissness"], product)
        self.assertEqual(result["status"], "nicht_anwendbar")


class DraftGuardTest(unittest.TestCase):
    """Bauplan Art. 10a: Textvorschläge dürfen keine Kontaktangaben erfinden."""

    pages = [{"text": "Bergwiese GmbH, datenschutz@bergwiese.example, UID CHE-123.456.789"}]

    def test_invented_email_and_phone_are_replaced(self):
        draft = guard_facts("Mail: info@erfunden.example, Tel. 044 123 45 67", self.pages)
        self.assertEqual(draft, f"Mail: {PLACEHOLDER}, Tel. {PLACEHOLDER}")

    def test_known_facts_stay(self):
        draft = guard_facts("Kontakt: datenschutz@bergwiese.example, CHE-123.456.789", self.pages)
        self.assertNotIn(PLACEHOLDER, draft)


class ExcerptTest(unittest.TestCase):
    """Lange Seiten: Anfang und die Abschnitte zu den Stichwörtern statt einfach abschneiden."""

    def test_long_page_keeps_the_section_at_the_end(self):
        text = "Verantwortlich: Shop AG, Bern\n" + "Allgemeines.\n" * 3000 + "12. Ausland\nWir übermitteln Daten in die USA."
        short = excerpt(text, ["ausland", "usa"], limit=3000)
        self.assertIn("Shop AG", short)
        self.assertIn("Wir übermitteln Daten in die USA.", short)
        self.assertLessEqual(len(short), 3000)

    def test_beginning_is_not_repeated(self):
        text = "Verantwortlich: Shop AG\n" + "Allgemeines.\n" * 3000 + "Ausland: USA"
        short = excerpt(text, ["verantwortlich", "ausland"], limit=3000)
        self.assertEqual(short.count("Verantwortlich: Shop AG"), 1)
        self.assertIn("[…]\nAllgemeines.\nAusland: USA", short)        # eine Zeile Zusammenhang vor dem Treffer

    def test_short_page_stays_unchanged(self):
        self.assertEqual(excerpt("Kurze AGB.", ["recht"]), "Kurze AGB.")


class ModelAnswerTest(unittest.TestCase):

    def test_json_is_found_inside_text_and_code_fences(self):
        answer = parse_json_answer('Hier mein Urteil:\n```json\n{"status": "fehlt", "beleg": ""}\n```')
        self.assertEqual(answer["status"], "fehlt")

    def test_german_quote_closed_with_straight_quote_is_repaired(self):
        # echte Antwort von Apertus 8B: das gerade " nach «Stück!» beendet sonst den JSON-Text
        answer = parse_json_answer('{"status": "fehlt", "beleg": "„nur noch 2 Stück!“", '
                                   '"begruendung": "Die Aussage „nur noch 2 Stück!" wirkt dauerhaft."}')
        self.assertEqual(answer["begruendung"], "Die Aussage „nur noch 2 Stück!“ wirkt dauerhaft.")

    def test_unknown_status_becomes_unclear(self):
        self.assertEqual(verdict("swissness", "vielleicht")["status"], "unklar")

    def test_cost_at_list_price(self):
        cost = cost_usd("swiss-ai/apertus-v1.5-8b", {"input": 1_000_000, "output": 1_000_000})
        self.assertAlmostEqual(cost, 0.30)
        self.assertIsNone(cost_usd("lokales-modell", {"input": 10, "output": 10}))


if __name__ == "__main__":
    unittest.main()
