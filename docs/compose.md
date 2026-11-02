# Composition language, phase P0

Phase P0 of the Shilpa Composition Language (spec v0.1, sections 1 to 8). It covers the IR, the @-mention parser, the resolver for native and catalog parts, the ops `add`, `ground`, `place`, `mate` and `insert`, units and plausibility checks, interpret-then-apply, and an append-only step history.

## Pipeline

1. **Parse mentions** (`shilpa/compose/mentions.py`). Deterministic, follows the EBNF in spec 2.1, never raises.
2. **Resolve** (`resolve.py`). Lookup order: instances in this composition, then the tenant's native parts, then the catalog. An ambiguous match becomes a blocker with options. Pinned chips are checked against the library.
3. **Compose** (`shilpa/agent/composer.py`). Prose goes in and IR steps come out, via `call_structured(purpose="compose")`. The model refers to parts only by mention id. Any pin it writes is discarded.
4. **Expand** (`expand.py`). Selectors are evaluated to concrete features in a fixed order. `insert` becomes N instances and N mates. Units are normalised and plausibility is checked. Fit, count and reference problems become blockers with patch options.
5. **Lower** (`lower.py`). The result is an `AssemblySpec` with ports derived from features, serialised canonically (`spec_json`, `spec_hash`).
6. **Apply** (`shilpa/api/compose.py`). The interpretation is re-run without the model, then the existing assembly job is enqueued through the outbox and a `CompositionStep` is appended.

Feature tables come from `features.py`:
- **Native parts:** the recipe is built and hole walls are read from the persistent topology names (`<hole op>.wall[k]`), plus the six bounding-box faces.
- **Catalog parts:** each port is a feature, with the aliases `axis.main` and `face.end[0]`/`face.end[1]`.

## API

All routes are under `/v1`, and every query filters by tenant.

| Route | Who | Notes |
|---|---|---|
| `POST /compositions` `{project_id, name}` | editor, admin | 201 |
| `GET /compositions/{id}`, `GET /projects/{pid}/compositions` | any member | |
| `POST /compositions/{id}/interpret` | editor, admin | Builds nothing. Calls the model only when `steps` is absent; 503 `planner_disabled` while `SHILPA_LLM=off`. |
| `POST /compositions/{id}/apply` | editor, admin | 202. Takes an `Idempotency-Key`. Returns 409 `stale_revision`, `step_running` or `interpretation_changed`, or 422 `blocked`. |
| `GET /compositions/{id}/steps` | any member | Append-only history; status is `pending`, `applied` or `failed`. |

### Interpret request

```json
{"prompt": "wherever there are holes on @plate, put @ISO4032-M6 inside",
 "mentions": [{"text": "@plate", "ref": {"item": "<model id>", "version": "<version id>"}}],
 "steps": null,
 "answers": []}
```

- `mentions` is optional: it holds the chips the user picked, pinned as in spec 2.2.
- `steps` is set when re-interpreting a card. It must be the card's `steps`, sent back unchanged.
- `answers` is set together with `steps`: it holds the `patch` list of each option the user chose.

### Interpret response (the interpretation card)

```json
{
  "ir_version": "0.1",
  "composition_id": "…",
  "base_version_id": "… or null",
  "status": "ready | blocked | empty",
  "reading": "Place 4 x ISO 4032 M6-1, one per Ø6.4 hole on plate, coaxial, seated on the exit face (4 instances, 4 mates).",
  "readings": [{"step_id": "s3", "op": "insert", "text": "…", "instances_added": ["iso4032_m6", "…"], "mates_added": ["s3_m1", "…"]}],
  "counts": {"instances_added": 4, "mates_added": 4, "instances_total": 7, "mates_total": 6},
  "quantities": [{"step_id": "s3", "field": "offset.distance", "as_typed": "10 m", "value": 10, "unit": "m", "mm": 10000,
                  "normalised": "10 m → 10 000 mm", "provenance": "user"}],
  "assumptions": [{"step_id": "s3", "field": "offset.direction", "value": "+X", "reason": "…", "by": "reader (optional)"}],
  "filters": [{"step_id": "s3", "text": "@plate", "path": "holes[*]", "filter": [{"attr": "diameter", "op": "≈", "value": 6.4, "unit": "mm"}],
               "count": 4, "of": 6}],
  "mentions": [{"id": "m1", "text": "@plate", "status": "ok | ambiguous | unknown | invalid", "label": "plate", "message": "",
                "ref": {"text": "@plate", "mention": "m1", "source": "native | catalog | instance", "item": "…", "version": "…"},
                "candidates": []}],
  "blockers": [{"id": "s3:fit_mismatch", "step_id": "s3", "code": "fit_mismatch", "message": "2 of 6 holes are Ø8.4 (M8 clearance). …",
                "field": "target.selector", "blocking": true,
                "options": [{"label": "Only the 4 Ø6.4 holes", "patch": [{"step": "s3", "set": {"…": "…"}, "acknowledge": null, "append_step": null}]}]}],
  "warnings": [{"step_id": "s2", "code": "under_constrained", "message": "…"}],
  "steps": [{"id": "s3", "op": "insert", "…": "…"}],
  "ir": {"ir_version": "0.1", "composition_id": "…", "units": "mm", "steps": ["applied steps followed by the new ones"]},
  "spec_hash": "sha256 of the lowered AssemblySpec, or null",
  "spec": {"the AssemblySpec Apply would build, or null": "…"},
  "llm": {"used": true, "purpose": "compose", "llm_calls": 1, "cost_usd": 0.0, "…": "…"},
  "disclaimer": "Geometry validated. Not reviewed for engineering release."
}
```

