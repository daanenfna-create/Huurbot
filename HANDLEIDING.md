# Huurbot — installatiehandleiding

Deze bot checkt 3x per dag (09:30, 13:00, 17:00) negen verhuurderssites op
nieuwe huurwoningen in Nijmegen en Lent, en mailt je de nieuwe. Hij draait
gratis op GitHub Actions, dus je computer hoeft niet aan te staan.

Volg de stappen hieronder precies. Je hoeft niets te programmeren, alleen
klikken en plakken. Reken op ongeveer een uur de eerste keer.

---

## Wat je nodig hebt

1. Een GitHub-account (gratis)
2. Een Gmail-adres
3. Een Gmail "app-wachtwoord" (leg ik uit in stap 2)

---

## Stap 1 — GitHub-account maken

1. Ga naar https://github.com en klik op "Sign up".
2. Maak een account aan met je e-mailadres. Het is gratis.
3. Bevestig je e-mailadres via de mail die je krijgt.

---

## Stap 2 — Gmail app-wachtwoord aanmaken

Een gewoon Gmail-wachtwoord werkt niet voor scripts. Je hebt een speciaal
"app-wachtwoord" nodig. Zo maak je dat:

1. Je Google-account moet tweestapsverificatie aan hebben staan.
   Ga naar https://myaccount.google.com/security en zet "Verificatie in
   twee stappen" aan als dat nog niet zo is.
2. Ga daarna naar https://myaccount.google.com/apppasswords
3. Geef het een naam, bijvoorbeeld "Huurbot", en klik op "Maken".
4. Google toont een wachtwoord van 16 letters (vier blokjes van vier).
   Schrijf dit op of kopieer het. Je ziet het maar één keer.
   Dit is je GMAIL_APP_WACHTWOORD. (De spaties mag je laten staan of weghalen.)

---

## Stap 3 — De code op GitHub zetten

1. Ga naar https://github.com/new om een nieuwe repository te maken.
2. Geef hem een naam, bijvoorbeeld "huurbot".
3. Kies "Private" (zo kan niemand anders je instellingen zien).
4. Klik op "Create repository".
5. Op de volgende pagina klik je op de link "uploading an existing file"
   (staat in de tekst "…or push an existing repository…", of zoek de knop
   "Add file" > "Upload files").
6. Sleep ALLE bestanden uit het zip-bestand dat je van Claude hebt gekregen
   in het uploadvak. Let op: de map ".github" moet je mee uploaden, want
   daar staat de planner in. Het makkelijkst: pak het zip uit op je computer
   en sleep de hele inhoud erin.
7. Klik onderaan op "Commit changes".

> Lukt het slepen van de .github map niet via de browser? Dat kan gebeuren.
> Vraag Claude dan om hulp met "GitHub Desktop", een gratis programma dat dit
> makkelijker maakt.

---

## Stap 4 — Je geheime gegevens instellen

De bot heeft je Gmail-gegevens nodig, maar die zet je NIET in de code. Je
zet ze in de beveiligde "Secrets" van GitHub.

1. In je repository, klik bovenaan op "Settings".
2. In het linkermenu: "Secrets and variables" > "Actions".
3. Klik op "New repository secret" en maak deze drie aan (één voor één):

   - Naam: `GMAIL_ADRES`
     Waarde: je volledige Gmail-adres, bijv. jouwnaam@gmail.com

   - Naam: `GMAIL_APP_WACHTWOORD`
     Waarde: het 16-letter app-wachtwoord uit stap 2

   - Naam: `ONTVANGER_ADRES`
     Waarde: het adres waar je de meldingen wil ontvangen
     (mag hetzelfde zijn als GMAIL_ADRES)

4. Klik bij elk op "Add secret".

---

## Stap 5 — Testen

1. In je repository, klik bovenaan op "Actions".
2. Als GitHub vraagt of je workflows wil inschakelen, klik op de groene knop
   om ze aan te zetten.
3. Klik links op "Huurbot check".
4. Klik rechts op "Run workflow" > "Run workflow".
5. Wacht een paar minuten. Ververs de pagina. Je ziet een gele cirkel
   (bezig) die groen (gelukt) of rood (fout) wordt.
6. Bij de allereerste run zijn ALLE woningen "nieuw", dus je krijgt een mail
   met veel woningen. Dat is normaal en eenmalig. Daarna krijg je alleen nog
   echt nieuwe woningen.

> Krijg je geen mail? Check je spam. En klik op de run om de logs te zien;
> daar staat wat er gebeurde. Je kunt die tekst aan Claude laten zien.

---

## Klaar!

Vanaf nu draait de bot automatisch om 09:30, 13:00 en 17:00. Je hoeft niets
meer te doen. Bij nieuwe woningen krijg je vanzelf een mail.

---

## Goed om te weten

- De tijden staan ingesteld op NL-zomertijd. In de winter verschuift het een
  uur (naar 8:30, 12:00, 16:00). Wil je dat exact houden, vraag Claude om de
  tijden aan te passen.
- Sommige sites laden lastig of hebben botbeveiliging. Lukt een site niet
  dan staat dat onderaan je mail vermeld, en blijven de andere sites gewoon
  werken.
- Wil je een site toevoegen of verwijderen? Dat staat bovenaan in
  check_woningen.py in de lijst SITES. Vraag Claude gerust om hulp.
