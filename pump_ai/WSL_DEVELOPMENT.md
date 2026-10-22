# Ubuntu 开发环境

这份配置用于当前 Windows 编辑器 + WSL2 Ubuntu 26.04 + OpenFOAM 14 的工作方式。
Windows 端保留 VaneCraft、Fluent、CAD 工具和已有 PhysicsNeMo 训练环境；
Ubuntu 负责 OpenFOAM 自动化、算例配置、网格与数据预处理。

2026-10-22 已完成安装：Conda 26.9.3、项目 Python 3.12.15；
`pip check`、数值与数据/网格读写自检、现有 10 项数据约定测试均通过。
Miniconda 与项目环境合计约 2.4 GiB，Ubuntu 下载缓存已清理。

## 安装内容与位置

| 内容 | 位置 |
| --- | --- |
| Ubuntu 自带 Python 3.14 | `/usr/bin/python3`，保持系统管理 |
| Miniconda（独立于 Windows Conda） | `/root/miniconda3` |
| 项目 Python 3.12 环境 | `/root/miniconda3/envs/pump-cfd` |
| OpenFOAM | `/opt/openfoam14` |
| CFD 算例与临时计算文件 | `/root/pumpflow/cases`、`/root/pumpflow/tmp` |
| 项目源代码 | Windows 当前仓库；WSL 通过 `/mnt/c/Users/AhaSac/Desktop/documents/fd/physicsnemo` 访问 |
| 安装包、日志、自检输出 | Windows 项目的 `pump_ai/.cache/wsl-setup/`，已由 `.gitignore` 排除 |

Python 包的用途见 [requirements-wsl.txt](requirements-wsl.txt) 中的逐组注释。
当前包括数值计算、数据格式、PyVista/VTK 与 STL 处理、HTTP API、图表、测试和调试工具。
本次安装为了减少等待，将大型 Linux wheel 预下载到 Windows 缓存并校验 PyPI SHA256；
临时 uv 安装辅助工具也在同一缓存目录，不安装进 Ubuntu。后续仍可正常使用 conda/pip。
PyVista/VTK 用于文件读取，不启动 ParaView 图形界面。
本次不复制 Windows 虚拟环境，也不在 Ubuntu 重装 CUDA、PyTorch 或 PhysicsNeMo 训练栈。
现有 `train_openfoam_pump.py prepare` 的数据预处理可使用这个环境；
`train` / `predict` 仍使用已有训练环境，需要 Linux 训练时再建立单独环境。

## 每次开发

在 Windows PowerShell 进入 Ubuntu：

```powershell
wsl -d Ubuntu
```

在 Ubuntu 激活环境并进入现有项目：

```bash
conda activate pump-cfd
cd /mnt/c/Users/AhaSac/Desktop/documents/fd/physicsnemo
python --version
# Python 应显示 3.12.x。
```

退出 Python 环境用 `conda deactivate`；退出 Ubuntu 用 `exit`。
Conda 的 base 默认不自动激活。OpenFOAM 的 bashrc 已由用户配置到 `~/.bashrc`。

## 下载与代理

新的交互终端会提供 `wsl_proxy` 函数，但不会自动启用代理。
需要下载包时：

```bash
wsl_proxy on
python -m pip install 包名
# 结束后可清除当前终端的 HTTP/HTTPS 代理变量。
wsl_proxy off
```

代理网关每次自动获取，端口默认 `7895`，与当前 Clash 的混合端口一致。
Clash 需要运行并启用“允许局域网”；TUN 可以继续开启。
如端口变更，在 `wsl_proxy on` 前执行 `export WSL_CLASH_PORT=实际端口`。
不要把随 WSL 重启可能变化的网关地址写死进 pip/conda 配置。

## 从 Windows 调用 Ubuntu Python

Windows 端的 Python 解释器列表不会自动成为 Linux 解释器。
如果继续使用普通 VS Code 窗口，可用 `wsl.exe` 启动 Linux Python；
自动化中建议指定解释器绝对路径，不依赖交互 shell 的 `conda activate`。

```powershell
wsl -d Ubuntu -- /root/miniconda3/envs/pump-cfd/bin/python --version
```

同时需要 OpenFOAM 的命令时，显式在 Bash 中加载 `/opt/openfoam14/etc/bashrc`。
安装目录属于当前默认 Linux 用户 root。以后迁移到普通用户时，应为该用户新建环境，
并重新注册 kernel，不要直接复制现有 Conda 目录。

## 重建与检查

安装脚本带有 SHA256 校验、已有环境检查以及实际数值/文件读写自检：

```bash
bash /mnt/c/Users/AhaSac/Desktop/documents/fd/physicsnemo/pump_ai/setup_wsl_dev.sh
```

也可在已有 Miniconda 中切换到 `pump_ai` 目录，再运行：

```bash
conda env create -f environment-wsl.yml
```

`requirements-wsl.lock.txt` 记录实际 Python 包版本；`conda-wsl-linux-64.lock.txt`
记录 Conda 运行时包的精确下载地址。重建同平台环境可先运行
`conda create -n pump-cfd --file conda-wsl-linux-64.lock.txt`，再在新环境运行
`python -m pip install -r requirements-wsl.lock.txt`。
这两个锁文件按 Linux x86_64 生成，不用于 Windows。

安装后的轻量检查（不运行 CFD 算例）：

```bash
conda activate pump-cfd
python pump_ai/check_wsl_dev.py
python -m pip check
```

自检报告在 `.cache/wsl-setup/verification.json`，包括实际版本、解释器路径和结果。
安装后只清理 Conda 的下载/未使用缓存；本地安装包和日志继续保留在 Windows 项目中。

## 官方参考

- [Miniconda Linux 安装](https://www.anaconda.com/docs/getting-started/miniconda/install/linux-install)
- [安装包与 SHA256](https://repo.anaconda.com/miniconda/)
- [Conda 环境管理](https://docs.conda.io/projects/conda/en/stable/user-guide/tasks/manage-environments.html)
- [uv 为指定 Python 环境安装包](https://docs.astral.sh/uv/pip/environments/)
