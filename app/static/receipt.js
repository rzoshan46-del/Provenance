// app/static/receipt.js — Client verification for verifiable payout receipts

document.addEventListener("DOMContentLoaded", function () {
    const btn = document.getElementById("btn-verify-receipt");
    const resultContainer = document.getElementById("verify-receipt-result");

    if (!btn || !resultContainer) return;

    btn.addEventListener("click", function () {
        const milestoneId = btn.getAttribute("data-milestone-id");
        if (!milestoneId) return;

        btn.disabled = true;
        btn.textContent = "Verifying...";
        resultContainer.innerHTML = '<span class="status-msg pending" style="display:inline-block;padding:0.4rem 0.8rem;border-radius:4px;font-size:0.85rem">Recomputing SHA-256 hashes...</span>';

        fetch("/api/milestones/" + encodeURIComponent(milestoneId) + "/receipt")
            .then(function (res) {
                return res.json();
            })
            .then(function (data) {
                btn.disabled = false;
                btn.textContent = "Verify receipt";

                if (data.receipt_verified) {
                    var inrFormatted = data.amount_inr ? "₹" + Number(data.amount_inr).toLocaleString("en-IN") : "";
                    resultContainer.innerHTML = '<div class="receipt-verify-success" style="padding:0.6rem 1rem;background:rgba(198,255,61,0.12);border:1px solid #C6FF3D;color:#C6FF3D;border-radius:6px;font-size:0.9rem;font-weight:600">✓ Receipt verified: totals reconcile to ' + inrFormatted + '</div>';
                } else {
                    var reason = data.reason || "Payout amounts and hashes do not reconcile";
                    resultContainer.innerHTML = '<div class="receipt-verify-failure" style="padding:0.6rem 1rem;background:rgba(255,77,79,0.12);border:1px solid #FF4D4F;color:#FF4D4F;border-radius:6px;font-size:0.9rem;font-weight:600">✗ Verification failed: ' + reason + '</div>';
                }
            })
            .catch(function (err) {
                btn.disabled = false;
                btn.textContent = "Verify receipt";
                resultContainer.innerHTML = '<div class="receipt-verify-failure" style="padding:0.6rem 1rem;background:rgba(255,77,79,0.12);border:1px solid #FF4D4F;color:#FF4D4F;border-radius:6px;font-size:0.9rem;font-weight:600">✗ Network error verifying receipt</div>';
            });
    });
});
