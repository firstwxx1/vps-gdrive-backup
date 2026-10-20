#!/usr/bin/env bash
#
# vps-backup —— 把 VPS 自动备份到 Google Drive（基于 rclone）
#
# 功能：
#   * 归档模式：tar 打包 + 压缩(zstd/gzip) + 可选 AES-256 加密 → 上传，按 日/周/月 保留并自动清理
#   * 同步模式：rclone 增量同步目录到云盘，被修改/删除的旧文件按日期保留到 history 目录
#   * 数据库：MySQL/MariaDB、PostgreSQL、Docker 容器内的 MySQL/MariaDB/PostgreSQL
#   * Telegram 通知（失败必通知，成功可选）
#
# 用法：vps-backup [run|archive|sync|list|restore|test|help]
#
set -o pipefail
umask 077
export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:$PATH"

VERSION="1.0.0"
CONFIG_FILE="${VPS_BACKUP_CONFIG:-/etc/vps-backup/backup.conf}"
LOCK_DIR="/tmp/vps-backup.lock"

# ============================ 默认配置（会被配置文件覆盖） ============================
RCLONE_REMOTE="gdrive"
REMOTE_BASE="vps-backup"
BACKUP_NAME=""
RCLONE_CONFIG_FILE=""
RCLONE_EXTRA_FLAGS=""
BWLIMIT=""
DRIVE_USE_TRASH="false"

ARCHIVE_ENABLED="true"
ARCHIVE_PATHS=(/etc /root /home)
ARCHIVE_EXCLUDES=()
COMPRESSION="auto"
COMPRESS_LEVEL=""
ENCRYPT_PASSWORD=""
STREAM_UPLOAD="false"
KEEP_DAILY_DAYS=7
KEEP_WEEKLY_DAYS=28
KEEP_MONTHLY_DAYS=180

SYNC_ENABLED="false"
SYNC_PATHS=()
SYNC_EXCLUDES=()
SYNC_TRANSFERS=4
SYNC_KEEP_HISTORY_DAYS=30

MYSQL_ENABLED="false"
MYSQL_HOST=""
MYSQL_PORT=""
MYSQL_USER=""
MYSQL_PASSWORD=""
MYSQL_DATABASES="all"

PG_ENABLED="false"
PG_USER="postgres"
PG_DATABASES="all"

DOCKER_MYSQL_CONTAINERS=()
DOCKER_PG_CONTAINERS=()

PRE_HOOK=""
POST_HOOK=""

TMP_DIR="/var/tmp"
LOG_FILE="/var/log/vps-backup.log"

TG_BOT_TOKEN=""
TG_CHAT_ID=""
TG_API="https://api.telegram.org"
NOTIFY_ON_SUCCESS="false"

# ============================ 运行时状态 ============================
ERRORS=()
WARNINGS=()
ARCHIVE_RESULT=""
SYNC_RESULT=""
WORK_DIR=""
LOCK_HELD=0
FINISHED=0
START_TS=$(date +%s)

# ============================ 工具函数 ============================
ts()   { date '+%Y-%m-%d %H:%M:%S'; }
log()  { local line="[$(ts)] $*"; echo "$line"; echo "$line" >> "$LOG_FILE" 2>/dev/null; return 0; }
warn() { log "WARN: $*"; WARNINGS+=("$*"); }
err()  { log "ERROR: $*"; ERRORS+=("$*"); }

is_true() { case "${1,,}" in true|yes|y|1|on) return 0 ;; esac; return 1; }

human_size() {
    awk -v b="${1:-0}" 'BEGIN{split("B KB MB GB TB PB",u," ");i=1;while(b>=1024&&i<6){b/=1024;i++}
        if(i==1)printf "%d %s",b,u[i];else printf "%.2f %s",b,u[i]}'
}

fmt_duration() { local s=$1; printf '%dh%02dm%02ds' $((s / 3600)) $((s % 3600 / 60)) $((s % 60)); }

rc() { rclone "${RCLONE_FLAGS[@]}" "$@"; }

# 远端路径是否存在（文件或目录）
remote_exists() { [ -n "$(rc lsf --max-depth 1 "$1" 2>/dev/null | head -n 1)" ]; }

rotate_log() {
    [ -f "$LOG_FILE" ] || return 0
    local sz
    sz=$(wc -c < "$LOG_FILE" 2>/dev/null || echo 0)
    if [ "${sz:-0}" -gt 10485760 ]; then mv -f "$LOG_FILE" "$LOG_FILE.1"; fi
}

