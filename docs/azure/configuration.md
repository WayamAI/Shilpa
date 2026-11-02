
## Hosting guards, identity, health and logging (hosting plan step 3)

| Variable | Default | Meaning |
|---|---|---|
| `SHILPA_ENV` | `local` | `local`, `dev`, `staging` or `production`. Anything but `local` is "hosted". |
| `SHILPA_AUTH_MODE` | `dev` | `dev` (tokens `dev:<email>`) or `entra`. `dev` is refused when hosted. |
| `SHILPA_LLM_PROVIDER` | `azure` | `ollama` is refused when hosted (no non-Azure model host for engineering data). |
| `SHILPA_ENTRA_TENANT_ID` | | Required with `entra`. Tokens must carry this `tid` and an issuer of this tenant (v1 or v2 format). |
| `SHILPA_ENTRA_AUDIENCE` | | Required with `entra`. Comma-separated accepted `aud` values (API app id URI and/or client id). |
| `SHILPA_ENTRA_REQUIRED_SCOPE` | | `scp` value a delegated token must carry. |
| `SHILPA_ENTRA_REQUIRED_ROLE` | | `roles` value an app token must carry. At least one of scope or role is required; either satisfies. |
| `SHILPA_ENTRA_AUTHORITY` | `https://login.microsoftonline.com` | Authority host (sovereign clouds). |
| `SHILPA_ENTRA_JWKS_URL` | derived | Override for the signing-key document. |
| `SHILPA_ENTRA_JWKS_TTL_S` | `3600` | Signing-key cache lifetime. An unknown `kid` forces one refresh (at most every 30 s). |
| `SHILPA_ENTRA_LEEWAY_S` | `60` | Clock skew allowed on `exp` and `nbf`. |
| `SHILPA_ENTRA_AUTO_PROVISION` | `off` | When on, a valid token for an unknown email creates the user and a membership in tenant `entra:<tid>`. When off, unknown users get 403. |
| `SHILPA_ENTRA_DEFAULT_ROLE` | `project_viewer` | Role given to auto-provisioned users. |
| `SHILPA_LOG_LEVEL` | `INFO` | Root log level when hosted. |
| `APPLICATIONINSIGHTS_CONNECTION_STRING` | | Enables Azure Monitor export. Needs the optional extra: `uv sync --extra telemetry`. Without the package it logs a warning and carries on. |

**Startup guard.** When `SHILPA_ENV` is not `local` the API refuses to start (exit with a `ConfigError` listing every problem, each naming its variable) if: the provider is `ollama`; the auth mode is `dev`; `DATABASE_URL` is unset or SQLite; with the planner on and provider `azure`, `AZURE_OPENAI_ENDPOINT` or `AZURE_OPENAI_DEPLOYMENT` is missing (set `SHILPA_LLM=off` to run without a planner); with `entra`, the tenant, audience or a required scope/role is missing. `local` allows everything.

**Identity mapping.** A token's email (`preferred_username`, then `upn`, then `email`) is matched to `users.email`, and the user's membership gives the Shilpa tenant and role. Tokens without an email, or from an unknown user with auto-provision off, get 403. Bad signature, issuer, audience, tenant, expiry or `nbf` give 401. Tenant is never taken from a request field.

**Health.** `GET /v1/health/live` returns 200 whenever the process serves requests and checks nothing. `GET /v1/health/ready` returns 200 only when the database, the queue backend and blob storage answer, else 503 with the failing check (exception class only). The planner status is included but not required. Backends can expose `ping()` (on `shilpa.queue` and on `shilpa.storage.blobs`) to define their own probe; `GET /v1/health` is unchanged. Probes are unauthenticated and are not access-logged.

**Logging.** Hosted environments write one JSON object per line to stdout (`ts`, `level`, `logger`, `message`, `env`, extra fields). A redacting filter on every handler masks bearer tokens, JWTs, SAS parameters (`sig`, `sv`, `se`, ...), `AccountKey=`/`SharedAccessSignature=`, and `key=value` secrets in messages and exceptions. Fields named `prompt`, `recipe`, `system`, `messages`, `body`, `content`, `input`, `output` or `data` are replaced by `<redacted:N>` (their size); fields named `authorization`, `token`, `password` and similar by `[REDACTED]`. Log ids and sizes, not bodies. Requests are logged as method, path (no query), status and duration. `local` keeps the plain developer logging.

**LLM result cache.** Now the `llm_cache` table in the application database (created on first use, shared by all replicas, SQLite or PostgreSQL). Same key, TTL (`SHILPA_LLM_CACHE_TTL_S`), size bound (`SHILPA_LLM_CACHE_MAX_ENTRIES`) and switch (`SHILPA_LLM_CACHE=off`) as before. The old `var/llm_cache.sqlite` file is ignored and can be deleted.

## Cloud adapters: PostgreSQL, Blob Storage, Service Bus (hosting plan step 2)

Every default is the local one, so nothing below is needed for development. Code: `shilpa/db.py`, `shilpa/storage.py`, `shilpa/queue.py`, `shilpa/queue_servicebus.py`; settings block `CloudSettings` (`shilpa.settings.cloud`).

### PostgreSQL

