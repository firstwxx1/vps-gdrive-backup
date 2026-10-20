#!/usr/bin/env bash
#
# vps-backup-panel —— VPS 自动备份与多节点部署命令终端面板
#
set -o pipefail
export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:$PATH"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color
BOLD='\033[1m'

CONFIG_FILE="${VPS_BACKUP_CONFIG:-/etc/vps-backup/backup.conf}"

clear_screen() {
    clear 2>/dev/null || true
}

header() {
    clear_screen
    echo -e "${CYAN}========================================================================${NC}"
    echo -e "${BOLD}${GREEN}        🚀 Google Drive 5TB VPS 备份与多节点管理终端面板${NC}"
    echo -e "${CYAN}========================================================================${NC}"
    echo -e " 本机节点: ${YELLOW}$(hostname)${NC} | 系统时区: ${BLUE}$(date '+%Y-%m-%d %H:%M:%S %Z')${NC}"
    echo -e "${CYAN}------------------------------------------------------------------------${NC}"
}

pause() {
    echo
    read -r -p "按回车键返回主菜单..."
}

show_quota() {
    header
    echo -e "${BOLD}[*] 正在查询 Google Drive 5TB 容量与已用空间...${NC}\n"
    rclone about gdrive: 2>/dev/null || echo -e "${RED}查询失败，请检查 rclone 配置${NC}"
    pause
}

run_now() {
    header
    echo -e "${BOLD}[*] 准备开始执行备份...${NC}\n"
    echo -e "提示: 正在使用流式上传，自动热备份容器数据库，并打包上传到 Google Drive。"
    echo -e "详细日志将输出到 /var/log/vps-backup.log\n"
    /usr/local/bin/vps-backup run
    pause
}

list_backups() {
    header
    echo -e "${BOLD}[*] 正在获取 Google Drive 上的备份文件列表...${NC}\n"
    /usr/local/bin/vps-backup list
    pause
}

restore_backup() {
    header
    echo -e "${BOLD}[*] 恢复备份到独立测试目录${NC}\n"
    echo -e "云盘上的近期备份："
    rclone lsf --max-depth 2 gdrive:vps-backup/ 2>/dev/null | grep -E '\.tar|\.enc' || true
    echo
    read -r -p "请输入要恢复的文件名或路径: " fname
    if [ -z "$fname" ]; then
        echo -e "${YELLOW}未输入文件名，操作取消${NC}"
    else
        read -r -p "请输入解压目标目录 [默认 /root/vps-restore]: " tdir
        tdir="${tdir:-/root/vps-restore}"
        echo -e "\n[*] 开始恢复 $fname 到 $tdir ..."
        /usr/local/bin/vps-backup restore "$fname" "$tdir"
    fi
    pause
}

tail_logs() {
    header
    echo -e "${BOLD}[*] 实时查看备份日志 (按 Ctrl+C 退出)${NC}\n"
    if [ -f /var/log/vps-backup.log ]; then
        tail -n 50 -f /var/log/vps-backup.log
    else
        echo -e "${YELLOW}日志文件 /var/log/vps-backup.log 尚未生成${NC}"
        pause
    fi
}

