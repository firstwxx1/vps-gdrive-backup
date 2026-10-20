#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
多节点远程流式备份引擎 (支持国内无外网VPS / 非root sudo用户 / Serv00)
通过主控节点 SSH 拉取打包流并直接上传到 Google Drive 5TB，不占目标机本地磁盘、无视国内墙阻断。
"""
import json
import os
import sys
import time
import subprocess
import paramiko

NODES_FILE = "/etc/vps-backup/nodes.json"

def load_nodes():
    if os.path.exists(NODES_FILE):
        with open(NODES_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []

def backup_node(node):
    name = node.get("name") or f"vps-{node.get('host')}"
    host = node.get("host")
    port = int(node.get("port", 22))
    user = node.get("user", "root")
    pw = node.get("password") or node.get("pass") or ""
    ntype = node.get("type", "linux")

    print(f"[*] 开始远程备份节点: {name} ({user}@{host}:{port}) ...")
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(host, port=port, username=user, password=pw, timeout=20)

    if ntype == "serv00" or "serv00" in host:
        _, stdout, stderr = c.exec_command("/bin/sh ~/bin/serv00-backup.sh", timeout=300)
        out = stdout.read().decode("utf-8", errors="ignore") + stderr.read().decode("utf-8", errors="ignore")
        c.close()
        print(f"[+] Serv00 节点 {name} 备份完成！{out}")
        return True

    sudo_prefix = "" if user == "root" else "sudo "
    stamp = time.strftime("%Y%m%d-%H%M%S")
    fname = f"{name}_{stamp}.tar.gz"
    dest = f"gdrive:vps-backup/{name}/archive/daily/{fname}"

    prep_cmd = f"""{sudo_prefix}bash -c '
    rm -rf /tmp/_vps_db_dump && mkdir -p /tmp/_vps_db_dump
    if command -v docker >/dev/null 2>&1; then
        for cid in $(docker ps --format "{{{{.Names}}}}|{{{{.Image}}}}"); do
            cname="${{cid%%|*}}"
            cimg="${{cid#*|}}"
            case "$cimg" in
                *postgres*)
                    docker exec "$cname" sh -c "pg_dumpall -U \\"\\${{POSTGRES_USER:-postgres}}\\"" 2>/dev/null | gzip -c > "/tmp/_vps_db_dump/pg-${{cname}}.sql.gz" || true
                    ;;
                *mysql*|*mariadb*)
                    docker exec "$cname" sh -c "p=\\"\\${{MYSQL_ROOT_PASSWORD:-\\$MARIADB_ROOT_PASSWORD}}\\"; d=\\$(command -v mariadb-dump || command -v mysqldump); \\"\\$d\\" -uroot -p\\"\\$p\\" --all-databases --single-transaction --quick" 2>/dev/null | gzip -c > "/tmp/_vps_db_dump/mysql-${{cname}}.sql.gz" || true
                    ;;
            esac
        done
    fi
    '"""
    _, out_p, err_p = c.exec_command(prep_cmd, timeout=120)
    out_p.channel.recv_exit_status()

    tar_cmd = (
        f"{sudo_prefix}tar -czf - --ignore-failed-read "
        "--exclude='*.log' --exclude='*.tmp' --exclude='node_modules' --exclude='.cache' "
        "--exclude='__pycache__' --exclude='.wine*' --exclude='.local' --exclude='.npm*' "
        "--exclude='.openclaw' --exclude='.mt5' --exclude='go' --exclude='containerd' "
        "--exclude='node-v*' --exclude='docker' --exclude='*.tar.zst' --exclude='*.tar.gz' "
        "--exclude='*.exe' --exclude='*.xwd' --exclude='.venv' --exclude='venv' "
        "-C / etc root home opt /tmp/_vps_db_dump 2>/dev/null"
    )
    print(f"[*] 正在通过 SSH 加密流式拉取 {name} 数据并实时上传至 {dest} ...")
    transport = c.get_transport()
    chan = transport.open_session()
    chan.exec_command(tar_cmd)

    rclone_proc = subprocess.Popen(
        ["rclone", "rcat", "--bind", "0.0.0.0", "--tpslimit", "4", "--drive-chunk-size", "64M", dest],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    total_bytes = 0
    while True:
        chunk = chan.recv(65536)
        if not chunk:
            break
        rclone_proc.stdin.write(chunk)
        total_bytes += len(chunk)

    rclone_proc.stdin.close()
    rc = rclone_proc.wait()
    err_txt = rclone_proc.stderr.read().decode("utf-8", errors="ignore")

    c.exec_command(f"{sudo_prefix}rm -rf /tmp/_vps_db_dump")
    c.close()

    if rc == 0 and total_bytes > 100:
        sz_mb = total_bytes / 1048576.0
        print(f"[+] 节点 {name} 备份成功: {fname} ({sz_mb:.2f} MB)")
        return True
    else:
        print(f"[!] 节点 {name} 上传失败 (rc={rc}): {err_txt}")
        return False

if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "all"
    nodes = load_nodes()
    for n in nodes:
        if target == "all" or target in (n.get("name"), n.get("host")):
            try:
                backup_node(n)
            except Exception as e:
                print(f"[!] 节点 {n.get('name')} 备份异常: {e}")
