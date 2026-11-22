# 5-Minute Demo Script

This walkthrough uses the seeded demo personas to show CritX end-to-end. Each step takes about 30 seconds. For a one-click guided version, open **`/story`** in the app.

> **Pre-requisite:** Start the app with `PROVENANCE_DEMO=1` and `AUTH_MODE=demo`. The persona switcher appears in the top bar.

---

## Step 1 — Sponsor Posts a Project (Meera)

1. Switch to **Sponsor Meera** using the persona switcher.
2. Navigate to **Projects**. Notice project *"Low-cost detection of diabetic retinopathy from fundus images on edge devices"* is already posted with a charter, public summary and a locked confidential brief.
3. Click into the project. The charter (v1) shows the funded engagement model, split terms, IP and confidentiality clauses.

## Step 2 — AI Scopes Milestones (Meera)

1. As Meera, trigger **Propose Milestones** via the AI scoping agent.
2. The agent reads the confidential brief through the AI Gateway and proposes 2 milestones with required skills.
3. Review and **approve** both milestones. Escrow rows are created in `draft` state.

## Step 3 — AI Matches Team (Meera)

1. As Meera, run **Match Team**.
2. The matching agent recommends **Expert Arvind** + students **Ananya, Rahul, Sneha** with skill-overlap explanations.
3. Notice: **Kiran** is excluded (conflict of interest with MedVision Labs) and **Tara** is excluded (minor without guardian consent).

## Step 4 — Members Join the Project

1. Switch to **Expert Arvind**. Navigate to the project, accept the charter and acknowledge the engagement model. He can now see the confidential brief.
2. Repeat for **Student Ananya**, **Rahul** and **Sneha**.
3. Switch to **Student Vikram** (not matched). Try to view the brief — **403 Forbidden**.
4. Switch to **Expert Kiran**. Try to join — **403: conflict of interest**.

## Step 5 — Sponsor Funds Milestone 1 (Meera)

1. Switch back to **Sponsor Meera**.
2. Click **Fund** on Milestone 1. The escrow transitions from `draft` → `funded` (MOCKED: production would use a payment gateway).
3. The ledger records `escrow_funded`.

## Step 6 — Members Contribute Work

1. Switch to **Student Ananya**. Submit an original contribution to Milestone 1 with `ai_declaration: human`.
2. Switch to **Student Sneha**. Submit an original contribution with `ai_declaration: ai_assisted`.
3. Switch to **Student Rahul**. Use the **Workspace Agent** to draft a contribution from a clean source document. The draft appears as a pending action. **Approve** it — it is submitted as `agent_generated` with Rahul as the human owner.

## Step 7 — Expert Reviews Contributions (Arvind)

1. Switch to **Expert Arvind**.
2. Review Ananya's contribution — **Approve** with impact score **5**.
3. Review Sneha's contribution — **Approve** with impact score **3**.
4. Review Rahul's contribution — **Approve** with impact score **2**.

## Step 8 — Catch Plagiarism & Injection

1. Switch to **Student Rahul**. Submit Ananya's text verbatim as a new contribution.
2. The integrity engine flags it (similarity score ≥ 0.6) and sets `review_status: flagged`.
3. Switch to **Expert Arvind**. Review the flagged contribution — **Reject** with written reasons against the acceptance criteria.
4. Switch to **Student Sneha**. Use the workspace agent with a document that contains an injection attempt. The AI Gateway blocks the hostile `send_email` tool call and logs `agent_action_blocked`.

## Step 9 — Leak Tracing (Meera)

1. Switch to **Student Ananya**. View the confidential brief — an invisible watermark (zero-width characters encoding her user ID) is embedded and an access log entry is written.
2. Switch to **Sponsor Meera**. Open the **Leak Tracer**. Paste the marked text.
3. The tracer extracts the watermark and identifies **Ananya** with confidence **1.0**.

## Step 10 — Accept Milestone & Payouts (Meera)

1. As **Expert Arvind**, submit Milestone 1 (at least 1 approved contribution exists).
2. Switch to **Sponsor Meera**. **Accept** the milestone.
3. Escrow releases automatically. The payout receipt shows:

   | Recipient | Amount | Reason |
   |-----------|--------|--------|
   | Ananya | ₹25,783 | Highest impact (weight 5) |
   | Sneha | ₹18,643 | Impact weight 3 |
   | Rahul | ₹15,074 | Impact weight 2 |
   | Expert Arvind | ₹25,500 | 30% of net |
   | Platform fee | ₹10,000 | 10% |
   | AI reserve | ₹5,000 | 5% |

4. Credentials (certificates) are issued to all contributors.
5. Check the **Ledger** — every action is recorded in the hash chain.

## Step 11 — Verify Ledger Integrity

1. Open the **Ledger** page and click **Verify** — all entries are valid, the chain is green.
2. Click **Tamper** (demo tool) — an old entry's payload is modified.
3. Click **Verify** again — the chain turns red and the first broken block shakes. The system names the tampered entry.
4. Click **Restore** to fix the chain.

## Step 12 — Graph Visualisation

1. Navigate to the **Contribution Graph** (Cytoscape.js).
2. Explore nodes: users, projects, milestones, contributions, skills.
3. Trace provenance: who contributed what, who reviewed it, and who earned credit.

---

## Guided Demo

For a scripted, one-click-per-step version of this walkthrough, open **`/story`** in the app. Story Mode runs real services in-process as the correct persona for each step.
