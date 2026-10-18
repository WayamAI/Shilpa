# Commercial Landscape: AI for Mechanical CAD (text-to-CAD, drawing/image-to-CAD, in-CAD copilots), as of Oct 2026

Research date: 2026-10-18. About 20 search/fetch calls. Source-quality warning: many "2026 comparison" pages come from competing AI-CAD vendors, notably getleo.ai (Leo AI) and blog.texocad.ai (TexoCAD). They are cited where they are useful and labeled [competitor source]. Prefer vendor docs and Engineering.com/DEVELOP3D where those exist.

---

## 1. Zoo (formerly KittyCAD): Text-to-CAD, KCL, Zoo Design Studio, Zookeeper

### Takeaway
Zoo is the most complete "code-as-CAD + AI" stack that actually ships. It has its own geometry engine, the KCL language, an open-source desktop app (Design Studio, v1 in May 2025) and a conversational agent (Zookeeper). Independent tests show it handles simple prismatic parts well. It fails on medium-complexity parametric parts such as gears and manifolds, and it is mostly scoped to single parts.

### Cited Findings
- Zoo Design Studio v1 launched on May 21, 2025. It includes primitives, sketch constraints, patterns, shell, helix, extrude/revolve, fillet/chamfer, loft, sweep and GPU-accelerated booleans. It has native apps for macOS, Windows and Linux plus a web client that supports single-file workflows only. — [Zoo blog: Design Studio v1](https://zoo.dev/blog/zoo-design-studio-v1)
- v1 "ships assemblies", but **Constraints 2.0 and Assembly Mates were still roadmap items** with an open spec. Exports: STEP, glTF, FBX, STL, PLY, OBJ. — [Zoo blog](https://zoo.dev/blog/zoo-design-studio-v1)
- Open source: the Design Studio application layer is open source at github.com/KittyCAD/modeling-app. The geometry engine is proprietary and cloud/GPU-based. Zoo names OpenNURBS and Vulkan as libraries it uses. — [Zoo blog](https://zoo.dev/blog/zoo-design-studio-v1); [GitHub KittyCAD/modeling-app](https://github.com/kittycad/modeling-app)
- Zookeeper (conversational CAD agent) creates and modifies models, uses selected faces and edges as context, and works with imported STEP/STL. Design Studio offers point-and-click, direct KCL editing and prompting as three views of the same design. — [TexoCAD, Feb 2026, updated Oct 1 2026, competitor source](https://blog.texocad.ai/posts/ai-cad-software-2026); [Zoo: Announcing Zookeeper](https://zoo.dev/blog/announcing-zookeeper)
- KCL 3.0 has been released. New projects default to it and old projects keep working without forced migration. A May 2026 sketch-mode update added sketch blocks and access to a geometric constraint solver. — [ENGtechnica on KCL 3.0](https://engtechnica.com/kcl-3-0-expands-cad-modeling-while-protecting-existing-designs/); [TexoCAD Zoo review, competitor source](https://blog.texocad.ai/posts/zoo-text-to-cad-review)
- Exported STEP carries only the resulting solid, not the KCL recipe, so parametric intent is lost when the model leaves Zoo. — [TexoCAD, competitor source](https://blog.texocad.ai/posts/ai-cad-software-2026)
- Pricing in the Zookeeper announcement: Free tier with $10/month of Zookeeper credit, then $0.50/min pay-as-you-go. Plus is $20/month (about 400 min). Pro is $99/month with unlimited Zookeeper. The API is $10 free per month, then $0.0083/s (about $0.50/min). Failed Text-to-CAD calls are not charged. — [Zoo: Announcing Zookeeper](https://zoo.dev/blog/announcing-zookeeper); [Zoo API pricing](https://docs.zoo.dev/api-pricing); [Zoo: billing for Text-to-CAD](https://zoo.dev/blog/turning-on-billing-for-text-to-cad)
- Enterprise offering: custom fine-tuned models trained on customer files. — [Zoo blog](https://zoo.dev/blog/zoo-design-studio-v1)
- **Independent test (Xometry Pro, Aug 26 2025, free tiers):** the 20 mm cylinder (OD 5, ID 3) was accurate and editable with live sliders. The 24-tooth involute gear (module 2, 20° PA, hub, bore, 6 holes) was **inaccurate**. The 150×100×50 manifold with internal channels was **not generated**. New generations overwrite the previous model. Rated 2/5 for accuracy. — [Xometry: We Tested 7 Text-to-CAD Tools](https://xometry.pro/en/articles/text-to-cad-tools-test/)
- Reviews note that Zoo cannot validate manufacturability, is scoped to single parts rather than assemblies, and has no vendor-independent accuracy benchmark (its demos are vendor evidence). — [Leo AI review, competitor source](https://www.getleo.ai/blog/zoo-text-to-cad-review); [TexoCAD review, competitor source](https://blog.texocad.ai/posts/zoo-text-to-cad-review)

### Inferences
- Zoo is the closest architectural analogue to Shilpa: an LLM writes code, a kernel evaluates it, and the result is a parametric model. Shilpa's differentiators could be (a) open, standard output (FreeCAD/SolidWorks feature trees rather than a proprietary language whose intent is lost on STEP export), (b) validation and manufacturability checks, which Zoo lacks, and (c) drawing-to-CAD.
- Capability target: Shilpa should reliably pass the "Xometry medium" class (an involute gear with hub, bore and bolt pattern) and the "high" class (a manifold block with internal channels). Zoo failed both in the 2025 test.

### Gaps
- No 2026 independent re-test of Zookeeper on complex parts was found. The status of assembly mates and Constraints 2.0 in KCL 3.0 is unverified. The Design Studio app license was not confirmed (the repo needs checking).

---

## 2. Autodesk (Fusion): Project Bernini, neural CAD, AutoConstrain, Assistant, Generative Design

### Takeaway
What has shipped is AI *assistance*: AutoConstrain (sketch dimensions and constraints, now also as "Finish with AutoConstrain" in the Sept 2026 update), automated drawings, and long-standing Generative Design (topology-style outcomes). **Neural CAD**, a foundation model that generates editable B-rep, was announced at AU 2025 as Bernini's successor. As of the latest sources it is a roadmap item, not GA.

### Cited Findings
- Project Bernini (2024) was "strictly experimental and not available for public use". — [Autodesk News](https://adsknews.autodesk.com/en/news/research-project-bernini/)
- Neural CAD was announced at AU 2025. It builds on Autodesk AI Lab and Bernini research and is described as a geometry-aware model generating editable B-rep inside Fusion and Forma. — [Tech-Clarity AU2025](https://tech-clarity.com/autodesk-au-2025/23272); [DEVELOP3D: Autodesk shows its AI hand](https://develop3d.com/cad/autodesk-shows-its-ai-hand/); [AEC Magazine on neural CAD](https://aecmag.com/opinion/neural-cad-ai-foundational-models/)
- The Fusion Roadmap 2026 lists neural CAD experiences (prompt to editable geometry) and Text-to-Command (natural-language modeling commands) as planned, under a safe-harbor note that "planned features are not promises or guarantees." — [TexoCAD summarizing the Fusion roadmap, competitor source](https://blog.texocad.ai/posts/ai-cad-software-2026)
- The September 2026 Fusion update added "Finish with AutoConstrain", which automatically applies sketch constraints when a sketch is finished and runs in the background. — [Autodesk Fusion blog, Sept 2026 update](https://www.autodesk.com/products/fusion-360/blog/september-2026-major-product-update-whats-new/) (page returned 403 to fetch; details are from the search snippet)
- AutoConstrain generates a list of options for dimensions and constraints on a sketch. Earlier reporting said it does not change sketch geometry and was limited to Commercial subscriptions. — [Fusion Help](https://help.autodesk.com/view/fusion360/ENU/?contextId=SKT-AUTO-CONSTRAIN-CONCEPT); [Autodesk support article](https://www.autodesk.com/support/technical/article/caas/sfdcarticles/sfdcarticles/AI-auto-constrain-is-not-showing-on-Fusion.html); [Engineering.com: AutoConstrain is live](https://www.engineering.com/fusion-autoconstrain-is-now-live-and-it-might-actually-be-useful/)
- AI for drawings and sketching in Fusion has been covered by Engineering.com. — [Engineering.com: AI takes on sketching and drawings in Fusion](https://www.engineering.com/ai-takes-on-sketching-and-drawings-in-autodesk-fusion/); [Engineering.com: 3 new AI features in Fusion](https://www.engineering.com/3-new-ai-features-in-autodesk-fusion/)
- Generative Design ships inside the Fusion Simulation Extension, reportedly at $1,465/year. — [TexoCAD, competitor source](https://blog.texocad.ai/posts/ai-cad-software-2026)
- Third-party Fusion add-ins already exist: Backflip's scan-to-CAD add-in (section 4) and an open-source "CADAgent for Fusion 360". — [TexoCAD](https://blog.texocad.ai/posts/ai-cad-software-2026)

### Inferences
- If neural CAD reaches GA in Fusion, Autodesk will be the first incumbent with native prompt-to-B-rep. Its approach is a learned geometry model rather than code generation, so explicit parametric validation may be weaker. That is Shilpa's opportunity: auditable, constraint-checked feature trees.

### Gaps
- No confirmed GA date for neural CAD or Text-to-Command was found as of Oct 2026. The Autodesk Assistant's modeling capabilities in Fusion are not verified. The full Sept 2026 release notes could not be fetched (403).

---

## 3. PTC (Onshape, Creo), Dassault Systèmes (SolidWorks/3DEXPERIENCE), Siemens (NX/Solid Edge)

### Takeaway
Incumbent AI in 2026 is dominated by help/Q&A assistants plus targeted automation: drawings, fasteners, mates and error diagnosis. Dassault is the most aggressive. Its 2026 roadmap includes assembly-structure generation, generative drawings, image-to-mesh and an xDesign **PDF drawing to parametric 3D part** beta. Onshape's AI Advisor explicitly does not generate geometry, but PTC's FeatureScript MCP Server opens Onshape to external agents. Siemens ships a help copilot, AI mate snapping and auto-drawings, but no generative modeling.

### Cited Findings
**Dassault / SolidWorks**
- At 3DEXPERIENCE World 2026 (Feb 2026) there were three "virtual companions": Aura (copilot, 2025), Leo (engineering, mechanics, simulation, manufacturing; not related to the startup Leo AI) and Marie (materials/chemistry). — [DEVELOP3D: New Solidworks AI agents](https://develop3d.com/cad/new-solidworks-ai-agents-added-at-3dexperience-world/); [3DMag](https://www.3dmag.com/news/showcasing-the-future-of-ai-at-3dexperience-world-2026/)
- Ten SolidWorks AI tools were announced, all scheduled for **GA in July 2026**:
  - Already in beta in the current release: Assembly Structure Designer (a top-level assembly skeleton with subassemblies and parts from a Leo request), What's Wrong (groups feature-tree errors and finds the root cause), Drawing Creation (generative drawings with preset sheet size, standard and template).
  - Beta from April 2026: Design Inspection, Material Manager, Project Planner, Assembly Performance Doctor, PLM Model Insights, Design Change Impact.
  - Beta from July 2026: Image to Mesh (photos to mesh).
  — [Engineering.com: 10 AI tools coming to Solidworks in 2026](https://www.engineering.com/10-ai-tools-coming-to-solidworks-in-2026/)
- **xDesign (browser) converts a PDF of a 2D drawing into a parametric 3D part**, with beta from April 2026. xDesign also converts B-rep/STEP into a parametric model (beta). Chat-driven modeling and requirements-to-model were still "in development" and might miss July GA. — [Engineering.com](https://www.engineering.com/10-ai-tools-coming-to-solidworks-in-2026/)
- Aura retrieves knowledge from 3DSwym and official documentation. One review says Aura requires 3DEXPERIENCE connectivity and is not on traditional desktop SolidWorks, and another says the 2025 headline demo (full assemblies from a text prompt) had not shipped. — [SOLIDWORKS blog](https://blogs.solidworks.com/solidworksblog/2025/10/whats-new-in-solidworks-2026-collaboration-and-data-management.html); [Leo AI AURA review, competitor source](https://www.getleo.ai/blog/solidworks-aura-review-2026); [CoLab: What can LEO and AURA do](https://www.colabsoftware.com/post/solidworks-ai)
- Some AURA features were "still in beta as of the 2026 release". — [Leo AI comparison, Sep/Oct 2026, competitor source](https://www.getleo.ai/blog/built-in-ai-cad-plm-comparison-2026)

**PTC**
- Onshape AI Advisor has been live since around Oct 2025. It is a conversational assistant grounded in Onshape training material and docs. Per Onshape's own feature page it does **not** generate designs, predict model errors or do generative design. — [Leo AI comparison, competitor source](https://www.getleo.ai/blog/built-in-ai-cad-plm-comparison-2026); [TexoCAD](https://blog.texocad.ai/posts/ai-cad-software-2026)
- PTC's **Onshape FeatureScript MCP Server** lets AI agents write, test, debug and refine custom FeatureScript features and share them across a team. Release status was not stated. — [Leo AI comparison](https://www.getleo.ai/blog/built-in-ai-cad-plm-comparison-2026)
- Creo AI ("Triple A") has three parts. **Advise** is live in Creo and Creo+ (Q&A about the open model and Creo usage). **Assist** is targeted for beta later in 2026. **Automate** (executes modeling steps) is in early alpha, targeted before end of 2026. — [Leo AI comparison](https://www.getleo.ai/blog/built-in-ai-cad-plm-comparison-2026)

**Siemens**
- Designcenter Solid Edge 2026 (Oct 2025) has three features. Design Copilot is a conversational help chatbot, reportedly Solid Edge X only. Magnetic Snap Assembly does AI-suggested mating when a part is dragged onto an assembly. Automated drawings produce "up to 80% of your 2D drawing views", including orthographic, broken and isometric views with dimensions, as a value-based-licensing add-on. — [Siemens blog: Solid Edge 2026 AI](https://blogs.sw.siemens.com/solidedge/designcenter-solid-edge-2026-artificial-intelligence/); [Siemens News](https://news.siemens.com/en-us/siemens-designcenter-solid-edge-2026/); [Engineering.com: 3 AI features in Solid Edge](https://www.engineering.com/the-3-ai-features-in-designcenter-solid-edge/)
- NX Design Copilot is a natural-language help assistant announced with the 2025-2026 NX releases. Teamcenter Copilot answers from managed documents with citations, respecting access permissions. Neither generates geometry. — [Leo AI comparison](https://www.getleo.ai/blog/built-in-ai-cad-plm-comparison-2026); [TexoCAD: NX AI Chat, competitor source](https://blog.texocad.ai/posts/siemens-nx-ai-chat)

### Inferences
- **Dassault xDesign drawing-PDF-to-parametric is the most direct incumbent threat to Shilpa's drawing-to-CAD pitch**, but it lives in browser xDesign on 3DEXPERIENCE, not in desktop SolidWorks. A SolidWorks desktop companion that does drawing-to-feature-tree remains a gap that MecAgent is also targeting.
- Auto-drawings (CAD to 2D) is becoming table stakes: Siemens has it, SolidWorks has it, Fusion has it. Shilpa's roadmap should include drawing output.
- The MCP and agent-API trend (Onshape FeatureScript MCP, Creo Automate) suggests that incumbents will expose tool surfaces for third-party agents, which favors agent companions like Shilpa.

### Gaps
- Whether the SolidWorks July 2026 GA actually happened on schedule, and whether the xDesign drawing-to-3D beta reached GA, was not verified. No Onshape generative-geometry features were found. Pricing for SolidWorks AI features is not public.

---

## 4. Startups: MecAgent, Backflip, Leo AI, Adam, Vizcom, CADGPT-style tools, others

### Takeaway
The startup field splits into (a) in-CAD agents that drive existing CAD (MecAgent for SolidWorks, Leo AI across SolidWorks/Onshape/CATIA/Inventor), (b) generators (Adam, Zoo, CADScribe), (c) scan/mesh-to-parametric (Backflip, GA in Aug 2026) and (d) concept/industrial design (Vizcom, mesh plus renders). Funding is seed to Series B scale. No startup has independently verified complex-assembly generation.

### Cited Findings
**MecAgent** (Shilpa's inspiration)
- Raised about $3M (€2.75M) in May 2025, described variously as pre-seed or seed. Investors: Kima Ventures, Founders Inc., Outlander VC, Earthling VC, Irregular Expressions. Founders: Owein Dourneau, Guillaume Debregeas, Alexandre Senet. No 2026 round was found. — [SignalBase](https://www.trysignalbase.com/news/funding/mecagent-inc-secures-3m-pre-seed-investment-to-launch-the-copilot-for-mechanical-engineers-revolution); [Founders Inc portfolio](https://f.inc/portfolio/mecagent/); [Caplight](https://www.caplight.com/company/mecagent)
- Current product, per its site in Oct 2026:
  - A "CAD Agent" inside a live SolidWorks session (2024-2026 versions). It models parts from text or STEP, adds parts to assemblies, applies materials and equations, renames components, exports files and writes macros.
  - "Background CAD Tasks", including drawing-to-CAD and CAD-to-drawing.
  - Text-to-CAD for parts, assemblies and drawings from a spec.
  - Other CAD logos are shown (Inventor, CATIA V5, 3DX, Fusion, NX, Solid Edge, Onshape, Creo), but only SolidWorks has a download, and a "soon" label appears.
  — [mecagent.com](https://mecagent.com)
- Pricing:
  - Free: 3,000 tokens and 11 agentic runs.
  - Starter: $84/month (40 runs, 1 Drawing-to-CAD, 2 CAD-to-Drawing).
  - Advanced+: $417/seat/month (202 runs, 6 Drawing-to-CAD, 10 CAD-to-Drawing).
  - Claims 210k followers and 80M views, with logos of NASA, Apple, McLaren and others (unverified).
  — [mecagent.com](https://mecagent.com)

**Backflip AI**
- Founded by Markforged co-founders Greg Mark and David Benhaim. $30M Series A (Dec 2024) co-led by a16z and NEA. — [Forbes, Feb 2025](https://www.forbes.com/sites/michaelmolitch-hou/2025/02/20/how-backflips-ai-aids-amateur-and-veteran-3d-designers-alike/); [VoxelMatters](https://www.voxelmatters.com/backflip-ai-launches-cad-copilot-that-turns-3d-scans-into-editable-models/)
- **GA around Aug 4 2026:** a CAD copilot built on a second-generation foundation model that converts scans, STL and mesh into **parametric models with a feature tree** (chained extrude, revolve and pattern operations). It runs as an Autodesk Fusion add-in and as a web app with STEP export. Fast mode takes a couple of minutes, and a "Thinking" mode targets accuracy on complex parts. It also offers multimodal CAD-library search.
  - Pricing: from $20/month (Builder, Pro, Business, Enterprise), with 3-4 free reconstructions.
  - A large automaker digitizes about half of processed parts with it.
  - Plugins for other CAD packages are planned later in 2026.
  - The ~$1,500 to ~$10 per-part cost claim comes from the vendor.
  — [VoxelMatters](https://www.voxelmatters.com/backflip-ai-launches-cad-copilot-that-turns-3d-scans-into-editable-models/); [MLQ](https://mlq.ai/news/backflip-ai-launches-scan-to-cad-tool-inside-autodesk-fusion/)

**Leo AI** (Israel; CEO Maor Farid)
- $9.7M seed, per the company's press page. Engineering.com reported additional funding, but the amount was not retrieved. — [Leo AI press](https://www.getleo.ai/press); [Crunchbase](https://www.crunchbase.com/organization/leo-ai-81b4)
- Around March 2026, Leo claimed **full CAD assemblies from a text prompt** with design calculations and part sourcing. The demo was a hydraulic piston pushing 50 kg over a 100 mm stroke. Each part has a part and feature tree, and it works with SolidWorks, Onshape, CATIA and Inventor. **Limitation: parts are not mated automatically.** The user closes mates manually, and the demo video skips human steps. — [Engineering.com: Leo AI can now generate full CAD assemblies](https://www.engineering.com/leo-ai-can-now-generate-full-cad-assemblies/)
- In the Xometry Aug 2025 test, Leo (free plan) output only PNG concept images that were not dimensionally accurate, with no STEP/STL on the free plan. That test predates the assembly feature. — [Xometry](https://xometry.pro/en/articles/text-to-cad-tools-test/)

**Adam (AdamCAD)**
- YC W25, founded in 2024 by Zach Dive and Aaron Li. $4.1M seed led by TQ Ventures, announced Oct 31 2025 (with 468 Capital, Pioneer, Script, Transpose). The company is pivoting from consumer text-to-3D to an enterprise CAD copilot. — [TechBuzz](https://www.techbuzz.ai/articles/adam-raises-4-1m-after-viral-text-to-3d-tool-hits-10m-impressions); [AI Curator](https://aicurator.io/adam-funding/)
- Xometry test: the cylinder and **gear were accurate with editable parameters**, and the manifold was simplified but included fillets and channels. It was the best performer at 4/5 accuracy. It is browser-only with Parametric and Creative modes and exports STL and SCAD (OpenSCAD), not STEP. — [Xometry](https://xometry.pro/en/articles/text-to-cad-tools-test/)

**Vizcom** (industrial design, sketch to render or mesh)
- $20M Series A led by Index (Mar 2024) and a $27M Series B led by Radical Ventures (Oct 2025). Reported totals conflict ($47M vs $52M). Customers reportedly include Ford, New Balance, Nike and Honda. — [Vizcom blog](https://www.vizcom.ai/blog/vizcom-raises-series-a-funding); [Radical Ventures](https://radical.vc/?p=3122)
- It generates lightweight 3D **meshes** from sketches for volume and proportion checks, not editable CAD. — [aggregator sources via search; low confidence](https://uiuxshowcase.com/resources/vizcom/)

**Other generators (Xometry test, Aug 2025)**
- CADGPT (via YesChat) produced code only (DXF-style), with no preview or download.
- CADScribe produced usable STEP/STL for simple parts, but its gear was wrong, the manifold was cut off by input length, and the free tier allows 10 prompts.
- Vondy claimed STEP/DWG output, but the download links did not work.
- Across all tools: "minimal support for complex assemblies or functional constraints".
— [Xometry](https://xometry.pro/en/articles/text-to-cad-tools-test/)
- TexoCAD is another text-to-CAD entrant, judging by its blog. It is cited here only as a source.

### Inferences
- MecAgent is a direct competitor with the same SolidWorks-companion shape and published drawing-to-CAD quotas. Its $84-$417/month pricing gives a market anchor for Shilpa. Its tight Drawing-to-CAD quotas (1-6 per month) suggest the feature is expensive or slow, which is a possible wedge if Shilpa makes drawing-to-CAD cheap and validated.
- The documented failure of the most advanced startup, Leo AI (assemblies without mates), points to a concrete target: generate assemblies **with mates or constraints** and validated interfaces.
- Backflip shows that a feature-tree output (not dumb B-rep) is now the bar for "reverse engineering" products.

### Gaps
- Spectral (Spectral Labs) and other 2026 seed-stage text-to-CAD startups were not researched. CADAM, an open-source text-to-OpenSCAD tool, was not verified. Leo AI's additional funding amount and pricing were not found. MecAgent's 2026 traction is unverified, and its customer logos are unverified.

---

## 5. Image/text-to-3D mesh vendors (Meshy, Tripo, Luma, CSM, Rodin, Hunyuan3D)

### Takeaway
None of these vendors outputs editable CAD (STEP or a feature tree). They output meshes (GLB, OBJ, FBX, USDZ, STL, 3MF) suited to concepts, games and visualization. Mesh-to-parametric conversion is a separate product category (Backflip, and xDesign B-rep-to-parametric).

### Cited Findings
- Meshy, Tripo and Rodin produce meshes. Typical formats are GLB, OBJ, FBX, USDZ, STL and 3MF, and almost none output a print-ready mesh directly. For functional, dimensioned parts the source recommends text-to-CAD or CAD instead. — [3DPrinting.com guide](https://3dprinting.com/software-guides/ai-3d-model-generators/); [BuildMVPFast Sept 2026](https://www.buildmvpfast.com/articles/best-llms-2026-guide/3d-modeling-ai)
- Hunyuan3D 2.1 (open source) outputs textured GLB/OBJ meshes. Rodin Gen-2.5 is noted for hard-surface props with quad topology and PBR materials. — [3DAIStudio API comparison](https://www.3daistudio.com/blog/best-3d-model-generation-apis-2026)
- Dassault's own SolidWorks "Image to Mesh" (beta and GA July 2026) also produces a mesh, not B-rep. — [Engineering.com](https://www.engineering.com/10-ai-tools-coming-to-solidworks-in-2026/)

### Inferences
- For Shilpa, mesh generators are upstream concept tools. A pipeline of image to mesh (Meshy, Hunyuan3D) to parametric (Backflip-like) is emerging and is a possible future integration path for "product concept" inputs.

### Gaps
- Luma and CSM (Common Sense Machines) were not specifically researched. CSM previously marketed "parts" and segmented outputs, but no 2026 source confirms CAD export. Vendor-published benchmarks (e.g., Neural4D vs Tripo) are biased.

---

## 6. What tools demonstrably handle (parts vs assemblies, sheet metal, drawings, history), and benchmarks

### Takeaway
Verified, shipped capability as of Oct 2026:
- **Single prismatic parts** from text: Zoo, Adam, CADScribe and MecAgent.
- **Parametric feature trees**: Zoo (KCL), Backflip (from mesh) and MecAgent/Leo (native host CAD).
- **CAD-to-2D drawings**: Siemens, SolidWorks, Fusion and MecAgent.
- **Assembly skeletons/structures**: SolidWorks Assembly Structure Designer (beta), and Leo with no automatic mates.

Not demonstrated by any vendor: **sheet metal generation**, fully mated assemblies from text, or validated manufacturability. The only independent multi-tool benchmark found is Xometry (Aug 2025, free tiers, 3 functional prompts). There are no rigorous third-party benchmarks of commercial tools.

### Cited Findings
- Xometry functional benchmark (cylinder / gear / manifold): Zoo got 1/3 correct. Adam got 2/3 correct and 1 simplified. CADScribe got 1/3. The others produced no usable geometry. The authors concluded the tools are useful for prototyping and teaching, "not a substitute for professional CAD", with "inconsistent file export" and "minimal support for complex assemblies or functional constraints". — [Xometry, Aug 26 2025](https://xometry.pro/en/articles/text-to-cad-tools-test/)
- Assemblies: Zoo v1 has assemblies but mates are on the roadmap ([Zoo](https://zoo.dev/blog/zoo-design-studio-v1)). Leo has no auto-mates ([Engineering.com](https://www.engineering.com/leo-ai-can-now-generate-full-cad-assemblies/)). SolidWorks Assembly Structure Designer generates structure, not detailed geometry ([Engineering.com](https://www.engineering.com/10-ai-tools-coming-to-solidworks-in-2026/)). Solid Edge Magnetic Snap does AI mating of existing parts ([Engineering.com](https://www.engineering.com/the-3-ai-features-in-designcenter-solid-edge/)).
- Drawings output: Solid Edge auto-generates up to 80% of drawing views ([Siemens](https://blogs.sw.siemens.com/solidedge/designcenter-solid-edge-2026-artificial-intelligence/)). SolidWorks Drawing Creation was in beta with GA in July 2026 ([Engineering.com](https://www.engineering.com/10-ai-tools-coming-to-solidworks-in-2026/)). MecAgent offers CAD-to-Drawing ([mecagent.com](https://mecagent.com)).
- Drawing to CAD: MecAgent's paid tiers (quota-limited) and Dassault xDesign's PDF-to-parametric beta (Apr 2026). — [mecagent.com](https://mecagent.com); [Engineering.com](https://www.engineering.com/10-ai-tools-coming-to-solidworks-in-2026/)
- Editing history: Zoo regenerations overwrite the previous model ([Xometry](https://xometry.pro/en/articles/text-to-cad-tools-test/)). Zoo STEP export drops the KCL history ([TexoCAD](https://blog.texocad.ai/posts/ai-cad-software-2026)). Backflip outputs an editable feature tree ([VoxelMatters](https://www.voxelmatters.com/backflip-ai-launches-cad-copilot-that-turns-3d-scans-into-editable-models/)).
- Incumbent assistants "don't generate complex geometry from scratch". — [Leo AI, competitor source](https://www.getleo.ai/blog/built-in-ai-cad-plm-comparison-2026)

### Inferences
- **Proposed capability targets for Shilpa:**
  1. Pass the three Xometry functional prompts with dimensional verification.
  2. Generate a parametric FreeCAD feature tree that survives export, so history is preserved, unlike Zoo's STEP output.
  3. Drawing-to-CAD with automated dimensional cross-checks against the drawing.
  4. Assemblies with mates or constraints, which neither Leo nor Zoo offers.
  5. Sheet metal, which no competitor demonstrated.
  6. CAD-to-drawing output to reach parity with incumbents.
- **Market direction:**
  - Incumbents converge on help copilots, auto-drawings, AI mates and error diagnosis, while neural/generative geometry (Autodesk neural CAD, Dassault chat-modeling) stays in preview.
  - Platforms open agent APIs (Onshape MCP, Creo Automate).
  - Startups compete on in-CAD agents and on reverse engineering.
  - A publishable, reproducible benchmark is a market gap Wayam could fill for credibility.

### Gaps
- No independent 2026 benchmark comparing Zookeeper, Adam, MecAgent, Leo and Backflip was found. Academic benchmarks (e.g., Text2CAD, CAD-Recode, CADPrompt) were outside this scope. Engineer YouTube and forum evaluations were not reviewed because of the tool-call budget. No evidence was found of any commercial tool generating sheet-metal features (flanges, bends, flat patterns) from text or drawings.
