# Provenance

> Many minds. One mission. Every contribution counted.

A verified, access-controlled collaborative research platform connecting sponsors, domain experts, and students with transparent attribution, tamper-evident ledgers, and fair reward distribution.

---

## Run Instructions

### Prerequisites
- Python 3.11+

### Windows (PowerShell)
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python demo_reset.py
python smoke.py
uvicorn app.main:app --reload
```

### macOS / Linux
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python demo_reset.py
python smoke.py
uvicorn app.main:app --reload
```

Open `http://127.0.0.1:8000` in your browser.

---

## AI Tools Used
- **Google Antigravity**: Used for architecture design, data modeling, backend/frontend implementation, smoke testing, and documentation generation.

---

## What is Mocked
In this prototype, the following components are simulated for hackathon demo purposes:
- **Authentication & KYC**: Simulated via topbar persona switcher and `persona_id` cookie. Production would use a real identity provider (e.g., OAuth2 / OIDC / DigiLocker / Aadhaar KYC).
- **Payment & Escrow**: Simulated internal escrow states. Production would use an authorized escrow banking partner or payment gateway (e.g., Razorpay Escrow / Cashfree).
- **Signatures**: Digital charter agreements and contributions are recorded with hashes. Production would use per-user Ed25519 cryptographic key pairs or PKI certificates.
- **AI-Content & Similarity Detector**: Fast shingle/token similarity comparison. Production would integrate vetted external AI text and code classifiers.
- **Ledger Anchoring**: Local SHA-256 append-only hash chain. Production would periodically anchor Merkle roots into a public blockchain (e.g., Polygon or Ethereum).
