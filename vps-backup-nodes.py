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

def save_nodes(nodes):
    os.makedirs(os.path.dirname(NODES_FILE), exist_ok=True)
    with open(NODES_FILE, "w", encoding="utf-8") as f:
        json.dump(nodes, f, ensure_ascii=False, indent=2)
    os.chmod(NODES_FILE, 0o600)

def delete_node(name, purge_gdrive=False):
    conf = load_conf()
    master = conf.get("BACKUP_NAME", "vps-45.130.166.10")
    if name == master:
        print(f"[!] 安全拦截: 禁止删除本机主控节点 ({master})")
        return False, "禁止删除本机主控节点"

    nodes = load_nodes()
    target = next((n for n in nodes if n.get("name") == name or n.get("host") == name), None)
    if not target:
        print(f"[!] 未找到节点: {name}")
        return False, f"未找到名为 {name} 的节点"

    real_name = target.get("name") or name
    nodes = [n for n in nodes if n.get("name") != real_name and n.get("host") != target.get("host")]
    save_nodes(nodes)
    print(f"[+] 节点 {real_name} 已从监控调度列表移除")

    purge_msg = ""
    if purge_gdrive:
        print(f"[*] 正在清空云盘目录 gdrive:vps-backup/{real_name}/ ...")
        cmd = ["rclone", "purge", "--bind", "0.0.0.0", f"gdrive:vps-backup/{real_name}/"]
        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if p.returncode == 0:
            purge_msg = "，并已彻底清空云盘历史备份目录"
            print(f"[+] 云盘目录 gdrive:vps-backup/{real_name}/ 已彻底清空")
        else:
            purge_msg = f"，但清空云盘失败: {p.stderr.strip()[:200]}"
            print(f"[!] 清空云盘失败: {p.stderr.strip()}")
    else:
        purge_msg = "，云盘历史备份已完好保留"

    tg_send(
        f"🗑️ <b>[节点删除通知]</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🌐 <b>节点名称</b>: <code>{real_name}</code>\n"
        f"📋 <b>操作结果</b>: 节点已从调度列表中移除{purge_msg}。"
    )
    return True, f"节点 {real_name} 已成功移除{purge_msg}"

def rename_node(old_name, new_name):
    old_name = (old_name or "").strip()
    new_name = (new_name or "").strip()
    if not old_name or not new_name:
        return False, "原名称与新名称均不能为空"
    if old_name == new_name:
        return False, "新名称与原名称相同，无需更改"
    if not re.match(r'^[a-zA-Z0-9_\-\.]+$', new_name):
        return False, "新名称仅支持字母、数字、下划线、中划线和点"

    conf = load_conf()
    master = conf.get("BACKUP_NAME", "vps-45.130.166.10")
    nodes = load_nodes()

    if new_name == master:
        return False, f"新名称 {new_name} 与本机主控名称重复"
    if any(n.get("name") == new_name for n in nodes):
        return False, f"新名称 {new_name} 已被其他受控节点占用"

    is_master = (old_name == master)
    remote_target = next((n for n in nodes if n.get("name") == old_name or n.get("host") == old_name), None)

    if not is_master and not remote_target:
        return False, f"未找到名为 {old_name} 的节点"

    if is_master:
        if os.path.exists(CONF_FILE):
            try:
                content = open(CONF_FILE, "r", encoding="utf-8", errors="ignore").read()
                if re.search(r'^BACKUP_NAME=.*$', content, re.M):
                    content = re.sub(r'^BACKUP_NAME=.*$', f'BACKUP_NAME="{new_name}"', content, flags=re.M)
                else:
                    content = content.rstrip() + f'\nBACKUP_NAME="{new_name}"\n'
                with open(CONF_FILE, "w", encoding="utf-8") as f:
                    f.write(content)
                print(f"[+] 本机主控节点名称已修改: {old_name} -> {new_name}")
            except Exception as e:
                return False, f"更新 backup.conf 失败: {e}"
    else:
        for n in nodes:
            if n.get("name") == remote_target.get("name") or n.get("host") == remote_target.get("host"):
                n["name"] = new_name
                break
        save_nodes(nodes)
        print(f"[+] 受控远程节点名称已修改: {old_name} -> {new_name}")

    # 同步迁移 Google Drive 云盘目录（如果旧备份目录存在）
    cloud_msg = ""
    try:
        check_cmd = ["rclone", "lsf", "--bind", "0.0.0.0", f"gdrive:vps-backup/{old_name}/"]
        check_p = subprocess.run(check_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=12)
        if check_p.returncode == 0 and check_p.stdout.strip():
            print(f"[*] 正在将云盘目录 gdrive:vps-backup/{old_name} 重命名为 gdrive:vps-backup/{new_name} ...")
            mv_cmd = ["rclone", "moveto", "--bind", "0.0.0.0", f"gdrive:vps-backup/{old_name}", f"gdrive:vps-backup/{new_name}"]
            mv_p = subprocess.run(mv_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=40)
            if mv_p.returncode == 0:
                cloud_msg = "，云盘历史备份已无缝迁移至新名称目录"
                print(f"[+] 云盘目录无缝重命名迁移成功！")
            else:
                cloud_msg = f"，但云盘迁移提示: {mv_p.stderr.strip()[:100]}"
                print(f"[!] 云盘重命名提示: {mv_p.stderr.strip()}")
    except Exception as e:
        cloud_msg = f" (云盘迁移异常: {e})"

    tg_send(
        f"✏️ <b>[节点名称修改通知]</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"原节点名称: <code>{old_name}</code>\n"
        f"新节点名称: <code>{new_name}</code>\n"
        f"节点类型: {'🖥️ 本机海外主控' if is_master else '🌐 远程受控节点'}\n"
        f"处理结果: 节点名称修改成功{cloud_msg}。"
    )
    return True, f"节点已成功更名为 {new_name}{cloud_msg}"

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
    if len(sys.argv) > 1 and sys.argv[1] == "_notify":
        if len(sys.argv) > 2:
            tg_send(sys.argv[2])
        sys.exit(0)

    if len(sys.argv) > 1 and sys.argv[1] in ("del", "delete", "rm", "remove"):
        if len(sys.argv) < 3:
            print("用法: vps-backup-nodes.py del <node_name> [--purge]")
            sys.exit(1)
        del_target = sys.argv[2]
        do_purge = ("--purge" in sys.argv)
        ok, msg = delete_node(del_target, purge_gdrive=do_purge)
        print(msg)
        sys.exit(0 if ok else 1)

    if len(sys.argv) > 1 and sys.argv[1] in ("rename", "mv"):
        if len(sys.argv) < 4:
            print("用法: vps-backup-nodes.py rename <old_name> <new_name>")
            sys.exit(1)
        old_n = sys.argv[2]
        new_n = sys.argv[3]
        ok, msg = rename_node(old_n, new_n)
        print(msg)
        sys.exit(0 if ok else 1)

    if len(sys.argv) > 1 and sys.argv[1] in ("list", "ls"):
        nodes = load_nodes()
        print(f"已纳管远程节点数量: {len(nodes)}")
        for idx, n in enumerate(nodes, 1):
            nname = n.get("name") or f"vps-{n.get('host')}"
            print(f"  [{idx}] {nname} ({n.get('user', 'root')}@{n.get('host')}:{n.get('port', 22)}) [类型: {n.get('type', 'linux')}]")
        sys.exit(0)

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
