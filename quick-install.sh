#!/usr/bin/env bash
#
# vps-gdrive-backup 一键部署安装脚本
# 支持: Ubuntu / Debian / CentOS / Rocky / Alma / Alpine / Arch / openSUSE
#
# 一键运行命令:
#   curl -fsSL https://raw.githubusercontent.com/firstwxx1/vps-gdrive-backup/main/quick-install.sh | bash
#
set -eo pipefail

REPO_RAW="https://raw.githubusercontent.com/firstwxx1/vps-gdrive-backup/main"
CONF_DIR="/etc/vps-backup"
BIN_DIR="/usr/local/bin"
DEFAULT_WEB_PORT=8999

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'
BOLD='\033[1m'

info()  { echo -e "${GREEN}[+]${NC} $*"; }
warn()  { echo -e "${YELLOW}[!]${NC} $*"; }
err()   { echo -e "${RED}[x]${NC} $*" >&2; }
die()   { err "$*"; exit 1; }

[ "$(id -u)" -eq 0 ] || die "请使用 root 权限运行此脚本 (例如: sudo bash)"

clear 2>/dev/null || true
echo -e "${CYAN}========================================================================${NC}"
echo -e "${BOLD}${GREEN}        🚀 Google Drive 5TB VPS 自动备份与终端面板 一键部署${NC}"
echo -e "${CYAN}========================================================================${NC}"
echo -e " 源码仓库: ${BLUE}https://github.com/firstwxx1/vps-gdrive-backup${NC}"
echo -e " 操作系统: $(uname -s) $(uname -m)"
echo -e "${CYAN}------------------------------------------------------------------------${NC}\n"

# 1. 检测包管理器并安装基础依赖
PM=none
for p in apt-get dnf yum apk zypper pacman; do
    if command -v "$p" > /dev/null; then PM="$p"; break; fi
done
info "检测到系统包管理器: $PM"

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
        esac || warn "安装 $p 失败（可能已安装或名称不同）"
    done
}

info "正在安装基础依赖组件 (curl, tar, gzip, zstd, openssl, cron, python3)..."
case "$PM" in
    apt-get) apt-get update -qq > /dev/null 2>&1 || true
             pkg_install ca-certificates curl tar gzip zstd openssl unzip cron python3 python3-pip ;;
    dnf|yum) pkg_install epel-release 2>/dev/null || true
             pkg_install ca-certificates curl tar gzip zstd openssl unzip cronie python3 python3-pip ;;
    apk)     pkg_install bash ca-certificates curl tar gzip zstd openssl unzip coreutils python3 ;;
    zypper)  pkg_install ca-certificates curl tar gzip zstd openssl unzip cron python3 ;;
    pacman)  pacman -Sy > /dev/null 2>&1 || true
             pkg_install ca-certificates curl tar gzip zstd openssl unzip cronie python3 ;;
    *) warn "未识别包管理器，请确保已安装 curl, tar, gzip, zstd, openssl, python3" ;;
esac

# 2. 安装 / 升级 rclone
if ! command -v rclone > /dev/null; then
    info "正在安装最新版本 rclone ..."
    curl -fsSL https://rclone.org/install.sh | bash || die "rclone 自动安装失败，请检查网络"
else
    info "检测到已安装 rclone: $(rclone version | head -n 1)"
fi

# 3. 创建配置目录与下载核心脚本
info "正在从 GitHub 下载最新版本核心脚本..."
mkdir -p "$CONF_DIR" "$BIN_DIR"
chmod 700 "$CONF_DIR"

download() {
    local src="$REPO_RAW/$1"
    local dest="$2"
    curl -fsSL "$src" -o "$dest" || die "下载失败: $src"
}

download "vps-backup.sh" "$BIN_DIR/vps-backup"
chmod +x "$BIN_DIR/vps-backup"

download "vps-backup-panel.sh" "$BIN_DIR/vps-backup-panel"
chmod +x "$BIN_DIR/vps-backup-panel"
ln -sf "$BIN_DIR/vps-backup-panel" "$BIN_DIR/backup-panel"

download "web_panel.py" "$BIN_DIR/vps-backup-web.py"
chmod +x "$BIN_DIR/vps-backup-web.py"

download "backup.conf.example" "$CONF_DIR/backup.conf.example"

# 4. 生成默认配置文件（若不存在）
if [ ! -f "$CONF_DIR/backup.conf" ]; then
    info "初始化本地备份配置: $CONF_DIR/backup.conf"
    cat > "$CONF_DIR/backup.conf" <<EOF
# VPS 备份配置
RCLONE_REMOTE="gdrive"
REMOTE_BASE="vps-backup"
BACKUP_NAME="$(hostname -s 2>/dev/null || hostname)"

STREAM_UPLOAD="true"
COMPRESSION="auto"
KEEP_DAILY_DAYS=7
KEEP_WEEKLY_DAYS=28
KEEP_MONTHLY_DAYS=180

ARCHIVE_ENABLED="true"
ARCHIVE_PATHS=(
    /etc
    /root
    /opt
    /home
)
ARCHIVE_EXCLUDES=(
    "*.log"
    "*.tmp"
    "node_modules"
    ".cache"
    "__pycache__"
    "*/logs/*"
    "*/log/*"
    "/opt/docker"
)

