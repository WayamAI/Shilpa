# Infrastructure (Bicep) and pipeline

Build steps 4 and 5 of `hosting-plan.md`. Nothing here has been deployed: it was validated offline with `az bicep build` and `az bicep lint` only. Items marked **[Verify]** need a check against your subscription and region; **[Decide]** needs an owner's call; **[Assumption]** records something I inferred from the code.

## Layout

```
infra/
  main.bicep                 resource-group scope, composes everything
  bicepconfig.json           linter rules (use-recent-api-versions on, secret rules as errors)
  modules/
    monitoring.bicep         Log Analytics + Application Insights (workspace-based)
    registry.bicep           ACR (admin user off)
    identities.bicep         four user-assigned managed identities: web, api, coordinator, worker
    keyvault.bicep           Key Vault, RBAC mode, soft delete, purge protection (param)
    storage.bicep            StorageV2, no shared keys, soft delete + versioning, `artifacts` container
    servicebus.bicep         namespace (Entra-only) + queues `cad`, `plan` with DLQ settings
    postgres.bicep           Flexible Server, Entra-only auth, PITR, database `shilpa`
    openai.bicep             Azure OpenAI account + deployments from a parameter
    roles.bicep              every role assignment (the matrix below)
    containerenv.bicep       Container Apps environment (workload profiles, Consumption)
    apps.bicep               web, api, coordinator apps and the CAD worker Job
    budget.bicep             monthly budget, alerts at 50/80/100% actual
    network.bicep            optional: VNet, delegated subnet, private DNS zones
    privateendpoint.bicep    optional: one private endpoint + DNS zone group
    frontdoor.bicep          optional: Front Door + WAF
  params/{dev,staging,prod}.bicepparam
pipelines/azure-pipelines.yml
```

### Scope decision

`main.bicep` is **resource-group scope**. The deployment identity needs Contributor plus the right to create role assignments (Role Based Access Control Administrator or User Access Administrator) on that one resource group, never on the subscription. Subscription scope would only be needed to create resource groups or subscription-wide budgets, and the blueprint wants one resource group per environment anyway (section 18). An operator creates `rg-shilpa-{dev,stg,prod}` once.

### API versions

Resource API versions were taken from the Bicep type definitions bundled with the installed CLI (Bicep 0.48.1): the `use-recent-api-versions` linter rule lists the acceptable versions per type, and every module lints clean against it. I could not browse Microsoft's reference pages from this environment, so this is the authoritative-but-indirect source. Re-run `az bicep lint` periodically.

| Type | Version |
|---|---|
| Microsoft.OperationalInsights/workspaces | 2025-02-01 |
| Microsoft.Insights/components | 2020-02-02 |
| Microsoft.ContainerRegistry/registries | 2025-04-01 |
| Microsoft.KeyVault/vaults | 2026-02-01 |
| Microsoft.ManagedIdentity/userAssignedIdentities | 2024-11-30 |
| Microsoft.Storage/storageAccounts (+ blobServices, containers) | 2025-01-01 |
| Microsoft.ServiceBus/namespaces (+ queues) | 2026-01-01 |
| Microsoft.DBforPostgreSQL/flexibleServers (+ administrators, databases, firewallRules) | 2025-08-01 |
| Microsoft.CognitiveServices/accounts (+ deployments) | 2025-06-01 |
| Microsoft.App/managedEnvironments, containerApps, jobs | 2025-07-01 |
| Microsoft.Consumption/budgets | 2026-06-01 |
| Microsoft.Authorization/roleAssignments | 2022-04-01 |
| Microsoft.Network (virtualNetworks, privateEndpoints) | 2025-05-01 |
| Microsoft.Network/privateDnsZones (+ links) | 2024-06-01 |
| Microsoft.Cdn/profiles (+ endpoints, origins, routes, securityPolicies) | 2025-06-01 |
| Microsoft.Network/FrontDoorWebApplicationFirewallPolicies | 2025-03-01 |

Role definition GUIDs were read from `az role definition list` (built-in definitions) rather than typed from memory.

## Deploy dev from a laptop

Prerequisites: Azure CLI with Bicep (`az bicep version`), Owner (or Contributor + User Access Administrator) on a dev resource group, and an Entra group whose object id will administer PostgreSQL.

