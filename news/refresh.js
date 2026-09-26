// Beim Öffnen aktualisieren: Ist die Seite älter als 5 Minuten, stößt sie über ein kleines
// Skript auf dem eigenen Server (refresh_url, hält den GitHub-Schlüssel) einen neuen Build an,
// wartet auf den neuen Stand und lädt sich dann neu.
(() => {
  "use strict";
  const dataEl = document.getElementById("briefing-data");
  if (!dataEl) return;
  const data = JSON.parse(dataEl.textContent);
  const url = data.refresh_url;
  const built = Date.parse(data.built || "");
  if (!url || !built) return;

  const FRESH_MS = 5 * 60 * 1000;   // jüngere Seiten nicht neu bauen
  const POLL_MS = 10 * 1000;
  const GIVE_UP_MS = 4 * 60 * 1000; // Build + Veröffentlichung dauern meist gut eine Minute
  if (Date.now() - built < FRESH_MS) return;

  const bar = document.createElement("div");
  bar.className = "refresh-bar";
  bar.setAttribute("role", "status");
  bar.textContent = "Wird aktualisiert …";
  document.body.prepend(bar);
  const done = (text) => { bar.textContent = text; setTimeout(() => bar.remove(), 6000); };

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
      await new Promise((r) => setTimeout(r, POLL_MS));
      if (await newerBuild()) {
        location.reload();
        return;
      }
    }
    done("Aktualisierung dauert länger – später einfach neu laden.");
  }

  fetch(url, { method: "POST", cache: "no-store" })
    .then((r) => r.json())
    .then((res) => {
      // Gerade erst gestartet (auch von jemand anderem): ebenfalls auf den neuen Stand warten
      if (res.started || (res.since != null && res.since * 1000 < GIVE_UP_MS)) {
        bar.textContent = "Wird aktualisiert … (ca. 1 Minute)";
        waitAndReload(res.started ? Date.now() : Date.now() - res.since * 1000);
      } else {
        done("Aktualisierung gerade nicht möglich – der Stand oben ist aktuell.");
      }
    })
    .catch(() => done("Aktualisierung nicht erreichbar – der Stand oben gilt."));
})();
