// app/static/credentials.js — Client-side verification for digital credentials and certificates

document.addEventListener("DOMContentLoaded", function () {
    // 1. Inline verification buttons on credential cards
    const verifyButtons = document.querySelectorAll(".btn-verify-cred");
    verifyButtons.forEach(function (btn) {
        btn.addEventListener("click", function () {
            const hash = btn.getAttribute("data-hash");
            const targetId = btn.getAttribute("data-target");
            const targetEl = document.getElementById(targetId);

            if (!hash || !targetEl) return;

            btn.disabled = true;
            targetEl.innerHTML = '<span style="color:var(--muted);font-size:0.8rem">Verifying...</span>';

            fetch("/api/credentials/" + encodeURIComponent(hash))
                .then(function (res) {
                    if (res.status === 200) {
                        return res.json().then(function (data) {
                            btn.disabled = false;
                            targetEl.innerHTML = '<span class="chip chip-lime" style="font-size:0.75rem;padding:0.2rem 0.5rem">✓ VALID &amp; ANCHORED</span>';
                        });
                    } else {
                        btn.disabled = false;
                        targetEl.innerHTML = '<span class="chip chip-red" style="font-size:0.75rem;padding:0.2rem 0.5rem">✗ INVALID / NOT FOUND</span>';
                    }
                })
                .catch(function () {
                    btn.disabled = false;
                    targetEl.innerHTML = '<span class="chip chip-red" style="font-size:0.75rem;padding:0.2rem 0.5rem">✗ ERROR</span>';
                });
        });
    });

    // 2. Global hash verification form
    const form = document.getElementById("form-verify-hash");
    const hashInput = document.getElementById("input-cred-hash");
    const manualResult = document.getElementById("manual-verify-result");

    if (form && hashInput && manualResult) {
        form.addEventListener("submit", function (e) {
            e.preventDefault();
            const hash = (hashInput.value || "").trim();
            if (!hash) {
                manualResult.innerHTML = '<div class="alert alert-red">Please enter a valid credential hash.</div>';
                return;
            }

            manualResult.innerHTML = '<span style="color:var(--muted)">Querying ledger registry...</span>';

            fetch("/api/credentials/" + encodeURIComponent(hash))
                .then(function (res) {
                    if (res.status === 200) {
                        return res.json().then(function (data) {
                            manualResult.innerHTML = `
                                <div class="card" style="border-color:#C6FF3D;background:rgba(198,255,61,0.05);margin-top:1rem">
                                    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:0.75rem">
                                        <span class="chip chip-lime">✓ VALID CREDENTIAL</span>
                                        <span class="muted-text" style="font-size:0.8rem">${data.issued_at || ''}</span>
                                    </div>
                                    <h3 style="font-size:1.1rem;margin-bottom:0.5rem;color:var(--text)">${data.project_title || 'Unknown Project'}</h3>
                                    <div style="font-size:0.85rem;color:var(--muted);display:flex;flex-direction:column;gap:0.35rem">
                                        <div><strong>Kind:</strong> ${data.kind || 'certificate'}</div>
                                        <div><strong>User ID:</strong> #${data.user_id}</div>
                                        <div style="word-break:break-all"><strong>Hash:</strong> <code style="font-family:var(--font-mono);color:var(--text)">${data.credential_hash}</code></div>
                                    </div>
                                </div>
                            `;
                        });
                    } else {
                        manualResult.innerHTML = `
                            <div class="card" style="border-color:#FF4D4F;background:rgba(255,77,79,0.05);margin-top:1rem">
                                <span class="chip chip-red">✗ UNVERIFIED / NOT FOUND</span>
                                <p style="margin-top:0.5rem;font-size:0.88rem;color:#FF4D4F">No credential matching this hash exists in the Provenance registry.</p>
                            </div>
                        `;
                    }
                })
                .catch(function () {
                    manualResult.innerHTML = '<div class="alert alert-red" style="margin-top:1rem">Network error verifying credential hash.</div>';
                });
        });
    }
});
