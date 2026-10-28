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

\## 17. Ledger implementation details (added in S2)

\- Module app/ledger.py. Only this file may write to ledger\_entries, and only by INSERT through append(), except the clearly labelled demo helpers tamper\_demo() and restore\_demo().

\- canonical(obj) = json.dumps(obj, sort\_keys=True, separators=(",",":"), ensure\_ascii=True).

\- payload\_json = canonical(payload); payload\_hash = SHA-256 hex of payload\_json.

\- entry\_hash = SHA-256 hex of prev\_hash + "|" + canonical({"timestamp","actor\_id","actor\_type","human\_owner\_id","action","project\_id","payload\_hash","charter\_version"}). None becomes null. The timestamp is UTC ISO-8601 with milliseconds and is stored exactly as hashed.

\- Genesis entry: action "genesis", actor\_type "system", prev\_hash = 64 zeros, payload {"note":"ledger initialised"}.

\- append(...) validates: actor\_type is human, agent or system; agent entries MUST have human\_owner\_id; human entries default human\_owner\_id to actor\_id. It runs inside BEGIN IMMEDIATE so two writers cannot fork the chain.

\- verify() walks entries by id and checks: (1) payload\_hash == SHA-256(payload\_json); (2) entry\_hash recomputes; (3) prev\_hash equals the previous entry\_hash (64 zeros for the first). It returns ok, checked, first\_broken\_id, reason, head\_hash.

\- Payloads hold ids, hashes and short labels only. NEVER put confidential text (briefs, artefact text) or emails in a payload.

\- Visibility: verify is public. A project's entries are fully visible only if can\_view(user, project, 'roster') is true; otherwise they are returned REDACTED (id, prev\_hash, entry\_hash, timestamp only), so the chain stays checkable without leaking content. Entries without a project (genesis, system) are visible to everyone.

\- Demo tools: tamper adds "\_tampered": true to the payload\_json of an old entry (simulating someone editing the database directly); restore removes it. They are enabled unless env PROVENANCE\_DEMO is "0" (read on every call) and write no ledger entry.

\- Limits (say this in the demo): someone with full database control who re-computes every later hash is detected only by an external anchor. MOCKED: production would anchor the head hash or a Merkle root on a public blockchain and use per-user signatures.

\- Action vocabulary for later modules: genesis, project\_posted, charter\_published, charter\_accepted, charter\_declined, member\_left, milestone\_proposed, escrow\_funded, escrow\_state\_changed, contribution\_submitted, contribution\_flagged, review\_recorded, payout\_released, credential\_issued, agent\_action, agent\_action\_approved, dispute\_opened, dispute\_resolved, correction.

\## 18. Milestones, escrow, split, contributions, credentials (added in S3)

