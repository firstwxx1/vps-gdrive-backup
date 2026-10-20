import os
import sys
import subprocess
import re
import webbrowser

DIR = os.path.dirname(os.path.abspath(__file__))
RCLONE_EXE = os.path.join(DIR, "rclone.exe")
RCLONE_CONF = os.path.join(DIR, "rclone.conf")

print("=" * 60)
print("     Google Drive 5TB 云盘一键授权 (rclone)")
print("=" * 60)
print("\n[*] 正在启动 Google 授权服务...")
print("[*] 系统将自动打开浏览器，请在网页中登录拥有 5TB 的 Google 账号并点击【允许】。")
print("[*] 授权成功后页面会显示 Success!，请勿关闭本窗口...\n")

try:
    # 启动 rclone authorize drive
    proc = subprocess.Popen(
        [RCLONE_EXE, "authorize", "drive"],
        cwd=DIR,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="ignore"
    )
    
    output = []
    opened_browser = False
    while True:
        line = proc.stdout.readline()
        if not line and proc.poll() is not None:
            break
        if line:
            output.append(line)
            # 自动提取链接并在浏览器中打开
            m_url = re.search(r'(http://127\.0\.0\.1:53682/auth\S*)', line)
            if m_url and not opened_browser:
                url = m_url.group(1)
                print(f"[+] 正在自动打开授权网址：\n{url}\n")
                webbrowser.open(url)
                opened_browser = True
            elif "http" in line:
                print(line.strip())
                
    proc.wait()
    full_output = "".join(output)
    
    # 提取 token
    m = re.search(r'\{[\s\S]*\"access_token\"[\s\S]*\}', full_output)
    if m:
        token = m.group(0).strip()
        conf_content = f"[gdrive]\ntype = drive\nscope = drive\ntoken = {token}\n"
        with open(RCLONE_CONF, "w", encoding="utf-8") as f:
            f.write(conf_content)
        print("\n" + "=" * 60)
        print("  【成功】Google Drive 授权完成！")
        print(f"  配置文件已生成: {RCLONE_CONF}")
        print("=" * 60)
        print("\n现在可以回到 AI 对话框，回复【已完成】即可！")
    else:
        print("\n[!] 未能获取到授权 Token，输出日志：")
        print(full_output)
        
except Exception as e:
    print(f"\n[ERROR] 发生异常: {e}")

input("\n按回车键退出...")
