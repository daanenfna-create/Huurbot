#!/usr/bin/env python3
"""
Huurbot - checkt verhuurderssites op nieuwe woningen en mailt je de nieuwe.

Werkt zo:
1. Bezoekt elke site uit SITES en haalt de woning-links eruit.
2. Vergelijkt met de vorige keer (opgeslagen in seen.json).
3. Mailt je alleen de NIEUWE woningen.
4. Slaat de nieuwe stand op zodat de volgende run weet wat al gezien is.

Sites die hun aanbod via JavaScript laden worden gerenderd met Playwright.
"""

import json
import os
import re
import smtplib
import sys
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from pathlib import Path
from urllib.parse import urljoin, urlparse

from playwright.sync_api import sync_playwright

# --------------------------------------------------------------------------
# De sites die we volgen.
# "patroon" is een stukje tekst dat in de link van een woning voorkomt.
# Zo onderscheiden we echte woningen van menu-links e.d.
# --------------------------------------------------------------------------
SITES = [
    {
        "naam": "ST Makelaars",
        "url": "https://stmakelaars.nl/wonen/aanbod?buy_rent=rent&order_by=created_at-desc&page=1",
        "patroon": "/wonen/",
    },
    {
        "naam": "Hans Janssen",
        "url": "https://www.hansjanssen.nl/wonen/zoeken/heel-nederland/huur/",
        "patroon": "/wonen/",
    },
    {
        "naam": "Soof Verhuurmakelaar",
        "url": "https://soofverhuurmakelaar.nl/woningaanbod/huur",
        "patroon": "/woningaanbod/",
    },
    {
        "naam": "123Wonen Nijmegen",
        "url": "https://www.123wonen.nl/huurwoningen/in/nijmegen",
        "patroon": "/huurwoning",
    },
    {
        "naam": "Rebo Groep",
        "url": "https://www.rebogroep.nl/nl/particulier/ons-aanbod/huren?page=1",
        "patroon": "/aanbod/",
    },
    {
        "naam": "Vesteda Nijmegen",
        "url": "https://www.vesteda.com/nl/woning-zoeken?placeType=1&sortType=0&radius=10&s=Nijmegen,+Nederland&sc=woning&latitude=51.84328&longitude=5.8609314&filters=&priceFrom=500&priceTo=9999",
        "patroon": "/nl/woning/",
    },
    {
        "naam": "Ik Wil Huren",
        "url": "https://ikwilhuren.nu/aanbod/",
        "patroon": "/aanbod/",
    },
    {
        "naam": "BPD Woningfonds",
        "url": "https://hurenbij.bpdwoningfonds.nl/aanbod/",
        "patroon": "/aanbod/",
    },
    {
        "naam": "Corpowonen Woonwaarts",
        "url": "https://www.corpowonen.nl/aanbod/huur/heel-nederland/corporatie-woonwaarts",
        "patroon": "/aanbod/",
    },
]

SEEN_FILE = Path("seen.json")

# --------------------------------------------------------------------------
# Plaatsfilter. Alleen woningen waarvan de link OF de kaarttekst Nijmegen of
# Lent bevat, worden meegenomen. "nijmegen" mag overal in voorkomen; "lent"
# telt alleen als los woord (zodat 'talent' of 'lente' niet meetelt).
# Wil je later een plaats toevoegen, vraag Claude om de filterregel aan te
# passen, want elke plaats heeft zijn eigen valkuilen qua losse letters.
# --------------------------------------------------------------------------
PLAATSEN = ["nijmegen", "lent"]


