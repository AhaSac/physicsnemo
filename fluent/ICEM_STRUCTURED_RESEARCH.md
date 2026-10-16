# ICEM 叶轮结构化六面体：资料、案例与自动化设计

2026-09-29。用户明确要求 ICEM 结构化网格、节点严格对应、批处理。现有 `icem_tetra` / `icem_tetra_prism` 不是本目标的完成证据；停止把它们作为结构化路线继续优化。本文是已查证的资料与待实现设计，尚无本项目叶轮的合格 `.blk` 模板。

## 已核实资料与案例

1. [Ansys 2024 R2 Hexa Meshing](https://ansyshelp.ansys.com/public/Views/Secured/corp/v242/en/icm_user/iuser_hexa.html)：Hexa 以贴合 CAD 的分块拓扑为基础，支持分裂块、顶点移动、边到几何曲线关联、O-grid、周期性和参数化 Replay。它是半自动的拓扑建模工具，不是更换 tetra 算法名称即可得到结构化网格。
2. [Ansys 2024 R2 Workbench/ICEM Replay](https://ansyshelp.ansys.com/public/Views/Secured/corp/v242/en/wb2_help/wb2h_IcemCFD.html)：Replay 可记录 blocking、边分布、网格和边界定义；带 blocking 的项目可执行 hexa、转换预网格并保存。导出 Fluent 使用非结构化存储格式不等于原有六面体拓扑变成四面体。
3. [Mary & Cerru，ETC 2019 离心泵案例](https://www.euroturbo.eu/paper/ETC2019-228.pdf)，PDF 第 4–5 页：完整六叶片叶轮及前后间隙采用 ICEM 多块六面体，叶轮约 490 万单元，无周期简化；图 5 可参考流道、叶轮和蜗壳网格安排。论文不是可直接运行的 blocking 脚本，不能照抄其节点编号。
4. [Jiang 等，2018 带导叶离心泵](https://www.extrica.com/article/18758)：采用 ICEM 17.1 结构化六面体，图 3 和表 3 展示分部件网格及多组密度。该案例能证明方案适用范围，不能证明本项目几何已被正确分块。
5. [Ansys 2025 R2 Tutorial Manual](https://ansyshelp.ansys.com/public/Views/Secured/corp/v252/en/pdf/Ansys_ICEM_CFD_Tutorial_Manual_2025_R2.pdf)，PDF 第 225–227 页：周期关系通过成对顶点、轴和角度定义；对应节点经旋转后应匹配。该教程版本用于方法参考，实际命令须以本机 242 接口为准。
6. 本机 242 随附 `blocking-interfaces/IcemHexaBlockingHarness/BlockingHarness-CSharp/TurbineBlade.cs`。已阅读源码：它调用 MultiZone；预期结果中明确含 1 个非结构化块、四面体、金字塔和负的最小质量。因此**不能**把这个名称带 TurbineBlade 的样例当作已验证纯结构化叶轮模板。另有 `ElbowTutorial.cs` 和 `.blk/.tin` 成对样例，可用于基础 blocking 接口验证。

## “每个点合上”的可检验含义（本项目设计）

- CAD 关联：关键 blocking 顶点关联正确的几何点，特征边关联正确的曲线；面贴合正确的 CAD 面。记录几何偏差及未关联实体，不以“最近点”代替语义匹配。
- 相邻块：使用共享拓扑实体。公共面的两侧共用节点 ID；检查边节点数、边方向和完整分布，而不仅检查四个角点。
- 周期面：只有验证几何确实周期后才采用单通道复制。检查旋转变换后的逐节点一一对应、节点数一致和最大配对误差；不将不同位置节点直接合并。
- 完整性：无非预期自由面、重复单元、悬挂节点、负体积；边界命名覆盖流域外表面；体单元全部为 HEXA_8，不能以 hex-dominant 或 MultiZone 混合网格冒充纯六面体。
- 数值质量：分别报告 ICEM 原生质量和 Fluent 正交质量/偏斜度，最终以 Fluent 对实际导出网格的检查为准。坐标“接近”与拓扑共形分别验收。

## 拟采用的批处理结构（未实施完成）

1. 从 SCDOC 提取流域拓扑、叶片数、轴线、叶片前后缘、轮毂/轮盖及接口环。已有命名只用于定位候选面，不直接固定 CAD 面序号。
2. 对几何分类：周期同形叶道可尝试单通道 O/H/J 组合再旋转；非周期缺陷、局部间隙或端部不同的模型使用独立多块拓扑。O/H/J 的选择仍需依据当前几何，不在未检查几何时预定一种。
3. 先在代表性模型生成并验证 `.blk + .tin + replay`；模板采用几何特征关联、共享拓扑和节点数约束。三个输入的面数为 110/80/82，不能据名称相似就认定可共用相同顶点编号。
4. 参数化叶道方向节点数、跨叶道节点数、轮毂到轮盖节点数、首层间距和增长率；对共享边施加等式约束，对周期边施加旋转对应约束。
5. Python 批处理驱动 ICEM Replay：加载几何 → 建立/更新 blocking → 关联与节点约束检查 → premesh → 六面体/共形检查 → 导出 → Fluent 242 复核 → CSV/JSON。任何拓扑断裂不通过坐标强行合并掩盖，单案例失败后继续下一案例。

## 本机接口线索与现实限制

`v242/icemcfd/win64_amd/lib/med_batch/hex_funcs.tcl` 中已定位 `ic_hex_set_edge_projection`、`ic_hex_merge_vertices`、`ic_hex_make_blocking_periodic`、`ic_hex_set_periodicity`、`ic_hex_check_mesh`、`ic_hex_write_blocking_mesh` 等入口；这些接口的存在不等于叶轮模板已建立。

ICEM 242 当前 `cfd_preppost` 许可证被服务器拒绝。221 能启动，但 Hexa 模块是否另需许可尚待实际验证；不得用 tetra 许可成功代替 Hexa 许可成功。Fluent 242 已实测可用。下一项 ICEM 验证应是官方简单 blocking 样例的 Hexa 许可、生成和导出，再进入实际叶轮拓扑。

后续实测更新：221 的 Hexa 初始化、blocking 读取/建立、预网格和 Fluent 导出已执行成功。官方 collar 样例产生 2,080 HEXA_8 和 525 PENTA_6，因此未当作纯六面体通过。官方 Box.tin 经脚本建立 bounding-box blocking，导出 1,650 HEXA_8，TETRA_4/PENTA_6/PYRA_5 均为 0；证据为 `outputs/hex_box_probe221/result.txt`、`probe.rpl`、`box.blk`、`box.uns`、`box.msh`。这证明基础 Hexa 批处理接口可用，尚未证明叶轮拓扑或其节点对应完成。

## 2026-09-30 模板批处理实现与实测

`icem_structured.py` 已接入 `icem_hex` 预设。模板清单必须绑定原始输入 SHA256、毫米单位 `.tin` 和 `.blk` 的 SHA256、流体块族及命名边组。`icem_hex_templates` 按模型名指定清单；`icem_hex_node_counts` 按边组覆盖节点数。未知边组、错误输入、修改过的模板和同一公共边的冲突计数会拒绝执行。原有边分布和 CAD 关联由 `.blk` 保存。

回放启用 CAD 投影，读取分块并检查无非结构化块，设置/回读边节点数，检查只产生 HEXA_8，再使用官方转换器导出。生产复核比较 Fluent 总单元数与 HEXA_8 数量，检查拓扑及边界集合。不得仅凭模板文件名或指纹断言 CAD 贴合、公共面共节点已全部验证。

实测证据：`outputs/hex_template_probe221/run4`。官方简单盒体的毫米模板设置 7×5×5 节点后，生成 96 个 HEXA_8，TETRA_4/PENTA_6/PYRA_5 全为 0，成功导出。正确节点查询为 `ic_hex_get_edge_param a b nodes`；`ic_hex_get_edge_segment_number` 实测不能用来读取该预网格节点数。失败处理已修复，避免缺失 errorInfo 再触发模态弹窗。18 项自动化测试通过。

**尚未具备 2/3/4 号实际叶轮的 `.blk` 模板，因此不能把 `icem_hex` 称为已跑通的叶轮方案。** 不提供虚构的默认叶轮顶点编号，不会回退到四面体。

后续复核：run4 的 `fluent_audit.json` 显示 96 单元、最小正交质量 0.9999999999999998、拓扑检查通过。`run5_x9` 仅将 x 方向节点从 7 改为 9，单元数由 96 变为 128，仍全部为 HEXA_8，证明覆盖参数实际生效。此处仅为接口与参数化验证，不作为叶轮质量结论。


## 2026-10-02：真实入口扇区六面体与完整叶轮限制

4号入口分区已实测生成560个纯六面体，最小正交质量0.9982685855、边界最大偏斜度0.0358871581，Fluent网格检查通过。按原生CAD轴向接缝分割成14个六面扇区，逐次分离实体并检查体积守恒；入口分区体积相对误差6.17e-7。多次对未分离的多片实体直接Split会丢失分区，已由体积检查拦截。

关键改动：保留导入BRep实体拓扑，不对已有实体执行表面build_topo；后者在试验中使扫掠报no such surface。实际体族由生成blocking决定，不一定等于请求的volfam名称。

初始网格虽然质量高，面邻接检查发现14个独立分量。原生blocking auto_merge未改变这一点。测得252对接口节点位置一致至约1.12e-13mm；使用1e-6mm容差并解除跨分区节点分类限制，删除仅由内部壁面组成的子集后，560个体单元不变、连通分量变为1、边界面为784。此结论仅适用于该入口，不可把强制节点合并无条件套用到任意薄隙几何。

网格总体积比入口CAD低0.2131%，在1%体积检查范围内；112个外壁面未通过0.001mm的严格半径检查，观测偏差约0.001674mm。原始边界名称尚未全部恢复。完整4号标准原生拓扑分块仍保留1个非结构化体块；增强映射退回二维，不是全叶轮纯六面体成功。

结果：`outputs/impeller4_inlet_sectors_v2/inlet_result.json`。连接性检查工具：`mesh_connectivity.py`，22项自动化测试通过。


## 2026-10-08：剩余区域的代表性验证

完整4号径向分区的56个区域中，21个区域包含自由体块，主要对应三种重复几何：入口/轮毂转弯、曲面叶片通道、出口/尾缘。不能仅凭面数判断可扫掠性：同为10面的两类区域结果不同。各取一个代表独立测试，均仍含自由块。

显式选择曲面通道的下侧两片面作为扫掠源面，虽得到102个六面体，但原生流程报错，Fluent网格检查失败，最小正交质量为0，体积误差3.3024%。原生一致加密至594单元后仍失败，体积误差3.2617%，说明不能靠尺寸调参修复。该候选不得作为可用模板。

入口/轮毂代表沿z=-267mm切成6面入口和15面转弯区，体积误差0.014693%，但转弯区仍未完成结构化分块。后续必须改变局部几何分块与关联，避免重复相同的自动扫掠/加密试验。

证据：`outputs/impeller4_representatives/representative_results.json`。


2026-10-09 remaining-region audit: SECTOR05 has no high arc/chord notch (max1.0107), unlike the successful SECTOR04. SECTOR01 axial CAD-seam cuts produce a 0.66585mm3 sliver and4freeblocks; rejected. Explicit circumferential sourceFACE12 still1freeblock. Remaining work requires blade-following blocking and explicit CAD associations; do not infer whole-impeller success from the verified SECTOR04 patch. Official embedded-blade O-grid tutorial: https://ansyshelp.ansys.com/public/Views/Secured/corp/v242/en/icm_tut/hexa_pipeblade_init_block_and_assoc.html