deploy_new_vps() {
    header
    echo -e "${BOLD}${CYAN}=== 部署新 VPS / 服务器自动备份节点 ===${NC}\n"
    echo "将本机已配置好的 5TB Google Drive 授权和备份程序自动部署到其他服务器。"
    echo
    read -r -p "请输入新服务器 IP 地址或域名: " r_host
    if [ -z "$r_host" ]; then echo -e "${YELLOW}已取消${NC}"; pause; return; fi
    read -r -p "请输入 SSH 端口 [默认 22]: " r_port
    r_port="${r_port:-22}"
    read -r -p "请输入 SSH 用户名 [默认 root]: " r_user
    r_user="${r_user:-root}"
    read -s -r -p "请输入 SSH 密码 (若已配置密钥可直接回车): " r_pass
    echo

    echo -e "\n[*] 开始自动连接并部署到 $r_user@$r_host:$r_port ..."
    
    # 借助 python paramiko 或 sshpass 进行部署
    python3 -c "
import paramiko, sys, os

host = '$r_host'
port = int('$r_port')
user = '$r_user'
password = '''$r_pass''' if '''$r_pass''' else None

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
try:
    print(f'[+] 正在建立 SSH 连接到 {user}@{host}:{port} ...')
    client.connect(host, port=port, username=user, password=password, timeout=15)
    print('[+] 连接成功！创建远程临时安装目录...')
    remote_tmp = '/tmp/vps-backup-installer'
    client.exec_command(f'rm -rf {remote_tmp} && mkdir -p -m 700 {remote_tmp}')
    
    sftp = client.open_sftp()
    print('[+] 上传程序脚本与 Google Drive 授权配置...')
    for f in ['/usr/local/bin/vps-backup', '/etc/vps-backup/backup.conf.example']:
        if os.path.exists(f):
            sftp.put(f, f'{remote_tmp}/' + os.path.basename(f))
            
    # 上传 rclone 授权配置
    rc_conf = os.path.expanduser('~/.config/rclone/rclone.conf')
    if os.path.exists(rc_conf):
        sftp.put(rc_conf, f'{remote_tmp}/rclone.conf')
    sftp.close()
    
    print('[+] 执行远程自动化安装...')
    cmd = f'cd {remote_tmp} && curl -fsSL https://rclone.org/install.sh | bash && install -m 755 vps-backup /usr/local/bin/ && mkdir -p ~/.config/rclone && cp -f rclone.conf ~/.config/rclone/ && mkdir -p /etc/vps-backup && cp -n backup.conf.example /etc/vps-backup/backup.conf && (crontab -l 2>/dev/null | grep -v vps-backup ; echo \"$((RANDOM % 60)) 3 * * * /usr/local/bin/vps-backup >/dev/null 2>&1\") | crontab - && rm -rf {remote_tmp}'
    stdin, stdout, stderr = client.exec_command(cmd, get_pty=True)
    for line in stdout:
        print('  ' + line.rstrip())
        
    print('[+] 测试新服务器的云盘连接...')
    stdin, stdout, stderr = client.exec_command('/usr/local/bin/vps-backup test', get_pty=True)
    for line in stdout:
        print('  ' + line.rstrip())
    client.close()
    print('\n[OK] 新服务器部署成功！已加入每日定时自动备份。')
except Exception as e:
    print(f'[ERROR] 部署失败: {e}')
"
    pause
}

edit_config() {
    header
    echo -e "${BOLD}[*] 编辑备份配置文件: $CONFIG_FILE${NC}\n"
    if command -v nano >/dev/null; then
        nano "$CONFIG_FILE"
    else
        vim "$CONFIG_FILE"
    fi
}

run_test() {
    header
    echo -e "${BOLD}[*] 运行系统自检与连接测试 (vps-backup test)...${NC}\n"
    /usr/local/bin/vps-backup test
    pause
}

configure_telegram() {
    header
    echo -e "${BOLD}${CYAN}=== 配置 Telegram 机器人控制面板 ===${NC}\n"
    echo -e "你可以通过手机 Telegram 随时控制备份、查看5TB云盘容量、查看实时日志与接收报警！"
    echo -e "获取步骤："
    echo -e "  1. 在 Telegram 搜索并打开 ${YELLOW}@BotFather${NC}"
    echo -e "  2. 发送 ${GREEN}/newbot${NC}，按提示给机器人起个名字和用户名"
    echo -e "  3. BotFather 会给你一串 Token，格式如: ${BLUE}123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ${NC}"
    echo
    read -r -p "请输入你的 Telegram Bot Token: " new_token
    new_token=$(echo "$new_token" | tr -d '[:space:]')
    if [ -z "$new_token" ]; then
        echo -e "${YELLOW}未输入 Token，操作已取消${NC}"
        pause
        return
    fi

    echo -e "\n[*] 正在验证 Bot Token 有效性..."
    bot_info=$(curl -s --max-time 10 "https://api.telegram.org/bot${new_token}/getMe")
    if ! echo "$bot_info" | grep -q '"ok":true'; then
        echo -e "${RED}[x] 验证失败！请检查 Token 是否输入正确，或 Telegram 服务连通性。${NC}"
        echo "错误信息: $bot_info"
        pause
        return
    fi

    bot_username=$(python3 -c "import json; print(json.loads('''$bot_info''')['result'].get('username', ''))" 2>/dev/null || echo "你的机器人")
    echo -e "${GREEN}[+] 验证成功！机器人名称: @${bot_username}${NC}"

    # 保存配置到 backup.conf
    sed -i "s|^TG_BOT_TOKEN=.*|TG_BOT_TOKEN=\"${new_token}\"|" "$CONFIG_FILE" 2>/dev/null || echo "TG_BOT_TOKEN=\"${new_token}\"" >> "$CONFIG_FILE"
    
    # 启动/重启 Telegram 机器人守护服务
    systemctl daemon-reload 2>/dev/null || true
    systemctl enable --now vps-backup-bot 2>/dev/null || true
    systemctl restart vps-backup-bot 2>/dev/null || true

    echo -e "\n${BOLD}${GREEN}🎉 Telegram 机器人控制面板已成功激活并启动！${NC}"
    echo -e "${YELLOW}👉 快速启用步骤：${NC}"
    echo -e "  1. 打开 Telegram，搜索你的机器人：${BOLD}@${bot_username}${NC}"
    echo -e "  2. 点击底部的 ${GREEN}【START】${NC} 或发送 ${GREEN}/start${NC}"
    echo -e "  3. 机器人将自动将你绑定为管理员，并弹出交互式管理面板！"
    pause
}

