"""Heute fällige Aufgaben aus dem eigenen Aufgaben-Dashboard (URL im Secret TASKS_URL).

Die URL enthält einen Zugangsschlüssel und steht deshalb nur im Secret, nie im Repo
oder im Log. Gelesen wird JSON, falls die Seite es liefert, sonst die HTML-Seite.
Klappt das Einlesen nicht, loggt das Modul nur den Aufbau der Seite (Tags, Klassen),
keine Inhalte.
"""
import html
import http.cookiejar
import json
import os
import re
import urllib.parse
import urllib.request
from collections import Counter
from datetime import date
from html.parser import HTMLParser

USER_AGENT = "Mozilla/5.0 (compatible; MorningBriefing/1.0)"
TITLE_KEYS = ("title", "titel", "name", "text", "aufgabe", "task", "summary", "beschreibung")
DUE_KEYS = ("due", "faellig", "fällig", "faelligkeit", "fälligkeit", "datum", "date", "deadline",
            "due_date", "dueDate", "termin")
DONE_KEYS = ("done", "erledigt", "completed", "status", "checked", "abgeschlossen")
TASK_HINT = re.compile(r"task|aufgabe|todo", re.I)
DONE_HINT = re.compile(r"\b(done|erledigt|completed|abgeschlossen)\b", re.I)
DATE_ISO = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
DATE_DE = re.compile(r"\b(\d{1,2})\.(\d{1,2})\.(?:(\d{4}|\d{2})\b)?")
TITLE_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6", "strong", "b"}
TITLE_CLASS = re.compile(r"title|titel|name|summary", re.I)


class TasksError(Exception):
    """Text enthält nur Schritt/Struktur, nie Inhalte oder die URL (Log ist öffentlich)."""


def parse_date(text):
    if not text:
        return None
    text = str(text)
    if re.search(r"\bheute\b|\btoday\b", text, re.I):
        return "today"
    m = DATE_ISO.search(text)
    if m:
        return date(int(m[1]), int(m[2]), int(m[3]))
    m = DATE_DE.search(text)
    if m:
        if m[3]:
            year = int(m[3]) + (2000 if len(m[3]) == 2 else 0)
        else:
            year = date.today().year
        try:
            return date(year, int(m[2]), int(m[1]))
        except ValueError:
            return None
    return None


def _is_done(value):
    if isinstance(value, bool):
        return value
    return bool(value) and bool(DONE_HINT.search(str(value)))


# ---------- JSON ----------
def _task_list(data):
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("tasks", "aufgaben", "items", "data", "todos"):
            if isinstance(data.get(key), list):
                return data[key]
    return None


def _field(item, keys):
    lower = {k.lower(): v for k, v in item.items()}
    for key in keys:
        if key.lower() in lower and lower[key.lower()] not in (None, ""):
            return lower[key.lower()]
    return None


def tasks_from_json(data):
    items = _task_list(data)
    if items is None:
        return None
    tasks = []
    for item in items:
        if not isinstance(item, dict):
            continue
        title = _field(item, TITLE_KEYS)
        if not title:
            continue
        tasks.append({"title": str(title).strip(), "due": parse_date(_field(item, DUE_KEYS)),
                      "done": _is_done(_field(item, DONE_KEYS))})
    return tasks


