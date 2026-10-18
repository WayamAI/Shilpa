# R1 requirement scoring

Language report rescored: `language_report_req.json`; 36 tasks that should build (the clarify/conflict/unsupported tasks keep their outcome scoring in run_language.py).

| Metric | Gold suite | Generated suite |
|---|---|---|
| Build rate (old headline) | 94.4% | |
| Legacy pass (bbox + volume + hole counts) | 97.2% | |
| **Pass Rate** (all tests pass) | 94.4% | 91.7% |
| **Requirement Score** (mean fraction passed) | 94.4% | 91.7% |
| Tests | 264 | 249 |
| Mutation score, language references (gate >= 90%) | 99.6% (260/261) | 99.6% (252/253, 33 suites) |
| Mutation score, language references, gold without volume tests (ablation) | 99.6% (260/261) | |
| Mutation score, 30 corpus parts: legacy analytic oracle only | 89.4% (228/255) | |
| Mutation score, 30 corpus parts: oracle + requirement tests | 100.0% (255/255) | |

Gold vs generated verdicts: agreement 100.0% on the agent's outputs (n=33, kappa None); 99.2% on mutants (n=253, kappa -0.004).

Gold tests passed by category: dimension 86/94, geometric_type 11/11, spatial 28/28, topology 56/59, validity 34/36, volume 34/36.
Generated tests passed by category: dimension 101/106, geometric_type 10/10, spatial 32/33, topology 33/34, validity 33/34, volume 31/32.

Mutants, gold (language): count 7/7, dim 157/157, drop 33/33, move 63/64; 28 equivalent and 29 stillborn excluded. Survivors: 1.
Mutants, generated (language): count 7/7, dim 154/154, drop 32/32, move 59/60; 28 equivalent and 29 stillborn excluded. Survivors: 1.
Mutants, legacy oracle (corpus): count 6/6, dim 152/152, drop 33/33, move 37/64; 14 equivalent and 34 stillborn excluded. Survivors: 27.
Mutants, gold (corpus): count 6/6, dim 152/152, drop 33/33, move 64/64; 14 equivalent and 34 stillborn excluded. Survivors: 0.

Reading these numbers:
- A task that should build but produced no geometry (clarification, refusal) scores 0 on both suites. The legacy scorer accepts a refusal on the injection task; requirement scoring does not, because no part exists.
- Gold suites were strengthened once after the first mutation pass exposed gaps (bore concentricity, row centring, L-profile face count, per-wall thickness). Their mutation scores are therefore partly in-sample; the generated suites were never tuned against these mutants.
- Mutants are excluded when they fail to build (the adapter's own preconditions reject them) or are congruent to the reference in the canonical frame. Mirror mutants of these parts are all equivalent. A rotated bolt circle is only generated when the recipe states a start angle; when the prompt itself does not, surviving it is correct.
- Kappa is degenerate when one verdict dominates (all outputs pass, nearly all mutants are killed); read the raw agreement and the gold_only / gen_only counts in the JSON instead.

Elapsed 46.3 s. Full data: `evals/out/requirements_report.json`.
