# 叶轮网格自动化（ANSYS 2024 R2）

统一 Python 入口调用 SpaceClaim、Fluent Meshing 和 ICEM。默认使用三个已有流域模型 `2impeller / 3impeller / 4impeller`，排除损坏的 `1impeller`。原始 SCDOC 不覆盖。

推荐固定入口（从项目目录调用）：

```powershell
# 三个模型顺序批处理，每次同一配置
.\fluent\run_fixed.ps1
# 单个模型，最低正交质量 0.2
.\fluent\run_fixed.ps1 -Models 3impeller
# 复杂叶轮最低正交质量 0.15；生成参数不变
.\fluent\run_fixed.ps1 -Models 3impeller -ComplexGeometry
# 只预览，不运行
.\fluent\run_fixed.ps1 -Plan
```

固定方案：ANSYS 2024 R2、Watertight Geometry、polyhedra、尺寸 0.04–8 mm、4 核、原生默认面改善、原生 smooth-transition 边界层、体改善 Quality Limit = 0.3。完整配置为 `repeatable_config.json` / `complex_config.json`，两者只改变验收下限。面偏斜度保留在报告中，不影响这两个方案验收；仍要求有效单元、拓扑检查通过及命名完整。不自动调参或切换网格类型。

该生成方案已在 3 号从头实测：768,776 单元，最小正交质量 **0.270445**。原始记录为 `outputs/runs/20260929_200419_47400/3impeller/user_baseline`。历史报告按当时表面限制标记未通过，保留不改；固定入口输出新的独立报告。每次相同设置不保证文件逐字节相同，并行网格算法可能有细微差异。原生未覆盖参数由固定的 2024 R2 版本决定，`native_*_arguments.json` 记录显式传入值。配置中的非原生分支参数（如 `boundary_layers: 0`）不覆盖原生默认边界层。


固定入口已复跑验证：`outputs/runs/20260929_220214_50972/3impeller/pump_repeatable`，退出码 0、768,776 单元、最小正交质量 0.270445，与旧基准一致，约 10.2 分钟。该目录提供实际 `mesh.msh.h5`、`quality.json` 和逐步参数对比。

截至 2026-09-30，三个模型的固定方案全部通过（按用户最新正交质量标准），实际网格校验和与报告一致：

| 模型 | 单元数 | 最小正交质量 | 耗时 |
|---|---:|---:|---:|
| 2impeller | 1,010,472 | 0.3000105 | 11.0 分钟 |
| 3impeller | 768,776 | 0.2704451 | 10.2 分钟 |
| 4impeller | 470,699 | 0.3000472 | 6.6 分钟 |

完整汇总及网格路径见 `outputs/fixed_results.csv`。3 号两次独立生成的单元数、质量值和五步原生实参一致；2/4 号目前各完成一次固定入口验证。


用户指定的 ICEM 目标已明确为结构化六面体；现有 tetra/prism 分支仅保留历史诊断用途，不构成该目标的完成。资料与待实现设计见 [ICEM_STRUCTURED_RESEARCH.md](ICEM_STRUCTURED_RESEARCH.md)。

**当前验证范围：** SpaceClaim 的三个模型命名及 3 号模板恢复已实测；Fluent 3 号最终多面体网格重读复核通过：862,514 个单元，最终边界面最大偏斜度 **0.5879051**、体最小正交质量 **0.3674325**，生成阶段三角面最大偏斜度 0.6466914。更多方案的状态查 `outputs/runs/*/summary.csv`。ICEM 242 被本机 `cfd_preppost` 许可证阻断（FlexNet -25,147）；ICEM 221 已验证可获取许可证并保留命名导入，提供显式备用配置。

## 使用

3 号 `poly_hexcore` 也已通过：2,837,450 单元，最大边界面偏斜度 0.5879051，最小正交质量 0.3500098。ICEM 221 四面体已完成实际生成、官方转换器导出及 Fluent 242 复核，但质量未达标（最大边界面偏斜度 0.9642730、最小正交质量 0.0201091）；未将它标为合格网格。ICEM 242 的许可证限制仍存在。

在 `physicsnemo` 项目目录打开 PowerShell。本机已安装项目独立 Python 3.12 + PyFluent 0.28.1。

