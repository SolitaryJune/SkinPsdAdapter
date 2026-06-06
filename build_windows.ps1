param(
  [switch]$Clean
)

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

# 这个脚本用于在 Windows 上制作“发给别人用”的单文件 exe。
# 产物位置：dist\SkinPsdAdapter.exe

if ($Clean) {
  Remove-Item -Recurse -Force .\build, .\dist -ErrorAction SilentlyContinue
}

if (-not (Test-Path ".venv\Scripts\python.exe")) {
  py -3 -m venv .venv
}

.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt pyinstaller
.\.venv\Scripts\python.exe -m PyInstaller .\skin_psd_adapter.spec --noconfirm

Write-Host ""
Write-Host "打包完成：$PSScriptRoot\dist\SkinPsdAdapter.exe"
Write-Host "把这个 SkinPsdAdapter.exe 单文件发给别人即可。"
