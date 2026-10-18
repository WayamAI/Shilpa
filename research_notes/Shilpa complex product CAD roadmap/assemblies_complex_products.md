# AI for Multi-Part Assemblies and Whole Products in CAD (state as of Oct 2026)

Scope: product decomposition, assembly generation, mate/joint inference, standard parts, sheet metal/freeform, whole-product demos. Written for Shilpa (single-part typed feature IR on build123d/OCCT, FreeCAD export, gpt-5.5 planner), with "design an entire bicycle end to end" as the target request. Note: several 2026 arXiv papers below were checked only at abstract level (numbers come from abstracts/HTML pages, not reproduced).

## 1. Assembly datasets and models (Fusion 360 Gallery Assembly, JoinABLe, AutoMate, Assemble-Them-All, 2024-2026 generative assembly work)

### Takeaway
The learning-based datasets (Fusion 360 Gallery Assembly, AutoMate) and models (JoinABLe, Mates2Motion, Assemble-Them-All) date from 2021-2022. They are useful for pairwise joint/mate prediction and for assembly sequencing. The 2026 wave of "text-to-assembly" work (ArtiCAD, AssemCAD, Embodied CAD) is different: none of it trains end-to-end. All three use LLM planners that emit an explicit symbolic assembly spec (parts + connectors/ports + typed mates), then a deterministic solver/mate library places the geometry. That pattern fits directly onto Shilpa's typed IR.

