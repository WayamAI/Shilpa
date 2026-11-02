# Containers and local parity

Build step 1 of `hosting-plan.md`. Two images, one compose file.

| File | Purpose |
|---|---|
| `apps/web/Dockerfile` (+ `docker-entrypoint.sh`, `.dockerignore`) | Studio: Next.js 16 `output: "standalone"`, node `24.22.2-slim` (Node 24 LTS, pinned), non-root uid 10001, port 3000 |
| `Dockerfile.backend` (+ root `.dockerignore`) | API, coordinator and CAD worker: one image, three commands. Python `3.12.16-slim-trixie`, uv `0.13.6`, non-root uid 10001, port 8000 |
| `docker-compose.yml` | Local parity: api, coordinator, worker, web; profile `cloud` adds Postgres 18.6 and Azurite 3.35.0 |

## Build

```
docker build -t shilpa-backend:local -f Dockerfile.backend .
docker build -t shilpa-web:local apps/web
```

Image sizes (measured, Docker Desktop, amd64): backend 2.1 GB on disk (487 MB compressed content), web 395 MB (97 MB compressed). The backend is mostly the OCP/OpenCascade wheel, numpy/scipy-class libraries and PyMuPDF.

## Run locally

```
docker compose up --build        # studio http://localhost:13000, API http://localhost:18000/v1/health
docker compose --profile cloud up postgres azurite   # cloud-parity services (not used by today's code)
```

Ports are 13000 (web), 18000 (API), 15432 (Postgres), 11000-11002 (Azurite blob, queue, table; 10000 was taken on the dev machine). Sign in with `dev@wayam.local`.
Today's code runs on SQLite in the `shilpa-data` volume, shared by api, coordinator and worker (the queue is DB-backed).
Compose substitutes variables from a `.env` in the repo root, and the developer `.env` there is the same file the app reads. If it sets `SHILPA_LLM_PROVIDER=ollama` and `OLLAMA_API_KEY`, the containers will use them; use a separate `--env-file` for a clean run. The model kill switch defaults to `SHILPA_LLM=off`; to plan with a model put `SHILPA_LLM=on` plus `AZURE_OPENAI_*` (or `SHILPA_LLM_PROVIDER=ollama` and `OLLAMA_API_KEY`, laptops only) in an untracked `.env` next to the compose file.

When the Postgres driver lands (step 2): `SHILPA_DATABASE_URL=postgresql+psycopg://shilpa:shilpa@postgres:5432/shilpa docker compose --profile cloud up`. Compose does not default to Postgres yet because `psycopg` is not in `uv.lock`.

The **Service Bus emulator is not enabled**: it requires accepting Microsoft's emulator EULA (`ACCEPT_EULA=Y`), a SQL Server container with its own EULA, and a queue `Config.json`. A commented block in `docker-compose.yml` shows the wiring; enable it deliberately.

## The API origin is a runtime setting

Next 16 serialises `rewrites()` at build time (no runtime hook). The image is built with a placeholder origin and `docker-entrypoint.sh` replaces it with `SHILPA_API_ORIGIN` at container start (a text swap in `server.js` and `.next/*.json`; idempotent). One image therefore serves every environment: in Container Apps set `SHILPA_API_ORIGIN=https://<api-internal-fqdn>`. For a plain `next build` outside Docker the build-time variable still applies. If a later Next release changes how rewrites are serialised, check the swap still matches (the compose smoke test catches it: `/v1/health` through the web port).

## What each container needs

| Container | Command | Env | Notes |
|---|---|---|---|
| web | `node server.js` | `SHILPA_API_ORIGIN` (required in practice), `PORT` (3000) | No secrets. Health: `GET /login` 200. |
| api | uvicorn `shilpa.api.app:app` | `DATABASE_URL`, `SHILPA_VAR_DIR=/data`, `SHILPA_AUTH_MODE`, planner settings | Health: `GET /v1/health`. Needs the DB and blob storage. |
| coordinator | `python -m shilpa.coordinator` | `DATABASE_URL`, `SHILPA_VAR_DIR` | Outbox dispatcher; later Service Bus send. No ingress. |
| worker | `python -m shilpa.workers.cad` | `DATABASE_URL`, `SHILPA_VAR_DIR`, `SHILPA_WORKER_TIMEOUT_S`, optional `SHILPA_FREECAD_CMD` | Runs the geometry subprocess. Later: Container Apps Job + KEDA Service Bus scaler. |

Identities (step 4, no keys in env): api and coordinator get a user-assigned identity with Blob Data Contributor, Service Bus Data Sender and Key Vault secrets user; the worker identity gets Blob and Service Bus Data Receiver; none for the geometry subprocess.

## Security notes

- No `.env`, keys or `var/` are in either build context (`.dockerignore`) and nothing sets credentials with `ENV`/`ARG`.
- The geometry subprocess is launched by `shilpa/workers/cad.py` with `env=_scrubbed_env()` (allow-list: PATH, HOME, LANG, `SHILPA_FREECAD_CMD`, Windows basics). `DATABASE_URL`, storage and model credentials are not inherited. The image sets `PATH`, `HOME` (`/home/shilpa`) and no secrets, so nothing sensitive leaks through those. Network egress denial for the subprocess is an infrastructure concern (Container Apps environment egress rules) and is not enforced by the image.
- Both runtime images run as uid 10001. The backend writes only to `/data` (a volume; on Container Apps use Azure Files or an emptyDir for worker scratch, Blob for artifacts once step 2 lands).

## FreeCAD (optional)

`docker build -f Dockerfile.backend --build-arg WITH_FREECAD=true ...` installs Debian's `freecad` and sets `SHILPA_FREECAD_CMD=/usr/bin/freecadcmd`. Off by default (about 1 GB larger; decision pending, hosting plan question 4). The FreeCAD path was developed against the Windows `FreeCADCmd.exe`; the Linux package is untested with it, so treat the flag as experimental until `evals/run_freecad.py` has been run on that image.

## System libraries

Only `libgl1` (it pulls libX11/libGLX). `ldd` on `OCP.cpython-312-x86_64-linux-gnu.so` in the built image shows no other missing library, and `import build123d` plus a `Box` volume check pass. GLU and the other X libs are not needed by the no-VTK OCP wheel.
