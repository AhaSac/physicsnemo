# OpenFOAM 离心泵性能训练

`train_openfoam_pump.py` 调用本仓库 `physicsnemo.models.geotransolver.GeoTransolver`，训练完整泵几何与工况到扬程、扭矩的映射，并由功率关系计算效率。代码包含详细中文批注。第一版面向正转、正流量、正扬程、正输入扭矩的单级单吸离心泵，使用单相、不可压缩、无空化的已收敛结果。关死点、反转、反向流动、空化和启动过程不在当前范围内。

它包含 `prepare`、`train`、`predict` 三个入口。不会启动 OpenFOAM、自动抽取任意 CAD 流体域，也不会生成三维预测流场。

## 1. OpenFOAM 需要保存什么

每个工况保存一份可复现的 OpenFOAM case，至少保留：

```text
raw/pump_001_q01/
├── case.foam                     # 空文件，供 PyVista/ParaView 识别 case
├── constant/
│   ├── polyMesh/                 # points、faces、owner、neighbour、boundary 等
│   ├── ...物性与湍流设置...
│   └── ...MRF 设置...
├── system/                       # controlDict、fvSchemes、fvSolution 等
├── 0/                            # 初始及边界条件
├── <已收敛时间>/                 # U、p、湍流变量等；不同发行版字段组织可能不同
├── postProcessing/              # 总压/流量、旋转壁压力及黏性力矩、稳定性监控
└── log.<solver>
```

并行算例先重构完整网格与需要的结果。本脚本的 `.foam` 读取入口只处理已重构的单一流体网格；多 region 或特殊网格组织可先在 ParaView 中导出各类表面，使用下面的 `surface_files` 入口。

同一几何不同转速/流量复用一份参考几何点云即可，训练表每行仍表示一个独立工况。叶轮和蜗壳必须处于真实装配位置。保留 CAD 源文件及工况设置，后续扩大数据集时方便复现。

仅训练本性能模型，实际读取的监督信息是几何和 H/T 标签，不需要每次把全部体网格压力、速度搬进显存。仍建议归档这些原始场，供检查和后续流场代理训练使用。

## 2. 先生成可信的性能标签

### 扬程 H，单位 m

选定固定定义的入口/出口测量截面，采用一致的流量加权平均方法：

```text
H = <p/(rho*g) + |U_absolute|²/(2*g) + z>out
  - <p/(rho*g) + |U_absolute|²/(2*g) + z>in
```

对于常密度、同高度的截面，可由质量/体积流量加权总压差除以 `rho*g` 计算。明显回流时应明确正反向通量处理方法，不能随意混用面积平均与流量平均。

**务必检查压力字段的 dimensions。** 常见不可压缩 OpenFOAM 求解器的 `p` 是运动学压力，单位 m²/s²；转换到 Pa 时乘密度。对于这种 `p`，同高截面可写成 `H = Δ<p + |U_absolute|²/2>/g`，不能再次除以密度。若 `p` 已经是 Pa，则使用 `Δ<p + rho*|U_absolute|²/2>/(rho*g)`。如果使用 `p_rgh`，先恢复物理静压及一致的重力参考，避免遗漏或重复叠加重力项。

可使用发行版支持的 `pressure` function object 生成总压，再使用 `surfaceFieldValue` 做流量加权报告。MRF/滑移网格要确认 U 的参考系，标签使用绝对速度。不要仅从函数名称推断输出单位，检查写出的字段维度与日志。

### 扭矩 T，单位 N·m

用 `forces` function object 在**所有被模拟的旋转湿壁面**积分压力与黏性贡献，指定真实旋转中心。以 OpenCFD 分支的常见配置为例，将下面一段放进 `controlDict` 的 `functions` 内，并替换 patch、中心、密度：

```foam
rotorLoads
{
    type            forces;
    libs            ("libforces.so");
    patches         (blades hub shroud); // 示例：必须换成实际全部旋转湿壁
    p               p;
    U               U;
    rho             rhoInf;            // 此示例针对运动学压力的不可压缩情况
    rhoInf          998.2;
    CofR            (0 0 0);           // 真实转轴上的力矩参考点，单位m
    writeControl    timeStep;
    writeInterval   1;
}
```

不同 OpenFOAM 发行版/版本的库名、字典和输出列可能不同，以安装版本的 `forces` 文档/教程为准。这里使用有量纲 `forces`，不能把 `forceCoeffs` 的无量纲力矩系数直接填进 `T_Nm`。

如果报告给出流体作用在转子上的力矩向量 M，驱动扭矩按 `T = -dot(M, rotation_axis)` 计算，其中轴方向与正转方向一致。先人工确认所用报告的作用/反作用约定。必须包含压力和黏性贡献，不要只取压力矩，也不要用 abs() 静默掩盖符号设置错误。

