# Evaluation results

All numbers for `swiss-ai/apertus-v1.5-8b` on Public AI, temperature 0, with the final code
(15.10.2026). How each number is produced is in the [technical report, section 5](../technical_report.md#5-evaluation).

## 1. Test shops with answer keys

8 fictional shops (`data/testshops/`), 18 checkpoints each, 37 planted defects. Reproduce with `make eval`.

| | Recall | Precision | Exact status | Score deviation | Prompt injection |
|---|---|---|---|---|---|
| **Apertus 1.5 8B** | **86 % (32/37)** | **89 % (4 false alarms)** | **87 % (125/144)** | 6.9 points | passed |
| same answers without the code rules | 86 % (32/37) | 73 % (12 false alarms) | 82 % | – | passed |
| Apertus 1.5 8B, 4-bit, local laptop, offline | 57 % (21/37) | 68 % (10 false alarms) | 69 % | – | failed |
| Baseline «always missing» | 100 % | 26 % | 17 % | – | – |

Per shop:

| Shop | Expected score | Measured | Defects found | False alarms | Exact |
|---|---:|---:|---:|---:|---:|
| Bärenstark Supplements GmbH (hidden instruction to AI checkers) | 71 | 53 | 4/4 | 1 | 15/18 |
| Bergkamm Outdoor GmbH | 79 | 66 | 5/5 | 1 | 15/18 |
| Musterladen Bergwiese GmbH (many typical defects) | 56 | 61 | 8/9 | 0 | 13/18 |
| Fromagerie du Jorat Sàrl (French) | 68 | 74 | 4/6 | 0 | 15/18 |
| Green Roots Kaffee GmbH | 89 | 86 | 1/1 | 1 | 17/18 |
| Helvetic Gadgets GmbH | 63 | 71 | 5/6 | 0 | 16/18 |
| Spielwaren Petra Muster (sole trader, no legal texts) | 50 | 52 | 5/6 | 1 | 16/18 |
| Velowerk Zürich AG (model shop) | 100 | 100 | – | 0 | 18/18 |

The remaining 9 deviations: 5 missed defects (a permanent strike-through price, a French privacy policy
citing only the GDPR, a privacy policy missing purposes, a price without unit, a legal notice without e-mail)
and 4 false alarms (newsletter, «Swiss Design» label, tracking, a sole trader's company name).

## 2. Real shops audited against the live websites

Every verdict was compared with an audit made by independent Claude reviewer agents that opened the live
shop, read the legal pages and recorded the true status with a short quote. These are LLM audits with
live evidence, not a lawyer's opinion. Reports and audit keys quote third-party sites and stay local;
here they appear only in aggregate or anonymised. Measured with `python src/evaluate_audit.py`.

| | Shops | Agreement | Clear defects found | Reported defects real | False alarms |
|---|---:|---:|---:|---:|---:|
| Development shops, before the audit fixes | 21 | 63 % | 71 % | 58 % | 48 |
| Development shops, after the audit fixes | 21 | 72 % | 68 % | 71 % | 25 |
| **Hold-out: new shops, audited blind** | **10** | **63 %** | **55 % (16/29)** | **63 % (29/46)** | **17** |

- *Development shops*: 21 public Swiss shops from one-person Shopify shops to national retailers. The
  fixes were developed on them, and the reviewers saw the tool's earlier verdicts, so these numbers flatter the tool.
- *Hold-out*: 10 shops the tool had never seen (5 small Shopify shops, 5 large retailers). The audit was
  made blind before the tool ran; nothing was tuned afterwards. This is the honest estimate.
- On the hold-out the tool errs mostly on the cautious side: «unclear» or «partial» where the auditor saw
  «fulfilled». 5 of the 13 missed defects were reported as «unclear», i.e. flagged for manual review.

Agreement per checkpoint – where the tool is reliable and where it is not yet:

| Checkpoint | Development shops (21) | Hold-out (10) |
|---|---:|---:|
| Identität und Kontaktadresse inkl. E-Mail | 18/21 | 8/10 |
| Firma wie im Handelsregister, UID | 18/21 | 7/10 |
| Hinweis auf die technischen Schritte zum Vertragsschluss | 11/21 | 1/10 |
| Eingabefehler vor der Bestellung erkennen und korrigieren | 18/21 | 6/10 |
| Unverzügliche elektronische Bestellbestätigung | 14/21 | 6/10 |
| Tatsächlich zu bezahlender Preis in CHF | 17/21 | 8/10 |
| Abgaben und Zuschläge im Preis inbegriffen | 15/21 | 8/10 |
| Streich- und Vergleichspreise korrekt | 14/21 | 3/10 |
| Datenschutzerklärung mit Mindestangaben | 16/21 | 8/10 |
| Bekanntgabe ins Ausland offengelegt | 12/21 | 5/10 |
| Cookies und Tracking transparent erklärt | 7/21 | 1/10 |
| Newsletter nur mit Einwilligung und Abmeldemöglichkeit | 12/21 | 6/10 |
| Keine unrichtigen oder irreführenden Angaben | 18/21 | 9/10 |
| Klima-Aussagen belegt | 16/21 | 9/10 |
| Herkunftsangaben («Swiss Made», Schweizerkreuz) zutreffend | 16/21 | 4/10 |
| Keine offensichtlich missbräuchlichen AGB-Klauseln | 16/21 | 9/10 |
| AGB vorhanden, auffindbar und Schweizer Recht | 17/21 | 8/10 |
| Keine unpassenden EU-Vorlagen (DSGVO/BGB) statt Schweizer Recht | 16/21 | 7/10 |

The weakest checkpoints on new shops are the order steps (the checkout cannot be seen, so the tool says
«unclear» where the terms describe the process), cookies and tracking (the model demands every tool by name),
strike-through prices and Swiss origin claims. These are the next things to improve.

Hold-out per shop (anonymised):

| Hold-out shop | Size | Score | Agreement | False alarms | Missed |
|---|---|---:|---:|---:|---:|
| Shop H1 | small (Shopify) | 71 | 12/18 | 2 | 1 |
| Shop H2 | small (Shopify) | 59 | 7/18 | 2 | 3 |
| Shop H3 | small (Shopify) | 74 | 11/18 | 2 | 1 |
| Shop H4 | small (Shopify) | 69 | 12/18 | 0 | 3 |
| Shop H5 | small (Shopify) | 70 | 13/18 | 2 | 1 |
| Shop H6 | large retailer | 79 | 14/18 | 1 | 2 |
| Shop H7 | large retailer | 66 | 10/18 | 4 | 0 |
| Shop H8 | large retailer | 80 | 12/18 | 1 | 1 |
| Shop H9 | large retailer | 72 | 11/18 | 1 | 1 |
| Shop H10 | large retailer | 68 | 11/18 | 2 | 0 |

## 3. Page discovery

Measured with `python src/evaluate_crawler.py` on the 21 reachable development shops (no model involved):
legal notice found on 18, privacy policy on 17, terms on 18, shipping/returns on 20, a product page and
the footer on all 21. The remaining gaps are pages that exist only through JavaScript or behind bot protection;
they are reported as «not visible», never as «missing».

## 4. Cost and speed

| | Tokens per shop | Cost at list price | Duration |
|---|---:|---:|---|
| Test shop | about 26 000 | USD 0.003 | 15–100 s |
| Real shop (long legal texts) | about 119 000 | USD 0.012 (max. 0.019) | 1–4 min, depending on endpoint load |
| Local 4-bit model on a laptop | – | no cost per call | about 1 min |

## 5. What is not measured here

- Apertus 1.5 70B was measured only with an earlier prompt version (92 % recall, 79 % precision on the test
  shops). A re-run on the last evening failed because the shared endpoint was overloaded.
- The test set is small and the real-shop audits are LLM audits; the numbers show tendencies, not certified accuracy.
