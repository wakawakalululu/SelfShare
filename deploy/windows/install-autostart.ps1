[CmdletBinding(DefaultParameterSetName='Gui')]
param(
  [Parameter(ParameterSetName='Gui', Mandatory=$true)]
  [string]$GuiExe,

  [Parameter(ParameterSetName='Watch', Mandatory=$true)]
  [string]$SyncFolder,

  [Parameter(ParameterSetName='Watch')]
  [string]$PythonwExe,

  [Parameter(ParameterSetName='Watch')]
  [string]$SelfSharePy,

  [switch]$Force
)

$ErrorActionPreference = 'Stop'
if (-not $SelfSharePy) {
  $RepoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
  $SelfSharePy = Join-Path $RepoRoot 'selfshare.py'
}
$Sid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value
$Work = Join-Path $env:LOCALAPPDATA 'SelfShare\tasks'
New-Item -ItemType Directory -Force -Path $Work | Out-Null

function Escape-Xml([string]$Value) {
  return [System.Security.SecurityElement]::Escape($Value)
}

if ($PSCmdlet.ParameterSetName -eq 'Gui') {
  $GuiExe = (Resolve-Path $GuiExe).Path
  $Template = Join-Path $PSScriptRoot 'SelfShare-GUI-OnLogon.xml.template'
  $TaskName = '\SelfShare\GUI'
  $XmlPath = Join-Path $Work 'SelfShare-GUI-OnLogon.xml'
  $Xml = Get-Content $Template -Raw -Encoding UTF8
  $Xml = $Xml.Replace('__USER_SID__', (Escape-Xml $Sid))
  $Xml = $Xml.Replace('__GUI_EXE__', (Escape-Xml $GuiExe))
  $Xml = $Xml.Replace('__GUI_DIR__', (Escape-Xml (Split-Path -Parent $GuiExe)))
} else {
  $SelfSharePy = (Resolve-Path $SelfSharePy).Path
  $SyncFolder = (Resolve-Path $SyncFolder).Path
  if (-not $PythonwExe) {
    $PythonwExe = (Get-Command pythonw.exe -ErrorAction Stop).Source
  }
  $PythonwExe = (Resolve-Path $PythonwExe).Path
  $Template = Join-Path $PSScriptRoot 'SelfShare-Watch-OnLogon.xml.template'
  $TaskName = '\SelfShare\Watch'
  $XmlPath = Join-Path $Work 'SelfShare-Watch-OnLogon.xml'
  $Xml = Get-Content $Template -Raw -Encoding UTF8
  $Xml = $Xml.Replace('__USER_SID__', (Escape-Xml $Sid))
  $Xml = $Xml.Replace('__PYTHONW_EXE__', (Escape-Xml $PythonwExe))
  $Xml = $Xml.Replace('__SELFSHARE_PY__', (Escape-Xml $SelfSharePy))
  $Xml = $Xml.Replace('__SYNC_FOLDER__', (Escape-Xml $SyncFolder))
  $Xml = $Xml.Replace('__PROJECT_DIR__', (Escape-Xml (Split-Path -Parent $SelfSharePy)))
}

# schtasks 读取文件时以 XML 声明为准；输出 UTF-16LE 时同步修改声明。
$Xml = $Xml.Replace('encoding="UTF-8"', 'encoding="UTF-16"')
[System.IO.File]::WriteAllText($XmlPath, $Xml, [System.Text.Encoding]::Unicode)

if ($Force) {
  # 任务不存在是正常情况；通过 cmd 吞掉该预期错误，避免
  # $ErrorActionPreference=Stop 把 native stderr 升级成终止异常。
  cmd.exe /c "schtasks.exe /Delete /TN `"$TaskName`" /F >nul 2>&1" | Out-Null
}

schtasks.exe /Create /TN $TaskName /XML $XmlPath /F
if ($LASTEXITCODE -ne 0) { throw "创建计划任务失败：$TaskName" }

schtasks.exe /Query /TN $TaskName /V /FO LIST
if ($LASTEXITCODE -ne 0) { throw "计划任务创建后无法查询：$TaskName" }

Write-Host "已安装开机自启任务：$TaskName" -ForegroundColor Green
Write-Host "生成的 XML：$XmlPath"
Write-Host "卸载命令：schtasks /Delete /TN `"$TaskName`" /F"