**Blocker codes:**
- References: `ambiguous_reference`, `unknown_part`, `unresolved_reference`, `invalid_reference`, `not_in_composition`, `broken_reference`, `mention_syntax`.
- Features: `missing_feature`, `unknown_feature`, `selection_changed`.
- Values and fit: `unit_suspect`, `unit_mismatch`, `bad_unit`, `fit_mismatch`.
- Placement: `already_placed`, `unplaced`, `needs_one_face`, `needs_one_axis`, `needs_ports`.
- Other: `planned`, `clarify`.

A blocker with `"blocking": true` disables Apply until the user picks an option. Picking `acknowledge` turns the blocker into a recorded warning.

### Apply request

```json
{"prompt": "…", "steps": "<card.steps>", "base_version_id": "<card.base_version_id>", "spec_hash": "<card.spec_hash>",
 "idempotency_key": "optional; the Idempotency-Key header also works"}
```

Response: `{"step": {…, "status": "pending"}, "job": {…}}`. Follow `GET /v1/jobs/{id}/events`. The step becomes `applied`, with `result_version_id`, once the job succeeds.

## Decisions taken in P0

- [Assumption] **One tenant library** (spec 8.4). Every single-part model in any of the tenant's projects can be mentioned by the slug of its name.
- [Assumption] **Pinned versions only** (spec 8.4). A mention resolves to the model's head version. Applied steps keep their version ids, and replay loads exactly those versions.
- [Assumption] **Slug precedence.** Composition instances come first, then native parts, then the catalog. If a native part and a catalog designation share a slug, the native part wins.
- [Assumption] **`@shaft-<d>` alias.** It means catalog `linear.shaft`, diameter d, length 200 mm. The designation lookup does not know this fixture name.
- [Assumption] **Box faces.** P0 faces are the six sides of the part's bounding box (`face.top`, `face.x_min`, …), not recognised planar faces.
- [Assumption] **Feature order.** Group members are ordered by the (z, y, x) of their origin (spec 2.1). Indices are 0-based; `#k` instance numbers are 1-based.
- [Assumption] **Hole frames.** A hole's origin is its entry centre. The entry side comes from the recipe hole's `face`; for an `entry_face` hole it is the end with the larger coordinate. `seat: exit` uses the other end.
- [Assumption] **Default seats.** `insert` seats on the hole's entry face unless the IR says `exit`. The source seats on its first face port (a nut's `face_a`), or on the bottom of its box.
- [Assumption] **`place`.**
  - It centres the source on the target face, with the source's opposite box side facing it, and `offset` is the gap between the two.
  - `away from` uses +X, recorded as an assumption, because the source has no position yet.
  - Rotation about the face normal is fixed (the x axes stay aligned). This is recorded as an assumption, with an `under_constrained` warning.
  - A placement with a gap uses intent `clearance`, so the contact check does not flag the intended gap.
- [Assumption] **Coaxial mates.**
  - Coaxial with a distance becomes a `fixed` aligned mate. Without a distance, it becomes `cylindrical`.
  - "15 mm from `face.end[0]`" is measured from that face, inward along the axis, to the source's axis origin (a bearing's centre).
  - Matching `bore_d` contracts imply a `press_fit` intent (assumed) and a 1 mm³ interference allowance.
- [Assumption] **Fit check.** A fastener of thread size M fits a hole whose diameter lies within the ISO 273 clearance range for M (fine to coarse, ±0.01 mm), or a tapped hole of size M.
- [Assumption] **Plausibility.** A length is suspect when it is more than 20 times the largest part dimension in the composition (spec 3.2). Steps that were already applied are not re-questioned.
- [Assumption] **Default tolerances.** `≈` uses 0.05 mm and `=` uses 0.001 mm, unless the predicate has `tol`.
- [Assumption] **A part must be placed.** A part added without being grounded or placed is a blocker (`unplaced`), because the mate tree would leave it floating. If nothing is grounded, the first part is grounded (assumed).
- [Assumption] **Answers.** The client sends back the chosen option's patch list. Patches can only set fields on existing steps (dotted paths, at most 5 deep), acknowledge a code, or append a step. The result is validated again as IR.
- [Assumption] **History.** The history is append-only. A step's `status` moves forward (`pending` to `applied` or `failed`) when the job ends; the change is picked up lazily on read and on apply. Only one step may be pending at a time.
- [Assumption] **Fixture bracket.** The `@bracket` used in the tests is a flat 80 x 40 x 5 mm part with 4 Ø6.4 holes, not a true L-bracket.

## Not in P0

These ops are in the schema, but `interpret` reports them as `planned` (never faked): `fasten`, `pattern`, `repeat`, `constraint`, `replace` and `remove` (P3), `mirror` and `promote` (P1). Also not in P0:

- `parallel`, `perpendicular` and `tangent` constraints.
- Nested parts (`@a/b`).
- Placing along an axis or edge.
- Seats other than entry and exit.
- `LibraryItem` tables, import and recognition.
- Editing and reordering steps.
- A per-stage model for `compose`: `settings.stage_model` has no `compose` entry yet, so compose uses the provider default. Adding one needs a `settings.py` change.
