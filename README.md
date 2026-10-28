# Provenance (CritX)

> **Many minds. One mission. Every contribution counted.**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python: 3.11+](https://img.shields.io/badge/Python-3.11%2B-blue.svg)](https://www.python.org/)
[![Framework: FastAPI](https://img.shields.io/badge/Framework-FastAPI-009688.svg)](https://fastapi.tiangolo.com/)
[![Database: SQLite](https://img.shields.io/badge/Database-SQLite-003B57.svg)](https://www.sqlite.org/)
[![Test Suite: 130+ Checks](https://img.shields.io/badge/Tests-130%2B%20Passing-brightgreen.svg)](smoke.py)

**Provenance** is an open-source, cryptographically verified collaborative research ecosystem connecting research sponsors, domain experts, and student researchers. It solves the modern trust crisis in academic and industrial R&D through **zero-trust access control**, an **append-only SHA-256 audit ledger**, **per-viewer steganographic leak tracing**, a **mathematically exact rupee split engine**, and **scoped AI workflows with prompt injection firewalls**.

---

## The Problem: The Trust & Credit Crisis in Collaborative R&D

Modern research ecosystems face four fundamental breakdowns:

1. **Attribution Theft & Undisclosed AI**: Students often do heavy lifting without receiving fair attribution, while undisclosed AI tools generate code or text that gets claimed as original human research.
2. **Confidentiality Leaks**: Research sponsors hesitate to share high-value clinical or proprietary datasets with student teams out of fear that confidential details will be leaked or pasted into public cloud LLMs.
3. **Scope Creep & Broken Promises**: Milestone terms and stipends are frequently modified mid-project without multi-party consent, leaving contributors stranded.
4. **Financial Rounding & Unfair Splits**: Discretionary reward distributions lack mathematical transparency, often shortchanging junior contributors.

**Provenance solves this end-to-end** with deterministic rules enforced at the server layer.

---

## Architectural Pillars

```
 ┌────────────────────────────────────────────────────────────────────────┐
 │                      PROVENANCE ECOSYSTEM                              │
 └────────────────────────────────────┬───────────────────────────────────┘
                                      │
     ┌────────────────────────────────┼──────────────────────────────┐
     ▼                                ▼                              ▼
┌──────────────┐             ┌─────────────────┐            ┌──────────────────┐
│ ACCESS & RBAC│             │ LIVING CHARTER  │            │  AI FIREWALL     │
│ Server-side  │             │ Versioned terms │            │  Scoped agents,  │
│ zero-trust   │             │ Multi-party ack │            │  Prompt defense, │
│ rules engine │             │ Scope-creep safe│            │  PII redaction   │
└──────┬───────┘             └────────┬────────┘            └────────┬─────────┘
       │                              │                              │
       └──────────────────────┬───────┴──────────────────────────────┘
                              ▼
        ┌──────────────────────────────────────────────┐
        │       APPEND-ONLY HASH-CHAINED LEDGER        │
        │  SHA-256 Prev-Hash Link  • BEGIN IMMEDIATE   │
        │  Live Tamper Detection   • Redacted Audit    │
        └─────────────────────┬────────────────────────┘
                              │
     ┌────────────────────────┼──────────────────────────────┐
     ▼                        ▼                              ▼
┌──────────────────┐  ┌──────────────────┐         ┌───────────────────┐
│ ESCROW & SPLIT   │  │ STEGANOGRAPHY    │         │ INTEGRITY ENGINE  │
│ Exact fractions  │  │ Zero-width marks │         │ 3-word shingles   │
│ Largest-remainder│  │ Leak tracer      │         │ Jaccard + Cosine  │
│ No float math    │  │ Viewer-bound text│         │ Undisclosed AI    │
└──────────────────┘  └──────────────────┘         └───────────────────┘
```

### 1. Living Project Charters & Multi-Party Consent
- Projects begin with an immutable, versioned charter.
- Participants must explicitly accept both the charter terms and the engagement model (`funded` vs. `knowledge_sharing`).
- Any mid-project modification automatically triggers a `reaccept_required` state across all participants, locking access to confidential briefs until mutual consent is restored or contributors exit with full pro-rata credit.

### 2. Zero-Trust Access Control ([`app/access.py`](app/access.py))
- Single server-side source of truth (`can_view()`). Authorization is never entrusted to cosmetic frontend DOM hiding.
- **Least-Privilege by Design**: Even platform **Administrators are strictly blocked from reading confidential research briefs**—only the project sponsor and verified active team members hold access.

### 3. Append-Only Cryptographic Audit Ledger ([`app/ledger.py`](app/ledger.py))
- Every single state transition (charters, joins, milestones, reviews, contributions, payouts) forms an unbroken SHA-256 hash chain:
  $$\text{entry\_hash} = \text{SHA-256}(\text{prev\_hash} \parallel \text{canonical}(\text{fields}))$$
- Concurrency-safe transactions using SQLite `BEGIN IMMEDIATE`.
- **Live Tamper Verification**: Any manual modification of a database record breaks backward hash validation, pointing directly to the corrupted entry ID in real time.

### 4. Forensic Zero-Width Steganography ([`app/integrity/watermark.py`](app/integrity/watermark.py))
- When confidential briefs or deliverables are served, the engine injects imperceptible zero-width unicode characters (`U+2060`, `U+200B`, `U+200C`) encoding the viewer's 16-bit User ID and an 8-bit checksum.
- If text is leaked onto the public web, the sponsor or admin can paste it into the **Integrity Center** (`/integrity`) to recover the leaker's identity with 100% mathematical confidence.

### 5. Mathematically Exact Split Engine ([`app/splits.py`](app/splits.py))
- Built strictly with Python `fractions.Fraction` and integer paise/rupees—completely eliminating floating-point rounding errors.
- Uses **Hare-Niemeyer (Largest-Remainder)** integer distribution to guarantee:
  $$\sum \text{Student Shares} + \sum \text{Expert Shares} + \text{Platform Fee (10\%)} + \text{AI Reserve (5\%)} \equiv \text{Milestone Total}$$

### 6. Scoped AI Gateway & Prompt Firewall ([`app/ai/gateway.py`](app/ai/gateway.py))
- Every AI agent must have a named human supervisor; autonomous unowned actions are prohibited.
- **Data Privacy Routing**: Confidential projects automatically route to local air-gapped LLMs (Ollama); cloud APIs are blocked.
- **AI Firewall**: Scans inbound content for adversarial prompt injections (`ignore previous instructions`, `reveal system prompt`) and quarantines suspicious tool calls (e.g. `send_email`).

---

## Human Engineering & AI Co-Development Philosophy

This project was built through a high-discipline **human-in-the-loop pair-programming methodology**:

- **Architectural & Security Invariants (Crafted by Human Design)**: The zero-trust least-privilege matrix, the fractional split algorithms, the zero-width steganographic bit-encoding schemes, and the cryptographic ledger rules were manually conceptualized, specified, and enforced.
- **High-Velocity AI Amplification**: Generative AI tools (Google Antigravity) were utilized as an agile engineering accelerant—generating synthetic biomedical datasets, building test harnesses, and rapidly scaffolding comprehensive integration scenarios.
- **Test-Driven Defense**: Nothing was declared complete without passing a suite of **over 130+ continuous end-to-end invariant checks** in `smoke.py`. Every AI prompt, decision, and generation is transparently logged in `AI_USAGE.md`.

---

## 5-Minute Tour for Evaluators & Judges

When evaluating the live application, we recommend following this narrative path:

1. **The Interactive Story Mode (`/story`)**:
   - Navigate to [http://127.0.0.1:8000/story](http://127.0.0.1:8000/story).
   - Step through the complete 12-stage lifecycle with 1-click execution:
     `Post` $\to$ `Scope` $\to$ `Match` $\to$ `Join` $\to$ `Fund` $\to$ `Work` $\to$ `Catch` $\to$ `Trace` $\to$ `Accept` $\to$ `Unpaid` $\to$ `Verify` $\to$ `Twist`.
2. **Zero-Trust Access Matrix (`/projects/1/visibility`)**:
   - Inspect the live visibility table demonstrating how anonymous visitors, students, experts, and administrators see completely different data slices based on backend rules.
3. **Plagiarism & Undisclosed AI Gating (`/projects/1/milestones`)**:
   - View how contributions exceeding 0.6 shingle similarity or containing boilerplate LLM signatures are locked until an expert provides written justification.
4. **Steganographic Leak Tracer (`/integrity`)**:
   - View confidential text as student Ananya, copy the text, and paste it into the tracer to reveal her user ID.
5. **Ledger Tamper Experiment (`/projects/1`)**:
   - Trigger a simulated database tamper and watch the real-time cryptographic verification fail with a red indicator flagging the exact altered block.

---

## Getting Started

### Prerequisites
- Python 3.11+
- Git

### Installation & Run

#### Windows (PowerShell)
```powershell
# Clone the repository
git clone https://github.com/rzoshan46-del/CritX.git
cd CritX

# Create and activate virtual environment
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# Install dependencies
pip install -r requirements.txt

# Reset and seed synthetic data
python demo_reset.py

# Run verification suite (130+ end-to-end checks)
python smoke.py

# Launch development server
uvicorn app.main:app --reload --port 8000
```

#### macOS / Linux
```bash
# Clone the repository
git clone https://github.com/rzoshan46-del/CritX.git
cd CritX

# Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Reset and seed synthetic data
python3 demo_reset.py

# Run verification suite (130+ end-to-end checks)
python3 smoke.py

# Launch development server
uvicorn app.main:app --reload --port 8000
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000) in your browser.

---

## Quick Navigation

| Module | URL | Description |
| :--- | :--- | :--- |
| **Home / Feed** | [http://127.0.0.1:8000/](http://127.0.0.1:8000/) | Live projects, quick persona switch, active milestones |
| **Story Walkthrough** | [http://127.0.0.1:8000/story](http://127.0.0.1:8000/story) | 1-click end-to-end evaluator demonstration |
| **Integrity Center** | [http://127.0.0.1:8000/integrity](http://127.0.0.1:8000/integrity) | Plagiarism checker, provenance breakdown, leak tracer |
| **Projects & Charters**| [http://127.0.0.1:8000/projects](http://127.0.0.1:8000/projects) | Living charters, version history, escrow status |
| **Persona Switcher** | [http://127.0.0.1:8000/login](http://127.0.0.1:8000/login) | Switch between 9 seeded personas (Sponsor, Expert, Student, Admin) |

---

## Prototype Status & Production Roadmap

In this hackathon release, certain external infrastructure integrations are simulated for deterministic evaluation:
- **Identity & KYC**: Simulated via topbar persona switcher and `persona_id` session cookies. Production would integrate OAuth2/OIDC, DigiLocker, or SAML/SSO.
- **Banking Escrow**: Simulated internal escrow states (`draft` $\to$ `funded` $\to$ `submitted` $\to$ `accepted` $\to$ `released`). Production would integrate with banking partners (e.g. Razorpay Escrow / Cashfree).
- **Public Blockchain Anchoring**: Local SQLite SHA-256 hash chain. Production would anchor periodic Merkle roots to public chains (Polygon / Ethereum).

---

## Contributing

Contributions, feedback, and security reviews are welcomed!

1. Fork the Project
2. Create your Feature Branch (`git checkout -b feature/InnovativeFeature`)
3. Run the validation suite to ensure zero regressions (`python smoke.py`)
4. Commit your Changes (`git commit -m 'feat: add InnovativeFeature'`)
5. Push to the Branch (`git push origin feature/InnovativeFeature`)
6. Open a Pull Request

---

## License & Copyright

Distributed under the **MIT License**. See [`LICENSE`](LICENSE) for full details.

```text
MIT License

Copyright (c) 2026 Roshan Zameer

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```