tg_send() {
    [ -n "$TG_BOT_TOKEN" ] && [ -n "$TG_CHAT_ID" ] || return 0
    local text="$1"
    [ "${#text}" -gt 4000 ] && text="${text:0:4000}..."
    curl -fsS -m 30 -X POST "${TG_API%/}/bot${TG_BOT_TOKEN}/sendMessage" \
        --data-urlencode "chat_id=${TG_CHAT_ID}" \
        --data-urlencode "text=${text}" \
        -d "disable_web_page_preview=true" > /dev/null
}

usage() {
    cat <<EOF
vps-backup v$VERSION —— VPS 自动备份到 Google Drive

用法: vps-backup [命令]

命令:
  run                 按配置执行全部备份（默认，定时任务调用的就是它）
  archive             只执行归档备份（含数据库导出），忽略 ARCHIVE_ENABLED
  sync                只执行目录同步，忽略 SYNC_ENABLED
  list                列出云盘上本机的备份，以及所有主机目录
  restore <文件> [目录] 下载并解压归档到目录（默认 /root/vps-restore）
                      <文件> 可以是本机备份文件名，或 "主机名/archive/daily/文件名"
  test                检查依赖、测试云盘读写、发送 Telegram 测试消息
  help                显示帮助

配置文件: $CONFIG_FILE （可用环境变量 VPS_BACKUP_CONFIG 指定）
EOF
}

# ============================ 配置加载 ============================
load_config() {
    if [ ! -f "$CONFIG_FILE" ]; then
        echo "找不到配置文件: $CONFIG_FILE （可用环境变量 VPS_BACKUP_CONFIG 指定）" >&2
        exit 1
    fi
    # shellcheck source=/dev/null
    . "$CONFIG_FILE" || { echo "配置文件加载失败: $CONFIG_FILE" >&2; exit 1; }

    [ -n "$LOG_FILE" ] || LOG_FILE="/dev/null"
    mkdir -p "$(dirname "$LOG_FILE")" 2>/dev/null

    RCLONE_REMOTE="${RCLONE_REMOTE%:}"
    REMOTE_BASE="${REMOTE_BASE#/}"; REMOTE_BASE="${REMOTE_BASE%/}"
    [ -n "$REMOTE_BASE" ] || REMOTE_BASE="vps-backup"
    [ -n "$BACKUP_NAME" ] || BACKUP_NAME="$(hostname -s 2>/dev/null || hostname)"
    REMOTE_TOP="${RCLONE_REMOTE}:${REMOTE_BASE}"
    REMOTE_ROOT="${REMOTE_TOP}/${BACKUP_NAME}"

    local v
    for v in KEEP_DAILY_DAYS KEEP_WEEKLY_DAYS KEEP_MONTHLY_DAYS SYNC_KEEP_HISTORY_DAYS SYNC_TRANSFERS; do
        [[ "${!v}" =~ ^[0-9]+$ ]] || { echo "配置错误: $v 必须是非负整数" >&2; exit 1; }
    done
    [ "$KEEP_DAILY_DAYS" -ge 1 ] || { echo "配置错误: KEEP_DAILY_DAYS 至少为 1" >&2; exit 1; }

    RCLONE_FLAGS=(--retries 5 --low-level-retries 20 --log-level NOTICE
        --drive-chunk-size 64M --drive-stop-on-upload-limit "--drive-use-trash=${DRIVE_USE_TRASH}")
    [ "$LOG_FILE" != "/dev/null" ] && RCLONE_FLAGS+=(--log-file "$LOG_FILE")
    [ -n "$RCLONE_CONFIG_FILE" ] && RCLONE_FLAGS+=(--config "$RCLONE_CONFIG_FILE")
    [ -n "$BWLIMIT" ] && RCLONE_FLAGS+=(--bwlimit "$BWLIMIT")
    if [ -n "$RCLONE_EXTRA_FLAGS" ]; then
        local extra
        read -r -a extra <<< "$RCLONE_EXTRA_FLAGS"
        RCLONE_FLAGS+=("${extra[@]}")
    fi
}

# ============================ 锁 / 清理 / 结束 ============================
acquire_lock() {
    if mkdir "$LOCK_DIR" 2>/dev/null; then
        echo $$ > "$LOCK_DIR/pid"; LOCK_HELD=1; return 0
    fi
    local pid
    pid=$(cat "$LOCK_DIR/pid" 2>/dev/null)
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
        log "上一次备份仍在运行 (PID $pid)，本次跳过"
        tg_send "⚠️ VPS 备份跳过
主机: $BACKUP_NAME
原因: 上一次备份仍在运行 (PID $pid)，请检查是否卡住" || true
        exit 1
    fi
    rm -rf "$LOCK_DIR"
    if mkdir "$LOCK_DIR" 2>/dev/null; then
        echo $$ > "$LOCK_DIR/pid"; LOCK_HELD=1; return 0
    fi
    echo "无法创建锁 $LOCK_DIR" >&2
    exit 1
}

