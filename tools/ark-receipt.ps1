<#
ark-receipt.ps1 —— 归档完成后生成 run.receipt.v1 并回传存储服务器（Windows / PowerShell 5.1）

示例：
  .\ark-receipt.ps1 -Node win009 -Project tcl-r5 -RunId 20261102_090644_wake_recognition -Upload
  .\ark-receipt.ps1 -Node win009 -Project tcl-r5 -RunId ... -Task "唤醒+命令词长稳" -DryRun

流程与 ark-receipt.sh 完全一致：
  1. 定位 <StorageRoot>/results/<Node>/<Project>/<RunId>（本机有就本地读，否则 scp 取 manifest/summary）
  2. 调同目录 ark_receipt.py 生成回执，evidence_dir 固定写存储路径
  3. -Upload 时回传 <StorageRoot>/receipts/<Node>/<Project>/<RunId>/run.receipt.json 并读回校验

认证：优先免密公钥；若设置了 $env:ARK_STORAGE_SSH_PASS，则用一次性 askpass（文件里只引用变量，不含密码）。
退出码：0 成功；2 参数/输入错误；3 哈希不符；4 传输失败
#>
[CmdletBinding()]
param(
  [Parameter(Mandatory = $true)][string]$Node,
  [Parameter(Mandatory = $true)][string]$Project,
  [Parameter(Mandatory = $true)][string]$RunId,
  [string]$Task,
  [string]$Skill = 'lstest',
  [string]$SkillVersion = 'unknown',
  [string]$Firmware,
  [string]$Confidence,
  [string]$Lessons,
  [string]$Bugs,
  [string]$EvidenceDir,
  [string]$StorageRoot = '/srv/storage/ark',
  [string]$StorageHost = '10.11.63.24',
  [int]$StoragePort = 10027,
  [string]$StorageUser = 'administrator',
  [switch]$Upload,
  [switch]$DryRun,
  [string]$WorkDir
)

$ErrorActionPreference = 'Stop'
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$pyScript = Join-Path $scriptDir 'ark_receipt.py'
if (-not (Test-Path $pyScript)) { Write-Error "同目录缺 ark_receipt.py：$pyScript"; exit 2 }

# --- 定位 python ------------------------------------------------------------
$python = $null
foreach ($cand in @(@('py', '-3'), @('python', ''), @('python3', ''))) {
  $exe = $cand[0]; $pre = $cand[1]
  $cmd = Get-Command $exe -ErrorAction SilentlyContinue
  if (-not $cmd) { continue }
  $args = @()
  if ($pre) { $args += $pre }
  $args += @('-c', 'import sys;print(sys.version_info[0])')
  try {
    $ver = & $exe @args 2>$null
    if ($LASTEXITCODE -eq 0 -and "$ver".Trim() -eq '3') { $python = @{ Exe = $exe; Pre = $pre }; break }
  } catch { }
}
if (-not $python) { Write-Error '找不到 Python 3（需要 python3 / python / py -3）'; exit 2 }

# --- ssh / scp 封装 ---------------------------------------------------------
$sshOpts = @('-o', 'StrictHostKeyChecking=no', '-o', 'UserKnownHostsFile=NUL', '-o', 'ConnectTimeout=10', '-o', 'LogLevel=ERROR', '-p', "$StoragePort")
$remote = "$StorageUser@$StorageHost"
$askpass = $null
$keyAuth = $false
& ssh @sshOpts -o BatchMode=yes -o PasswordAuthentication=no $remote true 2>$null | Out-Null
if ($LASTEXITCODE -eq 0) { $keyAuth = $true }

if (-not $keyAuth) {
  if (-not $env:ARK_STORAGE_SSH_PASS) { Write-Error '免密不可用且未设置 ARK_STORAGE_SSH_PASS'; exit 4 }
  $askpass = Join-Path ([System.IO.Path]::GetTempPath()) ("ark-askpass-" + [guid]::NewGuid().ToString('N') + '.cmd')
  Set-Content -Path $askpass -Encoding ASCII -Value @('@echo off', 'echo %ARK_STORAGE_SSH_PASS%')
  $env:SSH_ASKPASS = $askpass
  $env:SSH_ASKPASS_REQUIRE = 'force'
}

function Invoke-Remote {
  param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Command)
  $out = & ssh @sshOpts $remote @Command 2>&1
  return @{ Code = $LASTEXITCODE; Out = ($out -join "`n") }
}

function Copy-FromRemote {
  param([string]$RemotePath, [string]$LocalPath)
  & scp @sshOpts -q "${remote}:$RemotePath" $LocalPath 2>$null | Out-Null
  return $LASTEXITCODE
}