manage_web() {
    header
    echo -e "${BOLD}${CYAN}=== Web 终端管理面板管理 ===${NC}\n"
    local status="未运行"
    if systemctl is-active --quiet vps-backup-web 2>/dev/null; then
        status="${GREEN}运行中 (端口: 8999)${NC}"
    fi
    echo -e "Web 面板状态: $status"
    echo -e "访问地址: ${BLUE}http://$(curl -s4 ifconfig.me || hostname -I | awk '{print $1}'):8999${NC}"
    echo
    echo "1. 启动 Web 面板服务"
    echo "2. 停止 Web 面板服务"
    echo "3. 重启 Web 面板服务"
    echo "0. 返回"
    echo
    read -r -p "请选择: " w_opt
    case "$w_opt" in
        1) systemctl enable --now vps-backup-web 2>/dev/null; echo "已启动！" ;;
        2) systemctl stop vps-backup-web 2>/dev/null; echo "已停止！" ;;
        3) systemctl restart vps-backup-web 2>/dev/null; echo "已重启！" ;;
    esac
    pause
}

main_menu() {
    while true; do
        header
        echo -e "${BOLD}请选择管理操作：${NC}"
        echo
        echo -e "  ${GREEN}[1]${NC} ▶ 立即执行备份 (自动热备份数据库并上传到云盘)"
        echo -e "  ${GREEN}[2]${NC} 📊 查看 Google Drive 5TB 容量与配额"
        echo -e "  ${GREEN}[3]${NC} 📂 查看云盘上的备份列表 (日/周/月归档)"
        echo -e "  ${GREEN}[4]${NC} 🔄 一键恢复备份文件到测试目录"
        echo -e "  ${GREEN}[5]${NC} 📜 查看实时备份日志 (tail -f)"
        echo -e "  ${GREEN}[6]${NC} 🌐 一键部署新 VPS 节点 (批量纳入自动备份)"
        echo -e "  ${GREEN}[7]${NC} ⚙️ 编辑备份配置 (修改备份目录/数据库/策略)"
        echo -e "  ${GREEN}[8]${NC} 🩺 运行自检测试 (测试读写与 Telegram 通知)"
        echo -e "  ${GREEN}[9]${NC} 🤖 配置并启用 Telegram 手机控制面板 (内联交互按钮)"
        echo -e "  ${GREEN}[W]${NC} 💻 Web 浏览器终端管理面板开关"
        echo
        echo -e "  ${RED}[0]${NC} 退出面板"
        echo -e "${CYAN}------------------------------------------------------------------------${NC}"
        read -r -p "请输入选项编号: " choice
        case "${choice,,}" in
            1) run_now ;;
            2) show_quota ;;
            3) list_backups ;;
            4) restore_backup ;;
            5) tail_logs ;;
            6) deploy_new_vps ;;
            7) edit_config ;;
            8) run_test ;;
            9|t) configure_telegram ;;
            w) manage_web ;;
            0|q) clear_screen; exit 0 ;;
            *) echo -e "${RED}无效输入，请重新输入${NC}"; sleep 1 ;;
        esac
    done
}

main_menu