### 工况与收敛

- Q 使用 m³/s，`m³/h ÷ 3600`；质量流量应先除以密度。使用与 H/T 标签一致的实际流量，并确认质量守恒。
- n 使用 rpm，由脚本换算为转/秒和 rad/s；不要把 rad/s 填成 rpm。
- mu 使用动力黏度 Pa·s；如果 OpenFOAM 设置的是运动黏度 nu，应取 `mu=rho*nu`。
- 稳态算例检查性能监控是否稳定、质量不平衡是否满足要求、湍流/壁面处理及网格是否可信，不能只看残差。
- 瞬态算例先达到周期稳定，再在相同规则的完整周期窗口内统计 H/T。固定 Q/n 时效率由平均 H、平均 T 计算；不能用单个最终时间步代替平均结果。
- 保持湍流模型、壁面处理、边界条件、粗糙度和损失建模范围一致。变更这些设置时要扩展工况特征或建立独立任务。

效率由 `eta=rho*g*Q*H/(T*2*pi*n_rpm/60)` 计算，不需要单独提供监督列。它只代表模拟范围内的效率；未建模泄漏、盘摩擦或机械损失时，不能声称得到完整实泵轴效率。

## 3. 填写几何与样本清单

复制 `geometry.example.json` 和 `samples.example.csv` 后改成真实内容。这两个文件是模板，CSV 的 H/T 刻意留空、converged 为 false，程序会拒绝直接把它当作真实数据训练。

JSON 的每套几何需要提供：

| 字段 | 含义 |
|---|---|
| geometry_id | 一套真实几何唯一ID，同一几何所有工况必须共用 |
| foam_file | 参考 case 的空 `.foam` 文件路径；相对路径以 JSON 所在目录为基准 |
| length_unit | 原始网格坐标单位，只接受 m 或 mm |
| impeller_diameter_m | 叶轮外径，始终填 m，与 length_unit 无关 |
| rotation_origin | 旋转中心，使用原始坐标单位 |
| rotation_axis | 正向旋转轴方向，例如 [0,0,1] |
| radial_reference | 垂直转轴的固定径向基准，例如 [1,0,0] |
| patches | rotor_wall、stator_wall、inlet、outlet 四类实际 patch 名称 |
| time | 可选：明确读取的参考网格时间；缺省用最后时间 |

`stator_wall` 要包含所有静止湿壁，不能漏掉入口/出口管段的壁面。转静接口、AMI/cyclic 面不作为实体壁面重复加入。使用完整整泵几何，当前脚本不做周期扇区重建。滑移网格为每套几何指定一致参考转角，不能让不同工况的最终转子角度混入几何输入。

也支持 CAD 或 ParaView 导出的分组表面文件：删除某条几何的 `foam_file` 和 `patches`，改成下面的字段，其他字段保留：

```json
"surface_files": {
  "rotor_wall": ["surfaces/blades.stl", "surfaces/hub.stl", "surfaces/shroud.stl"],
  "stator_wall": ["surfaces/stator.vtp"],
  "inlet": ["surfaces/inlet.vtp"],
  "outlet": ["surfaces/outlet.vtp"]
}
```

每个文件只放其对应的过流表面，保持装配坐标，不能直接把包含内外表面及非湿壁的整套固体外壳当成流道边界。`.x_t` 需要先导出上述表面，脚本没有 Parasolid 导入器。

CSV 必填列：

```csv
sample_id,geometry_id,n_rpm,Q_m3_s,rho_kg_m3,mu_Pa_s,H_m,T_Nm,converged
```

可选列 `split` 填 train/val/test。同一 geometry_id 不能跨集合。也可把整列全部留空，脚本按几何自动划分，需要至少三套几何。`case_dir`、`averaging_start`、`averaging_end` 等附加列会保留到数据清单供溯源，不会作为网络输入。

三套几何只是程序能做划分的下限，不能支撑可靠的新几何泛化。先用少量样本确认流程，再逐渐扩大不同叶轮/蜗壳的几何覆盖；同一泵更多工况不能替代更多独立几何。相同几何不要换ID重复放进不同集合。

## 4. 环境与运行命令

建议建立独立环境，避免改变现有 PyFluent 虚拟环境。当前仓库的 `pyproject.toml` 要求 Python>=3.11、PyTorch>=2.10；使用与显卡驱动匹配的 PyTorch，随后在仓库根目录安装：

```powershell
python -m pip install -e .
python -m pip install pyvista
```

以下命令均从 `physicsnemo` 仓库根目录执行，`python` 应是该独立环境的解释器。`prepare` 需要 NumPy、PyVista/VTK；`train/predict` 还需要本仓库 PhysicsNeMo 及其依赖。

