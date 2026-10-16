# 实测与限制

2026-09-29，Windows，ANSYS 2024 R2，PyFluent 0.28.1，项目独立 Python 3.12 环境。

- 输入目录：`C:/Users/AhaSac/Desktop/pump/0907wang/xt/imperfectimpeller`。
- 排除 `1impeller.scdoc`。其余三份压缩包完整、可读取命名信息；压缩包完整不等于几何无缺陷。
- SpaceClaim 已实测打开 3 号流域，80 个面；命名脚本成功生成副本及面覆盖/几何特征报告。
- 3 号 Fluent 基准：862,911 个多面体单元，最小正交质量 0.2020892。
- 对该体网格实测 ImproveVolumeMesh：最小正交质量 0.35060235，单元数不变。
- 对基准表面单独实测 ImproveSurfaceMesh：最大偏斜度由约 0.95 降为 0.64669138；这些独立实验不能冒充同一个最终网格同时通过。
- 质量查询问题根因为 PyFluent 返回 Protobuf RepeatedScalarContainer，而请求序列化只接受 Python list/tuple；未转换直接回传导致参数丢失。已统一转换并增加真实 Protobuf 容器回归测试。生产流程按面区名称逐区查询，排除 CAD faceting 和内部面。
- ICEM 242 实机启动失败：cfd_preppost / FlexNet -25,147，许可证服务器不支持此版本功能。Tcl 生成器依据本机 242 程序签名编写，网格阶段尚未实机验证。
- codex-autoresearch 的迭代记录器拒绝包含既有未跟踪 resource/ 数据的工作区；没有提交、清理或回滚用户数据。工程进展改由本文件及各案例独立日志记录。
- 用户已将体质量接受下限放宽为 >=0.2，以可配置多方案、批处理为主要交付；严格 >0.3 预设仍保留。

正式端到端结果以 `outputs/runs/*/summary.csv` 和各案例 `quality.json` 为准。

后续验证：2/3/4 号 SpaceClaim 命名副本全部通过，面数 110/80/82；3 号几何特征模板恢复命名通过。ICEM 六份 replay 已生成。增加源文件、表面参数和网格 SHA256 校验的面网格缓存，以降低多方案比较的重复成本。

2026-09-29 后续进展：三个模型已各有一份 Fluent 合格网格，具体路径和数值见 VALIDATION.md。用户澄清其常用参数为 polyhedra、面尺寸 0.04–8 mm、其他默认、体改善目标 0.3；新增 user_baseline 保留原生 smooth-transition 和原生改善工作流。原生默认体改善目标 0.15 的对照为 768,776 单元、最小正交质量 0.154139、最终面偏斜度 0.845693，不合格；不能冒充用户的 0.3 设置。保存后旧工作流步骤再执行未改变质量，正在以 0.3 从头复现。修复 Fluent TUI 对 Windows 路径中反斜杠转义的问题，改用正斜杠路径。

用户明确 ICEM 目标为结构化六面体，停止用四面体优化代替。已查官方 Replay/Hexa 文档及离心泵论文，研究记录见 ICEM_STRUCTURED_RESEARCH.md。221 官方 Box 几何的 Hexa 脚本实测生成、保存 blocking 并导出 1,650 个纯六面体；叶轮模板仍待建立。全程原始四份 SCDOC 哈希未改变。

2026-09-29: Fresh native user_baseline target 0.3 completed at 20260929_200419_47400: 768776 cells, min orthogonal 0.2704451118, surface-generation skewness 0.7778507902, final boundary skewness 0.8456929403; topology and names pass, surface acceptance fails. Added configurable native surface improvement arguments for the next controlled experiment. Cache key now includes improvement settings to prevent reuse across differing improvement configurations.

2026-09-29 user steering: repeatable execution, surface skewness informational, normal orthogonal >=0.2, complex >=0.15, improve target 0.3. Fixed full configs and run_fixed.ps1 added; 13 tests passed; historical reports unchanged. SpaceClaim master topology exported all three, vertex identity requires further audit.
Fixed entry end-to-end validation started: 20260929_220214_50972/3impeller/pump_repeatable. Prior optional surface refinement 20260929_215818_39564 cancelled after user reprioritization; cancellation recorded separately. Fixed config invariance checks added, 14 tests pass. Default CLI scheme now pump_repeatable.

