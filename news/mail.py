"""Postfach-Check per IMAP: wichtige neue Mails und Stand der Bewerbungen.

Nur lesend (readonly, BODY.PEEK) – nichts wird als gelesen markiert.
Zugangsdaten kommen aus Umgebungsvariablen (im Workflow aus GitHub-Secrets):
MAIL_USER und MAIL_PASSWORD (bei Gmail ein App-Passwort).

Datenschutz: Die Seite ist öffentlich. Deshalb verlassen nur Zahlen dieses Modul,
nie Absender, Firmen oder Betreffzeilen – auch nicht ins Log.
"""
import email
import html
import imaplib
import os
import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from email.header import decode_header, make_header

# IMAP-Server nach Adress-Domain; andere Anbieter per "mail": {"host": ...} in feeds.json
IMAP_HOSTS = {
    "gmail.com": "imap.gmail.com", "googlemail.com": "imap.gmail.com",
    "gmx.de": "imap.gmx.net", "gmx.net": "imap.gmx.net", "gmx.at": "imap.gmx.net",
    "gmx.ch": "imap.gmx.net", "gmx.com": "imap.gmx.com",
    "web.de": "imap.web.de",
}
DEFAULTS = {
    "host": None,  # None = aus der Adresse ableiten, sonst Gmail
    # Gmail-Suche: Tab „Allgemein“ filtert Werbung, Soziales, Benachrichtigungen, Foren
    "gmail_query": "in:inbox category:primary is:unread newer_than:1d",
    # Bewerbungs-Mails kommen oft von Bewerbermanagement-Systemen und landen unter
    # „Benachrichtigungen“ – daher alle Tabs außer Werbung/Soziales, gelesen oder nicht
    "applications_query": ("in:inbox newer_than:1d -category:promotions -category:social "
                           "(Bewerbung OR Bewerbungen OR Vorstellungsgespräch OR Kennenlernen "
                           "OR application OR applying OR interview OR candidate OR Absage)"),
    "hours": 24,
    "max_messages": 60,
}
HEADERS = "FROM LIST-UNSUBSCRIBE LIST-ID PRECEDENCE AUTO-SUBMITTED"
AUTOMATED_SENDER = re.compile(
    r"(no-?reply|do-?not-?reply|newsletter|marketing|mailer-daemon|notifications?@|news@)", re.I)

# ---------- Bewerbungen ----------
ABOUT_APPLICATION = re.compile(
    r"bewerbung|bewerber|bewerben|kandidat|vorstellungsgespr|application|applying|applied|candida",
    re.I)
# Jobportal-Newsletter („Neue Jobs für dich“) sind keine Rückmeldungen
JOB_ALERT = re.compile(
    r"neue jobs|jobs? für dich|job-?alert|jobempfehlung|passende (jobs|stellen)|stellenangebote für"
    r"|jobs you may|recommended jobs|new jobs", re.I)
# Reihenfolge = Vorrang: eine Absage nach dem Interview ist eine Absage, keine Einladung
STATUS_PATTERNS = [
    ("angebot", r"vertragsangebot|arbeitsvertrag|zusage für die stelle|freuen uns, ihnen (die stelle|ein angebot)"
                r"|job offer|offer letter|pleased to offer"),
    ("absage", r"\bleider\b|absage|nicht (weiter )?berücksichtig|für (einen )?andere[nr]? (kandidat|bewerber)"
               r"|anderweitig besetzt|unfortunately|not (to )?(move|moving) forward|other candidates"
               r"|decided not to|regret to inform"),
    ("einladung", r"vorstellungsgespr|kennenlerngespr|einladung|laden (sie|dich) .{0,60}ein|terminvorschl"
                  r"|telefoninterview|video-?interview|zu einem (persönlichen |ersten )?(gespräch|interview)"
                  r"|invite you|schedule (a|an) (call|time|interview)"),
    ("eingang", r"eingegangen|erhalten|eingangsbestätigung|vielen dank für (ihre|deine) bewerbung"
                r"|received your application|thank you for (applying|your application)"),
]
STATUS_RE = [(name, re.compile(rx, re.I)) for name, rx in STATUS_PATTERNS]


