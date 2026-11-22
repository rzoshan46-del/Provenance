# Security Policy

## Reporting a Vulnerability

If you discover a security issue, please email **security@critx.example** with a description and steps to reproduce. We will acknowledge receipt within 48 hours and aim to provide a fix or mitigation within 7 days.

**Do not** open a public GitHub issue for security vulnerabilities.

---

## Security Controls

| Control | Implementation |
|---------|---------------|
| **Signed session cookies** | Sessions are signed with `itsdangerous` via Starlette `SessionMiddleware`. In production, `SESSION_SECRET` must be set to a strong random value. |
| **CSRF protection** | All state-changing POST routes include CSRF validation. |
| **Role-based access control** | Enforced server-side on every route via `app/access.py`. Templates never gate access alone. |
| **Engagement model acknowledgements** | Members must separately acknowledge the engagement model (paid/unpaid) when accepting a charter. |
| **Conflict-of-interest checks** | Experts whose `conflict_orgs` includes the sponsor's institution are blocked from joining. |
| **No secrets in code** | API keys (`GEMINI_API_KEY`, `SESSION_SECRET`, OAuth credentials) come only from environment variables and are never logged or committed. |
| **Docs disabled in production** | OpenAPI/Swagger UI defaults to disabled when `APP_ENV=production`. |
| **Watermarked briefs** | Confidential briefs and contribution text are invisibly watermarked per viewer with zero-width characters encoding the viewer's user ID. Leaked text can be traced back to the viewer. |

---

## Known Limitations

| Limitation | Notes |
|------------|-------|
| **SQLite single-writer** | SQLite allows only one concurrent write transaction. Production should use Postgres or add a write queue. |
| **Demo mode bypasses auth** | When `AUTH_MODE=demo`, the persona switcher allows instant impersonation without credentials. This is disabled when `AUTH_MODE=google`. |
| **No rate limiting** | The prototype has no request rate limiting. Production should add middleware-level rate limiting. |
| **Mocked payment** | Escrow funding is simulated. Production would integrate a payment gateway with KYC verification. |
| **Mocked signatures** | Ledger entries are not cryptographically signed per-user. Production would use Ed25519 keys. |
| **Watermark robustness** | Zero-width character watermarks can be stripped by some tools. Production would use robust fingerprinting. |
