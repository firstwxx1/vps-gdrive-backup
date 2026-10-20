#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
VPS 备份与部署 Web 终端管理面板
端口: 8999
依赖: Python 3 标准库（零外部依赖）
"""

import http.server
import socketserver
import urllib.parse
import urllib.request
import json
import subprocess
import os
import sys
import threading
import time
import hashlib
import secrets

PORT = 8999
CONF_FILE = "/etc/vps-backup/web.conf"
DEFAULT_PASS = "admin123456"

# 读取或生成密码
def get_auth_token():
    if os.path.exists(CONF_FILE):
        try:
            with open(CONF_FILE, "r", encoding="utf-8") as f:
                for line in f:
                    if line.startswith("PASSWORD="):
                        return line.strip().split("=", 1)[1].strip('"\'')
        except:
            pass
    return DEFAULT_PASS

SESSION_TOKENS = set()

HTML_PAGE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Google Drive 5TB VPS 备份管理终端面板</title>
    <style>
        :root {
            --bg: #0f172a;
            --card-bg: #1e293b;
            --border: #334155;
            --text: #f8fafc;
            --text-dim: #94a3b8;
            --primary: #38bdf8;
            --primary-hover: #0284c7;
            --success: #22c55e;
            --danger: #ef4444;
            --term-bg: #090d16;
        }
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", sans-serif;
            background-color: var(--bg);
            color: var(--text);
            padding: 24px;
            min-height: 100vh;
        }
        .container { max-width: 1100px; margin: 0 auto; }
        .header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding-bottom: 20px;
            border-bottom: 1px solid var(--border);
            margin-bottom: 24px;
        }
        .header h1 {
            font-size: 24px;
            font-weight: 700;
            display: flex;
            align-items: center;
            gap: 10px;
            color: var(--primary);
        }
        .header .badge {
            background: #0369a1;
            color: #e0f2fe;
            font-size: 13px;
            padding: 4px 10px;
            border-radius: 9999px;
            font-weight: 500;
        }
        .grid-cards {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
            gap: 16px;
            margin-bottom: 24px;
        }
        .card {
            background: var(--card-bg);
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 18px;
        }
        .card-title {
            font-size: 13px;
            color: var(--text-dim);
            text-transform: uppercase;
            letter-spacing: 0.05em;
            margin-bottom: 8px;
        }
        .card-value {
            font-size: 22px;
            font-weight: 700;
            color: var(--text);
        }
        .progress-bar {
            background: #334155;
            height: 8px;
            border-radius: 4px;
            overflow: hidden;
            margin-top: 10px;
        }
        .progress-fill {
            background: var(--success);
            height: 100%;
            width: 0%;
            transition: width 0.3s;
        }
        .btn-group {
            display: flex;
            flex-wrap: wrap;
            gap: 10px;
            margin-bottom: 20px;
        }
        button, .btn {
            background: var(--card-bg);
            color: var(--text);
            border: 1px solid var(--border);
            padding: 10px 16px;
            border-radius: 8px;
            font-size: 14px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s;
            display: inline-flex;
            align-items: center;
            gap: 6px;
        }
        button:hover { background: #273549; border-color: var(--primary); }
        button.btn-primary {
            background: var(--primary);
            color: #0f172a;
            border-color: var(--primary);
        }
        button.btn-primary:hover { background: var(--primary-hover); }
        .terminal-box {
            background: var(--term-bg);
            border: 1px solid var(--border);
            border-radius: 12px;
            overflow: hidden;
            margin-bottom: 24px;
        }
        .term-header {
            background: #131b2e;
            padding: 10px 16px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 1px solid var(--border);
            font-family: monospace;
            font-size: 13px;
            color: var(--text-dim);
        }
        .term-body {
            padding: 16px;
            font-family: "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace;
            font-size: 13px;
            line-height: 1.5;
            color: #38bdf8;
            height: 380px;
            overflow-y: auto;
            white-space: pre-wrap;
            word-break: break-all;
        }
        .term-input-bar {
            display: flex;
            background: #131b2e;
            border-top: 1px solid var(--border);
            padding: 8px 12px;
            align-items: center;
        }
        .term-prompt {
            color: var(--success);
            font-family: monospace;
            font-weight: bold;
            margin-right: 8px;
            user-select: none;
        }
        .term-input {
            flex: 1;
            background: transparent;
            border: none;
            color: #fff;
            font-family: monospace;
            font-size: 14px;
            outline: none;
        }
        /* 部署弹窗/卡片 */
        .deploy-section {
            background: var(--card-bg);
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 20px;
            margin-top: 24px;
        }
        .deploy-title {
            font-size: 16px;
            font-weight: 700;
            margin-bottom: 16px;
            display: flex;
            align-items: center;
            gap: 8px;
            color: var(--primary);
        }
        .form-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 12px;
            margin-bottom: 16px;
        }
        .form-group label {
            display: block;
            font-size: 12px;
            color: var(--text-dim);
            margin-bottom: 6px;
        }
        .form-group input {
            width: 100%;
            padding: 9px 12px;
            background: #0f172a;
            border: 1px solid var(--border);
            border-radius: 6px;
            color: #fff;
            font-size: 14px;
            outline: none;
        }
        .form-group input:focus { border-color: var(--primary); }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <div>
                <h1>☁️ Google Drive 5TB 备份管理终端</h1>
                <div style="font-size: 13px; color: var(--text-dim); margin-top: 4px;">多服务器统一备份与节点部署控制台</div>
            </div>
            <div class="badge">已连接 5TB 谷歌云盘</div>
        </div>

        <div class="grid-cards">
            <div class="card">
                <div class="card-title">Google Drive 总配额</div>
                <div class="card-value" id="quota-total">5.00 TiB</div>
                <div style="font-size: 12px; color: var(--text-dim); margin-top: 4px;">超大企业级云存储</div>
            </div>
            <div class="card">
                <div class="card-title">已用空间</div>
                <div class="card-value" id="quota-used">计算中...</div>
                <div class="progress-bar"><div class="progress-fill" id="quota-fill"></div></div>
            </div>
            <div class="card">
                <div class="card-title">剩余可用</div>
                <div class="card-value" id="quota-free">5.00 TiB</div>
                <div style="font-size: 12px; color: var(--success); margin-top: 4px;">空间非常充足</div>
            </div>
            <div class="card">
                <div class="card-title">自动备份时间</div>
                <div class="card-value" style="font-size: 18px;">每天 03:17 (UTC)</div>
                <div style="font-size: 12px; color: var(--text-dim); margin-top: 4px;">系统自动无感运行</div>
            </div>
        </div>

        <div class="btn-group">
            <button class="btn-primary" onclick="runCmd('vps-backup run')">▶ 立即执行备份</button>
            <button onclick="runCmd('vps-backup list')">📂 查看云盘备份列表</button>
            <button onclick="runCmd('rclone about gdrive:')">📊 刷新云盘容量配额</button>
            <button onclick="runCmd('vps-backup test')">🩺 运行自检测试</button>
            <button onclick="runCmd('tail -n 60 /var/log/vps-backup.log')">📜 查看近期日志</button>
            <button onclick="clearTerm()">🧹 清空终端屏幕</button>
        </div>

        <div class="terminal-box">
            <div class="term-header">
                <span>TERMINAL CONSOLE (bash)</span>
                <span id="term-status" style="color: var(--success);">● 准备就绪</span>
            </div>
            <div class="term-body" id="term-body">欢迎使用 Google Drive 5TB VPS 备份管理终端！\n点击上方快捷按钮，或在下方输入命令执行。\n\n</div>
            <div class="term-input-bar">
                <span class="term-prompt">root@vps:~#</span>
                <input type="text" class="term-input" id="term-input" placeholder="输入命令，例如: vps-backup list 回车执行" onkeydown="if(event.key==='Enter') sendInputCmd()">
                <button style="padding: 6px 12px; font-size: 13px;" onclick="sendInputCmd()">发送</button>
            </div>
        </div>

        <div class="deploy-section" style="margin-top: 24px;">
            <div class="deploy-title">🤖 启用 Telegram 手机控制机器人面板</div>
            <p style="font-size: 13px; color: var(--text-dim); margin-bottom: 16px;">
                在 Telegram 中向 <b>@BotFather</b> 发送 <code>/newbot</code> 创建机器人获取 Token，填入下方即可随时在手机上点击按钮管理备份、查询5TB配额并接收报警。
            </p>
            <div style="display: flex; gap: 12px; margin-bottom: 12px; max-width: 600px;">
                <input type="text" id="tg-token" placeholder="输入形如 123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ 的 Token" style="flex: 1; padding: 10px 12px; background: #0f172a; border: 1px solid var(--border); border-radius: 6px; color: #fff; outline: none;">
                <button class="btn-primary" onclick="setupTelegram()">绑定并启动机器人</button>
            </div>
            <div id="tg-status" style="font-size: 13px; color: var(--text-dim);"></div>
        </div>

        <div class="deploy-section">
            <div class="deploy-title">🌐 一键部署新 VPS 节点到 Google Drive 自动备份</div>
            <p style="font-size: 13px; color: var(--text-dim); margin-bottom: 16px;">
                输入新 VPS 的连接信息，本面板将自动把 Google Drive 5TB 授权及备份程序推送到目标机器，并设立每日凌晨定时任务。
            </p>
            <div class="form-grid">
                <div class="form-group">
                    <label>新服务器 IP 或域名</label>
                    <input type="text" id="deploy-ip" placeholder="例如: 1.2.3.4">
                </div>
                <div class="form-group">
                    <label>SSH 端口</label>
                    <input type="text" id="deploy-port" value="22">
                </div>
                <div class="form-group">
                    <label>SSH 用户名</label>
                    <input type="text" id="deploy-user" value="root">
                </div>
                <div class="form-group">
                    <label>SSH 密码</label>
                    <input type="password" id="deploy-pass" placeholder="输入密码">
                </div>
            </div>
            <button class="btn-primary" onclick="startDeploy()">🚀 开始部署新节点</button>
        </div>
    </div>

    <script>
        const term = document.getElementById('term-body');
        const termInput = document.getElementById('term-input');
        const termStatus = document.getElementById('term-status');

        function appendTerm(text) {
            term.textContent += text;
            term.scrollTop = term.scrollHeight;
        }

        function clearTerm() {
            term.textContent = "";
        }

        async function fetchQuota() {
            try {
                const res = await fetch('/api/quota');
                const data = await res.json();
                if (data.total) document.getElementById('quota-total').textContent = data.total;
                if (data.used) document.getElementById('quota-used').textContent = data.used;
                if (data.free) document.getElementById('quota-free').textContent = data.free;
            } catch(e) {}
        }

        async function runCmd(cmd) {
            appendTerm('\\n$ ' + cmd + '\\n');
            termStatus.textContent = '● 正在执行: ' + cmd;
            termStatus.style.color = '#38bdf8';
            try {
                const res = await fetch('/api/exec', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ cmd: cmd })
                });
                const data = await res.json();
                appendTerm(data.output || '(无输出)\\n');
                if (data.output && data.output.includes('Total:')) {
                    fetchQuota();
                }
            } catch(err) {
                appendTerm('[错误] 执行请求失败: ' + err + '\\n');
            }
            termStatus.textContent = '● 准备就绪';
            termStatus.style.color = 'var(--success)';
        }

        function sendInputCmd() {
            const cmd = termInput.value.trim();
            if (!cmd) return;
            termInput.value = '';
            runCmd(cmd);
        }

        async function setupTelegram() {
            const token = document.getElementById('tg-token').value.trim();
            const statusEl = document.getElementById('tg-status');
            if (!token) {
                alert('请输入 Telegram Bot Token');
                return;
            }
            statusEl.innerHTML = '<span style="color: #38bdf8;">正在验证 Token 并启动守护服务...</span>';
            try {
                const res = await fetch('/api/telegram', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ token: token })
                });
                const data = await res.json();
                if (data.ok) {
                    statusEl.innerHTML = `<span style="color: var(--success); font-weight: bold;">✅ 机器人已启动！请打开 Telegram 搜索 <u>@${data.username}</u> 发送 /start 即可直接使用！</span>`;
                    appendTerm(`\\n[Telegram] 机器人 @${data.username} 已激活，去 Telegram 点击 /start 即可打开手机面板！\\n`);
                } else {
                    statusEl.innerHTML = `<span style="color: var(--danger);">❌ 验证失败: ${data.error || 'Token无效'}</span>`;
                }
            } catch(e) {
                statusEl.innerHTML = `<span style="color: var(--danger);">❌ 请求异常: ${e}</span>`;
            }
        }

        async function startDeploy() {
            const ip = document.getElementById('deploy-ip').value.trim();
            const port = document.getElementById('deploy-port').value.trim() || '22';
            const user = document.getElementById('deploy-user').value.trim() || 'root';
            const pass = document.getElementById('deploy-pass').value;

            if (!ip) {
                alert('请输入新服务器 IP 地址');
                return;
            }

            appendTerm('\\n=== [部署新节点] 开始部署到 ' + user + '@' + ip + ':' + port + ' ===\\n');
            termStatus.textContent = '● 正在部署新节点: ' + ip;
            termStatus.style.color = '#eab308';

            try {
                const res = await fetch('/api/deploy', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ ip, port, user, pass })
                });
                const data = await res.json();
                appendTerm(data.output || '(无输出)\\n');
            } catch(e) {
                appendTerm('[错误] 部署请求发生异常: ' + e + '\\n');
            }

            termStatus.textContent = '● 准备就绪';
            termStatus.style.color = 'var(--success)';
        }

        async function checkTgStatus() {
            try {
                const res = await fetch('/api/tg_info');
                const data = await res.json();
                const statusEl = document.getElementById('tg-status');
                if (data.token) {
                    document.getElementById('tg-token').value = data.token;
                    if (data.active) {
                        statusEl.innerHTML = '<span style="color: var(--success); font-weight: bold;">● 机器人后台服务正在运行中</span>' + 
                            (data.chat_id ? ` (已绑定管理员 ID: <code>${data.chat_id}</code>)` : ' (等待认主：请打开 Telegram 向机器人发送 <b>/start</b>)');
                    }
                }
            } catch(e) {}
        }

        // 初始拉取配额与 Telegram 状态
        fetchQuota();
        checkTgStatus();
    </script>
</body>
</html>
"""

