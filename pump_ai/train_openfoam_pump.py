#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""用 PhysicsNeMo GeoTransolver 训练单级单吸离心泵的几何条件性能代理模型。

本文件包含三个独立入口，详见同目录 README.md：
  prepare：从 OpenFOAM boundary 或分组表面文件生成几何点云，整理性能标签。
  train：  几何点云 + 工况 -> 扬程系数、扭矩系数；保存验证集最优模型。
  predict：对一个已预处理的几何和指定工况预测 H、T、效率。

重要范围：这是性能回归脚本，不会运行 OpenFOAM，也不预测三维压力/速度场。
H、T 标签应由已经收敛的 OpenFOAM 后处理产生，不能用初始场或未收敛结果。
当前支持正转、正流量、正扬程/输入扭矩的单相无空化泵送工况，不含关死点。
几何必须是完整过流表面，并区分旋转壁、静止壁、入口、出口四类。
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import random
import re
import sys
from pathlib import Path

import numpy as np

# 直接从仓库运行时，优先使用这份克隆代码中的 physicsnemo，避免误用另一个安装。
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

PARTS = ("rotor_wall", "stator_wall", "inlet", "outlet")
FORMAT_VERSION = 1
CONDITION_NAMES = ("log_n_Hz", "log_Q", "log_rho", "log_mu", "log_D", "log_phi", "log_Re")
REQUIRED_COLUMNS = (
    "sample_id", "geometry_id", "n_rpm", "Q_m3_s", "rho_kg_m3", "mu_Pa_s",
    "H_m", "T_Nm", "converged",
)


def read_json(path):
    # utf-8-sig 也兼容某些 Windows 编辑器保存的 UTF-8 BOM。
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")


def positive(value, name):
    try:
        value = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} 必须填写数字，收到 {value!r}") from exc
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} 必须是有限正数，收到 {value}")
    return value


def safe_id(value):
    # ID 用于输出文件名，禁止路径分隔符和 ..，避免意外写到数据集目录之外。
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", value) or ".." in value:
        raise ValueError(f"非法 ID：{value!r}；请使用字母、数字、下划线、点或短横线")
    return value


def resolved(base, name):
    path = Path(name)
    return path.resolve() if path.is_absolute() else (base / path).resolve()


def require_pyvista():
    try:
        import pyvista as pv
    except ImportError as exc:
        raise RuntimeError("prepare 需要 PyVista/VTK：python -m pip install pyvista") from exc
    return pv


def canonical_basis(spec, unit_scale):
    """显式对齐转轴，保留蜗壳舌部与叶轮的相对角度，不分别对齐各个零件。

    rotation_origin 的单位和原几何一致；axis/radial_reference 是无量纲方向。
    radial_reference 指定泵的基准径向，不能为每个部件单独随意选择。
    """
    origin = np.asarray(spec["rotation_origin"], dtype=np.float64) * unit_scale
    axis = np.asarray(spec["rotation_axis"], dtype=np.float64)
    radial = np.asarray(spec["radial_reference"], dtype=np.float64)
    if any(v.shape != (3,) or not np.isfinite(v).all() for v in (origin, axis, radial)):
        raise ValueError("旋转原点、轴、径向基准必须都是三个有限数值")
    axis /= positive(np.linalg.norm(axis), "rotation_axis 长度")
    radial = radial - np.dot(radial, axis) * axis
    radial /= positive(np.linalg.norm(radial), "径向基准在转轴垂面上的投影长度")
    return origin, np.column_stack((radial, np.cross(axis, radial), axis))


def collect_named_blocks(block, pv, prefix=""):
    """递归查找 VTK/OpenFOAM 多块数据；保留完整名字，拒绝歧义的 patch 匹配。"""
    result = []
    if isinstance(block, pv.MultiBlock):
        for i, name in enumerate(block.keys()):
            child = block[i]
            if child is not None:
                result.extend(collect_named_blocks(child, pv, f"{prefix}/{name}"))
    elif getattr(block, "n_cells", 0) > 0:
        result.append((prefix.strip("/"), block))
    return result