Fixed entry validation COMPLETE: 20260929_220214_50972/3impeller/pump_repeatable, exit 0, passed=true, 768776 cells, orthogonal minimum 0.2704451118399696, 609.485 seconds. Five native argument snapshots match prior baseline; exported mesh hash verified. Current concrete fixed Fluent deliverable validated on model 3; ICEM impeller structured blocking and fixed preset models 2/4 remain outstanding.

Topology identity fix verified on all three CAD files: V/E/F = 218/351/110, 149/244/80, 136/241/82; all endpoint incidence and directed face-loop closure checks passed. Closed edge fin counts pass. No coordinate-only merging. Next: add ICEM blocking-template batch replay with source/template fingerprints and pure-hexa gate.

ICEM template run1 hit an error-reporting scope bug ($errorInfo), causing a modal dialog; fixed both replay backends to guard ::errorInfo. Run2 now exits with explicit edge-count mismatch. Local 221 wrapper adds one to the native segment count, so its return is node count; corrected comparison. Fluent fixed 2impeller completed: 1010472 cells, orthogonal 0.3000105289; 4impeller started automatically.

2026-09-30: All fixed Fluent models completed. 4impeller: 470699 cells, orthogonal 0.3000472316, 393.985 s. ICEM template root cause resolved: curve segment query is not the grid node count; use ic_hex_get_edge_param nodes. Production replay run4 generated 96 HEXA_8, no tetra/prism/pyramid, exported Fluent mesh. Fixture only; no impeller blocking template claimed.

ICEM run4 exported mesh independently read by Fluent 242: 96 cells, minimum orthogonal 0.9999999999999998, topology check passed. Run5_x9 changes x nodes 7->9 with y/z fixed at5: 128 HEXA_8, no other volume types, export success. Template batch parameterization is mechanically verified on the fixture only.

Actual impeller3 blocking probe: 80 CAD surfaces, build-topology successful. Installed 221 runtime rejects documented -block_type/-volfam; runtime usage provides -mapped/-mixed flags instead. Next bounded experiment uses -inherited -mapped, retaining all geometry and no defeaturing. Wall adjacency reveals 10 components on model3 and14 on models2/4; no assumption of interchangeable CAD face IDs.

Actual impeller3 -mapped trial reached the 180-second limit after repeated nonparallel source/target loop messages; owned ICEM process tree terminated, no complete blocking candidate. Periodicity probe exposed concrete Face.ProjectPoint return type SurfaceEvaluation; corrected .Point extraction.

CAD projection controls: zero-angle max residual on 2/3 is already 0.0410745/0.0416957 mm, so rotational maxima at the same level cannot establish nonperiodicity. Model4 identity residual 9.4e-7 mm, +/-360/7 residuals 9.5e-6/1.24e-4 mm. These are sampled diagnostics only. All three topology adjacency checks pass; exported independent wall patches 14/10/14. Prepared actual model4 mapped trial from SCDOC because its CAD projection residual and wall-face topology are cleaner.

## 2026-10-01 ICEM directed edge distribution
Added positive finite spacing/growth overrides with reversed-edge normalization and shared-edge conflict rejection. Real ICEM221 run6_spacing SUCCESS, pure96 HEXA_8. Requested h1/h2=2,r1/r2=1.2,lmax=8; actual h1/h2~1.99976,r1/r2~2.3408. Actual parameter TSV retained: requests are not exact growth guarantees. Impeller blocking remains unfinished.

4impeller detached CAD split probe: z=-267,-271.25,-284 mm all produce2 pieces. At -267 mm faces10/74, volume relative difference0.0003501. No source modification. This is a candidate partition only, not a conformal interface or hexa success. Directed distribution regression suite20 passed.

Partition inlet sweep180s timeout before import-stage reporting, med_batch CPU~1.9s, no candidate. Cannot attribute to blocking convergence; investigate CAD import. run6 spacing Fluent audit96 cells minorth0.9999999999999998, meshcheckpass,volume10440.

Parasolid inlet import completed immediately (IMPORT_END); rejected expected missing named fluid family. SCDOC import stall isolated from blocking. Next diagnostic explicitly assigns one imported body/material to FLUID_REGION; original boundary name certification remains pending.

Explicit inlet XT sweep finished: native ERROR Meshing failed during creation of3D blocking / Found free block in swept body; dimension2. Strict dimension gate rejected; no3D mesh claimed. Need geometry-specific blocking rather than reuse automatic swept surface candidate. No remaining probe job intentionally running.

