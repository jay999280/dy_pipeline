#!/usr/bin/env bash
# ============================================================
# dy-pipeline-skill 一键安装脚本（Linux / macOS）
# 用法：bash install.sh
# ============================================================
set -e
echo ""
echo "=== dy-pipeline-skill 一键安装 ==="

# 1. 检查 Python
if ! command -v python3 >/dev/null 2>&1; then
    echo "[X] 未找到 python3，请先安装 Python 3.10+"
    exit 1
fi
echo "[1/5] Python: $(python3 --version)"

# 2. 检查 ffmpeg
if command -v ffmpeg >/dev/null 2>&1; then
    echo "[2/5] ffmpeg: 已安装"
else
    echo "[2/5] ffmpeg: 未安装，请先安装："
    echo "      macOS:  brew install ffmpeg"
    echo "      Debian: sudo apt install ffmpeg"
    exit 1
fi

# 3. 虚拟环境
if [ ! -d ".venv" ]; then
    echo "[3/5] 创建虚拟环境 .venv ..."
    python3 -m venv .venv
fi
PIP=".venv/bin/pip"

# 4. 依赖 + Chrome
echo "[4/5] 安装依赖（首次约 1-3 分钟）..."
$PIP install -r requirements.txt -q
echo "[5/5] 安装 Playwright Chrome..."
.venv/bin/python -m playwright install chrome

# 5. .env
if [ ! -f ".env" ]; then
    cp .env.example .env
    echo ""
    echo "已生成 .env（请打开填写 LLM_API_KEY）"
fi

echo ""
echo "=== 安装完成！下一步 ==="
echo "1. 编辑 .env，填入你的 LLM_API_KEY"
echo "2. 复制需求卡: cp config/需求卡模板.yaml config/我的客户_需求卡.yaml"
echo "3. 跑流水线: .venv/bin/python src/run.py config/我的客户_需求卡.yaml"
echo "   （首次运行会弹 Chrome 扫码登录抖音）"
echo ""
