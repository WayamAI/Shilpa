# Shilpa on Azure: hosting plan

Status: plan, 2026-11-02. It builds on `Shilpa_Azure_Execution_Blueprint.docx` (§5 architecture, §6 regions, §17 security, §18 operations, §21 cost) and records what the code needs before it can run there. Items marked **[Decide]** need an owner's decision. Items marked **[Verify]** need a check against the chosen subscription and region before any spend.

## 1. Target architecture

| Layer | Azure service | Starting size | Code today | Gap |
|---|---|---|---|---|
| Studio (Next.js 16) | Container Apps, external ingress | 0.5 vCPU / 1 GiB, min 1 | `apps/web`, `next start` | Container image (standalone output). `/v1` proxy to the API over internal ingress. |
| API (FastAPI) | Container Apps, internal ingress | 1 vCPU / 2 GiB, min 1 warm | `shilpa/api` | Image, Entra auth, health and readiness probes |
| Coordinator / outbox dispatcher | Container Apps | 0.5 vCPU / 1 GiB, 1 replica | `shilpa/coordinator.py` | Image (same package), Service Bus send |
| CAD workers | Container Apps **Jobs**, event-driven by Service Bus | 2 vCPU / 4 GiB per execution | `shilpa/workers/cad.py` + geometry subprocess | Image with build123d/OCC (+ FreeCAD optional), KEDA Service Bus scaler, non-root |
| Database | PostgreSQL Flexible Server | Burstable B2s for dev/pilot | SQLite by default; `DATABASE_URL` honoured | psycopg driver, migration discipline, connection pooling |
| Artifacts | Blob Storage (StorageV2, hot) | n/a | `LocalBlobStore` (filesystem) | `AzureBlobStore` behind the same interface; workers stage locally, then upload |
| Queues | Service Bus Standard (cad, planning, dead-letter) | n/a | DB-backed peek-lock queue | Service Bus backend behind `shilpa/queue.py` |
| Planner LLM | **Azure OpenAI in Foundry** | Deployments per stage | Azure **or Ollama Cloud** (`beam`) | Production must not use Ollama (below) |
| LLM result cache | PostgreSQL table | n/a | sqlite file in `var/` | Move to the database so replicas share it |
| Thumbnails | Blob (THUMB artifact) | n/a | Rendered on publish, served by the API | Done. Backfill once per environment. |
| Identity | Entra ID (workforce); External ID only for self-service | n/a | `dev:<email>` tokens | JWT validation (issuer, audience, signature, expiry, org); MSAL in the studio |
| Secrets | Key Vault + managed identities | n/a | `.env` | Per-service user-assigned identities; no keys in env |
| Images | Azure Container Registry | Basic or Standard | none | Build, scan, SBOM, pin by digest |
| Telemetry | Application Insights + Log Analytics | n/a | Python logging | OpenTelemetry exporter; no prompts, CAD files or tokens in logs |
| Edge | Managed ingress (POC) → Front Door + WAF (external pilot) | n/a | n/a | Custom domain, TLS |
| IaC / CD | Bicep + Azure DevOps (workload identity federation) | n/a | none | Modules, per-environment parameters, pipeline |

AKS, Redis and a second orchestration engine are deliberately out (blueprint §5).

## 2. Decisions that change the code now

1. **No non-Azure model host in hosted environments.** The blueprint (§6) forbids sending engineering files to a non-Azure model host. The dev `.env` uses Ollama Cloud (`beam`), and drawings go to `kimi-k3`.
   - Hosted environments set `SHILPA_ENV=staging|production`. The settings layer must refuse to start with `SHILPA_LLM_PROVIDER=ollama` there.
   - Ollama stays a local developer option only.
   - **[Decide]** which Azure OpenAI deployments to use per stage. The language eval already shows gpt-5.5 at 59/60 and gpt-5-mini at 42/60 for planning.
   - Candidate split: a small model for intake, the strong model for plan and repair. This needs a run of `evals/run_language.py --compare`.
2. **Region: Central India** if every required service and model is available there. **[Verify]** Azure OpenAI model availability and deployment type (regional vs global processing), Container Apps Jobs, PostgreSQL Flexible Server SKUs and quotas. If a model is only available globally, record the data-processing implication and get sign-off.
3. **Storage access path.** Browsers never get storage URLs in the POC. Uploads and downloads go through the authenticated API (already true). Public network access to the storage account is off, with private endpoints when the pilot is external.
4. **Static thumbnails.** Catalog thumbnails ship inside the web image. Model thumbnails are THUMB artifacts in Blob, served through the API. The per-machine `public/thumbs/models` script goes away after backfill.
5. **One image for API, coordinator and workers**, with different commands. The geometry subprocess runs as a non-root user without managed identity or database credentials (blueprint §17).

