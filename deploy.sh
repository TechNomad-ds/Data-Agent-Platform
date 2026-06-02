#!/bin/bash
# DataMind Platform 一键部署脚本
# 用法: bash deploy.sh
set -e

echo "========================================="
echo "  DataMind Platform 部署脚本"
echo "========================================="
echo ""

# 检测系统
if [[ "$OSTYPE" == "darwin"* ]]; then
    PKG="brew install"
    echo "检测到 macOS"
elif [[ -f /etc/debian_version ]]; then
    PKG="sudo apt install -y"
    echo "检测到 Debian/Ubuntu"
elif [[ -f /etc/redhat-release ]]; then
    PKG="sudo yum install -y"
    echo "检测到 CentOS/RHEL"
else
    echo "未知系统，请手动安装依赖"
    PKG="echo 请手动安装:"
fi

# 1. 检查依赖
echo ""
echo "[1/6] 检查依赖..."

check_cmd() {
    if ! command -v "$1" &>/dev/null; then
        echo "  ✗ $1 未安装"
        return 1
    else
        echo "  ✓ $1 已安装"
        return 0
    fi
}

check_cmd python3 || { echo "  → 请安装 Python 3.11+"; exit 1; }
check_cmd node || { echo "  → 请安装 Node.js 18+"; exit 1; }
check_cmd npm || { echo "  → 请安装 npm"; exit 1; }
check_cmd psql || echo "  ⚠ PostgreSQL 客户端未安装（如果数据库在远程可忽略）"
check_cmd redis-cli || echo "  ⚠ Redis 客户端未安装（如果 Redis 在远程可忽略）"

# 2. 配置文件
echo ""
echo "[2/6] 检查配置..."

if [ ! -f .env ]; then
    if [ -f .env.example ]; then
        cp .env.example .env
        echo "  已从 .env.example 创建 .env，请编辑填入 API Key 等配置"
        echo "  → vi .env"
        exit 1
    else
        echo "  ✗ 缺少 .env 配置文件"
        exit 1
    fi
else
    echo "  ✓ .env 已存在"
fi

# 3. 后端
echo ""
echo "[3/6] 安装后端依赖..."

cd backend
if [ ! -d venv ]; then
    python3 -m venv venv
    echo "  ✓ 虚拟环境已创建"
fi

venv/bin/python -m pip install --upgrade pip -q 2>/dev/null
venv/bin/pip install -r requirements.txt -q
echo "  ✓ Python 依赖已安装"

# 4. 数据库迁移
echo ""
echo "[4/6] 数据库迁移..."

venv/bin/alembic upgrade head 2>/dev/null && echo "  ✓ 数据库迁移完成" || echo "  ⚠ 迁移失败，请检查数据库连接"

cd ..

# 5. 前端
echo ""
echo "[5/6] 构建前端..."

cd frontend
npm install --silent 2>/dev/null
npm run build 2>/dev/null
echo "  ✓ 前端构建完成"
cd ..

# 6. 启动
echo ""
echo "[6/6] 启动服务..."
echo ""
echo "========================================="
echo "  部署完成！启动命令："
echo ""
echo "  后端:"
echo "    cd backend && venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8002"
echo ""
echo "  前端（开发模式）:"
echo "    cd frontend && npm run dev"
echo ""
echo "  前端（生产模式，需要 nginx）:"
echo "    将 frontend/dist/ 部署到 nginx"
echo "    参考 frontend/nginx.conf"
echo ""
echo "  管理员账号: pkudcai / pkudcai2026"
echo "========================================="
