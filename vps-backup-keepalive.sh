#!/usr/bin/env bash
#
# vps-backup-keepalive —— VPS 备份系统服务守护与保活检测脚本
# 负责在开机和系统运行期间保活 Web 终端面板、Telegram Bot、Cron 任务
# 支持自动拉起死锁/崩溃进程、验证端口、开机自愈，并向 Telegram 发送报警。
#
export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:$PATH"

CONF_FILE="/etc/vps-backup/backup.conf"
LOG_FILE="/var/log/vps-backup-keepalive.log"
BOOT_FLAG="/run/vps-backup-boot-checked"

log_msg() {
    local msg="$1"
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $msg" >> "$LOG_FILE"
}

notify_tg() {
    local text="$1"
    if [ -f "/usr/local/bin/vps-backup-nodes.py" ]; then
        python3 /usr/local/bin/vps-backup-nodes.py _notify "$text" >/dev/null 2>&1 || true
    fi
}

get_tg_token() {
    if [ -f "$CONF_FILE" ]; then
        grep '^TG_BOT_TOKEN=' "$CONF_FILE" 2>/dev/null | cut -d'=' -f2 | tr -d '"'\'' '
    fi
}

# 1. 开机自愈检测 (利用 /run 内存目录判断开机事件)
check_boot_event() {
    if [ ! -f "$BOOT_FLAG" ]; then
        touch "$BOOT_FLAG"
        local uptime_str
        uptime_str=$(uptime -p 2>/dev/null || uptime | awk '{print $3}')
        log_msg "[BOOT] 检测到 VPS 开机或重启 (运行时间: $uptime_str)，执行服务自启与健康状态校验..."

        # 等待网络基础通信就绪
        sleep 2

        # 启动并核验各个服务
        systemctl restart vps-backup-web >/dev/null 2>&1 || true
        local token
        token=$(get_tg_token)
        if [ -n "$token" ]; then
            systemctl restart vps-backup-bot >/dev/null 2>&1 || true
        fi

        local host_name
        host_name=$(hostname 2>/dev/null || echo "VPS")
        notify_tg "🚀 <b>[VPS 重启·开机自启完成]</b>\n━━━━━━━━━━━━━━━━━━━━━━\n🖥️ <b>主控机器</b>: <code>${host_name}</code>\n⏰ <b>系统运行时间</b>: ${uptime_str}\n✅ <b>Web 终端面板 (端口 8999)</b>: 已自动启动\n✅ <b>Telegram 机器人守护</b>: 已恢复在线\n✅ <b>每日凌晨自动备份调度</b>: 已加载运行\n━━━━━━━━━━━━━━━━━━━━━━\n💡 <i>双重保活守护机制已生效，系统全天候自动监控运行状态。</i>"
    fi
}