```bash
az login
az account set --subscription <dev-subscription-id>

# 1. Edit infra/params/dev.bicepparam: postgresAdminObjectId, postgresAdminName, entraAudience,
#    budgetContactEmails, and the openAiDeployments / modelDeployments examples [Verify].
# 2. Resource group (once)
az group create --name rg-shilpa-dev --location centralindia

# 3. Preview, then deploy. With no images set, placeholder containers are deployed so the registry exists first.
az deployment group what-if --resource-group rg-shilpa-dev \
  --template-file infra/main.bicep --parameters infra/params/dev.bicepparam
az deployment group create  --resource-group rg-shilpa-dev --name shilpa-bootstrap \
  --template-file infra/main.bicep --parameters infra/params/dev.bicepparam \
  --query properties.outputs

# 4. Push images (names from the outputs), then redeploy by digest. Image references reach the param file through
#    environment variables because a .bicepparam file cannot be combined with inline overrides.
ACR=$(az deployment group show -g rg-shilpa-dev -n shilpa-bootstrap --query properties.outputs.acrName.value -o tsv)
az acr login --name $ACR
docker build -f apps/web/Dockerfile -t $ACR.azurecr.io/shilpa-web:dev apps/web
docker build -f Dockerfile.backend  -t $ACR.azurecr.io/shilpa-backend:dev .
docker push $ACR.azurecr.io/shilpa-web:dev && docker push $ACR.azurecr.io/shilpa-backend:dev
export SHILPA_WEB_IMAGE=$ACR.azurecr.io/shilpa-web@$(az acr repository show -n $ACR --image shilpa-web:dev --query digest -o tsv)
export SHILPA_BACKEND_IMAGE=$ACR.azurecr.io/shilpa-backend@$(az acr repository show -n $ACR --image shilpa-backend:dev --query digest -o tsv)
az deployment group create -g rg-shilpa-dev --name shilpa-dev \
  --template-file infra/main.bicep --parameters infra/params/dev.bicepparam
```