function Copy-ToRemote {
  param([string]$LocalPath, [string]$RemotePath)
  & scp @sshOpts -q $LocalPath "${remote}:$RemotePath" 2>$null | Out-Null
  return $LASTEXITCODE
}

function Get-Sha256([string]$Path) {
  return (Get-FileHash -Path $Path -Algorithm SHA256).Hash.ToLower()
}

$resultsDir = "$StorageRoot/results/$Node/$Project/$RunId"
$receiptsDir = "$StorageRoot/receipts/$Node/$Project/$RunId"
if (-not $EvidenceDir) { $EvidenceDir = $resultsDir }

if (-not $WorkDir) { $WorkDir = Join-Path ([System.IO.Path]::GetTempPath()) ("ark-receipt-" + [guid]::NewGuid().ToString('N')) }
New-Item -ItemType Directory -Force -Path $WorkDir | Out-Null

try {
  $localResults = $resultsDir
  if ($IsWindows -ne $false -and $resultsDir -match '^/') { $localResults = $null }
  if (-not (Test-Path (Join-Path $localResults 'manifest.json'))) { $localResults = $null }

  if ($localResults) {
    $manifest = Join-Path $localResults 'manifest.json'
    $summary = Join-Path $localResults 'summary_final.json'
    Write-Host "SOURCE: local $localResults"
  } else {
    Write-Host "SOURCE: remote ${remote}:$resultsDir"
    $manifest = Join-Path $WorkDir 'manifest.json'
    $summary = Join-Path $WorkDir 'summary_final.json'
    if ((Copy-FromRemote "$resultsDir/manifest.json" $manifest) -ne 0) { Write-Error '取 manifest.json 失败'; exit 4 }
    if ((Copy-FromRemote "$resultsDir/summary_final.json" $summary) -ne 0) {
      Write-Warning '没有 summary_final.json，回执按 manifest 生成'
      $summary = $null
    }
  }

  $out = Join-Path $WorkDir 'run.receipt.json'
  $pyArgs = @($pyScript, '--manifest', $manifest, '--node', $Node, '--project', $Project,
              '--run-id', $RunId, '--storage-root', $StorageRoot, '--evidence-dir', $EvidenceDir,
              '--skill', $Skill, '--skill-version', $SkillVersion, '--out', $out)
  if ($summary -and (Test-Path $summary)) { $pyArgs += @('--summary', $summary) }
  if ($Task) { $pyArgs += @('--task', $Task) }
  if ($Firmware) { $pyArgs += @('--firmware', $Firmware) }
  if ($Confidence) { $pyArgs += @('--confidence', $Confidence) }
  if ($Lessons) { $pyArgs += @('--lessons', $Lessons) }
  if ($Bugs) { $pyArgs += @('--bugs', $Bugs) }
  if ($DryRun) { $pyArgs += @('--dry-run') }

  $runArgs = @()
  if ($python.Pre) { $runArgs += $python.Pre }
  $runArgs += $pyArgs
  & $python.Exe @runArgs
  if ($LASTEXITCODE -ne 0) { Write-Error "回执生成失败（exit $LASTEXITCODE）"; exit 2 }

  if ($DryRun) { Write-Host 'UPLOAD: skipped（-DryRun）'; exit 0 }
  if (-not $Upload) {
    Copy-Item $out (Join-Path (Get-Location) 'run.receipt.json') -Force
    Write-Host 'UPLOAD: skipped（未加 -Upload）；本地副本 .\run.receipt.json'
    exit 0
  }

  $localSha = Get-Sha256 $out
  $mk = Invoke-Remote "mkdir -p '$receiptsDir' && chmod 2775 '$receiptsDir'"
  if ($mk.Code -ne 0) { Write-Error "建 receipts 目录失败：$($mk.Out)"; exit 4 }
  if ((Copy-ToRemote $out "$receiptsDir/run.receipt.json") -ne 0) { Write-Error '回传回执失败'; exit 4 }
  $shaRes = Invoke-Remote "sha256sum '$receiptsDir/run.receipt.json' | cut -d' ' -f1"
  $remoteSha = ($shaRes.Out -replace '\s', '')
  if ($remoteSha -ne $localSha) { Write-Error "回执回传哈希不一致 local=$localSha remote=$remoteSha"; exit 3 }
  Write-Host "RECEIPT_AT: remote ${remote}:$receiptsDir/run.receipt.json"
  Write-Host "RECEIPT_SHA256: $remoteSha"
  Write-Host 'RECEIPT_VERIFIED: OK'
} finally {
  if ($askpass -and (Test-Path $askpass)) { Remove-Item $askpass -Force -ErrorAction SilentlyContinue }
  Remove-Item Env:SSH_ASKPASS -ErrorAction SilentlyContinue
  Remove-Item Env:SSH_ASKPASS_REQUIRE -ErrorAction SilentlyContinue
}
