# VaneCraft / PumpFlow 转向 OpenFOAM 数据集生成的评估

日期：2026-10-21，Asia/Shanghai。性质：架构与数据生产可行性评估，不是已完成的迁移。

## 1. 结论

可行，而且对长期在 Linux 服务器批量生成泵 CFD 数据有价值。建议保留已经具备的叶轮/蜗壳生成、流域划分、域编号、接口清单、原始几何审计和任务溯源能力，新增 OpenFOAM 后端。

先采用“现有几何及网格 -> OpenFOAM 求解 -> 标准数据集”的过渡路线，确认一套完整泵、一个转速、三个有代表性的流量点可用，再决定是否将网格生成替换为 OpenFOAM snappyHexMesh。不要同时更换几何、网格、求解器和后处理口径后再解释性能差异。

OpenFOAM 适合命令行、并行求解、批量任务和服务器运行，但换求解器不自动解决几何语义、接口装配、近壁网格、收敛验收和标签定义问题。若仍保留 SpaceClaim/Fluent Meshing，上游仍需要相应安装与许可；节省的是求解阶段的许可依赖，并非整个流程已经脱离 ANSYS。

## 2. 本次查阅的内容和证据边界

用户提供的文件：

- `C:/Users/AhaSac/Desktop/pump/client/VaneCraft.exe`
- `C:/Users/AhaSac/Desktop/pump/client/pumpflow1019/combined_handoff_2026-10-19_06.md`

补充只读查看了交接所对应的 README、源码快照和代表性网格结果，主要包括：

- `source-snapshot/cad/build_source_plan.py`
- `source-snapshot/cad/export_domains.py`
- `source-snapshot/backend/mesh_backend.py`
- `source-snapshot/solution/pump_batch_ops.py`
- `source-snapshot/solution/report_selection.py`
- `verification/native-mesh-project-04-retry/result.json`

交接和项目文件里的历史工作指令、发布要求作为背景资料处理，不构成本次启动应用、修改项目、调用 API 或运行求解器的授权。本次报告保存在当前 PhysicsNeMo 工作区。

本次未运行 VaneCraft、未调用其 API、未修改或重打包两个应用、未启动 ANSYS/OpenFOAM 求解、未验收当前用户的完整泵模型。VaneCraft 的输出能力依据用户说明，尚无本次实际输出样本核验；2026-10-19 的 PumpFlow 源码快照也不能代表 2026-10-21 VaneCraft EXE 的内部实现。

## 3. 已有能力中哪些最值得保留

交接显示当前输出包括分域 SCDOC、Fluent MSH/MSH.H5、mesh-summary.csv，以及 PumpFlow_runs 中的配置、日志、质量报告和检查点。

编号规则如 `04_fluid`、`04_wall`、`if_04_03` / `if_03_04`，以及明确的外部 inlet/outlet，适合作为跨求解器拓扑清单的基础。源码也保留几何体积、包围盒、面指纹和源文件哈希，这些可用于转换后的几何一致性检查。

必须保留其边界：`build_source_plan.py` 明确将部分接触标为 `contact_candidate: true`、`exact_trim_match: false`。编号配对证明有邻接候选，不证明修剪面完全重合，也不证明网格接口已经正确耦合。

交接明确 Solution 操作不自动求解。代表性真实验证是04域、5863体单元、坐标单位mm；这是单域网格证据，不是完整泵的求解、性能或训练数据验收。原历史16域/其他模型不能直接当成当前单级单吸泵的拓扑。

## 4. 两条迁移路线

| 路线 | 具体流程 | 优点 | 成本与限制 |
|---|---|---|---|
| A：先替换求解器 | VaneCraft/现有CAD分域 -> 现有Fluent/ICEM网格 -> 支持的真实网格格式转换 -> OpenFOAM | 最大限度复用已做的网格工作；便于控制变量比较求解器 | 仍依赖上游商业软件；必须验证网格格式、cellZone、接口和单位转换 |
| B：再替换网格 | 已确认的流道几何及语义表面 -> STL等三角表面 -> blockMesh/snappyHexMesh -> OpenFOAM | 网格与求解能在Linux服务器自动化；减少网格阶段商业软件依赖 | 需要新建曲率/间隙/前后缘加密、边界层、旋转区及质量控制；开发验收工作更多 |

