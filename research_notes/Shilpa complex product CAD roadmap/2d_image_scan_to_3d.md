# 2D drawings, images and 3D scans to 3D models (editable CAD and visual meshes), state of the art as of Oct 2026

Scope note: about 20 searches and fetches, run 2026-10-18. Numbers are the authors' own reported figures unless stated otherwise. Licences were checked on GitHub or Hugging Face where possible. Where a licence was not visible it is listed as a gap, not guessed.

## Q1. Engineering drawing / multi-view orthographic reconstruction to CAD (incl. GD&T, assembly drawings, BOM)

### Takeaway
VLM-to-CAD-code is now the standard approach for turning orthographic drawings into CAD: a fine-tuned 8B VLM writes CadQuery code that is then executed. Accuracy is still modest. The best published result (Ortho2CAD, Jul 2026) reaches IoU 0.79 on synthetic DeepCAD and 0.56 on Fusion360. It covers sketch+extrude only and uses bounding-box dimensions only. Full multi-sheet, fully dimensioned, assembly-level drawing-to-CAD is not solved in open research. Annotation and GD&T extraction is best done with hybrid pipelines (detector + OCR + fine-tuned VLM). There is no public standard benchmark for GD&T or BOM extraction.

### Cited Findings
- **Ortho2CAD** (CMU, arXiv 2607.08891, Jul 2026). Base model is Qwen3-VL-8B-Instruct. Input is a raster 3-view first-angle drawing with hidden lines and 3 bounding-box dimensions; output is CadQuery code. Training is SFT on the DeepCAD/GenCAD-Code split (147,289 train) followed by Dr.GRPO-style RL with an IoU reward on Fusion360 (6,900 train). Drawings are generated synthetically from STEP files with pythonOCC. [arXiv](https://arxiv.org/html/2607.08891v1)
  - Results on DeepCAD (100-sample test): valid-code rate / IoU. Ortho2CAD 100% / 0.792. CAD-Coder 100% / 0.736. GPT-5.2 (zero-shot) 90% / 0.599. Qwen3-VL-32B 76% / 0.49. [arXiv](https://arxiv.org/html/2607.08891v1)
  - Results on Fusion360: Ortho2CAD-RL 100% / 0.560. GPT-5.2 78% / 0.518. CAD-Coder 90% / 0.247. [arXiv](https://arxiv.org/html/2607.08891v1)
  - Stated limitations: sketch+extrude only; bounding-box dimensions only, so inner diameters and similar features must be inferred; 100-sample test subsets; low IoU on thin or complex geometry; single-pass with no iterative refinement. Training cost was 11 h on 44 H100s (SFT) and about 100 h on 4 H100s (RL). [arXiv](https://arxiv.org/html/2607.08891v1)
  - Code is at github.com/AdityaJoglekar/Ortho2CAD. No code licence is stated on the paper page. [arXiv](https://arxiv.org/html/2607.08891v1)
  - The authors state that no large-scale public dataset pairs dimensioned multi-view engineering drawings with 3D CAD. [arXiv](https://arxiv.org/html/2607.08891v1)
- Related drawing-to-CAD lineage cited by Ortho2CAD: Zhang et al. 2023 (orthographic drawings to 3D CAD, Computers & Graphics) and Zhang et al. 2025 (an RL follow-up in Computer-Aided Design); Image2CADSeq (Li & Sha 2025); Text2CAD (Khan et al. 2024, arXiv 2411.06206, "Text to 3D CAD generation via technical drawings"); CADmium (2025); CADCodeVerify (2024). [arXiv](https://arxiv.org/html/2607.08891v1); [search listing](https://arxiv.org/pdf/2508.18733)
- **Drawing2CAD** (arXiv 2508.18733, 2025) does seq2seq generation of CAD from *vector* drawings. Only its reference list was retrieved, so details are not verified. [arXiv](https://arxiv.org/pdf/2508.18733)
- **VisCAD** (arXiv 2609.03811, Sep 2026) is a "foundation model suite" for industrial CAD.
  - VisCAD-M1 is 27B parameters. It maps renders, text, 2D drawings and real photos to programs in a CAD DSL, and it also covers assembly-level generation (mating relations, poses, placement). Its pipeline includes a "multimodal understanding & BoM" stage.
  - Part-level score is 0.5540 vs 0.5496 for the best frontier model, and 0.5797 when VisCAD-M1 is used as a test-time verifier. Benchmarks are PubCADBench and RealCADBench.
  - Release and licence are not stated in the abstract.
  - [arXiv](https://arxiv.org/abs/2609.03811); [search](https://arxiv.org/pdf/2609.03811)
- **Annotation / GD&T extraction.**
  - Khan et al. fine-tuned Florence-2 on 400 annotated drawings and compared it against zero-shot GPT-4o and Claude-3.5-Sonnet. Reported gains: +29.95% precision, +37.75% recall, +52.4% F1, and 43.15% fewer hallucinations. [arXiv 2411.03707](https://arxiv.org/abs/2411.03707)
  - A multi-stage hybrid framework (arXiv 2510.21862) runs layout segmentation, then annotation detection, then VLM parsing, for multi-view drawings. [arXiv](https://arxiv.org/pdf/2510.21862)
  - "From Drawings to Decisions" (Robotics & CIM, 2025/26) uses YOLOv11-OBB followed by fine-tuned VLMs and reports above 93% F1. On GD&T frames, Donut gave higher schema compliance. [ScienceDirect](https://www.sciencedirect.com/science/article/abs/pii/S0736584525002406); [arXiv 2506.17374](https://bytez.com/docs/arxiv/2506.17374/paper)
  - TechDrawOCRvsVLM compares eDOCr2 OCR, Gemini, and OCR+VLM on dimensions, GD&T and tolerances. It is a single-drawing demo. [GitHub](https://github.com/ebubekirdogan/TechDrawOCRvsVLM)
  - Mapping 2D annotations onto 3D CAD features with LLM reasoning is covered in arXiv 2602.18296 (2026). [arXiv](https://arxiv.org/pdf/2602.18296)
  - "Engineering drawings to assembly instructions" with a VLM appears at PHM-AP. [PHM Society](https://papers.phmsociety.org/index.php/phmap/article/view/4481)
- No public benchmark jointly scores GD&T and BOM extraction from assembly drawings. Most BOM-extraction material online is vendor marketing. [search summary; e.g. Aginera blog](https://aginera.ai/blog/bom-extraction-indian-manufacturers-guide)

### Inferences
- Shilpa's current approach (a frontier VLM planner emitting a typed feature IR, executed and validated) is architecturally the same as the SOTA research systems: VLM, then code, then kernel, then check. Shilpa has two advantages over the research systems. First, it reads *real dimensions*, whereas Ortho2CAD sees only bounding boxes. Second, it validates output, whereas the research systems are single-pass. Zero-shot GPT-5.2 at about 0.5–0.6 IoU on undimensioned 3-views suggests that dimension reading plus a verify-and-repair loop matters more than the base model.
- For multi-sheet and assembly drawings, a practical route is staged:
  1. Sheet and view segmentation, plus title-block and BOM-table parsing (a detector + OCR + VLM hybrid).
  2. Per-part reconstruction using the existing pipeline.
  3. Assembly placement from balloon references and section views, guided by the BOM.

  VisCAD's "understanding & BoM, then part generation, then assembly" decomposition matches this staging.
- An RL-with-IoU-reward fine-tune of a small open VLM (Ortho2CAD recipe) is an option if Shilpa ever wants an on-prem model. It requires synthetic drawing generation from STEP, which Shilpa could do with its own build123d/OCC stack.

### Gaps
- No found paper reconstructs full *assemblies* from multi-sheet assembly drawings into mated CAD with published accuracy.
- Licences for the Ortho2CAD code and for VisCAD's release status were not found.
- Drawing2CAD's metrics were not retrieved.
- No accuracy numbers on *real* scanned or legacy drawings were found. All reconstruction benchmarks are synthetic renders from DeepCAD or Fusion360.

## Q2. Image/photo to editable CAD, and hand sketch to CAD

### Takeaway
Fine-tuned VLMs that emit CadQuery code (CAD-Coder, cadrille) give 100% or near-100% executable code and IoU of about 0.85–0.92 on synthetic renders. Real-photo results are mostly qualitative, and accuracy drops sharply on real data: cadrille reaches 65% IoU on the real-scan CC3D benchmark, against 92% on DeepCAD. Hand-sketch-to-CAD research is thin. It mostly addresses 2D sketch parameterisation (PICASSO, WACV 2025) or older sketch-to-sequence work.

### Cited Findings
- **CAD-Coder** (MIT, arXiv 2505.14646, 2025; journal version JMD 2026). A LLaVA-1.5-style open VLM that outputs CadQuery. Its GenCAD-Code dataset has more than 163k image–code pairs. It beats GPT-4.5 and Qwen2.5-VL-72B on 3D solid similarity with 100% valid syntax. The authors report only "some signs" of generalisation to real photos. [arXiv](https://arxiv.org/abs/2505.14646); [MIT DeCoDE](https://decode.mit.edu/assets/papers/2026_doris_cadcoderjmd.pdf)
- **CADCrafter** (CVPR 2025, arXiv 2504.04753). Latent diffusion from image to CAD command sequence. It is trained on synthetic data, uses a DPO code checker driven by CAD-compiler feedback, and is evaluated on a new set of unconstrained photos of 3D-printed parts. [CVF](https://openaccess.thecvf.com/content/CVPR2025/papers/Chen_CADCrafter_Generating_Computer-Aided_Design_Models_from_Unconstrained_Images_CVPR_2025_paper.pdf)
- **Img2CAD** (arXiv 2408.01437, 2024). VLM-assisted conditional factorisation of an image into structured CAD. Trained on synthetic ShapeNet data and shown on Pix3D and product photos, with natural-language structure edits. [arXiv](https://arxiv.org/pdf/2408.01437)
- **cadrille** (arXiv 2505.22914, 2025). Qwen2-VL-2B, taking point cloud, multi-view image or text as input and producing CadQuery code; trained with SFT followed by online RL (Dr. CPPO). Multi-view image results (CD×10³ / IoU% / invalid rate%) [arXiv](https://arxiv.org/html/2505.22914v1):
  - DeepCAD: 0.17 / 92.2 / 0.0
  - Fusion360: 0.17 / 84.6 / 0.0
  - CC3D real: 0.57 / 65.0 / 0.1
  - Baseline for comparison, LRM-mesh-then-CAD-Recode: 0.53 / 69.8 / 14.3 on DeepCAD.
  - Code is at github.com/col14m/cadrille; licence not stated on the paper page. [arXiv](https://arxiv.org/abs/2505.22914)
- **MV2Cyl** (arXiv 2406.10853, 2024) reconstructs extrusion cylinders from multi-view images. **View2CAD** (arXiv 2504.04000, 2025) produces view-centric CAD from a single RGB-D scan. [MV2Cyl](https://arxiv.org/pdf/2406.10853); [View2CAD](https://arxiv.org/pdf/2504.04000)
- **Hand sketch.**
  - PICASSO (WACV 2025, arXiv 2407.13394) parameterises 2D CAD sketches from hand-drawn or precise sketch images, trained with rendering self-supervision so it needs no paired CAD parameters. [CVF](https://openaccess.thecvf.com/content/WACV2025/html/Karadeniz_PICASSO_A_Feed-Forward_Framework_for_Parametric_Inference_of_CAD_Sketches_WACV_2025_paper.html)
  - Vitruvion (ICLR 2022, arXiv 2109.14124) generates sketch primitives and constraints from hand-drawn raster sketches. It is foundational work. [arXiv](https://arxiv.org/pdf/2109.14124)
  - Free2CAD (freehand drawings to CAD programs) was mentioned only via a LinkedIn post, so it is unverified here. [LinkedIn](https://br.linkedin.com/in/thaisbbaker)

### Inferences
- These models do well on DeepCAD-style sketch+extrude prisms but drop about 25–30 IoU points on real data. For product photos, the realistic output is therefore a *proposal* CAD that needs dimensions supplied by the user, by a reference object, or by a drawing, followed by validation. A photo carries no absolute scale.
- Shilpa's gpt-5.5 planner plus a feature IR can follow the same pattern as cadrille: generate N candidates, execute them, and score each against the image using silhouette or render IoU. This "sample, execute, select" loop drives much of the reported gain in CAD-Recode and cadrille.

### Gaps
- No quantitative benchmark of photo-to-CAD on real *consumer products* was found. Real-photo evaluations are qualitative or use 3D-printed parts.
- No 2025–26 freehand-3D-sketch-to-B-rep system with published accuracy was found beyond PICASSO, which is 2D only.

## Q3. Point cloud / mesh to CAD reverse engineering

### Takeaway
Two families exist:
1. **Code-generating LLMs**: CAD-Recode (ICCV 2025) and cadrille. They produce editable CadQuery and are strong on prismatic sketch+extrude parts. On real scans (CC3D) they reach about 60–68% IoU.
2. **Segment-and-fit B-rep methods**: Point2CAD, ComplexGen, NVDNet/Split-and-Fit. They produce surface-level B-reps, including freeform surfaces, but no feature history and no design intent.

Commercial tools (Geomagic Design X) remain region-segmentation plus manual or semi-automatic feature fitting. Users consistently call automatic parametric feature creation the weakest part.

### Cited Findings
- **CAD-Recode** (ICCV 2025, arXiv 2412.14042). Point cloud to CadQuery Python, built on a Qwen2-1.5B LLM with a point-cloud projector and trained on 1M synthetic CAD sequences. [arXiv](https://arxiv.org/abs/2412.14042v2); [ICCV PDF](https://orbilu.uni.lu/bitstream/10993/67036/1/CADRecode_ICCV_2025.pdf)
  - DeepCAD mean CD falls from 3.43 to 0.30 and IoU rises from 77.6% to 92.0% vs CAD-SIGNet. Candidate selection matters: 10 candidates are generated and the one with minimum CD is picked. [ICCV PDF](https://orbilu.uni.lu/bitstream/10993/67036/1/CADRecode_ICCV_2025.pdf)
  - v1.5 was released in March 2025. The model and dataset are on Hugging Face (filapro/cad-recode, filapro/cad-recode-v1.5), and there is a HF Space demo. The code licence is in LICENSE.md, which was not read; the weights and dataset licences are not stated on the README. [GitHub](https://github.com/filaPro/cad-recode)
- **cadrille, point-cloud input** (CD×10³ / IoU% / invalid rate%) [arXiv](https://arxiv.org/html/2505.22914v1):
  - cadrille-RL: DeepCAD 0.17 / 90.2 / 0.0; Fusion360 0.17 / 85.0 / 0.2; CC3D (real scans) 0.47 / 67.9 / 0.2.
  - CAD-Recode on the same table: CC3D 0.54 / 60.5 / 9.8.
  - CAD-SIGNet: CC3D 4.42 / 39.1 / 15.5.
- **CADENA: Stepwise CAD reverse engineering** (arXiv 2608.00799, 2026) appeared in search. Not read. [arXiv](https://arxiv.org/pdf/2608.00799)
- **Point2CAD** (CVPR 2024, arXiv 2312.04962).
  - Pipeline: the point cloud is segmented into surface clusters by an external tool (ParseNet or HPNet), then primitives and freeform INR surfaces are fitted, intersected and trimmed, and topology (edges, corners) is recovered. [arXiv](https://arxiv.org/pdf/2312.04962); [GitHub](https://github.com/YujiaLiu76/Point2CAD)
  - It claims SOTA on ABC and says ComplexGen outputs are often topologically inconsistent. [arXiv](https://arxiv.org/pdf/2312.04962)
  - The README licence is CC-BY-NC 4.0 (research only, contact the authors for commercial use), while the GitHub sidebar says Apache-2.0. It needs PyMesh and Docker; a GPU is optional. [GitHub](https://github.com/YujiaLiu76/Point2CAD)
- **ComplexGen** (SIGGRAPH 2022, arXiv 2205.14573) generates a B-rep chain complex (foundational). Trained on 20k ABC models and tested on 3k. [arXiv](https://arxiv.org/pdf/2205.14573)
- **NVDNet / Split-and-Fit** (SIGGRAPH 2024, arXiv 2406.05261). A neural Voronoi diagram partitions the input, then surfaces are fitted. On ABC it reports the best topology scores: face–edge F1 0.778 and edge–vertex F1 0.753, against ComplexGen's 0.599 and 0.572. [arXiv](https://arxiv.org/html/2406.05261v1)
- **Commercial: Geomagic Design X** (Hexagon).
  - The workflow is region-based mesh segmentation, producing closed, knit parametric surfaces and solids, with a deviation heat-map comparing mesh and CAD. [CATI](https://www.cati.com/?p=123053)
  - Users repeatedly call automatic parametric feature generation the weakest part. [Capterra](https://www.capterra.ca/software/1038237/geomagic-design-x); [GetApp](https://www.getapp.com/software/2062744/geomagic-design-x) (and regional GetApp mirrors)
  - Release 2025.1 adds LiveTransfer to SOLIDWORKS, NX, Inventor and Creo. [Quality Digest](https://www.qualitydigest.com/node/38324)
- A survey of geometric deep learning for CAD gives background on this area. [arXiv 2402.17695](https://arxiv.org/pdf/2402.17695)

### Inferences
- For Shilpa, CAD-Recode and cadrille are the most directly usable research artefacts. Both output CadQuery, which shares OCC with build123d and maps naturally to a feature IR. Weights are on HF. Licences must be confirmed before commercial use.
- Use them as proposal generators for prismatic parts, then refine dimensions by fitting against the scan with OCC distance queries.
- For freeform or cast parts, route to segment-and-fit (Point2CAD-style). Point2CAD's own licence blocks commercial use, so a re-implementation or an alternative would be needed. Alternatively, accept a "dumb solid" B-rep with a deviation report.
- No method recovers design intent (constraints, tolerances, standard hole series) from scans. That must come from rules or the user.

### Gaps
- Licence texts for CAD-Recode (LICENSE.md) and cadrille were not read.
- No independent head-to-head benchmark across Point2CAD, NVDNet and CAD-Recode under a single protocol was found.
- No quantitative accuracy figures for commercial auto-surfacing or feature recognition (Design X, QuickSurface, Fusion mesh-to-BRep) were found.

## Q4. Image/text to 3D mesh (visual assets) and part-aware generation

### Takeaway
Open image-to-3D models in late 2026 produce high-quality textured, PBR meshes in seconds on a 24 GB+ GPU.
- **TRELLIS.2** (Microsoft, MIT licence, 4B parameters) is the cleanest licence choice.
- **Hunyuan3D 2.1, Omni and Part** have open weights under a restrictive Tencent community licence that excludes the EU, UK and South Korea and caps use at 1M MAU.
- **Hunyuan3D 3.x** appears to be hosted/API-only.

Part-aware generation exists: PartCrafter (NeurIPS 2025), OmniPart (2025), Hunyuan3D-Part (P3-SAM + X-Part), and Hunyuan3D-Buffalo with text-grounded part generation. These give *segmented meshes* suitable for concepts and visualisation, not dimensioned engineering parts.

### Cited Findings
- **TRELLIS.2** (arXiv 2512.14692, late 2025). [GitHub](https://github.com/microsoft/TRELLIS.2)
  - MIT licence for code and model; dependencies nvdiffrast and nvdiffrec have their own terms.
  - 4B parameters. Uses an "O-Voxel" sparse representation that handles open, non-manifold and internal structures.
  - Speed on an H100: about 3 s at 512³, about 17 s at 1024³, about 60 s at 1536³.
  - Needs at least 24 GB VRAM (verified on A100 and H100); Linux only.
  - Output is GLB with PBR textures (base colour, roughness, metallic, opacity). No part or segmentation feature is mentioned.
- **Hunyuan3D 2.1** (arXiv 2506.15442) delivers production-ready PBR. Weights are under the Tencent Hunyuan 3D 2.1 Community License, which excludes the EU, UK and South Korea, and use above 1M MAU needs a separate licence. [arXiv](https://arxiv.org/pdf/2506.15442); [secondary summary](https://triposr.org/blog/hunyuan3d-versions)
- **Hunyuan3D-Omni** (Sep 25, 2025; 3.3B parameters, built on 2.1). Controllable generation with point cloud, voxel, bounding-box and skeleton conditioning. Same territorial and MAU-restricted licence. [GitHub](https://github.com/Tencent-Hunyuan/Hunyuan3D-Omni); [HF](https://huggingface.co/tencent/Hunyuan3D-Omni/blob/main/README.md)
- **Hunyuan3D-Part.** P3-SAM handles part segmentation and X-Part handles part generation. The open release is a "light" X-Part; the full version is in Hunyuan3D-Studio. Licence file not verified. [GitHub](https://github.com/Tencent-Hunyuan/Hunyuan3D-Part); [HF](https://huggingface.co/tencent/Hunyuan3D-Part)
- **Hunyuan3D 3.0/3.1** have no official open weights or repo found. Third-party sources describe them as hosted/API only, and the GitHub "Hunyuan3D-3" repos are unofficial API wrappers. [triposr.org blog](https://triposr.org/blog/hunyuan3d-versions); [exedesign wrapper](https://github.com/exedesign/Hunyuan-3D-v3)
- **Hunyuan3D-Buffalo 1.0** (arXiv 2608.02711, Aug 2026) unifies a 3D VLM (understanding) with a DiT (generation). It supports text-to-3D, instruction-guided editing and text-grounded part generation, and was trained on an 87M-sample corpus. Open release is not stated. [arXiv](https://arxiv.org/abs/2608.02711)
- **PartCrafter** (NeurIPS 2025, arXiv 2506.05573) generates multiple part meshes in one shot from a single image, using per-part latent token sets and hierarchical attention, with no segmentation input needed. [arXiv](https://arxiv.org/html/2506.05573v1); [NeurIPS](https://neurips.cc/virtual/2025/poster/120299)
- **OmniPart** (arXiv 2507.06165, 2025) works in two stages: an autoregressive planner lays out part bounding boxes (guided by 2D masks), then a rectified-flow model synthesises the parts. Its axis-aligned boxes are a known limitation. [arXiv](https://arxiv.org/abs/2507.06165)
- The broader 2026 comparisons found are from blogs and secondary sources: TripoSR vs Hunyuan3D vs TRELLIS, and open-source lists. [triposr.org](https://triposr.org/blog/free-image-to-3d); [cinevva](https://app.cinevva.com/guides/ai-3d-model-generators); [builderai](https://builderai.tools/blog/single-image-to-3d-model-pipeline-2026)

### Inferences
- For a product-concept "visual mesh" lane, TRELLIS.2 is the default because of its MIT licence. Hunyuan3D is usable only if the deployment is outside the EU, UK and South Korea and below 1M MAU. Hunyuan3D-Part or PartCrafter can provide part-separated concept meshes, for example a housing, buttons and a lens as separate meshes.
- These models are tied to roughly 24 GB GPUs on Linux, so on a Windows dev box they belong as a remote or cloud service.

### Gaps
- Stable Fast 3D / SPAR3D (Stability AI) and other 2026 entrants were not checked in this session, so their licences and quality are unverified.
- No standard quantitative quality benchmarks were collected.
- PartCrafter and OmniPart licences were not checked.

## Q5. Mesh-to-CAD limits and bridging approaches; routing for a hybrid system

### Takeaway
A generated or scanned mesh is a tessellated surface with no analytic faces, no feature history, no dimensions or tolerances, and often no watertight or manifold guarantee. TRELLIS.2 explicitly models non-manifold and internal geometry. Generated meshes also have no absolute scale.

The bridges that exist are:
- mesh/points to CAD code (CAD-Recode, cadrille);
- segment-and-fit to B-rep (Point2CAD, NVDNet);
- commercial region-fit with deviation maps (Design X).

All of these lose accuracy on real data, and none recovers design intent. A hybrid system should keep "engineering CAD" and "visual mesh" as separate lanes with explicit conversion steps, each with a quality gate.

### Cited Findings
- On real scans, the best code-generating reverse-engineering model reaches 67.9% IoU (cadrille-RL, CC3D), against about 90% on synthetic DeepCAD. [arXiv](https://arxiv.org/html/2505.22914v1)
- Going from multi-view images through a mesh (LRM) and then to CAD-Recode gives a 14–20% invalid rate and lower IoU (69.8 on DeepCAD) than direct image-to-CAD (92.2 IoU, 0% invalid). [arXiv](https://arxiv.org/html/2505.22914v1)
- TRELLIS.2's representation deliberately supports open surfaces, non-manifold geometry and internal structures, which are the opposite of a valid solid B-rep. [GitHub](https://github.com/microsoft/TRELLIS.2)
- Segment-and-fit methods produce trimmed analytic and freeform surfaces with topology, but Point2CAD reports topological inconsistency in ComplexGen outputs. [arXiv](https://arxiv.org/pdf/2312.04962)
- Commercial scan-to-CAD relies on region segmentation, surface fitting, and a deviation heat-map to verify the result, and automatic feature creation is weak. [CATI](https://www.cati.com/?p=123053); [Capterra](https://www.capterra.ca/software/1038237/geomagic-design-x)
- Hunyuan3D-Omni accepts point-cloud and bounding-box conditioning, which allows a CAD envelope to steer a visual mesh (CAD to mesh styling). [GitHub](https://github.com/Tencent-Hunyuan/Hunyuan3D-Omni)

### Inferences (proposed routing for Shilpa)
1. **Dimensioned engineering drawing, single part.** Keep the current gpt-5.5 path to typed IR, build123d, then validation. Add sheet segmentation and a detector/OCR cross-check for GD&T (hybrid pipelines beat pure VLMs on annotation extraction).
2. **Multi-sheet or assembly drawing.** Parse the title block, the BOM table and balloons, then run per-part drawing-to-IR, then assemble with mates inferred from views and BOM. Treat assembly as experimental; no published SOTA exists to lean on.
3. **Sketch or product photo.**
   - Use the VLM to produce a proposal feature IR.
   - Generate N candidates, execute them, and pick the one with the best render or silhouette match (the cadrille/CAD-Recode selection trick).
   - Ask the user for key dimensions or scale.
   - Optionally generate a TRELLIS.2 concept mesh in parallel as a visual reference or for silhouette scoring.
4. **Scan (mesh or point cloud).**
   - Prismatic parts: CAD-Recode or cadrille proposals, then IR refinement by distance fitting with a deviation report.
   - Freeform parts: segment-and-fit B-rep, or keep the mesh, flagged "non-parametric".
   - Report the deviation heat-map as the quality gate.
5. **Visual-only requests (renders, concepts).** TRELLIS.2 (MIT) or Hunyuan3D (licence-restricted). Use part-aware models for segmented concepts. Never label the output as engineering CAD.
6. Keep provenance and confidence on every artefact: whether it was measured, inferred or generated, and its deviation in mm.

### Gaps
- No published work that converts generated *visual* meshes (TRELLIS or Hunyuan output) into valid parametric CAD with reported accuracy was found.
- No quantitative data on the scale ambiguity of single-photo reconstruction for engineering use was found.
