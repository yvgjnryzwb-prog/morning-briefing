"""Erzeugt aus den Dashboard-Daten ein vorlesbares Morning-Briefing.

Das Ergebnis ist reine Daten (Kapitel mit Sätzen und Sprache); vorgelesen wird im
Browser über die Web Speech API (siehe briefing.js).
"""
import re

WEEKDAYS = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]
MONTHS = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli",
          "August", "September", "Oktober", "November", "Dezember"]
WORDS_PER_MINUTE = 150

DEFAULTS = {"top_items": 5, "items_per_category": 3, "summaries": True}


def norm_title(title):
    return re.sub(r"\W+", "", title.lower())[:80]


def spoken_title(title):
    """Rubriknamen fürs Ohr: „International (EN)“ → „International“, „&“ → „und“."""
    title = re.sub(r"\s*\([^)]*\)", "", title)
    return title.replace("&", "und").strip()


def sentence(text):
    """Schlagzeilen haben oft keinen Schlusspunkt – für eine Sprechpause ergänzen."""
    text = text.strip().rstrip(" …").rstrip()
    if text and text[-1] not in ".!?:":
        text += "."
    return text


def split_sentences(text):
    """Teilt in Sätze, damit lange Texte nicht abreißen (Chrome bricht nach ~15 s ab).

    Punkte nach Zahlen („25. September“) und sehr kurze Stücke werden wieder angefügt.
    """
    pieces = re.split(r"(?<=[.!?…])\s+(?=\S)", text.strip())
    out = []
    for piece in pieces:
        if out and (re.search(r"\d\.$", out[-1]) or len(out[-1]) < 20):
            out[-1] += " " + piece
        else:
            out.append(piece)
    return [p for p in out if p]


def complete_sentences(text, limit=260):
    """Nur ganze Sätze aus einem Teaser, abgeschnittene Reste fallen weg."""
    text = re.sub(r"\s*…$", "", text or "").strip()
    picked = []
    for s in split_sentences(text):
        if s[-1] not in ".!?\"“”»«'" or len(" ".join(picked + [s])) > limit:
            break
        picked.append(s)
    return " ".join(picked)


def parts(text, lang):
    return [{"text": s, "lang": lang} for s in split_sentences(text)]


def headline_parts(item, lang, with_summary, prefix=None):
    out = []
    if prefix:
        out += parts(prefix, "de")
    out += parts(sentence(item["title"]), lang)
    if with_summary:
        summary = complete_sentences(item.get("summary_long") or item.get("summary"))
        if summary and norm_title(summary) != norm_title(item["title"]):
            out += parts(summary, lang)
    return out


def build_briefing(top, sections, categories, now_local, options=None, mail=None,
                   applications=None, tasks=None):
    """top/sections wie aus collect(); categories aus feeds.json (für Sprache/Opt-out).

    mail/applications: fertige Sätze zum Postfach und zu Bewerbungen (nur Zahlen,
    siehe mail.py) oder None.
    """
    opts = dict(DEFAULTS, **(options or {}))
    cat_cfg = {c["title"]: c for c in categories}
    cat_by_id = {c["id"]: c for c in categories}
    lang_of = lambda title: cat_cfg.get(title, {}).get("lang", "de")

    date = f"{WEEKDAYS[now_local.weekday()]}, der {now_local.day}. {MONTHS[now_local.month - 1]}"
    segments = [{
        "id": "intro",
        "title": "Begrüßung",
        "parts": parts(f"Guten Morgen! Heute ist {date}. "
                       f"Hier ist dein Morning-Briefing, Stand {now_local:%H:%M} Uhr.", "de"),
    }]
    if mail:
        segments.append({"id": "mail", "title": "Posteingang", "parts": parts(mail, "de")})
    if applications:
        segments.append({"id": "bewerbungen", "title": "Bewerbungen",
                         "parts": parts(applications, "de")})
    if tasks:
        segments.append({"id": "aufgaben", "title": "Aufgaben", "parts": parts(tasks, "de")})

    spoken = set()
    top_parts = []
    for item in top:
        if len(spoken) >= opts["top_items"]:
            break
        key = norm_title(item["title"])
        if key in spoken:
            continue
        spoken.add(key)
        top_parts += headline_parts(item, lang_of(item["category"]), opts["summaries"],
                                    prefix=spoken_title(item["category"]) + ":")
    if top_parts:
        segments.append({"id": "top", "title": "Auf einen Blick",
                         "parts": parts("Zuerst die wichtigsten Meldungen.", "de") + top_parts})

    for sec in sections:
        cfg = cat_by_id.get(sec["id"], {})
        if cfg.get("briefing") is False:
            continue
        items = [i for i in sec["items"] if norm_title(i["title"]) not in spoken]
        items = items[:opts["items_per_category"]]
        if not items:
            continue
        lang = cfg.get("lang", "de")
        seg_parts = parts(f"{spoken_title(sec['title'])}.", "de")
        for item in items:
            spoken.add(norm_title(item["title"]))
            seg_parts += headline_parts(item, lang, False)
        segments.append({"id": sec["id"], "title": spoken_title(sec["title"]), "parts": seg_parts})

    segments.append({"id": "outro", "title": "Abschluss",
                     "parts": parts("Das war dein Briefing. Einen guten Tag!", "de")})

    words = sum(len(p["text"].split()) for s in segments for p in s["parts"])
    return {"lang": "de-DE", "minutes": max(1, round(words / WORDS_PER_MINUTE)), "segments": segments}


def plain_text(briefing):
    """Briefing als Fließtext, z. B. für eine Text-Datei oder externe TTS-Dienste."""
    return "\n\n".join(" ".join(p["text"] for p in s["parts"]) for s in briefing["segments"]) + "\n"