| Variable | Default | Meaning |
|---|---|---|
| `DATABASE_URL` | SQLite file in `var/` | `postgresql+psycopg://user@host:5432/db?sslmode=require`. `postgresql://` and `postgres://` are rewritten to the psycopg 3 driver. Azure requires `sslmode=require` (or stricter); it is not added for you. |
| `DATABASE_AUTH` | `password` | `entra`: ignore any password in the URL and use an Entra access token (scope `https://ossrdbms-aad.database.windows.net/.default`, via `DefaultAzureCredential`) as the password, fetched on every new connection. The URL user is the database role mapped to the managed identity (its name, not its client id). Set `AZURE_CLIENT_ID` to pick a user-assigned identity. |
| `DATABASE_ENTRA_SCOPE` | the scope above | Override for sovereign clouds. |
| `SHILPA_DB_POOL_SIZE` / `SHILPA_DB_MAX_OVERFLOW` | `5` / `5` | Connections kept / extra under load, per process. Size so `(api + coordinator + worker replicas) x (pool + overflow)` stays under the server's `max_connections`. |
| `SHILPA_DB_POOL_TIMEOUT_S` | `30` | Wait for a free pooled connection. |
| `SHILPA_DB_POOL_RECYCLE_S` | `1800` | Replace connections older than this; keep it under the Entra token lifetime (about 60 min). |
| `SHILPA_DB_CONNECT_TIMEOUT_S` | `10` | TCP/auth timeout for a new connection. |

PostgreSQL pools are pre-pinged. SQLite pragmas (WAL, foreign keys, busy timeout) apply only to SQLite. On PostgreSQL `init_db()` takes a session advisory lock so replicas starting together do not race on `CREATE TABLE`. The queue claims rows with `SELECT ... FOR UPDATE SKIP LOCKED` (concurrent receivers never block on or double-claim a row; the lock-token compare-and-swap stays as a second guard), and the outbox dispatcher claims its batch the same way, so several coordinators can run.

### Blob storage

| Variable | Default | Meaning |
|---|---|---|
| `SHILPA_BLOB_BACKEND` | `local` | `local` (files under `SHILPA_VAR_DIR/blobs`) or `azure`. |
| `SHILPA_BLOB_ACCOUNT_URL` | | `https://<account>.blob.core.windows.net`. Authentication is `DefaultAzureCredential` (managed identity); no account keys, no SAS. The identity needs **Storage Blob Data Contributor** on the container (API and worker). |
| `SHILPA_BLOB_CONTAINER` | `artifacts` | Container name; created by infrastructure. |
| `SHILPA_BLOB_CONNECTION_STRING` | | Azurite only (the container is created on first use). Do not set in Azure. |
| `SHILPA_WORKDIR` | system temp | Scratch root for worker builds and drawing ingestion on the Azure backend. Needs space for one job's output; ephemeral storage is enough. |

How publication works with the Azure store: the worker builds into a local scratch directory, uploads it to the staging prefix (`.../jobs/{job}/attempts/{n}/`) only when the geometry succeeded, copies the published files server-side into the version prefix, and only then commits the version and artifact rows in one database transaction. A crash leaves unreferenced blobs that nothing reads; staging and orphaned version prefixes should be removed by a lifecycle rule (delete blobs under `tenants/*/projects/*/jobs/` after, say, 7 days). Downloads and drawing pages are streamed through the API after the tenant ownership check; clients never receive a storage URL. Uploaded drawings are parsed from a local scratch copy and then pushed (original, page images, `ingest.json`).

### Queue

| Variable | Default | Meaning |
|---|---|---|
| `SHILPA_QUEUE_BACKEND` | `db` | `db` (the `queue_messages` table) or `servicebus`. The outbox always stays in the database; with `servicebus` the dispatcher (coordinator) sends each outbox row with `message_id` = the outbox id. |
| `SHILPA_SERVICEBUS_NAMESPACE` | | `<namespace>.servicebus.windows.net`. `DefaultAzureCredential`; roles **Azure Service Bus Data Sender** (api not needed; coordinator, worker) and **Data Receiver** (coordinator for `plan`, worker for `cad`). |
| `SHILPA_SERVICEBUS_QUEUE_PREFIX` | | Prepended to the queue names `plan` and `cad`. |
| `SHILPA_SERVICEBUS_CONNECTION_STRING` | | Service Bus emulator only. |
| `SHILPA_SERVICEBUS_WAIT_S` | `1` | How long one `receive` waits for a message before returning none. |

Queue entities (infrastructure) must have: duplicate detection on (window at least the outbox retry horizon, e.g. 1 day), `lockDuration` matching `SHILPA_LOCK_DURATION_S` (default 60 s; the worker renews it), and `maxDeliveryCount` equal to `SHILPA_MAX_DELIVERY_COUNT` (the client also dead-letters when a message exceeds it). `complete`, `abandon`, `renew` and `dead_letter` return `False` when the lock was lost, as the database queue does. Receivers are long-lived because a lock belongs to the link that received the message. Handlers stay idempotent: duplicate detection does not replace database idempotency.

### Tests

`uv run pytest` needs none of this. Optional: `TEST_DATABASE_URL=postgresql://user:pw@host:port/db` runs `tests/test_postgres.py` in throwaway schemas; Azurite on `127.0.0.1:10000` (or `SHILPA_TEST_AZURITE_CONNECTION_STRING`) enables the Azurite blob tests, and `SHILPA_TEST_SERVICEBUS_CONNECTION_STRING` the emulator queue tests. Otherwise those tests skip with the reason; the logic is always covered by in-memory fakes of the SDK clients (`tests/fakes_azure.py`).
