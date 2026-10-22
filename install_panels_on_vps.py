import paramiko
import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def deploy_panels_and_bot():
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    print("[*] 连接到 45.130.166.10 ...")
    client.connect("45.130.166.10", port=22, username="root", password="Hsb35901147411", timeout=15)
    
    sftp = client.open_sftp()
    
    # 1. 上传各面板脚本
    print("[+] 上传更新后的面板、多节点备份引擎、保活守护与 Telegram 机器人脚本...")
    sftp.put(os.path.join(BASE_DIR, "vps-backup-panel.sh"), "/usr/local/bin/vps-backup-panel")
    sftp.put(os.path.join(BASE_DIR, "web_panel.py"), "/usr/local/bin/vps-backup-web.py")
    sftp.put(os.path.join(BASE_DIR, "tg_bot.py"), "/usr/local/bin/vps-backup-bot.py")
    sftp.put(os.path.join(BASE_DIR, "vps-backup-nodes.py"), "/usr/local/bin/vps-backup-nodes.py")
    sftp.put(os.path.join(BASE_DIR, "vps-backup-keepalive.sh"), "/usr/local/bin/vps-backup-keepalive")
    sftp.close()
    
    cmd = """
    chmod +x /usr/local/bin/vps-backup-panel /usr/local/bin/vps-backup-web.py /usr/local/bin/vps-backup-bot.py /usr/local/bin/vps-backup-nodes.py /usr/local/bin/vps-backup-keepalive
    ln -sf /usr/local/bin/vps-backup-keepalive /usr/local/bin/vps-keepalive

    # 部署并加固 Web 终端管理面板服务
    cat > /etc/systemd/system/vps-backup-web.service <<EOF
[Unit]
Description=VPS Google Drive Backup Web Terminal Panel
After=network.target network-online.target
Wants=network-online.target
StartLimitIntervalSec=0

[Service]
Type=simple
User=root
ExecStart=/usr/bin/python3 /usr/local/bin/vps-backup-web.py
Restart=always
RestartSec=5
KillMode=mixed
TimeoutStopSec=10

[Install]
WantedBy=multi-user.target
EOF

    # 部署并加固 Telegram Bot 服务
    cat > /etc/systemd/system/vps-backup-bot.service <<EOF
[Unit]
Description=VPS Google Drive Backup Telegram Bot Daemon
After=network.target network-online.target
Wants=network-online.target
StartLimitIntervalSec=0

[Service]
Type=simple
User=root
ExecStart=/usr/bin/python3 /usr/local/bin/vps-backup-bot.py
Restart=always
RestartSec=5
KillMode=mixed
TimeoutStopSec=10

[Install]
WantedBy=multi-user.target
EOF

    systemctl daemon-reload
    systemctl enable vps-backup-web vps-backup-bot cron 2>/dev/null || true
    systemctl restart vps-backup-web
    systemctl restart vps-backup-bot

    # 执行保活与开机自启安装
    /usr/local/bin/vps-backup-keepalive install

    echo "=== 服务保活与健康自检报告 ==="
    /usr/local/bin/vps-backup-keepalive status
    """
    stdin, stdout, stderr = client.exec_command(cmd)
    out = stdout.read().decode('utf-8', errors='ignore')
    for line in out.splitlines():
        try:
            print("  " + line)
        except Exception:
            clean_line = line.encode('ascii', errors='backslashreplace').decode('ascii')
            print("  " + clean_line)
        
    client.close()
    print("[OK] VPS 上的面板与 Telegram Bot 服务已更新部署完成！")

if __name__ == '__main__':
    deploy_panels_and_bot()
