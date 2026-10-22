#!/usr/bin/env bash
#
# vps-backup 安装脚本：安装依赖 + rclone + 脚本 + 配置 + 每日定时任务
# 支持 Debian/Ubuntu、CentOS/RHEL/Rocky/Alma/Fedora、Alpine、Arch、openSUSE
#
# 用法: bash install.sh [选项]
#   --hour N            每天几点执行（默认 3，即凌晨 3 点，按 VPS 系统时区）
#   --minute N          第几分钟执行（默认随机 0-59，多台 VPS 自动错峰）
#   --config FILE       使用指定的 backup.conf（会覆盖已有配置，旧配置自动备份）
#   --rclone-conf FILE  安装指定的 rclone.conf（含 Google Drive 授权）
#   --no-cron           不创建定时任务
#   --uninstall         卸载（保留 /etc/vps-backup 配置）
#
set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN=/usr/local/bin/vps-backup
CONF_DIR=/etc/vps-backup
CRON_FILE=/etc/cron.d/vps-backup
HOUR=3
MINUTE=""
CONF_SRC=""
RCLONE_CONF_SRC=""
NO_CRON=0
UNINSTALL=0

info() { echo -e "\033[32m[+]\033[0m $*"; }
warn() { echo -e "\033[33m[!]\033[0m $*"; }
die()  { echo -e "\033[31m[x]\033[0m $*" >&2; exit 1; }

while [ $# -gt 0 ]; do
    case "$1" in
        --hour) HOUR="$2"; shift 2 ;;
        --minute) MINUTE="$2"; shift 2 ;;
        --config) CONF_SRC="$2"; shift 2 ;;
        --rclone-conf) RCLONE_CONF_SRC="$2"; shift 2 ;;
        --no-cron) NO_CRON=1; shift ;;
        --uninstall) UNINSTALL=1; shift ;;
        -h|--help) sed -n '2,15p' "$0"; exit 0 ;;
        *) die "未知参数: $1" ;;
    esac
done

[ "$(id -u)" -eq 0 ] || die "请使用 root 运行"

remove_cron() {
    rm -f "$CRON_FILE"
    if command -v crontab > /dev/null && crontab -l > /dev/null 2>&1; then
        { crontab -l 2> /dev/null | grep -v "$BIN" || true; } | crontab -
    fi
}

if [ "$UNINSTALL" = 1 ]; then
    remove_cron
    rm -f "$BIN"
    info "已卸载。配置保留在 $CONF_DIR，云盘上的备份不受影响"
    exit 0
fi

[[ "$HOUR" =~ ^[0-9]+$ ]] && [ "$HOUR" -le 23 ] || die "--hour 必须是 0-23"
[ -z "$MINUTE" ] || { [[ "$MINUTE" =~ ^[0-9]+$ ]] && [ "$MINUTE" -le 59 ]; } || die "--minute 必须是 0-59"
[ -f "$SCRIPT_DIR/vps-backup.sh" ] || die "找不到 $SCRIPT_DIR/vps-backup.sh"

# ---------------- 安装依赖 ----------------
PM=none
for p in apt-get dnf yum apk zypper pacman; do
    if command -v "$p" > /dev/null; then PM="$p"; break; fi
done
info "包管理器: $PM"

pkg_install() {
    local p
    for p in "$@"; do
        case "$PM" in
            apt-get) DEBIAN_FRONTEND=noninteractive apt-get install -y -qq "$p" > /dev/null 2>&1 ;;
            dnf|yum) "$PM" install -y -q "$p" > /dev/null 2>&1 ;;
            apk)     apk add --no-cache -q "$p" > /dev/null 2>&1 ;;
            zypper)  zypper -n -q install "$p" > /dev/null 2>&1 ;;
            pacman)  pacman -S --noconfirm --needed "$p" > /dev/null 2>&1 ;;
            *) false ;;
        esac || warn "安装 $p 失败（可忽略非必需组件）"
    done
}

case "$PM" in
    apt-get) apt-get update -qq > /dev/null 2>&1 || true
             pkg_install ca-certificates curl tar gzip zstd openssl unzip cron ;;
    dnf|yum) command -v zstd > /dev/null || pkg_install epel-release
             pkg_install ca-certificates curl tar gzip zstd openssl unzip cronie ;;
    apk)     pkg_install bash ca-certificates curl tar gzip zstd openssl unzip coreutils ;;
    zypper)  pkg_install ca-certificates curl tar gzip zstd openssl unzip cron ;;
    pacman)  pacman -Sy > /dev/null 2>&1 || true
             pkg_install ca-certificates curl tar gzip zstd openssl unzip cronie ;;
    *) warn "未识别的系统，请手动安装: curl tar gzip zstd openssl unzip cron" ;;
esac

command -v curl > /dev/null || die "curl 安装失败"
tar --version 2> /dev/null | grep -q GNU || die "需要 GNU tar"

# ---------------- 安装 rclone ----------------
if ! command -v rclone > /dev/null; then
    info "安装 rclone ..."
    curl -fsSL https://rclone.org/install.sh | bash || die "rclone 安装失败"