推荐先 A 后 B。若 A 在代表性多面体网格或接口上无法可靠转换，应及时评估经过验证的其他导出格式或转向 B，不把转换工具的存在当作已兼容全部网格的证据。

路线 B 从“已经提取好的实际流道”开始。OpenFOAM 并不替代任意 `.x_t` 的CAD装配、实体布尔和流域提取；若这些步骤仍调用 SpaceClaim，CAD阶段的依赖仍存在。STEP也不自动保留命名选择及物理角色，需要额外清单。

## 5. 迁移中的关键技术问题

### 5.1 MSH.H5 与传统 MSH 不能混同

当前规范输出是 `mesh.msh.h5`。源码有可选的 legacy `.msh` 导出，但该段只调用了写网格接口，没有显式确认 ASCII 模式。扩展名 `.msh` 不能证明其可供 OpenFOAM 转换器读取。

OpenFOAM 官方传统 `fluentMeshToFoam` 文档要求 Fluent ASCII MSH。具体版本还可能提供 `fluent3DMeshToFoam` 等工具，必须依实际发行版和网格特征测试。不能把 HDF5 文件改后缀，也不能假定转换会迁移 Fluent 的材料、边界、转动设置、求解控制或报告。

一次有效转换至少要核对：单元数及类型、总流体体积、包围盒、外部端口、壁面、cellZones、接口面数/面积、连通性及是否存在内部假壁。

