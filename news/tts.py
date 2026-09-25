"""Vertont das Briefing mit Microsoft-Edge-Neural-Stimmen (Paket edge-tts) als eine MP3.

Jeder Satz wird einzeln erzeugt; daraus ergeben sich exakte Startzeiten für
Untertitel und Kapitelsprünge im Player. Edge liefert CBR-MP3 mit 48 kbit/s,
die Clips lassen sich daher einfach aneinanderhängen und die Dauer aus der
Dateigröße berechnen.
"""
import asyncio

BYTES_PER_SECOND = 48000 / 8
FALLBACK_VOICES = {"de": "de-DE-KatjaNeural", "en": "en-GB-SoniaNeural"}
DEFAULTS = {"voice_de": "de-DE-SeraphinaMultilingualNeural", "voice_en": "en-GB-SoniaNeural",
            "rate": "+0%", "parallel": 4}


async def _speak(text, voices, rate):
    import edge_tts

    error = None
    for attempt, voice in enumerate([voices[0], voices[0], voices[1]]):
        try:
            audio = bytearray()
            async for chunk in edge_tts.Communicate(text, voice, rate=rate).stream():
                if chunk["type"] == "audio":
                    audio += chunk["data"]
            if audio:
                return bytes(audio)
            error = RuntimeError("leere Antwort")
        except Exception as exc:  # Netzwerk, Drosselung, unbekannte Stimme …
            error = exc
        await asyncio.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"Vertonung fehlgeschlagen für „{text[:50]}“: {error}")


def synthesize(briefing, out_path, options=None):
    """Schreibt die MP3 und liefert Startzeiten (Sekunden) je Satz in Briefing-Reihenfolge."""
    opts = dict(DEFAULTS, **(options or {}))
    parts = [p for seg in briefing["segments"] for p in seg["parts"]]

    def voices_for(lang):
        base = (lang or "de")[:2].lower()
        chosen = opts.get(f"voice_{base}") or FALLBACK_VOICES.get(base, FALLBACK_VOICES["de"])
        return chosen, FALLBACK_VOICES.get(base, FALLBACK_VOICES["de"])

    async def run():
        limit = asyncio.Semaphore(opts["parallel"])

        async def one(part):
            async with limit:
                return await _speak(part["text"], voices_for(part["lang"]), opts["rate"])

        return await asyncio.gather(*(one(p) for p in parts))

    clips = asyncio.run(run())
    times, t = [], 0.0
    for clip in clips:
        times.append(round(t, 2))
        t += len(clip) / BYTES_PER_SECOND
    out_path.write_bytes(b"".join(clips))
    voice = opts["voice_de"].split("-")[2].replace("MultilingualNeural", "").replace("Neural", "")
    return {"times": times, "duration": round(t, 1), "voice": voice}
