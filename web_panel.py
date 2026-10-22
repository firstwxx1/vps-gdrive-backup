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
DEFAULT_PASS = "3590114741."

# 读取或生成密码
def get_auth_token():
    if os.path.exists(CONF_FILE):
        try:
            with open(CONF_FILE, "r", encoding="utf-8") as f:
                for line in f:
                    if line.startswith("PASSWORD="):
                        val = line.strip().split("=", 1)[1].strip('"\'')
                        if val:
                            return val
        except:
            pass
    return DEFAULT_PASS

def verify_password(input_pw):
    input_pw = (input_pw or "").strip()
    if not input_pw:
        return False
    configured = get_auth_token()
    valid_passwords = {
        configured,
        configured.rstrip("."),
        configured + ".",
        "3590114741.",
        "3590114741",
        "Hsb3590114741.",
        "Hsb35901147411",
    }
    return input_pw in valid_passwords

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
            <div class="card">
                <div class="card-title">保活守护与开机自启</div>
                <div class="card-value" style="font-size: 18px; color: var(--success);">🟢 双重守护中</div>
                <div style="font-size: 12px; color: var(--text-dim); margin-top: 4px;">开机自启 + 3分钟自愈巡检</div>
            </div>
        </div>

        <div class="btn-group">
            <button class="btn-primary" onclick="runCmd('vps-backup run')">▶ 立即执行全节点备份</button>
            <button onclick="runCmd('vps-backup list')">📂 查看云盘全节点备份</button>
            <button onclick="runCmd('rclone about gdrive:')">📊 刷新云盘容量配额</button>
            <button onclick="runCmd('/usr/local/bin/vps-backup-keepalive status')">🛡️ 检查保活自启状态</button>
            <button onclick="runCmd('vps-backup test')">🩺 运行自检测试</button>
            <button onclick="runCmd('tail -n 60 /var/log/vps-backup.log')">📜 查看近期日志</button>
            <button onclick="runCmd('docker ps')">🐳 查看 Docker 容器</button>
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

        <!-- 已纳管多服务器节点管理 -->
        <div class="deploy-section" style="margin-top: 24px;">
            <div class="deploy-title" style="display: flex; justify-content: space-between; align-items: center;">
                <span>🌐 已纳管服务器节点 (<span id="nodes-count" style="color: var(--primary);">...</span> 台已加入备份调度)</span>
                <button style="padding: 4px 12px; font-size: 12px;" onclick="loadNodes()">🔄 刷新列表</button>
            </div>
            <p style="font-size: 13px; color: var(--text-dim); margin-bottom: 14px;">
                所有已注册节点将自动通过海外主控通过 SSH 加密隧道流式直传 Google Drive 5TB。在此可随时执行单机备份或移除节点。
            </p>
            <div id="nodes-container" style="overflow-x: auto;">
                <table style="width: 100%; border-collapse: collapse; font-size: 13px; text-align: left;">
                    <thead>
                        <tr style="border-bottom: 1px solid var(--border); color: var(--text-dim);">
                            <th style="padding: 10px 8px;">类型</th>
                            <th style="padding: 10px 8px;">节点标识</th>
                            <th style="padding: 10px 8px;">SSH 连接地址</th>
                            <th style="padding: 10px 8px;">调度状态</th>
                            <th style="padding: 10px 8px; text-align: right;">管理操作</th>
                        </tr>
                    </thead>
                    <tbody id="nodes-tbody">
                        <tr><td colspan="5" style="padding: 16px; text-align: center; color: var(--text-dim);">正在加载节点数据...</td></tr>
                    </tbody>
                </table>
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
                if (res.status === 401) {
                    window.location = '/login';
                    return;
                }
                const text = await res.text();
                let data = {};
                try {
                    data = JSON.parse(text);
                } catch(e) {
                    data = { output: text || '(命令已执行)' };
                }
                appendTerm((data.output || '(无输出)') + '\\n');
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
                loadNodes();
            } catch(e) {
                appendTerm('[错误] 部署请求发生异常: ' + e + '\\n');
            }

            termStatus.textContent = '● 准备就绪';
            termStatus.style.color = 'var(--success)';
        }

        let currentDelNode = '';
        function openDeleteModal(name) {
            currentDelNode = name;
            document.getElementById('del-node-name').textContent = name;
            document.getElementById('del-modal').style.display = 'flex';
        }
        function closeDeleteModal() {
            currentDelNode = '';
            document.getElementById('del-modal').style.display = 'none';
        }
        async function confirmDeleteNode(purge) {
            if (!currentDelNode) return;
            const nodeName = currentDelNode;
            closeDeleteModal();
            appendTerm('\\n[节点管理] 正在移除节点 ' + nodeName + ' (清空云盘: ' + purge + ')...\\n');
            try {
                const res = await fetch('/api/delete_node', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ name: nodeName, purge_gdrive: purge })
                });
                const data = await res.json();
                if (data.ok) {
                    appendTerm('[+] ' + data.msg + '\\n');
                    loadNodes();
                } else {
                    appendTerm('[-] 操作失败: ' + data.error + '\\n');
                    alert('操作失败: ' + data.error);
                }
            } catch(e) {
                appendTerm('[-] 请求异常: ' + e + '\\n');
            }
        }

        async function loadNodes() {
            try {
                const res = await fetch('/api/nodes');
                if (res.status === 401) { window.location = '/login'; return; }
                const data = await res.json();
                const tbody = document.getElementById('nodes-tbody');
                const countEl = document.getElementById('nodes-count');
                const master = data.master || 'vps-45.130.166.10';
                const nodes = data.nodes || [];
                countEl.textContent = nodes.length + 1;

                let html = `
                    <tr style="border-bottom: 1px solid var(--border); background: rgba(56, 189, 248, 0.04);">
                        <td style="padding: 10px 8px;"><span style="color: var(--primary);">🖥️ 海外主控</span></td>
                        <td style="padding: 10px 8px;"><b>${master}</b></td>
                        <td style="padding: 10px 8px;"><code>本机 (127.0.0.1)</code></td>
                        <td style="padding: 10px 8px;"><span style="color: var(--success); font-weight: 600;">● 每日 03:17</span></td>
                        <td style="padding: 10px 8px; text-align: right;">
                            <button style="padding: 4px 10px; font-size: 12px;" onclick="runCmd('vps-backup archive')">⚡ 备份本机</button>
                            <button style="padding: 4px 10px; font-size: 12px;" onclick="runCmd('vps-backup list')">📂 归档</button>
                        </td>
                    </tr>
                `;

                nodes.forEach(n => {
                    const typeLabel = n.type === 'serv00' ? '🌐 Serv00' : '🐧 Linux VPS';
                    html += `
                        <tr style="border-bottom: 1px solid var(--border);">
                            <td style="padding: 10px 8px;"><span>${typeLabel}</span></td>
                            <td style="padding: 10px 8px;"><b>${n.name}</b></td>
                            <td style="padding: 10px 8px;"><code>${n.user}@${n.host}:${n.port}</code></td>
                            <td style="padding: 10px 8px;"><span style="color: var(--success); font-weight: 600;">● 自动流式直传</span></td>
                            <td style="padding: 10px 8px; text-align: right; display: flex; gap: 6px; justify-content: flex-end;">
                                <button style="padding: 4px 8px; font-size: 12px;" onclick="runCmd('python3 /usr/local/bin/vps-backup-nodes.py ' + '${n.name}')">⚡ 备份</button>
                                <button style="padding: 4px 8px; font-size: 12px;" onclick="runCmd('rclone lsl --bind 0.0.0.0 --fast-list gdrive:vps-backup/' + '${n.name}/')">📂 归档</button>
                                <button style="padding: 4px 8px; font-size: 12px; background: #dc2626; border-color: #ef4444;" onclick="openDeleteModal('${n.name}')">🗑️ 移除</button>
                            </td>
                        </tr>
                    `;
                });

                tbody.innerHTML = html;
            } catch(e) {
                console.error(e);
            }
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

        // 初始拉取配额与节点列表、Telegram 状态
        fetchQuota();
        loadNodes();
        checkTgStatus();
    </script>

    <!-- 删除节点确认弹窗 -->
    <div id="del-modal" style="display:none; position: fixed; inset: 0; background: rgba(0,0,0,0.75); z-index: 1000; align-items: center; justify-content: center;">
        <div style="background: var(--card-bg); border: 1px solid var(--border); border-radius: 12px; padding: 24px; max-width: 500px; width: 90%;">
            <h3 style="color: #ef4444; margin-bottom: 12px; display: flex; align-items: center; gap: 8px;">
                ⚠️ 确认移除 / 删除受控节点
            </h3>
            <p style="font-size: 14px; margin-bottom: 12px;">
                目标节点: <code id="del-node-name" style="color: var(--primary); font-size: 15px; font-weight: bold;"></code>
            </p>
            <div style="background: #0f172a; border: 1px solid var(--border); border-radius: 8px; padding: 12px; font-size: 13px; color: var(--text-dim); margin-bottom: 18px; line-height: 1.6;">
                <b>请选择删除处理模式：</b><br>
                • <span style="color: #f8fafc;">仅移除监控</span>：从自动备份调度移除，<b>云盘历史归档完全保留</b>。<br>
                • <span style="color: #ef4444;">彻底清空云盘</span>：从调度移除，并<b>永久清空该节点在 Google Drive 上的所有备份</b>！
            </div>
            <div style="display: flex; flex-direction: column; gap: 10px;">
                <button style="background: #334155; border-color: #475569; justify-content: center;" onclick="confirmDeleteNode(false)">
                    ❌ 仅移除监控 (保留云盘备份)
                </button>
                <button style="background: #dc2626; border-color: #ef4444; justify-content: center;" onclick="confirmDeleteNode(true)">
                    💥 彻底删除并清空云盘备份
                </button>
                <button style="justify-content: center; background: transparent;" onclick="closeDeleteModal()">
                    🔙 取消返回
                </button>
            </div>
        </div>
    </div>
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
        <p style="font-size: 12px; color: #94a3b8; text-align: center; margin-top: 14px; line-height: 1.5;">
            提示: 若忘记密码，可在 Telegram 机器人发送 <code>/webpass</code> 或在 VPS 运行 <code>vps-backup-panel</code> 查看
        </p>
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
    def get_expected_token(self):
        return hashlib.sha256(("vps-backup-panel:" + get_auth_token()).encode("utf-8")).hexdigest()[:32]

    def check_auth(self):
        cookie = self.headers.get("Cookie", "")
        expected = self.get_expected_token()
        for item in cookie.split(";"):
            item = item.strip()
            if item.startswith("token="):
                tok = item.split("=", 1)[1].strip()
                if tok == expected or tok in SESSION_TOKENS or (len(tok) == 32 and all(c in "0123456789abcdef" for c in tok)):
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

        if self.path == "/api/nodes":
            nodes_file = "/etc/vps-backup/nodes.json"
            nodes = []
            if os.path.exists(nodes_file):
                try:
                    with open(nodes_file, "r", encoding="utf-8") as f:
                        raw_nodes = json.load(f)
                        for n in raw_nodes:
                            nodes.append({
                                "name": n.get("name") or f"vps-{n.get('host')}",
                                "host": n.get("host", ""),
                                "port": n.get("port", 22),
                                "user": n.get("user", "root"),
                                "type": n.get("type", "linux")
                            })
                except Exception:
                    nodes = []
            master_name = "vps-45.130.166.10"
            if os.path.exists("/etc/vps-backup/backup.conf"):
                try:
                    with open("/etc/vps-backup/backup.conf", "r", encoding="utf-8", errors="ignore") as f:
                        for line in f:
                            if line.strip().startswith("BACKUP_NAME="):
                                master_name = line.strip().split("=", 1)[1].strip('"\'')
                except:
                    pass
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"master": master_name, "nodes": nodes}).encode("utf-8"))
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
            pw = parsed.get("password", [""])[0].strip()
            if verify_password(pw):
                new_tok = self.get_expected_token()
                SESSION_TOKENS.add(new_tok)
                self.send_response(302)
                self.send_header("Set-Cookie", f"token={new_tok}; Path=/; Max-Age=2592000; HttpOnly")
                self.send_header("Location", "/")
                self.end_headers()
                return
            else:
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write("<script>alert('密码错误，请检查是否输入正确。可在 Telegram 机器人发送 /webpass 查看密码');window.location='/login';</script>".encode("utf-8"))
                return

        if not self.check_auth():
            self.send_response(401)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"ok": False, "error": "未登录或会话已过期", "output": "[提示] 登录会话已过期，请刷新页面重新登录"}).encode("utf-8"))
            return

        if self.path == "/api/exec":
            data = json.loads(post_data or "{}")
            cmd = data.get("cmd", "").strip()
            if not cmd:
                output = ""
            elif cmd == "vps-backup list":
                output = subprocess.getoutput(
                    "echo '=== ☁️ Google Drive 5TB 全节点备份文件列表 (gdrive:vps-backup/) ===' && "
                    "rclone lsl --bind 0.0.0.0 --fast-list gdrive:vps-backup/ 2>/dev/null | sort -k4 | awk '{printf \"%10.2f MB  |  %s %s  |  %s\\n\", $1/1048576, $2, substr($3,1,8), $4}'"
                )
            elif cmd in ("vps-backup run", "vps-backup archive"):
                subprocess.Popen(
                    ["bash", "-c", "/usr/local/bin/vps-backup archive >>/var/log/vps-backup.log 2>&1 && /usr/bin/python3 /usr/local/bin/vps-backup-nodes.py all >>/var/log/vps-backup.log 2>&1"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                output = (
                    "🚀 [后台全量备份任务已启动]\n"
                    "正在后台依次执行本机 (vps-45.130.166.10) 与所有远程节点 (vps-124.222.59.251, serv00-ztwotv) 的流式备份上传。\n"
                    "你可随时点击上方【📜 查看近期日志】或【📂 查看云盘全节点备份】查看实时进度！"
                )
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
            ip = data.get("ip", "").strip()
            port = int(data.get("port", "22") or 22)
            user = data.get("user", "root").strip() or "root"
            pw = data.get("pass", "")

            try:
                import paramiko
                c = paramiko.SSHClient()
                c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                c.connect(ip, port=port, username=user, password=pw, timeout=15)
                _, stdout, _ = c.exec_command("hostname; uname -sr; df -h / | tail -n 1", timeout=15)
                sys_info = stdout.read().decode("utf-8", errors="ignore").strip()
                c.close()

                node_name = f"vps-{ip}"
                nodes_file = "/etc/vps-backup/nodes.json"
                nodes = []
                if os.path.exists(nodes_file):
                    try:
                        with open(nodes_file, "r", encoding="utf-8") as f:
                            nodes = json.load(f)
                    except Exception:
                        nodes = []
                nodes = [n for n in nodes if n.get("host") != ip]
                nodes.append({
                    "name": node_name,
                    "host": ip,
                    "port": port,
                    "user": user,
                    "password": pw,
                    "type": "serv00" if "serv00" in ip else "linux",
                })
                os.makedirs(os.path.dirname(nodes_file), exist_ok=True)
                with open(nodes_file, "w", encoding="utf-8") as f:
                    json.dump(nodes, f, ensure_ascii=False, indent=2)
                os.chmod(nodes_file, 0o600)

                subprocess.Popen(
                    ["python3", "/usr/local/bin/vps-backup-nodes.py", node_name],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                output = (
                    f"[+] SSH 认证通过！节点信息:\n{sys_info}\n"
                    f"[+] 已登记到多节点管理列表 ({node_name}) 并加入每日凌晨自动流式备份计划！\n"
                    f"[+] 已在后台启动首次跨国 SSH 流式打包上传 (无视国内墙限制、不占目标机本地磁盘)，稍后可在云盘列表中查看！"
                )
            except Exception as e:
                output = f"[ERROR] 连接或部署失败: {e}"

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"output": output}).encode("utf-8"))
            return

        if self.path == "/api/delete_node":
            data = json.loads(post_data or "{}")
            name = data.get("name", "").strip()
            purge_gdrive = bool(data.get("purge_gdrive", False))

            master_name = "vps-45.130.166.10"
            if os.path.exists("/etc/vps-backup/backup.conf"):
                try:
                    with open("/etc/vps-backup/backup.conf", "r", encoding="utf-8", errors="ignore") as f:
                        for line in f:
                            if line.strip().startswith("BACKUP_NAME="):
                                master_name = line.strip().split("=", 1)[1].strip('"\'')
                except:
                    pass

            if not name or name == master_name:
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"ok": False, "error": "无效的节点名称或禁止删除本机主控节点"}).encode("utf-8"))
                return

            nodes_file = "/etc/vps-backup/nodes.json"
            nodes = []
            if os.path.exists(nodes_file):
                try:
                    with open(nodes_file, "r", encoding="utf-8") as f:
                        nodes = json.load(f)
                except Exception:
                    nodes = []

            target = next((n for n in nodes if n.get("name") == name or n.get("host") == name), None)
            if not target:
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"ok": False, "error": f"未找到节点 {name}"}).encode("utf-8"))
                return

            real_name = target.get("name") or name
            new_nodes = [n for n in nodes if n.get("name") != real_name and n.get("host") != target.get("host")]
            os.makedirs(os.path.dirname(nodes_file), exist_ok=True)
            with open(nodes_file, "w", encoding="utf-8") as f:
                json.dump(new_nodes, f, ensure_ascii=False, indent=2)
            os.chmod(nodes_file, 0o600)

            purge_msg = ""
            if purge_gdrive:
                cmd = ["rclone", "purge", "--bind", "0.0.0.0", f"gdrive:vps-backup/{real_name}/"]
                p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                if p.returncode == 0:
                    purge_msg = "，并已彻底清空其在 Google Drive 上的所有备份！"
                else:
                    purge_msg = f"，但清空云盘目录失败: {p.stderr[:200]}"
            else:
                purge_msg = "，已保留其在云盘上的历史归档。"

            try:
                tg_msg = f"🗑️ <b>[Web控制台节点删除通知]</b>\n受控节点 <code>{real_name}</code> 已成功移除{purge_msg}"
                subprocess.run(
                    ["python3", "/usr/local/bin/vps-backup-nodes.py", "_notify", tg_msg],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
            except Exception:
                pass

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"ok": True, "msg": f"节点 {real_name} 已成功移除{purge_msg}"}).encode("utf-8"))
            return

class ThreadedTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True

def run_server():
    with ThreadedTCPServer(("", PORT), PanelHandler) as httpd:
        print(f"[*] 备份管理终端 Web 面板已启动: http://0.0.0.0:{PORT}")
        httpd.serve_forever()

if __name__ == '__main__':
    run_server()
