import paramiko
import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def install_panels():
    vps_ip = os.environ.get("VPS_IP", "45.130.166.10")
    vps_pass = os.environ.get("VPS_PASSWORD", "")
    if not vps_pass:
        import getpass
        vps_pass = getpass.getpass(f"请输入 VPS ({vps_ip}) root 密码: ")

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    print(f"[*] 连接到 {vps_ip} ...")
    client.connect(vps_ip, port=22, username="root", password=vps_pass, timeout=15)
    
    sftp = client.open_sftp()
    
    # 1. 上传 CLI 终端面板脚本
    print("[+] 上传交互式 CLI 终端面板 (vps-backup-panel)...")
    sftp.put(os.path.join(BASE_DIR, "vps-backup-panel.sh"), "/usr/local/bin/vps-backup-panel")
    
    # 2. 上传 Web 终端面板服务
    print("[+] 上传 Web 终端管理面板服务...")
    sftp.put(os.path.join(BASE_DIR, "web_panel.py"), "/usr/local/bin/vps-backup-web.py")
    
    sftp.close()
    
    # 3. 赋予权限 & 写入 systemd 服务
    cmd = """
    chmod +x /usr/local/bin/vps-backup-panel /usr/local/bin/vps-backup-web.py
    
    # 配置 web.conf 默认密码
    mkdir -p /etc/vps-backup
    if [ ! -f /etc/vps-backup/web.conf ]; then
        echo 'PASSWORD="Hsb35901147411"' > /etc/vps-backup/web.conf
        chmod 600 /etc/vps-backup/web.conf
    fi
    
    # 创建 systemd 服务
    cat > /etc/systemd/system/vps-backup-web.service <<EOF
[Unit]
Description=VPS Google Drive Backup Web Terminal Panel
After=network.target

[Service]
Type=simple
User=root
ExecStart=/usr/bin/python3 /usr/local/bin/vps-backup-web.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

    systemctl daemon-reload
    systemctl enable --now vps-backup-web
    systemctl status vps-backup-web --no-pager | head -n 10
    """
    
    print("[+] 安装 systemd 服务并启动...")
    stdin, stdout, stderr = client.exec_command(cmd)
    out = stdout.read().decode('utf-8', errors='ignore')
    for line in out.splitlines():
        print("  " + line.encode('ascii', errors='replace').decode('ascii'))
        
    client.close()
    print("[OK] 安装完成！")

if __name__ == '__main__':
    install_panels()
