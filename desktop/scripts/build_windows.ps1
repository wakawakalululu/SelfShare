param(
  [ValidateSet('Debug','Release')]
  [string]$Configuration = 'Release',
  [switch]$SkipFlutter
)

$ErrorActionPreference = 'Stop'
$Root  = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$Core  = Join-Path $Root 'desktop\core'
$App   = Join-Path $Root 'desktop\app'

# ---------------------------------------------------------------- Rust core ---
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
Write-Host "      DLL: $dll"

if ($SkipFlutter) {
  Write-Host '[2/4] Flutter skipped by request' -ForegroundColor Yellow
  exit 0
}

if (-not (Get-Command flutter -ErrorAction SilentlyContinue)) {
  # 常见安装位置兜底
  foreach ($candidate in @('C:\dev\flutter\bin', "$env:LOCALAPPDATA\flutter\bin", 'C:\flutter\bin')) {
    if (Test-Path (Join-Path $candidate 'flutter.bat')) {
      $env:PATH = "$candidate;$env:PATH"
      break
    }
  }
}
if (-not (Get-Command flutter -ErrorAction SilentlyContinue)) {
  throw 'Flutter SDK not found. Install Flutter 3.19+ or add it to PATH.'
}

# ------------------------------------------------------------ MSVC + Win SDK ---
# Flutter 的 CMake 在没有 vcvars 环境时会找不到编译器/SDK，这里显式补上。
$vs = 'C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools'
$msvcRoot = Get-ChildItem "$vs\VC\Tools\MSVC" -Directory -ErrorAction SilentlyContinue |
            Sort-Object Name -Descending | Select-Object -First 1
$sdkInc = Get-ChildItem 'C:\Program Files (x86)\Windows Kits\10\Include' -Directory -ErrorAction SilentlyContinue |
          Sort-Object Name -Descending | Select-Object -First 1

if ($msvcRoot -and $sdkInc) {
  $msvc = $msvcRoot.FullName
  $sdkVer = $sdkInc.Name
  $sdk = 'C:\Program Files (x86)\Windows Kits\10'
  $env:PATH = "$sdk\bin\$sdkVer\x64;$msvc\bin\Hostx64\x64;" +
              "$vs\Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin;" +
              "$vs\Common7\IDE\CommonExtensions\Microsoft\CMake\Ninja;" + $env:PATH
  $env:INCLUDE = "$msvc\include;$sdk\Include\$sdkVer\ucrt;$sdk\Include\$sdkVer\um;$sdk\Include\$sdkVer\shared"
  $env:LIB = "$msvc\lib\x64;$sdk\Lib\$sdkVer\ucrt\x64;$sdk\Lib\$sdkVer\um\x64"
  $env:VCToolsVersion = $msvcRoot.Name
  $env:VSINSTALLDIR = $vs
  $env:VCToolsInstallDir = $msvc
  $env:WindowsSdkDir = $sdk
  $env:WindowsSDKVersion = "$sdkVer\"
  $env:CMAKE_GENERATOR = 'Ninja'
  Write-Host "      MSVC $($msvcRoot.Name) / SDK $sdkVer" -ForegroundColor DarkGray
} else {
  Write-Warning 'MSVC or Windows SDK not found; the build will likely fail.'
}

Write-Host '[2/4] Flutter pub get + analyze' -ForegroundColor Cyan
Push-Location $App
try {
  flutter pub get
  if ($LASTEXITCODE -ne 0) { throw 'flutter pub get failed' }
  flutter analyze
  if ($LASTEXITCODE -ne 0) { throw 'flutter analyze failed' }

  Write-Host '[3/4] flutter build windows' -ForegroundColor Cyan
  $flag = if ($Configuration -eq 'Release') { '--release' } else { '--debug' }
  flutter build windows $flag
  if ($LASTEXITCODE -ne 0) { throw 'flutter build windows failed' }

  # ---------------------------------------------------------- assemble bundle ---
  # cmake install 的默认 prefix 是 Program Files（无写权限会静默失败），
  # 因此这里从 install 结果或构建目录汇总出一个可直接运行的目录。
  Write-Host '[4/4] Assemble runnable bundle' -ForegroundColor Cyan
  $bundle = Join-Path $App "build\windows\x64\runner\$Configuration"
  $installed = 'C:\Program Files\selfshare_desktop'
  if (Test-Path $installed) {
    Copy-Item "$installed\*" $bundle -Recurse -Force
  }
  Copy-Item $dll (Join-Path $bundle 'selfshare_core.dll') -Force
  $required = @('selfshare_desktop.exe','flutter_windows.dll','data\app.so','selfshare_core.dll')
  $missing = $required | Where-Object { -not (Test-Path (Join-Path $bundle $_)) }
  if ($missing) { throw "bundle incomplete, missing: $($missing -join ', ')" }
  Write-Host "      OK: $bundle" -ForegroundColor Green
  Write-Host "      run: $bundle\selfshare_desktop.exe"
} finally { Pop-Location }
