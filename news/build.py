#!/usr/bin/env python3
"""Baut das Nachrichten-Dashboard als statische HTML-Seite aus RSS/Atom-Feeds.

Nur Standardbibliothek. Aufruf:  python news/build.py [--out site/index.html]
"""
import argparse
import concurrent.futures
import html
import json
import re
import shutil
import sys
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from briefing import MONTHS, WEEKDAYS, build_briefing, plain_text
from mail import (MailError, applications_sentence, check_mailbox, load_applications_file,
                  mail_sentence)

HERE = Path(__file__).resolve().parent
TZ = ZoneInfo("Europe/Berlin")
USER_AGENT = "Mozilla/5.0 (compatible; NewsDashboard/1.0)"


def fetch(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def local(tag):
    """Tag-Name ohne XML-Namespace."""
    return tag.rsplit("}", 1)[-1]


def child_text(el, *names):
    for child in el:
        if local(child.tag) in names and (child.text or "").strip():
            return child.text.strip()
    return ""


def parse_date(value):
    if not value:
        return None
    try:
        dt = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def clean(text, limit=220):
    text = re.sub(r"<[^>]+>", " ", html.unescape(text or ""))
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > limit:
        text = text[:limit].rsplit(" ", 1)[0] + " …"
    return text


def parse_feed(data):
    """Liest RSS 2.0, RDF/RSS 1.0 und Atom. Liefert Liste von dicts."""
    root = ET.fromstring(data)
    items = []
    for el in root.iter():
        kind = local(el.tag)
        if kind not in ("item", "entry"):
            continue
        link = child_text(el, "link")
        if not link:  # Atom: <link href="..."/>
            for child in el:
                if local(child.tag) == "link" and child.get("rel", "alternate") == "alternate":
                    link = child.get("href", "")
                    break
        title = clean(child_text(el, "title"), 200)
        if not title or not link:
            continue
        items.append({
            "title": title,
            "link": link.strip(),
            "summary": clean(child_text(el, "description", "summary", "content")),
            "summary_long": clean(child_text(el, "description", "summary", "content"), 600),
            "date": parse_date(child_text(el, "pubDate", "date", "published", "updated")),
        })
    return items


def load_feed(feed):
    try:
        items = parse_feed(fetch(feed["url"]))
    except Exception as exc:  # ein kaputter Feed soll das Dashboard nicht verhindern
        print(f"WARN {feed['name']} ({feed['url']}): {exc}", file=sys.stderr)
        return feed, None
    for rank, item in enumerate(items):
        item["source"] = feed["name"]
        item["rank"] = rank
    return feed, items


def norm_title(title):
    return re.sub(r"\W+", "", title.lower())[:80]


def collect(config, now):
    cutoff = now - timedelta(hours=config.get("max_age_hours", 30))
    per_cat = config.get("items_per_category", 10)
    feeds = [f for c in config["categories"] for f in c["feeds"]]
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        results = {id(f): items for f, items in pool.map(load_feed, feeds)}

    seen, top, sections, failed = set(), [], [], []
    for cat in config["categories"]:
        pool_items = []
        for feed in cat["feeds"]:
            items = results[id(feed)]
            if items is None:
                failed.append(feed["name"] + " · " + cat["title"])
                continue
            fresh = [i for i in items if i["date"] is None or i["date"] >= cutoff]
            if feed.get("top") and fresh:
                top.append(dict(fresh[0], category=cat["title"]))
            pool_items.extend(fresh)
        # Neueste zuerst, Einträge ohne Datum nach Feed-Reihenfolge ans Ende
        pool_items.sort(key=lambda i: (i["date"] is None,
                                       -(i["date"].timestamp() if i["date"] else 0), i["rank"]))
        picked = []
        for item in pool_items:
            key = norm_title(item["title"])
            if key in seen:
                continue
            seen.add(key)
            picked.append(item)
            if len(picked) >= per_cat:
                break
        sections.append({"id": cat["id"], "title": cat["title"], "items": picked})
    return top, sections, failed


def fmt_time(dt, now):
    if dt is None:
        return ""
    local_dt = dt.astimezone(TZ)
    if local_dt.date() == now.astimezone(TZ).date():
        return local_dt.strftime("%H:%M")
    return local_dt.strftime("%d.%m. %H:%M")


def esc(value):
    return html.escape(value or "", quote=True)


def render(top, sections, failed, now, briefing):
    local_now = now.astimezone(TZ)
    date_str = f"{WEEKDAYS[local_now.weekday()]}, {local_now.day}. {MONTHS[local_now.month - 1]} {local_now.year}"
    total = sum(len(s["items"]) for s in sections)

    top_html = "\n".join(
        f'''<a class="lead" href="{esc(i["link"])}" target="_blank" rel="noopener">
  <span class="meta"><b>{esc(i["category"])}</b> · {esc(i["source"])} {esc(fmt_time(i["date"], now))}</span>
  <span class="lead-title">{esc(i["title"])}</span>
  <span class="lead-sum">{esc(i["summary"])}</span>
</a>''' for i in top)

    nav_html = "".join(f'<a href="#{esc(s["id"])}">{esc(s["title"])}</a>' for s in sections)

    section_html = []
    for s in sections:
        rows = "\n".join(
            f'''<li><a href="{esc(i["link"])}" target="_blank" rel="noopener" title="{esc(i["summary"])}">
  <span class="t">{esc(i["title"])}</span>
  <span class="meta">{esc(i["source"])} {esc(fmt_time(i["date"], now))}</span>
</a></li>''' for i in s["items"]) or '<li class="empty">Keine aktuellen Meldungen.</li>'
        section_html.append(
            f'<section id="{esc(s["id"])}"><h2>{esc(s["title"])}</h2><ol>{rows}</ol></section>')

    failed_html = (f'<p class="warn">Nicht erreichbar: {esc(", ".join(failed))}</p>' if failed else "")

    return TEMPLATE.format(
        date=esc(date_str),
        updated=local_now.strftime("%H:%M"),
        iso=now.isoformat(timespec="seconds"),
        total=total,
        nav=nav_html,
        top=top_html or '<p class="empty">Keine Top-Meldungen verfügbar.</p>',
        sections="\n".join(section_html),
        failed=failed_html,
        briefing_minutes=briefing["minutes"],
        briefing_json=json.dumps(briefing, ensure_ascii=False).replace("</", "<\\/"),
    )


TEMPLATE = """<!doctype html>
<html lang="de">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Morgen-Nachrichten</title>
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>📰</text></svg>">
<style>
:root {{
  --bg: #f6f5f1; --card: #ffffff; --ink: #1c1c1a; --muted: #6b6a64;
  --line: #e4e2da; --accent: #b3261e; --hover: #f0eee7;
}}
@media (prefers-color-scheme: dark) {{
  :root {{ --bg: #141413; --card: #1d1d1b; --ink: #ecebe6; --muted: #9a998f;
          --line: #2e2d2a; --accent: #ff8a7a; --hover: #262522; }}
}}
* {{ box-sizing: border-box; }}
body {{ margin: 0; background: var(--bg); color: var(--ink);
  font: 16px/1.45 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; }}
a {{ color: inherit; text-decoration: none; overflow-wrap: anywhere; }}
.wrap {{ max-width: 1200px; margin: 0 auto; padding: 24px 16px 48px; }}
header {{ display: flex; flex-wrap: wrap; justify-content: space-between; align-items: end;
  gap: 8px 24px; border-bottom: 3px solid var(--ink); padding-bottom: 12px; }}
h1 {{ margin: 0; font: 700 clamp(1.8rem, 5vw, 2.8rem)/1.1 Georgia, "Times New Roman", serif; }}
.date {{ color: var(--muted); }}
.stamp {{ color: var(--muted); font-size: .85rem; text-align: right; }}
nav {{ display: flex; gap: 6px; flex-wrap: wrap; margin: 14px 0 22px; }}
nav a {{ padding: 4px 12px; border: 1px solid var(--line); border-radius: 99px;
  font-size: .85rem; background: var(--card); }}
nav a:hover {{ border-color: var(--accent); color: var(--accent); }}
h2 {{ font: 700 1.05rem/1.2 system-ui, sans-serif; text-transform: uppercase;
  letter-spacing: .06em; margin: 0 0 10px; color: var(--accent); }}
.leads {{ display: grid; gap: 12px; grid-template-columns: repeat(auto-fill, minmax(min(260px, 100%), 1fr));
  margin-bottom: 32px; }}
.lead {{ display: flex; flex-direction: column; gap: 6px; padding: 14px 16px;
  background: var(--card); border: 1px solid var(--line); border-top: 3px solid var(--accent);
  border-radius: 6px; }}
.lead:hover {{ background: var(--hover); }}
.lead-title {{ font: 700 1.1rem/1.3 Georgia, serif; }}
.lead-sum {{ color: var(--muted); font-size: .9rem; display: -webkit-box;
  -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden; }}
.meta {{ color: var(--muted); font-size: .78rem; }}
.meta b {{ color: var(--accent); font-weight: 600; }}
.grid {{ display: grid; gap: 20px; grid-template-columns: repeat(auto-fill, minmax(min(340px, 100%), 1fr)); }}
section {{ background: var(--card); border: 1px solid var(--line); border-radius: 6px;
  padding: 14px 16px 6px; scroll-margin-top: 12px; }}
ol {{ list-style: none; margin: 0; padding: 0; }}
li a {{ display: flex; flex-direction: column; padding: 8px 6px; margin: 0 -6px;
  border-top: 1px solid var(--line); border-radius: 4px; }}
li:first-child a {{ border-top: 0; }}
li a:hover {{ background: var(--hover); }}
li a:hover .t {{ color: var(--accent); }}
.empty, .warn {{ color: var(--muted); font-size: .9rem; padding: 8px 0; }}
.warn {{ margin-top: 24px; }}
footer {{ margin-top: 32px; color: var(--muted); font-size: .8rem; }}
.briefing {{ margin: 18px 0 0; padding: 14px 16px; border-left: 3px solid var(--accent); }}
.bf-head {{ display: flex; flex-wrap: wrap; align-items: baseline; gap: 4px 12px; }}
.bf-head h2 {{ margin: 0; }}
.bf-controls {{ display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin: 12px 0 4px; }}
.bf-controls button, .bf-controls select, .bf-chapters button {{ font: inherit; color: var(--ink);
  background: var(--bg); border: 1px solid var(--line); border-radius: 99px; padding: 6px 12px;
  min-height: 40px; cursor: pointer; }}
.bf-controls select {{ max-width: 100%; }}
.bf-controls button:hover, .bf-chapters button:hover {{ border-color: var(--accent); color: var(--accent); }}
.bf-controls .bf-play {{ background: var(--accent); border-color: var(--accent); color: var(--card);
  min-width: 56px; font-size: 1.1rem; }}
.bf-controls .bf-play:hover {{ color: var(--card); opacity: .9; }}
.bf-mic[aria-pressed="true"] {{ border-color: var(--accent); color: var(--accent); }}
.listening .bf-mic::after {{ content: " ●"; animation: bf-pulse 1.2s infinite; }}
@keyframes bf-pulse {{ 50% {{ opacity: .2; }} }}
.bf-caption {{ min-height: 1.45em; margin: 8px 0; font: 1.05rem/1.4 Georgia, serif; }}
.bf-caption:empty {{ display: none; }}
.bf-chapters {{ display: flex; flex-wrap: wrap; gap: 6px; }}
.bf-chapters button {{ min-height: 32px; padding: 3px 10px; font-size: .85rem; }}
.bf-chapters button[aria-current] {{ background: var(--accent); border-color: var(--accent); color: var(--card); }}
.bf-status:empty {{ display: none; }}
.bf-unsupported {{ display: none; }}
.briefing.unsupported > :not(.bf-head):not(.bf-unsupported) {{ display: none; }}
.briefing.unsupported .bf-unsupported {{ display: block; }}
@media (prefers-reduced-motion: reduce) {{ .listening .bf-mic::after {{ animation: none; }} }}
</style>
</head>
<body>
<div class="wrap">
<header>
  <div><h1>Morgen-Nachrichten</h1><div class="date">{date}</div></div>
  <div class="stamp">Stand: <time datetime="{iso}">{updated} Uhr</time><br>{total} Meldungen</div>
</header>
<section id="briefing" class="briefing" aria-label="Morning-Briefing">
  <div class="bf-head">
    <h2>🎧 Morning-Briefing</h2><span class="meta">ca. {briefing_minutes} Min.<span class="bf-voice-name"></span> · Tasten: B Start/Pause, N/P Kapitel</span>
  </div>
  <div class="bf-controls">
    <button type="button" data-act="prev" aria-label="Vorheriges Kapitel">⏮</button>
    <button type="button" data-act="play" class="bf-play" aria-label="Vorlesen">▶</button>
    <button type="button" data-act="next" aria-label="Nächstes Kapitel">⏭</button>
    <button type="button" data-act="stop" aria-label="Stopp">■</button>
    <select id="bf-rate" aria-label="Tempo">
      <option value="0.85">0,85×</option><option value="1" selected>1×</option>
      <option value="1.15">1,15×</option><option value="1.3">1,3×</option><option value="1.5">1,5×</option>
    </select>
    <select id="bf-voice" aria-label="Stimme"></select>
    <button type="button" data-act="mic" class="bf-mic" aria-pressed="false"
      title="Sprachsteuerung: „weiter“, „zurück“, „Pause“, „schneller“, Rubrikname">🎤 Sprachsteuerung</button>
  </div>
  <p class="bf-caption" aria-live="polite"></p>
  <ol class="bf-chapters"></ol>
  <p class="bf-status meta" aria-live="polite"></p>
  <p class="bf-hint meta" hidden>Klingt blechern? Bessere Stimmen gibt es kostenlos: iPhone/Mac unter
    <b>Einstellungen → Bedienungshilfen → Gesprochene Inhalte → Stimmen → Deutsch</b> z.&nbsp;B. „Anna (Premium)“
    laden, dann Seite neu öffnen und oben auswählen. Unter Windows klingen die „Natural“-Stimmen in Edge am besten.</p>
  <p class="bf-unsupported meta">Dieser Browser kann nicht vorlesen. <a href="briefing.txt">Briefing als Text</a></p>
</section>
<script type="application/json" id="briefing-data">{briefing_json}</script>
<script src="briefing.js" defer></script>
<nav><a href="#top">Top</a>{nav}</nav>
<h2 id="top">Auf einen Blick</h2>
<div class="leads">
{top}
</div>
<div class="grid">
{sections}
</div>
{failed}
<footer>Automatisch erstellt aus öffentlichen RSS-Feeds · Aktualisierung täglich um 6:00 Uhr</footer>
</div>
</body>
</html>
"""


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", default=HERE / "feeds.json", type=Path)
    ap.add_argument("--out", default=Path("site/index.html"), type=Path)
    ap.add_argument("--audio", action="store_true",
                    help="Briefing zusätzlich als MP3 vertonen (benötigt: pip install edge-tts)")
    args = ap.parse_args()

    config = json.loads(args.config.read_text(encoding="utf-8"))
    now = datetime.now(timezone.utc)
    top, sections, failed = collect(config, now)
    if not any(s["items"] for s in sections):
        sys.exit("Keine einzige Meldung geladen – Dashboard wird nicht überschrieben.")

    # Bevorzugt: Zahlen der täglichen Claude-Routine (Gmail-Connector), sonst IMAP
    mailbox = load_applications_file(HERE / "applications.json", now.astimezone(TZ).date())
    if mailbox:
        print(f"Bewerbungen aus applications.json: {sum(mailbox['applications'].values())}")
    else:
        try:
            mailbox = check_mailbox(config.get("mail"))
        except Exception as exc:  # Log ist öffentlich: MailError enthält nur Schritt + Servermeldung
            reason = str(exc) if isinstance(exc, MailError) else type(exc).__name__
            print(f"WARN Postfach nicht geprüft: {reason}", file=sys.stderr)
            mailbox = "error"
    if isinstance(mailbox, dict):
        print(f"Postfach: {mailbox['important'] if mailbox['important'] is not None else '–'} wichtige Mails, "
              f"{sum(mailbox['applications'].values())} zu Bewerbungen")
    briefing = build_briefing(top, sections, config["categories"], now.astimezone(TZ),
                              config.get("briefing"), mail=mail_sentence(mailbox),
                              applications=applications_sentence(mailbox))
    out_dir = args.out.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    if args.audio:
        try:
            from tts import synthesize
            audio = synthesize(briefing, out_dir / "briefing.mp3", config.get("tts"))
        except Exception as exc:  # ohne Audio liest der Browser selbst vor
            print(f"WARN Vertonung übersprungen: {exc}", file=sys.stderr)
        else:
            # ?v= verhindert, dass Safari die MP3 vom Vortag aus dem Cache spielt
            briefing["audio"] = dict(audio, src=f"briefing.mp3?v={int(now.timestamp())}")
            briefing["minutes"] = max(1, round(audio["duration"] / 60))
    args.out.write_text(render(top, sections, failed, now, briefing), encoding="utf-8")
    (out_dir / "briefing.json").write_text(json.dumps(briefing, ensure_ascii=False, indent=1),
                                           encoding="utf-8")
    (out_dir / "briefing.txt").write_text(plain_text(briefing), encoding="utf-8")
    shutil.copyfile(HERE / "briefing.js", out_dir / "briefing.js")
    print(f"{args.out}: {sum(len(s['items']) for s in sections)} Meldungen, "
          f"{len(failed)} Feeds nicht erreichbar, Briefing ca. {briefing['minutes']} Min.")


if __name__ == "__main__":
    main()
