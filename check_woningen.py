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
# "patroon"  = stukje dat in de link van een ECHTE woning voorkomt.
# "negeer"   = lijst van stukjes; staat er een in de link, dan is het geen
#              woning maar een overzicht/zoek/menu-pagina en slaan we hem over.
# --------------------------------------------------------------------------
SITES = [
    {
        "naam": "ST Makelaars",
        "url": "https://stmakelaars.nl/wonen/aanbod?buy_rent=rent&order_by=created_at-desc&page=1",
        "patroon": "/wonen/aanbod/",
        "negeer": ["verkocht", "verhuurd"],
    },
    {
        "naam": "Hans Janssen",
        "url": "https://www.hansjanssen.nl/wonen/zoeken/heel-nederland/huur/",
        "patroon": "/wonen/object/",
        "negeer": ["/zoeken/", "/kaart/"],
    },
    {
        "naam": "Soof Verhuurmakelaar",
        "url": "https://soofverhuurmakelaar.nl/woningaanbod/huur",
        "patroon": "/woningaanbod/huur/",
        "negeer": [],
    },
    {
        "naam": "123Wonen Nijmegen",
        "url": "https://www.123wonen.nl/huurwoningen/in/nijmegen",
        "patroon": "/huurwoning/",
        "negeer": ["/in/"],
    },
    {
        "naam": "Rebo Groep",
        "url": "https://www.rebogroep.nl/nl/particulier/ons-aanbod/huren?page=1",
        "patroon": "/woning/",
        "negeer": ["/ons-aanbod/", "/kopen", "/huren"],
    },
    {
        "naam": "Vesteda Nijmegen",
        "url": "https://www.vesteda.com/nl/woning-zoeken?placeType=1&sortType=0&radius=10&s=Nijmegen,+Nederland&sc=woning&latitude=51.84328&longitude=5.8609314&filters=&priceFrom=500&priceTo=9999",
        "patroon": "/nl/woning/",
        "negeer": ["woning-zoeken"],
    },
    {
        "naam": "Ik Wil Huren",
        "url": "https://ikwilhuren.nu/aanbod/?straal=15&plaats=Nijmegen&sort=aanbodDESC",
        "patroon": "/object/",
        "negeer": [],
    },
    {
        "naam": "BPD Woningfonds",
        "url": "https://hurenbij.bpdwoningfonds.nl/aanbod/",
        "patroon": "/object/",
        "negeer": [],
    },
    {
        "naam": "Corpowonen Woonwaarts",
        "url": "https://www.corpowonen.nl/aanbod/huur/heel-nederland/corporatie-woonwaarts",
        "patroon": "/object/",
        "negeer": [],
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

# --------------------------------------------------------------------------
# Budgetfilter. Woningen duurder dan MAX_PRIJS (euro per maand) vallen weg.
# TOON_ZONDER_PRIJS bepaalt wat er gebeurt met woningen waarvan we GEEN prijs
# op de overzichtspagina kunnen vinden:
#   True  = toch tonen (je mist niets, maar krijgt soms te dure woningen)
#   False = weglaten (alleen woningen waarvan we zeker weten dat ze passen)
# --------------------------------------------------------------------------
MAX_PRIJS = 1400
TOON_ZONDER_PRIJS = True


def haal_prijs(tekst):
    """Zoek een huurprijs in de kaarttekst. Geeft bv. '€ 1.194' terug, of ''."""
    # Zoekt naar een euroteken gevolgd door een bedrag (met punt/komma).
    m = re.search(r"€\s?\d[\d.,]*", tekst)
    if m:
        return m.group(0).strip()
    return ""


def prijs_naar_getal(prijs):
    """Zet '€ 1.194' of '€1.250,50' om naar een geheel getal (1194 / 1250).

    In Nederland is de punt een duizendtalscheiding en de komma een decimaal.
    We zijn alleen geïnteresseerd in hele euro's. Geeft None als er geen
    bruikbaar bedrag in staat.
    """
    if not prijs:
        return None
    # Houd alleen cijfers, punten en komma's over.
    schoon = re.sub(r"[^\d.,]", "", prijs)
    if not schoon:
        return None
    # Knip een eventueel decimaalgedeelte (achter de komma) weg.
    schoon = schoon.split(",")[0]
    # Punten (duizendtallen) verwijderen.
    schoon = schoon.replace(".", "")
    if schoon.isdigit():
        return int(schoon)
    return None


def haal_adres(tekst, url):
    """Probeer het adres te bepalen.

    Eerst uit de kaarttekst (eerste zinnige regel, meestal de straat+nummer).
    Lukt dat niet, dan leiden we het af uit de link (bv.
    '.../steenstraat-19-nijmegen-nn105598' -> 'Steenstraat 19 Nijmegen').
    """
    # 1) Uit de kaarttekst: pak de eerste regel die op een adres lijkt.
    for regel in (tekst or "").splitlines():
        r = regel.strip()
        if not r:
            continue
        # Sla regels over die duidelijk geen adres zijn.
        laag = r.lower()
        if laag in ("te huur", "nieuw", "verhuurd"):
            continue
        if r.startswith("€") or r.startswith("Beschikbaar"):
            continue
        # Een adres bevat meestal een huisnummer (een cijfer).
        if re.search(r"\d", r) and len(r) < 60:
            return r

    # 2) Terugval: uit het laatste stuk van de link.
    pad = urlparse(url).path.rstrip("/")
    laatste = pad.split("/")[-1]
    # Haal codes als 'nn105598' of lange id's achteraan weg.
    laatste = re.sub(r"-?[a-z]{2}\d{4,}$", "", laatste)
    laatste = re.sub(r"-?\d{4,}$", "", laatste)
    # Splits op streepjes en gooi 'woorden' weg die eigenlijk codes zijn
    # (lange reeksen met door elkaar cijfers en letters, of postcodes).
    ruwe = [w for w in laatste.split("-") if w]
    woorden = []
    for w in ruwe:
        # Postcode-achtig (1096gg) of lange hex-code (a922680760a64e) overslaan
        if re.fullmatch(r"\d{4}[a-z]{0,2}", w):
            continue
        if len(w) >= 10 and re.search(r"\d", w) and re.search(r"[a-z]", w):
            continue
        woorden.append(w)
    if woorden:
        return " ".join(w.capitalize() for w in woorden)
    return ""


def is_verhuurd(tekst):
    """True als de woning al verhuurd/onder optie is (dan willen we hem niet)."""
    laag = tekst.lower()
    woorden = ["verhuurd", "onder optie", "in optie", "niet beschikbaar"]
    return any(w in laag for w in woorden)


def haal_woninglinks(page, site):
    """Open de site, wacht tot hij geladen is, en verzamel echte woningen.

    Geeft een lijst van dicts terug: {"url": ..., "prijs": ...}
    """
    # We wachten op 'domcontentloaded' i.p.v. 'networkidle'. Sommige sites
    # (zoals Rebo) hebben constant achtergrondverkeer waardoor 'networkidle'
    # nooit bereikt wordt en je een timeout krijgt. Daarna geven we de pagina
    # met een vaste wachttijd de kans om de woningen (via JavaScript) te tonen.
    try:
        page.goto(site["url"], wait_until="domcontentloaded", timeout=60000)
    except Exception:
        # Laatste poging: gewoon openen zonder op een toestand te wachten.
        page.goto(site["url"], wait_until="commit", timeout=60000)
    # Geef JavaScript-sites tijd om hun aanbod in te laden.
    page.wait_for_timeout(6000)

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

    # Per link halen we de href op én de tekst van het dichtstbijzijnde
    # 'kaartje'. We pakken een KLEINER kaartje (2 niveaus omhoog) zodat de
    # tekst van buurwoningen niet uitlekt naar deze woning.
    items = page.eval_on_selector_all(
        "a[href]",
        """els => els.map(e => {
            let kaart = e;
            for (let i = 0; i < 2 && kaart.parentElement; i++) {
                kaart = kaart.parentElement;
            }
            return {
                href: e.getAttribute('href'),
                tekst: (kaart.innerText || '').slice(0, 300)
            };
        })""",
    )

    gevonden = {}
    for item in items:
        href = item.get("href")
        if not href:
            continue

        # Moet het woning-patroon bevatten ...
        if site["patroon"] not in href:
            continue
        # ... en geen van de te negeren stukjes.
        if any(stuk in href for stuk in site.get("negeer", [])):
            continue

        vol = urljoin(basis, href)
        # Link moet een eigen woningpagina zijn, niet een losse categorie.
        pad = urlparse(vol).path.rstrip("/")
        if pad.count("/") < 2:
            continue

        tekst = item.get("tekst") or ""

        # ---- Al verhuurd? Dan overslaan. ----
        if is_verhuurd(tekst):
            continue

        # ---- Plaatsfilter: alleen Nijmegen of Lent ----
        haystack = (vol + " " + tekst).lower()
        match = "nijmegen" in haystack or re.search(r"\blent\b", haystack)
        if not match:
            continue

        # Prijs en adres erbij zoeken (mogen leeg blijven)
        prijs = haal_prijs(tekst)
        adres = haal_adres(tekst, vol)

        # ---- Budgetfilter ----
        bedrag = prijs_naar_getal(prijs)
        if bedrag is not None:
            # We kennen de prijs: te duur? dan overslaan.
            if bedrag > MAX_PRIJS:
                continue
        else:
            # We kennen de prijs niet. Afhankelijk van de instelling tonen of niet.
            if not TOON_ZONDER_PRIJS:
                continue

        # Bewaar; als we deze woning al hadden maar nu mét prijs, vul aan.
        if vol not in gevonden or (prijs and not gevonden[vol]["prijs"]):
            gevonden[vol] = {"url": vol, "prijs": prijs, "adres": adres}

    return list(gevonden.values())


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
    # .strip() haalt per ongeluk meegekomen spaties/enters weg, zodat een
    # onzichtbaar 'newline'-teken achter een adres geen fout meer geeft.
    afzender = os.environ["GMAIL_ADRES"].strip()
    wachtwoord = os.environ["GMAIL_APP_WACHTWOORD"].strip()
    ontvanger_ruw = os.environ.get("ONTVANGER_ADRES", afzender)
    # Sta meerdere ontvangers toe, gescheiden door komma of puntkomma.
    ontvangers = [
        a.strip()
        for a in re.split(r"[,;]", ontvanger_ruw)
        if a.strip()
    ]
    if not ontvangers:
        ontvangers = [afzender]

    regels = ["<h2>Nieuwe huurwoningen gevonden!</h2>"]
    totaal = 0
    for site, woningen in nieuwe_per_site.items():
        if not woningen:
            continue
        totaal += len(woningen)
        regels.append(f"<h3>{site} ({len(woningen)} nieuw)</h3><ul>")
        for w in woningen:
            adres = w.get("adres") or "Adres onbekend"
            prijs = w.get("prijs") or ""
            prijs_html = f" — <strong>{prijs} p/m</strong>" if prijs else ""
            regels.append(
                f'<li><strong>{adres}</strong>{prijs_html}<br>'
                f'<a href="{w["url"]}">{w["url"]}</a></li>'
            )
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
    msg["To"] = ", ".join(ontvangers)
    msg.attach(MIMEText(html, "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(afzender, wachtwoord)
        server.sendmail(afzender, ontvangers, msg.as_string())
    print(f"Mail verstuurd naar {', '.join(ontvangers)} ({totaal} nieuwe woningen).")


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
                woningen = haal_woninglinks(page, site)
                eerder = set(seen.get(naam, []))
                # Nieuw = woningen waarvan de URL nog niet eerder gezien is
                nieuw = [w for w in woningen if w["url"] not in eerder]
                nieuwe_per_site[naam] = nieuw
                # Update de complete lijst van geziene URL's
                alle_urls = {w["url"] for w in woningen} | eerder
                seen[naam] = sorted(alle_urls)
                print(f"  {len(woningen)} gevonden, waarvan {len(nieuw)} nieuw.")
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
