# Shilpa

AI CAD agent by Wayam AI. It turns engineering requests into inspectable, editable,
validated CAD models (STEP / STL / GLB), following `Shilpa_Azure_Execution_Blueprint.docx`.

This repository runs **entirely on your machine**. The only cloud dependency is the
**Azure OpenAI** deployment used by the planner.

## What works today

| Blueprint item | Status |
|---|---|
| §8 Typed IR 1.0 (parameters with units, restricted expressions, semantic selectors, assertions) | `shilpa/contracts/` |
| §4.1 Deterministic build123d adapter: sketches, extrude, stepped-shaft revolve, holes and patterns, pockets, booleans, fillets, chamfers | `shilpa/adapters/build123d_adapter.py` |
| §19 Independent validation from the re-imported STEP: validity, solid count, bbox, volume, hole axes, STEP round trip, STL watertight, GLB scale | `shilpa/validators/geometry.py` |
| G1: 30 golden recipes across 6 families with analytic oracles | `evals/` |
| §9 Planner: intake parsing, clarification policy, plan building, bounded repair, conversational edits (Azure OpenAI structured outputs) | `shilpa/agent/` |
| §10 Job state machine: CAS transitions, outbox, peek-lock queue with DLQ, leases, cancellation, single publication | `shilpa/jobs.py`, `shilpa/queue.py`, `shilpa/coordinator.py`, `shilpa/workers/` |
| §15 REST API `/v1` with SSE progress, idempotency keys, 409 on stale edits | `shilpa/api/` |
| §14 Studio: projects, conversation with clarification, 3D viewer, parameters, validation, versions, export | `apps/studio/` |

## Local stand-ins for Azure services

| Azure (blueprint) | Local now | How it swaps |
|---|---|---|
| PostgreSQL Flexible Server | SQLite (`var/shilpa.db`) via SQLAlchemy | set `DATABASE_URL` |
| Service Bus | DB-backed queue with peek-lock, delivery count, dead letters | `shilpa/queue.py` interface |
| Blob Storage | `var/blobs/` with the blueprint key layout | `shilpa/storage.py` interface |
| Container Apps Jobs | CAD worker process + credential-free geometry subprocess | container image |
| Entra ID | dev bearer tokens `dev:<email>` for seeded users | JWT validation in `shilpa/api/auth.py` |
| **Azure OpenAI** | **Azure OpenAI** | — |

## Setup

Requires Python 3.12 (managed by `uv`) and Node 20+.

```powershell
uv sync                         # Python deps, including build123d / Open CASCADE
cd apps/studio; npm install; cd ../..
copy .env.example .env          # then fill in AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_DEPLOYMENT
```

Use a deployment that supports structured outputs (`json_schema` with `strict: true`).
Leave `AZURE_OPENAI_API_KEY` empty to authenticate with Entra ID (`az login`).

## Run

```powershell
uv run python evals/make_corpus.py      # regenerate the 30 golden fixtures (already committed)
uv run python evals/run_corpus.py       # gate G1: build + validate all 30, writes evals/out/
uv run pytest                           # contract, geometry and workflow tests
uv run python -m shilpa.dev             # API :8000 + coordinator + CAD worker + studio :5173
```

Open http://localhost:5173. Without Azure OpenAI configured you can still run the golden
examples and do parameter edits, version restore and exports; language input and
conversational edits need the planner.

Dev users (switch in the top bar): `dev@wayam.local` (org admin), `viewer@wayam.local`
(read-only), `other@example.com` (a second tenant, for isolation checks).

## Engineering boundaries

A generated model is **geometry-validated**, not reviewed for engineering release. A valid
solid does not establish strength, fit, material suitability or safe manufacture. Comparison
tolerances (0.01 mm, 1e-5 relative volume) are software tolerances, not manufacturing ones.
The 30 golden recipes are synthetic starters; the mechanical SME must replace them with
approved reference parts (backlog B002).
