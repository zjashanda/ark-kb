# 新节点上线：装好 ark-fetch，放好本机台账副本，跑一次自检。
# 用法：
#   powershell -ExecutionPolicy Bypass -File bootstrap.ps1 [-ConfigUrl <台账地址>] [-Source <ark_fetch.py 地址>]
param(
  [string]$ConfigUrl = '\\10.11.63.24\storage\ark\mesh\sources.json',
  [string]$Source = '\\10.11.63.24\storage\ark\mesh\ark_fetch.py'
)
$ErrorActionPreference = 'Stop'
$arkDir = Join-Path $env:USERPROFILE '.config\ark'
$cacheDir = Join-Path $env:LOCALAPPDATA 'ark-mesh-cache'
New-Item -ItemType Directory -Force -Path $arkDir, $cacheDir | Out-Null

$tool = Join-Path $arkDir 'ark_fetch.py'
if (Test-Path -LiteralPath $Source) {
  Copy-Item -LiteralPath $Source -Destination $tool -Force
} elseif (Test-Path -LiteralPath $tool) {
  Write-Output "保留已有 $tool"
} else {
  Write-Output "MISSING: 没有找到 ark_fetch.py（$Source），请用 -Source 指定"
  exit 2
}

$cfg = Join-Path $arkDir 'mesh-sources.json'
if (Test-Path -LiteralPath $ConfigUrl) {
  Copy-Item -LiteralPath $ConfigUrl -Destination $cfg -Force
} elseif (Test-Path -LiteralPath $cfg) {
  Write-Output "保留已有 $cfg"
} else {
  Write-Output "MISSING: 没有找到台账（$ConfigUrl），请用 -ConfigUrl 指定"
  exit 2
}

$py = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $py) { $py = (Get-Command python3 -ErrorAction SilentlyContinue).Source }
if (-not $py) { Write-Output 'MISSING: 本机没有 python'; exit 2 }

$env:ARK_MESH_CONFIG = $cfg
$env:ARK_MESH_CACHE = $cacheDir
Write-Output "== 本机 =="
Write-Output ("host={0} user={1} python={2}" -f $env:COMPUTERNAME, $env:USERNAME, $py)
Write-Output "== 公钥（要免密直连时把这段追加到对端 authorized_keys） =="
$pub = Join-Path $env:USERPROFILE '.ssh\id_ed25519.pub'
if (Test-Path -LiteralPath $pub) { Get-Content -LiteralPath $pub } else { Write-Output '(本机还没有 id_ed25519.pub，可先 ssh-keygen -t ed25519)' }
Write-Output "== 自检 =="
& $py $tool status --timeout 6
exit $LASTEXITCODE
