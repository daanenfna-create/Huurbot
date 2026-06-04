name: Huurbot check

# Wanneer draait dit?
on:
  # Elk kwartier, maar alleen tijdens kantooruren op werkdagen.
  # Gratis omdat de repository openbaar (public) is.
  # Let op: GitHub draait op UTC. NL is in de zomer UTC+2, in de winter UTC+1.
  # Onderstaande dekt 9:00 t/m 17:45 NL-zomertijd (7-15 UTC), ma t/m vr.
  # ("*/15" = minuut 0,15,30,45 ; "7-15" = die uren ; "1-5" = ma-vr)
  schedule:
    - cron: "*/15 7-15 * * 1-5"
  # Hiermee kun je hem ook handmatig starten via de GitHub-knop (handig om te testen)
  workflow_dispatch:

# Nodig zodat de bot zijn 'seen.json' kan terugschrijven naar de repo
permissions:
  contents: write

jobs:
  check:
    runs-on: ubuntu-latest
    steps:
      - name: Code ophalen
        uses: actions/checkout@v6

      - name: Python installeren
        uses: actions/setup-python@v6
        with:
          python-version: "3.12"

      - name: Pakketten installeren
        run: |
          pip install -r requirements.txt
          python -m playwright install --with-deps chromium

      - name: Woningen checken
        env:
          GMAIL_ADRES: ${{ secrets.GMAIL_ADRES }}
          GMAIL_APP_WACHTWOORD: ${{ secrets.GMAIL_APP_WACHTWOORD }}
          ONTVANGER_ADRES: ${{ secrets.ONTVANGER_ADRES }}
        run: python check_woningen.py

      - name: Stand opslaan (seen.json bijwerken)
        run: |
          git config user.name "huurbot"
          git config user.email "huurbot@users.noreply.github.com"
          git add seen.json
          git commit -m "Stand bijgewerkt" || echo "Niets veranderd"
          git push || echo "Niets om te pushen"