```powershell
# 查看全部预设与参数
.\fluent\.venv312\Scripts\python.exe .\fluent\run_meshing.py presets

# 仅预览任务，不启动 ANSYS
.\fluent\.venv312\Scripts\python.exe .\fluent\run_meshing.py plan --models 3impeller --schemes poly tetra_prism

# 规范化流域及各面命名，验证覆盖率，保存三个副本
.\fluent\.venv312\Scripts\python.exe .\fluent\run_meshing.py prepare

# 运行一个模型的一种方案
.\fluent\.venv312\Scripts\python.exe -u .\fluent\run_meshing.py mesh --models 3impeller --schemes poly

# 三个模型 × 两种方案，逐案例运行；失败后继续下一案例
.\fluent\.venv312\Scripts\python.exe -u .\fluent\run_meshing.py batch --schemes poly tetra_prism --cores 4

# 保留原有命名、直接网格化，跳过 SpaceClaim
.\fluent\.venv312\Scripts\python.exe -u .\fluent\run_meshing.py batch --models 3impeller --schemes poly --skip-prepare

# 用 JSON 覆盖尺寸、边界层、改善参数
.\fluent\.venv312\Scripts\python.exe -u .\fluent\run_meshing.py batch --schemes poly_prism --config .\fluent\config_fine.example.json

# 不需要许可证即可生成三个模型的 ICEM replay
.\fluent\.venv312\Scripts\python.exe .\fluent\run_meshing.py replay --schemes icem_tetra icem_tetra_prism

# 有有效 ICEM 2024 R2 许可证后执行；导出后由 PyFluent 检查
.\fluent\.venv312\Scripts\python.exe -u .\fluent\run_meshing.py batch --schemes icem_tetra

# 本机可用的 ICEM 2022 R1 备用配置，质量检查仍使用 Fluent 2024 R2
.\fluent\.venv312\Scripts\python.exe -u .\fluent\run_meshing.py batch --schemes icem_tetra --config .\fluent\config_icem221.example.json

# 汇总所有正式案例
.\fluent\.venv312\Scripts\python.exe .\fluent\run_meshing.py summary
```

参数扫描可与任意预设组合使用；每组独立保存参数、网格和质量结果：

```powershell
.\fluent\.venv312\Scripts\python.exe .\fluent\run_meshing.py plan --models 3impeller --schemes poly tetra_prism --sweep .\fluent\sweep.example.json
.\fluent\.venv312\Scripts\python.exe -u .\fluent\run_meshing.py batch --models 3impeller --schemes poly tetra_prism --sweep .\fluent\sweep.example.json
```

扫描 JSON 是 `[{"name":"fine","parameters":{"max_size":1.5}}]` 形式；参数优先级为预设、`--config`/`--cores`、扫描组。示例只是待测试参数组合，不保证每组达到质量阈值。改变表面参数后不能继续使用旧的 `surface_cache`，校验器会拒绝。

输入默认路径在 `run_meshing.py`，也可用 `--input-dir "其他目录"`。模型文件名仍采用 `2impeller.scdoc` 等形式。`--output` 指定批处理输出根目录。每次执行创建独立时间戳目录，避免旧网格或旧报告误判为新结果。

## 方案

| 预设 | 引擎 | 网格 |
|---|---|---|
| `poly` | Fluent Meshing | 多面体 |
| `poly_prism` | Fluent Meshing | 多面体 + 棱柱边界层 |
| `poly_hexcore` | Fluent Meshing | poly-hexcore |
| `hexcore` | Fluent Meshing | hexcore |
| `tetra` | Fluent Meshing | 四面体 |
| `tetra_prism` | Fluent Meshing | 四面体 + 棱柱边界层 |
| `strict_poly` | Fluent Meshing | 多面体，体质量严格 >0.3 |
| `icem_tetra` | ICEM | 四面体；221 批处理已实测，当前质量未达标 |
| `icem_tetra_prism` | ICEM | 四面体 + 棱柱；221 修复试验已生成，当前网格检查未通过 |

预设代表已实现的配置分支，**不代表每一种已在三个模型上实测通过**。ICEM 的纯六面体 O/H/C 分块需要几何对应的 blocking 拓扑，本项目不把通用四面体 replay 冒充自动结构化六面体。

## 参数

`presets.json` 保存默认值和预设差异，`--config` 接受覆盖参数的 JSON。未知顶层参数会报错。

| 参数 | 含义 / 默认 |
|---|---|
| `min_size / max_size` | 最小/最大面尺寸：0.3 / 2 mm |
| `growth_rate` | 面尺寸增长率：1.15 |
| `curvature_angle` | 曲率法向角：12° |
| `surface_controls` | 追加 Fluent 242 的 CFDSurfaceMeshControls 字段，如间隙控制；由 Fluent 校验 |
| `local_sizing` | Fluent Add Local Sizing 参数对象列表，供标签/面局部加密 |
| `boundary_layers` | 默认 0；带 prism 的预设默认 5 |
| `boundary_types` | 可选的面标签到 Fluent 边界类型映射；不指定时保留工作流默认类型 |
| `first_height / layer_growth` | 首层高度 0.05 mm / 层增长率 1.2 |
| `surface_target / surface_limit` | 改善目标 0.65 / 验收严格 <0.7 |
| `surface_improve_min_size` | 改善允许最小尺寸 0.05 mm |
| `orthogonal_limit` | 验收默认 >=0.2 |
| `orthogonal_strict` | `true` 时改为严格大于阈值 |
| `volume_target` | 自动改善目标 0.35 |
| `improve_passes` | 最多 2 轮；达到目标或没有改善即停止 |
| `surface_improve_iterations / volume_improve_iterations` | 每轮内部改善次数：5 / 5 |
| `surface_overrides / volume_overrides / boundary_layer_overrides` | Fluent 242 原生工作流参数覆盖；错误参数会进入失败报告 |
| `cores / timeout_seconds` | 每案例 4 核 / 2400 秒上限 |
| `surface_cache` | 可选缓存面网格路径，需同名 `.json` 元数据且源文件/参数/网格哈希一致 |
| `icem_root` | ICEM 独立安装根目录；可选 v221，不改变 Fluent 242 |

