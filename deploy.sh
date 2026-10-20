#!/usr/bin/env bash
#
# 批量部署 vps-backup 到多台 VPS（在任意 Linux / macOS / WSL / Git Bash 上运行）
#
# 用法: bash deploy.sh [hosts.txt]
#
# hosts.txt 每行一台：  user@host[:port]     # 开头为注释
#   root@1.2.3.4
#   root@hk.example.com:2222
#
# 本目录下的可选文件：
#   rclone.conf              —— Google Drive 授权，会安装到每台 VPS（强烈建议提供）
#   backup.conf              —— 所有 VPS 共用的配置
#   configs/<host>.conf      —— 某台 VPS 的专用配置（优先于 backup.conf，<host> 为 hosts.txt 里 @ 后面的主机部分）
# 都不提供时，VPS 上使用默认配置（已有配置则保留）
#
# 额外的 install.sh 参数可通过环境变量传入，例如：INSTALL_ARGS="--hour 4" bash deploy.sh
#
set -o pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HOSTS_FILE="${1:-$DIR/hosts.txt}"
REMOTE_TMP="/tmp/vps-backup-installer"
[ -f "$HOSTS_FILE" ] || { echo "找不到 $HOSTS_FILE"; exit 1; }

ok_list=(); fail_list=()

while IFS= read -r line <&3; do
    line="${line%%#*}"; line="$(echo "$line" | tr -d '[:space:]')"
    [ -z "$line" ] && continue

    target="${line%:*}"; port=22
    [[ "$line" == *:* ]] && port="${line##*:}"
    user="${target%@*}"; host="${target#*@}"
    [ "$user" = "$target" ] && user="root"
    sudo=""; [ "$user" != "root" ] && sudo="sudo"

    echo; echo "================ $user@$host:$port ================"
    files=("$DIR/vps-backup.sh" "$DIR/install.sh" "$DIR/backup.conf.example")
    args="$INSTALL_ARGS"
    [ -f "$DIR/rclone.conf" ] && { files+=("$DIR/rclone.conf"); args+=" --rclone-conf $REMOTE_TMP/rclone.conf"; }
    conf=""
    if [ -f "$DIR/configs/$host.conf" ]; then conf="$DIR/configs/$host.conf"
    elif [ -f "$DIR/backup.conf" ]; then conf="$DIR/backup.conf"; fi
    if [ -n "$conf" ]; then
        files+=("$conf"); args+=" --config $REMOTE_TMP/$(basename "$conf")"
        echo "使用配置: $conf"
    fi

    if ssh -p "$port" -o ConnectTimeout=15 "$user@$host" "rm -rf $REMOTE_TMP && mkdir -p -m 700 $REMOTE_TMP" < /dev/null \
        && scp -q -P "$port" "${files[@]}" "$user@$host:$REMOTE_TMP/" < /dev/null \
        && ssh -p "$port" "$user@$host" "$sudo bash $REMOTE_TMP/install.sh $args; r=\$?; rm -rf $REMOTE_TMP; [ \$r -eq 0 ] && $sudo /usr/local/bin/vps-backup test" < /dev/null; then
        ok_list+=("$host")
    else
        fail_list+=("$host")
    fi
done 3< "$HOSTS_FILE"

echo; echo "================ 部署结果 ================"
echo "成功 (${#ok_list[@]}): ${ok_list[*]}"
echo "失败 (${#fail_list[@]}): ${fail_list[*]}"
[ "${#fail_list[@]}" -eq 0 ]
