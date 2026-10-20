#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Google Drive 5TB VPS 备份与全能运维 - Telegram 终极控制面板机器人
功能:
  1. 左下角原生命令菜单 (setMyCommands) + 底部常驻快捷键盘 (ReplyKeyboardMarkup)
  2. 备份与恢复中心: 全量/归档/增量备份、Serv00远程备份、云盘文件浏览/一键恢复/删除、清空云盘回收站
  3. 数据库中心: 一键热导出 MySQL/PostgreSQL 容器数据库并直接发送文件到 Telegram 聊天窗口 & 上传云盘、动态勾选数据库容器
  4. 多节点与部署中心: 查看所有节点、在 TG 对话框输入 IP/密码直接一键 SSH 部署新 VPS、批量检测与触发所有节点备份
  5. 在线配置中心: 在 TG 内直接开关流式上传、开关成功通知、增删备份目录、修改每日定时备份时间、修改保留天数、设置加密密码
  6. Docker 容器管理: 查看所有容器状态、在 TG 内一键重启/启动/停止容器、查看容器日志与资源占用
  7. 服务器监控与 Web 终端: 系统负载/内存/磁盘/流量监控、大目录分析、Top进程、一键清理垃圾、直接发送 Linux 命令当终端用
"""

import os
import re
import sys
import time
import json
import shlex
import subprocess
import threading

CONF_FILE = "/etc/vps-backup/backup.conf"
NODES_FILE = "/etc/vps-backup/nodes.json"
LOG_FILE = "/var/log/vps-backup.log"
CRON_FILE = "/etc/cron.d/vps-backup"


def parse_conf():
    """读取 backup.conf 配置（包括普通变量与数组）"""
    conf = {
        "RCLONE_REMOTE": "gdrive",
        "REMOTE_BASE": "vps-backup",
        "BACKUP_NAME": os.uname().nodename,
        "STREAM_UPLOAD": "true",
        "COMPRESSION": "auto",
        "ENCRYPT_PASSWORD": "",
        "KEEP_DAILY_DAYS": "7",
        "KEEP_WEEKLY_DAYS": "28",
        "KEEP_MONTHLY_DAYS": "180",
        "ARCHIVE_ENABLED": "true",
        "SYNC_ENABLED": "false",
        "NOTIFY_ON_SUCCESS": "false",
        "TG_BOT_TOKEN": "",
        "TG_CHAT_ID": "",
        "TG_API": "https://api.telegram.org",
        "ARCHIVE_PATHS": ["/etc", "/root", "/opt"],
        "SYNC_PATHS": [],
        "DOCKER_MYSQL_CONTAINERS": [],
        "DOCKER_PG_CONTAINERS": [],
    }
    if not os.path.exists(CONF_FILE):
        return conf
    try:
        content = open(CONF_FILE, "r", encoding="utf-8", errors="ignore").read()
        for line in content.splitlines():
            s = line.strip()
            if not s or s.startswith("#") or "=" not in s or "(" in s:
                continue
            k, v = s.split("=", 1)
            k = k.strip()
            v = v.split("#", 1)[0].strip().strip('"\'')
            if k in conf and not isinstance(conf[k], list):
                conf[k] = v

        for arr_key in ["ARCHIVE_PATHS", "SYNC_PATHS", "DOCKER_MYSQL_CONTAINERS", "DOCKER_PG_CONTAINERS"]:
            m = re.search(rf'^{arr_key}=\((.*?)\)', content, re.M | re.S)
            if m:
                items = []
                for raw_line in m.group(1).splitlines():
                    part = raw_line.split("#", 1)[0].strip()
                    for tok in shlex.split(part):
                        if tok:
                            items.append(tok)
                conf[arr_key] = items
    except Exception as e:
        print(f"[!] parse_conf error: {e}")
    return conf


def set_conf_scalar(key, val):
    """修改或追加 backup.conf 中的普通键值"""
    lines = []
    found = False
    if os.path.exists(CONF_FILE):
        with open(CONF_FILE, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                if re.match(rf'^\s*{re.escape(key)}=', line):
                    if str(val).isdigit() and key.startswith("KEEP_"):
                        lines.append(f'{key}={val}\n')
                    else:
                        lines.append(f'{key}="{val}"\n')
                    found = True
                else:
                    lines.append(line)
    if not found:
        if str(val).isdigit() and key.startswith("KEEP_"):
            lines.append(f'\n{key}={val}\n')
        else:
            lines.append(f'\n{key}="{val}"\n')
    with open(CONF_FILE, "w", encoding="utf-8") as f:
        f.writelines(lines)


def set_conf_array(key, items):
    """修改或追加 backup.conf 中的数组键值"""
    block = f"{key}=(\n" + "".join(f"    {x}\n" for x in items) + ")"
    if os.path.exists(CONF_FILE):
        content = open(CONF_FILE, "r", encoding="utf-8", errors="ignore").read()
        if re.search(rf'^{key}=\(.*?\)', content, re.M | re.S):
            content = re.sub(rf'^{key}=\(.*?\)', block, content, flags=re.M | re.S)
        else:
            content = content.rstrip() + "\n\n" + block + "\n"
    else:
        content = block + "\n"
    with open(CONF_FILE, "w", encoding="utf-8") as f:
        f.write(content)


def get_cron_schedule():
    if os.path.exists(CRON_FILE):
        try:
            for line in open(CRON_FILE, "r", encoding="utf-8", errors="ignore"):
                line = line.strip()
                if line and not line.startswith("#") and "vps-backup" in line:
                    parts = line.split()
                    if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
                        return f"{int(parts[1]):02d}:{int(parts[0]):02d}"
        except:
            pass
    return "03:17"


def set_cron_schedule(hour, minute):
    content = (
        "# vps-backup 每日自动备份\n"
        "SHELL=/bin/bash\n"
        "PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin\n"
        f"{int(minute)} {int(hour)} * * * root /usr/local/bin/vps-backup > /dev/null 2>&1\n"
    )
    with open(CRON_FILE, "w", encoding="utf-8") as f:
        f.write(content)
    os.chmod(CRON_FILE, 0o644)


def load_nodes():
    if os.path.exists(NODES_FILE):
        try:
            return json.loads(open(NODES_FILE, "r", encoding="utf-8").read())
        except:
            pass
    return []


def save_nodes(nodes):
    os.makedirs(os.path.dirname(NODES_FILE), exist_ok=True)
    with open(NODES_FILE, "w", encoding="utf-8") as f:
        json.dump(nodes, f, ensure_ascii=False, indent=2)
    os.chmod(NODES_FILE, 0o600)


def html_escape(s):
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


class TelegramBot:
    def __init__(self):
        self.conf = parse_conf()
        self.token = self.conf.get("TG_BOT_TOKEN", "").strip()
        self.admin_id = self.conf.get("TG_CHAT_ID", "").strip()
        self.api_base = self.conf.get("TG_API", "https://api.telegram.org").rstrip("/")
        self.is_running_backup = False
        self.user_state = {}        # chat_id -> {"mode": ..., "meta": ...}
        self.file_cache = {}        # short_id -> full remote relative path
        self.container_cache = {}   # short_id -> container name
        self.commands_registered = False
        self.last_token = ""

    def reload(self):
        self.conf = parse_conf()
        self.token = self.conf.get("TG_BOT_TOKEN", "").strip()
        self.admin_id = self.conf.get("TG_CHAT_ID", "").strip()
        self.api_base = self.conf.get("TG_API", "https://api.telegram.org").rstrip("/")

    def api_call(self, method, data=None, timeout=30):
        if not self.token:
            return None
        url = f"{self.api_base}/bot{self.token}/{method}"
        cmd = ["curl", "-4", "-s", "-m", str(timeout), url]
        if data is not None:
            cmd.extend(["-H", "Content-Type: application/json", "-d", json.dumps(data)])
        try:
            out = subprocess.check_output(cmd, text=True, errors="ignore")
            return json.loads(out or "{}")
        except Exception:
            return None

    def send_document(self, chat_id, filepath, caption=""):
        if not self.token or not os.path.exists(filepath):
            return None
        url = f"{self.api_base}/bot{self.token}/sendDocument"
        cmd = [
            "curl", "-4", "-s", "-m", "120",
            "-F", f"chat_id={chat_id}",
            "-F", f"document=@{filepath}",
        ]
        if caption:
            cmd.extend(["-F", f"caption={caption[:900]}"])
        try:
            out = subprocess.check_output(cmd, text=True, errors="ignore")
            return json.loads(out or "{}")
        except Exception:
            return None

    def register_commands(self):
        commands = [
            {"command": "menu", "description": "🏠 打开全功能主控面板与底部菜单"},
            {"command": "backup", "description": "🚀 备份与恢复中心 (全量/增量/Serv00)"},
            {"command": "files", "description": "📂 云盘文件浏览、一键恢复与删除"},
            {"command": "db", "description": "🗄️ 数据库热备管理 (导出并直发TG)"},
            {"command": "nodes", "description": "🌐 多节点管理与一键部署新 VPS"},
            {"command": "config", "description": "⚙️ 备份目录、保留天数与定时策略设置"},
            {"command": "docker", "description": "🐳 Docker 容器状态、重启与日志管理"},
            {"command": "status", "description": "🖥️ 服务器负载、磁盘、大目录与进程监控"},
            {"command": "sh", "description": "💻 执行远程 Linux 命令 (例: /sh df -h)"},
            {"command": "log", "description": "📜 查看近期备份与运行日志"},
        ]
        res = self.api_call("setMyCommands", {"commands": commands})
        if res and res.get("ok"):
            self.api_call("setChatMenuButton", {"menu_button": {"type": "commands"}})
            self.commands_registered = True
            self.last_token = self.token
            print("[+] Telegram 左下角命令菜单注册成功！")
            if self.admin_id:
                self.send_msg(self.admin_id, "✅ <b>已为你收起底部大键盘</b>（你可随时通过消息内按钮或左下角 <b>Menu</b> 按钮操作）", reply_markup={"remove_keyboard": True})
                self.show_home(self.admin_id, with_reply_kb=False)

    def get_reply_keyboard(self):
        return {
            "keyboard": [
                [{"text": "🚀 备份与恢复"}, {"text": "📂 云盘文件管理"}, {"text": "🌐 节点与部署"}],
                [{"text": "🗄️ 数据库热备"}, {"text": "🐳 Docker 管理"}, {"text": "⚙️ 策略与配置"}],
                [{"text": "🖥️ 服务器状态"}, {"text": "💻 快捷运维/终端"}, {"text": "🔽 收起底部键盘"}],
            ],
            "resize_keyboard": True,
            "is_persistent": False,
            "one_time_keyboard": True,
        }

    def send_msg(self, chat_id, text, reply_markup=None, parse_mode="HTML"):
        data = {
            "chat_id": chat_id,
            "text": text[:4000],
            "parse_mode": parse_mode,
            "disable_web_page_preview": True,
        }
        if reply_markup:
            data["reply_markup"] = reply_markup
        return self.api_call("sendMessage", data)

    def edit_msg(self, chat_id, message_id, text, reply_markup=None, parse_mode="HTML"):
        data = {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": text[:4000],
            "parse_mode": parse_mode,
            "disable_web_page_preview": True,
        }
        if reply_markup:
            data["reply_markup"] = reply_markup
        res = self.api_call("editMessageText", data)
        if not res or not res.get("ok"):
            if res and "message is not modified" in str(res.get("description", "")):
                return res
            return self.send_msg(chat_id, text, reply_markup=reply_markup, parse_mode=parse_mode)
        return res

    def answer_cb(self, cq_id, text=None, alert=False):
        data = {"callback_query_id": cq_id}
        if text:
            data["text"] = text[:190]
            data["show_alert"] = alert
        return self.api_call("answerCallbackQuery", data)

    # ==================== 主面板与导航菜单 ====================
    def get_home_kb(self):
        return {
            "inline_keyboard": [
                [
                    {"text": "🚀 备份与恢复中心", "callback_data": "nav:backup"},
                    {"text": "📂 云盘文件与空间", "callback_data": "nav:files"},
                ],
                [
                    {"text": "🗄️ 数据库热备直发", "callback_data": "nav:db"},
                    {"text": "🌐 多节点与新机部署", "callback_data": "nav:nodes"},
                ],
                [
                    {"text": "⚙️ 策略与配置修改", "callback_data": "nav:config"},
                    {"text": "🐳 Docker 容器管理", "callback_data": "nav:docker"},
                ],
                [
                    {"text": "🖥️ 服务器监控看板", "callback_data": "nav:status"},
                    {"text": "💻 快捷运维与终端", "callback_data": "nav:ops"},
                ],
                [
                    {"text": "⚡ 立即一键全量备份", "callback_data": "act:bk_run"},
                    {"text": "🔄 刷新主控台", "callback_data": "nav:home"},
                ],
                [
                    {"text": "⌨️ 呼出底部按键", "callback_data": "act:kb_show"},
                    {"text": "🔽 收起底部按键", "callback_data": "act:kb_hide"},
                ],
            ]
        }

    def render_home_text(self):
        self.reload()
        host = os.uname().nodename
        bname = self.conf.get("BACKUP_NAME", host)
        cron_time = get_cron_schedule()
        stream = "开启 (免占本地磁盘)" if self.conf.get("STREAM_UPLOAD") == "true" else "关闭 (本地打包)"
        notify = "成功/失败均通知" if self.conf.get("NOTIFY_ON_SUCCESS") == "true" else "仅失败报警"
        enc = "🔒 已开启 AES-256" if self.conf.get("ENCRYPT_PASSWORD") else "🔓 未加密"
        db_cnt = len(self.conf.get("DOCKER_MYSQL_CONTAINERS", [])) + len(self.conf.get("DOCKER_PG_CONTAINERS", []))
        return (
            f"<b>☁️ Google Drive 5TB 全能备份与运维中心</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📍 <b>当前主控节点</b>: <code>{bname}</code> ({host})\n"
            f"⏰ <b>每日定时任务</b>: <code>每天 {cron_time} (UTC)</code>\n"
            f"🌊 <b>上传模式</b>: <code>{stream}</code>\n"
            f"🗄️ <b>热备数据库数</b>: <code>{db_cnt} 个容器实例</code>\n"
            f"🔐 <b>加密状态</b>: <code>{enc}</code>\n"
            f"🔔 <b>通知策略</b>: <code>{notify}</code>\n"
            f"📅 <b>保留周期</b>: <code>日{self.conf.get('KEEP_DAILY_DAYS')}天 / 周{self.conf.get('KEEP_WEEKLY_DAYS')}天 / 月{self.conf.get('KEEP_MONTHLY_DAYS')}天</code>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"💡 <i>你可使用下方内联菜单、底部常驻键盘或左下角 Menu 菜单进行全方位控制：</i>"
        )

    def show_home(self, chat_id, msg_id=None, with_reply_kb=False):
        self.user_state.pop(str(chat_id), None)
        text = self.render_home_text()
        if with_reply_kb:
            self.send_msg(chat_id, "⌨️ <b>已激活底部常驻快捷键盘与左下角命令菜单！</b>", reply_markup=self.get_reply_keyboard())
        if msg_id:
            self.edit_msg(chat_id, msg_id, text, reply_markup=self.get_home_kb())
        else:
            self.send_msg(chat_id, text, reply_markup=self.get_home_kb())

    # ==================== 1. 备份与恢复中心 ====================
    def show_backup_menu(self, chat_id, msg_id=None):
        text = (
            "<b>🚀 备份与恢复控制中心</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "• <b>完整备份 (run)</b>: 按配置执行数据库导出 + 归档/同步\n"
            "• <b>仅归档 (archive)</b>: 强制执行数据库导出 + 打包压缩上传\n"
            "• <b>仅同步 (sync)</b>: 强制执行目录增量镜像同步\n"
            "• <b>Serv00 备份</b>: 远程触发 Serv00 虚拟主机立即打包上传云盘\n"
            "• <b>一键恢复向导</b>: 选择云盘上的备份包自动解压到 <code>/root/vps-restore</code>"
        )
        kb = {
            "inline_keyboard": [
                [
                    {"text": "⚡ 立即完整备份 (run)", "callback_data": "act:bk_run"},
                    {"text": "📦 仅归档备份 (archive)", "callback_data": "act:bk_archive"},
                ],
                [
                    {"text": "🔄 仅增量同步 (sync)", "callback_data": "act:bk_sync"},
                    {"text": "📡 立即备份 Serv00", "callback_data": "act:bk_serv00"},
                ],
                [
                    {"text": "📥 一键恢复向导", "callback_data": "act:restore_list"},
                    {"text": "🩺 备份系统自检", "callback_data": "act:bk_test"},
                ],
                [
                    {"text": "📜 查看备份日志", "callback_data": "act:log_view"},
                    {"text": "🔙 返回主控台", "callback_data": "nav:home"},
                ],
            ]
        }
        if msg_id:
            self.edit_msg(chat_id, msg_id, text, reply_markup=kb)
        else:
            self.send_msg(chat_id, text, reply_markup=kb)

    def run_backup_task(self, chat_id, mode="run"):
        if self.is_running_backup:
            self.send_msg(chat_id, "⚠️ <b>当前已有备份任务正在后台运行中，请稍候查看结果！</b>")
            return

        def worker():
            self.is_running_backup = True
            t0 = time.time()
            try:
                self.send_msg(
                    chat_id,
                    f"⏳ <b>[备份已启动: {mode}]</b>\n正在后台导出数据库并流式打包上传至 5TB Google Drive，完成后将自动推送报告...",
                )
                p = subprocess.run(
                    ["/usr/local/bin/vps-backup", mode],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    errors="ignore",
                )
                dur = int(time.time() - t0)
                out = html_escape(p.stdout.strip()[-2500:])
                icon = "✅" if p.returncode == 0 else "❌"
                status = "成功" if p.returncode == 0 else f"失败 (exit {p.returncode})"
                self.send_msg(
                    chat_id,
                    f"{icon} <b>[备份任务{status}]</b> (耗时 {dur}s)\n━━━━━━━━━━━━━━━━━━━━━━\n<pre>{out}</pre>",
                    reply_markup=self.get_home_kb(),
                )
            except Exception as e:
                self.send_msg(chat_id, f"❌ 备份执行异常: <code>{html_escape(str(e))}</code>")
            finally:
                self.is_running_backup = False

        threading.Thread(target=worker, daemon=True).start()

    def run_serv00_backup(self, chat_id):
        def worker():
            self.send_msg(chat_id, "⏳ <b>正在远程连接 Serv00 并触发立即备份上传至 Google Drive...</b>")
            nodes = load_nodes()
            serv00 = next((n for n in nodes if "serv00" in n.get("host", "") or "serv00" in n.get("name", "")), None)
            if not serv00:
                self.send_msg(chat_id, "⚠️ 未找到已保存的 Serv00 节点信息，请在【🌐 节点与部署】中添加。")
                return
            try:
                import paramiko
                c = paramiko.SSHClient()
                c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                c.connect(
                    serv00["host"],
                    port=int(serv00.get("port", 22)),
                    username=serv00["user"],
                    password=serv00["password"],
                    timeout=15,
                )
                cmd = "/bin/sh ~/bin/serv00-backup.sh && ~/bin/rclone lsl gdrive:vps-backup/serv00-" + serv00["user"] + "/archive/daily/ | tail -n 5"
                _, stdout, stderr = c.exec_command(cmd, timeout=120)
                out = stdout.read().decode("utf-8", errors="ignore") + stderr.read().decode("utf-8", errors="ignore")
                c.close()
                self.send_msg(
                    chat_id,
                    f"✅ <b>[Serv00 备份完成]</b>\n━━━━━━━━━━━━━━━━━━━━━━\n<pre>{html_escape(out.strip()[-2000:])}</pre>",
                    reply_markup=self.get_home_kb(),
                )
            except Exception as e:
                self.send_msg(chat_id, f"❌ Serv00 远程备份失败: <code>{html_escape(str(e))}</code>")

        threading.Thread(target=worker, daemon=True).start()

    # ==================== 2. 云盘文件与空间管理 ====================
    def show_files_menu(self, chat_id, msg_id=None):
        self.reload()
        bname = self.conf.get("BACKUP_NAME", os.uname().nodename)
        text = (
            f"<b>📂 Google Drive 5TB 云盘文件与空间管理</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"当前节点目录: <code>gdrive:vps-backup/{bname}</code>\n"
            f"点击下方按钮浏览各周期归档文件（支持对单个文件<b>一键恢复</b>或<b>删除</b>）："
        )
        kb = {
            "inline_keyboard": [
                [
                    {"text": "📊 5TB 容量与节点占用统计", "callback_data": "act:quota_detail"},
                ],
                [
                    {"text": "📅 每日备份 (daily)", "callback_data": "flist:daily"},
                    {"text": "📆 每周备份 (weekly)", "callback_data": "flist:weekly"},
                ],
                [
                    {"text": "🗓️ 每月备份 (monthly)", "callback_data": "flist:monthly"},
                    {"text": "🌐 Serv00 备份文件", "callback_data": "flist:serv00"},
                ],
                [
                    {"text": "🧹 按策略清理过期备份", "callback_data": "act:prune_now"},
                    {"text": "🗑️ 清空云盘回收站释放空间", "callback_data": "act:empty_trash"},
                ],
                [
                    {"text": "🔙 返回主控台", "callback_data": "nav:home"},
                ],
            ]
        }
        if msg_id:
            self.edit_msg(chat_id, msg_id, text, reply_markup=kb)
        else:
            self.send_msg(chat_id, text, reply_markup=kb)

    def show_tier_files(self, chat_id, msg_id, tier):
        self.reload()
        remote = self.conf.get("RCLONE_REMOTE", "gdrive")
        base = self.conf.get("REMOTE_BASE", "vps-backup")
        bname = self.conf.get("BACKUP_NAME", os.uname().nodename)
        if tier == "serv00":
            rel_dir = "serv00-ztwotv/archive/daily"
        else:
            rel_dir = f"{bname}/archive/{tier}"

        full_remote = f"{remote}:{base}/{rel_dir}"
        out = subprocess.getoutput(f"rclone lsl --tpslimit 4 '{full_remote}' 2>/dev/null | sort -k2,3")
        lines = [ln.strip() for ln in out.splitlines() if ln.strip() and not ln.startswith("NOTICE")]

        self.file_cache.clear()
        kb_rows = []
        summary_lines = []
        for idx, ln in enumerate(lines[-10:], 1):
            parts = ln.split(None, 3)
            if len(parts) < 4:
                continue
            sz_mb = int(parts[0]) / 1048576.0
            dt = f"{parts[1]} {parts[2][:8]}"
            fname = parts[3]
            fid = f"f{idx}"
            self.file_cache[fid] = f"{rel_dir}/{fname}"
            summary_lines.append(f"{idx}. <code>{html_escape(fname)}</code>\n   📦 <b>{sz_mb:.2f} MB</b> | 🕒 {dt}")
            kb_rows.append([
                {"text": f"📥 恢复 #{idx}", "callback_data": f"fres:{fid}"},
                {"text": f"🗑️ 删除 #{idx}", "callback_data": f"fdel:{fid}"},
            ])

        kb_rows.append([
            {"text": "🔄 刷新列表", "callback_data": f"flist:{tier}"},
            {"text": "🔙 返回文件管理", "callback_data": "nav:files"},
        ])
        body = "\n".join(summary_lines) if summary_lines else "<i>（该目录下暂无备份文件）</i>"
        text = (
            f"<b>📂 云盘目录: {html_escape(rel_dir)}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"{body}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"💡 点击对应序号可<b>直接恢复到 /root/vps-restore</b> 或从云盘删除："
        )
        self.edit_msg(chat_id, msg_id, text, reply_markup={"inline_keyboard": kb_rows})

    def handle_file_restore(self, chat_id, fid):
        rel_path = self.file_cache.get(fid)
        if not rel_path:
            self.send_msg(chat_id, "⚠️ 文件缓存已过期，请重新打开列表后再点击。")
            return

        def worker():
            target_dir = f"/root/vps-restore/{int(time.time())}"
            self.send_msg(chat_id, f"⏳ <b>正在从云盘下载并恢复:</b>\n<code>{html_escape(rel_path)}</code>\n目标目录: <code>{target_dir}</code>")
            p = subprocess.run(
                ["/usr/local/bin/vps-backup", "restore", rel_path, target_dir],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                errors="ignore",
            )
            files_out = subprocess.getoutput(f"ls -la '{target_dir}' 2>/dev/null | head -n 20")
            icon = "✅" if p.returncode == 0 else "❌"
            self.send_msg(
                chat_id,
                f"{icon} <b>[恢复任务结束]</b>\n解压位置: <code>{target_dir}</code>\n\n<pre>{html_escape(p.stdout[-1200:])}\n{html_escape(files_out)}</pre>",
                reply_markup=self.get_home_kb(),
            )

        threading.Thread(target=worker, daemon=True).start()

    def handle_file_delete(self, chat_id, msg_id, fid):
        rel_path = self.file_cache.get(fid)
        if not rel_path:
            self.send_msg(chat_id, "⚠️ 文件缓存已过期，请重新刷新列表。")
            return
        remote = self.conf.get("RCLONE_REMOTE", "gdrive")
        base = self.conf.get("REMOTE_BASE", "vps-backup")
        full = f"{remote}:{base}/{rel_path}"
        subprocess.run(["rclone", "deletefile", "--drive-use-trash=false", full])
        self.send_msg(chat_id, f"🗑️ 已从云盘永久删除: <code>{html_escape(rel_path)}</code>")

    # ==================== 3. 数据库热备与直发中心 ====================
    def show_db_menu(self, chat_id, msg_id=None):
        self.reload()
        my_list = self.conf.get("DOCKER_MYSQL_CONTAINERS", [])
        pg_list = self.conf.get("DOCKER_PG_CONTAINERS", [])
        text = (
            f"<b>🗄️ 数据库热备与直发管理中心</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🐬 <b>MySQL/MariaDB 容器</b>: <code>{', '.join(my_list) if my_list else '未配置'}</code>\n"
            f"🐘 <b>PostgreSQL 容器</b>: <code>{', '.join(pg_list) if pg_list else '未配置'}</code>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"💡 你可以<b>一键单独热导出所有数据库</b>并直接将 <code>.sql.gz</code> 备份包发送到当前 Telegram 聊天窗口保存，同时归档至 Google Drive！"
        )
        kb = {
            "inline_keyboard": [
                [
                    {"text": "⚡ 立即导出全部数据库并发到 TG + 云盘", "callback_data": "act:db_dump_tg"},
                ],
                [
                    {"text": "☑️ 勾选/管理参与备份的数据库容器", "callback_data": "act:db_select"},
                ],
                [
                    {"text": "🔙 返回主控台", "callback_data": "nav:home"},
                ],
            ]
        }
        if msg_id:
            self.edit_msg(chat_id, msg_id, text, reply_markup=kb)
        else:
            self.send_msg(chat_id, text, reply_markup=kb)

    def dump_databases_to_tg(self, chat_id):
        def worker():
            self.reload()
            my_list = self.conf.get("DOCKER_MYSQL_CONTAINERS", [])
            pg_list = self.conf.get("DOCKER_PG_CONTAINERS", [])
            if not my_list and not pg_list:
                self.send_msg(chat_id, "⚠️ 当前未配置任何数据库容器，请先在数据库中心勾选容器。")
                return

            stamp = time.strftime("%Y%m%d-%H%M%S")
            tmp_dir = f"/var/tmp/tg-dbdump-{stamp}"
            os.makedirs(tmp_dir, exist_ok=True)
            self.send_msg(chat_id, "⏳ <b>正在热导出所有容器数据库...</b>")

            dumped_files = []
            for c in my_list:
                out_file = f"{tmp_dir}/mysql-{c}-{stamp}.sql.gz"
                cmd = (
                    f"docker exec {shlex.quote(c)} sh -c '"
                    'p="${MYSQL_ROOT_PASSWORD:-$MARIADB_ROOT_PASSWORD}"; '
                    'd=$(command -v mariadb-dump || command -v mysqldump); '
                    'exec "$d" -uroot -p"$p" --all-databases --single-transaction --quick --routines --triggers'
                    f"' 2>/dev/null | gzip -c > {shlex.quote(out_file)}"
                )
                subprocess.run(["bash", "-c", cmd])
                if os.path.exists(out_file) and os.path.getsize(out_file) > 50:
                    dumped_files.append((c, out_file))

            for c in pg_list:
                out_file = f"{tmp_dir}/pg-{c}-{stamp}.sql.gz"
                cmd = (
                    f"docker exec {shlex.quote(c)} sh -c '"
                    'exec pg_dumpall -U "${POSTGRES_USER:-postgres}"'
                    f"' 2>/dev/null | gzip -c > {shlex.quote(out_file)}"
                )
                subprocess.run(["bash", "-c", cmd])
                if os.path.exists(out_file) and os.path.getsize(out_file) > 50:
                    dumped_files.append((c, out_file))

            remote = self.conf.get("RCLONE_REMOTE", "gdrive")
            base = self.conf.get("REMOTE_BASE", "vps-backup")
            bname = self.conf.get("BACKUP_NAME", os.uname().nodename)
            remote_db_dir = f"{remote}:{base}/{bname}/databases/{stamp}"

            for cname, fpath in dumped_files:
                sz_kb = os.path.getsize(fpath) / 1024.0
                subprocess.run(["rclone", "copy", "--tpslimit", "4", fpath, remote_db_dir])
                if os.path.getsize(fpath) < 48 * 1024 * 1024:
                    self.send_document(chat_id, fpath, caption=f"🗄️ 数据库热备: {cname} ({sz_kb:.1f} KB)\n已同步至: {remote_db_dir}")

            subprocess.run(["rm", "-rf", tmp_dir])
            self.send_msg(
                chat_id,
                f"✅ <b>数据库导出完成！共成功导出 {len(dumped_files)} 个实例。</b>\n☁️ 云盘路径: <code>{remote_db_dir}</code>",
                reply_markup=self.get_home_kb(),
            )

        threading.Thread(target=worker, daemon=True).start()

    def show_db_selector(self, chat_id, msg_id):
        self.reload()
        my_set = set(self.conf.get("DOCKER_MYSQL_CONTAINERS", []))
        pg_set = set(self.conf.get("DOCKER_PG_CONTAINERS", []))
        out = subprocess.getoutput("docker ps --format '{{.Names}}|{{.Image}}'")
        kb_rows = []
        for idx, line in enumerate(out.splitlines(), 1):
            if "|" not in line:
                continue
            cname, img = line.split("|", 1)
            img_l = img.lower()
            if any(k in img_l or k in cname.lower() for k in ["mysql", "mariadb", "postgres", "db"]):
                is_pg = "postgres" in img_l
                active = (cname in pg_set) if is_pg else (cname in my_set)
                mark = "✅" if active else "⬜"
                db_type = "PG" if is_pg else "MySQL"
                cid = f"dbc{idx}"
                self.container_cache[cid] = (cname, "pg" if is_pg else "mysql")
                kb_rows.append([{"text": f"{mark} [{db_type}] {cname}", "callback_data": f"dbtoggle:{cid}"}])

        kb_rows.append([{"text": "🔙 返回数据库中心", "callback_data": "nav:db"}])
        self.edit_msg(
            chat_id,
            msg_id,
            "<b>☑️ 点击下方数据库容器即可开启/关闭每日自动热备份：</b>",
            reply_markup={"inline_keyboard": kb_rows},
        )

    def toggle_db_container(self, chat_id, msg_id, cid):
        info = self.container_cache.get(cid)
        if not info:
            return
        cname, db_type = info
        self.reload()
        key = "DOCKER_PG_CONTAINERS" if db_type == "pg" else "DOCKER_MYSQL_CONTAINERS"
        cur = list(self.conf.get(key, []))
        if cname in cur:
            cur.remove(cname)
        else:
            cur.append(cname)
        set_conf_array(key, cur)
        self.show_db_selector(chat_id, msg_id)

    # ==================== 4. 多节点管理与新机一键部署 ====================
    def show_nodes_menu(self, chat_id, msg_id=None):
        nodes = load_nodes()
        node_lines = []
        for idx, n in enumerate(nodes, 1):
            node_lines.append(f"{idx}. <b>{html_escape(n.get('name'))}</b> (<code>{html_escape(n.get('user'))}@{html_escape(n.get('host'))}:{n.get('port', 22)}</code>)")
        body = "\n".join(node_lines) if node_lines else "<i>暂未登记远程节点</i>"
        text = (
            f"<b>🌐 多服务器节点管理与一键部署</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"<b>已登记的受控节点 ({len(nodes)} 台)</b>:\n{body}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"💡 可直接点击<b>【➕ 部署新 VPS 节点】</b>，将本机的 5TB Google Drive 授权与自动备份脚本一键安装到任何新服务器上！"
        )
        kb = {
            "inline_keyboard": [
                [
                    {"text": "➕ 一键部署新 VPS 节点", "callback_data": "act:node_add_prompt"},
                    {"text": "☁️ 云盘上所有主机目录", "callback_data": "act:node_cloud_dirs"},
                ],
                [
                    {"text": "🛰️ 批量检测所有节点连通性", "callback_data": "act:node_ping_all"},
                    {"text": "⚡ 触发所有节点立即备份", "callback_data": "act:node_backup_all"},
                ],
                [
                    {"text": "🔙 返回主控台", "callback_data": "nav:home"},
                ],
            ]
        }
        if msg_id:
            self.edit_msg(chat_id, msg_id, text, reply_markup=kb)
        else:
            self.send_msg(chat_id, text, reply_markup=kb)

    def deploy_remote_vps(self, chat_id, host, port, user, password):
        def worker():
            self.send_msg(chat_id, f"🚀 <b>开始自动部署新节点:</b> <code>{user}@{host}:{port}</code> ...")
            try:
                import paramiko
                c = paramiko.SSHClient()
                c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                c.connect(host, port=int(port), username=user, password=password, timeout=15)

                remote_tmp = "/tmp/vps-backup-installer"
                c.exec_command(f"rm -rf {remote_tmp} && mkdir -p -m 700 {remote_tmp}")
                time.sleep(1)

                sftp = c.open_sftp()
                for local_f in ["/usr/local/bin/vps-backup", "/etc/vps-backup/backup.conf.example"]:
                    if os.path.exists(local_f):
                        sftp.put(local_f, f"{remote_tmp}/{os.path.basename(local_f)}")
                rc_conf = os.path.expanduser("~/.config/rclone/rclone.conf")
                if os.path.exists(rc_conf):
                    sftp.put(rc_conf, f"{remote_tmp}/rclone.conf")
                sftp.close()

                install_cmd = (
                    f"cd {remote_tmp} && "
                    "(command -v rclone >/dev/null || curl -fsSL https://rclone.org/install.sh | bash) && "
                    "install -m 755 vps-backup /usr/local/bin/vps-backup && "
                    "mkdir -p ~/.config/rclone && cp -f rclone.conf ~/.config/rclone/rclone.conf && chmod 600 ~/.config/rclone/rclone.conf && "
                    "mkdir -p /etc/vps-backup && cp -n backup.conf.example /etc/vps-backup/backup.conf && "
                    "sed -i 's/^STREAM_UPLOAD=.*/STREAM_UPLOAD=\"true\"/' /etc/vps-backup/backup.conf && "
                    "(crontab -l 2>/dev/null | grep -v vps-backup ; echo \"$((RANDOM % 60)) 3 * * * /usr/local/bin/vps-backup >/dev/null 2>&1\") | crontab - && "
                    "rm -rf " + remote_tmp + " && /usr/local/bin/vps-backup test"
                )
                _, stdout, stderr = c.exec_command(install_cmd, timeout=180)
                out = stdout.read().decode("utf-8", errors="ignore") + stderr.read().decode("utf-8", errors="ignore")
                c.close()

                # 保存到 nodes.json
                nodes = load_nodes()
                nodes = [n for n in nodes if n.get("host") != host]
                nodes.append({
                    "name": f"vps-{host}",
                    "host": host,
                    "port": int(port),
                    "user": user,
                    "password": password,
                    "type": "linux",
                })
                save_nodes(nodes)

                self.send_msg(
                    chat_id,
                    f"✅ <b>[新节点 {html_escape(host)} 部署成功]</b>\n已自动加入节点列表并设置每日凌晨自动备份！\n\n<pre>{html_escape(out[-1800:])}</pre>",
                    reply_markup=self.get_home_kb(),
                )
            except Exception as e:
                self.send_msg(chat_id, f"❌ 部署失败: <code>{html_escape(str(e))}</code>")

        threading.Thread(target=worker, daemon=True).start()

    # ==================== 5. 策略与配置中心 ====================
    def show_config_menu(self, chat_id, msg_id=None):
        self.reload()
        paths = self.conf.get("ARCHIVE_PATHS", [])
        stream_on = self.conf.get("STREAM_UPLOAD") == "true"
        notify_on = self.conf.get("NOTIFY_ON_SUCCESS") == "true"
        enc_on = bool(self.conf.get("ENCRYPT_PASSWORD"))
        cron_time = get_cron_schedule()

        text = (
            f"<b>⚙️ 备份策略与配置在线修改</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📁 <b>当前打包目录 ({len(paths)}个)</b>:\n<code>{'  '.join(paths)}</code>\n\n"
            f"🌊 <b>流式上传 (免占本地磁盘)</b>: <code>{'✅ 开启' if stream_on else '❌ 关闭'}</code>\n"
            f"🔔 <b>成功时也推送TG通知</b>: <code>{'✅ 开启' if notify_on else '❌ 关闭(仅失败报警)'}</code>\n"
            f"🔐 <b>AES-256 备份加密</b>: <code>{'🔒 已启用' if enc_on else '🔓 未启用'}</code>\n"
            f"⏰ <b>每日自动备份时间</b>: <code>{cron_time} (UTC)</code>\n"
            f"📅 <b>保留天数 (日/周/月)</b>: <code>{self.conf.get('KEEP_DAILY_DAYS')} / {self.conf.get('KEEP_WEEKLY_DAYS')} / {self.conf.get('KEEP_MONTHLY_DAYS')} 天</code>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"点击下方按钮直接在线切换或修改："
        )
        kb = {
            "inline_keyboard": [
                [
                    {"text": f"🌊 流式上传: {'✅开' if stream_on else '❌关'}", "callback_data": "cfg:toggle_stream"},
                    {"text": f"🔔 成功通知: {'✅开' if notify_on else '❌关'}", "callback_data": "cfg:toggle_notify"},
                ],
                [
                    {"text": "➕ 添加备份目录", "callback_data": "cfg:add_path"},
                    {"text": "➖ 移除备份目录", "callback_data": "cfg:del_path_menu"},
                ],
                [
                    {"text": "⏰ 修改定时备份时间", "callback_data": "cfg:cron_menu"},
                    {"text": "📅 修改保留天数策略", "callback_data": "cfg:keep_menu"},
                ],
                [
                    {"text": "🔐 设置/清除备份加密密码", "callback_data": "cfg:enc_prompt"},
                ],
                [
                    {"text": "🔙 返回主控台", "callback_data": "nav:home"},
                ],
            ]
        }
        if msg_id:
            self.edit_msg(chat_id, msg_id, text, reply_markup=kb)
        else:
            self.send_msg(chat_id, text, reply_markup=kb)

    # ==================== 6. Docker 容器管理中心 ====================
    def show_docker_menu(self, chat_id, msg_id=None):
        out = subprocess.getoutput("docker ps -a --format '{{.Names}}|{{.Status}}|{{.Image}}'")
        lines = []
        kb_rows = []
        self.container_cache.clear()
        row = []
        for idx, ln in enumerate(out.splitlines(), 1):
            if "|" not in ln:
                continue
            name, st, img = ln.split("|", 2)
            up = st.lower().startswith("up")
            icon = "🟢" if up else "🔴"
            lines.append(f"{icon} <b>{html_escape(name)}</b> — <code>{html_escape(st)}</code>")
            cid = f"dk{idx}"
            self.container_cache[cid] = name
            row.append({"text": f"{icon} {name[:16]}", "callback_data": f"dkview:{cid}"})
            if len(row) == 2:
                kb_rows.append(row)
                row = []
        if row:
            kb_rows.append(row)

        kb_rows.append([
            {"text": "📊 容器资源占用 (stats)", "callback_data": "act:dk_stats"},
            {"text": "🔄 刷新列表", "callback_data": "nav:docker"},
        ])
        kb_rows.append([{"text": "🔙 返回主控台", "callback_data": "nav:home"}])

        text = (
            f"<b>🐳 Docker 容器状态与管理 ({len(lines)} 个)</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            + "\n".join(lines[:25])
            + "\n━━━━━━━━━━━━━━━━━━━━━━\n💡 点击下方容器名称可进行<b>重启 / 停止 / 启动 / 查看日志</b>："
        )
        if msg_id:
            self.edit_msg(chat_id, msg_id, text, reply_markup={"inline_keyboard": kb_rows})
        else:
            self.send_msg(chat_id, text, reply_markup={"inline_keyboard": kb_rows})

    def show_container_detail(self, chat_id, msg_id, cid):
        cname = self.container_cache.get(cid)
        if not cname:
            self.show_docker_menu(chat_id, msg_id)
            return
        st = subprocess.getoutput(f"docker inspect -f '状态: {{.State.Status}} | 启动于: {{.State.StartedAt}}' {shlex.quote(cname)} 2>/dev/null")
        logs = subprocess.getoutput(f"docker logs --tail 20 {shlex.quote(cname)} 2>&1")
        text = (
            f"<b>🐳 容器管理: {html_escape(cname)}</b>\n"
            f"<code>{html_escape(st)}</code>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"<b>最新 20 行日志:</b>\n<pre>{html_escape(logs[-2000:])}</pre>"
        )
        kb = {
            "inline_keyboard": [
                [
                    {"text": "🔄 重启容器", "callback_data": f"dkact:restart:{cid}"},
                    {"text": "▶️ 启动", "callback_data": f"dkact:start:{cid}"},
                    {"text": "⏹️ 停止", "callback_data": f"dkact:stop:{cid}"},
                ],
                [
                    {"text": "🔃 刷新日志", "callback_data": f"dkview:{cid}"},
                    {"text": "🔙 返回容器列表", "callback_data": "nav:docker"},
                ],
            ]
        }
        self.edit_msg(chat_id, msg_id, text, reply_markup=kb)

    # ==================== 7. 服务器状态与快捷运维终端 ====================
    def show_status_menu(self, chat_id, msg_id=None):
        uptime = subprocess.getoutput("uptime")
        disk = subprocess.getoutput("df -h / /var /opt 2>/dev/null | uniq")
        mem = subprocess.getoutput("free -h")
        text = (
            f"<b>🖥️ 服务器实时监控看板</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"<b>⏱️ 运行时间与负载</b>:\n<pre>{html_escape(uptime)}</pre>\n"
            f"<b>💾 磁盘空间</b>:\n<pre>{html_escape(disk)}</pre>\n"
            f"<b>🧠 内存使用</b>:\n<pre>{html_escape(mem)}</pre>"
        )
        kb = {
            "inline_keyboard": [
                [
                    {"text": "🔥 Top 10 进程 (CPU/内存)", "callback_data": "act:top_procs"},
                    {"text": "📁 大目录占用排行", "callback_data": "act:big_dirs"},
                ],
                [
                    {"text": "🔌 端口监听列表", "callback_data": "act:net_ports"},
                    {"text": "🔄 刷新状态", "callback_data": "nav:status"},
                ],
                [
                    {"text": "🔙 返回主控台", "callback_data": "nav:home"},
                ],
            ]
        }
        if msg_id:
            self.edit_msg(chat_id, msg_id, text, reply_markup=kb)
        else:
            self.send_msg(chat_id, text, reply_markup=kb)

    def show_ops_menu(self, chat_id, msg_id=None):
        text = (
            "<b>💻 快捷运维与远程 Shell 终端</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "• 点击<b>【⌨️ 进入命令终端模式】</b>后，直接发消息即可在 VPS 上执行任意 Linux 命令\n"
            "• 或者随时直接发送 <code>/sh 命令</code>（例如 <code>/sh df -h</code>）"
        )
        kb = {
            "inline_keyboard": [
                [
                    {"text": "⌨️ 进入交互式 Shell 终端模式", "callback_data": "act:shell_prompt"},
                ],
                [
                    {"text": "🧹 一键清理系统日志与无用缓存", "callback_data": "act:clean_sys"},
                    {"text": "🐳 清理 Docker 悬空镜像缓存", "callback_data": "act:clean_docker"},
                ],
                [
                    {"text": "🔄 重启 Web 管理面板 (8999)", "callback_data": "act:restart_web"},
                    {"text": "📜 查看备份日志 (最新50行)", "callback_data": "act:log_view"},
                ],
                [
                    {"text": "🔙 返回主控台", "callback_data": "nav:home"},
                ],
            ]
        }
        if msg_id:
            self.edit_msg(chat_id, msg_id, text, reply_markup=kb)
        else:
            self.send_msg(chat_id, text, reply_markup=kb)

    # ==================== 处理回调与用户输入 ====================
    def handle_callback(self, cq):
        cq_id = cq["id"]
        from_id = str(cq["from"]["id"])
        msg = cq.get("message", {})
        chat_id = str(msg.get("chat", {}).get("id", ""))
        msg_id = msg.get("message_id")
        data = cq.get("data", "")

        if self.admin_id and from_id != self.admin_id and chat_id != self.admin_id:
            self.answer_cb(cq_id, "⛔ 无权操作", alert=True)
            return

        self.answer_cb(cq_id)

        # 导航路由
        if data == "nav:home":
            self.show_home(chat_id, msg_id)
        elif data == "nav:backup":
            self.show_backup_menu(chat_id, msg_id)
        elif data == "nav:files":
            self.show_files_menu(chat_id, msg_id)
        elif data == "nav:db":
            self.show_db_menu(chat_id, msg_id)
        elif data == "nav:nodes":
            self.show_nodes_menu(chat_id, msg_id)
        elif data == "nav:config":
            self.show_config_menu(chat_id, msg_id)
        elif data == "nav:docker":
            self.show_docker_menu(chat_id, msg_id)
        elif data == "nav:status":
            self.show_status_menu(chat_id, msg_id)
        elif data == "nav:ops":
            self.show_ops_menu(chat_id, msg_id)
        elif data == "act:kb_show":
            self.send_msg(chat_id, "⌨️ <b>已弹出底部快捷键盘</b>（点击右下角「🔽 收起底部键盘」或输入框右侧键盘图标即可收起）", reply_markup=self.get_reply_keyboard())
        elif data == "act:kb_hide":
            self.send_msg(chat_id, "🔽 <b>底部大键盘已彻底收起！</b>", reply_markup={"remove_keyboard": True})

        # 备份动作
        elif data == "act:bk_run":
            self.run_backup_task(chat_id, "run")
        elif data == "act:bk_archive":
            self.run_backup_task(chat_id, "archive")
        elif data == "act:bk_sync":
            self.run_backup_task(chat_id, "sync")
        elif data == "act:bk_serv00":
            self.run_serv00_backup(chat_id)
        elif data == "act:bk_test":
            out = subprocess.getoutput("/usr/local/bin/vps-backup test 2>&1")
            self.edit_msg(
                chat_id, msg_id,
                f"<b>🩺 备份系统自检结果</b>\n━━━━━━━━━━━━━━━━━━━━━━\n<pre>{html_escape(out[-3000:])}</pre>",
                reply_markup={"inline_keyboard": [[{"text": "🔙 返回备份中心", "callback_data": "nav:backup"}]]},
            )
        elif data == "act:restore_list":
            self.show_tier_files(chat_id, msg_id, "daily")

        # 云盘文件与空间动作
        elif data.startswith("flist:"):
            tier = data.split(":", 1)[1]
            self.show_tier_files(chat_id, msg_id, tier)
        elif data.startswith("fres:"):
            fid = data.split(":", 1)[1]
            self.handle_file_restore(chat_id, fid)
        elif data.startswith("fdel:"):
            fid = data.split(":", 1)[1]
            self.handle_file_delete(chat_id, msg_id, fid)
        elif data == "act:quota_detail":
            about = subprocess.getoutput("rclone about gdrive: 2>/dev/null")
            dirs = subprocess.getoutput("rclone lsf --dirs-only gdrive:vps-backup/ 2>/dev/null")
            self.edit_msg(
                chat_id, msg_id,
                f"<b>📊 Google Drive 5TB 容量与节点目录</b>\n━━━━━━━━━━━━━━━━━━━━━━\n<pre>{html_escape(about)}</pre>\n<b>云盘已备份节点目录:</b>\n<pre>{html_escape(dirs)}</pre>",
                reply_markup={"inline_keyboard": [[{"text": "🔙 返回文件管理", "callback_data": "nav:files"}]]},
            )
        elif data == "act:prune_now":
            out = subprocess.getoutput(
                "rclone delete --tpslimit 4 --min-age 7d gdrive:vps-backup/vps-45.130.166.10/archive/daily 2>&1"
            )
            self.send_msg(chat_id, f"🧹 <b>已按保留策略执行过期备份清理！</b>\n<code>{html_escape(out[:500] or '清理完成')}</code>")
        elif data == "act:empty_trash":
            threading.Thread(
                target=lambda: (
                    subprocess.run(["rclone", "cleanup", "gdrive:"]),
                    self.send_msg(chat_id, "🗑️ <b>Google Drive 云盘回收站已彻底清空！空间已释放。</b>"),
                ),
                daemon=True,
            ).start()

        # 数据库动作
        elif data == "act:db_dump_tg":
            self.dump_databases_to_tg(chat_id)
        elif data == "act:db_select":
            self.show_db_selector(chat_id, msg_id)
        elif data.startswith("dbtoggle:"):
            cid = data.split(":", 1)[1]
            self.toggle_db_container(chat_id, msg_id, cid)

        # 节点与部署动作
        elif data == "act:node_cloud_dirs":
            out = subprocess.getoutput("/usr/local/bin/vps-backup list 2>/dev/null")
            self.edit_msg(
                chat_id, msg_id,
                f"<b>☁️ 云盘上的各节点与备份概览</b>\n━━━━━━━━━━━━━━━━━━━━━━\n<pre>{html_escape(out[-3000:])}</pre>",
                reply_markup={"inline_keyboard": [[{"text": "🔙 返回节点中心", "callback_data": "nav:nodes"}]]},
            )
        elif data == "act:node_add_prompt":
            self.user_state[chat_id] = {"mode": "deploy_node"}
            self.send_msg(
                chat_id,
                "➕ <b>[一键部署新 VPS 节点]</b>\n"
                "请直接回复新服务器的连接信息（空格分隔）：\n"
                "<code>IP地址 端口 用户名 密码</code>\n\n"
                "例如：\n<code>1.2.3.4 22 root MyPassword123</code>\n"
                "<i>（发送 /cancel 可取消）</i>",
            )
        elif data == "act:node_ping_all":
            nodes = load_nodes()
            results = [f"🟢 <b>本机 ({os.uname().nodename})</b>: 在线"]
            for n in nodes:
                h, p = n.get("host"), n.get("port", 22)
                rc = subprocess.call(["nc", "-z", "-w", "3", str(h), str(p)])
                results.append(f"{'🟢' if rc == 0 else '🔴'} <b>{html_escape(n.get('name'))}</b> (<code>{h}:{p}</code>): {'SSH可达' if rc == 0 else '连接超时'}")
            self.edit_msg(
                chat_id, msg_id,
                "<b>🛰️ 节点连通性检测结果</b>\n━━━━━━━━━━━━━━━━━━━━━━\n" + "\n".join(results),
                reply_markup={"inline_keyboard": [[{"text": "🔙 返回节点中心", "callback_data": "nav:nodes"}]]},
            )
        elif data == "act:node_backup_all":
            self.run_backup_task(chat_id, "run")
            self.run_serv00_backup(chat_id)

        # 配置修改动作
        elif data == "cfg:toggle_stream":
            self.reload()
            new_val = "false" if self.conf.get("STREAM_UPLOAD") == "true" else "true"
            set_conf_scalar("STREAM_UPLOAD", new_val)
            self.show_config_menu(chat_id, msg_id)
        elif data == "cfg:toggle_notify":
            self.reload()
            new_val = "false" if self.conf.get("NOTIFY_ON_SUCCESS") == "true" else "true"
            set_conf_scalar("NOTIFY_ON_SUCCESS", new_val)
            self.show_config_menu(chat_id, msg_id)
        elif data == "cfg:add_path":
            self.user_state[chat_id] = {"mode": "add_path"}
            self.send_msg(chat_id, "📁 <b>请直接回复要添加到备份列表的绝对路径</b>（例如 <code>/var/www</code> 或 <code>/home</code>）：")
        elif data == "cfg:del_path_menu":
            self.reload()
            paths = self.conf.get("ARCHIVE_PATHS", [])
            kb_rows = [[{"text": f"➖ 移除 {p}", "callback_data": f"cfg:del_path:{p}"}] for p in paths]
            kb_rows.append([{"text": "🔙 返回配置中心", "callback_data": "nav:config"}])
            self.edit_msg(chat_id, msg_id, "<b>➖ 点击要从备份列表中移除的目录：</b>", reply_markup={"inline_keyboard": kb_rows})
        elif data.startswith("cfg:del_path:"):
            p_del = data.split(":", 2)[2]
            self.reload()
            paths = [p for p in self.conf.get("ARCHIVE_PATHS", []) if p != p_del]
            set_conf_array("ARCHIVE_PATHS", paths)
            self.show_config_menu(chat_id, msg_id)
        elif data == "cfg:cron_menu":
            kb = {
                "inline_keyboard": [
                    [
                        {"text": "每天 01:15", "callback_data": "cfg:set_cron:1:15"},
                        {"text": "每天 02:15", "callback_data": "cfg:set_cron:2:15"},
                        {"text": "每天 03:17", "callback_data": "cfg:set_cron:3:17"},
                    ],
                    [
                        {"text": "每天 04:20", "callback_data": "cfg:set_cron:4:20"},
                        {"text": "每天 05:30", "callback_data": "cfg:set_cron:5:30"},
                        {"text": "每天 18:00", "callback_data": "cfg:set_cron:18:0"},
                    ],
                    [{"text": "🔙 返回配置中心", "callback_data": "nav:config"}],
                ]
            }
            self.edit_msg(chat_id, msg_id, "<b>⏰ 选择每日自动备份执行时间 (UTC)：</b>", reply_markup=kb)
        elif data.startswith("cfg:set_cron:"):
            _, _, h, m = data.split(":")
            set_cron_schedule(h, m)
            self.show_config_menu(chat_id, msg_id)
        elif data == "cfg:keep_menu":
            kb = {
                "inline_keyboard": [
                    [{"text": "标准: 日7天 / 周28天 / 月180天", "callback_data": "cfg:set_keep:7:28:180"}],
                    [{"text": "精简: 日3天 / 周14天 / 月60天", "callback_data": "cfg:set_keep:3:14:60"}],
                    [{"text": "长效: 日14天 / 周60天 / 月365天", "callback_data": "cfg:set_keep:14:60:365"}],
                    [{"text": "🔙 返回配置中心", "callback_data": "nav:config"}],
                ]
            }
            self.edit_msg(chat_id, msg_id, "<b>📅 选择云盘历史备份保留周期策略：</b>", reply_markup=kb)
        elif data.startswith("cfg:set_keep:"):
            _, _, d, w, m = data.split(":")
            set_conf_scalar("KEEP_DAILY_DAYS", d)
            set_conf_scalar("KEEP_WEEKLY_DAYS", w)
            set_conf_scalar("KEEP_MONTHLY_DAYS", m)
            self.show_config_menu(chat_id, msg_id)
        elif data == "cfg:enc_prompt":
            self.user_state[chat_id] = {"mode": "set_enc"}
            self.send_msg(
                chat_id,
                "🔐 <b>请回复要设置的 AES-256 备份加密密码</b>（回复 <code>none</code> 则关闭加密）：\n⚠️ <i>请务必牢记密码，恢复备份时需要使用。</i>",
            )

        # Docker 容器动作
        elif data.startswith("dkview:"):
            cid = data.split(":", 1)[1]
            self.show_container_detail(chat_id, msg_id, cid)
        elif data.startswith("dkact:"):
            _, action, cid = data.split(":", 2)
            cname = self.container_cache.get(cid)
            if cname and action in ("restart", "start", "stop"):
                subprocess.run(["docker", action, cname])
                self.show_container_detail(chat_id, msg_id, cid)
        elif data == "act:dk_stats":
            out = subprocess.getoutput("docker stats --no-stream --format 'table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}'")
            self.edit_msg(
                chat_id, msg_id,
                f"<b>📊 Docker 容器实时资源占用</b>\n━━━━━━━━━━━━━━━━━━━━━━\n<pre>{html_escape(out[-3000:])}</pre>",
                reply_markup={"inline_keyboard": [[{"text": "🔄 刷新", "callback_data": "act:dk_stats"}, {"text": "🔙 返回Docker", "callback_data": "nav:docker"}]]},
            )

        # 监控与运维动作
        elif data == "act:top_procs":
            out = subprocess.getoutput("ps aux --sort=-%mem | head -n 12")
            self.edit_msg(
                chat_id, msg_id,
                f"<b>🔥 内存占用 Top 10 进程</b>\n━━━━━━━━━━━━━━━━━━━━━━\n<pre>{html_escape(out)}</pre>",
                reply_markup={"inline_keyboard": [[{"text": "🔙 返回服务器监控", "callback_data": "nav:status"}]]},
            )
        elif data == "act:big_dirs":
            out = subprocess.getoutput("du -h --max-depth=1 / /opt /root 2>/dev/null | sort -hr | head -n 20")
            self.edit_msg(
                chat_id, msg_id,
                f"<b>📁 磁盘大目录占用排行</b>\n━━━━━━━━━━━━━━━━━━━━━━\n<pre>{html_escape(out)}</pre>",
                reply_markup={"inline_keyboard": [[{"text": "🔙 返回服务器监控", "callback_data": "nav:status"}]]},
            )
        elif data == "act:net_ports":
            out = subprocess.getoutput("ss -tulpn | grep LISTEN | head -n 25")
            self.edit_msg(
                chat_id, msg_id,
                f"<b>🔌 当前监听端口列表</b>\n━━━━━━━━━━━━━━━━━━━━━━\n<pre>{html_escape(out)}</pre>",
                reply_markup={"inline_keyboard": [[{"text": "🔙 返回服务器监控", "callback_data": "nav:status"}]]},
            )
        elif data == "act:log_view":
            out = subprocess.getoutput(f"tail -n 50 {LOG_FILE} 2>/dev/null")
            self.edit_msg(
                chat_id, msg_id,
                f"<b>📜 备份日志 (最新 50 行)</b>\n━━━━━━━━━━━━━━━━━━━━━━\n<pre>{html_escape(out[-3200:] or '暂无日志')}</pre>",
                reply_markup={"inline_keyboard": [[{"text": "🔄 刷新日志", "callback_data": "act:log_view"}, {"text": "🔙 返回主控台", "callback_data": "nav:home"}]]},
            )
        elif data == "act:clean_sys":
            out = subprocess.getoutput("apt-get clean && journalctl --vacuum-size=50M 2>&1 && df -h /")
            self.send_msg(chat_id, f"🧹 <b>系统缓存与旧日志清理完成：</b>\n<pre>{html_escape(out[-1500:])}</pre>")
        elif data == "act:clean_docker":
            out = subprocess.getoutput("docker image prune -f 2>&1")
            self.send_msg(chat_id, f"🐳 <b>Docker 悬空镜像清理完成：</b>\n<pre>{html_escape(out[-1500:])}</pre>")
        elif data == "act:restart_web":
            subprocess.run(["systemctl", "restart", "vps-backup-web"])
            self.send_msg(chat_id, "✅ <b>Web 终端管理面板 (端口 8999) 已重启！</b>")
        elif data == "act:shell_prompt":
            self.user_state[chat_id] = {"mode": "shell"}
            self.send_msg(
                chat_id,
                "💻 <b>[已进入交互式 Shell 终端模式]</b>\n"
                "现在直接发送任意 Linux 命令即可在服务器上执行并返回结果（例如 <code>df -h</code>、<code>docker ps</code>）。\n"
                "<i>点击底部菜单按钮或发送 /cancel 即可退出终端模式。</i>",
            )

    def handle_message(self, msg):
        chat_id = str(msg["chat"]["id"])
        text = (msg.get("text") or "").strip()
        if not text:
            return

        # 首次对话自动认主绑定
        if not self.admin_id:
            self.admin_id = chat_id
            set_conf_scalar("TG_CHAT_ID", chat_id)
            self.send_msg(
                chat_id,
                f"🎉 <b>[管理员自动绑定成功]</b>\n你的管理员 Chat ID: <code>{chat_id}</code>",
                reply_markup=self.get_reply_keyboard(),
            )
            self.show_home(chat_id)
            return

        if chat_id != self.admin_id:
            self.send_msg(chat_id, "⛔ 私人专属 VPS 控制中心，未授权访问。")
            return

        # 取消状态或底部常驻按钮优先匹配
        if text in ("/cancel", "取消"):
            self.user_state.pop(chat_id, None)
            self.show_home(chat_id)
            return

        bottom_map = {
            "🏠 主控面板": lambda: self.show_home(chat_id),
            "🚀 备份与恢复": lambda: self.show_backup_menu(chat_id),
            "📂 云盘文件管理": lambda: self.show_files_menu(chat_id),
            "🌐 节点与部署": lambda: self.show_nodes_menu(chat_id),
            "🗄️ 数据库热备": lambda: self.show_db_menu(chat_id),
            "🐳 Docker 管理": lambda: self.show_docker_menu(chat_id),
            "⚙️ 策略与配置": lambda: self.show_config_menu(chat_id),
            "🖥️ 服务器状态": lambda: self.show_status_menu(chat_id),
            "💻 快捷运维/终端": lambda: self.show_ops_menu(chat_id),
        }
        if text in ("🔽 收起底部键盘", "/hide", "收起"):
            self.user_state.pop(chat_id, None)
            self.send_msg(chat_id, "🔽 <b>底部大键盘已彻底收起！</b>", reply_markup={"remove_keyboard": True})
            return

        if text in bottom_map:
            self.user_state.pop(chat_id, None)
            bottom_map[text]()
            return

        # 命令路由
        if text in ("/start", "/menu", "/help", "菜单", "面板"):
            self.show_home(chat_id, with_reply_kb=False)
            return
        elif text.startswith("/backup"):
            self.show_backup_menu(chat_id)
            return
        elif text.startswith("/files") or text.startswith("/quota") or text.startswith("/list"):
            self.show_files_menu(chat_id)
            return
        elif text.startswith("/db"):
            self.show_db_menu(chat_id)
            return
        elif text.startswith("/nodes") or text.startswith("/deploy"):
            self.show_nodes_menu(chat_id)
            return
        elif text.startswith("/config"):
            self.show_config_menu(chat_id)
            return
        elif text.startswith("/docker"):
            self.show_docker_menu(chat_id)
            return
        elif text.startswith("/status"):
            self.show_status_menu(chat_id)
            return
        elif text.startswith("/log"):
            out = subprocess.getoutput(f"tail -n 50 {LOG_FILE} 2>/dev/null")
            self.send_msg(chat_id, f"<b>📜 最新 50 行备份日志</b>\n<pre>{html_escape(out[-3200:])}</pre>", reply_markup=self.get_home_kb())
            return
        elif text.startswith("/sh "):
            cmd = text[4:].strip()
            out = subprocess.getoutput(cmd)
            self.send_msg(chat_id, f"💻 <code>$ {html_escape(cmd)}</code>\n<pre>{html_escape(out[-3500:] or '(无输出)')}</pre>")
            return
        elif text == "/sh":
            self.show_ops_menu(chat_id)
            return

        # 交互式输入状态处理
        state = self.user_state.get(chat_id)
        if state:
            mode = state.get("mode")
            if mode == "add_path":
                self.user_state.pop(chat_id, None)
                if not text.startswith("/"):
                    self.send_msg(chat_id, "❌ 必须是绝对路径（以 <code>/</code> 开头）。")
                else:
                    self.reload()
                    paths = list(self.conf.get("ARCHIVE_PATHS", []))
                    if text not in paths:
                        paths.append(text)
                        set_conf_array("ARCHIVE_PATHS", paths)
                    self.send_msg(chat_id, f"✅ 已添加备份目录: <code>{html_escape(text)}</code>")
                    self.show_config_menu(chat_id)
                return
            elif mode == "set_enc":
                self.user_state.pop(chat_id, None)
                pw = "" if text.lower() == "none" else text
                set_conf_scalar("ENCRYPT_PASSWORD", pw)
                self.send_msg(chat_id, "✅ 备份加密设置已更新！")
                self.show_config_menu(chat_id)
                return
            elif mode == "deploy_node":
                self.user_state.pop(chat_id, None)
                parts = text.split()
                if len(parts) < 4:
                    self.send_msg(chat_id, "❌ 格式错误，请按 <code>IP 端口 用户名 密码</code> 格式发送。")
                else:
                    self.deploy_remote_vps(chat_id, parts[0], parts[1], parts[2], " ".join(parts[3:]))
                return
            elif mode == "shell":
                out = subprocess.getoutput(text)
                self.send_msg(
                    chat_id,
                    f"💻 <code>root@vps:~# {html_escape(text)}</code>\n<pre>{html_escape(out[-3500:] or '(执行完成，无输出)')}</pre>",
                    reply_markup={"inline_keyboard": [[{"text": "🚪 退出终端模式", "callback_data": "nav:home"}]]},
                )
                return

        # 默认打开主控台
        self.show_home(chat_id, with_reply_kb=True)

    def run(self):
        offset = 0
        print("[*] Telegram 全功能控制面板机器人已启动...")
        while True:
            self.reload()
            if not self.token:
                time.sleep(5)
                continue

            if not self.commands_registered or self.last_token != self.token:
                self.register_commands()

            updates = self.api_call("getUpdates", {"offset": offset, "timeout": 20}, timeout=30)
            if not updates or not updates.get("ok"):
                time.sleep(2)
                continue

            for u in updates.get("result", []):
                offset = u["update_id"] + 1
                try:
                    if "callback_query" in u:
                        self.handle_callback(u["callback_query"])
                    elif "message" in u:
                        self.handle_message(u["message"])
                except Exception as e:
                    print(f"[!] update error: {e}")


if __name__ == "__main__":
    TelegramBot().run()
