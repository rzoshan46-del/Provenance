/**
 * Provenance — Ledger Interactive UI (Module S2b)
 * Vanilla JS only. No dependencies, no CDN.
 */

async function verifyLedger() {
    const btn = document.getElementById("verify-btn");
    if (btn) {
        btn.disabled = true;
        btn.textContent = "Verifying...";
    }

    try {
        const response = await fetch("/api/ledger/verify");
        if (!response.ok) {
            throw new Error(`HTTP error ${response.status}`);
        }
        const data = await response.json();

        const prefersReducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
        const blocks = Array.from(document.querySelectorAll(".chain-block"));
        const delayMs = prefersReducedMotion ? 0 : 80;

        for (let i = 0; i < blocks.length; i++) {
            const block = blocks[i];
            const entryId = parseInt(block.getAttribute("data-entry-id"), 10);

            // Clear previous state classes
            block.classList.remove("chain-block-verified", "chain-block-broken", "chain-block-unverifiable", "shake-anim");
            const existingTag = block.querySelector(".unverifiable-tag");
            if (existingTag) {
                existingTag.remove();
            }

            if (data.ok) {
                block.classList.add("chain-block-verified");
            } else {
                if (entryId < data.first_broken_id) {
                    block.classList.add("chain-block-verified");
                } else if (entryId === data.first_broken_id) {
                    block.classList.add("chain-block-broken");
                    if (!prefersReducedMotion) {
                        block.classList.add("shake-anim");
                        setTimeout(() => block.classList.remove("shake-anim"), 600);
                    }
                } else {
                    block.classList.add("chain-block-unverifiable");
                    const tag = document.createElement("span");
                    tag.className = "unverifiable-tag";
                    tag.textContent = "unverifiable";
                    block.appendChild(tag);
                }
            }

            if (delayMs > 0 && i < blocks.length - 1) {
                await new Promise((resolve) => setTimeout(resolve, delayMs));
            }
        }

        // Update Integrity Bar
        updateIntegrityBar(data);

    } catch (err) {
        console.error("Ledger verification failed:", err);
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.textContent = "Verify now";
        }
    }
}

function updateIntegrityBar(data) {
    const bar = document.getElementById("integrity-bar");
    if (!bar) return;

    if (data.ok) {
        bar.className = "integrity-bar integrity-ok";
        const group = bar.querySelector(".integrity-status-group");
        if (group) {
            group.innerHTML = `
                <span id="integrity-pill" class="integrity-pill pill-verified">CHAIN VERIFIED</span>
                <span id="integrity-meta" class="integrity-meta">
                    <strong id="integrity-count">${data.checked} entries</strong> &bull; Head:
                    <span id="integrity-head" class="mono head-hash" title="${data.head_hash}">${data.head_hash.slice(0, 12)}</span>
                </span>
            `;
        }
    } else {
        bar.className = "integrity-bar integrity-broken";
        const group = bar.querySelector(".integrity-status-group");
        if (group) {
            group.innerHTML = `
                <span id="integrity-pill" class="integrity-pill pill-broken">CHAIN BROKEN at entry #${data.first_broken_id}</span>
                <span id="integrity-meta" class="integrity-meta">
                    Reason: <strong>${data.reason}</strong> &bull;
                    <span class="broken-warning">Entries after #${data.first_broken_id} can no longer be trusted.</span>
                </span>
            `;
        }
    }
}

async function simulateTampering() {
    const select = document.getElementById("tamper-entry-select");
    const entryId = select ? select.value : "";
    const tamperBtn = document.getElementById("tamper-btn");
    if (tamperBtn) tamperBtn.disabled = true;

    try {
        const formData = new FormData();
        if (entryId) {
            formData.append("entry_id", entryId);
        }
        const response = await fetch("/api/ledger/tamper", {
            method: "POST",
            body: formData,
        });

        if (response.ok) {
            // Reload page to reflect updated server-side state
            window.location.reload();
        } else {
            const err = await response.json();
            alert("Tampering failed: " + (err.detail || "Unknown error"));
            if (tamperBtn) tamperBtn.disabled = false;
        }
    } catch (e) {
        alert("Tampering request failed: " + e.message);
        if (tamperBtn) tamperBtn.disabled = false;
    }
}

async function restoreLedger() {
    const restoreBtn = document.getElementById("restore-btn");
    if (restoreBtn) restoreBtn.disabled = true;

    try {
        const response = await fetch("/api/ledger/restore", {
            method: "POST",
        });

        if (response.ok) {
            window.location.reload();
        } else {
            const err = await response.json();
            alert("Restore failed: " + (err.detail || "Unknown error"));
            if (restoreBtn) restoreBtn.disabled = false;
        }
    } catch (e) {
        alert("Restore request failed: " + e.message);
        if (restoreBtn) restoreBtn.disabled = false;
    }
}