def _header(msg, name):
    try:
        return str(make_header(decode_header(msg.get(name) or "")))
    except Exception:
        return msg.get(name) or ""


def message_text(msg, limit=6000):
    """Betreff plus Text (text/plain bevorzugt, sonst HTML ohne Tags)."""
    plain, rich = [], []
    for part in msg.walk():
        ctype = part.get_content_type()
        if ctype not in ("text/plain", "text/html") or part.get_filename():
            continue
        try:
            payload = part.get_payload(decode=True) or b""
            text = payload.decode(part.get_content_charset() or "utf-8", "replace")
        except Exception:
            continue
        (plain if ctype == "text/plain" else rich).append(text)
    body = "\n".join(plain) if plain else re.sub(r"<[^>]+>", " ", html.unescape("\n".join(rich)))
    return (_header(msg, "Subject") + "\n" + re.sub(r"\s+", " ", body))[:limit]


def application_status(raw):
    """Status einer Bewerbungs-Mail oder None, wenn es keine Rückmeldung zu einer Bewerbung ist."""
    msg = email.message_from_bytes(raw)
    text = message_text(msg)
    subject = _header(msg, "Subject")
    if JOB_ALERT.search(subject) or not ABOUT_APPLICATION.search(text):
        return None
    for name, rx in STATUS_RE:
        if rx.search(text):
            return name
    return "sonstiges"


# ---------- wichtige Mails ----------
def is_personal(headers):
    """Heuristik gegen Newsletter, Massenmails und Automaten."""
    msg = email.message_from_bytes(headers)
    if msg.get("List-Unsubscribe") or msg.get("List-Id"):
        return False
    if (msg.get("Precedence") or "").strip().lower() in ("bulk", "list", "junk"):
        return False
    if (msg.get("Auto-Submitted") or "no").strip().lower() != "no":
        return False
    return not AUTOMATED_SENDER.search(msg.get("From") or "")


# ---------- IMAP ----------
class MailError(Exception):
    """Fehler mit Arbeitsschritt; Text stammt nur vom Server, nie aus Mails (Log ist öffentlich)."""


def _search(imap, opts, gmail_query, *fallback):
    if "gmail" in opts["host"]:
        # imaplib verschickt Befehle nur als ASCII – Umlaute („Vorstellungsgespräch“)
        # gehen deshalb als UTF-8-Literal an den Server
        imap.literal = gmail_query.encode("utf-8")
        typ, data = imap.uid("SEARCH", "CHARSET", "UTF-8", "X-GM-RAW")
    else:
        since = (datetime.now(timezone.utc) - timedelta(hours=opts["hours"])).strftime("%d-%b-%Y")
        typ, data = imap.uid("SEARCH", *fallback, "SINCE", since)
    if typ != "OK":
        raise RuntimeError("Suche fehlgeschlagen")
    return (data[0].split() if data and data[0] else [])[-opts["max_messages"]:]


def _fetch(imap, uids, what):
    for i in range(0, len(uids), 50):
        typ, rows = imap.uid("FETCH", b",".join(uids[i:i + 50]), f"({what})")
        for row in rows:
            if isinstance(row, tuple):
                yield row[1]


