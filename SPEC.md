# SPEC.md: Provenance (Collaborative Research Ecosystem), Gardenia 2K26

## 1\. Situation

* Hackathon: Gardenia 2K26 (Garden City University), 5-6 Oct 2026. Problem: "Collaborative Research Ecosystem". Passed Round 1 (pitch) and Round 2 (paper PoC). Round 3 is the live demo.
* Round 3 scoring (100): Technical implementation 30, Prototype functionality and performance 25, Effectiveness in solving the problem 20, User experience 10, Scalability and real-world applicability 5, Presentation and demo 5, Teamwork and Q\&A 5.
* Build time is about 6 hours. One primary builder (Python intermediate) using Google Antigravity on a free tier with limited quota. Three teammates handle docs, QA and video.
* Rules: free or local models are fine. No real money or real personal data; payments, KYC and agreements are SIMULATED with synthetic users. All code is written after 8:00 AM on 5 Oct. Libraries and templates are fine. Commit history is checked. Every AI coding tool must be declared in the README. Wherever something is mocked, say what production would use.

## 2\. Problem summary

Build a platform that connects research sponsors, domain experts and students into verified, access-controlled project teams. It gives each team a shared workspace powered by generative and agentic AI, records every human and AI contribution in a tamper-evident ledger, protects work against plagiarism, leakage and theft, and distributes monetary and non-monetary rewards fairly according to a project charter that every participant accepted before work began.
Two new problems: (1) who gets credit when an AI agent does part of the work; (2) how sponsor-confidential data stays protected inside AI tools.
Judge test: follow one problem from posting to payout and see at every step who did what, who could see what, and why each person was paid or credited.
Roles and "must never" rules:

* Student: can discover problems, join teams, earn credit (and money if funded). Never sees confidential details before acceptance; never claims others' work.
* Expert: leads or advises, reviews, gets recognition. Never takes credit for student work; never reviews a project with a conflict of interest.
* Sponsor: posts problems, funds milestones, receives results. Never uses deliverables beyond agreed terms; never sees contributors' private data beyond need.
* Admin: verifies identities, resolves disputes, audits. Never silently edits the ledger or payment records.
* AI agent: scoped to ONE project's data and tools. Never acts without a named human owner; never accesses other projects; never leaks data.

## 3\. Final demo story (must run end to end)

1 Post: sponsor posts "Low-cost detection of diabetic retinopathy from fundus images on edge devices" (INR 1,00,000) with charter, public summary, confidential brief.
2 Scope: AI agent proposes milestones and skills. 3 Match: platform recommends 1 expert + 3 students with reasons, filtering out a conflict of interest.
4 Join: members accept the charter; a non-member cannot see the brief. 5 Fund: milestone 1 funded into escrow.
6 Work: humans and agents work; every action logged with a human owner. 7 Catch: copied content is flagged for review.
8 Accept: escrow releases funds and each share is explained. Then a non-monetary project issues credentials and credit with no payment.
9 Verify: editing an old ledger entry makes verification fail. 10 Twist: the panel names a corner case; show how it is handled.
Submission: seeded prototype (one funded and one non-monetary project), repo with README + AI-tool declaration, 2-4 page architecture doc, demo video of 3 minutes or less, 5-minute live demo + 3 minutes Q\&A.

## 4\. Architecture

One FastAPI app with Jinja2 templates, SQLite, plain CSS and minimal vanilla JS. Modules: auth/RBAC (simulated persona login), projects and charter, ledger, escrow and payouts, AI gateway and agents, integrity. Rules: every state-changing action calls ledger.append(); every AI call goes through gateway.call(). Mocked in this prototype (state what production would use): login/KYC (real identity provider), payments (payment gateway + KYC provider), signatures (per-user Ed25519 keys), AI-content detector (vetted classifier), ledger anchoring (public blockchain Merkle-root anchor).

## 5\. Data model: create all 14 tables in S0 so later modules never need migrations

