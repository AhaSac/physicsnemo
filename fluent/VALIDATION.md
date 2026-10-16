# 实测结果

2026-09-29，本机 ANSYS Fluent 2024 R2，Python 3.12 / PyFluent 0.28.1。

验收要求：最终边界面最大偏斜度 <0.7；最小体正交质量 >=0.2；有体单元、拓扑检查及边界命名检查通过。下列四个结果同时也达到正交质量 >0.3。

| 模型 | 方案 | 单元数 | 最大边界面偏斜度 | 最小体正交质量 | 结果 |
|---|---|---:|---:|---:|---|
| 2impeller | tetra | 5,417,893 | 0.640240 | 0.306927 | 通过 |
| 3impeller | poly | 862,514 | 0.587905 | 0.367432 | 通过，最终网格另行重读复核 |
| 3impeller | poly_hexcore | 2,837,450 | 0.587905 | 0.350010 | 通过 |
| 4impeller | poly | 383,710 | 0.681457 | 0.351775 | 通过 |

实际网格及对应 `quality.json`：

- `outputs/runs/20260929_152655_18700/2impeller/tetra/mesh.msh.h5`
- `outputs/runs/20260929_141607_28608/3impeller/poly/mesh.msh.h5`
- `outputs/runs/20260929_142451_46476/3impeller/poly_hexcore/mesh.msh.h5`
- `outputs/runs/20260929_151459_20456/4impeller/poly/mesh.msh.h5`

坐标单位均为 mm，进入以 m 为单位的求解设置前需要缩放 0.001。原始 SCDOC 未覆盖。

## 批处理复现

```powershell
.\fluent\.venv312\Scripts\python.exe -u .\fluent\run_meshing.py batch --models 2impeller --schemes tetra --cores 1 --skip-prepare
.\fluent\.venv312\Scripts\python.exe -u .\fluent\run_meshing.py batch --models 3impeller 4impeller --schemes poly --skip-prepare
```

这组命令按实测选择各模型方案。参数扫描见 `sweep.example.json`；结果随参数和几何改变，需要重新验收。

## 未通过或有限制的方案

- 2 号 poly：1,062,494 单元，正交质量 0.350561，但最终边界面偏斜度 0.745633；保留为不合格结果。面网格阶段的 0.642206 不能代替最终体网格边界检查。
- ICEM 2024 R2：本机 `cfd_preppost` 许可证返回 FlexNet -25,147，未能执行网格生成。
- ICEM 2022 R1 备用路线：四面体批处理已完整执行并由 Fluent 242 复核，1,799,261 单元、偏斜度 0.964273、正交质量 0.020109；拓扑和命名通过，质量未达标。不能作为合格交付网格。
- ICEM 221 使用官方 `fluent6.exe` 导出，绕开 `ic_create_output` 调用界面入口造成的批处理崩溃。棱柱函数需显式传入参数文件和逐个壁面组。
- 3 号默认五层 Fluent 棱柱在四核运行时遇到 MPI 连接超时；单核成功生成体网格，但初始最小正交质量接近零。不可按“生成成功”判断可用。
- 单核五层 Fluent 检查点已另行复核：6,316,854 单元、边界面偏斜度 0.920803、正交质量 4.19e-9；改善试验长时间未产出新检查点后停止，保留为不合格结果。
- ICEM 五层棱柱修复试验实际导出 `prism_fixed.msh`，偏斜度 0.971944、正交质量 0，Fluent 网格检查失败。修复了接口执行问题，并未解决该参数组合的几何质量问题。
- ICEM 结构化六面体 blocking、任意新几何自动抽取流域/切割面尚未实现。SpaceClaim 脚本已验证三个已有流域的命名覆盖及同几何的模板恢复。

所有历史结果在 `outputs/runs/summary.csv`；`best_measured.json` 只从通过的实测案例选择，不能证明全局最优。方案列表是可配置分支，不能视为每种方案都已达标。

## 固定原生方案与最新验收标准（2026-09-29）

3 号原生基准从 SCDOC 到导出已完成：`20260929_200419_47400/3impeller/user_baseline`，768,776 单元，Improve Volume 前 0.106255、后 0.270445；面最大偏斜度 0.845693。拓扑检查和命名保留通过。参数为 0.04–8 mm、polyhedra、默认 smooth-transition 边界层、体改善目标 0.3。

用户最新要求：面偏斜度只记录；常规最小正交质量 >=0.2，复杂叶轮 >=0.15。此基准满足新标准，但不修改历史报告中按旧标准产生的失败状态。新增 `pump_repeatable` 和 `pump_complex` 使用相同生成参数；配置一致性、质量门槛和原有自动化共 14 项测试通过。新固定入口复跑位于 `20260929_220214_50972/3impeller/pump_repeatable`，结果以该目录真实报告为准。

ICEM 的 221 Hexa 引擎已通过简单盒体 1650 个纯六面体的生成与导出测试；这不代表实际叶轮结构化分块已完成。三个叶轮的 SpaceClaim 面/边环关联现已导出，但共享顶点身份仍需检查后才能用于分块。

固定入口复跑已完成（退出码 0）：`20260929_220214_50972/3impeller/pump_repeatable`，768,776 单元，最小正交质量 0.2704451118399696，609.485 秒，拓扑及边界命名通过。五个原生步骤实参均与旧基准完全相同；单元数与质量值也一致。最终网格 SHA256 与报告一致，报告按最新标准 `passed=true`。2/4 号尚未完成此固定入口的验证。

2026-09-30 更新：2/4 号固定入口现均已完成，结果见 `outputs/fixed_results.csv`。三份最终网格 SHA256、正交质量验收、拓扑检查及命名检查均核对通过。没有把面偏斜度重新作为失败门槛。
