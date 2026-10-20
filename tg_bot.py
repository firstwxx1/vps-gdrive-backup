#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Google Drive 5TB VPS 备份 - Telegram 交互式控制机器人
功能:
  - 手机 Telegram 端实时管理 VPS 备份
  - 交互式内联按钮面板 (立即备份、查询5TB云盘配额、备份列表、实时日志、服务器状态)
  - 仅响应绑定的管理用户，安全防越权
  - 零外部 pip 依赖（纯 Python 标准库）
"""

import os
import sys
import time
import json
import urllib.request
import urllib.parse
import subprocess
import threading

CONF_FILE = "/etc/vps-backup/backup.conf"
LOG_FILE = "/var/log/vps-backup.log"

def load_conf():
    conf = {
        "TG_BOT_TOKEN": "",
        "TG_CHAT_ID": "",
        "TG_API": "https://api.telegram.org",
        "BACKUP_NAME": "vps"
    }
    if os.path.exists(CONF_FILE):
        try:
            with open(CONF_FILE, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("#") or "=" not in line:
                        continue
                    k, v = line.split("=", 1)
                    k = k.strip()
                    v = v.strip().strip('"\'')
                    if k in conf:
                        conf[k] = v
        except Exception as e:
            print(f"[!] 读取配置错误: {e}")
    return conf

def save_chat_id(chat_id):
    if not os.path.exists(CONF_FILE):
        return
    try:
        lines = []
        found = False
        with open(CONF_FILE, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                if line.strip().startswith("TG_CHAT_ID="):
                    lines.append(f'TG_CHAT_ID="{chat_id}"\n')
                    found = True
                else:
                    lines.append(line)
        if not found:
            lines.append(f'\nTG_CHAT_ID="{chat_id}"\n')
        with open(CONF_FILE, "w", encoding="utf-8") as f:
            f.writelines(lines)
        print(f"[+] 已将 TG_CHAT_ID 自动保存到 {CONF_FILE}")
    except Exception as e:
        print(f"[!] 保存 TG_CHAT_ID 失败: {e}")

class TelegramBot:
    def __init__(self):
        self.conf = load_conf()
        self.token = self.conf.get("TG_BOT_TOKEN", "").strip()
        self.admin_id = self.conf.get("TG_CHAT_ID", "").strip()
        self.api_base = self.conf.get("TG_API", "https://api.telegram.org").rstrip("/")
        self.is_running_backup = False

    def reload(self):
        self.conf = load_conf()
        self.token = self.conf.get("TG_BOT_TOKEN", "").strip()
        self.admin_id = self.conf.get("TG_CHAT_ID", "").strip()

    def api_call(self, method, data=None):
        if not self.token:
            return None
        url = f"{self.api_base}/bot{self.token}/{method}"
        headers = {"Content-Type": "application/json"}
        req_data = json.dumps(data).encode("utf-8") if data else None
        req = urllib.request.Request(url, data=req_data, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=35) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            # print(f"API {method} error: {e}")
            return None

    def send_msg(self, chat_id, text, reply_markup=None, parse_mode="HTML"):
        data = {
            "chat_id": chat_id,
            "text": text[:4000],
            "parse_mode": parse_mode,
            "disable_web_page_preview": True
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
            "disable_web_page_preview": True
        }
        if reply_markup:
            data["reply_markup"] = reply_markup
        return self.api_call("editMessageText", data)

    def answer_callback(self, callback_query_id, text=None):
        data = {"callback_query_id": callback_query_id}
        if text:
            data["text"] = text
        return self.api_call("answerCallbackQuery", data)

    def get_main_keyboard(self):
        return {
            "inline_keyboard": [
                [
                    {"text": "🚀 立即执行备份", "callback_data": "btn_backup"},
                    {"text": "📊 5TB 云盘配额", "callback_data": "btn_quota"}
                ],
                [
                    {"text": "📂 云盘备份列表", "callback_data": "btn_list"},
                    {"text": "📜 查看近期日志", "callback_data": "btn_log"}
                ],
                [
                    {"text": "🖥️ 服务器系统状态", "callback_data": "btn_status"},
                    {"text": "🩺 备份系统自检", "callback_data": "btn_test"}
                ],
                [
                    {"text": "🔄 刷新主面板", "callback_data": "btn_menu"}
                ]
            ]
        }

    def get_back_keyboard(self):
        return {
            "inline_keyboard": [
                [
                    {"text": "🔙 返回主菜单", "callback_data": "btn_menu"},
                    {"text": "🔄 再次执行/刷新", "callback_data": "btn_refresh"}
                ]
            ]
        }

    def render_menu_text(self):
        host = os.uname().nodename
        t_now = time.strftime("%Y-%m-%d %H:%M:%S")
        return (
            f"<b>☁️ Google Drive 5TB 备份管理终端</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"📍 <b>主机名称</b>: <code>{host}</code>\n"
            f"⏰ <b>当前时间</b>: <code>{t_now}</code>\n"
            f"⚡ <b>定时任务</b>: 每天 03:17 自动运行\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"请点击下方快捷按钮进行操作："
        )

    def handle_backup(self, chat_id, msg_id=None):
        if self.is_running_backup:
            self.send_msg(chat_id, "⚠️ 当前已有备份任务正在运行中，请勿重复触发！")
            return

        def run_thread():
            self.is_running_backup = True
            try:
                self.send_msg(chat_id, "⏳ <b>[任务开始]</b> 正在执行数据库热导出与打包流式上传至 Google Drive，耗时约 1~3 分钟，请稍候...")
                p = subprocess.run(["/usr/local/bin/vps-backup", "run"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="ignore")
                out = p.stdout.strip()
                if p.returncode == 0:
                    res_msg = f"✅ <b>[备份成功完成]</b>\n\n<pre>{out[-1500:]}</pre>"
                else:
                    res_msg = f"❌ <b>[备份出现错误]</b>\n\n<pre>{out[-1500:]}</pre>"
                self.send_msg(chat_id, res_msg, reply_markup=self.get_main_keyboard())
            except Exception as e:
                self.send_msg(chat_id, f"❌ 执行异常: {e}")
            finally:
                self.is_running_backup = False

        threading.Thread(target=run_thread, daemon=True).start()

    def handle_quota(self, chat_id, msg_id=None):
        out = subprocess.getoutput("rclone about gdrive: 2>/dev/null")
        if not out or "Total:" not in out:
            out = "无法获取容量信息，请检查 rclone 配置。"
        text = f"<b>📊 Google Drive 5TB 云盘配额</b>\n━━━━━━━━━━━━━━━━━━\n<pre>{out}</pre>"
        if msg_id:
            self.edit_msg(chat_id, msg_id, text, reply_markup=self.get_back_keyboard())
        else:
            self.send_msg(chat_id, text, reply_markup=self.get_back_keyboard())

    def handle_list(self, chat_id, msg_id=None):
        out = subprocess.getoutput("/usr/local/bin/vps-backup list 2>/dev/null")
        if not out:
            out = "暂无备份文件或获取超时。"
        text = f"<b>📂 Google Drive 上的历史归档列表</b>\n━━━━━━━━━━━━━━━━━━\n<pre>{out[-3000:]}</pre>"
        if msg_id:
            self.edit_msg(chat_id, msg_id, text, reply_markup=self.get_back_keyboard())
        else:
            self.send_msg(chat_id, text, reply_markup=self.get_back_keyboard())

    def handle_log(self, chat_id, msg_id=None):
        out = subprocess.getoutput("tail -n 40 /var/log/vps-backup.log 2>/dev/null")
        if not out:
            out = "日志文件为空。"
        text = f"<b>📜 备份执行日志 (最新 40 行)</b>\n━━━━━━━━━━━━━━━━━━\n<pre>{out[-3000:]}</pre>"
        if msg_id:
            self.edit_msg(chat_id, msg_id, text, reply_markup=self.get_back_keyboard())
        else:
            self.send_msg(chat_id, text, reply_markup=self.get_back_keyboard())

    def handle_status(self, chat_id, msg_id=None):
        uptime = subprocess.getoutput("uptime")
        disk = subprocess.getoutput("df -h /")
        mem = subprocess.getoutput("free -h")
        text = (
            f"<b>🖥️ 服务器运行状态</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"<b>系统负载</b>:\n<pre>{uptime}</pre>\n"
            f"<b>磁盘使用</b>:\n<pre>{disk}</pre>\n"
            f"<b>内存使用</b>:\n<pre>{mem}</pre>"
        )
        if msg_id:
            self.edit_msg(chat_id, msg_id, text, reply_markup=self.get_back_keyboard())
        else:
            self.send_msg(chat_id, text, reply_markup=self.get_back_keyboard())

    def handle_test(self, chat_id, msg_id=None):
        out = subprocess.getoutput("/usr/local/bin/vps-backup test 2>/dev/null")
        text = f"<b>🩺 备份系统连通性自检</b>\n━━━━━━━━━━━━━━━━━━\n<pre>{out[-3000:]}</pre>"
        if msg_id:
            self.edit_msg(chat_id, msg_id, text, reply_markup=self.get_back_keyboard())
        else:
            self.send_msg(chat_id, text, reply_markup=self.get_back_keyboard())

    def run(self):
        offset = 0
        print("[*] Telegram Bot 守护服务启动中...")
        while True:
            self.reload()
            if not self.token:
                print("[!] 未在 /etc/vps-backup/backup.conf 中配置 TG_BOT_TOKEN，正在等待配置...")
                time.sleep(10)
                continue

            updates = self.api_call("getUpdates", {"offset": offset, "timeout": 25})
            if not updates or not updates.get("ok"):
                time.sleep(3)
                continue

            for u in updates.get("result", []):
                offset = u["update_id"] + 1

                # 1. 处理回调按钮点击
                if "callback_query" in u:
                    cq = u["callback_query"]
                    cq_id = cq["id"]
                    from_user = str(cq["from"]["id"])
                    data = cq.get("data", "")
                    msg = cq.get("message", {})
                    chat_id = msg.get("chat", {}).get("id")
                    msg_id = msg.get("message_id")

                    # 安全校验
                    if self.admin_id and from_user != self.admin_id and str(chat_id) != self.admin_id:
                        self.answer_callback(cq_id, "无权操作")
                        continue

                    self.answer_callback(cq_id)
                    if data == "btn_menu":
                        self.edit_msg(chat_id, msg_id, self.render_menu_text(), reply_markup=self.get_main_keyboard())
                    elif data == "btn_backup":
                        self.handle_backup(chat_id, msg_id)
                    elif data == "btn_quota":
                        self.handle_quota(chat_id, msg_id)
                    elif data == "btn_list":
                        self.handle_list(chat_id, msg_id)
                    elif data == "btn_log":
                        self.handle_log(chat_id, msg_id)
                    elif data == "btn_status":
                        self.handle_status(chat_id, msg_id)
                    elif data == "btn_test":
                        self.handle_test(chat_id, msg_id)
                    elif data == "btn_refresh":
                        self.edit_msg(chat_id, msg_id, self.render_menu_text(), reply_markup=self.get_main_keyboard())
                    continue

                # 2. 处理普通文本消息
                if "message" in u:
                    msg = u["message"]
                    chat_id = str(msg["chat"]["id"])
                    text = msg.get("text", "").strip()

                    # 如果尚未设置 admin_id，自动将第一个发送消息的用户绑定为管理员！
                    if not self.admin_id:
                        self.admin_id = chat_id
                        save_chat_id(chat_id)
                        self.send_msg(chat_id, f"🎉 <b>[管理员自动绑定成功]</b>\n你的 Chat ID 是: <code>{chat_id}</code>\n现在你可以使用本机器人管理你的 VPS 5TB 备份了！", reply_markup=self.get_main_keyboard())
                        continue

                    # 安全拦截非管理员
                    if chat_id != self.admin_id:
                        self.send_msg(chat_id, "⛔ 抱歉，本机器人为私人专属 VPS 控制面板，未授权访问。")
                        continue

                    if text in ["/start", "/menu", "menu", "面板", "管理"]:
                        self.send_msg(chat_id, self.render_menu_text(), reply_markup=self.get_main_keyboard())
                    elif text.startswith("/backup"):
                        self.handle_backup(chat_id)
                    elif text.startswith("/quota"):
                        self.handle_quota(chat_id)
                    elif text.startswith("/list"):
                        self.handle_list(chat_id)
                    elif text.startswith("/log"):
                        self.handle_log(chat_id)
                    elif text.startswith("/status"):
                        self.handle_status(chat_id)
                    elif text.startswith("/test"):
                        self.handle_test(chat_id)
                    else:
                        self.send_msg(chat_id, self.render_menu_text(), reply_markup=self.get_main_keyboard())

if __name__ == '__main__':
    bot = TelegramBot()
    bot.run()
