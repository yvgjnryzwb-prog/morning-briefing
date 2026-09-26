// Aktualisieren: automatisch beim Öffnen (Seite älter als 5 Minuten) oder per Button.
// Ein kleines Skript auf dem eigenen Server (refresh_url, hält den GitHub-Schlüssel) startet
// den Build; die Seite wartet auf den neuen Stand in briefing.json und lädt sich dann neu.
(() => {
  "use strict";
  const dataEl = document.getElementById("briefing-data");
  if (!dataEl) return;
  const data = JSON.parse(dataEl.textContent);
  const url = data.refresh_url;
  const built = Date.parse(data.built || "");
  if (!url || !built) return;

  const FRESH_MS = 5 * 60 * 1000;   // Server-Sperre und Alter für das automatische Aktualisieren
  const POLL_MS = 10 * 1000;
  const GIVE_UP_MS = 4 * 60 * 1000; // Build + Veröffentlichung dauern meist gut eine Minute

  const button = document.querySelector(".refresh-btn");
  let bar = null;
  let running = false;

  function show(text, sticky) {
    if (!bar) {
      bar = document.createElement("div");
      bar.className = "refresh-bar";
      bar.setAttribute("role", "status");
      document.body.prepend(bar);
    }
    bar.textContent = text;
    clearTimeout(show.timer);
    if (!sticky) show.timer = setTimeout(() => { bar.remove(); bar = null; }, 6000);
  }

  function finish(text) {
    running = false;
    if (button) button.disabled = false;
    show(text, false);
  }

  async function newerBuild() {
    try {
      const r = await fetch(`briefing.json?t=${Date.now()}`, { cache: "no-store" });
      const j = await r.json();
      return Date.parse(j.built || "") > built;
    } catch {
      return false;
    }
  }

  async function waitAndReload(since) {
    const until = since + GIVE_UP_MS;
    while (Date.now() < until) {
      if (await newerBuild()) {
        location.reload();
        return;
      }
      await new Promise((r) => setTimeout(r, POLL_MS));
    }
    finish("Aktualisierung dauert länger – später einfach neu laden.");
  }

  async function refresh(manual) {
    if (running) return;
    running = true;
    if (button) button.disabled = true;
    show("Wird aktualisiert …", true);
    let res;
    try {
      res = await (await fetch(url, { method: "POST", cache: "no-store" })).json();
    } catch {
      finish("Aktualisierung nicht erreichbar – der Stand oben gilt.");
      return;
    }
    const since = res.since != null ? res.since * 1000 : Infinity;
    // Ein kurz zuvor gestarteter Build (auch von jemand anderem) ist nur dann abzuwarten,
    // wenn er nach dem Stand dieser Seite gestartet wurde – sonst ist die Seite schon aktuell.
    const pending = since < GIVE_UP_MS && Date.now() - since > built;
    if (res.started || pending) {
      // gestartet – oder kurz zuvor von jemand anderem: in beiden Fällen auf den neuen Stand warten
      show("Wird aktualisiert … (ca. 1 Minute)", true);
      waitAndReload(res.started ? Date.now() : Date.now() - since);
    } else if (since < FRESH_MS) {
      const min = Math.max(1, Math.ceil((FRESH_MS - since) / 60000));
      finish(manual ? `Gerade erst aktualisiert – wieder möglich in ${min} Min.`
                    : "Der Stand oben ist aktuell.");
    } else {
      finish("Aktualisierung gerade nicht möglich – der Stand oben gilt.");
    }
  }

  if (button) {
    button.hidden = false;
    button.addEventListener("click", () => refresh(true));
  }
  if (Date.now() - built >= FRESH_MS) refresh(false);
})();
