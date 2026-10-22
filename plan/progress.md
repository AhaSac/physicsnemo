# Ubuntu 开发环境配置进度

日期：2026-10-22（Asia/Shanghai）。本记录仅对应本次 WSL 环境配置。

- 已确认：WSL2 Ubuntu 26.04.1、Linux x86_64、24 逻辑核、约 31 GiB 内存。
- 已确认：系统 Python 为 3.14.4；OpenFOAM 14 位于 `/opt/openfoam14`。
- 已确认：经 Windows Clash 混合端口 7895 可下载，TUN 保持用户现有设置。
- 已完成：官方 Miniconda Python 3.12 安装包下载，并通过官网 SHA256 校验。
- 已完成：创建安装脚本、项目环境清单、依赖清单、代理函数与开发说明。
- 已完成：安装 Conda 26.9.3 到 `/root/miniconda3`，创建 Python 3.12.15 的 `pump-cfd`。
- 已完成：安装数值、数据、网格、API、图表、测试与调试依赖；注册 `pump-cfd` kernel。
- 已完成：新终端 Conda 激活与代理函数检查；`pip check`、包导入、数值计算、
  HDF5/Parquet 和 VTP/VTU 文件往返读写、无桌面图片输出检查均通过。
- 已完成：现有 10 项数据约定测试、检查脚本 Ruff 静态检查和 Bash 语法检查均通过。
- 已完成：保存两份实际版本锁文件；清理 Conda 下载缓存及重复分段文件。
  Miniconda 和项目环境合计约 2.4 GiB，完整安装包、wheel 与日志保留在 Windows 项目缓存。

状态：完成。使用说明见 `pump_ai/WSL_DEVELOPMENT.md`；自检报告见
`pump_ai/.cache/wsl-setup/verification.json`。

范围：Ubuntu 仅配置 CFD 自动化与数据预处理环境；Windows CAD/Fluent 与已有训练环境保留在本地。
按用户要求不运行官方 CFD 算例。系统 Python 保留，由 Conda 提供独立 Python 3.12。
