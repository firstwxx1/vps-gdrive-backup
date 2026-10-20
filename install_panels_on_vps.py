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
    print("[+] 上传更新后的面板与 Telegram 机器人脚本...")
    sftp.put(os.path.join(BASE_DIR, "vps-backup-panel.sh"), "/usr/local/bin/vps-backup-panel")
    sftp.put(os.path.join(BASE_DIR, "web_panel.py"), "/usr/local/bin/vps-backup-web.py")
    sftp.put(os.path.join(BASE_DIR, "tg_bot.py"), "/usr/local/bin/vps-backup-bot.py")
    sftp.close()
    
    cmd = """
    chmod +x /usr/local/bin/vps-backup-panel /usr/local/bin/vps-backup-web.py /usr/local/bin/vps-backup-bot.py

    # 部署 Telegram Bot 服务
    cat > /etc/systemd/system/vps-backup-bot.service <<EOF
[Unit]
Description=VPS Google Drive Backup Telegram Bot Daemon
After=network.target

[Service]
Type=simple
User=root
ExecStart=/usr/bin/python3 /usr/local/bin/vps-backup-bot.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

    systemctl daemon-reload
    systemctl restart vps-backup-web
    systemctl enable vps-backup-bot 2>/dev/null || true
    echo "Web & Bot 服务状态："
    systemctl status vps-backup-web --no-pager | head -n 5
    """
    stdin, stdout, stderr = client.exec_command(cmd)
    out = stdout.read().decode('utf-8', errors='ignore')
    for line in out.splitlines():
        print("  " + line)
        
    client.close()
    print("[OK] VPS 上的面板与 Telegram Bot 服务已更新部署完成！")

if __name__ == '__main__':
    deploy_panels_and_bot()
