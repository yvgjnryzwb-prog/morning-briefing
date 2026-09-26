"""Anzahl passender Stellen und Veränderung zum Vortag.

Die Zahlen schreibt eine tägliche Claude-Routine mit dem Indeed-Connector nach
news/jobs.json (gleiche Suche wie „Passende Stellen suchen“ im Bewerbungs-Cockpit):
{"history": [{"date": "JJJJ-MM-TT", "count": 23}, ...]}  – nur Datum und Zahl.
"""
import json
from datetime import timedelta

WEEKDAYS = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]


def load_jobs(path, today):
    """(heutige Zahl, (Datum, Zahl) des letzten früheren Eintrags) oder None ohne Datei."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    entries = []
    for e in data.get("history", []) if isinstance(data, dict) else []:
        try:
            entries.append((str(e["date"]), int(e["count"])))
        except (KeyError, TypeError, ValueError):
            continue
    if not entries:
        return None
    entries.sort()
    current = next((c for d, c in entries if d == today.isoformat()), None)
    earlier = [(d, c) for d, c in entries if d < today.isoformat()]
    return {"today": current, "previous": earlier[-1] if earlier else None}


def _when(prev_date, today):
    from datetime import date
    d = date.fromisoformat(prev_date)
    if d == today - timedelta(days=1):
        return "gestern"
    if today - d < timedelta(days=7):
        return f"am {WEEKDAYS[d.weekday()]}"
    return f"am {d.day}.{d.month}."


def jobs_sentence(info, today):
    if info is None:
        return None
    if info["today"] is None:
        return "Die Zahl passender Stellen wurde heute nicht aktualisiert."
    n = info["today"]
    head = ("Auf Indeed gibt es aktuell keine passenden Stellen" if n == 0 else
            "Auf Indeed gibt es eine passende Stelle" if n == 1 else
            f"Auf Indeed gibt es {n} passende Stellen")
    if not info["previous"]:
        return head + ". Einen Vergleich gibt es ab dem nächsten Tag."
    prev_date, prev = info["previous"]
    diff, when = n - prev, _when(prev_date, today)
    if diff == 0:
        return f"{head}, genauso viele wie {when}."
    word = "mehr" if diff > 0 else "weniger"
    amount = "eine" if abs(diff) == 1 else str(abs(diff))
    return f"{head}, {amount} {word} als {when}."