def load_surfaces(spec, base, pv):
    """两种输入选一种：OpenFOAM .foam + patch 映射，或各部件 STL/VTP 文件。

    OpenFOAM 输入要求已经 reconstructPar 的串行完整网格。禁用 internalMesh，
    只加载需要的边界；本版本按单一流体网格处理，不自动拼接多 region。
    """
    if ("foam_file" in spec) == ("surface_files" in spec):
        raise ValueError("每套几何必须且只能提供 foam_file 或 surface_files")
    key = "patches" if "foam_file" in spec else "surface_files"
    mapping = spec[key]
    if set(mapping) != set(PARTS) or any(not isinstance(mapping[p], list) or not mapping[p] for p in PARTS):
        raise ValueError(f"{key} 必须包含四个非空列表：{PARTS}")
    flat = [str(item) for part in PARTS for item in mapping[part]]
    if len(flat) != len(set(flat)):
        raise ValueError("同一个 patch/表面文件不能重复分配，否则几何面积和采样会重复")
    if "surface_files" in spec:
        return {part: [pv.read(resolved(base, p)) for p in mapping[part]] for part in PARTS}

    foam_path = resolved(base, spec["foam_file"])
    if not foam_path.is_file():
        raise ValueError(f"找不到 {foam_path}；请先在 OpenFOAM case 中创建空的 case.foam 文件")
    reader = pv.OpenFOAMReader(str(foam_path))
    reader.disable_all_patch_arrays()
    reader.disable_all_cell_arrays()
    reader.disable_all_point_arrays()
    available = reader.patch_array_names
    for patch in flat:
        candidates = [name for name in available if name == patch or name == f"patch/{patch}"]
        if len(candidates) != 1:
            raise ValueError(f"patch {patch!r} 未找到或有歧义；实际可用名称：{available}")
        reader.enable_patch_array(candidates[0])
    if reader.time_values:
        # 稳态 MRF 取参考网格即可；滑移网格必须提供明确参考转角的时间。
        time_value = float(spec.get("time", max(reader.time_values)))
        reader.set_active_time_value(time_value)
    blocks = collect_named_blocks(reader.read(), pv)
    surfaces = {}
    for part in PARTS:
        surfaces[part] = []
        for patch in mapping[part]:
            matches = [mesh for name, mesh in blocks if name == patch or name.rsplit("/", 1)[-1] == patch.rsplit("/", 1)[-1]]
            if len(matches) != 1:
                raise ValueError(f"读入后的 patch {patch!r} 不唯一；数据块：{[n for n, _ in blocks]}")
            surfaces[part].append(matches[0])
    return surfaces


def triangle_samples(meshes, pv, count, rng, scale, origin, basis, diameter):
    """按三角形面积均匀采样，不把网格加密位置误当成几何的重要程度。

    每一类表面单独采样，确保很小的进出口也有点。再提供面积/D²特征，
    让网络知道这些等量点云对应的实际面积不同。无需强行统一网格节点数。
    """
    all_triangles = []
    for mesh in meshes:
        if isinstance(mesh, pv.MultiBlock):
            mesh = mesh.combine()
        surface = mesh.extract_surface().triangulate()
        faces = np.asarray(surface.faces).reshape(-1, 4)
        if not len(faces) or not np.all(faces[:, 0] == 3):
            raise ValueError("表面为空或未能三角化")
        xyz = np.asarray(surface.points, dtype=np.float64) * scale
        all_triangles.append(xyz[faces[:, 1:]])
    triangles = np.concatenate(all_triangles)
    if not np.isfinite(triangles).all():
        raise ValueError("表面含 NaN/Inf 坐标")
    area = np.linalg.norm(np.cross(triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0]), axis=1) * 0.5
    valid = area > 0
    triangles, area = triangles[valid], area[valid]
    total_area = positive(area.sum(), "表面总面积")
    chosen = triangles[rng.choice(len(area), size=count, p=area / total_area)]
    a, b = rng.random((2, count))
    root = np.sqrt(a)
    xyz = (1 - root[:, None]) * chosen[:, 0] + (root * (1 - b))[:, None] * chosen[:, 1] + (root * b)[:, None] * chosen[:, 2]
    # 平移、旋转后只除以真实叶轮直径 D，不分别压缩 x/y/z，也不各自归一化零件。
    points = (xyz - origin) @ basis / diameter
    return points, total_area / diameter**2