Offset inlet split -266.5mm still10 faces, so no tiny-face hypothesis supported. Actual ICEM face audit shows annulus inner7 cylindrical pieces andouter1; caparea8114.21mm2. Next split along actual vertex radial directions on detached inlet CAD for mapped sectors.

Sector preparation initial run exposed direct DesignBody vs occurrence API difference (.Master absent on direct body). Fixed dispatch before retry; no geometry partition was produced by that attempt.

First repeated in-place sector split lost85.7%volume, rejected candidate. Corrected to separate pieces after each plane and split each piece separately; assert volume conservation perstage. Select axial seams only to avoid cap-only tiny angular features. Failed exported v1 sectors must not be used.

Sector preparation v2 success:14pieces each6faces12edges; relativevolumeerror6.17e-7. Split each detached piece at each axial-seam radial plane. Proceed actual multisector3Dblocking test.

14sector sweep rejected endpoint discrepancies3.8e-6 to1.57421e-5mm withtopologytol1e-6mm. Next measured tolerance1e-4mm (0.1micrometre), below minmeshsize0.04mm by400x; do not interpret as arbitrarily closing physical gaps.

Tolerance1e-4 removed endpoint mismatch but3Dfailed; logs repeatedly no such surface and open loop after rebuild. Next diagnostic preserves imported native BRep topology (GUI3Dmultizone does not rebuild surface topology).

Preserving native BRep topology produced3Dstructuredblocking unstructuredcount0 for14realinletsectors. First meshselection FLUID_REGION empty: actualblockingfamilies PART_i_i_1_MATPOINT. Saved scoped inlet-only template and now replay actual14fluidfamilies with productionpurehex/cellpositive checks.

Actual 4impeller inlet-only template replay SUCCESS560HEXA_8, zeroTETRA4/PENTA6/PYRA5. Fullmesh topological dimension3. Fluent quality and component/connectivity audit in progress; do not yet claim shared interfaces. NativeBRep preservation now tested on whole4impeller.

Inlet560hex Fluent minorth0.9982685855, skew0.035887, meshcheckpass. ASCIIfaceadjacency reveals14components40cells each: NOT conformal. Test native blocking auto_merge before regen; rawqualityalone insufficient.

Blocking auto_merge no change: still14components. Next explicit tolerance1e-4mm node merge and delete only internal-wall subset; enforce560volumehexunchanged then independentfaceconnectivityaudit.

Full4scdoc reimport300s timeout before reporting, no blockingresult. Retryfromprevious untouched pre-build-topo TIN to avoidCADimportstall. Inlet merge196/252pairs dueclassification: all252duplicatepairs actuallycoincidewithin1.12e-13mm. Retrytol1e-6 withforceclassificationoverride; preservevolumecells andremoveinternalfacesonly.

Full4nativeTIN completed3Dblocking quickly, but1unstructuredvolume remains; rejectedpurehex readiness. Next exactGUIAggressive mapping removesautomatic_sweep. Inletinterfacefullmerge252nodes at1e-6mm gives560cells1component784boundaryfaces (expected physical boundary), no cellcountchange.

Conformal inlet Fluent minorth0.9982685855, maxskew0.0358871581, volume129609.5mm3 vsCAD129886.2444 error0.2130678%, meshcheckpass. Boundary classification strict0.001mm failed112outerfaces because projectedcylinder deviation~0.001674mm; no claimperfectCADfit. Entire4aggressivefailed3Dsweep->dimension2. StandardnativeTIN3D retains1unstructuredvolume; notpurehexready.

Full4block audit identifiesfree109 plus3fluid-sweptblocks; mostotherreportedmappedblocksORFN. Thusnotalmost-completewholehexa. Next fulloriginal4CAD radialsector partition usingverified inletaxisdirections, allvolumechecked at eachplane beforeexport.

Full4radial partition completed56pieces with8-17faces each, volume relativeerror0.0006413293 (0.06413%). No volume omissions beyondreportedtolerance. Next native-topology MultiZone onall56actualbodies; require3D,zeroUB,purepositiveHEXA8 beforeexport.

