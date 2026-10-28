# Provenance (CritX)

> **Many minds. One mission. Every contribution counted.**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python: 3.11+](https://img.shields.io/badge/Python-3.11%2B-blue.svg)](https://www.python.org/)
[![Framework: FastAPI](https://img.shields.io/badge/Framework-FastAPI-009688.svg)](https://fastapi.tiangolo.com/)
[![Database: SQLite](https://img.shields.io/badge/Database-SQLite-003B57.svg)](https://www.sqlite.org/)

**Provenance** is an open-source, verified, access-controlled collaborative research platform connecting research sponsors, domain experts, and student researchers. It features transparent attribution, zero-trust server-side access control, an append-only cryptographic ledger, invisible leak steganography, a mathematical rupee split engine, and scoped agentic AI workflows.

---

## Key Highlights

- **Cryptographic Append-Only Ledger (`app/ledger.py`)**: All state-changing events (projects, charters, milestones, contributions, payouts) form a SHA-256 hash chain with atomic `BEGIN IMMEDIATE` transactions and automated tamper detection.
- **Living Project Charters & Explicit Consent (`app/access.py`)**: Cryptographically versioned terms. When a charter changes, members enter a `reaccept_required` state, preventing scope creep and unconsented terms.
- **Zero-Trust Access Control**: Enforced exclusively on the server side (`can_view()`). Even platform administrators are prevented from viewing confidential research briefs (least-privilege).
- **Exact Rupee Split Engine (`app/splits.py`)**: Pure fraction-based math (`fractions.Fraction`) using Hare-Niemeyer largest-remainder integer rounding. Eliminates floating-point rounding errors across platform, expert, and student merit shares.
- **Invisible Steganographic Watermarking & Leak Tracer (`app/integrity/watermark.py`)**: Zero-width unicode markers (`U+2060`, `U+200B`, `U+200C`) with bitwise checksums identify leakers of confidential materials via majority-vote decoding.
- **Plagiarism & Undisclosed AI Catching (`app/integrity/similarity.py`)**: 3-word shingle Jaccard and token Cosine similarity algorithms flag unauthorized copies and uncredited AI text for human review.
- **Scoped AI Gateway & Firewall (`app/ai/gateway.py`)**: Agents require a named human supervisor and are scoped to single projects. Built-in defenses block prompt injections, sanitize PII, and quarantine unauthorized tool requests.
- **Interactive Story Mode (`/story`)**: An end-to-end 12-step presenter orchestrator with 1-click execution across real backend services and sandbox twist cases.

---

## Getting Started

### Prerequisites
- Python 3.11 or higher
- Git

### Installation

#### Windows (PowerShell)
```powershell
# Clone the repository
git clone https://github.com/<your-username>/CritX.git
cd CritX

# Create and activate virtual environment
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# Install dependencies
pip install -r requirements.txt

# Reset and seed database
python demo_reset.py

# Run comprehensive verification suite
python smoke.py

# Launch development server
uvicorn app.main:app --reload --port 8000
```

#### macOS / Linux
```bash
# Clone the repository
git clone https://github.com/<your-username>/CritX.git
cd CritX

# Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Reset and seed database
python3 demo_reset.py

# Run comprehensive verification suite
python3 smoke.py

# Launch development server
uvicorn app.main:app --reload --port 8000
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000) in your web browser.

---

## Web Navigation & Quick Links

- **Home / Dashboard**: [http://127.0.0.1:8000/](http://127.0.0.1:8000/)
- **Story Mode Walkthrough**: [http://127.0.0.1:8000/story](http://127.0.0.1:8000/story)
- **Projects & Charters**: [http://127.0.0.1:8000/projects](http://127.0.0.1:8000/projects)
- **Integrity Center & Leak Tracer**: [http://127.0.0.1:8000/integrity](http://127.0.0.1:8000/integrity)
- **Persona Switcher (9 Seeded Roles)**: [http://127.0.0.1:8000/login](http://127.0.0.1:8000/login)

---

## AI Tools Declaration
In accordance with open-source hackathon disclosure requirements:
- **Google Antigravity**: Used for architecture design, schema modeling, backend/frontend implementation, smoke testing, and documentation generation. Detailed prompts and module trajectories are cataloged in `AI_USAGE.md`.

---

## What is Mocked
In this prototype, the following components are simulated for hackathon demo purposes:
- **Authentication & KYC**: Simulated via topbar persona switcher and `persona_id` cookie. Production would use OAuth2/OIDC, DigiLocker, or institutional SSO.
- **Payment & Escrow**: Simulated internal escrow states. Production would integrate with banking escrow APIs (e.g., Razorpay Escrow / Cashfree).
- **Cryptographic Signatures**: Agreements and milestones are recorded with canonical JSON SHA-256 hashes. Production would use per-user Ed25519 key pairs.
- **Ledger Anchoring**: Local SQLite SHA-256 append-only hash chain. Production would anchor periodic Merkle roots to a public blockchain (e.g., Polygon, Ethereum).

---

## Contributing

Contributions are welcome! Please follow these steps:

1. Fork the Project
2. Create your Feature Branch (`git checkout -b feature/AmazingFeature`)
3. Ensure all tests pass (`python smoke.py`)
4. Commit your Changes (`git commit -m 'Add some AmazingFeature'`)
5. Push to the Branch (`git push origin feature/AmazingFeature`)
6. Open a Pull Request

---

## License & Copyright

Distributed under the **MIT License**. See `LICENSE` for more information.

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