else
    info "rclone 已安装: $(rclone version | head -n 1)（可用 rclone selfupdate 升级）"
fi

# ---------------- 安装脚本 & 配置 ----------------
install -m 755 "$SCRIPT_DIR/vps-backup.sh" "$BIN"
info "脚本已安装: $BIN"

if [ -f "$SCRIPT_DIR/vps-backup-keepalive.sh" ]; then
    install -m 755 "$SCRIPT_DIR/vps-backup-keepalive.sh" /usr/local/bin/vps-backup-keepalive
    ln -sf /usr/local/bin/vps-backup-keepalive /usr/local/bin/vps-keepalive
fi
if [ -f "$SCRIPT_DIR/vps-backup-nodes.py" ]; then
    install -m 755 "$SCRIPT_DIR/vps-backup-nodes.py" /usr/local/bin/vps-backup-nodes.py
    ln -sf /usr/local/bin/vps-backup-nodes.py /usr/local/bin/vps-nodes
fi
if [ -f "$SCRIPT_DIR/vps-backup-panel.sh" ]; then
    install -m 755 "$SCRIPT_DIR/vps-backup-panel.sh" /usr/local/bin/vps-backup-panel
fi

mkdir -p "$CONF_DIR"; chmod 700 "$CONF_DIR"
install -m 644 "$SCRIPT_DIR/backup.conf.example" "$CONF_DIR/backup.conf.example"
if [ -n "$CONF_SRC" ]; then
    [ -f "$CONF_SRC" ] || die "找不到配置文件 $CONF_SRC"
    if [ -f "$CONF_DIR/backup.conf" ]; then
        cp -p "$CONF_DIR/backup.conf" "$CONF_DIR/backup.conf.bak.$(date +%Y%m%d%H%M%S)"
    fi
    install -m 600 "$CONF_SRC" "$CONF_DIR/backup.conf"
    info "配置已安装: $CONF_DIR/backup.conf"
elif [ ! -f "$CONF_DIR/backup.conf" ]; then
    install -m 600 "$SCRIPT_DIR/backup.conf.example" "$CONF_DIR/backup.conf"
    info "已生成默认配置: $CONF_DIR/backup.conf"
else
    info "保留已有配置: $CONF_DIR/backup.conf"
fi

if [ -n "$RCLONE_CONF_SRC" ]; then
    [ -f "$RCLONE_CONF_SRC" ] || die "找不到 $RCLONE_CONF_SRC"
    RC_DEST="${HOME:-/root}/.config/rclone/rclone.conf"
    mkdir -p "$(dirname "$RC_DEST")"
    [ -f "$RC_DEST" ] && cp -p "$RC_DEST" "$RC_DEST.bak.$(date +%Y%m%d%H%M%S)"
    install -m 600 "$RCLONE_CONF_SRC" "$RC_DEST"
    info "rclone 配置已安装: $RC_DEST"
fi

# ---------------- 定时任务 ----------------
if [ "$NO_CRON" = 0 ]; then
    [ -n "$MINUTE" ] || MINUTE=$((RANDOM % 60))
    remove_cron
    if [ -f /etc/alpine-release ] || [ ! -d /etc/cron.d ]; then
        command -v crontab > /dev/null || die "未找到 crontab，请先安装 cron"
        { crontab -l 2> /dev/null || true; echo "$MINUTE $HOUR * * * $BIN > /dev/null 2>&1"; } | crontab -
    else
        cat > "$CRON_FILE" <<EOF
# vps-backup 每日自动备份（由 install.sh 生成）
SHELL=/bin/bash
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
$MINUTE $HOUR * * * root $BIN > /dev/null 2>&1
EOF
        chmod 644 "$CRON_FILE"
    fi

    # 启动 cron 服务
    if [ -f /etc/alpine-release ]; then
        rc-update add crond default > /dev/null 2>&1 || true
        rc-service crond start > /dev/null 2>&1 || true
    elif command -v systemctl > /dev/null; then
        for s in cron crond cronie; do
            systemctl enable --now "$s" > /dev/null 2>&1 && break
        done
    fi
    [ -x /usr/local/bin/vps-backup-keepalive ] && /usr/local/bin/vps-backup-keepalive install > /dev/null 2>&1 || true
    info "定时任务: 每天 $(printf '%02d:%02d' "$HOUR" "$MINUTE") 执行（系统时区: $(date +%Z)）"
fi

echo
info "安装完成！接下来："
RC_FILE=$(rclone config file 2> /dev/null | tail -n 1)
if ! rclone listremotes 2> /dev/null | grep -q .; then
    echo "  1. 配置 Google Drive：rclone config（或把电脑上配置好的 rclone.conf 复制到 $RC_FILE）"
else
    echo "  1. 已检测到 rclone 远端: $(rclone listremotes | tr '\n' ' ')"
fi
echo "  2. 编辑配置：nano $CONF_DIR/backup.conf"
echo "  3. 测试：    vps-backup test"
echo "  4. 立即备份：vps-backup run     （日志：tail -f /var/log/vps-backup.log）"
