@AGENTS.md

# Shilpa studio: working notes for agents

Read this before exploring. It exists so you don't have to rediscover it.

## Design system (Beam × Clay)

- Source of truth: Paper file `01M6DGJW2NF077S079TSKYDF4E` ("Shilpa — Product UI (Beam × Clay)"). Pages: `p-2-0` Foundations (`1Y5-0`), `p-1-0` Core flow (shell `1-0`, home `1X-0`, library `3R-0`, part detail `5L-0`, import `7F-0`, composer `99-0`/`159-0`/`1C7-0`, save `ER-0`, sign-in `1TD-0`, modals `1UN-0`, states `1W3-0`), `p-3-0` Language, `p-4-0` Mobile (`2CH-0`, `2FN-0`). Take values from `get_jsx`/`get_computed_styles`, never from screenshots.
- Tokens: `src/styles/tokens.css` only (Tailwind v4 `@theme static`). Defaults are cleared, so only Shilpa tokens resolve. Never put a hex value in a component.
  - Neutrals: `bg` `surface` `surface-2` `line` `line-strong` `ink` `body` `muted` `stage`.
  - Hues: `action` `pass` `fail` `consent` `ai` `basic` `complex`, each with a `-soft` tint.
  - **Text on tints uses the `*-text` shades** (AA). Paper's raw hues fail AA as small text. `muted` is for icons and dots; text uses `muted-text`.
  - Type: `text-caption` 11, `xs` 12, `sm` 13 (UI base), `md` 14, `brand` 15, `lg` 16, `heading` 17, `title` 18, `xl` 20, `page` 24, `headline` 26, `2xl` 28, `3xl` 40, `display` 44, `prose` 13/19, `lede` 16/24.
  - Radii: `sm` 6, `md` 8, `panel` 10, `lg` 12, `xl` 14, `2xl` 16. Shadows: `action`, `popover`, `dialog`, `toolbar`, `raised`. Motion: `duration-fast/base/slow`, `ease-out`.
- Primitives: `import { … } from "@/components/ui"` (button, field, feedback, overlay, surface, tabs). Use them; don't hand-roll controls. Live gallery of every state: `/dev/ui` (development only).
- Rules: sentence case everywhere, no uppercase tracked labels. Light mode only. One primary button per screen. Things in the design with no backend get `<Badge tone="consent">Planned</Badge>`, never fake data. Imagery in `public/imagery` (SH-* ids, see `C:\Users\mriga_ijtdono\shilpa-images-in\mapping.md`) is for categories and states, never as a stand-in for real geometry. Every screen must fit 390px wide with no horizontal scroll. Animations go behind `motion-safe:`.
- Global focus ring and base styles are in `@layer base` in `src/app/globals.css`. Containers focused in code use `tabIndex={-1}` and get no ring.

## Commands (from apps/web)

| What | Command |
|---|---|
| Typecheck | `npx tsc --noEmit` |
| Lint | `npx eslint` |
| Build | `npm run build` (set `SHILPA_API_ORIGIN` if the API isn't on 8000) |
| e2e | `SHILPA_WEB_URL=http://localhost:3101 npx playwright test` |

There is no formatter configured.

## Running locally: ports

- **8000 may belong to another project** (Parikshan). Don't kill it. Run Shilpa's backend on another port: `uv run python -m shilpa.dev --no-studio --port 8010`.
- Only one `next dev` can run per folder. For a second server, build with `SHILPA_API_ORIGIN=http://127.0.0.1:8010 npm run build`, then `node node_modules/next/dist/bin/next start --port 3101`. Use node directly: stopping an `npx` wrapper leaves the child holding the port.
- Rewrites read `SHILPA_API_ORIGIN` at build time for `next build`/`next start`. The Docker image substitutes it at container start instead (`apps/web/docker-entrypoint.sh`).
- Dev identities: `dev@wayam.local` (admin), `viewer@wayam.local` (read-only), `other@example.com` (second tenant). The session is the `shilpa-session` cookie, shared across localhost ports.

## Cost discipline for agents

- Delegate mechanical work (restyles that follow an existing pattern, test updates, asset pipelines) to a Sonnet subagent with a narrow file scope. Keep design decisions and verification in the main session.
- Parallel agents must not run `next build`/`dev`/`start` in the same folder (shared `.next`) and must not commit. The main session builds, checks in Chrome, and commits.
- Check phone layout with a 390×844 same-origin iframe in the page. Resizing the Chrome window is unreliable when it's maximised.