def haal_woninglinks(page, site):
    """Open de site, wacht tot hij geladen is, en verzamel woning-links."""
    page.goto(site["url"], wait_until="networkidle", timeout=60000)
    # Even extra wachten voor sites die traag laden
    page.wait_for_timeout(3000)

    # Probeer een 'accepteer cookies' knop te klikken (faalt stilletjes als die er niet is)
    for tekst in ["Accepteren", "Akkoord", "Accept", "Alles accepteren", "Sta toe"]:
        try:
            knop = page.get_by_role("button", name=re.compile(tekst, re.I))
            if knop.count() > 0:
                knop.first.click(timeout=2000)
                page.wait_for_timeout(1500)
                break
        except Exception:
            pass

    basis = "{0.scheme}://{0.netloc}".format(urlparse(site["url"]))

    # Per link halen we niet alleen de href op, maar ook de zichtbare tekst
    # van het dichtstbijzijnde 'kaartje' eromheen. Zo kunnen we op plaatsnaam
    # filteren ook als die niet in de link zelf staat.
    items = page.eval_on_selector_all(
        "a[href]",
        """els => els.map(e => {
            // Zoek een logisch 'kaart'-element omhoog in de boom
            let kaart = e;
            for (let i = 0; i < 4 && kaart.parentElement; i++) {
                kaart = kaart.parentElement;
            }
            return {
                href: e.getAttribute('href'),
                tekst: (kaart.innerText || '').slice(0, 400)
            };
        })""",
    )

    gevonden = {}
    for item in items:
        href = item.get("href")
        if not href:
            continue
        if site["patroon"] not in href:
            continue
        vol = urljoin(basis, href)
        # Filter losse categorie-links eruit (geen specifieke woning)
        pad = urlparse(vol).path.rstrip("/")
        if pad.count("/") < 2:
            continue

        # ---- Plaatsfilter: alleen Nijmegen of Lent ----
        # We kijken naar de link én de tekst van het kaartje.
        haystack = (vol + " " + (item.get("tekst") or "")).lower()
        # "nijmegen" mag overal in voorkomen; "lent" alleen als heel woord
        # (anders matcht het ook op 'talent', 'lente', enz.)
        match = "nijmegen" in haystack or re.search(r"\blent\b", haystack)
        if not match:
            continue

        gevonden[vol] = vol
    return list(gevonden.keys())


def laad_seen():
    if SEEN_FILE.exists():
        try:
            return json.loads(SEEN_FILE.read_text())
        except Exception:
            return {}
    return {}


def bewaar_seen(data):
    SEEN_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False))


def stuur_mail(nieuwe_per_site, fouten):
    afzender = os.environ["GMAIL_ADRES"]
    wachtwoord = os.environ["GMAIL_APP_WACHTWOORD"]
    ontvanger = os.environ.get("ONTVANGER_ADRES", afzender)

    regels = ["<h2>Nieuwe huurwoningen gevonden!</h2>"]
    totaal = 0
    for site, links in nieuwe_per_site.items():
        if not links:
            continue
        totaal += len(links)
        regels.append(f"<h3>{site} ({len(links)} nieuw)</h3><ul>")
        for l in links:
            regels.append(f'<li><a href="{l}">{l}</a></li>')
        regels.append("</ul>")

    if fouten:
        regels.append("<h3>Sites die niet gecheckt konden worden</h3><ul>")
        for naam, fout in fouten.items():
            regels.append(f"<li>{naam}: {fout}</li>")
        regels.append("</ul>")

    html = "\n".join(regels)
    onderwerp = f"Huurbot: {totaal} nieuwe woning(en)"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = onderwerp
    msg["From"] = afzender
    msg["To"] = ontvanger
    msg.attach(MIMEText(html, "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(afzender, wachtwoord)
        server.sendmail(afzender, [ontvanger], msg.as_string())
    print(f"Mail verstuurd naar {ontvanger} ({totaal} nieuwe woningen).")


def main():
    seen = laad_seen()
    nieuwe_per_site = {}
    fouten = {}

    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            locale="nl-NL",
        )
        for site in SITES:
            naam = site["naam"]
            print(f"Check: {naam} ...")
            page = context.new_page()
            try:
                links = haal_woninglinks(page, site)
                eerder = set(seen.get(naam, []))
                nieuw = [l for l in links if l not in eerder]
                nieuwe_per_site[naam] = nieuw
                # Update de complete lijst van gezien
                seen[naam] = sorted(set(links) | eerder)
                print(f"  {len(links)} gevonden, waarvan {len(nieuw)} nieuw.")
            except Exception as e:
                fouten[naam] = str(e)[:200]
                print(f"  FOUT: {e}")
            finally:
                page.close()
        browser.close()

    bewaar_seen(seen)

    totaal_nieuw = sum(len(v) for v in nieuwe_per_site.values())
    if totaal_nieuw > 0:
        stuur_mail(nieuwe_per_site, fouten)
    else:
        print("Geen nieuwe woningen. Geen mail verstuurd.")
        if fouten:
            print("Wel fouten bij:", ", ".join(fouten))


if __name__ == "__main__":
    main()