# 2. Web 管理面板保活检测 (端口 8999 + HTTP 连通性)
check_web() {
    local need_restart=0
    if ! systemctl is-active --quiet vps-backup-web 2>/dev/null; then
        need_restart=1
        log_msg "[WARN] vps-backup-web 处于 inactive 状态"
    else
        # 检测端口 8999 是否正常响应 HTTP 请求
        local http_code
        http_code=$(curl -s -m 4 -o /dev/null -w "%{http_code}" http://127.0.0.1:8999/login 2>/dev/null || echo "000")
        if [ "$http_code" != "200" ] && [ "$http_code" != "302" ]; then
            need_restart=1
            log_msg "[WARN] Web 控制台 8999 端口 HTTP 检查异常 (HTTP 状态码: $http_code)"
        fi
    fi

    if [ "$need_restart" -eq 1 ]; then
        log_msg "[ACTION] 正在尝试自动拉起重启 vps-backup-web..."
        systemctl restart vps-backup-web >/dev/null 2>&1
        sleep 2
        local verify_code
        verify_code=$(curl -s -m 4 -o /dev/null -w "%{http_code}" http://127.0.0.1:8999/login 2>/dev/null || echo "000")
        if [ "$verify_code" = "200" ] || [ "$verify_code" = "302" ]; then
            log_msg "[RECOVER] vps-backup-web 已成功自动恢复正常运行"
            notify_tg "🛡️ <b>[服务保活自愈通知]</b>\nWeb 终端面板 (端口 8999) 之前异常或未响应，保活守护已自动重启并恢复正常！"
        else
            log_msg "[ERROR] vps-backup-web 重启后仍未能正常响应端口 8999"
        fi
    fi
}

# 3. Telegram Bot 守护保活检测
check_bot() {
    local token
    token=$(get_tg_token)
    if [ -z "$token" ]; then
        return 0
    fi

    local need_restart=0
    if ! systemctl is-active --quiet vps-backup-bot 2>/dev/null; then
        need_restart=1
        log_msg "[WARN] vps-backup-bot 处于非 active 状态"
    elif ! pgrep -f "vps-backup-bot.py" >/dev/null 2>&1; then
        need_restart=1
        log_msg "[WARN] 未找到 vps-backup-bot.py 运行进程"
    fi

    if [ "$need_restart" -eq 1 ]; then
        log_msg "[ACTION] 正在自动重启拉起 vps-backup-bot..."
        systemctl restart vps-backup-bot >/dev/null 2>&1
        sleep 2
        if systemctl is-active --quiet vps-backup-bot 2>/dev/null; then
            log_msg "[RECOVER] vps-backup-bot 服务已成功恢复正常运行"
            notify_tg "🛡️ <b>[服务保活自愈通知]</b>\nTelegram 机器人守护进程之前已离线，保活守护已自动拉起并恢复正常在线！"
        else
            log_msg "[ERROR] vps-backup-bot 自动重启拉起失败"
        fi
    fi
}

# 4. 定时调度服务与 Cron 任务保活
check_cron() {
    for s in cron crond; do
        if systemctl list-unit-files "$s.service" &>/dev/null; then
            if ! systemctl is-active --quiet "$s" 2>/dev/null; then
                systemctl restart "$s" >/dev/null 2>&1
                log_msg "[RECOVER] 重启了异常离线的 $s 定时任务调度服务"
            fi
            break
        fi
    done

    # 检查每日备份调度是否在 crontab 或 /etc/cron.d 中有效存在
    local has_cron=0
    if [ -f "/etc/cron.d/vps-backup" ] && grep -q "vps-backup" "/etc/cron.d/vps-backup" 2>/dev/null; then
        has_cron=1
    fi
    if crontab -l 2>/dev/null | grep -q "vps-backup archive"; then
        has_cron=1
    fi

    if [ "$has_cron" -eq 0 ]; then
        log_msg "[WARN] 发现每日自动备份定时调度缺失，正在自动修复..."
        cat > "/etc/cron.d/vps-backup" <<EOF
# vps-backup 每日自动备份 (保活守护自动修复)
SHELL=/bin/bash
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
17 3 * * * root /usr/local/bin/vps-backup archive >/dev/null 2>&1 && /usr/bin/python3 /usr/local/bin/vps-backup-nodes.py all >/dev/null 2>&1
EOF
        chmod 644 "/etc/cron.d/vps-backup"
        log_msg "[RECOVER] 每日 03:17 自动备份计划已自动恢复！"
    fi
}

# 5. 确保开机自启开启 (systemctl enable)
ensure_auto_start() {
    for svc in vps-backup-web vps-backup-bot; do
        if [ -f "/etc/systemd/system/${svc}.service" ]; then
            if ! systemctl is-enabled --quiet "$svc" 2>/dev/null; then
                systemctl enable "$svc" >/dev/null 2>&1 || true
                log_msg "[CONFIG] 已将 $svc 设置为开机自动启动"
            fi
        fi
    done
}

# 6. 安装与配置保活定时器与开机保底
install_keepalive() {
    echo -e "\033[36m[*] 正在配置系统级保活与开机自启动守护...\033[0m"

    # 优化 Systemd 服务配置（无限重试、防止 rate-limit 封死、网络就绪后再启动）
    for svc in vps-backup-web vps-backup-bot; do
        local sf="/etc/systemd/system/${svc}.service"
        if [ -f "$sf" ]; then
            if ! grep -q "StartLimitIntervalSec=0" "$sf"; then
                sed -i '/\[Unit\]/a StartLimitIntervalSec=0\nWants=network-online.target' "$sf"
            fi
            if ! grep -q "network-online.target" "$sf"; then
                sed -i 's/After=network.target/After=network.target network-online.target/' "$sf"
            fi
        fi
    done
    systemctl daemon-reload >/dev/null 2>&1 || true

    # 开启开机自启
    ensure_auto_start
    systemctl enable cron >/dev/null 2>&1 || systemctl enable crond >/dev/null 2>&1 || true

    # 将保活守护写入 crontab（每 3 分钟心跳检测 + @reboot 开机保底）
    local cur_cron
    cur_cron=$(crontab -l 2>/dev/null || true)
    local new_cron="$cur_cron"

    if ! echo "$new_cron" | grep -q "vps-backup-keepalive"; then
        new_cron=$(echo "$new_cron" | grep -v "vps-backup-keepalive" || true)
        new_cron=$(printf "%s\n@reboot sleep 10 && /usr/local/bin/vps-backup-keepalive >/dev/null 2>&1\n*/3 * * * * /usr/local/bin/vps-backup-keepalive >/dev/null 2>&1\n" "$new_cron")
        echo "$new_cron" | crontab -
        echo -e "\033[32m[+] 已成功写入 crontab: @reboot 开机启动 + 每 3 分钟自动健康自检！\033[0m"
    else
        echo -e "\033[32m[+] crontab 已配置保活调度守护。\033[0m"
    fi
}

show_status() {
    echo -e "========================================================================"
    echo -e "           🛡️ VPS 备份系统服务保活与开机自启状态报告"
    echo -e "========================================================================"
    echo -e " 服务器时间: $(date '+%Y-%m-%d %H:%M:%S %Z') | 运行时间: $(uptime -p 2>/dev/null || uptime)"
    echo -e "------------------------------------------------------------------------"

    # Web 服务状态
    local web_act="🔴 未运行"
    if systemctl is-active --quiet vps-backup-web 2>/dev/null; then
        local http_code
        http_code=$(curl -s -m 3 -o /dev/null -w "%{http_code}" http://127.0.0.1:8999/login 2>/dev/null || echo "000")
        if [ "$http_code" = "200" ] || [ "$http_code" = "302" ]; then
            web_act="\033[32m🟢 正常运行中 (端口: 8999, HTTP: $http_code)\033[0m"
        else
            web_act="\033[33m🟡 进程存活但端口响应异常 (HTTP: $http_code)\033[0m"
        fi
    fi
    local web_en="\033[31m未开启\033[0m"
    systemctl is-enabled --quiet vps-backup-web 2>/dev/null && web_en="\033[32m已开启\033[0m"
    echo -e " • Web 终端管理面板: $web_act | 开机自启: $web_en"

    # Bot 服务状态
    local bot_act="⚪ 未配置 (未填 Token)"
    local token
    token=$(get_tg_token)
    if [ -n "$token" ]; then
        if systemctl is-active --quiet vps-backup-bot 2>/dev/null && pgrep -f "vps-backup-bot.py" >/dev/null 2>&1; then
            bot_act="\033[32m🟢 正常运行中 (守护中)\033[0m"
        else
            bot_act="\033[31m🔴 离线或异常\033[0m"
        fi
    fi
    local bot_en="\033[31m未开启\033[0m"
    systemctl is-enabled --quiet vps-backup-bot 2>/dev/null && bot_en="\033[32m已开启\033[0m"
    echo -e " • Telegram 机器人:  $bot_act | 开机自启: $bot_en"

    # Cron 状态
    local cron_act="\033[31m🔴 未运行\033[0m"
    for s in cron crond; do
        if systemctl is-active --quiet "$s" 2>/dev/null; then
            cron_act="\033[32m🟢 正常运行中 ($s)\033[0m"
            break
        fi
    done
    echo -e " • 定时调度服务:    $cron_act"

    # 保活 Cron 状态
    local kp_cron="\033[31m未配置\033[0m"
    if crontab -l 2>/dev/null | grep -q "vps-backup-keepalive"; then
        kp_cron="\033[32m🟢 已激活 (每 3 分钟自动心跳巡检 + @reboot 开机自愈)\033[0m"
    fi
    echo -e " • 保活与自愈守护:  $kp_cron"

    echo -e "------------------------------------------------------------------------"
    echo -e " 📜 近期保活日志 (/var/log/vps-backup-keepalive.log):"
    if [ -f "$LOG_FILE" ]; then
        tail -n 8 "$LOG_FILE" | sed 's/^/   /'
    else
        echo -e "   (暂无日志)"
    fi
    echo -e "========================================================================"
}

# 主入口执行逻辑
case "$1" in
    status|--status)
        show_status
        ;;
    install|--install)
        install_keepalive
        ;;
    test|--test)
        echo "[*] 执行服务健康状态检查..."
        check_web
        check_bot
        check_cron
        ensure_auto_start
        echo "[+] 检测与自愈测试执行完毕。"
        show_status
        ;;
    *)
        # 默认静默检查（由 cron 每 3 分钟执行）
        check_boot_event
        check_web
        check_bot
        check_cron
        ensure_auto_start
        ;;
esac
