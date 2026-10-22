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
    echo -e " 本机节点: ${YELLOW}$(hostname)${NC} | 系统时区: ${BLUE}$(date '+%Y-%m-%d %H:%M:%S %Z')${NC} | 保活状态: ${GREEN}双重守护中${NC}"
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

manage_nodes() {
    while true; do
        header
        echo -e "${BOLD}${CYAN}=== 🌐 多服务器节点管理中心 ===${NC}\n"
        echo -e "已纳管远程节点列表："
        python3 /usr/local/bin/vps-backup-nodes.py list 2>/dev/null || echo -e "  ${YELLOW}(暂无远程节点)${NC}"
        echo
        echo -e "  ${GREEN}[1]${NC} ➕ 接入新 VPS 节点 (流式无感直传 Google Drive)"
        echo -e "  ${GREEN}[2]${NC} 🗑️ 移除/删除已纳管节点 (支持清空云盘备份)"
        echo -e "  ${GREEN}[3]${NC} ⚡ 立即执行全节点并发流式备份"
        echo -e "  ${GREEN}[4]${NC} 📂 查看 Google Drive 全节点备份文件"
        echo -e "  ${GREEN}[0]${NC} 返回主菜单"
        echo
        read -r -p "请选择管理操作 [0-4]: " n_opt
        case "$n_opt" in
            1) deploy_new_vps ;;
            2) delete_node_cli ;;
            3)
                echo -e "\n[*] 正在启动全节点流式备份..."
                python3 /usr/local/bin/vps-backup-nodes.py all
                pause
                ;;
            4) list_backups ;;
            0|q) break ;;
            *) echo -e "${RED}无效输入${NC}"; sleep 1 ;;
        esac
    done
}

delete_node_cli() {
    header
    echo -e "${BOLD}${CYAN}=== 🗑️ 删除 / 移除已纳管节点 ===${NC}\n"
    python3 /usr/local/bin/vps-backup-nodes.py list 2>/dev/null
    echo
    read -r -p "请输入要移除的节点名称 (例如 vps-124.222.59.251 或 serv00-ztwotv): " del_name
    del_name=$(echo "$del_name" | tr -d '[:space:]')
    if [ -z "$del_name" ]; then
        echo -e "${YELLOW}未输入节点名称，操作已取消${NC}"
        pause
        return
    fi

    echo
    echo -e "请选择删除模式："
    echo -e "  ${GREEN}[1]${NC} 仅移除监控 (保留 Google Drive 上的所有历史归档)"
    echo -e "  ${RED}[2]${NC} 彻底移除并清空该节点在云盘上的所有备份归档 (不可逆！)"
    echo -e "  ${YELLOW}[0]${NC} 取消"
    echo
    read -r -p "请选择 [1/2/0]: " del_choice
    case "$del_choice" in
        1)
            python3 /usr/local/bin/vps-backup-nodes.py del "$del_name"
            ;;
        2)
            read -r -p "⚠️ 确认要彻底清空该节点在 Google Drive 上的数据吗？(输入 yes 确认): " confirm
            if [ "$confirm" = "yes" ]; then
                python3 /usr/local/bin/vps-backup-nodes.py del "$del_name" --purge
            else
                echo -e "${YELLOW}操作已取消${NC}"
            fi
            ;;
        *)
            echo -e "${YELLOW}操作已取消${NC}"
            ;;
    esac
    pause
}

