$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$PythonPath = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $PythonPath)) {
    Write-Error "项目虚拟环境不存在，请先运行 scripts/bootstrap-agent.ps1"
    exit 1
}

& $PythonPath -m odds_journal @args
exit $LASTEXITCODE
