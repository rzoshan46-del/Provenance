document.addEventListener("DOMContentLoaded", function() {
  const resultCard = document.getElementById("story-result-card");
  const resultTitle = document.getElementById("result-title");
  const resultSummary = document.getElementById("result-summary");
  const resultFacts = document.getElementById("result-facts");
  const resultPersonas = document.getElementById("result-personas");
  const resultLinks = document.getElementById("result-links");
  const bannerTamper = document.getElementById("banner-ledger-tamper");

  async function refreshStatus() {
    try {
      const res = await fetch("/api/story/status");
      if (!res.ok) return;
      const data = await res.json();
      
      if (bannerTamper) {
        bannerTamper.style.display = data.ledger_broken ? "block" : "none";
      }

      data.steps.forEach(s => {
        const item = document.querySelector(`.story-step-item[data-step="${s.key}"]`);
        if (!item) return;

        const chip = item.querySelector(".chip-status");
        const btn = item.querySelector(".btn-run-step");

        if (chip) {
          chip.textContent = s.status;
          chip.className = `chip-status status-${s.status}`;
        }

        if (btn) {
          if (s.status === "done") {
            btn.textContent = "Re-run";
            btn.disabled = false;
          } else if (s.status === "blocked") {
            btn.textContent = "Blocked";
            btn.disabled = true;
          } else {
            btn.textContent = "Run step";
            btn.disabled = false;
          }
        }
      });
    } catch (e) {
      console.error("Failed to refresh story status", e);
    }
  }

  function displayResult(data) {
    if (!resultCard) return;
    resultCard.style.display = "block";
    resultTitle.textContent = data.title || data.key || "Result";
    resultSummary.textContent = data.summary || "";

    resultFacts.innerHTML = "";
    if (data.facts && Object.keys(data.facts).length > 0) {
      for (const [k, v] of Object.entries(data.facts)) {
        const row = document.createElement("div");
        row.className = "fact-item";
        row.innerHTML = `<span class="fact-key">${k}:</span> <span class="fact-val">${v}</span>`;
        resultFacts.appendChild(row);
      }
    } else {
      resultFacts.innerHTML = "<p class='text-muted'>No facts recorded.</p>";
    }

    resultPersonas.innerHTML = "";
    if (data.personas && data.personas.length > 0) {
      data.personas.forEach(p => {
        const a = document.createElement("a");
        a.href = `/switch/${p.user_id}?next=${encodeURIComponent(p.path || "/")}`;
        a.className = "btn btn-outline btn-sm";
        a.textContent = `Open as ${p.name || p.role}`;
        resultPersonas.appendChild(a);
      });
    }

    resultLinks.innerHTML = "";
    if (data.links && data.links.length > 0) {
      data.links.forEach(l => {
        const a = document.createElement("a");
        a.href = l.href;
        a.className = "btn btn-secondary btn-sm";
        a.textContent = l.label;
        resultLinks.appendChild(a);
      });
    }

    resultCard.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  async function runStep(key) {
    try {
      const res = await fetch(`/api/story/run/${key}`, { method: "POST" });
      const data = await res.json();
      if (!res.ok) {
        alert(data.detail || "Error running step");
      } else {
        displayResult(data);
      }
      await refreshStatus();
    } catch (e) {
      alert("Error executing step: " + e.message);
    }
  }

  async function runTwist(caseName) {
    try {
      const res = await fetch(`/api/story/twist/${caseName}`, { method: "POST" });
      const data = await res.json();
      if (!res.ok) {
        alert(data.detail || "Error running twist");
      } else {
        displayResult(data);
      }
      await refreshStatus();
    } catch (e) {
      alert("Error executing twist: " + e.message);
    }
  }

  document.querySelectorAll(".btn-run-step").forEach(btn => {
    btn.addEventListener("click", () => {
      const key = btn.dataset.step;
      if (key) runStep(key);
    });
  });

  document.querySelectorAll(".btn-twist").forEach(btn => {
    btn.addEventListener("click", () => {
      const caseName = btn.dataset.case;
      if (caseName) runTwist(caseName);
    });
  });

  const btnNext = document.getElementById("btn-story-next");
  if (btnNext) {
    btnNext.addEventListener("click", async () => {
      const res = await fetch("/api/story/status");
      const data = await res.json();
      const nextStep = data.steps.find(s => s.status === "todo");
      if (nextStep) {
        await runStep(nextStep.key);
      } else {
        alert("All steps are completed!");
      }
    });
  }

  const btnAll = document.getElementById("btn-story-all");
  if (btnAll) {
    btnAll.addEventListener("click", async () => {
      btnAll.disabled = true;
      btnAll.textContent = "Running...";
      try {
        let res = await fetch("/api/story/status");
        let data = await res.json();
        let todoSteps = data.steps.filter(s => s.status === "todo");
        for (const s of todoSteps) {
          const r = await fetch(`/api/story/run/${s.key}`, { method: "POST" });
          const stepData = await r.json();
          if (!r.ok) {
            alert(`Step ${s.key} failed: ${stepData.detail}`);
            break;
          }
          displayResult(stepData);
          await refreshStatus();
        }
      } catch (e) {
        alert("Run all failed: " + e.message);
      } finally {
        btnAll.disabled = false;
        btnAll.textContent = "Run all remaining";
        await refreshStatus();
      }
    });
  }

  const btnRestore = document.getElementById("btn-story-restore");
  if (btnRestore) {
    btnRestore.addEventListener("click", async () => {
      const res = await fetch("/api/story/restore", { method: "POST" });
      const data = await res.json();
      if (res.ok) {
        alert(data.message || "Ledger restored.");
        await refreshStatus();
      } else {
        alert("Restore failed: " + data.detail);
      }
    });
  }

  const btnReset = document.getElementById("btn-story-reset");
  if (btnReset) {
    btnReset.addEventListener("click", async () => {
      if (!confirm("Are you sure you want to reset all demo data?")) return;
      const res = await fetch("/api/story/reset", { method: "POST" });
      const data = await res.json();
      if (res.ok) {
        alert(`Reset completed! Users: ${data.users}, Projects: ${data.projects}, Ledger: ${data.ledger_entries}`);
        window.location.reload();
      } else {
        alert("Reset failed: " + data.detail);
      }
    });
  }

  refreshStatus();
});
