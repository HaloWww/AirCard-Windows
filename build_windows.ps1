$ErrorActionPreference = "Stop"
$projectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $projectDir

$python = & py -3.12 -c "import sys; print(sys.executable)"
if (-not $python) {
    throw "64-bit Python 3.12 is required."
}

$buildEnv = Join-Path $projectDir ".venv-build"
if (-not (Test-Path -LiteralPath (Join-Path $buildEnv "Scripts\python.exe"))) {
    & py -3.12 -m venv $buildEnv
}

$buildPython = Join-Path $buildEnv "Scripts\python.exe"
$flet = Join-Path $buildEnv "Scripts\flet.exe"
& $buildPython -m pip install --upgrade pip
& $buildPython -m pip install -r requirements-build.txt

& $flet pack app.py `
    --name AirCard `
    --product-name "AirCard 卡面助手" `
    --file-description "Windows Apple Wallet 卡面管理工具" `
    --product-version "2.0.0" `
    --file-version "2.0.0.0" `
    --company-name "AirCard contributors" `
    --copyright "MIT License" `
    --hidden-import pymobiledevice3.lockdown pymobiledevice3.usbmux pymobiledevice3.services.afc pymobiledevice3.services.syslog pymobiledevice3.service_connection `
    --distpath dist `
    --yes

Write-Host "Built: $projectDir\dist\AirCard.exe"
