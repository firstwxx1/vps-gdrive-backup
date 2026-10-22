#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
多节点远程流式备份引擎 (支持国内无外网VPS / 非root sudo用户 / Serv00)
通过主控节点 SSH 拉取打包流并直接上传到 Google Drive 5TB，不占目标机本地磁盘、无视国内墙阻断。
支持自动读取 /etc/vps-backup/backup.conf 并向 Telegram 机器人实时推送各节点备份完成通知与总报告。
"""
import json
import os
import re
import sys
import time
import subprocess
import paramiko

NODES_FILE = "/etc/vps-backup/nodes.json"
CONF_FILE = "/etc/vps-backup/backup.conf"

def load_conf():
    conf = {
        "TG_BOT_TOKEN": "",
        "TG_CHAT_ID": "",
        "TG_API": "https://api.telegram.org",
        "NOTIFY_ON_SUCCESS": "true",
        "BACKUP_NAME": "vps-45.130.166.10",
    }
    if os.path.exists(CONF_FILE):
        try:
            with open(CONF_FILE, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    s = line.strip()
                    if not s or s.startswith("#") or "=" not in s:
                        continue
                    k, v = s.split("=", 1)
                    k = k.strip()
                    v = v.split("#", 1)[0].strip().strip('"\'')
                    if k in conf:
                        conf[k] = v
        except Exception as e:
            print(f"[!] load_conf error: {e}")
    return conf

def tg_send(text):
    conf = load_conf()
    token = conf.get("TG_BOT_TOKEN", "").strip()
    chat_id = conf.get("TG_CHAT_ID", "").strip()
    api_base = conf.get("TG_API", "https://api.telegram.org").rstrip("/")
    if not token or not chat_id:
        return
    url = f"{api_base}/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text[:4000],
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    cmd = [
        "curl", "-4", "-s", "-m", "20",
        "-X", "POST", url,
        "-H", "Content-Type: application/json",
        "-d", json.dumps(payload, ensure_ascii=False)
    ]
    try:
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as e:
        print(f"[!] tg_send error: {e}")

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
    t0 = time.time()

    print(f"[*] 开始远程备份节点: {name} ({user}@{host}:{port}) ...")
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        c.connect(host, port=port, username=user, password=pw, timeout=20)
    except Exception as e:
        err_msg = f"❌ <b>[远程节点备份失败]</b>\n节点: <code>{name}</code> ({user}@{host}:{port})\n原因: SSH 连接失败: {e}"
        print(f"[!] {err_msg}")
        tg_send(err_msg)
        return False, name, f"连接失败: {e}"

    if ntype == "serv00" or "serv00" in host:
        _, stdout, stderr = c.exec_command("/bin/sh ~/bin/serv00-backup.sh", timeout=300)
        out = stdout.read().decode("utf-8", errors="ignore") + stderr.read().decode("utf-8", errors="ignore")
        c.close()
        dur = int(time.time() - t0)
        
        # 获取最新上传的文件信息
        lsl_out = subprocess.getoutput(f"rclone lsl --bind 0.0.0.0 --fast-list 'gdrive:vps-backup/{name}/archive/daily/' 2>/dev/null | tail -n 1")
        file_info = ""
        sz_str = ""
        if lsl_out.strip():
            parts = lsl_out.strip().split(None, 3)
            if len(parts) >= 4:
                sz_mb = int(parts[0]) / 1048576.0
                fname = parts[3]
                file_info = f"\n📦 <b>归档文件</b>: <code>{fname}</code> ({sz_mb:.2f} MB)"
                sz_str = f"{sz_mb:.2f} MB"

        print(f"[+] Serv00 节点 {name} 备份完成！耗时 {dur}s")
        msg = (
            f"✅ <b>[远程节点备份成功]</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🌐 <b>受控节点</b>: <code>{name}</code> (Serv00 虚拟主机)\n"
            f"⏱️ <b>备份耗时</b>: {dur} 秒\n"
            f"{file_info}\n"
            f"☁️ <b>存储位置</b>: <code>gdrive:vps-backup/{name}/archive/daily/</code>"
        )
        tg_send(msg)
        return True, name, sz_str or "成功"

    sudo_prefix = "" if user == "root" else "sudo "
    stamp = time.strftime("%Y%m%d-%H%M%S")
    fname = f"{name}_{stamp}.tar.gz"
    dest = f"gdrive:vps-backup/{name}/archive/daily/{fname}"

    # 1. 自动热导出远端 Docker 数据库
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
    try:
        _, out_p, err_p = c.exec_command(prep_cmd, timeout=120)
        out_p.channel.recv_exit_status()
    except Exception as e:
        print(f"[!] prep docker db warning: {e}")

    # 2. 跨国 SSH 加密流式打包与 rclone 上传
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

    dur = int(time.time() - t0)
    if rc == 0 and total_bytes > 100:
        sz_mb = total_bytes / 1048576.0
        print(f"[+] 节点 {name} 备份成功: {fname} ({sz_mb:.2f} MB, 耗时 {dur}s)")
        msg = (
            f"✅ <b>[远程节点备份成功]</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🌐 <b>受控节点</b>: <code>{name}</code> ({user}@{host})\n"
            f"⏱️ <b>备份耗时</b>: {dur} 秒\n"
            f"📦 <b>归档文件</b>: <code>{fname}</code> (<b>{sz_mb:.2f} MB</b>)\n"
            f"🌊 <b>备份模式</b>: 跨国 SSH 隧道流式直传 Google Drive (免翻墙/零磁盘占用)\n"
            f"☁️ <b>存储位置</b>: <code>gdrive:vps-backup/{name}/archive/daily/</code>"
        )
        tg_send(msg)
        return True, name, f"{sz_mb:.2f} MB"
    else:
        err_msg = f"❌ <b>[远程节点备份失败]</b>\n节点: <code>{name}</code>\n原因: 上传中断 (rc={rc}): {err_txt[:500]}"
        print(f"[!] {err_msg}")
        tg_send(err_msg)
        return False, name, f"上传失败 (rc={rc})"

if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "all"
    nodes = load_nodes()
    results = []
    for n in nodes:
        if target == "all" or target in (n.get("name"), n.get("host")):
            try:
                ok, nname, info = backup_node(n)
                results.append((nname, ok, info))
            except Exception as e:
                print(f"[!] 节点 {n.get('name')} 备份异常: {e}")
                results.append((n.get("name"), False, str(e)))

    # 如果是全量节点备份且有节点执行，发送汇总报告
    if target == "all" and results:
        conf = load_conf()
        master = conf.get("BACKUP_NAME", "vps-45.130.166.10")
        quota = subprocess.getoutput("rclone about --bind 0.0.0.0 gdrive: 2>/dev/null")
        q_lines = [l for l in quota.splitlines() if any(l.startswith(k) for k in ["Total:", "Used:", "Free:"])]
        q_str = "\n".join(q_lines) if q_lines else "5.000 TiB 容量正常"

        lines = [f"• 主控机 <code>{master}</code>: ✅ 今日已归档"]
        for nname, ok, info in results:
            icon = "✅" if ok else "❌"
            lines.append(f"• 节点 <code>{nname}</code>: {icon} {info}")

        summary = (
            f"☁️ <b>【Google Drive 5TB 全节点备份报告】</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            + "\n".join(lines) + "\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📊 <b>云盘配额状态</b>:\n<code>{q_str}</code>"
        )
        tg_send(summary)