cleanup() {
    [ -n "$WORK_DIR" ] && [ -d "$WORK_DIR" ] && rm -rf "$WORK_DIR"
    [ "$LOCK_HELD" = 1 ] && rm -rf "$LOCK_DIR"
    unset VPS_BACKUP_PASS
}

on_signal() {
    err "备份被中断（收到终止信号）"
    finish
    exit 130
}

finish() {
    [ "$FINISHED" = 1 ] && return 0
    FINISHED=1
    local dur status icon msg e i=0
    dur=$(fmt_duration $(( $(date +%s) - START_TS )))
    if [ "${#ERRORS[@]}" -eq 0 ]; then status="成功"; icon="✅"; else status="失败"; icon="❌"; fi
    log "===== 备份结束：$status，耗时 $dur ====="

    msg="$icon VPS 备份$status
主机: $BACKUP_NAME ($(hostname))
时间: $(ts)
耗时: $dur"
    [ -n "$ARCHIVE_RESULT" ] && msg+="
归档: $ARCHIVE_RESULT"
    [ -n "$SYNC_RESULT" ] && msg+="
同步: $SYNC_RESULT"
    if [ "${#ERRORS[@]}" -gt 0 ]; then
        msg+=$'\n\n错误:'
        for e in "${ERRORS[@]}"; do msg+=$'\n- '"$e"; done
        msg+=$'\n\n详细日志: '"$LOG_FILE"
    fi
    if [ "${#WARNINGS[@]}" -gt 0 ]; then
        msg+=$'\n\n警告:'
        for e in "${WARNINGS[@]}"; do
            i=$((i + 1)); [ "$i" -gt 5 ] && { msg+=$'\n- ...'; break; }
            msg+=$'\n- '"$e"
        done
    fi
    if [ "${#ERRORS[@]}" -gt 0 ] || is_true "$NOTIFY_ON_SUCCESS"; then
        tg_send "$msg" || log "WARN: Telegram 通知发送失败"
    fi
}

run_hook() {
    local name="$1" cmd="$2"
    [ -n "$cmd" ] || return 0
    log "执行 $name: $cmd"
    if ! bash -c "$cmd" >> "$LOG_FILE" 2>&1; then
        err "$name 执行失败: $cmd"
        return 1
    fi
}

# ============================ 数据库导出 ============================
dump_mysql() {
    local dir="$1" dump client cnf dbs db n=0 pw st
    dump=$(command -v mariadb-dump || command -v mysqldump) || { err "MySQL: 未找到 mysqldump / mariadb-dump"; return; }
    client=$(command -v mariadb || command -v mysql) || { err "MySQL: 未找到 mysql 客户端"; return; }

    # 用临时 cnf 传递密码，避免出现在进程列表里
    cnf="$WORK_DIR/.my.cnf"
    pw="${MYSQL_PASSWORD//\\/\\\\}"; pw="${pw//\"/\\\"}"
    {
        echo "[client]"
        [ -n "$MYSQL_HOST" ] && echo "host=$MYSQL_HOST"
        [ -n "$MYSQL_PORT" ] && echo "port=$MYSQL_PORT"
        [ -n "$MYSQL_USER" ] && echo "user=$MYSQL_USER"
        [ -n "$MYSQL_PASSWORD" ] && echo "password=\"$pw\""
        true
    } > "$cnf"

    if [ "$MYSQL_DATABASES" = "all" ]; then
        dbs=$("$client" --defaults-extra-file="$cnf" -N -B -e 'SHOW DATABASES' 2>> "$LOG_FILE") \
            || { err "MySQL: 无法连接数据库（检查账号/密码/权限）"; return; }
        dbs=$(echo "$dbs" | grep -Ev '^(information_schema|performance_schema|sys)$')
    else
        dbs=$(echo "$MYSQL_DATABASES" | tr ' ,' '\n\n')
    fi

    while IFS= read -r db; do
        [ -z "$db" ] && continue
        log "MySQL: 导出 $db"
        "$dump" --defaults-extra-file="$cnf" --single-transaction --quick --routines --triggers \
            --events --hex-blob --databases "$db" 2>> "$LOG_FILE" | gzip -c > "$dir/mysql-$db.sql.gz"
        st=("${PIPESTATUS[@]}")
        if [ "${st[0]}" -ne 0 ] || [ "${st[1]}" -ne 0 ]; then err "MySQL: 导出 $db 失败"; else n=$((n + 1)); fi
    done <<< "$dbs"
    log "MySQL: 共导出 $n 个数据库"
}