# ---------- HTML ----------
class _Collector(HTMLParser):
    """Sammelt Elemente, deren Klasse/ID nach Aufgabe aussieht, samt Text und Merkmalen."""

    BLOCKS = {"li", "tr", "div", "article", "section", "label", "p"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []      # offene Aufgaben-Elemente: [tag, depth, texts, attrs, checked, title]
        self.title_depth = None  # Tiefe eines Überschrift-/Titel-Elements innerhalb der Aufgabe
        self.depth = 0
        self.tasks = []
        self.structure = Counter()

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        marker = " ".join(filter(None, [a.get("class"), a.get("id"), a.get("data-type")]))
        self.structure[tag] += 1
        for cls in (a.get("class") or "").split():
            self.structure["." + cls] += 1
        if tag not in ("br", "img", "input", "meta", "link", "hr"):
            self.depth += 1
        if tag == "input" and self.stack and a.get("type") == "checkbox" and "checked" in a:
            self.stack[-1][4] = True
        attrs_text = " ".join(str(v) for k, v in attrs if k.startswith("data-") or k in ("class", "title"))
        if self.stack:
            self.stack[-1][3] += " " + attrs_text
        if (self.stack and self.stack[-1][5] is None and self.title_depth is None
                and (tag in TITLE_TAGS or TITLE_CLASS.search(a.get("class") or ""))):
            self.title_depth = self.depth
            self.stack[-1][5] = []
        if tag in self.BLOCKS and TASK_HINT.search(marker) and not re.search(r"list|liste|container|wrap", marker, re.I):
            self.stack.append([tag, self.depth, [], attrs_text, False, None])

    def handle_endtag(self, tag):
        if self.title_depth is not None and self.depth == self.title_depth:
            self.title_depth = None
        if self.stack and self.stack[-1][0] == tag and self.stack[-1][1] == self.depth:
            _, _, texts, attrs_text, checked, title = self.stack.pop()
            text = re.sub(r"\s+", " ", " ".join(texts)).strip()
            if text:
                entry = {"text": text, "attrs": attrs_text, "checked": checked,
                         "title": re.sub(r"\s+", " ", " ".join(title or [])).strip()}
                if self.stack:  # verschachtelt: Text dem äußeren Element überlassen
                    self.stack[-1][2].append(text)
                else:
                    self.tasks.append(entry)
        self.depth = max(0, self.depth - 1)

    def handle_data(self, data):
        if self.stack and data.strip():
            self.stack[-1][2].append(data.strip())
            if self.title_depth is not None and self.stack[-1][5] is not None:
                self.stack[-1][5].append(data.strip())


def tasks_from_html(page):
    parser = _Collector()
    parser.feed(page)
    tasks = []
    for t in parser.tasks:
        due = parse_date(t["attrs"]) or parse_date(t["text"])
        title = DATE_ISO.sub("", DATE_DE.sub("", t["title"] or t["text"]))
        title = re.sub(r"\b(heute|today|fällig|faellig|erledigt|offen)\b:?", "", title, flags=re.I)
        title = re.sub(r"\s+", " ", title).strip(" -–·|:")
        if title:
            tasks.append({"title": title[:120], "due": due,
                          "done": t["checked"] or _is_done(t["attrs"])})
    return tasks, parser.structure


def _structure_summary(structure):
    tags = ", ".join(f"{k}×{v}" for k, v in structure.most_common() if not k.startswith("."))[:300]
    classes = ", ".join(f"{k}×{v}" for k, v in structure.most_common() if k.startswith("."))[:400]
    return f"Tags: {tags} | Klassen: {classes or 'keine'}"


# ---------- Abruf ----------
SCRIPT_RE = re.compile(r"<script[^>]*>(.*?)</script>", re.S | re.I)
ENDPOINT_RE = re.compile(r"""fetch\(\s*[`'"]([^`'"]+)[`'"]""")


def _get(url, opener):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT,
                                               "Accept": "application/json, text/html;q=0.9"})
    with opener(req, timeout=20) as resp:
        return resp.read().decode(resp.headers.get_content_charset() or "utf-8", "replace")


def _endpoints(page, page_url):
    """Datenquellen, die das Seitenskript per fetch() lädt – mit dem Schlüssel der Seite."""
    page_params = urllib.parse.parse_qsl(urllib.parse.urlsplit(page_url).query)
    found = []
    for script in SCRIPT_RE.findall(page):
        for target in ENDPOINT_RE.findall(script):
            target = re.sub(r"\$\{[^}]*\}", "", target)  # Template-Platzhalter entfernen
            parts = urllib.parse.urlsplit(urllib.parse.urljoin(page_url, target))
            # leere Parameter (vorher Platzhalter) mit den Werten aus dem Seiten-Link füllen
            params = dict(p for p in urllib.parse.parse_qsl(parts.query) if p[1])
            for key, value in page_params:
                params.setdefault(key, value)
            url = urllib.parse.urlunsplit(parts._replace(query=urllib.parse.urlencode(params)))
            if url not in found:
                found.append(url)
    return found