deploy_new_vps() {
    header
    echo -e "${BOLD}${CYAN}=== 🌐 接入并纳管新 VPS 节点 ===${NC}\n"
    echo "通过海外主控建立跨国 SSH 隧道，流式打包目标机数据直传 Google Drive 5TB。"
    echo "支持国内无外网机器/非root sudo用户/Serv00，零占用目标机磁盘、免安装 rclone！"
    echo
    read -r -p "请输入新服务器 IP 地址或域名: " r_host
    if [ -z "$r_host" ]; then echo -e "${YELLOW}已取消${NC}"; pause; return; fi
    read -r -p "请输入 SSH 端口 [默认 22]: " r_port
    r_port="${r_port:-22}"
    read -r -p "请输入 SSH 用户名 [默认 root]: " r_user
    r_user="${r_user:-root}"
    read -s -r -p "请输入 SSH 密码: " r_pass
    echo

    echo -e "\n[*] 开始建立连接并接入节点 $r_user@$r_host:$r_port ..."
    python3 -c "
import paramiko, json, os, subprocess

host = '$r_host'
port = int('$r_port')
user = '$r_user'
password = '''$r_pass''' if '''$r_pass''' else None

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
try:
    print(f'[+] 正在验证 SSH 连接 {user}@{host}:{port} ...')
    client.connect(host, port=port, username=user, password=password, timeout=15)
    _, stdout, _ = client.exec_command('hostname; uname -sr; df -h / | tail -n 1', timeout=15)
    info = stdout.read().decode('utf-8', errors='ignore').strip()
    client.close()
    print('[+] 连接验证成功！节点信息:\n' + info)

    node_name = f'vps-{host}'
    nodes_file = '/etc/vps-backup/nodes.json'
    nodes = []
    if os.path.exists(nodes_file):
        try:
            with open(nodes_file, 'r', encoding='utf-8') as f:
                nodes = json.load(f)
        except:
            nodes = []
    nodes = [n for n in nodes if n.get('host') != host]
    nodes.append({
        'name': node_name,
        'host': host,
        'port': port,
        'user': user,
        'password': '''$r_pass''',
        'type': 'serv00' if 'serv00' in host else 'linux'
    })
    os.makedirs(os.path.dirname(nodes_file), exist_ok=True)
    with open(nodes_file, 'w', encoding='utf-8') as f:
        json.dump(nodes, f, ensure_ascii=False, indent=2)
    os.chmod(nodes_file, 0o600)
    print(f'\n[OK] 节点 {node_name} 已成功注册并纳入每日凌晨定时备份调度！')
    print('[*] 正在执行首次流式直传备份测试...')
    subprocess.run(['python3', '/usr/local/bin/vps-backup-nodes.py', node_name])
except Exception as e:
    print(f'[ERROR] 接入失败: {e}')
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
    echo
    echo -e "${BOLD}[*] 检查保活守护与开机自启动状态...${NC}\n"
    /usr/local/bin/vps-backup-keepalive status 2>/dev/null || true
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
    local cur_pass="3590114741."
    if [ -f "/etc/vps-backup/web.conf" ]; then
        cur_pass=$(grep '^PASSWORD=' /etc/vps-backup/web.conf 2>/dev/null | cut -d'=' -f2 | tr -d '"'\'' ')
    fi
    echo -e "Web 面板状态: $status"
    echo -e "访问地址: ${BLUE}http://$(curl -s4 --max-time 3 ifconfig.me || hostname -I | awk '{print $1}'):8999${NC}"
    echo -e "当前管理密码: ${YELLOW}${cur_pass}${NC} (支持直接复制粘贴登录)"
    echo
    echo "1. 启动 Web 面板服务"
    echo "2. 停止 Web 面板服务"
    echo "3. 重启 Web 面板服务"
    echo "4. 修改 Web 面板管理密码"
    echo "0. 返回"
    echo
    read -r -p "请选择: " w_opt
    case "$w_opt" in
        1) systemctl enable --now vps-backup-web 2>/dev/null; echo "已启动！" ;;
        2) systemctl stop vps-backup-web 2>/dev/null; echo "已停止！" ;;
        3) systemctl restart vps-backup-web 2>/dev/null; echo "已重启！" ;;
        4)
            read -r -p "请输入新的 Web 面板登录密码: " new_pw
            new_pw=$(echo "$new_pw" | tr -d '[:space:]')
            if [ -n "$new_pw" ]; then
                echo "PASSWORD=\"$new_pw\"" > /etc/vps-backup/web.conf
                chmod 600 /etc/vps-backup/web.conf
                systemctl restart vps-backup-web 2>/dev/null || true
                echo -e "${GREEN}密码修改成功并已重启 Web 面板服务！${NC}"
            else
                echo -e "${YELLOW}未输入新密码，操作取消${NC}"
            fi
            ;;
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
        echo -e "  ${GREEN}[6]${NC} 🌐 多服务器节点管理中心 (部署新机 / 查看节点 / 删除节点)"
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
            6) manage_nodes ;;
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