Full4sector MultiZone terminal:3Ddimension but26unstructuredblocks, rejected, nofullmesh. Radialpartition alone insufficient. Productionhexa replay now exportsASCIIadjacency and backendrejectsmulticomponentfluid; realinlet replay560hex14components verifiesnegativegate data generation. Conformal560hex1component remainspositiveaudit.22tests pass.

Representative CADexportverified:SECTOR_01(17faces) spansinlet/hubturn;SECTOR_04(10faces) spanscurvedbladechannel;SECTOR_05(16faces) spansoutlet/trailingregionwithsmalltriangularfaces. Test eachalone to distinguish intrinsicmappingfailure frommultibodycoupling.

Representative standalone result {"name": "SECTOR_01", "returncode": 0, "summary": ["blocking_dimension=3", "unstructured_blocks=1", "ERROR: Unstructured blocks remain"]}

Representative standalone result {"name": "SECTOR_04", "returncode": 0, "summary": ["blocking_dimension=3", "unstructured_blocks=1", "ERROR: Unstructured blocks remain"]}

Representative standalone result {"name": "SECTOR_05", "returncode": 0, "summary": ["blocking_dimension=3", "unstructured_blocks=1", "ERROR: Unstructured blocks remain"]}

Explicit axial source result {"name": "SECTOR_04", "returncode": 0, "summary": ["source_faces=FACE11 FACE46", "ERROR: Found free block in swept body with auto-source selection ", "blocking_dimension=3", "unstructured_blocks=0", "hexes=102 tets=0 prisms=0 pyramids=0", "CANDIDATE_SAVED"]}

Explicit axial source result {"name": "SECTOR_05", "returncode": 0, "summary": ["source_faces=FACE58 FACE63 FACE59 FACE62", "multizone_result=ERROR: Found free block in swept body with auto-source selection ", "blocking_dimension=3", "unstructured_blocks=1", "ERROR: Unstructured blocks remain"]}

SECTOR04 explicit source102hex rejected: Fluent minorth0, skew2.72649, meshcheckfailed,volumeerror3.3024%. Test consistent2x edge refinement on sameblocking to distinguishdiscretization from topology/association errors. SECTOR01z=-267 split2pieces6/15faces, volumeerror0.014693%.

2026-10-08 representative audit: native independent01/04/05 each1freeblock. Explicit axial04 generated102hex butfailedmeshcheck,minorth0,volumeerror3.3024%;2xrefinement594hex stillfailed,minorth0,volumeerror3.2617%. Axial05still1freeblock. Hub01split6/15faces retained1freeblock. These are rejected diagnostics, not deliverable meshes. Nextworkmustchangegeometricblocking/association, notmerelyrefinesizing. Consolidated representative_results.json retained.

Both102/594hex failures concentratedinboundaryfamiliesFAM0:44(FACE46,bottomsource6edges) andFAM0:29(FACE41,sidewall). Testgeometrysplit throughactualsourceface reflexcorner/oppositevertex; rejectifnoclearconcavity orvolumeerror>.001. This changesblockinggeometry ratherthansizing.

Source-face endpoint polygon has4convexcorners plus2collinearpoints, so reflexcorner-diagonal hypothesis rejected. Next uses actualcurvededges arc/chordratio andmaximumchorddeviation to identify reentrantboundary, then shortest cross-gapcut towardotheredges; volumechecked.

Truecurve notch identified:arc/chord14.2083, crossgap7.2252mm. Transverseplane partitionsSECTOR04 into3pieces8/6/10faces,volumeerror0.0885269%. Testnative3Dmappingonactual3pieces.

Curve-driven splitSECTOR04native3D0freeblock144purehex. Joinedmeshconnectivity {"cells": 144, "face_connected_components": 3, "component_cell_counts": [24, 30, 90], "faces": 558, "internal_faces": 306, "boundary_faces": 252, "single_connected_volume": false, "scope": "Face connectivity only; also require geometric and mesh-quality audits."}; awaitingindependentquality/volume andsplitplane boundaryaudit beforeacceptance.

Curve-guided144hex minorth0.73646,skew0.25959,volumeerror0.2653%, but3components persist: only10nodesmerged. Identified11coincidentblockingedgepairs onnewcutplane. Testingexplicitnativeedge count/distributionmatching beforemeshgeneration.

Native match_edges rejectsfirstcoincident-endpoint pair44/45->82/83 (edgesdontmatch), so cannotassumeendpointcoincidencecertifiesedgegeometry. Nextcopyrequesteddistribution only andindependentlycheck resultingcoordinates/connectivity.

