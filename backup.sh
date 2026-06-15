#!/bin/bash
# DataMind Analyst 备份/恢复脚本
# 用法:
#   备份: bash backup.sh backup
#   恢复: bash backup.sh restore <备份文件.tar.gz>
set -e

# 从 .env 读取数据库配置
source .env 2>/dev/null
DB_NAME=$(echo "$DATABASE_URL_SYNC" | grep -oP '(?<=/)[^/]+$' || echo "datamind")
STORAGE_DIR=$(grep STORAGE_ROOT .env 2>/dev/null | cut -d= -f2 || echo "./backend/storage")
CHROMA_DIR=$(grep CHROMA_PERSIST_DIR .env 2>/dev/null | cut -d= -f2 || echo "./backend/chroma_data")
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_DIR="backups"

backup() {
    echo "===== DataMind 备份 ====="
    mkdir -p "$BACKUP_DIR/tmp_$TIMESTAMP"

    echo "[1/3] 导出数据库..."
    pg_dump "$DB_NAME" > "$BACKUP_DIR/tmp_$TIMESTAMP/database.sql" 2>/dev/null \
        && echo "  ✓ 数据库已导出" \
        || echo "  ✗ 数据库导出失败（请检查 pg_dump 和数据库连接）"

    echo "[2/3] 打包文件存储..."
    if [ -d "$STORAGE_DIR" ]; then
        cp -r "$STORAGE_DIR" "$BACKUP_DIR/tmp_$TIMESTAMP/storage"
        echo "  ✓ storage 已复制"
    fi
    if [ -d "$CHROMA_DIR" ]; then
        cp -r "$CHROMA_DIR" "$BACKUP_DIR/tmp_$TIMESTAMP/chroma_data"
        echo "  ✓ chroma_data 已复制"
    fi

    echo "[3/3] 压缩..."
    cp .env "$BACKUP_DIR/tmp_$TIMESTAMP/.env" 2>/dev/null
    cd "$BACKUP_DIR"
    tar -czf "datamind_backup_$TIMESTAMP.tar.gz" "tmp_$TIMESTAMP"
    rm -rf "tmp_$TIMESTAMP"
    cd ..

    SIZE=$(du -sh "$BACKUP_DIR/datamind_backup_$TIMESTAMP.tar.gz" | cut -f1)
    echo ""
    echo "✓ 备份完成: $BACKUP_DIR/datamind_backup_$TIMESTAMP.tar.gz ($SIZE)"
}

restore() {
    BACKUP_FILE="$1"
    if [ -z "$BACKUP_FILE" ] || [ ! -f "$BACKUP_FILE" ]; then
        echo "用法: bash backup.sh restore <备份文件.tar.gz>"
        exit 1
    fi

    echo "===== DataMind 恢复 ====="
    echo "⚠ 这将覆盖当前数据库和文件，确定继续？(y/N)"
    read -r confirm
    if [ "$confirm" != "y" ] && [ "$confirm" != "Y" ]; then
        echo "已取消"
        exit 0
    fi

    TMP="restore_tmp_$$"
    mkdir -p "$TMP"
    tar -xzf "$BACKUP_FILE" -C "$TMP"
    INNER=$(ls "$TMP")

    echo "[1/3] 恢复数据库..."
    if [ -f "$TMP/$INNER/database.sql" ]; then
        psql "$DB_NAME" < "$TMP/$INNER/database.sql" 2>/dev/null \
            && echo "  ✓ 数据库已恢复" \
            || echo "  ✗ 数据库恢复失败"
    fi

    echo "[2/3] 恢复文件..."
    if [ -d "$TMP/$INNER/storage" ]; then
        rm -rf "$STORAGE_DIR"
        cp -r "$TMP/$INNER/storage" "$STORAGE_DIR"
        echo "  ✓ storage 已恢复"
    fi
    if [ -d "$TMP/$INNER/chroma_data" ]; then
        rm -rf "$CHROMA_DIR"
        cp -r "$TMP/$INNER/chroma_data" "$CHROMA_DIR"
        echo "  ✓ chroma_data 已恢复"
    fi

    echo "[3/3] 清理..."
    rm -rf "$TMP"
    echo ""
    echo "✓ 恢复完成，请重启后端服务"
}

case "${1:-}" in
    backup)  backup ;;
    restore) restore "$2" ;;
    *)
        echo "DataMind 备份/恢复工具"
        echo ""
        echo "用法:"
        echo "  bash backup.sh backup              备份数据库+文件"
        echo "  bash backup.sh restore <file.tar.gz>  恢复备份"
        ;;
esac