pg_run() {
    if [ "$(id -un)" = "$PG_USER" ]; then
        "$@"
    else
        (cd /tmp && su "$PG_USER" -s /bin/sh -c "$(printf '%q ' "$@")")
    fi
}

dump_pg() {
    local dir="$1" dbs db n=0
    command -v pg_dump > /dev/null || { err "PostgreSQL: 未找到 pg_dump"; return; }

    log "PostgreSQL: 导出全局对象（角色/表空间）"
    pg_run pg_dumpall --globals-only 2>> "$LOG_FILE" | gzip -c > "$dir/pg-globals.sql.gz"
    [ "${PIPESTATUS[0]}" -eq 0 ] || err "PostgreSQL: 导出全局对象失败"

    if [ "$PG_DATABASES" = "all" ]; then
        dbs=$(pg_run psql -At -c "SELECT datname FROM pg_database WHERE datallowconn AND NOT datistemplate" 2>> "$LOG_FILE") \
            || { err "PostgreSQL: 无法列出数据库"; return; }
    else
        dbs=$(echo "$PG_DATABASES" | tr ' ,' '\n\n')
    fi

    while IFS= read -r db; do
        [ -z "$db" ] && continue
        log "PostgreSQL: 导出 $db"
        if pg_run pg_dump -Fc "$db" > "$dir/pg-$db.dump" 2>> "$LOG_FILE"; then
            n=$((n + 1))
        else
            err "PostgreSQL: 导出 $db 失败"
        fi
    done <<< "$dbs"
    log "PostgreSQL: 共导出 $n 个数据库"
}

dump_docker_mysql() {
    local dir="$1" c="$2" st
    command -v docker > /dev/null || { err "Docker: 未安装 docker"; return; }
    log "Docker MySQL: 导出容器 $c"
    # 自动读取容器内的 MYSQL_ROOT_PASSWORD / MARIADB_ROOT_PASSWORD（或 *_FILE）
    docker exec "$c" sh -c '
        p="${MYSQL_ROOT_PASSWORD:-$MARIADB_ROOT_PASSWORD}"
        f="${MYSQL_ROOT_PASSWORD_FILE:-$MARIADB_ROOT_PASSWORD_FILE}"
        [ -z "$p" ] && [ -n "$f" ] && [ -f "$f" ] && p=$(cat "$f")
        d=$(command -v mariadb-dump || command -v mysqldump)
        if [ -n "$p" ]; then set -- "-p$p"; else set --; fi
        exec "$d" -uroot "$@" --all-databases --single-transaction --quick --routines --triggers --events --hex-blob
    ' 2>> "$LOG_FILE" | gzip -c > "$dir/docker-mysql-$c.sql.gz"
    st=("${PIPESTATUS[@]}")
    [ "${st[0]}" -eq 0 ] && [ "${st[1]}" -eq 0 ] || err "Docker MySQL: 容器 $c 导出失败"
}

dump_docker_pg() {
    local dir="$1" c="$2" st
    command -v docker > /dev/null || { err "Docker: 未安装 docker"; return; }
    log "Docker PostgreSQL: 导出容器 $c"
    docker exec "$c" sh -c 'exec pg_dumpall -U "${POSTGRES_USER:-postgres}"' 2>> "$LOG_FILE" \
        | gzip -c > "$dir/docker-pg-$c.sql.gz"
    st=("${PIPESTATUS[@]}")
    [ "${st[0]}" -eq 0 ] && [ "${st[1]}" -eq 0 ] || err "Docker PostgreSQL: 容器 $c 导出失败"
}

dump_databases() {
    local dir="$WORK_DIR/_databases" c
    mkdir -p "$dir"
    is_true "$MYSQL_ENABLED" && dump_mysql "$dir"
    is_true "$PG_ENABLED" && dump_pg "$dir"
    for c in "${DOCKER_MYSQL_CONTAINERS[@]}"; do dump_docker_mysql "$dir" "$c"; done
    for c in "${DOCKER_PG_CONTAINERS[@]}"; do dump_docker_pg "$dir" "$c"; done
    [ -z "$(ls -A "$dir" 2> /dev/null)" ] && rmdir "$dir"
    return 0
}