2026-10-09 uniform interface experiment: pairededgeactualnodecounts alreadyequal; setbothendsuniformspacing/ratio1 atsamecounts andauditconnectivity separately. Rawstatus hexes=210;merge=0 0 20 {} 415;SUCCESS;

2026-10-09 shared topology diagnostic: CAD cutface pairs areas230.9957/230.9956 and213.848151/213.848151mm2; ShareTopology tolerance0.001mm preserves volume exactly. Native ICEM result ["blocking_dimension=3", "unstructured_blocks=0", "hexes=144 tets=0 prisms=0 pyramids=0", "merge=0 0 10 {} 307", "CANDIDATE_SAVED"]

2026-10-09 native blocking selected-vertex merge tolerance0.0001mm, update_projections; free_blocks=0;hexes=210;merge=0 0 0 {} 371;SUCCESS;

2026-10-09 merged blocking independent verification {"scope": "SECTOR_04 diagnostic only", "cut_plane_faces": {"internal": 27, "boundary": 3}, "complete_impeller": false, "cell_quality": {"count": 210, "min": 0.7363509486203252, "max": 0.9861797939435784, "mean": 0.9505903510454782, "raw": [210, 0.7363509486203252, 0.9861797939435784, 0.9505903510454782, 0.0, 0]}, "max_boundary_skewness": 0.295012546606889, "mesh_check_ok": true}

2026-10-09 saved merged blocking replay {"cells": 210, "face_connected_components": 1, "component_cell_counts": [210], "faces": 766, "internal_faces": 494, "boundary_faces": 272, "single_connected_volume": true, "scope": "Face connectivity only; also require geometric and mesh-quality audits.", "same_ascii_mesh_as_first_run": false}

2026-10-09 CAD residual boundary audit: three near-cut wall facets map toward original curved face2; maxvertexdistance0.004039mm and maxcentroiddistance0.278514mm. Do not collapse this strip; refine curvature approximation. Full impeller remains incomplete.

2026-10-09 saved blocking replay same coordinates and face geometry at1e-8mm despite renumbering. First refinement failed due flat edge-list API; nestedpairs corrected. Refined2 result {"cells": 1680, "face_connected_components": 1, "component_cell_counts": [1680], "faces": 5584, "internal_faces": 4496, "boundary_faces": 1088, "single_connected_volume": true, "scope": "Face connectivity only; also require geometric and mesh-quality audits.", "cell_quality": {"count": 1680, "min": 0.746219399583858, "max": 0.9940333405530642, "mean": 0.9576817401977042, "raw": [1680, 0.746219399583858, 0.9940333405530642, 0.9576817401977042, 0.0, 0]}, "max_boundary_skewness": 0.3110678394454398, "mesh_check_ok": true}

2026-10-09 SECTOR05 curve-notch hypothesis rejected: all bottom curve arc/chord<=1.0107, unlike SECTOR04 ratio14.2; no geometry exported. Next SECTOR01 partitions at actual CAD patch elevations -267,-271.2156,-298.06758 mm; volume guarded.

2026-10-09 SECTOR01 CAD station split:5pieces6/8/7/12/4faces, smallest0.66585mm3,volumeerror0.0788373%; native sweep ["ERROR: Found free block in swept body with auto-source selection ", "blocking_dimension=3", "unstructured_blocks=4", "ERROR: Unstructured blocks remain"]

2026-10-09 original SECTOR01 circumferential source at CAD radial plane y/x0.209271 ["source_faces=FACE12", "ERROR: Found free block in swept body with auto-source selection ", "blocking_dimension=3", "unstructured_blocks=1", "ERROR: Unstructured blocks remain"]

2026-10-09 SECTOR01 blade-leading-edge split from minimum radius points:3pieces10/15/8faces;volumeerror0.0454065%;native ["blocking_dimension=3", "unstructured_blocks=2", "ERROR: Unstructured blocks remain"]

2026-10-09 documented robust MultiZone decomposition comparison [{"case": "SECTOR_01", "result": ["blocking_dimension=3", "unstructured_blocks=1", "ERROR: Unstructured blocks remain"]}, {"case": "SECTOR_05", "result": ["blocking_dimension=3", "unstructured_blocks=1", "ERROR: Unstructured blocks remain"]}]