## 3. Environments

| | dev | staging | production |
|---|---|---|---|
| Resource group | `rg-shilpa-dev` | `rg-shilpa-stg` | `rg-shilpa-prod` |
| Data | synthetic and golden corpus | anonymised pilot samples | customer |
| PostgreSQL | Burstable, no HA | Burstable | General Purpose; zone-redundant HA **[Decide]** |
| Networking | public ingress + Entra auth | as prod | VNet, private endpoints (Postgres, Blob, Key Vault, OpenAI), Service Bus Premium if private **[Decide]**, Front Door + WAF |
| Planner | Azure OpenAI (Ollama allowed only on laptops) | Azure OpenAI | Azure OpenAI |
| Promotion | on merge to `main` | same image digests as dev, after smoke tests | same digests, manual approval |

## 4. Build order (each step shippable)

| # | Work | Owner | Exit check |
|---|---|---|---|
| 0 | Commit the in-flight work: THUMB artifacts, planner cost controls | main session | Python suite green with `SHILPA_LLM=off` |
| 1 | **Containers**: web (Next standalone), backend image (api, coordinator, worker), `.dockerignore`, `docker-compose.yml` for local parity (Postgres, Azurite, Service Bus emulator) | agent | `docker compose up` serves the studio; golden part builds end to end |
| 2 | **Cloud adapters**: Postgres driver and pooling, `AzureBlobStore`, Service Bus queue backend, both selected by settings with the local ones as default | agent | Unit tests with Azurite and emulator; existing tests unchanged on defaults |
| 3 | **Hosting guards and identity**: `SHILPA_ENV`, no-Ollama guard, Entra JWT validation, LLM cache in Postgres, `/v1/health/live` and `/v1/health/ready`, structured logs with redaction, OpenTelemetry hook | agent | Tests for each guard; dev mode unchanged |
| 4 | **Infrastructure**: Bicep modules (network, ACR, Key Vault, identities and roles, Postgres, Storage, Service Bus, Log Analytics + App Insights, Container Apps env, apps, jobs, Azure OpenAI account and deployments, budgets) and per-environment parameters | agent | `az bicep build` and `what-if` clean against a dev subscription **[Verify]** |
| 5 | **Pipeline**: Azure DevOps YAML: lint, typecheck, pytest, golden corpus, e2e, secret scan, image build, SBOM, vulnerability scan, push by digest, deploy dev, smoke, promote | agent | Dry-run on a branch |
| 6 | Studio sign-in with MSAL (Entra) replacing dev identities in hosted environments | next | e2e against staging |
| 7 | Compose API (interpret/apply), import pipeline, needs-you inbox | product | spec P0 to P2 exit criteria |

Steps 1 to 5 can run in parallel; 6 depends on 3 and 4.

## 5. Operations

- **Health**: liveness (process up) and readiness (DB reachable, queue reachable, storage reachable; planner status reported but not required).
- **Alerts**: queue age, dead letters, job failure rate, CAD validity rate, API 5xx, p95 latency, budget at 50/80/100%.
- **Targets** (blueprint §18, engineering not contractual): API p95 < 1 s; simple CAD p95 < 60 s worker time; text-to-CAD p95 < 3 min; pilot 99.5% API availability, RPO ≤ 24 h, RTO ≤ 8 h.
- **Backups**: PostgreSQL PITR (7 to 35 days), Blob soft delete and versioning, a restore drill before the external pilot.
- **Cost**: per-job cost is now recorded (`budget.calls[*].cost_usd`) once prices are set (`SHILPA_MODEL_PRICES`). Report cost per successful job. Azure budgets alert; admission control in the app stops spend.

## 6. Open questions

1. Data residency: is Central India mandatory, and is a global Azure OpenAI deployment acceptable? **[Decide]**
2. Which Azure OpenAI models and quotas are available on the subscription? **[Verify]**
3. Is the pilot internal-only (managed ingress plus Entra is enough) or external (Front Door, WAF and private networking from day one)? **[Decide]**
4. Is the FreeCAD adapter needed in hosted environments? It adds about 1 GB to the worker image. **[Decide]**
5. Azure DevOps or GitHub Actions? The blueprint says Azure DevOps; the repo has no remote CI yet. **[Decide]**
