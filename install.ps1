# ============================================================
# dy-pipeline-skill 一键安装脚本（Windows / PowerShell）
# 用法：右键"使用 PowerShell 运行"，或
#   powershell -ExecutionPolicy Bypass -File install.ps1
# ============================================================
$ErrorActionPreference = "Stop"
Write-Host "`n=== dy-pipeline-skill 一键安装 ===`n" -ForegroundColor Cyan

# 1. 检查 Python
$py = $null
foreach ($cand in @("py -3", "python")) {
    try { & $cand --version 2>$null | Out-Null; $py = $cand; break } catch {}
}
if (-not $py) {
    Write-Host "[X] 未找到 Python，请先安装 Python 3.10+（勾选 Add to PATH）" -ForegroundColor Red
    Write-Host "    下载: https://www.python.org/downloads/" -ForegroundColor Yellow
    exit 1
}
Write-Host "[1/5] Python: $((& $py --version 2>&1))" -ForegroundColor Green

# 2. 检查 ffmpeg
try { & ffmpeg -version 2>$null | Out-Null; Write-Host "[2/5] ffmpeg: 已安装" -ForegroundColor Green }
catch {
    Write-Host "[2/5] ffmpeg: 未安装，尝试 winget 安装..." -ForegroundColor Yellow
    try { winget install -e --id Gyan.FFmpeg --accept-source-agreements --accept-package-agreements | Out-Null
          Write-Host "      ffmpeg 安装完成，请【重新打开】终端后再继续" -ForegroundColor Green; exit 0 }
    catch { Write-Host "[X] ffmpeg 安装失败，请手动安装: https://ffmpeg.org/download.html" -ForegroundColor Red; exit 1 }
}

# 3. 创建虚拟环境并装依赖
if (-not (Test-Path ".venv")) {
    Write-Host "[3/5] 创建虚拟环境 .venv ..." -ForegroundColor Green
    & $py -m venv .venv
}
$pip = ".venv\Scripts\pip.exe"
Write-Host "[4/5] 安装依赖（首次约 1-3 分钟）..." -ForegroundColor Green
& $pip install -r requirements.txt -q

# 4. 安装 Chrome（采集用 Playwright 挂载）
Write-Host "[5/5] 安装 Playwright Chrome..." -ForegroundColor Green
& ".venv\Scripts\python.exe" -m playwright install chrome

# 5. 生成 .env
if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "`n已生成 .env（请打开填写 LLM_API_KEY）" -ForegroundColor Yellow
}

Write-Host "`n=== 安装完成！下一步 ===`n" -ForegroundColor Cyan
Write-Host "1. 编辑 .env，填入你的 LLM_API_KEY（智谱免费: https://open.bigmodel.cn）" -ForegroundColor White
Write-Host "2. 复制需求卡: copy config\需求卡模板.yaml config\我的客户_需求卡.yaml" -ForegroundColor White
Write-Host "3. 跑流水线: .venv\Scripts\python.exe src\run.py config\我的客户_需求卡.yaml" -ForegroundColor White
Write-Host "   （首次运行会弹 Chrome 扫码登录抖音）`n" -ForegroundColor White
