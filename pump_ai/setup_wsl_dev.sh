#!/usr/bin/env bash
# 在 WSL Ubuntu 内执行。本脚本只配置本用户的 Miniconda / pump-cfd，
# 不覆盖 /usr/bin/python3，不复制 Windows CAD/Fluent/训练环境，也不运行 CFD 算例。
set -euo pipefail

task_script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
task_cache="$task_script_dir/.cache/wsl-setup"
task_conda="$HOME/miniconda3"
task_env="$task_conda/envs/pump-cfd"
mkdir -p "$task_cache"
# 退出前等待 tee 写完，避免 Windows 启动器结束子进程时截断日志末尾。
exec 3>&1
exec > >(tee -a "$task_cache/setup.log" >&3) 2>&1
task_log_pid=$!
function finish_setup_log() {
    local task_exit_code=$?
    trap - EXIT
    exec 1>&3 2>&3 3>&-
    wait "$task_log_pid" || true
    exit "$task_exit_code"
}
trap finish_setup_log EXIT

[[ $(uname -s) == Linux && $(uname -m) == x86_64 ]] || {
    printf '本安装脚本仅用于 Linux x86_64。\n' >&2; exit 1;
}

# 使用用户已调通的 Clash。代理只在当前进程生效，Shell 中另提供手动开关。
source "$task_script_dir/wsl-proxy.sh"
wsl_proxy on

# 固定安装包与官网 SHA256，避免 latest 变化造成不可复现。
# 安装包和日志留在 Windows 项目，不额外占用 Ubuntu 的下载目录。
task_installer="$task_cache/Miniconda3-py312_26.9.3-0-Linux-x86_64.sh"
task_sha=3b1bdae3d62f5f8a068e1ee3f822c37c89b6054f2608de485af066952290cc32
if [[ ! -x "$task_conda/bin/conda" ]]; then
    if [[ ! -f "$task_installer" ]] || ! printf '%s  %s\n' "$task_sha" "$task_installer" | sha256sum -c --status; then
        printf '\n[1/6] 下载官方 Miniconda 安装包\n'
        curl -fL --retry 2 --connect-timeout 15 --max-time 1800 \
            "https://repo.anaconda.com/miniconda/$(basename "$task_installer")" \
            -o "$task_installer"
    fi
    printf '%s  %s\n' "$task_sha" "$task_installer" | sha256sum -c -
    # -b 为无人值守安装，-p 指定 Linux 用户目录，不影响 Windows Conda。
    bash "$task_installer" -b -p "$task_conda"
fi

printf '\n[2/6] 初始化 Conda，关闭 base 自动激活\n'
"$task_conda/bin/conda" init bash
"$task_conda/bin/conda" config --set auto_activate false
# 只用 conda-forge 创建本项目环境，避免混合不同来源的二进制依赖。
# 已有 .condarc 不整体覆盖，逐项设置此新安装所需的选项。
"$task_conda/bin/conda" config --set channel_priority strict
"$task_conda/bin/conda" config --remove-key channels 2>/dev/null || true
"$task_conda/bin/conda" config --add channels conda-forge

# 安装可交互使用的代理函数，并与 conda init 一起持久化。
# 自动 source 只定义函数，不会强制每个新终端启用代理。
task_proxy_line="source \"$task_script_dir/wsl-proxy.sh\""
if ! grep -qxF "$task_proxy_line" "$HOME/.bashrc"; then
    printf '\n# WSL Clash proxy: wsl_proxy on / off\n%s\n' "$task_proxy_line" >> "$HOME/.bashrc"
fi

printf '\n[3/6] 创建独立的 pump-cfd Python 3.12 环境\n'
if [[ ! -x "$task_env/bin/python" ]]; then
    "$task_conda/bin/conda" create --yes --name pump-cfd \
        --override-channels --channel conda-forge python=3.12 pip
fi

printf '\n[4/6] 安装 CFD 自动化、数据、网格与开发包\n'
"$task_env/bin/python" -m pip install --isolated --no-cache-dir \
    --root-user-action=ignore --index-url https://pypi.org/simple --upgrade pip
# 若已从官方 PyPI 预下载并校验 Linux wheel，直接使用这些本地文件。
# 缓存位于 Windows，避免在 Ubuntu 再保留一套下载文件。
shopt -s nullglob
task_wheels=("$task_cache/wheels/"*.whl)
shopt -u nullglob
# 若 Windows 缓存中已有经过发布校验的临时 uv 二进制，可并行下载依赖。
# uv 只作为安装辅助工具，不装进 Ubuntu，也不改变 Conda 的环境管理方式。
if [[ -x "$task_cache/uv/uv" ]]; then
    UV_CONCURRENT_DOWNLOADS=8 UV_HTTP_TIMEOUT=180 \
        "$task_cache/uv/uv" --no-config --no-cache pip install \
        --python "$task_env/bin/python" --link-mode=copy --index-url https://pypi.org/simple \
        --requirement "$task_script_dir/requirements-wsl.txt" "${task_wheels[@]}"
else
    "$task_env/bin/python" -m pip install --isolated --no-cache-dir \
        --root-user-action=ignore --index-url https://pypi.org/simple \
        --requirement "$task_script_dir/requirements-wsl.txt" \
        "${task_wheels[@]}"
fi
"$task_env/bin/python" -m ipykernel install --user --name pump-cfd \
    --display-name 'Python (WSL pump-cfd)'

printf '\n[5/6] 检查依赖、数值计算与网格读写（不运行 CFD 求解）\n'
"$task_env/bin/python" -m pip check
PATH="$task_env/bin:$PATH" "$task_env/bin/python" "$task_script_dir/check_wsl_dev.py"

printf '\n[6/6] 保存环境快照，整理缓存\n'
# 用版本列表生成锁文件，避免将本机缓存 wheel 的 file:// 地址固化进去。
"$task_env/bin/python" -m pip list --format=freeze > "$task_script_dir/requirements-wsl.lock.txt"
"$task_conda/bin/conda" list --name pump-cfd --explicit > "$task_script_dir/conda-wsl-linux-64.lock.txt"
"$task_conda/bin/conda" env export --name pump-cfd > "$task_cache/environment-installed.yml"
"$task_conda/bin/conda" clean --all --yes
mkdir -p "$HOME/pumpflow/cases" "$HOME/pumpflow/tmp"
printf '\n完成。重新打开终端后：conda activate pump-cfd\n'
printf '需要下载时：wsl_proxy on；关闭代理变量：wsl_proxy off\n'
printf 'Python: %s/bin/python\n' "$task_env"