2026-10-09 native short-edge blocking merge selected from measured CAD edges:01shortedges0.0318/0.0330mm threshold0.04;05shortedges0.575/0.621mm threshold0.65; [{"case": "SECTOR_01", "short_edge_mm": 0.04, "result": ["blocking_dimension=3", "unstructured_blocks=1", "ERROR: Unstructured blocks remain"]}, {"case": "SECTOR_05", "short_edge_mm": 0.65, "result": ["blocking_dimension=3", "unstructured_blocks=1", "ERROR: Unstructured blocks remain"]}]

2026-10-09 existing blade-face extension SplitBody.ByCutter rejected by SpaceClaim (cannot split body). New hypothesis: independent ruled cutter following an isoparametric blade-leading-edge curve, sampled from actual NURBS.

2026-10-09 automatic SpaceClaim startup path fails before script entry for242and221, both exit0; explicit242environment/cwd alsofails. No currentSpaceClaimprocessobserved. License servicesrunning, checkoutnotproven. User manualstartupcheckrequested. Fixed prepare stale-report acceptance with invocationUUID and exportedSHA256; cachehashverified;24regressiontests pass. ActualnewSpaceClaimexport remainsunverified. Curvedcutter params retained; no successfulcutclaimed.

2026-10-09 startup recovered by hidden Windows normal-window launch without /Headless=True. Curved leading-edge independent cutter succeeded;isocurveerror1.12e-13mm,3pieces15/10/8faces,volumeerror0.0772289%;ICEM ["ERROR: ICEM_LICENSE_UNAVAILABLE"]

2026-10-09 curved cutter ICEM via native PowerShell Start-Process acquiredlicense and reports2freeblocks. Python-native and Python-ShellExecute launch probes stillsilentexit; signedPSfilepolicy preventsnestedlauncher; environmentvalues equal case-insensitively. No systempolicy changed. Next curve-following meridional station atleadingedge radius minus0.5mm, combinedwithmedianleadingedgecut; cumulativevolume guarded.

2026-10-10 combined leading-edge median cutter and upstream meridional station:5pieces13/8/8/9/8faces,cumulative CADvolumeerror0.062635%;nativeICEM1freeblock17 PART_1_1_1_MATPOINT. Other4families mapped/swept, but no wholepartition meshquality verified. Retain topology improvement. Pythonchild launch unresolved; directPSStart-Process nativeSC242andICEM221 bothexecuted successfully. AllSigned policy remainsunchanged; no unsignedPSlauncher integrated.

2026-10-10 block17 investigation: ICEM221 native launch works outside sandbox; ordinary sandbox license-client startup fails. Read-only TIN/CAD endpoint matching identifies block17 as REGION_0 (5906.118328 mm3), maximum coordinate mismatch 4.65e-12 mm. Twelve scoped trials retained in outputs/impeller4_representatives/SECTOR_01_le_station/block17_20261010. Radial -160-degree cut and local CAD patch cuts preserve cumulative volume error about 0.06006%, but no whole-partition zero-free pure-hex conformal mesh was achieved. Standalone body2 (4.016422 mm3) generates6 pure hex, Fluent minorth0.835094, skew0.513812; body3 (3137.224883 mm3) generates164 pure hex, minorth0.638364, skew0.557232. Both pass meshcheck and each is one component; interfaces/names notverified. Residual regions2653.279916 and112.427154 mm3 still each have a free block. Additional rejected diagnostics: body4 has80hex+70prisms despitezero-free; body6 has450purehex butminorth0.015857. Other independent purehex bodies5/7 have24/82cells andminorth0.917933/0.711908. Source SCDOC/XT/TIN/BLK/result_summary fingerprints unchanged. Auto topology iteration closed as soft blocker after three distinct strategy routes failed; whole impeller/original objective incomplete. Next requires manual multiblock/Y/O-grid design on actual trim loops, then geometric conformity, purehex, mesh quality, connected interfaces and names. See block17_20261010/FINAL_REPORT.json, SUMMARY.md and individual verification.json. Legacy autoresearch state preserved; no background or replacement goal created.

