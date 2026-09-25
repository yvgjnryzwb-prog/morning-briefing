# Morgen-Nachrichten

Ein schnelles Nachrichten-Dashboard: Schlagzeilen aus Welt, Deutschland, Wirtschaft,
Tech & Wissen und internationalen Quellen auf einer Seite. Es wird jeden Morgen um
**6:00 Uhr (Berliner Zeit)** automatisch neu gebaut und über GitHub Pages veröffentlicht.

## Aufbau

| Datei | Zweck |
| --- | --- |
| `news/feeds.json` | Quellen (RSS/Atom) pro Rubrik, Zeitfenster, Anzahl Meldungen |
| `news/build.py` | Lädt die Feeds und erzeugt `site/index.html` (nur Python-Standardbibliothek) |
| `news/briefing.py` | Macht aus den Meldungen ein vorlesbares Morning-Briefing (`site/briefing.json`, `.txt`) |
| `news/briefing.js` | Sprachassistent im Browser: Abspielen, Vorlesen, Sprachsteuerung |
| `news/tts.py` | Vertont das Briefing mit Neural-Stimmen (edge-tts) als `site/briefing.mp3` |
| `.github/workflows/news-dashboard.yml` | Zeitplan 6:00 Uhr + Veröffentlichung auf GitHub Pages |

## Einrichtung (einmalig)

1. Diesen Branch in den Standard-Branch mergen. Geplante Workflows laufen nur dort.
2. Unter **Settings → Pages → Build and deployment → Source** die Option **GitHub Actions** wählen.
3. Unter **Actions → Nachrichten-Dashboard → Run workflow** den ersten Lauf starten.
   Danach ist das Dashboard unter `https://<user>.github.io/<repo>/` erreichbar.

## Morning-Briefing (Sprachassistent)

Oben auf der Seite liest ein Player die Nachrichten als Briefing vor: Begrüßung mit Datum,
die Top-Meldungen mit Kurzfassung, danach je Rubrik die wichtigsten weiteren Schlagzeilen.
Englische Meldungen werden mit einer englischen Stimme gelesen.

**Stimme:** Der Workflow vertont das Briefing jeden Morgen mit einer Microsoft-Neural-Stimme
([edge-tts](https://github.com/rany2/edge-tts), kostenlos, ohne Konto) als MP3. Die läuft auch bei
gesperrtem Handy weiter, mit Pause und Kapitel vor/zurück auf dem Sperrbildschirm. edge-tts nutzt
eine inoffizielle Schnittstelle: Fällt sie aus, fehlt nur die MP3 und der Browser liest wie
bisher mit seinen eigenen Stimmen vor. Stimme und Tempo stehen in `news/feeds.json` unter `"tts"`
(Liste aller Stimmen: `edge-tts --list-voices`, z. B. `de-DE-KatjaNeural`, `de-DE-ConradNeural`,
`de-DE-FlorianMultilingualNeural`; Tempo z. B. `"+10%"`).

- **Bedienung:** ▶ / ⏸, Kapitel vor/zurück, Tempo, Stimme; Tastatur: `B` Start/Pause, `N`/`P` Kapitel.
  Ein Klick auf ein Kapitel springt direkt dorthin. Mit `?play` in der Adresse startet es sofort
  (sofern der Browser Ton ohne Klick zulässt).
- **Sprachsteuerung** (🎤, Chrome/Edge/Safari): „weiter“, „zurück“, „Pause“, „von vorne“,
  „schneller“, „langsamer“, „Stopp“ oder ein Rubrikname wie „Wirtschaft“. Nur kurze Befehle
  zählen, damit der Assistent nicht auf seine eigene Stimme reagiert – mit Kopfhörern klappt es
  am zuverlässigsten. Hinweis: Chrome schickt die Mikrofon-Aufnahme zur Erkennung an Google.
- **Browser-Stimmen** (nur ohne MP3): kommen vom Betriebssystem. Die natürlichsten liefern meist Edge („Online (Natural)“)
  und macOS/iOS („Premium“/„Erweitert“, in den Bedienungshilfen nachladbar).
- **Einstellungen** in `news/feeds.json` unter `"briefing"`: `top_items`, `items_per_category`,
  `summaries`. Eine Rubrik mit `"briefing": false` wird übersprungen, `"lang"` setzt ihre Sprache.
- **Bewerbungsstand (GMX, Web.de, Gmail):** Nach der Begrüßung fasst das Briefing die
  Rückmeldungen auf Bewerbungen seit gestern zusammen, z. B. „eine Einladung zum Gespräch, zwei
  Absagen“. **Nur Zahlen, keine Firmen**, weil Seite, MP3 und Actions-Log öffentlich sind.
  Erkannt werden Jobangebote, Einladungen, Absagen und Eingangsbestätigungen (deutsch/englisch,
  per Stichwort im Mailtext), Jobportal-Newsletter werden ignoriert. Das Postfach wird nur lesend
  geöffnet, nichts wird als gelesen markiert. Der IMAP-Server ergibt sich aus der Adresse; andere
  Anbieter per `"mail": {"host": "imap.example.de"}` in `news/feeds.json`.
  Einrichtung: im Repo unter **Settings → Secrets and variables → Actions** zwei Secrets anlegen,
  `MAIL_USER` (Mailadresse) und `MAIL_PASSWORD`. Bei **GMX/Web.de** muss im Postfach unter
  *Einstellungen → POP3/IMAP-Abruf* der IMAP-Zugriff eingeschaltet sein; mit Zwei-Faktor-Anmeldung
  braucht es ein *anwendungsspezifisches Passwort*. Bei **Gmail** ein App-Passwort von
  <https://myaccount.google.com/apppasswords>. Ohne Secrets entfällt der Abschnitt.
  **Ohne Passwort:** Liegt `news/applications.json` vom selben Tag vor, nutzt das Briefing diese
  Zahlen statt IMAP. Die Datei schreibt eine tägliche Claude-Routine (ca. 5:40 Uhr) über den
  Gmail-Connector von claude.ai; sie enthält nur Datum und Zahlen, z. B.
  `{"date": "2026-09-26", "counts": {"einladung": 1, "absage": 2}}`.
  Optional nennt das Briefing zusätzlich die Zahl wichtiger neuer Mails (ungelesen, ohne
  Newsletter, Massen- und No-Reply-Mails): `"mail": {"important": true}` in `news/feeds.json`.
- `site/briefing.txt` enthält das Briefing als reinen Text, z. B. für externe TTS-Dienste.

## Lokal ausprobieren

```bash
python3 news/build.py --out site/index.html            # ohne MP3
pip install edge-tts && python3 news/build.py --audio  # mit Neural-Stimme
open site/index.html   # oder im Browser öffnen
```

## Anpassen

- **Quellen:** Einträge in `news/feeds.json` ergänzen oder entfernen. `"top": true` bringt die
  Spitzenmeldung dieses Feeds in den Bereich „Auf einen Blick“.
- **Menge:** `items_per_category` (Meldungen pro Rubrik) und `max_age_hours` (maximales Alter).
- **Uhrzeit:** die beiden `cron`-Zeilen und die Offsets im Check-Schritt des Workflows.

## Hinweise

- GitHub startet geplante Workflows bei hoher Last manchmal einige Minuten zu spät.
- Bei öffentlichen Repos pausiert GitHub Zeitpläne nach 60 Tagen ohne Repo-Aktivität.
  Der Workflow lässt sich dann unter **Actions** mit einem Klick wieder aktivieren.
- Ist ein Feed nicht erreichbar, wird er übersprungen und unten auf der Seite erwähnt.
