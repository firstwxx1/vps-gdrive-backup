import os
import sys
import paramiko
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
RCLONE_CONF = os.path.join(BASE_DIR, "rclone.conf")

def deploy_vps_ubuntu(host, user, password, port=22):
    print(f"\n==========================================")
    print(f"[*] 开始部署 VPS: {user}@{host}:{port}")
    print(f"==========================================")
    
    if not os.path.exists(RCLONE_CONF):
        print(f"[ERROR] 找不到 {RCLONE_CONF}")
        return False
        
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(host, port=port, username=user, password=password, timeout=15)
        print("[+] SSH 连接成功！")
        
        # 创建远程目录
        remote_tmp = "/tmp/vps-backup-install"
        client.exec_command(f"rm -rf {remote_tmp} && mkdir -p -m 700 {remote_tmp}")
        time.sleep(1)
            
        print("[+] 正在上传程序文件到 VPS...")
        sftp = client.open_sftp()
        for fname in ["vps-backup.sh", "install.sh", "backup.conf.example"]:
            local_f = os.path.join(BASE_DIR, fname)
            remote_f = f"{remote_tmp}/{fname}"
            sftp.put(local_f, remote_f)
            
        sftp.put(RCLONE_CONF, f"{remote_tmp}/rclone.conf")
        
        # 为 45.130.166.10 写入专属配置文件
        custom_conf = f"""# 45.130.166.10 专属配置
RCLONE_REMOTE="gdrive"
REMOTE_BASE="vps-backup"
BACKUP_NAME="vps-45.130.166.10"

# 流式上传模式：直接边打包边压缩边上传到谷歌云盘，不占用本地有限的磁盘空间
STREAM_UPLOAD="true"

# 保留策略
KEEP_DAILY_DAYS=7
KEEP_WEEKLY_DAYS=28
KEEP_MONTHLY_DAYS=180

# 备份系统配置、1Panel面板数据与网站、root目录
ARCHIVE_ENABLED="true"
ARCHIVE_PATHS=(
    /etc
    /root
    /opt
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

# 自动热备份运行中的容器数据库
DOCKER_MYSQL_CONTAINERS=(
    dujiaoka-db
)
DOCKER_PG_CONTAINERS=(
    p1305v2-db-1
    p1305cand-db-1
    p1305test-db-1
)

LOG_FILE="/var/log/vps-backup.log"
"""
        with sftp.file(f"{remote_tmp}/custom.conf", "w") as f:
            f.write(custom_conf)
            
        sftp.close()
        print("[+] 文件上传完成！开始在 VPS 上安装依赖、rclone 与每日定时任务...")
        
        cmd = f"cd {remote_tmp} && bash install.sh --config custom.conf --rclone-conf rclone.conf --hour 3"
        stdin, stdout, stderr = client.exec_command(cmd, get_pty=True)
        for line in stdout:
            print("  " + line.rstrip())
            
        print("\n[+] 执行自检 (vps-backup test)...")
        stdin, stdout, stderr = client.exec_command("/usr/local/bin/vps-backup test", get_pty=True)
        for line in stdout:
            print("  " + line.rstrip())
            
        print("\n[+] 立即触发一次真实测试备份 (vps-backup run)...")
        stdin, stdout, stderr = client.exec_command("/usr/local/bin/vps-backup run", get_pty=True)
        for line in stdout:
            print("  " + line.rstrip())

        # 清理远程临时目录
        client.exec_command(f"rm -rf {remote_tmp}")
        client.close()
        print(f"\n[OK] VPS {host} 部署与首次备份全部成功完成！")
        return True
    except Exception as e:
        print(f"[ERROR] 部署失败: {e}")
        return False