# ============================ 归档备份 ============================
maybe_encrypt() {
    if [ -n "$ENCRYPT_PASSWORD" ]; then
        openssl enc -aes-256-cbc -salt -pbkdf2 -iter 100000 -md sha256 -pass env:VPS_BACKUP_PASS
    else
        cat
    fi
}

do_archive() {
    local stamp ext name dest out p rel size tar_err fail=0 i has_root=0 x
    local -a compress_cmd paths tar_args st
    stamp=$(date +%Y%m%d-%H%M%S)

    if [ "$COMPRESSION" = "auto" ]; then
        if command -v zstd > /dev/null; then COMPRESSION=zstd; else COMPRESSION=gzip; fi
    fi
    case "$COMPRESSION" in
        zstd)
            command -v zstd > /dev/null || { err "未安装 zstd"; return 1; }
            ext=".tar.zst"; compress_cmd=(zstd -q -T0 "-${COMPRESS_LEVEL:-3}" -c) ;;
        gzip)
            ext=".tar.gz"
            if command -v pigz > /dev/null; then compress_cmd=(pigz "-${COMPRESS_LEVEL:-6}" -c)
            else compress_cmd=(gzip "-${COMPRESS_LEVEL:-6}" -c); fi ;;
        none) ext=".tar"; compress_cmd=(cat) ;;
        *) err "未知的压缩方式: $COMPRESSION"; return 1 ;;
    esac

    if [ -n "$ENCRYPT_PASSWORD" ]; then
        command -v openssl > /dev/null || { err "启用加密需要 openssl"; return 1; }
        openssl enc -help 2>&1 | grep -q -- '-pbkdf2' || { err "openssl 版本过旧（需 1.1.1+ 支持 -pbkdf2）"; return 1; }
        ext="$ext.enc"
        export VPS_BACKUP_PASS="$ENCRYPT_PASSWORD"
    fi

    name="${BACKUP_NAME}_${stamp}${ext}"
    dest="$REMOTE_ROOT/archive/daily/$name"

    for p in "${ARCHIVE_PATHS[@]}"; do
        case "$p" in /*) ;; *) warn "ARCHIVE_PATHS 必须是绝对路径，已跳过: $p"; continue ;; esac
        [ "$p" != "/" ] && p="${p%/}"
        if [ ! -e "$p" ]; then warn "路径不存在，已跳过: $p"; continue; fi
        rel="${p#/}"
        if [ -z "$rel" ]; then rel="."; has_root=1; fi
        paths+=("$rel")
    done

    tar_args=(-cpf - --ignore-failed-read --warning=no-file-changed --warning=no-file-removed
        --anchored "--exclude=${WORK_DIR#/}" "--exclude=./${WORK_DIR#/}")
    if [ "$has_root" = 1 ]; then
        for x in proc sys dev run tmp mnt media lost+found var/tmp var/run var/lock swapfile swap.img; do
            tar_args+=("--exclude=$x" "--exclude=./$x")
        done
    fi
    tar_args+=(--no-anchored)
    for x in "${ARCHIVE_EXCLUDES[@]}"; do tar_args+=("--exclude=${x#/}"); done
    [ "${#paths[@]}" -gt 0 ] && tar_args+=(-C / "${paths[@]}")
    [ -d "$WORK_DIR/_databases" ] && tar_args+=(-C "$WORK_DIR" _databases)

    if [ "${#paths[@]}" -eq 0 ] && [ ! -d "$WORK_DIR/_databases" ]; then
        err "没有可归档的内容（检查 ARCHIVE_PATHS）"
        return 1
    fi

    tar_err="$WORK_DIR/.tar.err"
    log "归档: 开始打包 -> $name （压缩: $COMPRESSION，加密: $([ -n "$ENCRYPT_PASSWORD" ] && echo 是 || echo 否)）"

    if is_true "$STREAM_UPLOAD"; then
        log "归档: 流式上传模式（不占用本地磁盘）"
        tar "${tar_args[@]}" 2> "$tar_err" | "${compress_cmd[@]}" | maybe_encrypt | rc rcat "$dest"
        st=("${PIPESTATUS[@]}")
        for i in 1 2; do [ "${st[$i]}" -eq 0 ] || fail=1; done
        if [ "${st[3]}" -ne 0 ]; then
            err "上传失败（rclone rcat exit ${st[3]}），详见 $LOG_FILE"
            [ "$fail" = 0 ] && fail=2
        fi
    else
        out="$WORK_DIR/$name"
        tar "${tar_args[@]}" 2> "$tar_err" | "${compress_cmd[@]}" | maybe_encrypt > "$out"
        st=("${PIPESTATUS[@]}")
        for i in 1 2; do [ "${st[$i]}" -eq 0 ] || fail=1; done
    fi

    tail -n 50 "$tar_err" >> "$LOG_FILE" 2> /dev/null
    if [ "${st[0]}" -eq 1 ]; then
        warn "tar: 部分文件在打包时发生变化（通常可忽略）"
    elif [ "${st[0]}" -ne 0 ]; then
        err "tar 打包失败 (exit ${st[0]}): $(tail -n 3 "$tar_err" | tr '\n' ' ')"
        fail=1
    fi
    [ "$fail" = 1 ] && [ "${st[0]}" -le 1 ] && err "压缩/加密/写入失败 (exit: ${st[*]})，请检查磁盘空间 ($TMP_DIR)"

    if [ "$fail" != 0 ]; then
        [ -n "$out" ] && rm -f "$out"
        is_true "$STREAM_UPLOAD" && rc deletefile "$dest" > /dev/null 2>&1
        return 1
    fi

    if ! is_true "$STREAM_UPLOAD"; then
        size=$(wc -c < "$out")
        log "归档: 打包完成 $(human_size "$size")，开始上传到 $dest"
        if ! rc copyto "$out" "$dest"; then
            err "上传失败: $dest"
            rm -f "$out"
            return 1
        fi
        rm -f "$out"
    else
        size=$(rc lsf --format s "$dest" 2> /dev/null | head -n 1)
    fi
    log "归档: 上传完成 $name ($(human_size "$size"))"
    ARCHIVE_RESULT="$name ($(human_size "$size"))"

    # 周备份：weekly 目录 6 天内没有新文件则复制一份（Google Drive 服务端复制，不消耗流量）
    if [ "$KEEP_WEEKLY_DAYS" -gt 0 ] && \
        [ -z "$(rc lsf --files-only --max-age 6d "$REMOTE_ROOT/archive/weekly" 2> /dev/null | head -n 1)" ]; then
        log "归档: 生成周备份"
        rc copyto "$dest" "$REMOTE_ROOT/archive/weekly/$name" || warn "复制到 weekly 失败"
    fi
    # 月备份：monthly 目录本月还没有备份则复制一份
    if [ "$KEEP_MONTHLY_DAYS" -gt 0 ] && \
        [ -z "$(rc lsf --files-only --include "${BACKUP_NAME}_$(date +%Y%m)*" "$REMOTE_ROOT/archive/monthly" 2> /dev/null | head -n 1)" ]; then
        log "归档: 生成月备份"
        rc copyto "$dest" "$REMOTE_ROOT/archive/monthly/$name" || warn "复制到 monthly 失败"
    fi
    return 0
}

prune_dir() {
    local tier="$1" days="$2" d="$REMOTE_ROOT/archive/$1"
    [ "$days" -gt 0 ] || return 0
    remote_exists "$d" || return 0
    log "清理: 删除 $tier 中超过 ${days} 天的备份"
    rc delete --min-age "${days}d" "$d" || warn "清理 $tier 失败"
}

prune_archives() {
    prune_dir daily "$KEEP_DAILY_DAYS"
    prune_dir weekly "$KEEP_WEEKLY_DAYS"
    prune_dir monthly "$KEEP_MONTHLY_DAYS"
}

# ============================ 增量同步 ============================
prune_sync_history() {
    local h="$REMOTE_ROOT/sync/history" cutoff d
    cutoff=$(date -d "@$(( $(date +%s) - SYNC_KEEP_HISTORY_DAYS * 86400 ))" +%Y%m%d 2> /dev/null) || return 0
    while IFS= read -r d; do
        d="${d%/}"
        [[ "$d" =~ ^[0-9]{8}-[0-9]{6}$ ]] || continue
        if [ "${d:0:8}" -lt "$cutoff" ]; then
            log "清理: 删除同步历史 $d"
            rc purge "$h/$d" || warn "删除同步历史 $d 失败"
        fi
    done < <(rc lsf --dirs-only "$h" 2> /dev/null)
}

do_sync() {
    local stamp p rel dest x ok=0 total=0
    local -a args
    stamp=$(date +%Y%m%d-%H%M%S)
    if [ "${#SYNC_PATHS[@]}" -eq 0 ]; then warn "SYNC_PATHS 为空，跳过同步"; return 0; fi

    for p in "${SYNC_PATHS[@]}"; do
        [ "$p" != "/" ] && p="${p%/}"
        case "$p" in /*) ;; *) warn "SYNC_PATHS 必须是绝对路径，已跳过: $p"; continue ;; esac
        [ -d "$p" ] || { warn "同步路径不存在或不是目录: $p"; continue; }
        total=$((total + 1))
        rel="${p#/}"
        dest="$REMOTE_ROOT/sync/current/$rel"
        args=(sync "$p" "$dest" --links --fast-list --transfers "$SYNC_TRANSFERS" --checkers 8)
        [ "$SYNC_KEEP_HISTORY_DAYS" -gt 0 ] && args+=(--backup-dir "$REMOTE_ROOT/sync/history/$stamp/$rel")
        for x in "${SYNC_EXCLUDES[@]}"; do args+=(--exclude "$x"); done
        log "同步: $p -> $dest"
        if rc "${args[@]}"; then
            log "同步: $p 完成"; ok=$((ok + 1))
        else
            err "同步失败: $p"
        fi
    done
    SYNC_RESULT="$ok/$total 个目录成功"
    [ "$SYNC_KEEP_HISTORY_DAYS" -gt 0 ] && prune_sync_history
    return 0
}

# ============================ 命令 ============================
run_backup() {
    local mode="$1" want_archive=0 want_sync=0
    [ "$(id -u)" -eq 0 ] || warn "建议以 root 运行，否则可能无法读取部分文件"
    rotate_log
    acquire_lock
    trap cleanup EXIT
    trap on_signal INT TERM HUP

    case "$mode" in
        archive) want_archive=1 ;;
        sync) want_sync=1 ;;
        run) is_true "$ARCHIVE_ENABLED" && want_archive=1; is_true "$SYNC_ENABLED" && want_sync=1 ;;
    esac

    log "===== 开始备份 [$mode] v$VERSION → $REMOTE_ROOT ====="
    mkdir -p "$TMP_DIR"
    WORK_DIR=$(mktemp -d "${TMP_DIR%/}/vps-backup.XXXXXX") || { err "无法创建临时目录 $TMP_DIR"; finish; exit 1; }

    run_hook PRE_HOOK "$PRE_HOOK"

    if [ "$want_archive" = 1 ]; then
        dump_databases
        if do_archive; then prune_archives; else log "归档失败，本次不清理旧备份"; fi
    elif is_true "$MYSQL_ENABLED" || is_true "$PG_ENABLED" || \
        [ "${#DOCKER_MYSQL_CONTAINERS[@]}" -gt 0 ] || [ "${#DOCKER_PG_CONTAINERS[@]}" -gt 0 ]; then
        [ "$mode" = "run" ] && warn "数据库导出只在归档模式下执行（ARCHIVE_ENABLED=false，已跳过数据库）"
    fi

    [ "$want_sync" = 1 ] && do_sync
    [ "$want_archive" = 0 ] && [ "$want_sync" = 0 ] && warn "归档和同步都未启用，什么也没做"

    run_hook POST_HOOK "$POST_HOOK"
    finish
    [ "${#ERRORS[@]}" -eq 0 ]
}

cmd_list() {
    local t
    echo "远端目录: $REMOTE_ROOT"
    for t in daily weekly monthly; do
        echo; echo "== 归档 / $t =="
        rc lsl "$REMOTE_ROOT/archive/$t" 2> /dev/null | sort -k2,3 | awk '{printf "%10.1f MB  %s %s  %s\n",$1/1048576,$2,substr($3,1,8),$4}'
    done
    echo; echo "== 同步历史 (sync/history) =="
    rc lsf --dirs-only "$REMOTE_ROOT/sync/history" 2> /dev/null
    echo; echo "== 云盘上所有主机 ($REMOTE_TOP) =="
    rc lsf --dirs-only "$REMOTE_TOP" 2> /dev/null
}

cmd_restore() {
    local name="$1" target="${2:-/root/vps-restore}" src="" t base
    local -a dec st
    if [ -z "$name" ]; then
        echo "用法: vps-backup restore <备份文件名 | 主机名/archive/daily/文件名> [解压目录]"
        echo "提示: 先用 vps-backup list 查看可用备份"
        exit 1
    fi
    if [[ "$name" == */* ]]; then
        src="$REMOTE_TOP/${name#/}"
    else
        for t in daily weekly monthly; do
            if [ -n "$(rc lsf "$REMOTE_ROOT/archive/$t/$name" 2> /dev/null)" ]; then
                src="$REMOTE_ROOT/archive/$t/$name"; break
            fi
        done
    fi
    [ -n "$src" ] && [ -n "$(rc lsf "$src" 2> /dev/null)" ] || { echo "找不到备份: $name" >&2; exit 1; }

    base="$name"
    if [[ "$base" == *.enc ]]; then
        if [ -z "$ENCRYPT_PASSWORD" ]; then
            read -r -s -p "请输入备份加密密码: " ENCRYPT_PASSWORD; echo
        fi
        export VPS_BACKUP_PASS="$ENCRYPT_PASSWORD"
        base="${base%.enc}"
    fi
    case "$base" in
        *.tar.zst) dec=(zstd -dc -q) ;;
        *.tar.gz)  dec=(gzip -dc) ;;
        *.tar)     dec=(cat) ;;
        *) echo "无法识别的备份格式: $name" >&2; exit 1 ;;
    esac

    mkdir -p "$target"
    echo "正在恢复 $src → $target ..."
    if [[ "$name" == *.enc ]]; then
        rc cat "$src" | openssl enc -d -aes-256-cbc -pbkdf2 -iter 100000 -md sha256 -pass env:VPS_BACKUP_PASS \
            | "${dec[@]}" | tar -xpf - -C "$target"
    else
        rc cat "$src" | cat | "${dec[@]}" | tar -xpf - -C "$target"
    fi
    st=("${PIPESTATUS[@]}")
    unset VPS_BACKUP_PASS
    if [ "${st[0]}" -ne 0 ] || [ "${st[1]}" -ne 0 ] || [ "${st[2]}" -ne 0 ] || [ "${st[3]}" -ne 0 ]; then
        echo "恢复失败 (exit: ${st[*]})，密码错误或文件损坏？" >&2
        exit 1
    fi
    echo "恢复完成: $target"
    [ -d "$target/_databases" ] && echo "数据库导出文件位于: $target/_databases"
    echo "（文件已解压到独立目录，请确认后再手动覆盖到系统路径）"
}

