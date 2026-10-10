$ErrorActionPreference = 'Stop'
$projectPath = $PSScriptRoot
Set-Location -LiteralPath $projectPath
$pythonPath = Join-Path $projectPath '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) {
    Write-Host '先创建 .venv 并安装 requirements.txt。'
    exit 1
}
$apiPort = Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue
if ($apiPort) {
    try {
        $health = Invoke-RestMethod 'http://127.0.0.1:8765/health'
        if ($health.mode -ne 'local prototype') { throw '端口被其他服务占用。' }
    } catch { throw '8765 端口已占用，无法确认海寻后端。' }
} else {
    Start-Process -FilePath $pythonPath -ArgumentList '-m uvicorn backend:app --host 127.0.0.1 --port 8765' -WorkingDirectory $projectPath -WindowStyle Hidden
}
$env:SEASEEK_RUNTIME = 'local'
& $pythonPath -m streamlit run streamlit_app.py --server.address 127.0.0.1 --server.port 8505
