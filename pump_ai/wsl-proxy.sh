#!/usr/bin/env bash
# 在 ~/.bashrc 中 source 此文件后，可运行 wsl_proxy on / off。
# 每次重新读取默认路由，适应 WSL 重启后 Windows 网关地址变化。
# 仅修改当前 shell 的代理变量，不改系统 DNS、路由、Clash 或 Windows 防火墙。
# Clash 必须已开启“允许局域网”，混合端口默认为用户目前使用的 7895。
function wsl_proxy() {
    local task_action="${1:-on}"
    local task_gateway task_port
    case "$task_action" in
        on)
            task_gateway=$(ip -4 route show default | awk 'NR==1 {print $3}')
            task_port="${WSL_CLASH_PORT:-7895}"
            if [[ -z "$task_gateway" ]]; then
                printf '找不到 WSL 默认网关，代理未更改。\n' >&2
                return 1
            fi
            export http_proxy="http://${task_gateway}:${task_port}"
            export https_proxy="$http_proxy"
            export HTTP_PROXY="$http_proxy"
            export HTTPS_PROXY="$http_proxy"
            export no_proxy="localhost,127.0.0.1,::1,${task_gateway}"
            export NO_PROXY="$no_proxy"
            printf 'WSL proxy: %s\n' "$http_proxy"
            ;;
        off)
            unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY
            printf '已清除当前终端的 HTTP/HTTPS 代理变量。\n'
            ;;
        *)
            printf '用法：wsl_proxy on | off\n' >&2
            return 2
            ;;
    esac
}