Validate without Azure at any time (this is what the pipeline's first stage runs):

```bash
az bicep build --file infra/main.bicep --stdout > /dev/null
az bicep lint  --file infra/main.bicep
for p in infra/params/*.bicepparam; do az bicep build-params --file "$p" --stdout > /dev/null; done
```

### Required follow-up steps after the first deployment

1. **PostgreSQL roles.** Bicep cannot run SQL. As a member of the admin group, connect to database `shilpa` with an Entra token and create one role per identity. The role name is the identity's name (`identityNames` output, e.g. `id-shilpa-dev-api`):

   ```sql
   SELECT * FROM pgaadauth_create_principal('id-shilpa-dev-api', false, false);
   SELECT * FROM pgaadauth_create_principal('id-shilpa-dev-coordinator', false, false);
   SELECT * FROM pgaadauth_create_principal('id-shilpa-dev-worker', false, false);
   -- after the schema exists:
   GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO "id-shilpa-dev-api", "id-shilpa-dev-coordinator", "id-shilpa-dev-worker";
   GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO "id-shilpa-dev-api", "id-shilpa-dev-coordinator", "id-shilpa-dev-worker";
   ```
   **[Decide]** who runs migrations (the admin identity out of band is recommended; the app roles above have DML only) and whether the worker's grants should be narrowed table by table. Run `init_db`/migrations once as the admin before the apps start, or the apps will crash-loop until the schema exists.
2. **Entra app registration** for the API (audience, scope or role) and the values for `entraAudience` / `entraRequiredScope`. The settings layer refuses to start without them.
3. **Backfill** thumbnails once per environment (hosting-plan section 1).
4. With private networking, Postgres, Blob, Key Vault, OpenAI and (if Premium) Service Bus have public access off, so step 1 must run from inside the VNet (jump host, Bastion, or a temporary firewall rule). **[Decide]** the operator access path.

## Parameters

| Parameter | Meaning | Default |
|---|---|---|
| `envName` | `dev` / `staging` / `prod`; short form (`dev`/`stg`/`prd`) goes into resource names; `prod` maps to `SHILPA_ENV=production` | required |
| `location` | Region for everything except OpenAI. **[Verify]** every service is offered | `centralindia` |
| `openAiLocation` | Region of the OpenAI account when the model is not offered in `location`. Moving engineering data to another region needs sign-off | `location` |
| `webImage`, `backendImage` | Full image references with digest. Empty deploys a public placeholder (bootstrap). Set in param files through `readEnvironmentVariable('SHILPA_WEB_IMAGE'/'SHILPA_BACKEND_IMAGE')` | empty |
| `authMode`, `entraAudience`, `entraRequiredScope`, `entraRequiredRole` | `SHILPA_AUTH_MODE` and `SHILPA_ENTRA_*` for the API. Tenant defaults to the deploying tenant | `entra` |
| `openAiDeployments` | Array of `{ name, model: { format, name, version }, sku: { name, capacity } }`. Created one at a time. Examples only; **[Verify]** | `[]` |
| `modelDeployments` | Stage to deployment name: `default` (`AZURE_OPENAI_DEPLOYMENT`), `intake`, `plan`, `repair`, `edit` (`SHILPA_MODEL_*`) | `{}` |
| `openAiApiVersion` | `AZURE_OPENAI_API_VERSION` | `2024-10-21` (same as `settings.py`) |
| `maxDeliveryCount`, `lockDurationSeconds` | Written to the queues and to `SHILPA_MAX_DELIVERY_COUNT` / `SHILPA_LOCK_DURATION_S`, so broker and code agree | 5 / 60 |
| `workerTimeoutSeconds` | `SHILPA_WORKER_TIMEOUT_S`; the Job `replicaTimeout` is this plus 300 s | 300 |
| `*Size`, `webMinReplicas`, `apiMinReplicas`, `workerMaxExecutions` | Container sizing; benchmark starting points from blueprint section 5 | see `main.bicep` |
| `postgresSkuTier/Name`, `postgresStorageGB`, `postgresBackupRetentionDays` (7-35), `postgresGeoRedundantBackup`, `postgresHighAvailability` | Database sizing and resilience. HA is not available on Burstable | Burstable `Standard_B2s`, 32 GB, 7 days |
| `postgresAdminObjectId/Name/PrincipalType` | Entra admin of the server (a group is recommended) | required |
| `postgresAllowAzureServices` | Public Postgres only: the 0.0.0.0 firewall rule so Container Apps can connect | `true` |
| `storageSku`, `blobSoftDeleteDays` | Replication and soft delete window (versioning is always on) | `Standard_LRS`, 14 |
| `serviceBusSku` | `Standard`, or `Premium` (needed for a private endpoint) | `Standard` |
| `acrSku` | `Premium` is needed for a private endpoint | `Standard` |
| `keyVaultPurgeProtection` | Irreversible once on; dev sets false | `true` |
| `logRetentionDays`, `logDailyQuotaGb` | Log Analytics retention and ingestion cap (-1 = none) | 30 / -1 |
| `enablePrivateNetworking` | Creates the VNet and private DNS, turns off public access on Postgres, Blob, Key Vault, OpenAI (and Service Bus/ACR when Premium), adds private endpoints, puts the Container Apps environment in the VNet | `false` |
| `enableFrontDoor`, `frontDoorSku` | Front Door + WAF in front of the web app (no custom domain yet) | `false` |
| `zoneRedundantEnvironment` | Zone-redundant Container Apps environment; **[Verify]** needs VNet and a zone-capable region | `false` |
| `budgetAmount`, `budgetContactEmails` | Monthly budget in the billing currency; alerts at 50/80/100% actual | required |

## Runtime wiring

| Component | Resource | Ingress | Command | Notes |
|---|---|---|---|---|
| web | Container App | external | image default (`node server.js`) | `SHILPA_API_ORIGIN=https://<api-internal-fqdn>`; probes on `/login` |
| api | Container App | internal | image default (uvicorn :8000) | probes on `/v1/health` (change to live/ready when they exist) |
| coordinator | Container App | none | `python -m shilpa.coordinator` | fixed at 1 replica |
| CAD worker | Container Apps **Job**, event trigger | none | `python -m shilpa.workers.cad --once` | KEDA `azure-servicebus` rule on queue `cad`, `messageCount=1`, authenticated with the worker identity, 0 to `workerMaxExecutions` executions, `replicaRetryLimit` 0 (redelivery belongs to Service Bus) |

Environment variables set by Bicep use the names in `shilpa/settings.py` (`DATABASE_AUTH=entra`, `SHILPA_BLOB_BACKEND=azure`, `SHILPA_BLOB_ACCOUNT_URL`, `SHILPA_BLOB_CONTAINER`, `SHILPA_QUEUE_BACKEND=servicebus`, `SHILPA_SERVICEBUS_NAMESPACE`, `SHILPA_ENTRA_*`, `AZURE_OPENAI_*`, `SHILPA_MODEL_*`). `DATABASE_URL` is `postgresql+psycopg://<identity-name>@<host>:5432/shilpa?sslmode=require` with no password. `AZURE_CLIENT_ID` selects the user-assigned identity for `DefaultAzureCredential`. No secrets are passed anywhere; there are no Container Apps secrets.

The worker gets `SHILPA_LLM=off` and no OpenAI endpoint, so a compromised worker has no model path even if the code asked for one.

### Queue semantics

`servicebus.bicep` mirrors `shilpa/queue.py`: `maxDeliveryCount` = `SHILPA_MAX_DELIVERY_COUNT`, `lockDuration` = `SHILPA_LOCK_DURATION_S` (workers renew), duplicate detection on `message_id` (10 min window), dead-lettering on expiry, 1 day TTL, local (key) auth disabled. The user asked for a `planning` queue; the code's name is `plan` (`QUEUES = ("plan", "cad")`), so the queues are `cad` and `plan`.

## Role-assignment matrix

All assignments are made in `modules/roles.bicep`, to user-assigned identities, at the narrowest scope that exists.

| Role | web | api | coordinator | worker | Scope |
|---|---|---|---|---|---|
| AcrPull | yes | yes | yes | yes | registry |
| Key Vault Secrets User | | yes | yes | | vault |
| Storage Blob Data Contributor | | yes | | yes | `artifacts` container only |
| Service Bus Data Sender | | | yes | | queues `cad` and `plan` |
| Service Bus Data Receiver | | | yes | yes | coordinator: `plan`; worker: `cad` |
| Cognitive Services OpenAI User | | yes | yes | | OpenAI account |
| PostgreSQL role (SQL, post-deploy) | | yes | yes | yes | database `shilpa` |

Why the worker looks the way it does (checked against `shilpa/workers/cad.py`): it reads and updates job state and artifact rows in the database, stages and publishes artifacts and thumbnails in Blob, and takes work from `cad`. When a repair is needed it writes an outbox row (`outbox=("plan", ...)`) in the database; the coordinator publishes it and runs the planner. So the worker needs no OpenAI access, no Key Vault access and no Service Bus send right. The web app only pulls its image.

Assumptions in the matrix: the coordinator does not touch Blob (it plans and dispatches); the API does not send to Service Bus (it writes outbox rows) and has no Service Bus role, so a readiness probe cannot check the queue with the API identity. **[Decide]** whether the API should get Data Receiver on one queue to peek for readiness, or readiness should report outbox lag from the database instead. **[Verify]** the KEDA Service Bus scaler with managed identity: confirm that Data Receiver on the queue is enough for it to read the message count; some KEDA versions need a management-plane read (for example Azure Service Bus Data Owner or a custom role with `Microsoft.ServiceBus/namespaces/queues/read`). Test in dev before relying on scale-from-zero.

**Geometry subprocess.** `cad.py` starts it with a scrubbed environment, so `DATABASE_URL`, `AZURE_CLIENT_ID` and similar are not inherited. In Container Apps the managed-identity token endpoint is still reachable from the same container network namespace, so the environment scrub is not a hard boundary (blueprint section 17: a container alone is not one). The mitigation here is that the worker identity is narrow; stronger isolation would need a separate execution environment and is a **[Decide]**.

## Pipeline

`pipelines/azure-pipelines.yml`:

1. **validate**: pytest with `SHILPA_LLM=off` (ruff is skipped, there is no `[tool.ruff]` yet, a commented step is ready), web `tsc --noEmit` and eslint, Bicep build / build-params / lint, gitleaks.
2. **build**: docker build `apps/web/Dockerfile` and `Dockerfile.backend`, syft SBOM (SPDX), trivy scan (fails on fixable HIGH/CRITICAL), push to the dev ACR on `main` only, record digests as a build artifact. Tools are downloaded at pinned versions and verified against the release checksum file. **[Verify]** the pinned versions (`SYFT_VERSION`, `TRIVY_VERSION`, `GITLEAKS_VERSION`) are current and acceptable.
3. **deploy_dev**: what-if, deployment, smoke test of `/v1/health` through the public web URL.
4. **deploy_staging**, **deploy_prod**: `az acr import` copies each image by digest from the build registry into the environment's registry and fails if the digest differs, then what-if, deploy and smoke. Approvals are checks on the `shilpa-staging` / `shilpa-prod` environments.

Setup you must do in Azure DevOps (names are placeholders): service connections `sc-shilpa-dev`, `sc-shilpa-stg`, `sc-shilpa-prod` (Azure Resource Manager, workload identity federation, each scoped to its resource group); environments `shilpa-dev`, `shilpa-staging`, `shilpa-prod` with an approval on the last; variable groups `shilpa-dev` (`AZURE_RG`, `ACR_NAME`), `shilpa-staging` and `shilpa-prod` (`TARGET_AZURE_RG`, `TARGET_ACR_NAME`, `SOURCE_ACR_NAME`). The staging and prod identities need AcrPull on the dev registry (to import) and, for the dev identity, AcrPush. Registries are per environment (separate data and identities per blueprint section 18), which is why promotion imports rather than rebuilds. None of these values are secrets.

Not in the pipeline yet: golden corpus and Playwright e2e (hosting-plan step 5 lists them), database migration step, queue/DLQ/job-failure alert rules (hosting-plan section 5), and Application Insights availability tests.

## Estimated monthly baseline for dev (illustrative)

These are the blueprint's **illustrative planning assumptions** (section 21), not live Azure prices. Replace them from the Azure Pricing Calculator for the chosen region, currency and SKUs before authorising spend.

| Line | Illustrative input (blueprint 21) | Result |
|---|---|---|
| Fixed platform allowance (runtime, database, queue, artifacts, registry, monitoring, secrets, networking/backup reserve) | USD 220 per month | USD 220 |
| CAD worker compute | 1,000 requests x 1.2 attempts x 2 min = 40 h at USD 0.15 per worker hour | USD 6 |
| Planner tokens | 1,200 attempts x (12,000 in at USD 2 + 2,000 out at USD 8 per million) | USD 48 |
| Subtotal | | USD 274 |
| Contingency | 20 percent | USD 328.8 |
| In INR | at the illustrative 90 per USD | about INR 29,600 |

This is my arithmetic over the blueprint's inputs, for the CPU and planner part only. The blueprint's full figure (about INR 45,025, authoritative in the workbook) also includes visual/GPU requests, which this infrastructure does not provision. Dev running with the minimum replicas above (web and API warm, coordinator always on, Burstable Postgres, Standard Service Bus) should sit near the fixed allowance; real numbers depend on the region and SKUs. Private networking, Premium Service Bus, Premium ACR, Front Door Premium, zone-redundant Postgres and commercial CAD licences are excluded and can move production materially above this. The dev budget in `dev.bicepparam` (150) is a placeholder chosen to alert, not an estimate, and is below the blueprint's illustrative total: **[Decide]** the real ceiling.

## Open decisions and risks

1. Scope of the deployment identity (RG-scoped Contributor + role-assignment right) and who owns the service connections.
2. Azure OpenAI: models, versions, deployment type (regional vs global processing), capacity, region. The param files hold examples only.
3. Auth: Entra app registration and the required scope or role.
4. Database: who runs migrations, per-table grants for the worker, HA mode and geo-redundant backup for prod.
5. Private networking: whether the pilot is external (VNet, private endpoints, Premium Service Bus/ACR, Front Door Premium) and how operators reach private data services.
6. Front Door: the origin is the public web FQDN, and nothing yet stops callers from bypassing Front Door. Options: private-link origin with an internal-only Container Apps environment, or validate the `X-Azure-FDID` header in the app (output `frontDoorId` is available).
7. Worker as a Job: the Job runs `python -m shilpa.workers.cad --once` (one message, exit 0). It still calls `init_db()` on start, which is idempotent; an `init_db`-free path would be marginally faster.
8. KEDA permission check above, and the API readiness-to-queue question.