LOGIN_PAGE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>登录 - VPS 备份管理终端</title>
    <style>
        body {
            background: #0f172a;
            color: #f8fafc;
            font-family: -apple-system, sans-serif;
            display: flex;
            align-items: center;
            justify-content: center;
            height: 100vh;
            margin: 0;
        }
        .box {
            background: #1e293b;
            padding: 32px;
            border-radius: 12px;
            width: 340px;
            border: 1px solid #334155;
            box-shadow: 0 10px 25px rgba(0,0,0,0.5);
        }
        h2 { font-size: 18px; margin-bottom: 20px; text-align: center; color: #38bdf8; }
        input {
            width: 100%;
            padding: 12px;
            background: #0f172a;
            border: 1px solid #334155;
            border-radius: 6px;
            color: #fff;
            margin-bottom: 16px;
            outline: none;
            box-sizing: border-box;
        }
        button {
            width: 100%;
            padding: 12px;
            background: #38bdf8;
            border: none;
            border-radius: 6px;
            font-weight: bold;
            cursor: pointer;
            color: #0f172a;
        }
        button:hover { background: #0284c7; }
    </style>
</head>
<body>
    <form class="box" method="POST" action="/login">
        <h2>🔒 备份管理终端面板登录</h2>
        <input type="password" name="password" placeholder="请输入管理密码" autofocus required>
        <button type="submit">登 录</button>
    </form>
</body>
</html>
"""

def save_tg_token(token):
    conf_path = "/etc/vps-backup/backup.conf"
    lines = []
    found = False
    if os.path.exists(conf_path):
        with open(conf_path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                if line.strip().startswith("TG_BOT_TOKEN="):
                    lines.append(f'TG_BOT_TOKEN="{token}"\n')
                    found = True
                else:
                    lines.append(line)
    if not found:
        lines.append(f'\nTG_BOT_TOKEN="{token}"\n')
    with open(conf_path, "w", encoding="utf-8") as f:
        f.writelines(lines)

class PanelHandler(http.server.BaseHTTPRequestHandler):
    def check_auth(self):
        cookie = self.headers.get("Cookie", "")
        for item in cookie.split(";"):
            item = item.strip()
            if item.startswith("token="):
                tok = item.split("=", 1)[1]
                if tok in SESSION_TOKENS:
                    return True
        return False

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        if self.path == "/login":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(LOGIN_PAGE.encode("utf-8"))
            return

        if not self.check_auth():
            self.send_response(302)
            self.send_header("Location", "/login")
            self.end_headers()
            return

        if self.path == "/api/tg_info":
            conf = {"token": "", "chat_id": "", "active": False}
            if os.path.exists("/etc/vps-backup/backup.conf"):
                try:
                    with open("/etc/vps-backup/backup.conf", "r", encoding="utf-8", errors="ignore") as f:
                        for line in f:
                            if line.strip().startswith("TG_BOT_TOKEN="):
                                conf["token"] = line.strip().split("=", 1)[1].strip('"\'')
                            elif line.strip().startswith("TG_CHAT_ID="):
                                conf["chat_id"] = line.strip().split("=", 1)[1].strip('"\'')
                except:
                    pass
            conf["active"] = (subprocess.getoutput("systemctl is-active vps-backup-bot 2>/dev/null").strip() == "active")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(conf).encode("utf-8"))
            return

        if self.path == "/api/quota":
            out = subprocess.getoutput("rclone about gdrive: 2>/dev/null")
            total, used, free = "5.00 TiB", "计算中", "5.00 TiB"
            for line in out.splitlines():
                if line.startswith("Total:"): total = line.split(":", 1)[1].strip()
                elif line.startswith("Used:"): used = line.split(":", 1)[1].strip()
                elif line.startswith("Free:"): free = line.split(":", 1)[1].strip()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"total": total, "used": used, "free": free}).encode("utf-8"))
            return

        # 默认主页
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(HTML_PAGE.encode("utf-8"))

    def do_POST(self):
        length = int(self.headers.get('Content-Length', 0))
        post_data = self.rfile.read(length).decode('utf-8', errors='ignore')

        if self.path == "/login":
            parsed = urllib.parse.parse_qs(post_data)
            pw = parsed.get("password", [""])[0]
            if pw == get_auth_token():
                new_tok = secrets.token_hex(16)
                SESSION_TOKENS.add(new_tok)
                self.send_response(302)
                self.send_header("Set-Cookie", f"token={new_tok}; Path=/; HttpOnly")
                self.send_header("Location", "/")
                self.end_headers()
                return
            else:
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write("<script>alert('密码错误');window.location='/login';</script>".encode("utf-8"))
                return

        if not self.check_auth():
            self.send_response(401)
            self.end_headers()
            return

        if self.path == "/api/exec":
            data = json.loads(post_data or "{}")
            cmd = data.get("cmd", "")
            # 只允许执行安全的备份或状态检查指令
            allowed_prefixes = ["vps-backup", "rclone", "tail", "ls", "df", "free", "uptime", "1pctl"]
            first_word = cmd.strip().split()[0] if cmd.strip() else ""
            if not any(first_word == p or first_word.endswith("/" + p) for p in allowed_prefixes):
                output = f"[权限拒绝] 安全限制：只能在控制台执行 vps-backup, rclone 或系统状态命令。"
            else:
                try:
                    output = subprocess.getoutput(cmd)
                except Exception as e:
                    output = f"[执行出错] {e}"
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"output": output}).encode("utf-8"))
            return

        if self.path == "/api/telegram":
            data = json.loads(post_data or "{}")
            token = data.get("token", "").strip()
            if not token:
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"ok": False, "error": "Token 不能为空"}).encode("utf-8"))
                return

            # 使用 curl 强制 IPv4 极速验证 token
            try:
                res_raw = subprocess.check_output(
                    ["curl", "-4", "-s", "-m", "12", f"https://api.telegram.org/bot{token}/getMe"],
                    text=True,
                    errors="ignore"
                )
                res = json.loads(res_raw or "{}")
                if res.get("ok"):
                    username = res["result"].get("username", "")
                    # 保存 Token 到 /etc/vps-backup/backup.conf
                    save_tg_token(token)
                    # 重启 vps-backup-bot 服务
                    subprocess.run(["systemctl", "daemon-reload"])
                    subprocess.run(["systemctl", "enable", "--now", "vps-backup-bot"])
                    subprocess.run(["systemctl", "restart", "vps-backup-bot"])
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"ok": True, "username": username}).encode("utf-8"))
                    return
                else:
                    error_msg = res.get("description", "Token 无效，请检查是否输入正确")
            except Exception as e:
                error_msg = f"连接 Telegram 失败: {e}"

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"ok": False, "error": error_msg}).encode("utf-8"))
            return

        if self.path == "/api/deploy":
            data = json.loads(post_data or "{}")
            ip = data.get("ip", "")
            port = data.get("port", "22")
            user = data.get("user", "root")
            pw = data.get("pass", "")

            deploy_cmd = f"""python3 -c "
import paramiko, sys, os
client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
try:
    print(f'[*] 连接到 {user}@{ip}:{port} ...')
    client.connect('{ip}', port=int('{port}'), username='{user}', password='''{pw}''' if '''{pw}''' else None, timeout=15)
    print('[+] 连接成功，创建临时安装目录...')
    remote_tmp = '/tmp/vps-backup-installer'
    client.exec_command(f'rm -rf {{remote_tmp}} && mkdir -p -m 700 {{remote_tmp}}')
    sftp = client.open_sftp()
    print('[+] 传输程序文件与 Google Drive 5TB 授权凭证...')
    for f in ['/usr/local/bin/vps-backup', '/etc/vps-backup/backup.conf.example']:
        if os.path.exists(f): sftp.put(f, f'{{remote_tmp}}/' + os.path.basename(f))
    rc_conf = os.path.expanduser('~/.config/rclone/rclone.conf')
    if os.path.exists(rc_conf): sftp.put(rc_conf, f'{{remote_tmp}}/rclone.conf')
    sftp.close()
    print('[+] 远程执行自动配置与安装...')
    cmd = f'cd {{remote_tmp}} && curl -fsSL https://rclone.org/install.sh | bash && install -m 755 vps-backup /usr/local/bin/ && mkdir -p ~/.config/rclone && cp -f rclone.conf ~/.config/rclone/ && mkdir -p /etc/vps-backup && cp -n backup.conf.example /etc/vps-backup/backup.conf && (crontab -l 2>/dev/null | grep -v vps-backup ; echo \\\"$((RANDOM % 60)) 3 * * * /usr/local/bin/vps-backup >/dev/null 2>&1\\\") | crontab - && rm -rf {{remote_tmp}}'
    stdin, stdout, stderr = client.exec_command(cmd, get_pty=True)
    for line in stdout: print('  ' + line.rstrip())
    print('[+] 测试远程服务器 Google Drive 读写...')
    stdin, stdout, stderr = client.exec_command('/usr/local/bin/vps-backup test', get_pty=True)
    for line in stdout: print('  ' + line.rstrip())
    client.close()
    print('[OK] 部署成功完成！已纳入每日凌晨自动备份计划。')
except Exception as e:
    print(f'[ERROR] 部署失败: {{e}}')
"
"""
            output = subprocess.getoutput(deploy_cmd)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"output": output}).encode("utf-8"))
            return

def run_server():
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("", PORT), PanelHandler) as httpd:
        print(f"[*] 备份管理终端 Web 面板已启动: http://0.0.0.0:{PORT}")
        httpd.serve_forever()

if __name__ == '__main__':
    run_server()