def fetch_tasks(env=os.environ, opener=None):
    """Liste {title, due, done} oder None, wenn TASKS_URL nicht gesetzt ist."""
    url = (env.get("TASKS_URL") or "").strip()
    if not url:
        return None
    if opener is None:
        # Wie ein Browser: Sitzungs-Cookie der Seite (Anmeldung per ?k=…) an die API mitschicken
        jar = http.cookiejar.CookieJar()
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar)).open
    try:
        body = _get(url, opener)
    except Exception as exc:
        raise TasksError(f"Abruf: {type(exc).__name__} {getattr(exc, 'code', '')}".strip()) from None
    try:
        tasks = tasks_from_json(json.loads(body))
        if tasks is not None:
            return tasks
    except ValueError:
        pass
    tasks, structure = tasks_from_html(body)
    if tasks:
        return tasks
    # App-Seite: Aufgaben kommen per JavaScript aus einer Schnittstelle
    tried = []
    for endpoint in _endpoints(body, url):
        path = urllib.parse.urlsplit(endpoint).path  # ohne Query – der Schlüssel bleibt geheim
        try:
            found = tasks_from_json(json.loads(_get(endpoint, opener)))
        except Exception as exc:
            tried.append(f"{path} ({type(exc).__name__} {getattr(exc, 'code', '')})".replace(" )", ")"))
            continue
        if found is not None:
            print(f"Aufgaben aus Schnittstelle {path}")
            return found
        tried.append(f"{path} (kein Aufgaben-JSON)")
    scripts = " ".join(SCRIPT_RE.findall(body))
    # Aufrufe der Schnittstelle als Code-Ausschnitt, Schlüssel und lange Werte maskiert
    calls = []
    for m in re.finditer(r"fetch\(", scripts):
        snippet = re.sub(r"\s+", " ", scripts[m.start():m.start() + 220])
        snippet = re.sub(r"[0-9a-fA-F]{16,}", "***", snippet)
        calls.append(snippet)
    for key in dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query)).values():
        calls = [c.replace(key, "***") for c in calls] if len(key) >= 6 else calls
    # Wie wird die API angesprochen? Definition von opts und Aufrufe der Hilfsfunktion
    fn = re.search(r"(?:async\s+)?function\s+(\w+)\s*\([^)]*\)\s*\{[^{}]{0,600}?fetch\(", scripts)
    if fn:
        start = fn.start()
        calls.append("DEF " + re.sub(r"\s+", " ", scripts[start:start + 400]))
        for m in list(re.finditer(r"\b" + re.escape(fn.group(1)) + r"\(", scripts))[1:6]:
            calls.append("CALL " + re.sub(r"\s+", " ", scripts[m.start():m.start() + 120]))
    calls = [re.sub(r"[0-9a-fA-F]{16,}", "***", c) for c in calls]
    for key in dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query)).values():
        calls = [c.replace(key, "***") for c in calls] if len(key) >= 6 else calls
    print("DIAG fetch-Aufrufe: " + " ‖ ".join(calls[:8]), file=__import__("sys").stderr)
    raise TasksError(
        "keine Aufgaben erkannt – Seitenaufbau: " + _structure_summary(structure)
        + f" | Skript: {len(scripts)} Zeichen, localStorage: "
        + ("ja" if "localStorage" in scripts else "nein")
        + f", fetch-Ziele: {', '.join(tried) or 'keine'}")


def due_today(tasks, today):
    """(heute fällig, überfällig) – jeweils offene Aufgaben."""
    todays, overdue = [], []
    open_tasks = [t for t in tasks if not t["done"]]
    if open_tasks and all(t["due"] is None for t in open_tasks):
        # Dashboard ohne Datumsangaben zeigt vermutlich nur Aktuelles: alles gilt als heute
        return [t["title"] for t in open_tasks], []
    for t in tasks:
        if t["done"]:
            continue
        if t["due"] == "today" or t["due"] == today:
            todays.append(t["title"])
        elif isinstance(t["due"], date) and t["due"] < today:
            overdue.append(t["title"])
    return todays, overdue


def tasks_sentence(result, today, max_titles=6):
    if result is None:
        return None
    if result == "error":
        return "Deine Aufgaben konnten heute nicht abgerufen werden."
    todays, overdue = due_today(result, today)
    parts = []
    if not todays:
        parts.append("Für heute stehen keine Aufgaben an.")
    elif len(todays) == 1:
        parts.append(f"Heute steht eine Aufgabe an: {todays[0]}.")
    else:
        listed = todays[:max_titles]
        text = ", ".join(listed[:-1]) + " und " + listed[-1]
        more = f" Dazu {len(todays) - max_titles} weitere." if len(todays) > max_titles else ""
        parts.append(f"Heute stehen {len(todays)} Aufgaben an: {text}.{more}")
    if overdue:
        parts.append("Außerdem ist eine Aufgabe überfällig." if len(overdue) == 1
                     else f"Außerdem sind {len(overdue)} Aufgaben überfällig.")
    return " ".join(parts)
