param(
  [ValidateSet('Debug','Release')]
  [string]$Configuration = 'Release',
  [switch]$SkipFlutter
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$Core = Join-Path $Root 'desktop\core'
$App = Join-Path $Root 'desktop\app'
$RustOut = Join-Path $App 'rust'

Write-Host '[1/4] Build Rust Core' -ForegroundColor Cyan
Push-Location $Core
try {
  if ($Configuration -eq 'Release') {
    cargo build --release
    $dll = Join-Path $Core 'target\release\selfshare_core.dll'
  } else {
    cargo build
    $dll = Join-Path $Core 'target\debug\selfshare_core.dll'
  }
  if ($LASTEXITCODE -ne 0) { throw 'cargo build failed' }
} finally { Pop-Location }

New-Item -ItemType Directory -Force -Path $RustOut | Out-Null
Copy-Item $dll (Join-Path $RustOut 'selfshare_core.dll') -Force
Write-Host "      Rust DLL: $RustOut\selfshare_core.dll"

if ($SkipFlutter) {
  Write-Host '[2/4] Flutter skipped by request' -ForegroundColor Yellow
  exit 0
}

if (-not (Get-Command flutter -ErrorAction SilentlyContinue)) {
  throw 'Flutter SDK not found in PATH. Install Flutter 3.19+ and rerun, or pass -SkipFlutter.'
}

Write-Host '[2/4] Generate/refresh Flutter Windows runner' -ForegroundColor Cyan
Push-Location $App
try {
  # 只补齐平台模板，不覆盖 lib/ 和 pubspec.yaml。
  flutter create --platforms windows .
  if ($LASTEXITCODE -ne 0) { throw 'flutter create failed' }
  flutter pub get
  if ($LASTEXITCODE -ne 0) { throw 'flutter pub get failed' }

  Write-Host '[3/4] Analyze Flutter app' -ForegroundColor Cyan
  flutter analyze
  if ($LASTEXITCODE -ne 0) { throw 'flutter analyze failed' }

  Write-Host '[4/4] Build Flutter Windows app' -ForegroundColor Cyan
  if ($Configuration -eq 'Release') {
    flutter build windows --release
  } else {
    flutter build windows --debug
  }
  if ($LASTEXITCODE -ne 0) { throw 'flutter build windows failed' }
} finally { Pop-Location }

$Mode = if ($Configuration -eq 'Release') { 'Release' } else { 'Debug' }
$Bundle = Join-Path $App "build\windows\x64\runner\$Mode"
if (Test-Path $Bundle) {
  Copy-Item (Join-Path $RustOut 'selfshare_core.dll') $Bundle -Force
  Write-Host "Build complete: $Bundle" -ForegroundColor Green
}