cmd_test() {
    local ok=1 f="$REMOTE_ROOT/.vps-backup-test"
    echo "== 依赖检查 =="
    echo "rclone : $(rclone version 2> /dev/null | head -n 1)"
    if tar --version 2> /dev/null | grep -q GNU; then echo "tar    : GNU tar OK"; else echo "tar    : ✗ 需要 GNU tar"; ok=0; fi
    if command -v zstd > /dev/null; then echo "zstd   : OK"; else echo "zstd   : 未安装（将使用 gzip）"; fi
    if [ -n "$ENCRYPT_PASSWORD" ]; then
        if openssl enc -help 2>&1 | grep -q -- '-pbkdf2'; then echo "openssl: OK (支持 pbkdf2)"
        else echo "openssl: ✗ 版本过旧，不支持 -pbkdf2"; ok=0; fi
    fi
    command -v curl > /dev/null && echo "curl   : OK" || { echo "curl   : ✗ 未安装"; ok=0; }

    echo; echo "== 云盘测试 ($REMOTE_ROOT) =="
    if echo "vps-backup test $(date)" | rc rcat "$f" && [ -n "$(rc lsf "$f" 2> /dev/null)" ]; then
        rc deletefile "$f" > /dev/null 2>&1
        echo "读写测试: OK"
        rc about "${RCLONE_REMOTE}:" 2> /dev/null | sed 's/^/  /'
    else
        echo "读写测试: ✗ 失败，请检查 rclone 配置（rclone config / rclone listremotes），详情见 $LOG_FILE"
        ok=0
    fi

    echo; echo "== Telegram 测试 =="
    if [ -n "$TG_BOT_TOKEN" ] && [ -n "$TG_CHAT_ID" ]; then
        if tg_send "🔔 vps-backup 测试消息
主机: $BACKUP_NAME ($(hostname))
时间: $(ts)"; then echo "发送: OK"; else echo "发送: ✗ 失败（检查 TG_BOT_TOKEN / TG_CHAT_ID / 网络）"; ok=0; fi
    else
        echo "未配置 TG_BOT_TOKEN / TG_CHAT_ID，跳过"
    fi

    echo
    if [ "$ok" = 1 ]; then echo "全部检查通过 ✅"; else echo "存在问题 ❌"; exit 1; fi
}

main() {
    local cmd="${1:-run}"
    [ $# -gt 0 ] && shift
    case "$cmd" in
        -h|--help|help) usage; exit 0 ;;
        -v|--version|version) echo "vps-backup $VERSION"; exit 0 ;;
    esac
    load_config
    command -v rclone > /dev/null || { echo "未安装 rclone，请先运行 install.sh" >&2; exit 1; }
    case "$cmd" in
        run|archive|sync) run_backup "$cmd" ;;
        list) cmd_list ;;
        restore) cmd_restore "$@" ;;
        test) cmd_test ;;
        *) usage; exit 1 ;;
    esac
}

main "$@"
