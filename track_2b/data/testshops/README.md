# Testshops

Erfundene Online-Shops zum Messen des Compliance-Checks. Alle Namen, Adressen
und Domains (`.example`) sind fiktiv.

Pro Shop ein Ordner:

- `startseite.md`, `impressum.md`, `datenschutz.md`, `agb.md`, `versand.md`,
  `produkt-1.md`, `checkout.md`: eine Datei pro Seite. Der Dateiname bestimmt den Seitentyp.
- `shop.json`: Lösungsblatt mit den eingebauten Mängeln und dem erwarteten
  Status für jeden der 18 Prüfpunkte (`erwartet`).

Einen Shop prüfen: `make check SHOP=testshop:bergwiese`
Alle messen: `make eval`
