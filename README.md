# vps-backup — VPS 自动备份到 Google Drive

基于 [rclone](https://rclone.org) 的 Bash 备份系统，支持将多台不同系统的 VPS 自动定时打包/同步备份到 Google Drive 5TB 云盘，并自带 Web 浏览器与 SSH 双终端管理面板。

## ⚡ 一键安装 (推荐)

在任何 Linux VPS（Ubuntu / Debian / CentOS / Rocky / Alma / Alpine / Arch / openSUSE）上以 root 身份执行：

```bash
curl -fsSL https://raw.githubusercontent.com/firstwxx1/vps-gdrive-backup/main/quick-install.sh | bash
```
> 或使用 wget：`wget -qO- https://raw.githubusercontent.com/firstwxx1/vps-gdrive-backup/main/quick-install.sh | bash`

安装脚本将自动完成：
- 系统环境与核心依赖（curl, tar, zstd, openssl, cron, python3）自动安装
- 最新版 rclone 自动检测与安装
- 部署 Web 浏览器可视化终端面板（端口 `8999`，开机自启）
- 部署 SSH 交互式彩色菜单命令：`backup-panel`
- 设定每日凌晨自动错峰备份计划任务

---

| 功能 | 说明 |
|---|---|
| 归档备份 | tar 打包 + zstd/gzip 压缩 + 可选 AES-256 加密，按 **日 / 周 / 月** 保留，过期的自动删除 |
| 增量同步 | `rclone sync` 镜像目录，只传变化的文件；被改/删的旧文件按日期保留到 `history` |
| 数据库 | MySQL/MariaDB、PostgreSQL、Docker 容器中的 MySQL/MariaDB/PostgreSQL 自动热备份 |
| 终端面板 | **Web 可视化控制台 (端口 8999)** + **SSH 交互式彩色菜单 (`vps-backup-panel`)** |
| 节点部署 | 支持从面板一键推送 5TB 授权到新 VPS / 服务器，批量纳入每日自动备份 |
| 通知 | Telegram，失败一定通知，成功可选 |
| 多机 | 每台 VPS 放在单独目录；`deploy.sh` 批量部署；定时任务时间随机错开 |
| 系统 | Debian/Ubuntu、CentOS/RHEL/Rocky/Alma/Fedora、Alpine、Arch、openSUSE、FreeBSD(Serv00) |

## 云盘目录结构

```
gdrive:vps-backup/
├── hk-01/
│   ├── archive/
│   │   ├── daily/    hk-01_20261020-030512.tar.zst.enc   (保留 7 天)
│   │   ├── weekly/   每周一份                             (保留 28 天)
│   │   └── monthly/  每月一份                             (保留 180 天)
│   └── sync/
│       ├── current/var/www/...        与 VPS 一致的最新文件
│       └── history/20261020-030512/   当次被修改/删除的旧版本 (保留 30 天)
└── us-02/
    └── ...
```

---

## 第一步：授权 Google Drive（只需做一次，所有 VPS 共用）

在**自己的 Windows 电脑**上操作最简单（有浏览器）：

1. 下载 rclone：<https://rclone.org/downloads/>，解压后在该目录打开 PowerShell。
2. *（强烈建议）* 创建自己的 Google API Client ID，避免 rclone 公共 ID 限速：
   1. 打开 <https://console.cloud.google.com/>，新建项目 → 「API 和服务」→ 启用 **Google Drive API**
   2. 「OAuth 同意屏幕」→ 用户类型选「外部」→ 填好必填项 → **发布应用（设为“正式版 / In production”）**
   3. 「凭据」→ 创建凭据 → OAuth 客户端 ID → 应用类型选 **桌面应用** → 记下 Client ID 和 Secret

   > ⚠️ 同意屏幕如果停留在「测试」状态，授权 **7 天后就会失效**，备份会突然全部失败。一定要发布。
3. 运行 `.\rclone.exe config`：
   - `n` 新建 → 名称填 **`gdrive`** → 类型选 **drive**
   - client_id / client_secret 填上一步的（没有就直接回车）
   - scope 选 `1`（drive，完整权限）
   - 其余一路回车，`Use web browser to automatically authenticate?` 选 `y`，在浏览器里登录你的 Google 账号授权
   - `Configure this as a Shared Drive?` 选 `n`（除非你用的是共享云端硬盘）
4. 运行 `.\rclone.exe config file` 找到 `rclone.conf`（通常在 `C:\Users\你\AppData\Roaming\rclone\rclone.conf`），
   把它复制到本项目目录。**这个文件等于你云盘的钥匙，不要泄露。**

> 如果只想在 VPS 上直接配：在 VPS 运行 `rclone config`，到浏览器那步选 `n`，它会给出一条 `rclone authorize ...` 命令，
> 在电脑上运行后把得到的 token 粘回 VPS 即可。

---

## 第二步：安装到 VPS

### 方式 A：单台安装

```bash
# 把本目录上传到 VPS（例如 scp -r vps-gdrive-backup root@IP:/root/），然后：
cd /root/vps-gdrive-backup
bash install.sh --rclone-conf ./rclone.conf     # 已经在 VPS 上配好 rclone 就去掉这个参数

nano /etc/vps-backup/backup.conf                # 修改要备份的目录、数据库、Telegram 等
vps-backup test                                 # 测试云盘读写 + Telegram
vps-backup run                                  # 立即执行一次
```

### 方式 B：多台批量部署

在任意一台 Linux / macOS / WSL / Git Bash（能 ssh 到各 VPS）上：

```bash
cd vps-gdrive-backup
cp backup.conf.example backup.conf    # 编辑为通用配置
# 可选：某台机器的专用配置放 configs/<主机>.conf，例如 configs/1.2.3.4.conf
cat > hosts.txt <<EOF
root@1.2.3.4
root@hk.example.com:2222
ubuntu@5.6.7.8
EOF
bash deploy.sh hosts.txt              # 需已配置 SSH 密钥登录
```

每台 VPS 默认用 **主机名** 作为云盘上的目录名。若多台 VPS 主机名相同（如都叫 `localhost`），
请用 `configs/<主机>.conf` 为它们分别设置 `BACKUP_NAME`，否则会互相覆盖/清理。

### 安装参数

| 参数 | 说明 |
|---|---|
| `--hour N` | 每天几点运行，默认 3（VPS 本地时区） |
| `--minute N` | 第几分钟，默认随机，多台 VPS 自动错峰 |
| `--config FILE` | 安装指定配置（旧配置自动备份为 `.bak.时间`） |
| `--rclone-conf FILE` | 安装 rclone 授权文件 |
| `--no-cron` | 不创建定时任务 |
| `--uninstall` | 卸载脚本和定时任务（保留配置与云盘数据） |

---

## 常用命令

```bash
vps-backup run         # 按配置完整备份（定时任务执行的就是这个）
vps-backup archive     # 只做归档（含数据库）
vps-backup sync        # 只做增量同步
vps-backup list        # 查看本机在云盘上的备份 & 所有主机
vps-backup test        # 自检
tail -f /var/log/vps-backup.log
```

## 恢复

```bash
vps-backup list
# 恢复本机的某个备份到 /root/vps-restore（不会直接覆盖系统文件）
vps-backup restore hk-01_20261020-030512.tar.zst.enc /root/vps-restore
# 在新机器上恢复其他主机的备份
vps-backup restore hk-01/archive/monthly/hk-01_20261001-031000.tar.zst.enc /root/restore-hk01
```

恢复后：
- 文件在 `/root/vps-restore/etc/...`、`/root/vps-restore/var/www/...`，确认后再手动复制回去
- 数据库在 `/root/vps-restore/_databases/`：
  ```bash
  zcat mysql-mydb.sql.gz | mysql                       # MySQL（文件里自带 CREATE DATABASE）
  zcat pg-globals.sql.gz | su postgres -c psql          # PostgreSQL 角色
  su postgres -c "pg_restore -C -d postgres /root/vps-restore/_databases/pg-mydb.dump"
  zcat docker-mysql-mysql.sql.gz | docker exec -i mysql sh -c 'mysql -uroot -p"$MYSQL_ROOT_PASSWORD"'
  ```
- 同步模式的文件直接 `rclone copy gdrive:vps-backup/hk-01/sync/current/var/www /var/www` 即可

在电脑上手动解密（不用脚本）：
```bash
rclone cat gdrive:vps-backup/hk-01/archive/daily/xxx.tar.zst.enc \
  | openssl enc -d -aes-256-cbc -pbkdf2 -iter 100000 -md sha256 -pass pass:你的密码 \
  | zstd -dc | tar -xf -
```

---

## 注意事项

- **Google Drive 每个账号每天上传上限约 750 GB**。达到后脚本会停止上传并报错（`--drive-stop-on-upload-limit`），第二天自动恢复。
  多台 VPS 共用一个账号时注意总量；首次同步大目录可以分几天进行。
- **中国大陆 VPS 无法直连 Google**，需要自行配置代理（rclone 支持 `HTTPS_PROXY` 环境变量，可写在配置文件里 `export HTTPS_PROXY=...`）。
- **加密密码一旦丢失无法恢复**。建议把 `ENCRYPT_PASSWORD` 存到密码管理器里。
- 归档模式默认先在 `TMP_DIR` 生成压缩包再上传，需要足够的磁盘空间；硬盘小的 VPS 设置 `STREAM_UPLOAD="true"`。
- 清理旧备份只在**本次上传成功后**执行，所以即使连续多天失败也不会把老备份删光。
- 数据库请使用导出（`MYSQL_ENABLED` / `DOCKER_*`），直接打包 `/var/lib/mysql` 得到的文件可能不一致。
- 同步模式的文件默认不加密；需要加密可在 rclone 中创建 `crypt` 类型远端包住 `gdrive:`，然后把 `RCLONE_REMOTE` 改为该远端名。

## 文件说明

| 文件 | 作用 |
|---|---|
| `vps-backup.sh` | 主程序，安装为 `/usr/local/bin/vps-backup` |
| `backup.conf.example` | 配置模板（含详细注释），安装为 `/etc/vps-backup/backup.conf` |
| `install.sh` | 安装依赖、rclone、脚本、配置和定时任务 |
| `deploy.sh` | 通过 SSH 批量部署到多台 VPS |