\- Milestone status: proposed | open | submitted | accepted. Manual creation by the sponsor sets "open" (S4's scoping agent will create "proposed"; the sponsor approves it to "open"). Funded projects: amount\_inr is a positive integer and an escrow row is created in state draft. Non-funded projects: amount\_inr MUST be 0 and no escrow row exists (no implied promises). stipend and institutional\_credit are not used in the demo; they behave like non-monetary (credentials only). MOCKED/not implemented: stipend payments.

\- Escrow transitions (app/services/escrow.py, escrow\_transition): draft->funded (sponsor owner; MOCKED payment, production would use a payment gateway + KYC); funded->submitted (expert member; needs at least 1 approved contribution); submitted->accepted (sponsor owner); accepted->released (automatic in the same call); submitted->funded and disputed->released|refunded are reserved for S6. Anything else raises ValueError. On funded projects no contribution can be submitted until the escrow state is funded.

\- Contributions: submitted by members of the CURRENT charter version. ai\_declaration is mandatory (human | ai\_assisted | agent\_generated). artefact\_hash = SHA-256 of the text. Reviewed only by expert members who are not the author and have no conflict of interest. Approve needs an integer impact\_score 1-10 (stored as impact\_weight); reject needs non-empty reasons stated against the acceptance criteria. A contribution is reviewed once (later attempts get 409). Credit ALWAYS goes to the human author; AI agents never receive payouts or credentials.

\- Split engine, app/splits.py: pure function compute\_split(amount\_inr, student\_weights {user\_id: weight}, expert\_ids, config=None). Uses fractions.Fraction and integer rupees. Default config: fee 0.10, ai\_reserve 0.05 (both of the milestone amount, rounded half up), expert\_share 0.30 of net, equal\_part 0.40 of the student pool. Expert pool is split equally among experts; if there are no experts it is added to the student pool. All-zero weights mean an equal split. No students raises ValueError("no eligible students"). Largest-remainder rounding; ties go to the LOWEST weight, then the lowest user id (this reproduces the handout example).

\- Weights: a student's weight is the sum of impact\_scores of their approved contributions on that milestone. Participants are students and experts with at least 1 approved contribution on that milestone; other members receive nothing for it.

\- Payouts: one row per paid person. rationale\_json holds the full breakdown (amount, config, fee, reserve, net, role, weight, weight share, equal part, weighted part, rounding adjustment, a plain-English sentence, and an AI-credit note when relevant). receipt\_hash = SHA-256 of canonical({escrow\_id, user\_id, amount\_inr, rationale}). The milestone receipt hash (SHA-256 of canonical({milestone\_id, amount\_inr, fee\_inr, ai\_reserve\_inr, payout\_hashes sorted})) goes in the ledger payout\_released payload. verify\_receipt recomputes everything and checks that payouts + fee + AI reserve equal the milestone amount. MOCKED: production would reconcile the AI reserve against metered AI usage.

\- Credentials: on acceptance, one "certificate" per contributor in every engagement model. credential\_hash = SHA-256 of canonical({project\_id, user\_id, kind, milestone\_id, charter\_version, issued\_at}). Public check: GET /api/credentials/{hash}.

\- Credit statement (non-monetary): computed live from approved contributions' impact scores as percentage shares. It contains no currency symbols or payment wording.

\- Visibility: milestones, contributions and receipts are visible to the owning sponsor, members and admin (can\_view 'milestones').

\- New ledger actions: milestone\_created, milestone\_approved, milestone\_submitted, milestone\_accepted (in addition to section 17).

\- Money is integer rupees everywhere. Indian digit grouping is used for display (1,00,000).

\- Demo numbers: a milestone of INR 1,00,000 with impact scores 5, 3, 2 and one expert reproduces the handout: students 25,783 / 18,643 / 15,074 and expert 25,500.

\## 19. AI layer: gateway, agents, scoping, matching, approval (added in S4)

\- Package app/ai/: gateway.py, agents.py, canned.py, scoping.py, matching.py, workspace.py. NO other file may import httpx or call a model.

\- Config comes from environment variables only (read on every call; never hard-coded or committed): PROVENANCE\_LLM (auto | canned; default auto), GEMINI\_API\_KEY, GEMINI\_MODEL (confirm the current free-tier model id in Google AI Studio), OLLAMA\_URL (default http://localhost:11434), OLLAMA\_MODEL. smoke.py sets PROVENANCE\_LLM=canned before importing the app.

\- Routing, pure function choose\_route(sensitivity\_label, mode, has\_api\_key, local\_available): mode canned -> canned. confidential -> local if available, otherwise canned, NEVER api. Any other label -> api if a key exists, otherwise canned. Any timeout, HTTP error or unusable output falls back to canned. ai\_calls.model\_route stores the route ACTUALLY used; the intended route and fallback\_reason are in the prompt\_summary JSON. Local availability = GET {OLLAMA\_URL}/api/tags within 1 second (cached 30 s).

\- Agents are rows in agents, unique per (kind, project\_id, human\_owner\_id), always with a human owner: scoping (allowed\_tools \["propose\_milestones"], owner = sponsor), matching (\["rank\_candidates"], owner = sponsor), workspace (\["draft\_text","summarize"], owner = the member using it), integrity (\[] , S5). Using an agent with a project other than its own raises PermissionError and writes a ledger agent\_action\_blocked entry.

\- gateway.call(agent\_id, task, instruction, data="", project\_id=None, meta=None, extra\_payload=None, response\_override=None) returns a result with text, route, intended\_route, call\_id, flags, redactions, blocked\_tools and tool\_requests. It: checks agent scope and owner; redacts emails and phone numbers in everything sent to a model (MOCKED regex redaction); wraps document text as untrusted DATA between delimiters with an instruction never to follow instructions inside it; scans for injection patterns (ignore previous/all instructions, disregard, reveal, system prompt, you are now, send ... email, exfiltrate) and records the labels; calls the chosen route; parses lines of the form "TOOL: name(args)" in the output; BLOCKS any tool not in the agent's allowed\_tools (ledger agent\_action\_blocked with the tool name and an args hash, never executed); writes an ai\_calls row and a ledger agent\_action entry (actor\_type agent, actor\_id = the agent id, human\_owner\_id = the owner).

\- ai\_calls.prompt\_summary is a JSON string: {"task","input\_hash","input\_chars","redactions","injection\_flags":\[...],"intended\_route","fallback\_reason","status":"done|pending|approved|rejected","meta":{...}}. Raw prompts, brief text and email addresses are NEVER stored in ai\_calls or the ledger. response\_summary holds hashes and sizes by default; matching stores its structured result JSON (ids, scores, reasons); workspace drafts store the full draft text (MOCKED: production would use a drafts table with access control).

\- In canned mode, when injection flags are present, the workspace fixture appends a simulated hostile line "TOOL: send\_email(...)" to demonstrate the block. Label it "SIMULATED compromised model output (MOCKED)".

\- Seeded skills (exactly): Arvind Nair: medical imaging, deep learning, edge deployment. Kiran Shah: medical imaging, deep learning, edge deployment, model quantization. Ananya: python, deep learning, data labelling. Rahul: python, edge deployment, model quantization. Sneha: python, medical imaging, data labelling. Vikram: web development, python, data analytics. Tara: python, deep learning, medical imaging.

\- Scoping: only the owning sponsor runs propose\_milestones(project\_id, budget\_inr). The agent gets the confidential brief as DATA via the gateway. At least 2 milestones with status "proposed", NO escrow yet; funded projects: budget\_inr must be a positive integer and the amounts split equally with the remainder on the last milestone; non-funded: all amounts 0. If milestones already exist: 409. Model output must be a JSON array of {title, deliverables, acceptance\_criteria, required\_skills\[]}; invalid output falls back to the canned fixture. Canned fixture: M1 "Data audit and baseline retinopathy classifier" (medical imaging, deep learning, data labelling, python); M2 "Edge optimisation and field evaluation" (edge deployment, model quantization, python). Ledger milestone\_proposed (actor = scoping agent, owner = sponsor). approve\_milestone(user, milestone\_id, amount\_inr=None): only the sponsor owner; status must be proposed (409); sets "open"; funded projects get an escrow row in state draft; ledger milestone\_approved. Proposed milestones are visible only to the sponsor and admin.

\- Matching: only the owning sponsor. Required skills = the union (lower-cased) over the project's proposed and open milestones; none gives 409. Eligible: role expert or student; verification\_level >= 1; not blocked by conflict of interest (an expert whose conflict\_orgs contains the sponsor's institution); minors need guardian\_consent=1 on funded projects. score = matched/required + 0.05 newcomer boost for students with no credentials; ties go to the higher verification\_level, then the lower id. Output: 1 expert + 3 students with deterministic explanations (matched and missing skills, verification level, newcomer note), plus an "excluded" list with one reason each ("conflict of interest", "guardian consent required", "verification level too low"). One gateway call produces a short summary; the structured result is stored via response\_override.

\- Human approval for side effects: a workspace draft creates a PENDING action (ai\_calls, task workspace\_draft, approved\_by NULL). Only the human owner can approve (even the sponsor gets 403). Approval submits the draft as a contribution authored by the owner with ai\_declaration agent\_generated and agent\_id set, through contributions.submit\_contribution (credit goes to the human), then sets approved\_by and writes ledger agent\_action\_approved. Reject sets status rejected and writes agent\_action\_rejected. If the source document was flagged, approval needs confirm\_flagged=true (400 otherwise). If submit\_contribution fails (for example the escrow is not funded), the action stays pending and the error is returned.

\- Ledger additions: agent\_action\_blocked, agent\_action\_rejected. ledger.list\_entries resolves actor\_name for actor\_type agent from the agents table, not from users.

\- Visibility: ai\_calls, agent actions and the AI Firewall are visible to the owning sponsor, members and admin; draft text only to its owner.

\## 20. Integrity: similarity, provenance, watermark, leak tracing (added in S5)

\- Package app/integrity/: similarity.py, signals.py, provenance.py, watermark.py, service.py. Integrity logic lives only here. Stored text is NEVER modified; watermarks are applied at output time only.

\- Tokenise: lower-case, regex \[a-z0-9]+. Shingles are 3-word tuples. compare(new\_text, other\_text) returns {jaccard, cosine, containment, score}: jaccard over shingle sets; cosine over token counts; containment = |A∩B| / |A| where A = the new text's shingles (only when A has at least 5 shingles); score = max(0.5\*jaccard + 0.5\*cosine, containment). Texts with fewer than 3 tokens score 0. FLAG\_THRESHOLD = 0.6.

\- check\_contribution(contribution\_id) runs at the end of submit\_contribution. It compares the new text with every contribution by OTHER authors on the whole platform (all projects; a user's own earlier work never counts). The maximum score goes into contributions.similarity\_score. Reasons: "similarity" when score >= 0.6; "possible\_undisclosed\_ai" when ai\_declaration is "human" and the MOCKED heuristic finds a strong marker (case-insensitive): "as an ai language model", "as a large language model", "i'm sorry, but i can't", "certainly! here", "regenerate response". Any reason sets review\_status "flagged" and writes a ledger contribution\_flagged entry (actor\_type system, payload {contribution\_id, reasons, score with 2 decimals, matched\_contribution\_id (only when the match is in the SAME project, else null), cross\_project}). The ledger never contains text.

\- Limits (say them in the demo): it catches verbatim and near-verbatim copying, not paraphrase. MOCKED: production would add semantic similarity and a vetted AI-content classifier.

\- Human review gates: only a human expert reviews flagged work (S3 rules). Approving a flagged contribution requires a non-empty written justification (reasons), otherwise 400. submit\_milestone returns 409 ("flagged contributions must be resolved first") while any contribution on the milestone is flagged. The system recommends; a human decides.

\- integrity\_report(user, contribution\_id): visible to the sponsor, members and admin (can\_view 'milestones'). Returns score, reasons, and for a SAME-project match its title, author name and up to 3 shared 3-word phrases; for a cross-project match only "matches content in another project (details hidden)". preview\_check(user, text, ai\_declaration="human", milestone\_id=None) returns score and reasons without creating anything (match details only when milestone\_id is given and visible to the caller).

\- Provenance: label per contribution from ai\_declaration and agent\_id: Human | AI-assisted | Agent-generated (with the agent name and its human owner). ai\_breakdown(milestone\_id) = percentages of reviewed impact (sum of impact\_weight of approved contributions) by declaration (human, ai\_assisted, agent\_generated), each rounded to 1 decimal with the rounding remainder on the largest share so they sum to 100.0. It is included in the receipt and the credit statement, computed LIVE and NOT part of any hash. Credit always goes to the human.

\- Authorship lookup: authorship\_lookup(user, text) hashes the text with SHA-256 and returns the EARLIEST contribution with the same artefact\_hash among contributions the user can see (can\_view 'milestones'), with author name, submitted time and the id of its contribution\_submitted ledger entry; otherwise {"found": false}. Matches in projects the user cannot see are never revealed.

\- Watermark (MOCKED robustness): marker = U+2060 + 24 bits + U+2060, where the bits are the 16-bit user id followed by an 8-bit checksum (sum of the two id bytes mod 256), 0 = U+200B and 1 = U+200C. apply(text, user\_id) inserts the marker after the first word of every non-empty line (appends it when a line is a single word). extract(text) finds all well-formed markers and returns {found, valid, user\_id, marks\_found, marks\_valid, confidence} by majority vote over marks with a valid checksum (confidence = votes for the winner / marks\_found). strip(text) removes markers; strip(apply(t)) == t exactly. Applied to every viewer EXCEPT the content's owner (the owning sponsor for the confidential brief; the author for a contribution): to the confidential brief and to contribution text, in both HTML and API output. artefact\_hash is always of the clean stored text. Defeated by retyping or by tools that strip invisible characters; production would use robust fingerprinting. Pages that show such content to a non-owner also show a visible overlay "Viewed by <name> · <date>".

\- Access log: serving the brief or a contribution text to a non-owner writes a ledger content\_viewed entry (actor = the viewer, project\_id set, payload {resource, resource\_id, watermark\_id}) at most once per (viewer, resource). Never the text.

\- Leak tracer: POST /api/integrity/trace (sponsor or admin only, 403 otherwise). It extracts the marker. Not found returns {"found": false, "message": "no watermark found (text may have been retyped, stripped or paraphrased)"}. Found: an admin may trace any user; a sponsor only a viewer who has a content\_viewed entry on one of THEIR projects (otherwise 404). The response has the viewer's name, role, confidence, marks\_found, marks\_valid and the viewer's logged views (limited to the caller's visibility). Every successful trace writes a ledger leak\_traced entry (payload {traced\_user\_id, confidence}); the traced text is never stored or returned.

\- New ledger actions: content\_viewed, leak\_traced (contribution\_flagged exists).
## 21. Corner cases, demo tools, Story Mode (added in S6)
- leave_project(user, project_id): allowed only from states member or reaccept_required (409 otherwise). Inserts a charter_acceptances row with engagement_model_ack=0 at the current version (state becomes "declined"). Ledger member_left (previous state member) or charter_declined (previous state reaccept_required), payload {user_id, previous_state, approved_contributions, total_impact}. Access is revoked automatically through can_view. CREDIT IS KEPT: payout and credential participants are everyone with an approved contribution on the milestone, whether or not they are still members, shared by reviewed impact (pro rata). A declined user may join again later.
- finalize_acceptance(milestone_id, actor, auto=False) is the single code path that releases a milestone (payouts, credentials, ledger). accept_milestone calls it for the sponsor. auto_accept_overdue(milestone_id, now=None) calls it with actor None (ledger actor_type system, payload {"auto": true, "reason": "acceptance window elapsed"}) when now minus the submission time is at least acceptance_window_days; otherwise 409 "acceptance window still open". The submission time is the timestamp of the latest ledger milestone_submitted entry for the milestone (parse ISO-8601 with datetime.fromisoformat after replacing a trailing Z with +00:00). escrow_transition accepts actor=None meaning "system". Demo tool: POST /api/milestones/{id}/simulate-days (admin only; form field days) computes now = submission time + days, writes no fake timestamps, and is labelled "DEMO TOOL: simulates time passing". Production would run auto-accept as a scheduled job.
- Engagement model change (publish_charter): funded -> non-funded is allowed only if the project has NO escrow in state funded, submitted, accepted or released (else 409 "funds are held: resolve escrow first"; MOCKED: production would refund held escrow) and a non-empty change_note is given. Draft escrow rows are deleted and milestone amounts set to 0; the terms rewards and credit_split are replaced (rewards from the sponsor, credit_split by the default "Credit is shared by reviewed impact. No payment is offered or implied."). non-funded -> funded gives 400 (start a new project). Everyone previously accepted becomes reaccept_required and must re-accept WITH the new engagement-model acknowledgement or leave with credit. For non-funded models the rewards text may not contain a currency symbol or the words pay, paid, payment, salary, stipend, fee (except inside "no payment" or "unpaid"): 400. This applies in create_project and publish_charter.
- The minor rule (guardian consent for funded work) and "AI wrote most" (provenance and ai_breakdown, credit to the human) already exist from S1 and S5.
- Demo mode: environment PROVENANCE_DEMO != "0" (read on every call) enables ledger tamper and restore, simulate-days, POST /api/demo/reset and all Story Mode endpoints. All return 403 when it is "0". demo.reset() empties all 14 tables (disable foreign keys, delete in a safe order, clear sqlite_sequence), then runs seed_users, ledger.ensure_genesis and seed_projects. Ledger rows may only be deleted by ledger.reset_for_demo() inside app/ledger.py, labelled "DEMO TOOL".
- Story Mode (app/story.py) runs REAL services in-process as the right persona; it is a presenter's orchestrator. MOCKED: it impersonates personas and is disabled when PROVENANCE_DEMO=0. Step keys in order: post, scope, match, join, fund, work, catch, trace, accept, unpaid, verify, twist. Each run returns {ok, key, title, summary, facts{...}, personas[{name,id,path}], links[...]}. Steps are idempotent (a second run reports "already done" and creates nothing) and enforce prerequisites (409 "run step <previous key> first"). Status is derived from the database. Use the real function names found in the code; adapt to them, do not rename.
  post: confirm seeded P1 (the handout title) exists, show the public summary, charter v1 and that the brief is locked for anonymous.
  scope: sponsor runs propose_milestones(P1, 100000) and approves both. match: sponsor runs matching (Arvind plus Ananya, Rahul, Sneha; Kiran excluded for conflict, Tara for guardian consent).
  join: Arvind, Ananya, Rahul, Sneha join P1; record that Vikram (non-member) gets 403 on the brief and that Kiran's join attempt is refused for conflict of interest.
  fund: sponsor funds milestone 1.
  work: Ananya submits an original text (human); Sneha submits an original text (ai_assisted); Rahul asks the workspace agent for a draft from a clean source document and approves it (agent_generated); Arvind approves the three with impact 5, 3, 2.
  catch: Rahul submits Ananya's text verbatim, it is flagged (score at least 0.6) and Arvind rejects it with written reasons against the acceptance criteria; Sneha asks the workspace agent about the injection sample document: the hostile send_email tool is blocked and she rejects the action.
  trace: Ananya views the brief (protected output, logged); the sponsor traces her marked copy and the tracer names Ananya with confidence 1.0.
  accept: Arvind submits milestone 1; the sponsor accepts; facts list each payout with its sentence, the receipt hash and verification.
  unpaid: on P2 (knowledge_sharing) Arvind, Ananya, Sneha and Rahul join, the sponsor creates a milestone with amount 0, they contribute unique texts, Arvind approves, submits, the sponsor accepts; facts show no payouts, credentials issued and the credit shares.
  verify: tamper an early entry, run verify and report the first broken entry; the chain stays broken until restore (POST /api/story/restore).
  twist: five sandbox cases, each on its own fresh project so the main story is never disturbed: quit (a member leaves, credit kept, access revoked), silent (sponsor goes silent, auto-accept after the window), unpaid (charter v2 funded -> unpaid with re-accept or leave), minor (Tara blocked for guardian consent), ai (AI wrote most: the AI breakdown is disclosed and credit goes to the human).
- GET /switch/{id}?next=/path: next must start with a single "/" and not "//" or a scheme; anything else redirects to "/".