def prepare_geometry(spec, base, out_dir, pool_points, seed):
    pv = require_pyvista()
    gid = safe_id(spec["geometry_id"])
    units = {"m": 1.0, "mm": 0.001}
    if spec["length_unit"] not in units:
        raise ValueError("length_unit 仅接受 m 或 mm；不要让程序猜测单位")
    scale = units[spec["length_unit"]]
    diameter = positive(spec["impeller_diameter_m"], "impeller_diameter_m")
    origin, basis = canonical_basis(spec, scale)
    surfaces = load_surfaces(spec, base, pv)
    # 所有几何使用同一采样种子，采样过程可复现且不依赖 Python 的随机 hash。
    rng = np.random.default_rng(seed)
    parts = []
    for index, part in enumerate(PARTS):
        xyz, area_ratio = triangle_samples(surfaces[part], pv, pool_points // 4, rng, scale, origin, basis, diameter)
        one_hot = np.zeros((len(xyz), 4))
        one_hot[:, index] = 1
        # 每点8维：归一化xyz(3) + 部件one-hot(4) + log(该类总面积/D²)(1)。
        parts.append(np.column_stack((xyz, one_hot, np.full(len(xyz), np.log(area_ratio)))))
    features = np.asarray(parts, dtype=np.float32)  # [4, 每类点数, 8]
    if not np.isfinite(features).all():
        raise ValueError(f"{gid} 产生非有限几何特征")
    path = out_dir / "geometries" / f"{gid}.npz"
    np.savez_compressed(path, features=features, diameter_m=np.float64(diameter), format_version=FORMAT_VERSION)
    return {"geometry_id": gid, "path": f"geometries/{gid}.npz", "spec": spec,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def condition_and_scales(row, diameter):
    """工况、相似系数与量纲恢复。n 是转/秒，绝不是直接把 rpm 代入。

    phi=Q/(nD³)，Re=rho*n*D²/mu；目标 psi=gH/(n²D²)，ct=T/(rho*n²D⁵)。
    不同直径、转速的尺度先按相似关系处理，Re 仍输入模型，因此不假设严格相似。
    """
    n = positive(row["n_rpm"], "n_rpm") / 60.0
    q = positive(row["Q_m3_s"], "Q_m3_s")
    rho = positive(row["rho_kg_m3"], "rho_kg_m3")
    mu = positive(row["mu_Pa_s"], "mu_Pa_s")
    values = np.array([n, q, rho, mu, diameter, q / (n * diameter**3), rho * n * diameter**2 / mu])
    return np.log(values), n**2 * diameter**2, rho * n**2 * diameter**5


def read_geometry(path):
    with np.load(path, allow_pickle=False) as data:
        if int(data["format_version"]) != FORMAT_VERSION:
            raise ValueError("几何格式版本不匹配，请重新 prepare")
        features = data["features"].copy()
        diameter = positive(data["diameter_m"], "diameter_m")
    if features.ndim != 3 or features.shape[0] != 4 or features.shape[2] != 8 or not np.isfinite(features).all():
        raise ValueError(f"无效几何点云：{path}")
    return features, diameter


def load_rows(csv_path, geometry_lookup, g):
    with Path(csv_path).open(encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        missing = set(REQUIRED_COLUMNS) - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"CSV 缺少列：{sorted(missing)}")
        rows = list(reader)
    seen = set()
    for row in rows:
        sid = safe_id(row["sample_id"])
        if sid in seen:
            raise ValueError(f"重复 sample_id：{sid}")
        seen.add(sid)
        gid = row["geometry_id"]
        if gid not in geometry_lookup:
            raise ValueError(f"{sid} 的 geometry_id={gid} 不在几何配置中")
        if row["converged"].strip().lower() not in ("true", "1", "yes"):
            raise ValueError(f"{sid} 未标记为已收敛；请先验收，或从本次训练清单中移除")
        for field in REQUIRED_COLUMNS[2:8]:
            row[field] = positive(row[field], f"{sid}.{field}")
        _, hs, ts = condition_and_scales(row, geometry_lookup[gid])
        eta = row["rho_kg_m3"] * g * row["Q_m3_s"] * row["H_m"] / (row["T_Nm"] * 2 * math.pi * row["n_rpm"] / 60)
        if eta > 1.05:
            raise ValueError(f"{sid} 的派生效率={eta:.4f}>1.05，请检查压力、流量、转速和扭矩单位/符号")
        row["eta"] = eta
        row["target_log_coeff"] = [math.log(g * row["H_m"] / hs), math.log(row["T_Nm"] / ts)]
    if not rows:
        raise ValueError("训练 CSV 为空")
    return rows


def assign_splits(rows, seed):
    """同一 geometry_id 的所有工况只能属于同一集合，防止新几何评估泄漏。

    可显式填写全部 split，也可以全部留空由程序按几何划分。两种方式不能混用。
    自动划分要求至少3套几何；真实应用应远多于这个仅满足程序运行的下限。
    """
    explicit = [bool(row.get("split", "").strip()) for row in rows]
    if any(explicit) and not all(explicit):
        raise ValueError("split 必须全部填写或全部留空")
    if not any(explicit):
        ids = sorted({row["geometry_id"] for row in rows})
        if len(ids) < 3:
            raise ValueError("自动划分至少需要3套不同几何，分别保留训练、验证、测试")
        random.Random(seed).shuffle(ids)
        n_holdout = max(1, int(len(ids) * 0.15))
        lookup = {gid: ("test" if i < n_holdout else "val" if i < 2 * n_holdout else "train") for i, gid in enumerate(ids)}
        for row in rows:
            row["split"] = lookup[row["geometry_id"]]
    grouped = {}
    for row in rows:
        split = row["split"].strip().lower()
        if split not in ("train", "val", "test"):
            raise ValueError(f"非法 split：{split}")
        row["split"] = split
        old = grouped.setdefault(row["geometry_id"], split)
        if old != split:
            raise ValueError(f"{row['geometry_id']} 跨集合出现，会泄漏几何信息")
    if not all(any(r["split"] == split for r in rows) for split in ("train", "val")):
        raise ValueError("必须同时有 train 和 val；显式划分时 test 可选")


def prepare(args):
    config_path = Path(args.geometry_config).resolve()
    config = read_json(config_path)
    specs = config["geometries"]
    ids = [safe_id(spec["geometry_id"]) for spec in specs]
    if not specs or len(ids) != len(set(ids)):
        raise ValueError("geometries 不能为空，geometry_id 不能重复")
    out = Path(args.out).resolve()
    if out.exists() and any(out.iterdir()):
        raise ValueError(f"输出目录非空：{out}；请换新目录，避免混入旧几何或覆盖数据")
    if args.pool_points < 16 or args.pool_points % 4:
        raise ValueError("pool-points 必须是至少16的4倍数")
    g = positive(config.get("g_m_s2", 9.80665), "g_m_s2")
    rows = None
    if args.samples:
        # 先验收标签，再进行可能较耗时的几何读取，模板留空也会在这里明确报错。
        lookup = {s["geometry_id"]: positive(s["impeller_diameter_m"], "impeller_diameter_m") for s in specs}
        rows = load_rows(args.samples, lookup, g)
        assign_splits(rows, args.seed)
    out.mkdir(parents=True, exist_ok=True)
    (out / "geometries").mkdir()
    records = []
    for spec in specs:
        record = prepare_geometry(spec, config_path.parent, out, args.pool_points, args.seed)
        records.append(record)
        print(f"已处理几何 {record['geometry_id']}", flush=True)
    prepared = {"format_version": FORMAT_VERSION, "g_m_s2": g, "seed": args.seed,
                "parts": PARTS, "physics": config.get("physics", {}), "geometries": records}
    # 不提供 --samples 时只准备几何，可用来为一个从未求解过的新泵做推理。
    if rows is not None:
        prepared["samples"] = rows
        print("样本数：", {split: sum(r["split"] == split for r in rows) for split in ("train", "val", "test")})
    write_json(out / "dataset.json", prepared)
    print(f"数据清单：{out / 'dataset.json'}")


def import_torch():
    try:
        import torch
    except ImportError as exc:
        raise RuntimeError("训练/推理需要 PyTorch 和本仓库 PhysicsNeMo 依赖，请参见 README.md") from exc
    return torch


def build_model(config):
    """真实调用 PhysicsNeMo 库；外围汇聚层和性能头用 PyTorch 编写。

    禁用 TransformerEngine 和局部 ball query，第一版不依赖这些额外加速路径。
    这仍是完整 GeoTransolver，不是用同名的自制网络替换库实现。
    """
    torch = import_torch()
    # 部分 PhysicsNeMo 模块在导入时初始化 Warp。把缓存放进项目，避免写用户
    # AppData；这不会改变系统配置，也不影响此模型使用纯PyTorch注意力路径。
    import warp as wp
    wp.config.kernel_cache_dir = str(Path(__file__).resolve().parent / ".cache" / "warp")
    from physicsnemo.models.geotransolver import GeoTransolver

    class PumpPerformanceNet(torch.nn.Module):
        def __init__(self):
            super().__init__()
            width = config["hidden"]
            self.encoder = GeoTransolver(
                functional_dim=8, out_dim=width, geometry_dim=8, global_dim=len(CONDITION_NAMES),
                n_layers=config["layers"], n_hidden=width, n_head=config["heads"],
                slice_num=config["slices"], use_te=False, include_local_features=False,
                dropout=0.0,
            )
            self.head = torch.nn.Sequential(
                torch.nn.Linear(2 * width + len(CONDITION_NAMES), width), torch.nn.GELU(),
                torch.nn.Linear(width, 2),
            )

        def forward(self, geometry, conditions):
            # geometry: [B,N,8]；conditions: [B,7]，作为1个全局token送入每个注意力块。
            local = self.encoder(geometry, geometry=geometry, global_embedding=conditions[:, None, :])
            # 平均汇聚描述整体；最大汇聚保留局部突出特征。工况也直连性能头。
            pooled = torch.cat((local.mean(dim=1), local.amax(dim=1), conditions), dim=-1)
            return self.head(pooled)  # [B,2]，标准化的 log(psi)、log(ct)

    return PumpPerformanceNet()


def sample_points(pool, count, seed):
    if count < 16 or count % 4 or count // 4 > pool.shape[1]:
        raise ValueError("points 必须是至少16的4倍数，且不能超过 prepare 的 pool-points")
    rng = np.random.default_rng(seed)
    return np.concatenate([part[rng.choice(len(part), count // 4, replace=False)] for part in pool])


def build_dataset(rows, geometries, stats, count, seed, training):
    torch = import_torch()

    class PumpDataset(torch.utils.data.Dataset):
        def __init__(self):
            self.epoch = 0

        def __len__(self):
            return len(rows)

        def __getitem__(self, index):
            row = rows[index]
            pool, diameter = geometries[row["geometry_id"]]
            # 同一几何的验证/测试点固定，避免指标随随机采样抖动；训练每轮重采样。
            gid_seed = int.from_bytes(hashlib.sha256(row["geometry_id"].encode()).digest()[:4], "little")
            draw_seed = seed + gid_seed + (self.epoch * len(rows) + index if training else 0)
            xyz = sample_points(pool, count, draw_seed)
            cond, _, _ = condition_and_scales(row, diameter)
            cond = (cond - stats["condition_mean"]) / stats["condition_std"]
            target = (np.array(row["target_log_coeff"]) - stats["target_mean"]) / stats["target_std"]
            return torch.from_numpy(xyz), torch.tensor(cond, dtype=torch.float32), torch.tensor(target, dtype=torch.float32)

    return PumpDataset()


def make_stats(rows, geometries):
    # 必须只用训练集拟合归一化；验证/测试标签不参与任何均值和方差计算。
    conditions = np.stack([condition_and_scales(r, geometries[r["geometry_id"]][1])[0] for r in rows])
    targets = np.array([r["target_log_coeff"] for r in rows])
    # 固定物性/转速的列方差可能为0；设置温和下限，避免新工况被放大成百万量级。
    return {"condition_mean": conditions.mean(0), "condition_std": np.maximum(conditions.std(0), 0.05),
            "target_mean": targets.mean(0), "target_std": np.maximum(targets.std(0), 0.05)}


def decode_predictions(predictions, rows, geometries, stats, g):
    log_coeff = predictions.astype(np.float64) * stats["target_std"] + stats["target_mean"]
    # 不对效率裁剪到[0,1]，否则会掩盖失真的模型。非有限值直接报错。
    with np.errstate(over="raise", invalid="raise", divide="raise"):
        coeff = np.exp(log_coeff)
        result = []
        for row, (psi, ct) in zip(rows, coeff):
            _, hs, ts = condition_and_scales(row, geometries[row["geometry_id"]][1])
            head, torque = psi * hs / g, ct * ts
            eta = row["rho_kg_m3"] * g * row["Q_m3_s"] * head / (torque * 2 * np.pi * row["n_rpm"] / 60)
            if not np.isfinite([head, torque, eta]).all() or head <= 0 or torque <= 0:
                raise ValueError("模型预测溢出或数值无效，请检查数据与训练稳定性")
            result.append({"sample_id": row.get("sample_id", "prediction"), "geometry_id": row["geometry_id"],
                           "H_pred_m": float(head), "T_pred_Nm": float(torque), "eta_pred": float(eta)})
    return result


def evaluate(model, loader, rows, geometries, stats, g, device):
    torch = import_torch()
    model.eval()
    predictions, loss_sum, number = [], 0.0, 0
    with torch.no_grad():
        for geometry, conditions, target in loader:
            pred = model(geometry.to(device), conditions.to(device))
            loss = torch.nn.functional.mse_loss(pred, target.to(device))
            predictions.append(pred.cpu().numpy())
            loss_sum += float(loss) * len(geometry)
            number += len(geometry)
    decoded = decode_predictions(np.concatenate(predictions), rows, geometries, stats, g)
    metrics = {"loss": loss_sum / number}
    for source, prediction, prefix in (("H_m", "H_pred_m", "H"), ("T_Nm", "T_pred_Nm", "T")):
        truth = np.array([r[source] for r in rows])
        diff = np.array([p[prediction] for p in decoded]) - truth
        metrics[f"{prefix}_mae"] = float(np.abs(diff).mean())
        metrics[f"{prefix}_rmse"] = float(np.sqrt(np.mean(diff**2)))
        metrics[f"{prefix}_mape_percent"] = float(np.mean(np.abs(diff) / truth) * 100)
    metrics["eta_mae_percentage_points"] = float(np.mean([abs(p["eta_pred"] - r["eta"]) for p, r in zip(decoded, rows)]) * 100)
    metrics["eta_outside_0_1_count"] = sum(not 0 <= p["eta_pred"] <= 1 for p in decoded)
    return metrics, decoded


def device_for(name, torch):
    if name == "auto":
        name = "cuda" if torch.cuda.is_available() else "cpu"
    if name == "cuda" and not torch.cuda.is_available():
        raise ValueError("指定了 CUDA，但当前 PyTorch 检测不到可用 GPU")
    return torch.device(name)


def train(args):
    torch = import_torch()
    if args.epochs < 1 or args.batch_size < 1 or args.patience < 1:
        raise ValueError("epochs、batch-size、patience 必须为正整数")
    if args.hidden < 1 or args.heads < 1 or args.hidden % args.heads or args.layers < 1 or args.slices < 1:
        raise ValueError("模型维度须为正整数，hidden 必须能被 heads 整除")
    positive(args.lr, "lr")
    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(args.seed)
    device = device_for(args.device, torch)
    data_path = Path(args.data).resolve()
    data = read_json(data_path / "dataset.json")
    if data["format_version"] != FORMAT_VERSION:
        raise ValueError("数据集版本不匹配")
    rows = data.get("samples", [])
    if not rows:
        raise ValueError("此数据集只有几何；训练前 prepare 必须提供 --samples")
    assign_splits(rows, args.seed)
    geometries = {}
    for entry in data["geometries"]:
        path = data_path / entry["path"]
        if hashlib.sha256(path.read_bytes()).hexdigest() != entry["sha256"]:
            raise ValueError(f"预处理几何文件已改变：{path}")
        geometries[entry["geometry_id"]] = read_geometry(path)
    for pool, _ in geometries.values():
        sample_points(pool, args.points, args.seed)  # 提前验证点数，避免训练中途才发现配置错误。
    split_rows = {s: [r for r in rows if r["split"] == s] for s in ("train", "val", "test")}
    stats = make_stats(split_rows["train"], geometries)
    datasets = {s: build_dataset(r, geometries, stats, args.points, args.seed, s == "train") for s, r in split_rows.items() if r}
    # 默认单进程读取缓存点云，在 Windows 上也可直接运行，避免进程重复复制大几何池。
    loaders = {s: torch.utils.data.DataLoader(ds, batch_size=args.batch_size, shuffle=s == "train", num_workers=0) for s, ds in datasets.items()}
    config = {"hidden": args.hidden, "layers": args.layers, "heads": args.heads, "slices": args.slices}
    model = build_model(config).to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=1e-4)
    out = Path(args.out).resolve()
    if out.exists() and any(out.iterdir()):
        raise ValueError(f"训练输出目录非空：{out}；请使用新目录保留已有权重")
    out.mkdir(parents=True, exist_ok=True)
    checkpoint_base = {"format_version": FORMAT_VERSION, "model_config": config,
                       "physicsnemo_version": str(sys.modules["physicsnemo"].__version__),
                       "stats": {k: v.tolist() for k, v in stats.items()}, "points": args.points,
                       "g_m_s2": data["g_m_s2"], "condition_names": CONDITION_NAMES,
                       "parts": PARTS, "physics": data.get("physics", {}),
                       "split_geometry_ids": {s: sorted({r["geometry_id"] for r in rs}) for s, rs in split_rows.items()},
                       "condition_min": np.min([condition_and_scales(r, geometries[r["geometry_id"]][1])[0] for r in split_rows["train"]], axis=0).tolist(),
                       "condition_max": np.max([condition_and_scales(r, geometries[r["geometry_id"]][1])[0] for r in split_rows["train"]], axis=0).tolist()}
    write_json(out / "run.json", {**checkpoint_base, "arguments": vars(args), "torch_version": str(torch.__version__),
                                   "dataset_sha256": hashlib.sha256((data_path / "dataset.json").read_bytes()).hexdigest()})
    best, stale = float("inf"), 0
    print(f"设备={device}；模型参数={sum(p.numel() for p in model.parameters()):,}；按几何隔离评估", flush=True)
    for epoch in range(1, args.epochs + 1):
        model.train()
        datasets["train"].epoch = epoch
        loss_sum, number = 0.0, 0
        for geometry, conditions, target in loaders["train"]:
            optimizer.zero_grad(set_to_none=True)
            pred = model(geometry.to(device), conditions.to(device))
            # 两个目标先在训练集内标准化，避免大数值的扭矩或扬程独占损失。
            loss = torch.nn.functional.mse_loss(pred, target.to(device))
            if not torch.isfinite(loss):
                raise ValueError("训练损失非有限，请检查标签、单位和学习率")
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0, error_if_nonfinite=True)
            optimizer.step()
            loss_sum += float(loss.detach()) * len(geometry)
            number += len(geometry)
        val, _ = evaluate(model, loaders["val"], split_rows["val"], geometries, stats, data["g_m_s2"], device)
        record = {"epoch": epoch, "train_loss": loss_sum / number, "val": val}
        with (out / "history.jsonl").open("a", encoding="utf-8") as file:
            file.write(json.dumps(record, allow_nan=False) + "\n")
        print(f"epoch={epoch:04d} train={record['train_loss']:.5f} val={val['loss']:.5f} H_MAPE={val['H_mape_percent']:.2f}% T_MAPE={val['T_mape_percent']:.2f}% eta_MAE={val['eta_mae_percentage_points']:.2f}个百分点", flush=True)
        if val["loss"] < best:
            best, stale = val["loss"], 0
            # CPU 权重便于在不同设备上载入；同时保存完整模型定义参数和归一化信息。
            torch.save({**checkpoint_base, "epoch": epoch, "val_metrics": val,
                        "model_state": {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}}, out / "best.pt")
        else:
            stale += 1
        if stale >= args.patience:
            print(f"连续 {args.patience} 轮验证损失未改善，提前停止。")
            break
    saved = torch.load(out / "best.pt", map_location="cpu", weights_only=True)
    model.load_state_dict(saved["model_state"])
    # 只在完成选模后评估一次 test，不根据 test 调整训练轮数或选择权重。
    final_metrics = {}
    for split in ("val", "test"):
        if split not in loaders:
            continue
        metrics, decoded = evaluate(model, loaders[split], split_rows[split], geometries, stats, data["g_m_s2"], device)
        final_metrics[split] = metrics
        exported = [{**p, "H_true_m": r["H_m"], "T_true_Nm": r["T_Nm"], "eta_true": r["eta"],
                     "n_rpm": r["n_rpm"], "Q_m3_s": r["Q_m3_s"]} for p, r in zip(decoded, split_rows[split])]
        with (out / f"{split}_predictions.csv").open("w", encoding="utf-8-sig", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=list(exported[0]))
            writer.writeheader()
            writer.writerows(exported)
    write_json(out / "metrics.json", final_metrics)
    print(f"最优权重：{out / 'best.pt'}；独立评估：{out / 'metrics.json'}")


def predict(args):
    torch = import_torch()
    device = device_for(args.device, torch)
    saved = torch.load(args.checkpoint, map_location="cpu", weights_only=True)
    if saved["format_version"] != FORMAT_VERSION or tuple(saved["condition_names"]) != CONDITION_NAMES:
        raise ValueError("权重格式或工况定义与当前脚本不匹配")
    pool, diameter = read_geometry(args.geometry)
    row = {"sample_id": "prediction", "geometry_id": Path(args.geometry).stem,
           "n_rpm": args.n_rpm, "Q_m3_s": args.flow, "rho_kg_m3": args.rho, "mu_Pa_s": args.mu}
    cond, _, _ = condition_and_scales(row, diameter)
    stats = {k: np.array(v) for k, v in saved["stats"].items()}
    model = build_model(saved["model_config"]).to(device)
    model.load_state_dict(saved["model_state"])
    model.eval()
    gid_seed = int.from_bytes(hashlib.sha256(row["geometry_id"].encode()).digest()[:4], "little")
    geometry = torch.from_numpy(sample_points(pool, saved["points"], args.seed + gid_seed))[None].to(device)
    condition = torch.tensor((cond - stats["condition_mean"]) / stats["condition_std"], dtype=torch.float32)[None].to(device)
    with torch.no_grad():
        pred = model(geometry, condition).cpu().numpy()
    result = decode_predictions(pred, [row], {row["geometry_id"]: (pool, diameter)}, stats, saved["g_m_s2"])[0]
    result.update({k: row[k] for k in ("n_rpm", "Q_m3_s", "rho_kg_m3", "mu_Pa_s")})
    # 只是输入范围检查，不是可靠性概率；几何是否超出训练分布仍需另行评估。
    tolerance = 1e-6
    result["conditions_outside_training_range"] = [name for name, v, lo, hi in zip(CONDITION_NAMES, cond, saved["condition_min"], saved["condition_max"]) if v < lo - tolerance or v > hi + tolerance]
    result["efficiency_outside_0_1"] = not 0 <= result["eta_pred"] <= 1
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    if args.output:
        write_json(args.output, result)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    prep = sub.add_parser("prepare", help="从OpenFOAM边界或分组表面文件生成几何数据，整理标签")
    prep.add_argument("--geometry-config", required=True)
    prep.add_argument("--samples", help="性能标签CSV；省略则只预处理几何，供新泵推理使用")
    prep.add_argument("--out", required=True)
    prep.add_argument("--pool-points", type=int, default=8192, help="缓存总点数，四类各占1/4")
    prep.add_argument("--seed", type=int, default=42)
    tr = sub.add_parser("train", help="调用PhysicsNeMo GeoTransolver训练性能模型")
    tr.add_argument("--data", required=True)
    tr.add_argument("--out", required=True)
    tr.add_argument("--epochs", type=int, default=300)
    tr.add_argument("--batch-size", type=int, default=2)
    tr.add_argument("--points", type=int, default=2048)
    tr.add_argument("--hidden", type=int, default=128)
    tr.add_argument("--layers", type=int, default=4)
    tr.add_argument("--heads", type=int, default=4)
    tr.add_argument("--slices", type=int, default=32)
    tr.add_argument("--lr", type=float, default=3e-4)
    tr.add_argument("--patience", type=int, default=40)
    tr.add_argument("--seed", type=int, default=42)
    tr.add_argument("--device", choices=("auto", "cpu", "cuda"), default="auto")
    pr = sub.add_parser("predict", help="预测指定几何与工况的扬程、扭矩和效率")
    pr.add_argument("--checkpoint", required=True)
    pr.add_argument("--geometry", required=True, help="prepare生成的某个几何.npz")
    pr.add_argument("--n-rpm", required=True, type=float)
    pr.add_argument("--flow", required=True, type=float, help="体积流量，m³/s，不是m³/h")
    pr.add_argument("--rho", type=float, default=998.2, help="密度kg/m³；必须与任务定义一致")
    pr.add_argument("--mu", type=float, default=0.001003, help="动力黏度Pa·s，不是运动黏度nu")
    pr.add_argument("--seed", type=int, default=42)
    pr.add_argument("--device", choices=("auto", "cpu", "cuda"), default="auto")
    pr.add_argument("--output", help="可选的预测JSON输出文件")
    args = parser.parse_args()
    try:
        {"prepare": prepare, "train": train, "predict": predict}[args.command](args)
    except (ValueError, RuntimeError, FileNotFoundError, KeyError, ImportError, FloatingPointError) as exc:
        parser.exit(2, f"错误：{exc}\n")


if __name__ == "__main__":
    main()