**单位：尺寸参数和当前导出的网格坐标均为 mm。** `quality.json` 的 `mesh_unit` 明确记录单位。后续求解若使用 SI，需要在 Fluent 中将坐标缩放 0.001；本项目负责到网格导出，不自动设置流体物性、转速或求解边界条件。首层高度是网格参数，并不自动保证任何 y+ 值。

ICEM 预设使用全局/表面尺寸、增长率、壁面棱柱参数和处理器数。Fluent 专用的 `local_sizing`、曲率角及 `*_overrides` 不应当用于 ICEM；Tcl 当前不实现这些接口。

## SpaceClaim 的分组与命名

三个输入已是流域实体。脚本校验一个流域体、所有边界面的完整且不重复覆盖，按显式映射重命名为 `fluid_*`、`interface_in_*`、`interface_out_*`、`wall_upper_*`、`wall_lower_*`、`wall_blades_*`；2 号原名 `2imperller_volute` 的拼写差异已纳入映射。

脚本另输出每个面的面积、曲面类型和包围盒，支持在**同一几何的命名丢失后**按特征恢复分组：

```powershell
.\fluent\.venv312\Scripts\python.exe -u .\fluent\run_meshing.py prepare --models 3impeller --reference .\fluent\outputs\3impeller\geometry\geometry.json
```

`spaceclaim_prepare.py` 也可在 SpaceClaim 内通过 `PUMP_CONFIG` 环境变量指向 JSON 运行。模板容差可设置 `linear_tolerance_m` 和 `relative_area_tolerance`。无法唯一匹配、缺面、重复选择时停止导出，不依靠不稳定的面序号猜测。此脚本分组已有拓扑面；不对任意新叶轮猜测入口，也不凭空从泵的固体装配提取流域或生成切割面。

## 报告与可靠性

每个案例提供 `job.json`、`parameters.json`、`worker.log`、`quality.json`，Fluent 案例还提供 `fluent.trn`、`surface_quality.json`、`mesh_check.txt`、`surface.msh.h5`、`mesh.msh.h5` 以及改善过程检查点。ICEM 提供 `mesh.rpl`、`icem.log`、`status.txt` 和成功时的 `mesh.msh`。

- 面质量查询只统计生成的网格面，排除 CAD 三角化副本；最终还检查体网格外边界面的偏斜度。
- 体质量记录改善前后历史；若最小正交质量下降，恢复之前检查点。
- 同时要求实际体单元、Fluent 拓扑检查和命名保留检查通过。缺数值、NaN、空网格不会标成通过。
- `quality_not_met` 保留实测结果和网格供比较；`error`/`license_blocked` 记录具体失败；失败案例不会中断后续案例。
- 按案例顺序运行，避免争抢许可证和内存。超时停止该案例自己的进程树。
- `summary.csv / summary.json` 汇总各模型、引擎、状态、质量、数量和耗时。
- 配置缓存目前用于 SpaceClaim 预处理；不把旧的不同参数网格自动当作新结果。
- 面网格缓存保存为 `surface.msh.h5` 与 `surface.msh.h5.json`，通过 `surface_cache` 指定。源文件、表面参数、局部加密、单位和网格 SHA256 任一不一致都会拒绝复用。
- 退出码：0 表示该批全部通过，1 表示存在执行/许可错误，2 表示存在未达质量要求案例。

可用 `audit --case-dir "某个案例目录"` 重读最终网格重新检查，独立生成 `audit.trn`。
修复导出或检查中间网格时，可增加 `--mesh-file "该案例中的网格文件名"`；报告保留原生成错误，并记录实际复核文件。`audit` 的退出码也反映验收是否通过。

完整实测对比见 [VALIDATION.md](VALIDATION.md)。`best_measured.json` 从通过的实测报告中按最小正交质量、最大偏斜度、单元数依次选择，不能代替网格无关性分析或证明全局最优。

测试：

```powershell
.\fluent\.venv312\Scripts\python.exe -m unittest discover -s fluent -p test_automation.py -v
```

本机安装依赖版本保存于 `requirements-lock.txt`。换机器可用 Python 3.12 创建虚拟环境并安装 `requirements.txt`，然后确认商业软件许可证。

接口依据：[SpaceClaim 242 命令行](https://ansyshelp.ansys.com/public/Views/Secured/corp/v242/en/spaceclaim/Discovery/user_manual/spaceclaim_command_line_options.html)、[ICEM 242 Replay](https://ansyshelp.ansys.com/public/Views/Secured/corp/v242/en/icm_help/icm_mm_replayscripts.html)，以及本机 `v242/scdm/SpaceClaim.Api.V242`、`v242/icemcfd/win64_amd/lib/med_batch` 和 PyFluent 的 242 生成接口。
