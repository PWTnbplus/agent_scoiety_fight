param(
  [string]$ProjectRoot = 'E:\master_exp\prj2_ai_scient',
  [string]$PythonExe = 'E:\resources\python\python.exe'
)
$ErrorActionPreference = 'Stop'
if (-not (Test-Path $PythonExe)) { $PythonExe = 'python' }
$scriptFile = Join-Path $PSScriptRoot 'ONE_CLICK_REAL_V5P7.py'
& $PythonExe $scriptFile --project-root $ProjectRoot --execute
if ($LASTEXITCODE -ne 0) { throw "V5P7 one-click execution exited with code $LASTEXITCODE. Read reports/009_V5P7_LIVE_*/execution_steps.jsonl." }