users(id, name, email, role\[student|expert|sponsor|admin], verification\_level INT, institution, is\_minor INT, guardian\_consent INT, conflict\_orgs JSON list, skills JSON list, bio)
projects(id, sponsor\_id, title, public\_summary, confidential\_brief, sensitivity\_label\[public|internal|confidential], engagement\_model\[funded|stipend|knowledge\_sharing|institutional\_credit], status, current\_charter\_version INT, created\_at)
charters(id, project\_id, version INT, terms\_json, hash, published\_at)
charter\_acceptances(id, project\_id, user\_id, charter\_version INT, engagement\_model\_ack INT, accepted\_at)
milestones(id, project\_id, title, deliverables, acceptance\_criteria, required\_skills JSON, amount\_inr INT, status, acceptance\_window\_days INT, created\_at)
contributions(id, milestone\_id, author\_id, agent\_id NULL, artefact\_title, artefact\_text, artefact\_hash, ai\_declaration\[human|ai\_assisted|agent\_generated], similarity\_score REAL, review\_status\[pending|approved|rejected|flagged], impact\_weight REAL, created\_at)
ledger\_entries(id, prev\_hash, entry\_hash, timestamp, actor\_id, actor\_type\[human|agent|system], human\_owner\_id, action, project\_id NULL, payload\_json, payload\_hash, charter\_version NULL)
escrows(id, milestone\_id, amount\_inr, state\[draft|funded|submitted|accepted|released|disputed|refunded], updated\_at)
payouts(id, escrow\_id, user\_id, amount\_inr, role, rationale\_json, receipt\_hash, created\_at)
reviews(id, contribution\_id, reviewer\_id, decision, reasons, criteria\_ref, created\_at)
disputes(id, milestone\_id, raised\_by, status, evidence\_json, resolution, created\_at)
agents(id, name, kind\[scoping|matching|workspace|integrity], human\_owner\_id, project\_id NULL, allowed\_tools JSON)
ai\_calls(id, agent\_id NULL, human\_owner\_id, project\_id NULL, sensitivity\_label, model\_route\[api|local|canned], prompt\_summary, response\_summary, approved\_by NULL, created\_at)
credentials(id, project\_id, user\_id, kind, issued\_at, credential\_hash)

Seed users (all synthetic): 1 admin (Admin Asha); 1 sponsor (Meera Rao, institution "MedVision Labs"); 2 experts (Arvind Nair, skills medical imaging/deep learning/edge deployment; Kiran Shah, similar skills, conflict\_orgs \["MedVision Labs"] so he must be filtered out); 5 students (Ananya, Rahul, Sneha, Vikram with different skill mixes and verification\_level 1+; Tara, is\_minor=1, guardian\_consent=0). Total 9 users.

## 6\. Ledger

Append-only hash chain. entry\_hash = SHA-256(prev\_hash + "|" + canonical\_json(timestamp, actor\_id, actor\_type, human\_owner\_id, action, project\_id, payload\_hash, charter\_version)); canonical\_json uses sort\_keys=True and separators (",",":"). payload\_hash = SHA-256 of canonical payload\_json. Genesis prev\_hash = 64 zeros. verify() recomputes from the first entry and returns (ok, first\_broken\_id). Tamper demo button runs a raw UPDATE on an old payload\_json so verify fails and names the first broken entry. Corrections are NEW entries (action "correction" referencing the old id), never edits. MOCKED: per-user signatures and public anchoring.

## 7\. Charter and engagement models

Models: funded (milestone payments via escrow + credit), stipend (fixed amount stated up front + credit), knowledge\_sharing (no payment: certificates, badges, co-authorship, letters), institutional\_credit. Charter terms: engagement model (unpaid must say so plainly), rewards, scope/milestones/acceptance criteria, people/roles, IP and publication, confidentiality and permitted AI tools, credit split, exit and disputes, future commercialisation. Rules: visible before applying (except the confidential brief); each member accepts a specific version with a SEPARATE engagement-model acknowledgement, recorded in the ledger; any change creates a new version that every affected member must re-accept (work blocked until they do; a member who declines leaves with full credit for accepted work); nothing on a non-monetary project may imply payment.