### Cited Findings
**Datasets / classic learning models**
- JoinABLe (Willis et al., CVPR 2022, Autodesk Research/MIT) predicts joints between pairs of parts. It is trained on weak supervision from standard parametric CAD files with no class labels. Joint-axis prediction is framed as link prediction over a graph of B-Rep faces/edges from the two parts, and a neurally guided search finds the joint pose. — [Autodesk Research](https://www.research.autodesk.com/publications/joinable-learning-bottom-up-assembly-of-parametric-cad-joints); [CVPR paper](https://openaccess.thecvf.com/content/CVPR2022/papers/Willis_JoinABLe_Learning_Bottom-Up_Assembly_of_Parametric_CAD_Joints_CVPR_2022_paper.pdf)
- JoinABLe reached 79.53% joint-axis accuracy, against roughly 80% for humans. — [CVPR paper](https://openaccess.thecvf.com/content/CVPR2022/papers/Willis_JoinABLe_Learning_Bottom-Up_Assembly_of_Parametric_CAD_Joints_CVPR_2022_paper.pdf); [arXiv 2111.12772](https://ar5iv.labs.arxiv.org/html/2111.12772)
- The Fusion 360 Gallery Assembly dataset holds joints, contact surfaces, holes and assembly graphs from about 20k Fusion 360 designs. It is released under a **non-commercial research licence**. — [JoinABLe supplemental](https://openaccess.thecvf.com/content/CVPR2022/supplemental/Willis_JoinABLe_Learning_Bottom-Up_CVPR_2022_supplemental.pdf)
- AutoMate (Jones et al., SIGGRAPH Asia 2021, UW + Onshape) scraped 255,213 Onshape assemblies, cleaned to 92,529 unique assemblies with 541,635 unique mates. Mate mix: fastened 62.1%, revolute 12.7%, planar 11.8%. Parts ship as Parasolid + STEP, with assembly/mate metadata in Parquet. — [arXiv 2105.12238](https://arxiv.org/pdf/2105.12238); [Dryad](https://datadryad.org/dataset/doi:10.5061/dryad.2547d7wvw); [project](https://grail.cs.washington.edu/projects/automate)
- Mates2Motion builds on 125,133 Onshape assemblies from the Jones et al. data. It filters out noisy or physically implausible assemblies and learns how mates produce motion. — [arXiv 2208.01779](https://arxiv.org/pdf/2208.01779)
- Assemble Them All (Tian et al., SIGGRAPH Asia 2022, MIT CSAIL + Autodesk + Texas A&M) uses physics-based assembly-by-disassembly planning to find a feasible part order and motion paths. It handles screws and puzzles, solves 80-part assemblies in minutes, and released code and a benchmark dataset. — [arXiv 2211.03977](https://arxiv.org/pdf/2211.03977); [project](https://assembly.csail.mit.edu)
- Other assembly works cited by ArtiCAD: CADKnitter (Le et al., 2025) for complementary part generation, and a GNN-based CAD assembly recommender (Liang et al., 2024). — [ArtiCAD related work](https://arxiv.org/html/2604.10992v1)

**2026 LLM text-to-assembly**
- **ArtiCAD** (Beihang/ZJU/HKU, arXiv 2604.10992, Apr 2026) is a training-free multi-agent system. A Design Agent produces parts, connectors, joints and total DOF. One Generation Agent per part writes a FreeCAD Python script and runs a generate-execute-repair loop with VLM checking. A deterministic Assembly Agent aligns connector pairs using FreeCAD's constraint solver, with no LLM in that step. A Review Agent scores the result. A rollback router classifies each error as CODE or DESIGN and re-runs only the responsible agent. — [arXiv HTML](https://arxiv.org/html/2604.10992v1)
  - ArtiCAD's connector contract is a named local frame (origin, primary axis, orthogonal reference axis, semantic label). Each joint references one connector on each of its two parts, and all attachments are fixed **before** geometry is generated. Assemblies are restricted to an acyclic kinematic tree rooted at a grounded part, with joint types Fixed/Revolute/Slider/Cylindrical/Ball. **Closed loops (four-bar, scissor) are not supported.** Output is FreeCAD assemblies plus URDF (SAPIEN/Isaac Sim). — [arXiv HTML](https://arxiv.org/html/2604.10992v1)
  - On ArtiCAD-Bench (120 tasks, VLM-judged 1-5), Gemini-3-Pro scored Geo 3.57 / Motion 3.91 with 100% success. The best single-VLM baseline scored 3.31 / 3.67 with 98.3% success. Ablation: predicting relationships late, rather than first, cut success to 89.2%. Removing rollback cut it to 95.0%. Judge agreement is only moderate (Krippendorff α 0.58-0.64). No code link; project page articad.github.io. — [arXiv HTML](https://arxiv.org/html/2604.10992v1)
- **AssemCAD** (arXiv 2607.05123, Jul 2026, Shanghai AI Lab authors incl. Botian Shi) argues that direct CAD-code generation fails to produce valid, reusable assemblies. It first builds an "Assembly Specification": typed parts, geometry-backed ports, executable mates, and engineering axioms tied to each relation. A port/mate CAD library executes the mates as deterministic transforms and checks the declared interfaces against B-Rep geometry. It synthesises parametric "component factories" on demand for both standard parts and open-world parts. It is evaluated on AssemBench and reports improved assembly preservation and physical validity over code-centric baselines across model backbones (no numbers in the abstract). No code link found. — [arXiv 2607.05123](https://arxiv.org/abs/2607.05123)
- **Embodied CAD** (arXiv 2606.31252, Jun 2026) is an agent that builds parametric B-Rep assemblies step by step rather than as one script. It picks actions from a layered L0-L4 CAD skill library and executes each in a CAD backend. Solver feedback drives planning and repair, and is also used as a reward for SFT warm-up and GRPO refinement. Benchmarks cover mechanical, industrial-equipment and mold assembly tasks. The authors report a remaining gap between valid tool calls and exact long-horizon policy. No code link found. — [arXiv 2606.31252](https://arxiv.org/abs/2606.31252)
- STEP-LLM (arXiv 2601.12641) generates STEP directly from text. NURBGen (arXiv 2511.06194, AAAI 2026) generates NURBS-based CAD from text. Both are single-part. — [STEP-LLM](https://arxiv.org/pdf/2601.12641); [NURBGen](https://arxiv.org/html/2511.06194v2)

### Inferences
- The field has converged on one pattern: (1) the LLM produces a symbolic assembly graph with interfaces declared first, (2) parts are generated independently against those interfaces, (3) a deterministic solver places them, (4) a verifier/rollback loop repairs failures. ArtiCAD's ablation (89.2% vs 100% success) is direct evidence that declaring interfaces before geometry matters.
- The licensing of the classic datasets (Fusion 360 Gallery: non-commercial) limits their use for training a commercial Shilpa model. They remain usable for research benchmarking, and AutoMate mate statistics are useful priors: about 62% of real mates are fastened.
- None of the 2026 systems publishes code, so Shilpa would implement the pattern itself rather than adopt a library.

### Gaps
- I could not open full PDFs for AssemCAD and Embodied CAD, so their numeric results and the details of AssemBench are unknown.
- I found no public SolidWorks assembly dataset of comparable scale. The AutoMate GitHub/Dryad licence terms were not checked.
- There is no confirmed evidence of a learned (non-LLM) model generating full multi-part assemblies with mates at product scale.

## 2. Hierarchical decomposition (BOM / product structure, skeleton models, interfaces, multi-agent CAD planners)

### Takeaway
Published LLM-CAD systems decompose at one level only: product, then parts plus connectors. Multi-level subsystem hierarchies, skeleton/top-down master models and BOM generation are absent from the AI literature I found. Shilpa would have to build them from established CAD practice.

### Cited Findings
- ArtiCAD's Design Agent outputs the full plan (parts, connectors, joints, DOF) before any geometry. It derives symmetric or repeated parts as copies of a source part instead of generating them again. — [arXiv HTML](https://arxiv.org/html/2604.10992v1)
- AssemCAD separates spec from geometry: the typed parts, ports and mates are explicit and each relation is tied to an engineering axiom, which makes the spec "interpretable and verifiable." — [arXiv 2607.05123](https://arxiv.org/abs/2607.05123)
- "From Idea to CAD" (Ocker et al., Honda Research Institute EU, arXiv 2503.04417, Mar 2025) uses requirements-engineering, CAD-engineering and vision-QA agents in a V-model-inspired workflow, with iterative validation with the user. Its stated limitation is weak VLM spatial reasoning. — [arXiv 2503.04417](https://arxiv.org/html/2503.04417v1)
- CADSmith (arXiv 2603.26512) splits single-part generation into Planner/Coder/Executor/Validator roles. An MDO agent paper (arXiv 2511.17511) applies divide-and-conquer to scripts for complex mechanical structures, on the grounds that a single LLM pass struggles with them. — [CADSmith](https://arxiv.org/html/2603.26512v1); [MDO agent](https://arxiv.org/pdf/2511.17511)
- Embodied CAD uses a stratified L0-L4 skill library (primitive to higher-level operations) as its decomposition device. — [arXiv 2606.31252](https://arxiv.org/abs/2606.31252)
- Large LLM-for-CAD survey: [arXiv 2505.08137](https://arxiv.org/html/2505.08137v1)
- FreeCAD 1.0's Assembly workbench "currently supports a bottom-up design approach." It produces parametric BOMs and exploded views that can be placed on TechDraw pages. — [LibreArts FreeCAD 1.0 review](https://librearts.org/2024/11/freecad-1-0/)

### Inferences
- Recommended architecture for Shilpa (inferred from the papers above plus standard top-down CAD practice):
  1. A **Product spec / requirements** layer: rider height, use case, materials, standards.
  2. A **Skeleton / master layout**: for a bicycle, a parametric frame geometry with points and axes for BB, head tube, dropouts and wheel axles, from stack/reach/angles. Every part references this layout, never another part directly.
  3. A **Product tree / BOM**: subsystems (frame, fork, wheels, drivetrain, cockpit, brakes, saddle/seatpost), each node tagged make vs buy.
  4. **Interface contracts** per edge: connector frames plus typed mates plus a dimension contract, such as 1-1/8" steerer, 68 mm BSA BB shell, 100x9 or 12x142 axle, 27.2 mm seatpost.
  5. Per-part generation through the existing single-part IR.
  6. Deterministic assembly solve, followed by interference/DOF checks and rollback.
- The skeleton approach also sidesteps ArtiCAD's closed-loop limitation for frames: the bike frame is a structural loop, but it is modelled as one weldment part on a skeleton, not as mated members.
- The BikeBench result (Section 6), where hybrid generation plus optimisation beat pure LLMs, suggests the LLM should pick parameters and topology while a numeric optimiser or rule checker refines the skeleton values.

### Gaps
- I found no AI paper that generates multi-level BOMs or uses skeleton models explicitly.
- I found no 2024-2026 paper on LLM-generated BOMs linked to CAD. This may exist in PLM vendor marketing, but it was not verified.

## 3. Mates and constraints (Onshape / FreeCAD Assembly + Ondsel solver / SolidWorks; open solvers; kinematics; interference)

### Takeaway
In all major CAD systems, a mate is "two local coordinate frames plus a behaviour type". The open-source path for Shilpa is the FreeCAD 1.x Assembly workbench (Ondsel solver) for kinematic joints, with build123d `Joint`s used for one-shot placement. Interference and clearance checks must come from Shilpa's own OCCT boolean/distance passes, because I found no documented interference tool in the FreeCAD Assembly workbench.

### Cited Findings
- **Onshape** mate types: fastened, revolute, slider, planar, cylindrical, pin slot, ball, parallel. A mate connector is a location on a face or edge that also acts as a coordinate system with its own x/y/z axes, and axis orientation matters for some mates. — [Onshape Help: Mate Connector](https://cad.onshape.com/help/Content/mateconnector.htm); [Assembly mate connector](https://cad.onshape.com/help/Content/Assembly/assembly_mate_connector.htm)
- The Onshape API feature list returns mate connectors as their construction recipe rather than resolved poses, and users report difficulty finding which parts a connector joins. — [Onshape forum](https://forum.onshape.com/discussion/31575/retrieve-mate-connector-data-host-part-and-entity-by-id)
- **FreeCAD 1.0** ships a built-in Assembly workbench written by Ondsel, using the open-source Ondsel solver. Workflow: insert parts as links, ground one part, add joints with offsets and limits, then drag to test motion. — [FreeCAD wiki](https://wiki.freecad.org/Assembly_Workbench/zh-cn); [LibreArts](https://librearts.org/2024/11/freecad-1-0/)
- Assembly workbench joint types (per the Ondsel handbook): fixed, revolute, cylindrical, slider, ball, rack and pinion, screw, gears, belt, angle, parallel, perpendicular. Motion is tested by dragging parts within the joint DOFs. — [Ondsel handbook](https://ondsel.com/handbook/Operation/freecad-contributions); [Revolute joint wiki](https://wiki.freecad.org/Assembly_CreateJointRevolute/en)
- Ondsel's prerelease post warned of "very 'fresh' code. Bugs are a certainty." One wiki version lists a Simulation tool as added in 1.1. — [Ondsel blog](https://ondsel.com/blog/assembly-wb-prerelease/); [FreeCAD wiki](https://wiki.freecad.org/Assembly_Workbench/ru)
- **build123d joints** come in compatible pairs. `connect_to()` only repositions a part once and does not bind it. Relative locations are kept by placing parts in an Assembly (a Compound tree). Licence: Apache-2.0. — [build123d joints docs](https://build123d.readthedocs.io/en/latest/joints.html); [joints source](https://build123d.readthedocs.io/en/stable/_modules/joints.html)
- ArtiCAD uses FreeCAD's constraint solver as the deterministic assembly step and computes total DOF as the sum of per-joint DOF (Fixed 0, Revolute/Slider 1, Cylindrical 2, Ball 3). It exports URDF for physics simulation. — [arXiv HTML](https://arxiv.org/html/2604.10992v1)
- AssemCAD checks declared ports and mates against concrete B-Rep geometric evidence after execution. — [arXiv 2607.05123](https://arxiv.org/abs/2607.05123)

### Inferences
- A mate IR for Shilpa could be `{part_a.connector, part_b.connector, type ∈ {fixed, revolute, slider, cylindrical, ball, planar, screw, gear/belt couplers}, offsets, limits}`. This maps 1:1 to build123d `RigidJoint`/`RevoluteJoint`/`LinearJoint`/`CylindricalJoint`/`BallJoint` for placement, and to FreeCAD Assembly joints for export and motion, avoiding Onshape's opaque API representation.
- Recommended checks:
  - Pairwise interference via an OCCT boolean common volume, with a tolerance to allow intended press fits and threads.
  - Clearance via minimum distance (BRepExtrema).
  - DOF count against intent.
  - Swept-motion interference by sampling joint ranges, for example steering lock and crank rotation against the chainstay/heel.
  - Optional URDF export for physics checks.
- Using the FreeCAD solver headless from Shilpa's pipeline is feasible (ArtiCAD does it), but Shilpa is build123d-native, so placement through build123d joints plus a FreeCAD export with joints, for user editing, is the lower-risk path.

### Gaps
- I did not verify the Ondsel solver's licence (believed LGPL) or its maintenance status since Ondsel the company wound down. This should be checked on GitHub (FreeCAD/OndselSolver).
- SolidWorks mate taxonomy was not fetched; it is reported to cover standard, advanced and mechanical mates, but this was not verified here.
- No source confirmed a built-in interference-detection command in the FreeCAD 1.x Assembly workbench.
- Other open solvers (SolveSpace's libslvs, planegcs) were not researched in this pass.

## 4. Standard / purchased parts (bd_warehouse, cq_warehouse, FreeCAD Fasteners, catalogs; how AI uses them)

### Takeaway
There are permissive, Python-native parametric libraries for fasteners, bearings, flanges and pipes that fit build123d directly. AI research uses standard parts as code-level "component factories" rather than querying online catalogs. I found no evidence of LLM agents pulling TraceParts or McMaster models through APIs in published work.

### Cited Findings
- **bd_warehouse** (build123d ecosystem, Apache-2.0) offers fasteners (nuts, screws, washers, custom holes), flanges and pipes, and can be combined with build123d joints, for example flanges jointed onto a curved pipe. — [bd_warehouse docs](https://bd-warehouse.readthedocs.io/en/stable/_sources/index.rst.txt); [build123d external libs](https://build123d-ja.readthedocs.io/ja/latest/external.html)
- **cq_warehouse** (CadQuery) offers parametric threaded fasteners by standard, such as iso4762 and asme_b18.3 socket-head cap screws and iso4017 hex head. Its docs carry Apache-style licence boilerplate; the LICENSE file was not checked. — [cq_warehouse fastener docs](https://cq-warehouse.readthedocs.io/en/stable/fastener.html)
- **FreeCAD Fasteners Workbench** (shaise) is an external add-on covering ISO 4762, ISO 7380-1 and others. Licence: **GPL-2**. — [FreeCAD 0.19 release notes](https://wiki.freecad.org/Translations:Release_notes_0.19/125/en); [Fasteners WB wiki](https://wiki.freecad.org/Fasteners%20Workbench)
- AssemCAD synthesises reusable parametric component factories on demand, covering both standard parts and open-world parts. — [arXiv 2607.05123](https://arxiv.org/abs/2607.05123)
- Onshape mate types and connectors apply to its standard content, but I found no API documentation specific to standard content. — [Onshape Help](https://cad.onshape.com/help/Content/mateconnector.htm)

### Inferences
- For Shilpa, a "purchased part" node in the BOM should resolve to a catalog entry: {standard, size, parametric generator (bd_warehouse/own), pre-defined named joints/connectors, supplier part numbers as metadata}. The LLM picks entries and the generator builds the geometry. This avoids having the LLM model threads or bearings itself.
- GPL-2 code (Fasteners WB) is fine to invoke inside a user's FreeCAD, but should not be vendored into a proprietary Shilpa backend. Apache-2.0 bd_warehouse is the safe default.
- Bicycle-specific purchased parts (headsets, BB cups, hubs, chainrings, cassettes, tyres, quick-release/thru-axles) are not in bd_warehouse. Shilpa would need its own parametric "interface-envelope" library keyed to bike standards (BSA/T47/PF BB, ISO 5775 rims, IS/ZS/EC headsets, hub spacing).

### Gaps
- TraceParts, 3D ContentCentral and McMaster-Carr API terms, and any AI use of them, were not researched in this pass (no sources gathered).
- The cq_warehouse licence was not confirmed from its LICENSE file.

## 5. Sheet metal, freeform surfaces, tube frames and weldments

### Takeaway
Sheet metal and unfolding are mature in FreeCAD through the external SheetMetal workbench, which handles planar walls and cylindrical bends only. I found no confirmed native sheet-metal unfold in build123d. Text-to-NURBS is still research-stage (NURBGen). A bicycle's tube frame is best handled as a weldment generated by sweeping tube profiles along skeleton lines, with mitre/coping via booleans. That is feasible today in OCCT, but I found no AI paper doing it.

### Cited Findings
- The FreeCAD SheetMetal workbench (shaise, external, installed via Addon Manager) creates and unfolds sheet-metal parts. Unfold works only on constant-thickness parts made of planar walls and cylindrical bends. It also accepts Part/PartDesign solids that meet those conditions. Bend deduction is set by K-factor or a material sheet, with K-factor looked up from a spreadsheet by radius/thickness ratio. The flat pattern exports to DXF, and bend lines must be removed before laser cutting. — [FreeCAD wiki SheetMetal](https://wiki.freecad.org/SheetMetal_Workbench); [SheetMetal Unfold](https://wiki.freecad.org/SheetMetal_Unfold); [GitHub shaise/FreeCAD_SheetMetal](https://github.com/shaise/FreeCAD_SheetMetal); [FreeCAD blog tutorial 2025](https://blog.freecad.org/2025/07/11/tutorial-getting-started-with-the-sheetmetal-workbench/)
- Across commercial CAD, unfolders handle single-axis bends well. Lofted or doubly-curved transitions often fail or yield non-developable surfaces. — [Autodesk forum](https://forums.autodesk.com/t5/inventor-forum/unable-to-flatten-plate/m-p/8863099); [BricsCAD forum](https://forum.bricsys.com/discussion/comment/52109/)
- NURBGen (arXiv 2511.06194, AAAI 2026) is described as the first framework to generate high-fidelity 3D CAD directly from text through LLM-driven NURBS. — [NURBGen](https://arxiv.org/html/2511.06194v2)
- build123d joints and bd_warehouse pipes/flanges demonstrate swept pipes with jointed end fittings. — [build123d joints docs](https://build123d.readthedocs.io/en/latest/joints.html)

### Inferences
- A tube-frame IR for Shilpa could look like this:
  - Skeleton nodes (BB, head-tube top and bottom, seat cluster, dropouts) from frame geometry parameters (stack, reach, HTA, STA, chainstay length, BB drop).
  - Members as `{start_node, end_node, profile (OD, wall, optional ovalisation/taper), material}`, built as sweeps.
  - Joints, i.e. mitres, as booleans against neighbouring tube OD.
  - Butting as internal lofts.
  - Mitre templates and cut lengths as weldment manufacturing outputs.
  This is deterministic geometry, so the LLM only chooses parameters.
- Freeform parts (saddle shell, carbon lug shapes, handlebar bends) are the highest-risk area. Swept or lofted bends of fixed-OD tube are feasible now; free NURBS shells from text are research-stage.

### Gaps
- build123d's native sheet-metal and weldment capability was not confirmed; the search returned nothing. Check build123d docs/issues and community add-ons.
- I found no AI paper that generates tube frames or weldments specifically.

## 6. Public demos / case studies of AI generating whole products (vehicles, drones, bicycles, robots)

### Takeaway
I found no credible public demo of AI generating a complete, manufacturable, multi-part CAD product such as a whole bicycle or vehicle with mates and BOM. The best assembly demos are lab-scale articulated objects (ArtiCAD) and industrial/mold assemblies (Embodied CAD). Bicycle AI work exists only at the parametric-design level (BIKED/BikeBench on BikeCAD parameters). Commercial text-to-CAD tools remain mostly single-part.

### Cited Findings
- **BIKED** (Regenwetter, Curry, Ahmed, MIT DeCoDE; J. Mech. Des. 2021): about 4,500 BikeCAD bicycle designs with assembly and component images, parameters and class labels. Raw parameters number 23,613; processing yields an ML-ready 2,395-dimensional set of 4,512 models. — [arXiv 2103.05844](https://arxiv.org/abs/2103.05844v2); [project](https://decode.mit.edu/projects/biked/)
- **BikeBench** (arXiv 2508.00830, 2025) is a benchmark for generative models with objectives and constraints: aerodynamics, ergonomics, structural mechanics and human-rated usability. It includes 10k human ratings and a large synthetic set with parametric, CAD/XML, SVG and PNG representations. Finding: **LLMs and tabular generative models trail hybrid generative + optimisation methods** on quality, constraint satisfaction and similarity. Version discrepancy: v1 says 1.4M synthetic designs, v2 says 1.6M. — [v1](https://arxiv.org/html/2508.00830v1); [v2](https://arxiv.org/html/2508.00830v2)
- ArtiCAD produces articulated FreeCAD assemblies plus URDF from text or images, with VLM-judged quality about 3.5/5 on geometry. — [arXiv HTML](https://arxiv.org/html/2604.10992v1)
- Commercial tools, per secondary sources: Zoo writes parametric solids in KCL and recommends building one feature at a time, and a 2026 roundup says it struggles with multi-component assemblies. Leo AI is described as reasoning about parts as a system for early concepts, but its free plan offers no CAD-friendly export. Backflip is mainly scan/image-to-CAD. — [CADCrowd 2026 roundup](https://www.cadcrowd.com/blog/20-tools-for-ai-cad-design-drafting-software-mcp-drawing-apps-plugins-design-in-2026/); [Neural4D comparison](https://blog.neural4d.com/comparisons/best-ai-cad-generator/); [Xometry test](https://xometry.pro/en/articles/text-to-cad-tools-test/); [ENGtechnica on Zoo](https://engtechnica.com/zoo-turns-text-prompts-into-editable-cad-parts/)
- In an independent test, Zoo passed a simple cylinder but failed a gear and a multi-port manifold. — [Xometry test](https://xometry.pro/en/articles/text-to-cad-tools-test/)
- The "AI bike frame" Instructable uses Fusion 360 generative design (topology optimisation), not an LLM, and predates the window. — [Instructables](https://www.instructables.com/AI-Generated-Bike-Frame/)
- A 2026 Nature-family paper describes an AI that wrote the software for a drone C2 platform, not the drone hardware CAD. — [npj article](https://www.nature.com/articles/s44387-026-00101-6)

### Inferences
- Feasibility assessment for Shilpa:
  - **Feasible now (engineering, not research):**
    - LLM-generated product tree/BOM plus a parametric skeleton for a known product class such as a bicycle.
    - Typed connector/mate IR, build123d joint placement and FreeCAD Assembly export.
    - Standard parts from bd_warehouse plus a custom bike-standards library.
    - Tube-frame weldment from the skeleton.
    - Static interference/clearance checks.
    - Interface-first multi-agent generation with rollback, as in ArtiCAD/AssemCAD.
  - **Feasible with effort:**
    - Kinematic checks (steering, crank, suspension) via sampled joint ranges or URDF.
    - Sheet-metal parts via FreeCAD SheetMetal.
    - Parameter optimisation loops, following the BikeBench hybrid result.
  - **Research-stage:**
    - Open-ended "any product" decomposition without class templates.
    - Closed-loop mechanisms generated by LLMs (e.g. full-suspension linkages).
    - High-quality freeform/NURBS parts from text.
    - Learned joint inference at product scale with commercial-licence data.
- Any "entire bicycle" demo Shilpa ships would likely be ahead of public demos, but it should lean on templates and standards (BikeCAD-like parameters) rather than free-form LLM generation.

### Gaps
- I found no verified vehicle, drone-airframe or robot whole-product CAD-generation case study with real output (CAD vs mesh) in 2024-2026. Searches surfaced only control-software and RL demos.
- Autodesk (Project Bernini/Assistant), Siemens NX and PTC Onshape AI assembly features were not researched in this pass.