def check_mailbox(options=None, env=os.environ, imap_factory=imaplib.IMAP4_SSL):
    """{"important": int, "applications": Counter} oder None, wenn kein Postfach eingerichtet ist."""
    # Beim Einfügen (v. a. am Handy) rutschen leicht Leerzeichen oder Zeilenumbrüche mit
    user = (env.get("MAIL_USER") or "").strip()
    password = (env.get("MAIL_PASSWORD") or "").strip()
    if not user or not password:
        return None
    opts = dict(DEFAULTS, **(options or {}))
    if not opts["host"]:
        opts["host"] = IMAP_HOSTS.get(user.rpartition("@")[2].lower(), "imap.gmail.com")
    if "gmail" in opts["host"]:
        # Google zeigt App-Passwörter in Vierergruppen an; sie enthalten nie Leerzeichen
        password = re.sub(r"\s+", "", password)
    stage = "Verbindung"
    imap = None
    try:
        imap = imap_factory(opts["host"], timeout=30)
        stage = "Anmeldung"
        imap.login(user, password)
        stage = "Posteingang"
        imap.select("INBOX", readonly=True)
        stage = "Suche wichtige Mails"
        uids = _search(imap, opts, opts["gmail_query"], "UNSEEN")
        important = sum(1 for h in _fetch(imap, uids, f"BODY.PEEK[HEADER.FIELDS ({HEADERS})]")
                        if is_personal(h))
        stage = "Suche Bewerbungen"
        uids = _search(imap, opts, opts["applications_query"])
        statuses = Counter(s for raw in _fetch(imap, uids, "BODY.PEEK[]")
                           if (s := application_status(raw)))
        return {"important": important, "applications": statuses}
    except (imaplib.IMAP4.error, OSError, RuntimeError) as exc:
        detail = exc.args[0] if exc.args else ""
        if isinstance(detail, bytes):
            detail = detail.decode("utf-8", "replace")
        message = f"{stage}: {type(exc).__name__} {str(detail)[:120]}".strip()
        if stage == "Anmeldung":
            # Diagnose ohne Geheimnisse: Server und Passwortlänge (Gmail-App-Passwort = 16)
            message += f" (Server: {opts['host']}, Passwort: {len(password)} Zeichen)"
            if "gmx" in opts["host"] or "web.de" in opts["host"]:
                message += (" – bei GMX/Web.de muss unter Einstellungen → POP3/IMAP-Abruf "
                            "der IMAP-Zugriff eingeschaltet sein")
        raise MailError(message) from exc
    finally:
        if imap is not None:
            try:
                imap.logout()
            except Exception:
                pass


# ---------- Sätze fürs Briefing ----------
NUMBERS = ["keine", "eine", "zwei", "drei", "vier", "fünf", "sechs", "sieben", "acht", "neun",
           "zehn", "elf", "zwölf"]
STATUS_WORDS = {  # Einzahl, Mehrzahl
    "angebot": ("ein Jobangebot", "Jobangebote"),
    "einladung": ("eine Einladung zum Gespräch", "Einladungen zu Gesprächen"),
    "absage": ("eine Absage", "Absagen"),
    "eingang": ("eine Eingangsbestätigung", "Eingangsbestätigungen"),
    "sonstiges": ("eine weitere Nachricht", "weitere Nachrichten"),
}


def _count_phrase(n, status):
    one, many = STATUS_WORDS[status]
    if n == 1:
        return one
    return f"{NUMBERS[n] if n < len(NUMBERS) else n} {many}"


def mail_sentence(result):
    if result is None:
        return None
    if result == "error":
        return "Dein Postfach konnte nicht geprüft werden."
    count = result["important"]
    if count == 0:
        return "In deinem Postfach ist seit gestern nichts Wichtiges eingegangen."
    if count == 1:
        return "In deinem Postfach wartet eine wichtige neue Mail."
    return f"In deinem Postfach warten {count} wichtige neue Mails."


def applications_sentence(result):
    if result is None or result == "error":
        return None
    stats = result["applications"]
    phrases = [_count_phrase(stats[s], s) for s in STATUS_WORDS if stats.get(s)]
    if not phrases:
        return "Zu deinen Bewerbungen gibt es seit gestern nichts Neues."
    listed = phrases[0] if len(phrases) == 1 else ", ".join(phrases[:-1]) + " und " + phrases[-1]
    text = f"Zu deinen Bewerbungen seit gestern: {listed}."
    if stats.get("angebot") or stats.get("einladung"):
        text += " Da lohnt sich heute ein Blick ins Postfach."
    return text
