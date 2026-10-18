# Benchmarks, Datasets, Metrics and Maturity Ladders for AI CAD Generation (as of Oct 2026)

Scope note: research done 2026-10-18 with about 20 search/fetch calls. Primary sources were arXiv HTML pages, Hugging Face dataset cards and GitHub licence files. Where a number came only from a third-party paper or from memory, it is flagged. Several 2026 benchmarks (Text2CAD-Bench, RealCADBench, CADEngBench) have not yet released code or data publicly, according to their papers.

## Q1. Datasets and benchmarks: what each measures, size, levels, licence

### Takeaway
Since mid-2026 the field has moved away from reconstruction datasets that use Chamfer distance and IoU (DeepCAD, Fusion 360, ABC). The newer benchmarks are graded by requirements: test-driven checks (CADTestBench), funnel-style manufacturability and assembly checks (MUSE), engineering, edit and FEA ladders (CADEngBench), real industrial intents (RealCADBench) and long-horizon GUI agent tasks (CADWorld). Most of the big training corpora are licensed for non-commercial use only. The 2026 benchmark papers themselves are mostly CC BY 4.0, but the licence of the benchmark data needs checking separately.

### Cited Findings

**Foundational corpora (training and reconstruction)**
- ABC: 1M CAD models from Onshape, released under the MIT licence. Copyright in each model stays with its creator, and the dataset defers to Onshape Terms of Use section 1.g.ii. Commercial training rights are therefore unclear — [NYU archive record](https://archive.nyu.edu/handle/2451/44368); [Onshape terms](https://www.onshape.com/legal/terms-of-use#your_content)
- DeepCAD: sketch-and-extrude command sequences, reported as MIT licence in its official repository (as cited by CADmium) — [CADmium arXiv 2507.09792](https://arxiv.org/pdf/2507.09792)
- Fusion 360 Gallery (reconstruction, segmentation, assembly): custom Autodesk licence allowing use "only for non-commercial research purposes", with no redistribution of the full dataset. One paper describes it as CC BY-NC 4.0, which conflicts with Autodesk's LICENSE.md; treat the LICENSE.md as authoritative — [Autodesk LICENSE.md](https://github.com/AutodeskAILab/Fusion360GalleryDataset/blob/master/LICENSE.md); [HF mirror](https://huggingface.co/datasets/AI4Manufacturing/fusion360_reconstruction)
- Text2CAD (NeurIPS 2024): text annotations on DeepCAD models at four levels per model: L0 abstract, L1 beginner, L2 intermediate, L3 expert. v1.1 adds VLM-generated descriptions. Licence is **CC BY-NC-SA 4.0** with gated access; full storage is 605 GB — [HF dataset card](https://huggingface.co/datasets/SadilKhan/Text2CAD); [paper arXiv 2409.17106](https://arxiv.org/pdf/2409.17106)
- CAD-Recode v1.5: about 1M synthetic CadQuery programs plus about 1k validation, for point cloud to CAD code. Licence **CC BY-NC 4.0** — [HF card](https://huggingface.co/datasets/filapro/cad-recode-v1.5); [paper arXiv 2412.14042](https://arxiv.org/pdf/2412.14042)
- Omni-CAD (CAD-MLLM): about 453K models with text, multi-view images, point clouds and command sequences, split 425,726 train / 27,494 eval. Licence not found — [arXiv 2411.04954](https://arxiv.org/html/2411.04954v3)
- CADPrompt: 200 expert-written natural-language prompts for DeepCAD objects, introduced with CADCodeVerify. It is the base for CADTestBench — [CADmium](https://arxiv.org/pdf/2507.09792); [CADTests](https://arxiv.org/html/2605.07807v1)

**2026 requirement-graded benchmarks (most relevant to Shilpa)**
- **CADTestBench** (Mallis et al., NeurIPS 2026 poster):
  - Built from 200 CADPrompt samples, each with abstract and detailed prompts.
  - Has 5,937 executable CADTests (about 15 per sample) and 1,275 mutants.
  - Test categories: solid/shell validity, topology, geometric types, dimensions/ratios, volume, spatial arrangement.
  - Tests were written by Claude Sonnet 4.6 and refined over 4 rounds against reference models, transformed variants and mutants. Mutation score exceeds 90%.
  - Code: [GitHub](https://github.com/dimitrismallis/CADTestBench); data: [HF](https://huggingface.co/datasets/dimitrismallis/CADTestBench); paper is CC BY 4.0. Data licence not verified.
  - Source: [arXiv 2605.07807](https://arxiv.org/html/2605.07807v1)
- **Text2CAD-Bench** (Wang et al., May 2026):
  - 600 human-curated examples, each with geometric and sequence-style prompts (1,200 prompts total).
  - L1 (200): primitives and spatial relations.
  - L2 (200): booleans and standard features such as fillets.
  - L3 (100): sweep, loft, shell and freeform.
  - L4 (100): real-world single-solid products across industrial, consumer, medical, architectural and educational domains. L4 is scored by a VLM because there is no ground truth.
  - Paper is CC BY 4.0. Code and leaderboard are "to be released after acceptance".
  - Source: [arXiv 2605.18430](https://arxiv.org/html/2605.18430v1)
- **MUSE** (May 2026): 106 design instances (chairs, tables, card holders and similar) with specs plus Top/Front/Right/Iso drawings.
  - Manufacturing processes: CNC is the largest. Materials: timber and PLA are the most common. Connections: one-piece, interlocking, nailing, snap-fit.
  - The funnel has three stages:
    1. Code check: CadQuery executes and exports STEP.
    2. Geometry check: watertight, manifold, self-intersection free, overlap free.
    3. VLM-judged design intent across 6 binary criteria: Functional, Robust, Manufacturable, Well-toleranced, Assembly-ready, Connectable.
  - Paper is CC BY 4.0. Leaderboard, data and code are on the project site.
  - Sources: [arXiv 2605.28579v2](https://arxiv.org/html/2605.28579v2); [site](https://dong7313.github.io/muse-benchmark/)
- **CADEngBench** (MBZUAI, Aug 2026):
  - P track: 300 parts, each with a zero-to-CAD task and a functional edit task (600 tasks); 164 parts also have a CalculiX FEA test.
  - Ladder: L0 executable solid, L1 engineering/DFM requirements, L2-Z parametric integrity under parameter change, L2-E functional edit with preservation, L3 FEA agreement with the reference.
  - A track: 150 Fusion 360 body pairs. Tasks are B-Rep entity retrieval, joint type, joint frame and motion check (Entity@1, Typed@k, MRR, end-to-end).
  - No code link found. Licence is arXiv non-exclusive.
  - Source: [arXiv 2608.09296](https://arxiv.org/html/2608.09296v1)
- **RealCADBench** (Sep 2026):
  - 12,632 tasks across 19 factory-automation categories, drawn from an industrial marketplace and purchased industrial data. The reported slice is 1,745 part tasks plus the 25-task RCB-Assm25 assembly study.
  - Four input regimes: text, 2D engineering drawings, real photos, renders.
  - Output is FreeCAD Python. Metrics: Exec, Solid IoU, Surface IoU, Judge (Kimi K2.6, 0–100) and Profile Average.
  - The authors say they "will publicly release" it. Licence not verified.
  - Source: [arXiv 2609.03773](https://arxiv.org/html/2609.03773v1)
- **CADWorld** (Sep 2026): a computer-use benchmark of 200 FreeCAD GUI tasks across 11 workflow categories, covering 183 knowledge points.
  - Up to 100 GUI steps per task. Success means all evaluator checks pass on the saved file.
  - Includes CAM, FEM and TechDraw tasks. Paper is CC BY 4.0.
  - Sources: [arXiv 2609.16251](https://arxiv.org/html/2609.16251v1); [cad-world.github.io](https://cad-world.github.io)
- Other 2026 benchmarks seen only in reference lists, not inspected: BenchCAD (arXiv 2605.10865), CadBench, a multimodal CAD program benchmark (arXiv [2605.10873](https://arxiv.org/html/2605.10873v1)), and CADFS, a big CAD program dataset (CVPR 2026) — [CVF](https://openaccess.thecvf.com/content/CVPR2026/papers/Pyatov_CADFS_A_Big_CAD_Program_Dataset_and_Framework_for_Computer-Aided_CVPR_2026_paper.pdf). Epoch AI hosts a "CadEval" page with metrics for render success, Chamfer/Hausdorff distance and volume, but it lists no task count or scores — [Epoch](https://epoch.ai/benchmarks/cad-eval)

**Drawing-to-CAD**
- TriView2CAD (from CReFT-CAD): 200K synthetic plus 3K real three-view sets, with dimension labels tied one-to-one to primitives — [arXiv 2506.00568](https://arxiv.org/html/2506.00568v2)
- OmniMech (Aug 2026): more than 251K dimensioned and toleranced orthographic drawings paired with STEP/B-rep. Four tasks: program synthesis from drawings, diagram-to-3D, reasoning over dimension/tolerance annotations, and agentic tool use. VLMs are reported to "struggle" with executable synthesis and dimension/tolerance enforcement — [alphaxiv 2608.05539](https://www.alphaxiv.org/abs/2608.05539)
- Drawing2CAD: 161,407 models with FreeCAD TechDraw SVG drawings (3 orthographic views plus isometric) — [arXiv 2508.18733](https://arxiv.org/pdf/2508.18733). Ortho2CAD is a pythonOCC first-angle dimensioned-drawing generator — [arXiv 2607.08891](https://arxiv.org/pdf/2607.08891). OrthoCAD-322K is a DXF-to-3D retrieval dataset — [IITM PDF](https://ed.iitm.ac.in/~raman/agcl/OrthoCAD_322K_3DoR.pdf)
- RealCADBench includes a 2D engineering-drawing input regime built from industrial parts (see above).

**Sheet metal**
- BenDFM (Ghent, Mar 2026): 20,000 synthetic bending parts, both manufacturable and not, folded and unfolded, with labels for collision, unfolding overlap and complexity. Labels come from a PythonOCC bending simulator. It is a DFM classification benchmark, not a generation benchmark. A later paper cites 14,000 STEP files, so the size is unconfirmed — [arXiv 2603.13102](https://arxiv.org/html/2603.13102v1); [arXiv 2605.12266](https://arxiv.org/pdf/2605.12266)
- KUL-bend: 503 designs with shop-floor bending times. Proprietary — [arXiv 2605.12266](https://arxiv.org/pdf/2605.12266)

### Inferences
- For commercial training, the large corpora Text2CAD (NC-SA), CAD-Recode (NC), Fusion 360 (non-commercial research) and probably ABC (creator copyright) all carry restrictions. Using them for evaluation only is lower risk, but it still needs legal review. Shilpa should prefer self-generated or licence-clean evaluation data, and treat external benchmarks as reported, comparable numbers rather than training data.
- No public text-to-assembly benchmark covers whole multi-part products (for example a bicycle) with kinematic mates. MUSE (furniture-scale, VLM-judged assemblability), CADEngBench-A (pairwise joints) and RCB-Assm25 (25 tasks) are the nearest.
- No public sheet-metal generation benchmark was found. BenDFM could serve as an automated DFM oracle for Shilpa's sheet-metal outputs.

### Gaps
- Licences for the CADTestBench data, Omni-CAD, MUSE data, OmniMech and TriView2CAD were not verified.
- Exact Fusion 360 Gallery Assembly/Joint dataset sizes were not verified in this session. From memory, about 8,251 assemblies (Willis et al., JoinABLe, CVPR 2022); treat this as unverified.
- BenchCAD and CadBench content was not inspected.

## Q2. Metrics and their weaknesses

### Takeaway
Executability and Chamfer/IoU are necessary but correlate poorly with whether the part meets the request. Executable tests (CADTests) agree much better with human judgement. VLM judges are useful for product-level intent but show only moderate agreement with humans. Assembly checks are still crude.

### Cited Findings
- Invalidity rate (IR) and executability: CADEngBench found that 1,030 of 2,400 programs executed but only 432 of those passed engineering/DFM checks. About 58% of executable outputs violated at least one requirement — [CADEngBench](https://arxiv.org/html/2608.09296v1)
- Chamfer distance and IoU:
  - They are computed only on executed samples, so a high IR can inflate apparent quality — [Text2CAD-Bench](https://arxiv.org/html/2605.18430v1)
  - They are ill-suited to ambiguous text where many valid shapes exist. In a human study (125 pairs, κ=0.54), AUC against human labels was CD 0.663, CLIP 0.665 and LVM judge 0.659, versus CADTests Requirement Score 0.928. CADTests pass/fail reached 0.938 accuracy and 0.962 F1, versus 0.474 and 0.549 for the LVM metric — [CADTests](https://arxiv.org/html/2605.07807v1)
  - The cadrille paper reports *median* CD because invalid models bias the mean — [cadrille](https://arxiv.org/pdf/2505.22914)
- Test-driven pass rate: CADTestBench reports Pass Rate (all tests pass), Requirement Score (share of requirement groups met) and IR, with invalid outputs counted as failures. The authors concede that test coverage is finite and may diverge from human judgement — [CADTests](https://arxiv.org/html/2605.07807v1)
- VLM judging:
  - MUSE judge agreement with humans: Pearson r 0.713 (Gemini 3.1 Pro), 0.659 (GPT-5.5) and 0.620 (GPT-4o) at the sub-criterion level; 0.835 and 0.826 at the instance level. The sample size is inconsistently reported (20 vs n=104) — [MUSE](https://arxiv.org/html/2605.28579v2)
  - Text2CAD-Bench L4 uses GLM-4.6V scores on a 0–10 scale. RealCADBench uses a Kimi K2.6 rubric judge on a 0–100 scale. In RealCADBench, agents raised IoU but lowered the Judge score by about 7 pp — [RealCADBench](https://arxiv.org/html/2609.03773v1)
- Manufacturability/DFM: MUSE judges Manufacturable and Well-toleranced with a VLM, and the authors note designs were not physically manufactured. CADEngBench L1 uses explicit DFM requirement checks. BenDFM provides simulator-derived sheet-metal labels — [MUSE](https://arxiv.org/html/2605.28579v2); [CADEngBench](https://arxiv.org/html/2608.09296v1); [BenDFM](https://arxiv.org/html/2603.13102v1)
- Assembly validity:
  - MUSE: "Overlap Free" is the hardest geometric check. "Connectable" checks joint feasibility but not assembly order, and "Robust" is judged qualitatively rather than by physics — [MUSE](https://arxiv.org/html/2605.28579v2)
  - CADEngBench-A: only 26.4% of correct rank-1 entity localisations also got the full joint right — [CADEngBench](https://arxiv.org/html/2608.09296v1)
- Parametric and edit robustness: CADEngBench L2-Z and L2-E show edits touching existing history (joins, cuts, multi-body) pass only 40–46% of the time, versus 247/248 for an independent body addition — [CADEngBench](https://arxiv.org/html/2608.09296v1)
- Physics: in CADEngBench, a higher rate of reaching FEA did not correlate with agreement with the reference FEA — [CADEngBench](https://arxiv.org/html/2608.09296v1)

### Inferences
- Shilpa's current oracles (exact volume, bbox, holes) are closer in spirit to CADTests than to Chamfer/IoU, which is a strength. Extending them into per-requirement test suites gives a Requirement Score and Pass Rate directly comparable with CADTestBench.
- For assemblies, the metrics Shilpa needs mostly do not exist as public benchmarks yet: interference volume, mate satisfaction, DOF count against intended mechanism, and BOM consistency. Shilpa will need to build them, following MUSE's funnel structure.

### Gaps
- No published benchmark measures DOF or kinematic correctness of generated multi-part mechanisms.

## Q3. Published best scores (2025–2026)

### Takeaway
Frontier general models lead every benchmark, and agentic or test-guided loops add 5–15 pp. Scores are still low on hard tiers:
- About 60–81% pass rate on CADTestBench (CADPrompt-level simple parts).
- At most 52% on MUSE (assemblable furniture).
- About 22–30% DFM pass on CADEngBench.
- About 12–16% end-to-end on assembly joints.
- About 17.5% on long-horizon GUI CAD, against 87% for human experts.

### Cited Findings
- **CADTestBench** (Pass Rate, detailed / abstract prompts) — [CADTests](https://arxiv.org/html/2605.07807v1):
  - CADTests+Log with Claude Sonnet 4.6: 0.625 / 0.810 (RS 0.897 / 0.962). This is the best.
  - CADTests with Claude Sonnet 4.6: 0.590 / 0.765.
  - ReAct with Claude Sonnet 4.6: 0.580 / 0.715.
  - CADTests with GPT-5.2: 0.500 / 0.720.
  - CadCodeVerify with GPT-4.1: 0.410 / 0.630.
  - Fine-tuned Text2CAD: 0.025 / 0.085.
- **Text2CAD-Bench** (best general LLM) — [Text2CAD-Bench](https://arxiv.org/html/2605.18430v1):
  - L1: CD 44.31 (GPT-5.2), IoU 0.62, IR 11.1%.
  - L2: IoU 0.50 (GPT-5.2), IR 12.8%.
  - L3: CD 70.13 (Claude 4.5 Sonnet), IoU 0.28. The text claims 70–90% L3 invalidity, which conflicts with a 12.8% table entry and may be a table error.
  - L4: lowest IR is Gemini 3 Flash at 17%; best overall VLM score is DeepSeek-V3.2 at 8.26/10.
  - Domain-specific models (Text2CAD, CADFusion) had near-zero IoU.
- **MUSE** final score — [MUSE](https://arxiv.org/html/2605.28579v2):
  - GPT-5.5: 52.36%
  - Gemini 3.1 Pro: 43.40%
  - Claude Opus 4.7: 39.47%
  - GLM-5.1: 18.87%
  - Claude 3.7 Sonnet: 12.74%
  - GPT-4o: 5.03%
  - Llama-3.1-8B: 0%
- **CADEngBench-P** (L0 / L1 / L2-E / L3 pair pass) — [CADEngBench](https://arxiv.org/html/2608.09296v1):
  - Claude Sonnet 4.5: 58.0 / 28.3 / 66.7 / 35.8
  - Gemini 3 Flash: 52.7 / 30.0 / 72.3 / 46.3
  - GPT-5.2: 41.3 / 22.0 / 70.3 / 32.8
- **CADEngBench-A** end-to-end: Gemini 3 Flash 15.8%, Claude Sonnet 4.5 12.5%, GPT-5.2 11.7%. Cross-track rank correlation ρ is 0.048, meaning no model leads everywhere — [CADEngBench](https://arxiv.org/html/2608.09296v1)
- **RealCADBench** part track (regime-balanced Profile Average) — [RealCADBench](https://arxiv.org/html/2609.03773v1):
  - Gemini 3.1 Pro Preview: 0.551 (Exec 0.88, Solid IoU 0.43)
  - GPT-5.5: 0.548 (Exec 0.93)
  - Claude Opus 4.8: 0.532
  - Assembly track (RCB-Assm25): Codex with GPT-5.5 reaches PA 0.523 and Exec 1.0, but Solid IoU is only 0.28.
- **CADWorld** — [CADWorld](https://arxiv.org/html/2609.16251v1):
  - GPT-5.4 CUA: 17.5%; Opus 4.8 CUA: 16.0%; human experts: 87.0%.
  - Every model scored 0% on CAM, FEM and TechDraw tasks.
  - A 60-task subset reports 25%, an inconsistency within the paper.
- **Point cloud to CAD reconstruction** (third-party table, CADFit arXiv 2605.01171) — [CADFit](https://arxiv.org/pdf/2605.01171):
  - DeepCAD: cadrille IoU 0.872, CD 0.020, IR 0.7%; CAD-Recode IoU 0.818.
  - Fusion 360: cadrille IoU 0.817; CAD-Recode IoU 0.761.
  - GACO-CAD reports different cadrille numbers (RL: IoU 85.99) — [GACO-CAD](https://arxiv.org/pdf/2510.17157). These numbers are unverified against the original papers.

### Inferences
- A Shilpa result of about 97% build accuracy on internal tasks is roughly comparable to Invalidity/Exec metrics, where frontier models already reach 88–100%. It says little about requirement satisfaction, which is where public scores fall to 20–60%.
- Agentic, tool-verified loops (the Shilpa approach) are the current state of the art on CADTestBench and RCB-Assm25, so reporting against these benchmarks would be credible and competitive.

### Gaps
- No public leaderboards with continuously updated scores were found for Text2CAD-Bench (URL placeholder). The MUSE leaderboard exists but was not read directly.
- Scores for the newest models (for example Claude Opus 4.8 or GPT-5.5 on CADTestBench) were not found.

## Q4. Capability levels and maturity ladders

### Takeaway
No industry-standard autonomy ladder exists for AI CAD. Usable building blocks are:
- Difficulty ladders: Text2CAD's prompt levels, Text2CAD-Bench L1–L4, and CADEngBench L0–L3.
- Vendor autonomy ladders: Cadence's L1–L5 for design agents.
- An academic maturity model for generative engineering and design automation (2026), whose content was not accessible.

### Cited Findings
- Text2CAD prompt levels: abstract, beginner, intermediate, expert. These grade the *specification* style, not geometric difficulty — [HF](https://huggingface.co/datasets/SadilKhan/Text2CAD)
- Text2CAD-Bench geometric difficulty: L1 primitives, L2 booleans and fillets, L3 sweep/loft/shell/freeform, L4 real-world products. Performance "degrades sharply" at L3 — [arXiv 2605.18430](https://arxiv.org/html/2605.18430v1)
- CADEngBench engineering-validity ladder: L0 executable, L1 DFM/requirements, L2 parametric integrity and edit, L3 physics (FEA) — [arXiv 2608.09296](https://arxiv.org/html/2608.09296v1)
- MUSE funnel: code, then geometry, then function, manufacturing and assembly intent — [arXiv 2605.28579](https://arxiv.org/html/2605.28579v2)
- Cadence "Autonomy Levels for Design Agents" (sponsored post, Sep 2026) — [SemiEngineering](https://semiengineering.com/autonomy-levels-for-design-agents-l1-to-l5-explained/):
  - L1: optimisation AI on a bounded task.
  - L2: natural language as the tool interface.
  - L3: complex reasoning with self-validation by tools.
  - L4: multi-agent workflows, where the engineer sets the goal and acceptance criteria.
  - L5: full autonomy within a defined scope, with engineers keeping signoff.
  - It sets no numeric thresholds and stresses that a level is meaningless without scope, validation method, fallback and human decision points.
- "A maturity model for automation support in Generative Engineering and Design" (Procedia CIRP, 2026) describes levels of tool support and how responsibility is split between designer and computer. The full text was blocked (403), so the level definitions are not verified — [ScienceDirect](https://www.sciencedirect.com/science/article/pii/S2212827126008693)
- Shapiro's "Five Levels" (Manual L0 to "Dark Factory" L5) for software is cited in the AI Codebase Maturity Model — [arXiv 2604.09388](https://arxiv.org/pdf/2604.09388)
- Human versus agent gap: CADWorld's 87% expert reference pass against 17.5% for the best agent gives a ready "human parity" anchor — [CADWorld](https://arxiv.org/html/2609.16251v1)

### Inferences (proposed readiness framework for Shilpa)
The ladder below combines the sources above. It is a proposal, not an external standard.
- **R1, simple prismatic parts:** IR under 2% and CADTestBench Pass Rate at least 0.80 on abstract and 0.65 on detailed prompts, which matches or beats the published best of 0.81 / 0.625. Also Text2CAD-Bench L1–L2 IoU at or above the best published (0.62 / 0.50). Internal 30 golden parts and the 60-task eval already sit here.
- **R2, advanced features and freeform:** Text2CAD-Bench L3 (sweep/loft/shell) with IR under 10% and IoU beyond 0.28. Add Shilpa-internal tests for surface continuity.
- **R3, engineering-valid and editable:** CADEngBench-P L1 (DFM) above 50%, L2-E edits above 80%, and L2-Z parametric integrity. Drawing-to-CAD on OmniMech or TriView2CAD, plus the RealCADBench drawing regime, with dimension/tolerance enforcement.
- **R4, assemblies:** MUSE final score above 60%, beating GPT-5.5's 52%, with Overlap-Free close to 100%. CADEngBench-A end-to-end well above 16%. RCB-Assm25. Plus Shilpa-built checks for interference, mate satisfaction and DOF.
- **R5, whole products and long-horizon:** no public benchmark covers this. Build an internal product suite (bicycle, enclosure, sheet-metal bracket families) with BOM, kinematics and DFM oracles. Use CADWorld-style human-expert reference pass rates, where parity with the roughly 87% expert reference is the bar.
- Report autonomy level separately from difficulty level, in the style of Cadence L2 to L4. For example: "R3 at autonomy L3 (self-verifying, engineer reviews)".

### Gaps
- No CIMdata or Gartner report defining AI-CAD maturity was found in this session. Analyst reports are typically paywalled.
- The Procedia CIRP maturity model's level definitions could not be retrieved.

## Q5. Defining "production-ready" and human evaluation protocols

### Takeaway
Published human protocols are small and academic: paired preference or pass labelling, professional-designer validation, and rubric criteria. No source found reports field metrics such as engineer acceptance rate, edit rate or time saved for AI CAD.

### Cited Findings
- CADTests human evaluation: 125 pairs with two annotators, inter-annotator κ=0.54, which signals that even humans disagree moderately on text-to-CAD correctness — [CADTests](https://arxiv.org/html/2605.07807v1)
- MUSE: annotators scored rendered views on 6 binary criteria (Functional, Robust, Manufacturable, Well-toleranced, Assembly-ready, Connectable), and professional designers validated the references. These criteria work as a ready-made design-review rubric — [MUSE](https://arxiv.org/html/2605.28579v2)
- RealCADBench: a rubric-based visual-semantic identity judge covers failure modes of "missing fine structures, loss of part identity, incorrect assembly placement" — [RealCADBench](https://arxiv.org/html/2609.03773v1)
- CADWorld uses a human expert reference pass (87%) as a calibrated ceiling — [CADWorld](https://arxiv.org/html/2609.16251v1)
- Cadence: a level label needs "workflow scope, validation method, fallback behavior, and human decision points" — [SemiEngineering](https://semiengineering.com/autonomy-levels-for-design-agents-l1-to-l5-explained/)

### Inferences
- A defensible production-readiness definition for Shilpa would combine three things:
  1. Automated oracle pass at the target R-level, at or above the human-expert reference rate.
  2. A blinded engineer review using MUSE's 6 criteria plus a GD&T/DFM checklist, reporting inter-rater κ.
  3. Field metrics: first-pass acceptance rate, median edits or minutes to accept, and time saved against a baseline.
  Targets for item 3 must be set internally, because no published benchmarks exist for them.

### Gaps
- No public data was found on engineer acceptance or edit rates for AI-generated CAD in production. No standards body (NIST, ISO) document defining AI-CAD evaluation was found in this session.