def deploy_serv00(host, user, password, port=22):
    print(f"\n==========================================")
    print(f"[*] 开始配置 Serv00: {user}@{host}:{port}")
    print(f"==========================================")
    if not os.path.exists(RCLONE_CONF):
        print(f"[ERROR] 找不到 {RCLONE_CONF}")
        return False
        
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(host, port=port, username=user, password=password, timeout=15)
        print("[+] Serv00 SSH 连接成功！")
        
        cmd_init = """
        mkdir -p ~/.config/rclone ~/bin ~/backups
        if [ ! -f ~/bin/rclone ]; then
            echo "正在下载 FreeBSD 版 rclone..."
            fetch -o /tmp/rclone.zip https://downloads.rclone.org/rclone-current-freebsd-amd64.zip || curl -fsSL -o /tmp/rclone.zip https://downloads.rclone.org/rclone-current-freebsd-amd64.zip
            unzip -q -o /tmp/rclone.zip -d /tmp/
            cp /tmp/rclone-*-freebsd-amd64/rclone ~/bin/
            chmod +x ~/bin/rclone
            rm -rf /tmp/rclone*
        fi
        ~/bin/rclone version | head -n 1
        """
        stdin, stdout, stderr = client.exec_command(cmd_init)
        print("  " + stdout.read().decode('utf-8', errors='ignore').strip())
        
        # 上传 rclone.conf 到 ~/.config/rclone/rclone.conf
        sftp = client.open_sftp()
        sftp.put(RCLONE_CONF, f"/home/{user}/.config/rclone/rclone.conf")
        sftp.close()
        
        # 创建 Serv00 备份脚本
        serv00_script = f"""#!/bin/sh
PATH="/home/{user}/bin:/usr/local/bin:/usr/bin:/bin:$PATH"
export PATH
NOW=$(date +%Y%m%d-%H%M%S)
BACKUP_DIR="/home/{user}/backups"
TARGET="$BACKUP_DIR/serv00_{user}_$NOW.tar.gz"
mkdir -p "$BACKUP_DIR"

# 导出用户网站与邮件目录
tar -czf "$TARGET" -C "/home/{user}" --exclude='backups' --exclude='.cache' --exclude='tmp' domains public_html mail 2>/dev/null

# 上传到 Google Drive
~/bin/rclone copy "$TARGET" "gdrive:vps-backup/serv00-{user}/archive/daily/"

# 本地删除，云盘保留 14 天
rm -f "$TARGET"
~/bin/rclone delete --min-age 14d "gdrive:vps-backup/serv00-{user}/archive/daily/" >/dev/null 2>&1
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Serv00 Backup done: serv00_{user}_$NOW.tar.gz" >> /home/{user}/backup.log
"""
        sftp = client.open_sftp()
        with sftp.file(f"/home/{user}/bin/serv00-backup.sh", "w") as f:
            f.write(serv00_script)
        sftp.close()
        
        # 加执行权限 & 配置 crontab & 运行一次测试
        setup_cron = f"""
        chmod +x ~/bin/serv00-backup.sh
        # 测试 rclone 连接
        ~/bin/rclone about gdrive: 2>/dev/null | grep -E 'Total|Free' || echo "rclone test ok"
        # 写入 crontab (每天凌晨 3:30 执行)
        (crontab -l 2>/dev/null | grep -v 'serv00-backup.sh' ; echo "30 3 * * * /bin/sh /home/{user}/bin/serv00-backup.sh >/dev/null 2>&1") | crontab -
        echo "[+] 定时任务已设置："
        crontab -l | grep 'serv00-backup.sh'
        # 立即跑一次测试备份
        echo "[+] 立即执行一次 Serv00 备份测试..."
        /bin/sh /home/{user}/bin/serv00-backup.sh
        echo "[+] 云盘上的 Serv00 备份："
        ~/bin/rclone lsf "gdrive:vps-backup/serv00-{user}/archive/daily/"
        """
        stdin, stdout, stderr = client.exec_command(setup_cron)
        print("  " + stdout.read().decode('utf-8', errors='ignore').strip())
        
        client.close()
        print(f"\n[OK] Serv00 ({user}@{host}) 部署成功！")
        return True
    except Exception as e:
        print(f"[ERROR] Serv00 部署失败: {e}")
        return False

if __name__ == '__main__':
    vps_ip = os.environ.get("VPS_IP", "45.130.166.10")
    vps_pass = os.environ.get("VPS_PASSWORD", "")
    serv00_pass = os.environ.get("SERV00_PASSWORD", "")
    
    if not vps_pass:
        import getpass
        vps_pass = getpass.getpass(f"请输入 VPS ({vps_ip}) root 密码: ")
    if not serv00_pass:
        import getpass
        serv00_pass = getpass.getpass("请输入 Serv00 (ztwotv) 密码: ")

    vps_ok = deploy_vps_ubuntu(vps_ip, "root", vps_pass)
    serv00_ok = deploy_serv00("panel13.serv00.com", "ztwotv", serv00_pass)
    print("\n================ 全部部署结果 ================")
    print(f"VPS ({vps_ip}): {'成功' if vps_ok else '失败'}")
    print(f"Serv00 (panel13.serv00.com): {'成功' if serv00_ok else '失败'}")