```powershell
# 先复制模板并填写真实数据；示例采用 pump_ai 下的相对路径
python pump_ai/train_openfoam_pump.py prepare --geometry-config pump_ai/geometry.json --samples pump_ai/samples.csv --out pump_ai/data/prepared_v1 --pool-points 8192

# 训练；默认自动选择CUDA或CPU。显存不足先减小points或batch-size
python pump_ai/train_openfoam_pump.py train --data pump_ai/data/prepared_v1 --out pump_ai/runs/run_001 --epochs 300 --points 2048 --batch-size 2 --device auto

# 对准备过的几何预测；这些工况数值只是命令示例
python pump_ai/train_openfoam_pump.py predict --checkpoint pump_ai/runs/run_001/best.pt --geometry pump_ai/data/prepared_v1/geometries/pump_003.npz --n-rpm 2900 --flow 0.01 --rho 998.2 --mu 0.001003 --output pump_ai/runs/run_001/prediction.json

# 新泵没有CFD标签时，只准备它的几何，再把生成的npz交给上面的predict
python pump_ai/train_openfoam_pump.py prepare --geometry-config pump_ai/new_geometry.json --out pump_ai/data/new_geometry --pool-points 8192
```

输出目录要求为空，避免覆盖旧模型或混用不同预处理数据。`prepare` 失败后请换一个新输出目录或人工确认后清理失败目录，再重试。

每套几何按四类各采样等量点，每类内部按面积均匀采样。使用转轴、径向基准统一坐标，保留部件相对位置；坐标除以真实叶轮直径 D，D 仍进入工况编码。每点8维输入为 xyz、四类one-hot、该类总面积/D²的对数。所有点从边界几何提取，不读取压力/速度作为输入，因此推理时不需要先有CFD解。

工况输入为 n、Q、rho、mu、D、流量系数 phi、Re 的对数。标签为 `log(gH/(n²D²))`、`log(T/(rho*n²D⁵))`，其中 n 用转/秒。几何经 GeoTransolver 编码、全局汇聚、性能头得到这两个系数；逆变换得到正的 H/T，并计算效率。当前对数形式不支持零流量或负扬程等工况。

归一化仅由训练集拟合。训练每轮重采样点，验证/测试使用固定点；验证损失用于选择最优权重和提前停止，测试集只在选模结束后评估。

输出：

- `best.pt`：权重、网络配置、归一化参数、工况范围和几何划分。
- `run.json`：配置、物理任务说明、随机种子、数据清单哈希。
- `history.jsonl`：每轮训练损失、验证集物理量误差。
- `metrics.json`：最优权重的验证/测试指标。
- `val_predictions.csv`、`test_predictions.csv`：逐工况真值与预测，便于画性能曲线。

预测不会把效率强行裁剪到0～1，超界会标记。工况超出训练范围也会标记，但这不是不确定性估计；没有超范围并不保证新几何可靠。种子用于复现采样，不保证不同硬件上的训练结果逐位一致。

## 5. 文档依据

- [PhysicsNeMo GeoTransolver](https://docs.nvidia.com/physicsnemo/latest/physicsnemo/api/models/geotransolver.html)
- [OpenFOAM forces：压力、黏性力与力矩](https://doc.openfoam.com/2306/tools/post-processing/function-objects/forces/forces/)
- [OpenFOAM pressure：运动学压力、静压与总压](https://doc.openfoam.com/2312/tools/post-processing/function-objects/field/pressure/)
- [PyVista OpenFOAMReader](https://docs.pyvista.org/api/readers/_autosummary/pyvista.openfoamreader)

OpenFOAM Foundation 与 OpenCFD 分支存在命令和字典差异。上述 function object 示例以链接中的 OpenCFD 文档为依据；训练数据格式独立于具体发行版。

## 6. 本次软件验证

已通过10项数据约定测试，覆盖量纲换算及逆变换、效率、几何分组划分、坐标轴、采样和标签验收：

```powershell
python -m unittest discover -s pump_ai -p test_openfoam_pump.py -v
```

另用合成盒体与合成标签验证了分组STL预处理、原生OpenFOAM格式的patch读取、真实GeoTransolver两轮CPU训练、最优权重保存/重载、独立测试输出及单次预测一致性。验证环境为Python 3.13.0、PyTorch 2.14.1+cpu、PhysicsNeMo 2.3.0a0、PyVista 0.49.1。

这些是软件运行检查，不是离心泵工程精度验证；合成标签和测试权重均放在忽略的 `.smoke/` 中，不提供为真实训练数据或可用泵模型。当前还没有使用你的真实OpenFOAM算例进行训练。
