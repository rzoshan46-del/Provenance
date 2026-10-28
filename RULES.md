# RULES.md - Provenance Engineering Rules

All contributors and AI agents working on this codebase must strictly observe these engineering rules:

- **(a)** Read SPEC.md and RULES.md before every task.
- **(b)** Do only the module requested, no unrelated refactors, no new dependencies without asking.
- **(c)** Enforce access control on the SERVER for every route, never only by hiding things in templates.
- **(d)** Use the new Starlette TemplateResponse(request, name, context) signature.
- **(e)** All SQL is parameterised. No f-string or string concatenation SQL queries.
- **(f)** From S2 onward every state-changing action calls ledger.append().
- **(g)** From S4 onward every AI call goes through gateway.call().
- **(h)** After any change run python smoke.py and show its output, and never say "done" unless it passes.
- **(i)** Anything mocked is labelled "MOCKED: production would use X" in code comments and in the UI.
- **(j)** Synthetic data only. No real personal data or real payment details.
- **(k)** Append a line to AI_USAGE.md describing what you generated.
- **(n)** Money is integer rupees; all splitting goes through app/splits.py; escrow state changes go through escrow_transition only; never use floats for money.
- **(o)** Every model call goes through app/ai/gateway.py, and no other file imports httpx.
- **(p)** API keys come only from environment variables and are never printed, logged or committed.
- **(q)** All integrity logic lives in app/integrity; stored text is never modified; watermarks are applied only at output time.
- **(r)** Integrity checks recommend, a human reviewer decides; flagged work can never be auto-approved.

