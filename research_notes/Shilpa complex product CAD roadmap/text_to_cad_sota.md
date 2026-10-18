# Text-to-CAD and Generative Parametric CAD: State of the Art (as of Oct 2026)

Scope: LLM CAD-code generation, generative B-rep/sequence models, agentic CAD with tool use and visual verification, target languages, failure modes. Written for Shilpa (typed feature IR, build123d/OCCT, FreeCAD export, gpt-5.5 planner). About 17 tool calls were used. Many 2026 papers were checked only at the abstract level, so numbers are reported only where the primary text was read. Treat "no numbers given" as a real gap, not as zero.

## 1. LLM code generation for CAD: accuracy, benchmarks, operation coverage, code vs typed DSL

### Takeaway
Fine-tuned small LLMs that write CadQuery reach very low invalid rates (about 0-1.5%) and high IoU, but only on DeepCAD-style sketch+extrude data. On 2026 industrial benchmarks, frontier models (including GPT-5.5) drop to 56-81% executability and Solid IoU of about 0.28-0.54. They also tend to replace sweeps, lofts and twist-extrudes with simpler extrude patterns. Typed IRs, specs and construction graphs that sit between the LLM and the kernel are a strong 2026 trend (CADIR, ASSEMCAD, Embodied CAD, CADSmith's JSON planner spec).

### Cited Findings
**Text-to-CadQuery (arXiv 2505.06507, 2025)**
- Most open-source models (Gemma, Qwen, Mistral, Llama) fail to generate valid CadQuery zero-shot, while commercial models can. An automatic fixing step (for example, adding a missing workplane) raises execution success from 53% to 85%. A GPT-4.1-mini fine-tuned on a 10k subset reached a 0% invalid rate, with accuracy similar to a fine-tuned 7B model. — [Text-to-CadQuery](https://arxiv.org/pdf/2505.06507)

**CAD-Coder (arXiv 2505.19713, 2025; SFT + chain-of-thought + GRPO with a geometric (Chamfer) reward, outputs CadQuery)**
- Mean CD 6.54, median CD 0.17, invalid rate (IR) 1.45%.
- Ablations: SFT alone gave mean CD 74.6 and IR 5.3%. GRPO without CoT gave mean CD 17.3 and IR 4.95%.
- Zero-shot baselines on the same test set: Claude-3.7-Sonnet IR 47.03% (mean CD 186.5); GPT-4o IR 93.0%. — [CAD-Coder](https://arxiv.org/html/2505.19713)
- This is evidence that RL from geometric reward cuts both the invalid rate and the geometric error relative to SFT alone.

**CADmium vs Text2CAD**
- Comparison table on CADPrompt, reported in CAD-Judge: CADmium IR 6.28%, Text2CAD IR 1.57%. These are secondary numbers. I did not read CADmium's own paper. — [CAD-Judge (arXiv 2508.04002)](https://arxiv.org/html/2508.04002)

**Text2CAD (NeurIPS 2024)**
- Generates sketch-and-extrude sequences from text. It is trained on DeepCAD (about 150k training and 8k test/val sequences, all sketch+extrude). — [Text2CAD NeurIPS paper](https://proceedings.neurips.cc/paper_files/paper/2024/file/0e5b96f97c1813bb75f6c28532c2ecc7-Paper-Conference.pdf)
- The HF mirror of the dataset lists CC BY-NC-SA 4.0 (third-party upload, so verify). — [HF SadilKhan/Text2CAD](https://huggingface.co/datasets/SadilKhan/Text2CAD)

**CAD-Recode (arXiv 2412.14042, Dec 2024) and cadrille (arXiv 2505.22914, ICLR 2026)**
- Both translate point clouds to CadQuery code.
- CAD-Recode is built on Qwen2-1.5B plus one linear layer and claims state of the art on DeepCAD, Fusion360 and CC3D as of Dec 2024. The repo has a LICENSE.md (type not captured). — [CAD-Recode GitHub](https://github.com/filaPro/cad-recode)
- cadrille is built on Qwen2-VL-2B. Its SFT data is about 1M procedurally generated CAD-Recode samples plus about 160k DeepCAD samples with text. It accepts point cloud, image or text input. — [cadrille](https://arxiv.org/html/2505.22914v1)
- cadrille point-cloud results, IoU / IR:

  | Dataset | SFT | After Dr.CPPO online RL (GRPO variant) |
  |---|---|---|
  | DeepCAD | 87.1 / 2.1% | 90.2 / 0.0% |
  | Fusion360 | 79.8 / 2.8% | 85.0 / 0.2% |
  | CC3D (real scans) | 61.8 / 5.9% | 67.9 / 0.2% |

- cadrille multi-view image results after RL: DeepCAD IoU 92.2, Fusion360 84.6, CC3D 65.0, all with IR at or below 0.1%. Text-only result on DeepCAD (SFT): IoU 81.1, IR 1.4%. Offline DPO helped much less than online RL. — [cadrille](https://arxiv.org/html/2505.22914v1)
- Operation coverage: CAD-Recode's procedural generator lacks extruded cuts and symmetric extrusions. CC3D contains revolve, chamfer and fillet, which helps explain the lower CC3D IoU. — [cadrille](https://arxiv.org/html/2505.22914v1)
- Licence: cadrille weights are CC BY-NC-4.0 (non-commercial). Code is at github.com/col14m/cadrille. — [HF cadrille-rl](https://huggingface.co/maksimko123/cadrille-rl)

**2026 benchmarks**
- **BenchCAD (arXiv 2605.10865):**
  - 17,900 execution-verified CadQuery programs across 106 industrial part families (bevel gears, compression springs, twist drills). Tasks: VQA, code QA, image-to-code, and instruction-guided editing. More than 10 frontier models were evaluated.
  - Findings: models recover coarse outer geometry but miss fine 3D structure. They misread industrial parameters and replace sweeps, lofts and twist-extrudes with simpler sketch-extrude patterns. Fine-tuning and RL help in distribution but generalize poorly to unseen part families. — [BenchCAD](https://arxiv.org/abs/2605.10865)
- **RealCADBench (arXiv 2609.03773, Sep 2026):**
  - 12,632 tasks across 19 factory-automation categories, covering parts and assemblies. Models generate FreeCAD Python code. Inputs are text, 2D drawings, product photos and renders. The reported evaluation uses a 1,770-task slice.
  - Results for the six frontier-scale models across part regimes: executability 0.565-0.812, Solid IoU 0.284-0.538, Surface IoU 0.112-0.217. No model leads all four metrics.
  - On the 25-task assembly study, Codex with GPT-5.5 (agentic) beats standalone GPT-5.5 on executability and IoU, but scores 6.98 points lower on the visual-semantic judge.
  - Authors' conclusion: "execution alone is insufficient". — [RealCADBench](https://arxiv.org/abs/2609.03773)
- **P3D-Bench (arXiv 2606.11152):**
  - Text-to-3D, image-to-3D and assembly tasks: 400 text cases, 400 image cases, 203 assemblies.
  - Models capture global shape and semantic identity but miss precise parametric geometry. On assemblies, models get neither the part geometry nor the part count right. — [P3D-Bench](https://arxiv.org/abs/2606.11152), [project page](https://spatiaos.github.io/projects/P3D-Bench/)
- **Other 2026 benchmarks seen, not read:** Text2CAD-Bench (arXiv 2605.18430), CADBench (2605.10873), UniCAD (2606.05058). — [search listing](https://arxiv.org/pdf/2605.10873), [UniCAD](https://arxiv.org/pdf/2606.05058)

**Code vs typed IR, 2026 work**
- **CADIR (arXiv 2608.00891, Aug 2026):**
  - An executable IR on OCCT/OCP with explicit compositional operations and fine-grained execution diagnostics. It records operations, parameter dependencies, constraints and topology selections in a construction graph.
  - "Geometric Signature Matching" re-identifies edges and faces across parameter or backend changes, so adapters can rebuild native feature trees in FreeCAD, SolidWorks and Fusion 360.
  - Construction-graph retrieval (text/image) improves generation. It claims better fidelity and execution reliability than other representations, but the abstract gives no numbers. — [CADIR](https://arxiv.org/abs/2608.00891)
  - This is architecturally very close to Shilpa's typed IR plus FreeCAD export.
- **CADDesigner (arXiv 2508.01031, v6 May 2026):** argues that existing CAD SDKs, including build123d, were not designed for LLM generation. It notes that build123d's context managers and symbolic operator overloading can make LLM generation harder. — [CADDesigner](https://arxiv.org/html/2508.01031v5)
- **ToolCAD (arXiv 2604.07960, Apr 2026):** treats the LLM as a tool-using agent in an interactive CAD "gym" trained with online curriculum RL and CAD chain-of-thought. It claims open models comparable to proprietary ones (no numbers in the abstract). — [ToolCAD](https://arxiv.org/abs/2604.07960)
- **Zero-to-CAD (arXiv 2604.24479):** agentic synthesis of interpretable CAD programs at million scale without real data (seen in search only). — [Zero-to-CAD](https://arxiv.org/pdf/2604.24479)

### Inferences
- Benchmark numbers split sharply by data distribution. Near-perfect execution and about 90% IoU on DeepCAD/Fusion360 (sketch+extrude) do not carry over to industrial families with sweeps, lofts and springs, where even GPT-5.5 sits around 0.5 Solid IoU. Shilpa's 97% on prismatic and turned parts is consistent with the "easy regime."
- The best-documented ways to push past that regime are:
  - a constrained or typed action space (CADIR, Embodied CAD, ASSEMCAD);
  - online RL with geometric rewards (CAD-Coder, cadrille);
  - render-based verification (Section 3).
- Shilpa's typed-IR approach matches the 2026 direction. To scale it, the main work is extending the IR vocabulary (sweep, loft, shell, sheet metal) and keeping topology references stable, which is CADIR's signature-matching problem.

### Gaps
- No primary numbers were read for CAD-Llama, CADmium (own paper), Query2CAD, CAD-Assistant, ReCAD, ToolCAD or CADIR.
- I found no head-to-head study of build123d vs CadQuery vs a typed DSL with the same LLM.
- The CAD-Recode code/weights licence type was not captured (LICENSE.md exists).
- The DeepCAD dataset licence was not confirmed.

## 2. Generative B-rep and sequence models: complexity and controllability

### Takeaway
Direct B-rep generators (BrepGen, DTGBrepGen, BrepDiff, HoLa, BrepGPT, TG-Diff, BrepForge) can produce freeform, curved-surface solids that code-based methods cannot. However, they are mostly unconditional or class/point-cloud conditioned. They do not produce an editable feature history, and text or dimension control is weak or indirect. They are a poor fit as the main engine for a dimension-accurate engineering agent. They could be a niche option for freeform or styling surfaces.

### Cited Findings
- **BrepGen (arXiv 2401.15563, SIGGRAPH 2024, Autodesk Research):**
  - A DDPM diffusion model over a hierarchical latent tree. It generates top-down (faces, then edges, then vertices) and merges duplicate nodes to recover topology.
  - It is unconditional in the original paper and demonstrates complex freeform B-reps. — [BrepGen arXiv](https://arxiv.org/abs/2401.15563), [Autodesk page](https://www.research.autodesk.com/publications/brepgen/)
- **2025 follow-ups to BrepGen:**
  - DTGBrepGen conditions generation on an autoregressively generated face-adjacency graph.
  - BrepDiff is a single-stage diffusion model over masked UV-grids.
  - HoLa uses holistic latent codes that cover both primitives and topology. — [BrepGPT related work](https://arxiv.org/pdf/2511.22171)
- **BrepGPT (arXiv 2511.22171, Nov 2025):**
  - A single-stage autoregressive model. It uses a Voronoi Half-Patch representation with dual VQ-VAEs and a decoder-only Transformer, and claims SOTA on unconditional generation.
  - Supported conditioning: class, point cloud, text, image, plus autocompletion and interpolation.
  - Its text conditioning is indirect: GPT-4o makes an image, which becomes a point cloud, which conditions the B-rep model. It was evaluated on DeepCAD. — [BrepGPT](https://arxiv.org/abs/2511.22171)
- **Other 2026 B-rep generators (seen in search only):** TG-Diff (arXiv 2607.21928, discrete topology diffusion plus topology-conditioned geometry diffusion) and BrepForge (arXiv 2605.19411, wireframe composition plus boundary-conditioned surface instantiation). — [TG-Diff](https://arxiv.org/pdf/2607.21928), [BrepForge](https://arxiv.org/pdf/2605.19411)
- **Foundational sequence and B-rep models (older, flagged):** DeepCAD (ICCV 2021, about 178k sketch+extrude sequences), SkexGen (ICML 2022), HNC-CAD (ICML 2023), SolidGen (2023). These generate sketch+extrude sequences or B-reps on the DeepCAD/ABC distributions. — [DeepCAD dataset note](https://blog.texocad.ai/glossary/deepcad-dataset); others not re-verified here

### Inferences
- None of the B-rep generative models found offers precise dimensional control from text. Their outputs lack a parametric feature tree, which breaks Shilpa's FreeCAD/editability contract.
- For freeform surfaces, a more practical near-term route is to add loft, sweep and NURBS-surface operations to the typed IR. B-rep generators could serve as a research option for "styling" surfaces only.

### Gaps
- I did not obtain face-count limits, validity rates or licences for BrepGen, DTGBrepGen, HoLa, BrepGPT, TG-Diff or BrepForge. Older work reports BrepGen handling up to roughly 50 faces, but I did not verify this in this session.
- I found no 2026 text-plus-dimension-conditioned B-rep diffusion model with quantitative results.

## 3. Agentic CAD: tool use, render + VLM critique, test-driven verification, RL

### Takeaway
There is now quantitative evidence that verification loops help, mainly on harder parts.
- CADSmith: a vision loop cuts mean Chamfer distance on complex parts from 49.7 to 1.4.
- CADCodeVerify: about 7% lower point-cloud distance for GPT-4.
- Verifier-free consensus over N samples: 1-10% lower Chamfer distance.
- Online RL from geometric rewards: invalid rate drops to about 0%.

At the assembly level, agentic or solver-grounded designs with typed specs beat monolithic code generation. Execution success is not enough: the visual-semantic judge can disagree with execution and IoU.

### Cited Findings
- **CADSmith (arXiv 2603.26512, Mar 2026):**
  - Five agents: Planner (emits a JSON spec with bounding box, holes and constraints), Coder (CadQuery with RAG over 155 API entries, 28 examples and 25 error-fix patterns), Executor (sandboxed, 60 s timeout), Validator (Claude Opus VLM given a 3-view render plus OCCT kernel metrics) and Refiner. An inner loop allows up to 3 execution retries and an outer loop up to 5 geometric refinements.
  - Results on 100 hand-written reference tasks:

    | Configuration | Exec | Mean CD | Median IoU |
    |---|---|---|---|
    | Zero-shot | 95% | 28.37 | 0.81 |
    | Loop without vision | 99% | 18.19 | 0.956 |
    | Full loop with vision | 100% | 0.74 | 0.963 |

  - Vision mattered mainly for complex tier-3 parts: mean CD 49.68 without vision vs 1.42 with it. On simple parts, the no-vision loop performed about the same.
  - 88% of tasks converged on the first iteration.
  - Failure mode: a quadcopter frame scored IoU 0.985 but had gaps between arms and hub that neither the metrics nor the VLM judge caught. — [CADSmith](https://arxiv.org/html/2603.26512v1)
- **CADCodeVerify (ICLR 2025):**
  - The VLM generates yes/no/unclear validation questions about the renders. The "no" and "unclear" answers become feedback for revising the code.
  - Reported gain for GPT-4: 7.30% lower point-cloud distance, plus improved compile rate. It introduced CADPrompt (200 prompts). — [CADCodeVerify ICLR 2025](https://proceedings.iclr.cc/paper_files/paper/2025/file/81a934cd364e18ea6fdeaf57a93c17d4-Paper-Conference.pdf), [arXiv 2410.05340](https://arxiv.org/pdf/2410.05340)
- **Query2CAD:** GPT-4 plus FreeCAD with BLIP-2 captioning for self-refinement, later with human-in-the-loop feedback. A critique is that BLIP-2 features lose the geometric precision needed to fix dimensions. — [Query2CAD GitHub](https://github.com/akshay140601/Query2CAD); critique via [CADSmith](https://arxiv.org/html/2603.26512v1)
- **Test-Time Scaling via Verifier-Free Consensus (arXiv 2608.09706):** sample N programs, compile them, and select the candidate that agrees most with the others, either geometrically or topologically.
  - Geometric consensus beat a SOTA method's verifier on all three geometric metrics, and topological consensus matched it on topology.
  - Against random selection, it gave 1-10% lower Chamfer distance across all tested LLMs and prompts. — [Consensus TTS](https://arxiv.org/abs/2608.09706)
- **Online RL from geometric reward:**
  - CAD-Coder (GRPO with a Chamfer reward): IR fell from 5.3% to 1.45%. — [CAD-Coder](https://arxiv.org/html/2505.19713)
  - cadrille (Dr.CPPO): IR fell to 0.0-0.2% with +3-6 IoU points. — [cadrille](https://arxiv.org/html/2505.22914v1)
- **Embodied CAD (arXiv 2606.31252):**
  - The agent picks actions from a stratified L0-L4 skill library. Each action becomes typed geometric operations executed by an exact kernel, with revision from solver feedback.
  - Solver rewards are used for SFT warm-up and GRPO. Tasks are mechanical, industrial-equipment and mold assemblies.
  - All strong-planner workflows executed, but a gap remains between valid tool calls and exact long-horizon policy. — [Embodied CAD](https://arxiv.org/abs/2606.31252)
- **ASSEMCAD (arXiv 2607.05123):** builds an "Assembly Specification" with typed parts, geometry-backed ports, executable mates and engineering axioms. A port/mate library executes deterministically and checks interfaces against the B-rep, and parametric component factories are synthesized on demand. It "substantially improves" assembly preservation and physical validity over code-centric baselines on AssemBench (no numbers in the abstract). — [ASSEMCAD](https://arxiv.org/abs/2607.05123)
- **MUSE (arXiv 2605.28579):**
  - Benchmarks editable B-rep assemblies against a Design Specification (assembly graph, parameter ranges, manufacturing plan). Scoring has three stages (code, geometry, design intent) with a rubric VLM judge validated against humans.
  - It finds a failure cascade from executable code to valid geometry to engineering-ready design. Its answer to whether LLMs produce working designs is "largely no." — [MUSE](https://arxiv.org/pdf/2605.28579), [alphaXiv](https://www.alphaxiv.org/abs/2605.28579)
- **RealCADBench:** Codex+GPT-5.5 as an agent improves executability and IoU on assemblies over plain GPT-5.5, but has a lower semantic judge score. — [RealCADBench](https://arxiv.org/abs/2609.03773)
- **Other 2026 agent papers seen, not read:** IterCAD (iterative program repair from orthographic views, arXiv 2608.24020), RA-CAD (learned post-execution critique, 2608.05714), ArtisanCAD (industrial-level CAD agent with expert knowledge distillation, 2607.05750), CADENA (stepwise CAD reverse engineering, 2608.00799). — [IterCAD](https://arxiv.org/pdf/2608.24020), [RA-CAD](https://arxiv.org/pdf/2608.05714), [ArtisanCAD](https://arxiv.org/pdf/2607.05750), [CADENA](https://arxiv.org/pdf/2608.00799)

### Inferences
- For whole products like a bicycle, the evidence favours a hierarchical spec-first architecture:
  - a product spec (part graph, ports and mates, parameter ranges);
  - per-part typed-IR generation;
  - deterministic mate solving;
  - kernel checks (validity, interference, contact gaps);
  - a VLM render check;
  - optional N-sample consensus.

  This combines ASSEMCAD, Embodied CAD, CADSmith and consensus TTS.
- Programmatic geometric checks should cover what VLMs miss, such as contact gaps and interference (see the CADSmith quadcopter case).

### Gaps
- No primary numeric results were read for ASSEMCAD, Embodied CAD, ToolCAD, IterCAD, RA-CAD or ArtisanCAD.
- I found no released code links in the abstracts of most 2026 agent papers. MUSE says it has a project site with code and a leaderboard.

## 4. Domain languages: KCL, FeatureScript, OpenSCAD, build123d vs CadQuery

### Takeaway
CadQuery dominates the research literature as the LLM target: most datasets, RL work and benchmarks (BenchCAD, CAD-Recode, cadrille, CAD-Coder, CADSmith) use it. FreeCAD Python is used by RealCADBench and Query2CAD. Zoo markets KCL plus its own kernel as LLM-friendly but publishes no comparable benchmark numbers. build123d has little dedicated LLM research, and one 2026 paper flags its operator-overloading and context-manager style as harder for LLMs.

### Cited Findings
- Zoo's Zookeeper is an LLM agent in Zoo Design Studio that writes KCL and returns parametric solids with an editable feature tree. Zoo claims its readable language and custom kernel suit LLMs better than legacy kernels. — [Zoo Zookeeper docs](https://zoo.dev/docs/zoo-design-studio/zookeeper), [Leo AI review](https://www.getleo.ai/blog/zoo-text-to-cad-review)
- The ML-ephant API takes a prompt and returns a CAD file, with Python, TypeScript, Go and Rust clients. Zoo was formerly KittyCAD and launched Text-to-CAD in Jan 2024. — [Zoo ML API](https://zoo.dev/machine-learning-api), [PR Newswire 2024](https://www.prnewswire.com/news-releases/kittycad-announces-zoo-launches-new-machine-learning-api-302026607.html)
- CADDesigner says build123d's symbolic operators and context managers can hinder LLM generation, and that existing SDKs were not designed for LLMs. — [CADDesigner](https://arxiv.org/html/2508.01031v5)
- CADFS (arXiv 2605.01925) is a "big CAD program dataset and framework" for LLMs. Seen in search only; the name suggests FeatureScript but this was not verified. — [CADFS](https://arxiv.org/pdf/2605.01925)

### Inferences
- If Shilpa keeps the typed IR as the LLM-facing layer, build123d's LLM-unfriendliness matters less, because the LLM never writes build123d directly. This is the same argument CADIR makes.
- The CadQuery-trained open models (cadrille, CAD-Recode) are non-commercial or of unclear licence, so they are not drop-in for a commercial product.

### Gaps
- I found no quantitative LLM benchmark for KCL, FeatureScript or OpenSCAD vs CadQuery.
- Zoo accuracy numbers were not found. Zoo pages may be stale.

## 5. Failure modes as complexity grows (quantitative)

### Takeaway
Failures cascade in a consistent order: execution, then geometric validity, then fine-feature fidelity, then design intent and assemblability. Execution rates mislead. Advanced operations get silently downgraded to extrudes. Multi-part output gets the part count and placement wrong.

### Cited Findings
- **Zero-shot invalid rates on CAD-Coder's test set:** GPT-4o 93%, Claude-3.7-Sonnet 47%, vs 1.45% after SFT + CoT + GRPO. — [CAD-Coder](https://arxiv.org/html/2505.19713)
- **Execution success for raw open-source LLMs** is about 53%, rising to 85% with auto-fixing. — [Text-to-CadQuery](https://arxiv.org/pdf/2505.06507)
- **The invalid rate rises with data complexity.** For cadrille point-cloud SFT, IR is 2.1% on DeepCAD, 2.8% on Fusion360 and 5.9% on CC3D, with IoU falling from 87 to 80 to 62. — [cadrille](https://arxiv.org/html/2505.22914v1)
- **Frontier models on industrial intents (RealCADBench):** 19-44% non-executable, Solid IoU at most 0.54, Surface IoU at most 0.22. Failures include missing fine structures, lost part identity and wrong assembly placement. — [RealCADBench](https://arxiv.org/abs/2609.03773)
- **Substitution of advanced operations:** sweep, loft and twist-extrude are replaced by sketch-extrude, and design parameters are misread. — [BenchCAD](https://arxiv.org/abs/2605.10865)
- **Assemblies:** models get neither part geometry nor part count right. — [P3D-Bench](https://arxiv.org/abs/2606.11152); and MUSE finds a cascade from code to geometry to engineering-ready design, with low success on fine-grained engineering criteria. — [MUSE](https://arxiv.org/pdf/2605.28579)
- **Silent geometric errors:** a high-IoU result with arm-hub gaps passed both the metric and the VLM judge. — [CADSmith](https://arxiv.org/html/2603.26512v1)
- **Fragile tails without verification:** CADSmith's zero-shot mean CD of 28.37 was driven by a few catastrophic mismatches. — [CADSmith](https://arxiv.org/html/2603.26512v1)

### Inferences
- Shilpa's eval should add these, because they are where 2026 benchmarks show collapse:
  - tasks with sweep, loft, shell or helix (BenchCAD-style families);
  - assembly tasks scored on part count, mates and interference;
  - a semantic judge alongside execution and IoU.
- BenchCAD, RealCADBench, MUSE and P3D-Bench are candidate external evals, but their data licences need checking.

### Gaps
- I found no quantitative data on hallucinated dimensions specifically (for example, the percentage of parameters off-spec).
- I found no quantitative data on sheet-metal or freeform-surface generation by LLMs. No 2026 paper found targets sheet metal directly.
- Licences for the BenchCAD, RealCADBench and P3D-Bench datasets were not stated on their abstract pages.
