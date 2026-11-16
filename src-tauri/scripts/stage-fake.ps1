<#
.SYNOPSIS
  用假 sidecar 摆出 B → D 交接目录 build/desktop-stage/，供 tauri build 试装。

.DESCRIPTION
  布局与 B 包将来的输出一致：
    build/desktop-stage/backend/mathlens-backend.exe   （这里是 fake-sidecar）
    build/desktop-stage/backend/_internal/...          （占位，验证 onedir 层级）
    build/desktop-stage/resources/...                  （-Resources 指定的合成资源，或最小占位）
    build/desktop-stage/backend/LICENSE-MathLens.txt、THIRD-PARTY-NOTICES.txt（与 B 包相同位置）
  build/ 已在 .gitignore 中，产物不入库。

.PARAMETER Resources
  合成资源目录（例如 A 交付的“只读 安装 resources”）。省略则只放最小占位。
#>
param([string]$Resources = "")

$ErrorActionPreference = 'Stop'
$srcTauri = Resolve-Path (Join-Path $PSScriptRoot '..')
$repo = Resolve-Path (Join-Path $srcTauri '..')
$stage = Join-Path $repo 'build\desktop-stage'

Push-Location $srcTauri
try {
    cargo build --release -p desktop-core --bin fake-sidecar
    if ($LASTEXITCODE -ne 0) { throw "fake-sidecar 构建失败" }
} finally {
    Pop-Location
}

if (Test-Path $stage) { Remove-Item -Recurse -Force $stage }
$backend = Join-Path $stage 'backend'
$resourcesOut = Join-Path $stage 'resources'
New-Item -ItemType Directory -Force (Join-Path $backend '_internal') | Out-Null
New-Item -ItemType Directory -Force $resourcesOut | Out-Null

Copy-Item (Join-Path $srcTauri 'target\release\fake-sidecar.exe') (Join-Path $backend 'mathlens-backend.exe')
Set-Content -Encoding utf8 (Join-Path $backend '_internal\README.txt') '假 sidecar 占位：真实安装包中这里是 PyInstaller onedir 的 _internal。'

if ($Resources) {
    Copy-Item -Recurse -Force (Join-Path $Resources '*') $resourcesOut
} else {
    New-Item -ItemType Directory -Force (Join-Path $resourcesOut 'dist') | Out-Null
    Set-Content -Encoding utf8 (Join-Path $resourcesOut 'dist\index.html') '<!doctype html><meta charset="utf-8"><title>做题龙</title>'
}

# 与 B 包实际布局一致：声明文件放在 backend\ 下
Copy-Item (Join-Path $repo 'LICENSE') (Join-Path $backend 'LICENSE-MathLens.txt')
Copy-Item (Join-Path $repo 'THIRD_PARTY_NOTICES.md') (Join-Path $backend 'THIRD-PARTY-NOTICES.txt')

Write-Host "已摆好 $stage"
Get-ChildItem -Recurse $stage | Measure-Object -Property Length -Sum | ForEach-Object {
    Write-Host ("文件 {0} 个，共 {1:N1} MiB" -f $_.Count, ($_.Sum / 1MB))
}