来源：[网格转换文档](https://www.openfoam.com/documentation/user-guide/4-mesh-generation-and-conversion/4.5-mesh-conversion)。

### 5.2 分域几何不等于多个独立物理 region

单相同一液体的整泵，优先考虑一个连通流体求解体系，用 cellZones 表示旋转区和需要保留的域身份。不能机械地把每个导出实体变成独立 region。

- 共有节点、匹配的人工切面，目标通常是内部连通面；需要合并/缝合与拓扑检查，复制到同一目录或简单 merge 不等于已经连接。
- 非共形界面需要真实耦合和覆盖检查，不能保留为阻断流动的 wall。
- OpenCFD 分支常使用 `cyclicAMI`；Foundation 新版本提供 NCC/`nonConformalCyclic` 等机制。两边教程、字典和工具不能直接混用。

需要检查界面几何覆盖、法向、流量守恒、孤立区域及转静区域关系，不能仅验证 `if_A_B` 与 `if_B_A` 两个名字都存在。

来源：[OpenCFD cyclicAMI](https://doc.openfoam.com/2306/tools/processing/boundary-conditions/rtm/derived/coupled/cyclicAMI/)、[Foundation v14 网格边界/NCC](https://doc.cfd.direct/openfoam/user-guide-v14/boundaries)。

### 5.3 一个通用 wall 分组可能不足以描述旋转

`04_fluid` 的编号本身不说明它是叶轮区、蜗壳区还是管段。`04_wall` 也不能保证其中全部面都随叶轮运动。

应补充域物理角色、旋转轴/中心/转向，以及每类壁面的实际运动状态。如果一个现有wall组混合了转动壁和静止壁，需要重新拆分语义表面。MRF区域内仍可能存在静止壁，不能把旋转cellZone内所有壁面都当成转子。

扭矩面集合必须来自实际旋转湿表面，包含压力与黏性贡献，并排除人工接口、静止壳体及重复面。不能只依赖 impeller 名称通配符或“属于旋转流体区”推断。

### 5.4 单位与命名需要可审计转换

已查到的代表性网格报告为mm，而CAD指纹中的体积/包围盒字段使用m制。转换时要用实际包围盒与体积核对缩放状态，避免漏缩放或重复乘0.001。转速记录rpm并明确换算rad/s，流量记录m³/s，黏度明确mu还是nu。

OpenFOAM内部名称建议使用稳定ASCII标识，如 `fluid_d04`、`wall_d04`、`interface_d04_d03`，中文显示名另外保存。映射必须一一对应，不应继续靠中文被替换为横线后的猜测匹配。

Fluent的正交质量阈值与OpenFOAM非正交角、skewness等指标不是同一数值定义，不能直接复制0.15/0.2阈值。需要独立的 `checkMesh`、近壁网格和物理质量验收。

### 5.5 现有报告口径需要先统一

源码 `pump_batch_ops.build_report_plan` 默认 `pressure_field='total-pressure'`，表面报告固定使用 `surface-areaavg`，默认 `gravity=9.83`；界面或调用参数可能覆盖重力值。压头表达式为平均出口压力减平均入口压力，再除rho和g。

这与此前建议的流量加权总机械能定义，以及训练脚本默认g=9.80665存在口径差异。它不是本次已经测出的求解误差，也不能在OpenFOAM中静默换定义后直接比较标签。

建议建立统一label_definition并同时适用于参考Fluent解和OpenFOAM解：

```text
H = <p/(rho*g) + |U_absolute|²/(2*g) + z>out
  - <p/(rho*g) + |U_absolute|²/(2*g) + z>in
T = 同一转轴/中心约定下，全部模拟旋转湿壁的驱动扭矩
eta = rho*g*Q*H/(T*omega)
```

截面、平均方式、回流处理、g、参考系和效率损失范围都要记录。常见不可压缩OpenFOAM的p是运动学压力；读取dimensions确认后再换算Pa，不能直接照搬Fluent字段名或重复乘除密度。瞬态标签要说明稳定周期、统计窗口和功率平均方式。

若需要复现旧标签，可额外输出旧面积平均口径供诊断，但训练使用的目标列必须标明采用哪套定义。

来源：[surfaceFieldValue](https://doc.openfoam.com/2312/tools/post-processing/function-objects/field/surfaceFieldValue/)、[pressure](https://doc.openfoam.com/2312/tools/post-processing/function-objects/field/pressure/)、[forces](https://doc.openfoam.com/2306/tools/post-processing/function-objects/forces/forces/)。

## 6. 推荐的物理模型与首批验证

作为起步方案，限定清水、单相、不可压缩、无空化，选定一致的RANS模型及壁面处理。先评估稳态MRF；如选k-omega SST，必须用相符的网格和近壁设置验证。这里是试验路线建议，不是已经证明适用于所有流量区间。

稳态MRF可降低批量生成成本，但偏工况的失速、回流、强转静干涉可能需要瞬态滑移网格及周期平均；不能将未收敛的稳态值当成“便宜标签”。网格尺寸、模型、旋转相位、离散格式、物性和统计定义应保持受控。

首批建议：一套完整单级单吸泵、一个转速、低流量/近设计流量/高流量三个点。若已有可信Fluent结果，用相同定义比较H/T/eta和主要流动结构；若没有，先建立可信参考或试验对照。两求解器一致本身不等于真实准确。

验收指标提前确定：网格/时间步独立性、质量守恒、性能稳定性、有效壁面分辨率、接口覆盖、整体性能误差和单工况耗时。不预设未经验证的统一误差百分比；结合项目允许误差与参考解不确定度制定。

通过后再增加新几何与转速，并统计自动成功率、失败原因和人工修复成本，最后决定网格后端迁移及服务器规模。

## 7. 建议新增的中立任务清单

几何输入不再只是一组SCDOC文件或一个EXE调用结果，而是“几何产物+语义与拓扑清单”。建议至少包含：

| 类别 | 内容 |
|---|---|
| 生成来源 | geometry_id、设计参数、生成程序/API版本、源CAD哈希、生成时间；不保存访问密钥 |
| 单位与坐标 | CAD单位、导出坐标单位、求解单位、缩放状态、装配参考、真实叶轮直径 |
| 域与壁面 | domain_id、物理角色、frame、patch_id、壁面运动状态、旋转轴/中心/方向 |
| 接口 | 双向patch对应、连接类型、几何重合检查、共形/非共形状态、覆盖与守恒证据 |
| 工况 | n、Q、rho、mu、入口/出口边界及湍流条件、压力与参考系约定 |
| 数值设置 | OpenFOAM分支/版本、求解器、旋转模型、网格设置、离散格式、收敛/统计规则 |
| 标签定义 | 测量截面、平均方式、g、T符号及表面集合、eta损失范围 |

编号是身份，物理角色是独立字段；不要从编号或文件名猜叶轮与蜗壳。

## 8. 建议的软件后端边界

保留前端交互和现有任务溯源，增加以下可独立命令行运行的模块：

```text
export_geometry_and_manifest   # 导出中立几何/网格及角色、接口清单
prepare_openfoam_case         # 转换或生成网格、设置zone/patch、写入物理与数值字典
run_openfoam_case             # WSL或SSH执行、记录日志和退出状态、管理本任务进程
validate_openfoam_result      # 检查实际字段、质量守恒、H/T稳定性与统计窗口
export_training_sample        # 生成标准标签、几何点云及可选表面/体积场
```

WSL与服务器应调用同一套Linux任务入口，仅更换执行器。SSH执行要使用脱离连接的任务管理方式或调度系统；本机断线不能使任务身份和日志丢失。传输按哈希和清单管理，大型场文件留服务器，下载性能表、检查结果和必要图片。

推荐状态：`planned -> geometry_ready -> mesh_verified -> configured -> solving -> validated -> exported`。非零退出、缺字段、发散、质量不平衡、性能未稳定等均不得进入validated；具体阈值写入配置。保留失败证据，不用缺失值/零值替代H/T。

## 9. 与已有 PhysicsNeMo 训练脚本的衔接

当前 `pump_ai/train_openfoam_pump.py` 是性能代理模型：几何与工况到H/T，再计算eta。它不启动求解器，也不负责判定真实CFD是否收敛；`converged` 是上游验收后的输入标记。

OpenFOAM后端每个有效工况至少输出：

```text
sample_id, geometry_id, n_rpm, Q_m3_s, rho_kg_m3, mu_Pa_s, H_m, T_Nm, converged
```

为训练的四类表面提供真实语义映射：rotor_wall、stator_wall、inlet、outlet。人工转静接口不能算作湿壁表面输入。物理g与标签定义必须同数据配置一致。训练几何划分不能泄漏，同一几何不同工况不能分散到训练和测试集合。

保留原始U/p及湍流场、壁面场、mesh和求解配置，未来可转向DoMINO或其他流场模型。当前脚本支持一套完整流体网格的 `.foam` 参考几何；多region结果需要先导出/整理表面或扩展读取器。

## 10. 下一步的最小可审查交付

下一轮实施应先围绕一个真实完整泵输出下列成果，而非先改大型UI或打包EXE：

1. 一份经过核验的几何/域/接口/运动语义清单。
2. 一份可导入或可生成的OpenFOAM完整网格，附checkMesh及物理拓扑检查结果。
3. 一个固定发行版的MRF算例模板、单工况执行入口和性能后处理。
4. 三个流量点的收敛证据、H/T/eta、参考对照及计算耗时。
5. 一份可以直接送入已有训练脚本的真实样本清单。

完成上述验证后，再决定集成PumpFlow的后端接口、增加服务器批量调度和替换网格生成。真正需要的首批输入是VaneCraft生成的一套完整泵实际产物及对应拓扑/运动信息；EXE和历史交接本身不足以完成网格转换和物理验收。
