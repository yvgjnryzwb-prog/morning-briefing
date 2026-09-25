// Morning-Briefing: spielt die vorab erzeugte Neural-MP3 (data.audio) ab. Fehlt sie oder
// lädt sie nicht, liest der Browser per Web Speech API selbst vor.
// Optional Sprachsteuerung per SpeechRecognition (Chrome, Edge, Safari).
(() => {
  "use strict";
  const root = document.getElementById("briefing");
  const dataEl = document.getElementById("briefing-data");
  if (!root || !dataEl) return;
  const data = JSON.parse(dataEl.textContent);
  const synth = window.speechSynthesis || null;
  const canSpeak = !!(synth && window.SpeechSynthesisUtterance);
  if (!canSpeak && !data.audio) {
    root.classList.add("unsupported");
    return;
  }
  const $ = (sel) => root.querySelector(sel);
  const ui = {
    play: $("[data-act=play]"), prev: $("[data-act=prev]"), next: $("[data-act=next]"),
    stop: $("[data-act=stop]"), mic: $("[data-act=mic]"), rate: $("#bf-rate"),
    voice: $("#bf-voice"), caption: $(".bf-caption"), chapters: $(".bf-chapters"),
    status: $(".bf-status"), hint: $(".bf-hint"), voiceName: $(".bf-voice-name"),
  };

  // Flache Warteschlange aller Sätze; seg = Kapitelindex
  const queue = [];
  const segStart = [];
  data.segments.forEach((seg, si) => {
    segStart[si] = queue.length;
    seg.parts.forEach((p) => queue.push({ seg: si, text: p.text, lang: p.lang || data.lang }));
  });

  let pos = 0;
  let playing = false;
  let audio = null; // HTMLAudioElement, solange die Neural-MP3 benutzt wird
  let token = 0; // verhindert, dass Events abgebrochener Sätze weiterspringen

  const store = {
    get(k) { try { return localStorage.getItem("briefing." + k); } catch { return null; } },
    set(k, v) { try { localStorage.setItem("briefing." + k, v); } catch { /* egal */ } },
  };

  // ---------- Stimmen ----------
  // iOS/macOS liefern neben guten Stimmen viele Spaß- und Roboterstimmen (Eddy, Grandma, Zarvox …).
  // Sie werden ausgeblendet; gute Stimmen werden nach Qualität sortiert.
  const NOVELTY = /^(eddy|flo|grandma|grandpa|reed|rocko|sandy|shelley|albert|bad news|bahh|bells|boing|bubbles|cellos|good news|jester|organ|superstar|trinoids|whisper|wobble|zarvox|junior|kathy|fred|ralph)\b/i;
  const GOOD_NAMES = /\b(anna|helena|martin|petra|markus|yannick|viktor|katja|conrad|amala|seraphina|florian|killian|daniel|serena|kate|arthur|martha|stephanie|oliver|jamie|libby|sonia|ryan|samantha|ava|zoe)\b/i;
  function score(v, base) {
    if (NOVELTY.test(v.name)) return -1;
    let s = 0;
    if (/premium/i.test(v.name)) s += 50;
    if (/natural|neural/i.test(v.name)) s += 45;          // Edge „Online (Natural)“
    if (/enhanced|erweitert|verbessert/i.test(v.name)) s += 35;
    if (/google/i.test(v.name)) s += 15;                    // Chrome „Google Deutsch“
    if (GOOD_NAMES.test(v.name)) s += 10;
    if (v.lang.replace("_", "-").toLowerCase() === (base === "en" ? "en-gb" : "de-de")) s += 3;
    if (v.default) s += 1;
    return s;
  }
  const byQuality = (list, base) => list
    .map((v) => [score(v, base), v]).filter(([s]) => s >= 0)
    .sort((a, b) => b[0] - a[0]).map(([, v]) => v);
  const voicesFor = (base) =>
    byQuality(voices.filter((v) => v.lang.toLowerCase().startsWith(base)), base);

  let voices = [];
  function loadVoices() {
    voices = synth.getVoices();
    const german = voicesFor("de");
    const saved = store.get("voice");
    ui.voice.replaceChildren(new Option(german[0] ? `Automatisch (${german[0].name})` : "Standardstimme", ""));
    german.forEach((v) => ui.voice.add(new Option(`${v.name} (${v.lang})`, v.name)));
    if (saved && german.some((v) => v.name === saved)) ui.voice.value = saved;
    ui.voice.hidden = !!audio || german.length === 0;
    // Nur Basis-Stimmen vorhanden → Hinweis, wie man bessere nachlädt
    const good = german[0] && score(german[0], "de") >= 35;
    ui.hint.hidden = !!audio || good || voices.length === 0;
  }
  function voiceFor(lang) {
    const base = lang.slice(0, 2).toLowerCase();
    if (base === "de" && ui.voice.value) {
      const chosen = voices.find((v) => v.name === ui.voice.value);
      if (chosen) return chosen;
    }
    return voicesFor(base)[0] || null;
  }
  if (canSpeak) {
    loadVoices();
    synth.addEventListener?.("voiceschanged", loadVoices);
  }

  // ---------- Neural-Audio (MP3) ----------
  if (data.audio && window.Audio) {
    audio = new Audio();
    audio.preload = "metadata";
    audio.src = data.audio.src;
    const times = data.audio.times;
    const useAudio = (on) => {
      root.classList.toggle("audio-mode", on);
      ui.voice.hidden = on || voicesFor("de").length === 0;
      if (on) ui.hint.hidden = true;
      ui.voiceName.textContent = on ? ` · Stimme: ${data.audio.voice} (Neural)` : "";
    };
    useAudio(true);
    audio.addEventListener("timeupdate", () => {
      const t = audio.currentTime + 0.05;
      let i = 0;
      while (i + 1 < times.length && times[i + 1] <= t) i++;
      if (i !== pos) { pos = i; render(); }
    });
    // Pause/Play über Sperrbildschirm, Kopfhörer oder Kontrollzentrum
    audio.addEventListener("pause", () => { if (playing) { playing = false; render(); } });
    audio.addEventListener("play", () => { if (!playing) { playing = true; render(); } });
    audio.addEventListener("ended", () => {
      playing = false;
      pos = 0;
      ui.caption.textContent = "Ende des Briefings.";
      render();
    });
    audio.addEventListener("error", () => {
      if (!audio) return;
      audio = null;
      useAudio(false);
      if (!canSpeak) { root.classList.add("unsupported"); return; }
      ui.status.textContent = "Audio nicht verfügbar – der Browser liest selbst vor.";
      if (playing) speakAt(pos);
    });
  }
  function seek(t) {
    if (audio.readyState >= 1) audio.currentTime = t;
    else audio.addEventListener("loadedmetadata", () => { audio.currentTime = t; }, { once: true });
  }
  function audioAt(i) {
    pos = Math.max(0, Math.min(i, queue.length - 1));
    seek(data.audio.times[pos]);
    audio.playbackRate = parseFloat(ui.rate.value) || 1;
    playing = true;
    render();
    audio.play().catch(() => {
      playing = false;
      ui.status.textContent = "Wiedergabe blockiert – bitte ▶ antippen.";
      render();
    });
  }

  const savedRate = store.get("rate");
  if (savedRate) ui.rate.value = savedRate;

  // ---------- Kapitel ----------
  data.segments.forEach((seg, si) => {
    const b = document.createElement("button");
    b.type = "button";
    b.textContent = seg.title;
    b.addEventListener("click", () => jumpTo(si));
    const li = document.createElement("li");
    li.append(b);
    ui.chapters.append(li);
  });

  function render() {
    const cur = queue[pos];
    root.classList.toggle("playing", playing);
    ui.play.textContent = playing ? "⏸" : "▶";
    ui.play.setAttribute("aria-label", playing ? "Pause" : "Vorlesen");
    ui.chapters.querySelectorAll("button").forEach((b, i) =>
      b.toggleAttribute("aria-current", !!cur && i === cur.seg && (playing || pos > 0)));
    if (cur && (playing || pos > 0)) ui.caption.textContent = cur.text;
  }

  // ---------- Wiedergabe ----------
  function speakAt(i) {
    if (audio) {
      if (i >= queue.length) { stop(); return; }
      audioAt(i);
      return;
    }
    const my = ++token;
    synth.cancel();
    if (i >= queue.length) {
      pos = 0;
      playing = false;
      ui.caption.textContent = "Ende des Briefings.";
      render();
      return;
    }
    pos = Math.max(0, i);
    playing = true;
    const item = queue[pos];
    const u = new SpeechSynthesisUtterance(item.text);
    u.lang = item.lang;
    const v = voiceFor(item.lang);
    if (v) u.voice = v;
    u.rate = parseFloat(ui.rate.value) || 1;
    u.onend = () => { if (my === token) speakAt(pos + 1); };
    u.onerror = (e) => {
      if (my !== token || e.error === "interrupted" || e.error === "canceled") return;
      ui.status.textContent = "Sprachausgabe-Fehler: " + e.error;
      speakAt(pos + 1);
    };
    render();
    // Kleiner Abstand nach cancel(), sonst verschluckt Chrome den Anfang
    setTimeout(() => { if (my === token) synth.speak(u); }, 60);
  }

  // Pause = abbrechen und Satzposition merken (pause()/resume() ist auf Android unzuverlässig)
  function pause() {
    if (audio) { playing = false; audio.pause(); render(); return; }
    token++;
    synth.cancel();
    playing = false;
    render();
  }
  function play() {
    // Audio nach Pause an gleicher Stelle fortsetzen statt am Satzanfang
    if (audio && audio.currentTime > 0 && !audio.ended) {
      audio.playbackRate = parseFloat(ui.rate.value) || 1;
      audio.play().catch(() => {});
    } else speakAt(pos);
  }
  function toggle() { playing ? pause() : play(); }
  function stop() {
    pause();
    pos = 0;
    if (audio) seek(0);
    ui.caption.textContent = "";
    render();
  }
  function jumpTo(si) { speakAt(segStart[Math.max(0, Math.min(si, data.segments.length - 1))]); }
  function nextSeg() {
    const si = queue[pos] ? queue[pos].seg : 0;
    if (si + 1 < data.segments.length) jumpTo(si + 1); else stop();
  }
  function prevSeg() {
    const si = queue[pos] ? queue[pos].seg : 0;
    // Mitten im Kapitel: an dessen Anfang, sonst ein Kapitel zurück
    jumpTo(pos - segStart[si] > 1 ? si : si - 1);
  }
  function setRate(delta) {
    const opts = [...ui.rate.options].map((o) => o.value);
    const idx = Math.max(0, Math.min(opts.length - 1, opts.indexOf(ui.rate.value) + delta));
    ui.rate.value = opts[idx];
    ui.rate.dispatchEvent(new Event("change"));
  }

  ui.play.addEventListener("click", toggle);
  ui.stop.addEventListener("click", stop);
  ui.next.addEventListener("click", nextSeg);
  ui.prev.addEventListener("click", prevSeg);
  ui.rate.addEventListener("change", () => {
    store.set("rate", ui.rate.value);
    if (audio) audio.playbackRate = parseFloat(ui.rate.value) || 1;
    else if (playing) speakAt(pos);
  });
  ui.voice.addEventListener("change", () => {
    store.set("voice", ui.voice.value);
    if (playing) speakAt(pos);
  });
  document.addEventListener("keydown", (e) => {
    if (e.target.closest("input, select, textarea") || e.metaKey || e.ctrlKey || e.altKey) return;
    if (e.key === "b" || e.key === "B") { e.preventDefault(); toggle(); }
    else if (e.key === "n" || e.key === "N") nextSeg();
    else if (e.key === "p" || e.key === "P") prevSeg();
  });
  window.addEventListener("pagehide", () => synth && synth.cancel());

  // Sperrbildschirm / Kontrollzentrum: Titel und Kapitel-Tasten
  if (audio && "mediaSession" in navigator && window.MediaMetadata) {
    navigator.mediaSession.metadata = new MediaMetadata({
      title: "Morning-Briefing", artist: "Morgen-Nachrichten", album: document.title,
    });
    [["play", play], ["pause", pause], ["stop", stop],
     ["nexttrack", nextSeg], ["previoustrack", prevSeg]].forEach(([action, fn]) => {
      try { navigator.mediaSession.setActionHandler(action, fn); } catch { /* nicht unterstützt */ }
    });
  }

  // ---------- Sprachsteuerung ----------
  const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  const segByWord = data.segments.map((s, i) => [s.title.toLowerCase(), i]);
  const COMMANDS = [
    [/^(stopp?|stop|halt|pause|ruhe|still)\b/, pause],
    [/^(weiter|nächstes?|nächste meldung|überspringen|skip)$/, () => (playing ? nextSeg() : play())],
    [/^(zurück|vorheriges?|nochmal|noch mal|wiederholen)$/, prevSeg],
    [/^(von vorne|neu starten|von anfang an)$/, () => jumpTo(0)],
    [/^(los|start|play|fortsetzen|weiterlesen|weiter lesen|lies vor|vorlesen|briefing|morning briefing)$/, play],
    [/^(schneller)$/, () => setRate(1)],
    [/^(langsamer)$/, () => setRate(-1)],
    [/^(ende|beenden|aus)$/, stop],
  ];
  function handleCommand(raw) {
    const said = raw.toLowerCase().replace(/[.,!?]/g, "").trim();
    // Nur kurze Äußerungen: sonst reagiert der Assistent auf seine eigene Stimme
    if (!said || said.split(/\s+/).length > 4) return false;
    for (const [re, fn] of COMMANDS) {
      if (re.test(said)) { fn(); return said; }
    }
    const topic = said.replace(/^(lies|spring zu|gehe? zu|zu|thema|rubrik)\s+/, "");
    const hit = segByWord.find(([title]) => title.split(/\s+/)[0] === topic.split(/\s+/)[0]);
    if (hit) { jumpTo(hit[1]); return said; }
    return false;
  }

  if (!Recognition) {
    ui.mic.hidden = true;
  } else {
    let rec = null;
    let listening = false;
    const setMic = (on) => {
      listening = on;
      ui.mic.setAttribute("aria-pressed", String(on));
      root.classList.toggle("listening", on);
      ui.status.textContent = on
        ? "Sprachsteuerung an – sag z. B. „weiter“, „zurück“, „Pause“ oder „Wirtschaft“."
        : "";
    };
    function start() {
      rec = new Recognition();
      rec.lang = "de-DE";
      rec.continuous = true;
      rec.interimResults = false;
      rec.onresult = (e) => {
        for (let i = e.resultIndex; i < e.results.length; i++) {
          if (!e.results[i].isFinal) continue;
          const hit = handleCommand(e.results[i][0].transcript);
          if (hit) ui.status.textContent = `Verstanden: „${hit}“`;
        }
      };
      rec.onerror = (e) => {
        if (e.error === "not-allowed" || e.error === "service-not-allowed") {
          setMic(false);
          ui.status.textContent = "Kein Mikrofonzugriff – bitte im Browser erlauben.";
        }
      };
      // Browser beenden die Erkennung nach Stille; solange aktiv, neu starten
      rec.onend = () => { if (listening) setTimeout(() => listening && rec.start(), 250); };
      rec.start();
      setMic(true);
    }
    ui.mic.addEventListener("click", () => {
      if (listening) { setMic(false); rec && rec.abort(); } else start();
    });
  }

  // ?play im Link startet sofort, sofern der Browser es ohne Klick erlaubt
  if (new URLSearchParams(location.search).has("play")) play();
  render();
})();