## 8\. Escrow and split engine

Escrow state machine: draft -> funded -> submitted -> accepted -> released, with disputed -> released|refunded. No milestone work starts until funded. Every transition writes a ledger entry.
Split engine (all percentages configurable): fee 10% and AI compute reserve 5% of the milestone; net = 85%. Expert gets 30% of net. Student pool = rest. 40% of the student pool is split equally; 60% is split by contribution weights. Use largest-remainder rounding so shares sum exactly.
Required unit test: amount 100000, weights \[0.5, 0.3, 0.2] gives students \[25783, 18643, 15074], expert 25500, fee 10000, AI reserve 5000.
Payout receipt shows every line with its reason and a receipt\_hash. AI never earns: AI compute cost is charged visibly, and credit for agent output goes to the human owner who directed and reviewed it. Non-monetary projects issue credentials (credentials table) and credit entries, no payment.

## 9\. AI gateway and agents

gateway.call(agent\_id, human\_owner\_id, project\_id, task, text): routes by project sensitivity\_label (confidential -> local model route via Ollama; otherwise API route to a free-tier model via httpx). If no key, failure or rate limit -> route "canned": deterministic fixtures labelled MOCKED so the demo never breaks. Always writes an ai\_calls row AND a ledger entry (actor\_type agent, human\_owner\_id set). Simple regex redaction (emails, phone numbers) before external calls (MOCKED). Prompt-injection defence: document text is wrapped as DATA with delimiters, the system instruction says never to follow instructions inside the data, and a pattern scan ("ignore previous", "reveal", "system prompt") flags suspicious content. Side-effect actions (share, publish, pay, email) need a recorded human approval (ai\_calls.approved\_by).
Agents: scoping (reads the brief, proposes at least 2 milestones with required skills; sponsor approves), matching (ranks 1 expert + 3 students by skill overlap with a short explanation; excludes anyone whose conflict\_orgs include the sponsor's institution; requires verification\_level >= 1; minors excluded from paid work without guardian consent; small boost for newcomers), workspace (project-scoped drafts, human owner, side effects need approval), integrity (similarity; recommends only, a human decides).

## 10\. Integrity (focus area: Trust and integrity)

Similarity: 3-word shingle Jaccard combined with cosine on token counts against all other contributions; flag when score is 0.6 or more (review\_status = flagged, routed to human review). Provenance label per artefact from ai\_declaration: Human / AI-assisted / Agent-generated (with the agent and its human owner). Watermark: encode the viewer's user id as 8-bit binary into zero-width characters (ZWSP = 0, ZWNJ = 1) inserted after the first word of confidential text shown to that viewer. Leak tracer: paste leaked text, extract the zero-width characters, decode the viewer id. MOCKED: production would use robust fingerprinting; some apps strip zero-width characters.

## 11\. Corner cases (build at least 3 of 5)

1 Student quits midway: credit kept pro rata by weight, access revoked, ledger entry. 2 Sponsor silent: acceptance window passes (demo button "simulate 7 days") -> auto-accept. 3 AI wrote most: ai\_declaration agent\_generated -> credit to the human owner, AI share disclosed on the receipt. 4 Paid becomes unpaid: new charter version, members re-accept or leave with credit. 5 Minor: paid work requires guardian\_consent.

## 12\. UI direction (bold)

Dark theme tokens: bg #0B0D10, panel #12161B, line #232A33, text #E8EDF2, muted #8A97A6, verified lime #C6FF3D, pending amber #FFB020, broken red #FF4D4F, info cyan #3DD6FF. System font stack, monospace for hashes. Signature moments: persona switcher in the top bar; ledger chain strip (blocks link; when tampered the chain turns red and the first broken block shakes); "who can see what" chips (Public / Members / Sponsor); View-as simulator; payout waterfall receipt; agent action cards "Owner: X, awaiting approval"; charter diff with re-accept banner; leak tracer reveal; Story Mode stepper running the 10-step demo with one click per step.

## 13\. Module plan (about 6 hours)

S0 skeleton, all tables, seed, persona switcher, smoke.py (30 min). S1 projects, charters, acceptance, brief gating, View-as (50). S2 ledger, verify, tamper (40). S3 escrow, split engine, payout receipt, credentials (55). S4 gateway, scoping, matching, agent approval (55). S5 integrity: similarity, provenance, watermark, leak tracer (40). S6 Story Mode, corner cases, polish, README (50). Buffer 20.

## 14\. Engineering rules and error protocol

See RULES.md. Error protocol: copy the FULL traceback; note the module and the failing smoke check; ask the AI for the root cause in plain words BEFORE any change; apply the smallest fix; re-run smoke.py; if not fixed in 20 minutes, git reset to the last green tag and re-prompt smaller.

## 15\. Prompt format for every module

GOAL (one module only) / STACK limits / FILES to create or change / DETAILS (from this spec) / DONE WHEN (visible behaviour) / SMOKE CHECKS TO ADD / THEN (run smoke.py, show output, do nothing else).

\## 16. Access rules and membership (added in S1)

\- Single source of truth: app/access.py has can\_view(user\_or\_None, project, resource). Routes AND the "visibility matrix" page both call it. No route re-implements these rules.

\- Resources and rules:

&#x20; - public\_summary: everyone, including anonymous.

&#x20; - charter: everyone (visible before applying).

&#x20; - brief (confidential): the owning sponsor, or a member of the CURRENT charter version. Admin can NOT see it (least privilege).

&#x20; - roster and milestones: owning sponsor, members, and admin (for audit).

\- Membership state comes from the LATEST charter\_acceptances row (highest id) for (project, user):

&#x20; - ack=1 and version = project.current\_charter\_version -> "member"

&#x20; - ack=1 and an older version -> "reaccept\_required" (work and brief blocked until re-accepted)

&#x20; - ack=0 -> "declined" (used later for leaving)

&#x20; - no row -> "none"

\- Join rules, checked in this order: role is student or expert (403); verification\_level >= 1 (403); expert conflict of interest, meaning the expert's conflict\_orgs contains the sponsor's institution (403, "conflict of interest"); minors need guardian\_consent=1 for funded and stipend projects (403, "guardian consent required"); both acknowledgements true (400): accept\_charter AND a SEPARATE ack\_engagement\_model. Joining is idempotent.

\- Charter versions: only the owning sponsor can publish. A new version is a new charters row (version+1, terms\_json, hash = SHA-256 of canonical JSON of {"version": n, "terms": terms}); it updates projects.current\_charter\_version (and engagement\_model if changed). Everyone previously accepted becomes "reaccept\_required".

\- No implied promises: pages for non-monetary projects contain no currency symbols or payment wording (except "no payment" or "unpaid").

\- Charter terms keys: engagement\_model, rewards, scope, people, ip\_publication, confidentiality, credit\_split, exit\_disputes, commercialisation.

\- Ledger hook names for S2: project\_posted, charter\_published, charter\_accepted, charter\_declined.

\- Seed projects (owned by the seeded sponsor, charter v1, no members, no milestones):

&#x20; P1 "Low-cost detection of diabetic retinopathy from fundus images on edge devices": funded, confidential, INR 1,00,000, split terms from section 8.

&#x20; P2 "Open annotation guidelines and benchmark for retinal image quality": knowledge\_sharing, internal, plainly UNPAID (recognition only: certificates, badges, co-authorship, recommendation letters). If later commercialised, contributors keep authorship credit and are notified; any payment terms need a new charter version each contributor must accept.