### 2026-10-10 block17 离散边界与原生手动分块继续试验
用户授权继续和网络研究。官方资源、trial13–21 已归档至 SECTOR_01_le_station/block17_20261010。两片残余分别生成1024/5184纯 HEXA_8、零 free block；Fluent最小正交质量0.368911/0.208509，体积误差0.630126%/0.947847%，mesh check及独立单连通通过。小片最大边界偏斜仍0.892079。离散点452个、加密测得弦误差最大0.004952084mm；ICEM诊断TIN实际导入成功。接口共节点、表面覆盖及命名未认证，整圈未完成。最新依据 CONTINUATION_REPORT.md/json，前12次历史报告保留。


### 2026-10-10 长期block17目标，迭代1–5
已建官方goal及隔离worktree前台日志。实际CAD审计揭示默认最近面投影问题；trial23轴向加密质量改善但面心误差不改善；trial24周向加密误差降低74%；trial26/27显式关联原CAD曲线，大/小块minOrth .888534/.243554、体积误差 .008859%/.068991%。节点、面心及原边点到网格的反向检查通过节点.005mm/其他.02mm采样门槛，每个原CAD面有覆盖样本。主指标4→5，迭代5 keep。共同接口当前369对325节点，尚未共节点；整体、命名未认证。证据 LONG_GOAL_STATUS.md/json。


## 2026-10-10 block17 原生共节点迭代22检查点
长期目标 active，完整验收5/8。trial39 已将主区、下三角区、顶帽三片联合成79,200个原生纯HEXA_8：minOrth0.243363、体积误差0.0109180%、Fluent检查和单连通通过，内部人工wall=0。上下接口分别960/480内部四边形、1025/533共用节点。前向CAD贴合节点最大0.00382181mm、面心0.00437553mm，但真实0.038043mm²顶帽小面没有面心覆盖，需末端短角段拓扑分割。trial41另一侧十块拓扑迁移因负体积与minOrth0失败，已拒绝；低体积误差不能证明有效。trial42恢复原生另一侧baseline：mapped72+swept8/10，依据实际台阶与轴向分带重新设计共节点接口。四片整体、CAD双向覆盖和命名未完成，不能将三片联合当整个block17完成。原CAD/初始TIN/BLK哈希已核对未变。代码提交e60c811f，规范运行状态C:/Users/AhaSac/Desktop/pump/autoresearch-results，最新证据与下一步见 outputs/impeller4_representatives/SECTOR_01_le_station/block17_20261010/LONG_GOAL_STATUS.md。本轮补充官方资源见该目录web_resources_20261010.md。


## 2026-10-10 原block17完整验收完成（iteration33）

前缘原block17已通过全部8/8验收；最终trial52_named_whole，117960原生HEXA_8，7mapped+2swept，zero free，最小正交质量0.32765357，Fluent检查通过，单连通，内部人工wall为零；实际共享接口1440四边形/1517共节点。原CAD全部13面/31条自适应离散曲线覆盖，节点最大距离0.00219421mm，面心0.01574538mm，反向曲线0.00216029mm。关键为保留自然swept台阶分带、只投影真实外边界、传播微小曲面特征，以及原生proj3精确B-spline投影；未放宽几何/质量阈值。

原区域CAD没有命名选择，已从完整原4impeller CAD真实命名面恢复上壁/下壁/叶片壁。全部16138外边界四边形唯一分类，另四个原分区切面使用interface类型24；三面实际相邻原region1/2/3，外sector切面12真实方位−168.180628°，最终名interface_sector01_cut_face12。原生ICEM文件保留内部家族名；最终物理命名通过Fluent边界元数据分区恢复，全部坐标、单元类型、面绕向和邻接未变。native51参数化重放全部网格数据与50/52一致，避免按不稳定faceID套旧命名。

交付：outputs/impeller4_representatives/SECTOR_01_le_station/block17_20261010/trial52_named_whole/DELIVERY.md、mesh.msh、named_binary.msh.h5。完整证据与参数/重放程序已归档，goal_control/block17_candidate.json为最终8/8清单。隔离代码提交3047a49cff1a241a90246291d0ca5d0e91d86eac，权威日志C:/Users/AhaSac/Desktop/pump/autoresearch-results iteration33。原regions.scdoc/x_t及初始TIN/BLK哈希复核未变。

仅原block17完成；整个叶轮其他区域、外部接口装配/配对与流场求解尚未完成。当前坐标为毫米，进入SI米制求解前应用0.001缩放。此前5/8、6/8、7/8为历史中间状态，不再是当前完成状态。
