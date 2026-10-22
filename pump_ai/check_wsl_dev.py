#!/usr/bin/env python3
"""轻量检查开发环境，不运行 CFD 算例，也不加载机器学习训练组件。"""

from __future__ import annotations

import importlib
import json
import os
import platform
import subprocess
import sys
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path


def main() -> None:
    # 包名与导入名不一致的情况在此明确映射，避免误报。
    packages = {
        "numpy": "numpy", "scipy": "scipy", "pandas": "pandas",
        "h5py": "h5py", "pyarrow": "pyarrow", "openpyxl": "openpyxl",
        "scikit-learn": "sklearn", "meshio": "meshio", "trimesh": "trimesh",
        "pyvista": "pyvista", "vtk": "vtk", "PyYAML": "yaml",
        "pydantic": "pydantic", "requests": "requests", "httpx": "httpx",
        "python-dotenv": "dotenv", "rich": "rich", "tqdm": "tqdm",
        "psutil": "psutil", "matplotlib": "matplotlib", "pytest": "pytest",
        "debugpy": "debugpy", "ipykernel": "ipykernel",
    }
    report = {
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "platform": platform.platform(),
        "python": sys.version,
        "executable": sys.executable,
        "packages": {},
    }
    assert platform.system() == "Linux", "请使用 WSL 的 Python 运行检查"
    assert sys.version_info[:2] == (3, 12), "pump-cfd 应使用 Python 3.12"
    for distribution, module in packages.items():
        importlib.import_module(module)
        report["packages"][distribution] = version(distribution)

    import h5py
    import meshio
    import numpy as np
    import pandas as pd
    import pyarrow as pa
    import pyarrow.parquet as pq
    import pyvista as pv
    from scipy.linalg import solve

    # 所有测试输出都写回 Windows 项目的已忽略目录，Ubuntu 不留示例数据副本。
    output = Path(__file__).resolve().parent / ".cache" / "wsl-setup"
    output.mkdir(parents=True, exist_ok=True)
    assert np.allclose(solve(np.eye(2), np.array([1.0, 2.0])), [1.0, 2.0])
    frame = pd.DataFrame({"Q_m3_s": [0.01, 0.02], "H_m": [12.0, 11.0]})
    pq.write_table(pa.Table.from_pandas(frame), output / "check.parquet")
    assert pd.read_parquet(output / "check.parquet").equals(frame)
    with h5py.File(output / "check.h5", "w") as handle:
        handle["Q_m3_s"] = frame["Q_m3_s"].to_numpy()
    with h5py.File(output / "check.h5", "r") as handle:
        assert np.allclose(handle["Q_m3_s"][:], frame["Q_m3_s"])

    # 实际往返读写三角面和 VTK 网格，验证二进制扩展，而非只检查 pip 列表。
    surface = pv.Cube().triangulate()
    surface.save(output / "check.vtp")
    assert pv.read(output / "check.vtp").n_cells == 12
    mesh = meshio.Mesh(np.array([[0., 0., 0.], [1., 0., 0.], [0., 1., 0.]]),
                       [("triangle", np.array([[0, 1, 2]]))])
    mesh.write(output / "check.vtu")
    assert meshio.read(output / "check.vtu").cells[0].data.shape == (1, 3)

    import matplotlib
    matplotlib.use("Agg")  # 验证不依赖桌面显示的图片输出。
    from matplotlib import pyplot as plt
    fig, ax = plt.subplots()
    ax.plot(frame["Q_m3_s"], frame["H_m"])
    fig.savefig(output / "check.png")
    plt.close(fig)

    # 仅验证加载环境后 OpenFOAM 可被发现；按用户要求不运行 CFD 算例。
    probe = subprocess.run(
        ["bash", "-c", "source /opt/openfoam14/etc/bashrc && printf '%s\\n' \"$WM_PROJECT_VERSION\" && command -v foamRun"],
        check=True, capture_output=True, text=True, timeout=30,
    )
    report["openfoam"] = probe.stdout.strip().splitlines()
    assert report["openfoam"][0] == "14"
    report["ruff"] = subprocess.check_output(["ruff", "--version"], text=True).strip()
    report["resource_summary"] = {
        "logical_cpus": os.cpu_count(),
        "memory_gib": round(importlib.import_module("psutil").virtual_memory().total / 1024**3, 2),
    }
    report["status"] = "PASS"
    (output / "verification.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
