// Story page controller: runs the presenter steps and twists, and keeps the page in sync.
// Element ids and data attributes here match app/templates/story.html.
document.addEventListener("DOMContentLoaded", function () {
  const byId = (id) => document.getElementById(id);

  const resultPanel = byId("result-panel");
  const resultTitle = byId("result-title");
  const resultSummary = byId("result-summary");
  const resultChip = byId("result-status-chip");
  const factsBox = byId("result-facts-container");
  const factsGrid = byId("result-facts-grid");
  const personasBox = byId("result-personas-container");
  const personasList = byId("result-personas-list");
  const btnAll = byId("btn-run-all");
  const btnRestore = byId("btn-restore-chain");
  const btnReset = byId("btn-reset-demo");

  if (resultSummary) resultSummary.setAttribute("aria-live", "polite");

  async function apiJson(url, options) {
    const res = await fetch(url, options);
    let data = {};
    try {
      data = await res.json();
    } catch (e) {
      data = {};
    }
    return { ok: res.ok, data: data };
  }

  function clear(node) {
    while (node && node.firstChild) node.removeChild(node.firstChild);
  }

  function linksContainer() {
    // The page has no container for related links, so create one the first time it is needed.
    let box = byId("result-links-container");
    if (!box && resultPanel) {
      box = document.createElement("div");
      box.id = "result-links-container";
      box.style.cssText = "display:none;margin-top:1.25rem;padding-top:1rem;border-top:1px solid var(--line)";
      const heading = document.createElement("h3");
      heading.textContent = "Related pages";
      heading.style.cssText = "font-size:0.95rem;text-transform:uppercase;letter-spacing:0.04em;color:var(--muted);margin-bottom:0.6rem";
      const list = document.createElement("div");
      list.id = "result-links-list";
      list.style.cssText = "display:flex;gap:0.5rem;flex-wrap:wrap";
      box.appendChild(heading);
      box.appendChild(list);
      resultPanel.appendChild(box);
    }
    return box;
  }

  function displayResult(data) {
    if (!resultPanel) return;
    if (resultTitle) resultTitle.textContent = data.title || data.key || "Result";
    if (resultSummary) resultSummary.textContent = data.summary || "";
    if (resultChip) resultChip.style.display = "inline-block";

    // Verified facts (textContent only, so nothing from the server is treated as HTML).
    clear(factsGrid);
    const facts = data.facts && typeof data.facts === "object" ? Object.entries(data.facts) : [];
    if (factsBox) factsBox.style.display = facts.length ? "block" : "none";
    facts.forEach(function (pair) {
      const key = document.createElement("span");
      key.className = "fact-key";
      key.style.color = "var(--muted)";
      key.textContent = pair[0];
      const val = document.createElement("span");
      val.className = "fact-val";
      val.textContent = typeof pair[1] === "object" ? JSON.stringify(pair[1]) : String(pair[1]);
      factsGrid.appendChild(key);
      factsGrid.appendChild(val);
    });

    // Persona links
    clear(personasList);
    const personas = Array.isArray(data.personas) ? data.personas : [];
    if (personasBox) personasBox.style.display = personas.length ? "block" : "none";
    personas.forEach(function (p) {
      const a = document.createElement("a");
      if (p.user_id !== null && p.user_id !== undefined) {
        a.href = "/switch/" + encodeURIComponent(p.user_id) + "?next=" + encodeURIComponent(p.path || "/");
      } else {
        a.href = p.path || "/";
      }
      a.className = "btn btn-secondary btn-sm";
      a.textContent = "Open as " + (p.name || p.role);
      personasList.appendChild(a);
    });

    // Related links
    const links = Array.isArray(data.links) ? data.links : [];
    const box = linksContainer();
    if (box) {
      const list = byId("result-links-list");
      clear(list);
      box.style.display = links.length ? "block" : "none";
      links.forEach(function (l) {
        const a = document.createElement("a");
        a.href = l.href;
        a.className = "btn btn-secondary btn-sm";
        a.textContent = l.label;
        list.appendChild(a);
      });
    }

    if (resultPanel.scrollIntoView) resultPanel.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  async function refreshStatus() {
    try {
      const r = await apiJson("/api/story/status");
      if (!r.ok || !Array.isArray(r.data.steps)) return null;

      r.data.steps.forEach(function (s) {
        const card = byId("step-card-" + s.key);
        const chip = byId("chip-" + s.key);
        const btn = document.querySelector('.btn-run-step[data-key="' + s.key + '"]');

        if (card) {
          card.classList.remove("step-done", "step-todo", "step-blocked");
          card.classList.add("step-" + s.status);
        }
        if (chip) {
          chip.textContent = s.status.toUpperCase();
          chip.className = "chip chip-status chip-" + s.status;
        }
        if (btn) {
          btn.classList.remove("btn-primary", "btn-next-highlight", "btn-secondary");
          if (s.status === "done") {
            btn.textContent = "Re-run";
            btn.disabled = false;
            btn.classList.add("btn-secondary");
          } else if (s.status === "blocked") {
            btn.textContent = "Run";
            btn.disabled = true;
            btn.classList.add("btn-secondary");
          } else {
            btn.textContent = "Run";
            btn.disabled = false;
            btn.classList.add("btn-primary", "btn-next-highlight");
          }
        }
      });

      if (btnRestore) btnRestore.style.display = r.data.ledger_broken ? "" : "none";
      return r.data;
    } catch (e) {
      console.error("Could not refresh the story status", e);
      return null;
    }
  }

  async function runStep(key) {
    try {
      const r = await apiJson("/api/story/run/" + encodeURIComponent(key), { method: "POST" });
      if (!r.ok) {
        alert(r.data.detail || "This step could not run.");
      } else {
        displayResult(r.data);
      }
    } catch (e) {
      alert("Error running the step: " + e.message);
    }
    await refreshStatus();
  }

  async function runTwist(caseName) {
    try {
      const r = await apiJson("/api/story/twist/" + encodeURIComponent(caseName), { method: "POST" });
      if (!r.ok) {
        alert(r.data.detail || "This twist could not run.");
      } else {
        displayResult(r.data);
      }
    } catch (e) {
      alert("Error running the twist: " + e.message);
    }
    await refreshStatus();
  }

  // Step buttons
  document.querySelectorAll(".btn-run-step").forEach(function (btn) {
    btn.addEventListener("click", function () {
      const key = btn.dataset.key;
      if (key) runStep(key);
    });
  });

  // Twist buttons
  document.querySelectorAll(".btn-twist").forEach(function (btn) {
    btn.addEventListener("click", function () {
      const caseName = btn.dataset.case;
      if (caseName) runTwist(caseName);
    });
  });

  // Run all remaining steps. Steps unlock one at a time, so ask for the next one each round.
  if (btnAll) {
    const idleLabel = btnAll.textContent;
    btnAll.addEventListener("click", async function () {
      btnAll.disabled = true;
      btnAll.textContent = "Running...";
      try {
        for (let round = 0; round < 30; round++) {
          const status = await refreshStatus();
          if (!status) break;
          const next = status.steps.find(function (s) { return s.status === "todo"; });
          if (!next) {
            if (round === 0) alert("All steps are already completed.");
            break;
          }
          const r = await apiJson("/api/story/run/" + encodeURIComponent(next.key), { method: "POST" });
          if (!r.ok) {
            alert("Step " + next.key + " failed: " + (r.data.detail || "unknown error"));
            break;
          }
          displayResult(r.data);
        }
      } catch (e) {
        alert("Run all failed: " + e.message);
      } finally {
        btnAll.disabled = false;
        btnAll.textContent = idleLabel;
        await refreshStatus();
      }
    });
  }

  // Restore the ledger after the tamper demo
  if (btnRestore) {
    btnRestore.addEventListener("click", async function () {
      try {
        const r = await apiJson("/api/story/restore", { method: "POST" });
        if (r.ok) {
          alert(r.data.message || "Ledger restored.");
        } else {
          alert("Restore failed: " + (r.data.detail || "unknown error"));
        }
      } catch (e) {
        alert("Restore failed: " + e.message);
      }
      await refreshStatus();
    });
  }

  // Reset all demo data
  if (btnReset) {
    btnReset.addEventListener("click", async function () {
      if (!confirm("Reset all demo data? This clears the current story.")) return;
      try {
        const r = await apiJson("/api/story/reset", { method: "POST" });
        if (r.ok) {
          alert("Reset complete. Users: " + r.data.users + ", projects: " + r.data.projects + ", ledger entries: " + r.data.ledger_entries);
          window.location.reload();
        } else {
          alert("Reset failed: " + (r.data.detail || "unknown error"));
        }
      } catch (e) {
        alert("Reset failed: " + e.message);
      }
    });
  }

  refreshStatus();
});