# Docker 容器数据库热备份 (容器名称)
DOCKER_MYSQL_CONTAINERS=()
DOCKER_PG_CONTAINERS=()

RCLONE_EXTRA_FLAGS="--tpslimit 4 --drive-chunk-size 128M"
LOG_FILE="/var/log/vps-backup.log"
EOF
    chmod 600 "$CONF_DIR/backup.conf"
else
    info "保留已有备份配置: $CONF_DIR/backup.conf"
fi

# 5. 配置 Web 终端管理面板服务 (systemd)
info "正在部署 Web 终端管理面板服务 (端口: $DEFAULT_WEB_PORT)..."
if [ ! -f "$CONF_DIR/web.conf" ]; then
    RAND_PASS=$(tr -dc A-Za-z0-9 </dev/urandom | head -c 12 || echo "Admin8888")
    echo "PASSWORD=\"$RAND_PASS\"" > "$CONF_DIR/web.conf"
    chmod 600 "$CONF_DIR/web.conf"
    WEB_PASS="$RAND_PASS"
else
    WEB_PASS=$(grep '^PASSWORD=' "$CONF_DIR/web.conf" | cut -d'=' -f2 | tr -d '"'\'' ')
fi

if command -v systemctl >/dev/null && [ -d /etc/systemd/system ]; then
    cat > /etc/systemd/system/vps-backup-web.service <<EOF
[Unit]
Description=VPS Google Drive Backup Web Terminal Panel
After=network.target

[Service]
Type=simple
User=root
ExecStart=/usr/bin/python3 $BIN_DIR/vps-backup-web.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
    systemctl daemon-reload
    systemctl enable --now vps-backup-web >/dev/null 2>&1 || true
fi

# 6. 配置每日定时任务 (每天凌晨 3:00~3:59 随机错峰执行)
MINUTE=$((RANDOM % 60))
HOUR=3
CRON_FILE="/etc/cron.d/vps-backup"

if [ -d /etc/cron.d ] && [ ! -f /etc/alpine-release ]; then
    cat > "$CRON_FILE" <<EOF
SHELL=/bin/bash
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
$MINUTE $HOUR * * * root $BIN_DIR/vps-backup >/dev/null 2>&1
EOF
    chmod 644 "$CRON_FILE"
else
    (crontab -l 2>/dev/null | grep -v 'vps-backup' ; echo "$MINUTE $HOUR * * * $BIN_DIR/vps-backup >/dev/null 2>&1") | crontab -
fi
info "定时备份任务设置完成: 每天 $(printf '%02d:%02d' "$HOUR" "$MINUTE") 执行"

# 7. 检查 Google Drive rclone 授权状态
echo -e "\n${CYAN}------------------------------------------------------------------------${NC}"
RC_CONFIG_FILE=$(rclone config file 2>/dev/null | tail -n 1)
HAS_GDRIVE=0
if rclone listremotes 2>/dev/null | grep -q '^gdrive:'; then
    HAS_GDRIVE=1
fi

if [ "$HAS_GDRIVE" -eq 1 ]; then
    echo -e "${GREEN}✅ 检测到已配置 Google Drive 远端 (gdrive:)！${NC}"
else
    echo -e "${YELLOW}⚠️ 尚未检测到名为 [gdrive] 的 Google Drive 授权。${NC}"
    echo -e "配置方式任选其一："
    echo -e "  1. 运行 ${BOLD}rclone config${NC} 新建类型为 drive、名称为 gdrive 的远端"
    echo -e "  2. 或将本机 Windows/Mac 生成的 ${BOLD}rclone.conf${NC} 复制到: ${BOLD}$RC_CONFIG_FILE${NC}"
fi

SERVER_IP=$(curl -s4 --max-time 3 ifconfig.me || hostname -I 2>/dev/null | awk '{print $1}' || echo "你的VPS_IP")

echo -e "\n${CYAN}========================================================================${NC}"
echo -e "${BOLD}${GREEN}  🎉 vps-gdrive-backup 一键部署安装完成！${NC}"
echo -e "${CYAN}========================================================================${NC}"
echo -e " 💻 ${BOLD}Web 终端管理面板${NC}:"
echo -e "    网址: ${BLUE}http://${SERVER_IP}:${DEFAULT_WEB_PORT}${NC}"
echo -e "    密码: ${YELLOW}${WEB_PASS}${NC} (可在 $CONF_DIR/web.conf 修改)"
echo
echo -e " 🖥️ ${BOLD}SSH 命令行管理终端面板${NC}:"
echo -e "    运行命令: ${GREEN}backup-panel${NC}  或  ${GREEN}vps-backup-panel${NC}"
echo
echo -e " 📋 ${BOLD}常用命令${NC}:"
echo -e "    vps-backup run       # 立即执行一次完整备份"
echo -e "    vps-backup list      # 列出云盘上的备份"
echo -e "    vps-backup test      # 自检测试连接"
echo -e "    tail -f /var/log/vps-backup.log"
echo -e "${CYAN}========================================================================${NC}\n"

# 如果处于可交互终端，询问是否立即打开管理面板
if [ -t 0 ] && [ -t 1 ]; then
    read -r -p "是否立即打开终端管理面板？[Y/n]: " open_now
    case "${open_now,,}" in
        n|no) exit 0 ;;
        *) exec "$BIN_DIR/vps-backup-panel" ;;
    esac
fi
