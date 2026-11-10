# skillhub_bootstrap.ps1 - NoahsArk node-side skillhub inventory / on-demand sync (Windows PowerShell 5.1)
#
# Usage:
#   powershell -NoProfile -ExecutionPolicy Bypass -File skillhub_bootstrap.ps1 -Hub "D:\zhsh\workspace\skillhub" -Inventory -Json
#   powershell -NoProfile -ExecutionPolicy Bypass -File skillhub_bootstrap.ps1 -Hub "D:\zhsh\workspace\skillhub" -Skills "Polaris,lstest" [-Apply] [-Json] [-RemoteBase https://github.com/zjashanda]
#
# Requires only git. Default is dry-run; -Apply writes.
# Hard rules: never delete, never reset --hard, never clean, never checkout --, never touch *.broken-*, never write under <hub>\tasks, never prompt.

param(
    [string]$Hub = "",
    [string]$Skills = "",
    [switch]$Inventory,
    [switch]$Apply,
    [switch]$Json,
    [string]$RemoteBase = "https://github.com/zjashanda",
    [switch]$FailOnDrift,
    [switch]$FailOnRemote
)

$ErrorActionPreference = "Continue"
$env:GIT_TERMINAL_PROMPT = "0"
$env:GIT_PAGER = "cat"
$env:PAGER = "cat"
$env:GIT_ASKPASS = ""
$env:SSH_ASKPASS = ""

$GITBASE = @("-c", "credential.helper=", "-c", "core.askPass=", "-c", "http.lowSpeedLimit=1000", "-c", "http.lowSpeedTime=20")

function Now-Iso { (Get-Date).ToString("yyyy-MM-ddTHH:mm:sszzz") }
function Node-Name { try { return [string]$env:COMPUTERNAME } catch { return "unknown" } }
function Remote-Url([string]$name) { return ($RemoteBase.TrimEnd('/') + "/" + $name + ".git") }

function Invoke-Git {
    param([string[]]$GitArgs, [switch]$NoBase)
    $all = @()
    if (-not $NoBase) { $all += $GITBASE }
    $all += $GitArgs
    $out = & git @all 2>&1
    return [pscustomobject]@{ Rc = $LASTEXITCODE; Out = ($out | Out-String).Trim() }
}

function Get-Head([string]$dir) {
    $r = Invoke-Git @("-C", $dir, "rev-parse", "--verify", "--quiet", "HEAD")
    if ($r.Rc -eq 0) { return $r.Out }
    return ""
}

function Get-BareSha([string]$cache) {
    $r = Invoke-Git @("-C", $cache, "rev-parse", "--verify", "--quiet", "HEAD")
    if ($r.Rc -eq 0 -and $r.Out) { return $r.Out }
    $r = Invoke-Git @("-C", $cache, "rev-parse", "--verify", "--quiet", "refs/remotes/origin/main")
    if ($r.Rc -eq 0 -and $r.Out) { return $r.Out }
    $r = Invoke-Git @("-C", $cache, "rev-parse", "--verify", "--quiet", "refs/remotes/origin/HEAD")
    if ($r.Rc -eq 0 -and $r.Out) { return $r.Out }
    return ""
}

function Get-RemoteSha([string]$cache) {
    $r = Invoke-Git @("-C", $cache, "rev-parse", "--verify", "--quiet", "refs/remotes/origin/main")
    if ($r.Rc -eq 0 -and $r.Out) { return $r.Out }
    $r = Invoke-Git @("-C", $cache, "rev-parse", "--verify", "--quiet", "refs/remotes/origin/HEAD")
    if ($r.Rc -eq 0 -and $r.Out) { return $r.Out }
    return ""
}

function Get-Branch([string]$dir) {
    $r = Invoke-Git @("-C", $dir, "branch", "--show-current")
    if ($r.Rc -eq 0) { return $r.Out }
    return ""
}

function Get-DirtyCounts([string]$dir) {
    $t = Invoke-Git @("-C", $dir, "status", "--porcelain", "--untracked-files=no")
    $a = Invoke-Git @("-C", $dir, "status", "--porcelain", "--untracked-files=all")
    $tl = @()
    if ($t.Out) { $tl = $t.Out -split "`r?`n" | Where-Object { $_ -ne "" } }
    $al = @()
    if ($a.Out) { $al = $a.Out -split "`r?`n" | Where-Object { $_ -ne "" } }
    $d = $tl.Count
    $u = $al.Count - $d
    if ($u -lt 0) { $u = 0 }
    return [pscustomobject]@{ Dirty = $d; Untracked = $u }
}

function Test-IsGit([string]$dir) {
    if (Test-Path (Join-Path $dir ".git")) { return $true }
    return $false
}

function First-Line([string]$s) {
    if (-not $s) { return "" }
    $l = ($s -split "`r?`n")[0]
    if ($l.Length -gt 200) { $l = $l.Substring(0, 200) }
    return $l
}

if (-not $Hub) {
    [Console]::Error.WriteLine("usage: -Hub PATH (-Inventory | -Skills a,b) [-Apply] [-Json] [-RemoteBase BASE]")
    exit 2
}

# ---------------- inventory ----------------
if ($Inventory -or (-not $Skills)) {
    $entries = New-Object System.Collections.ArrayList
    if (-not (Test-Path $Hub)) {
        $obj = [ordered]@{
            schema = "skillhub-inventory.v1"; node = (Node-Name); os = "windows"; hub = $Hub
            generated_at = (Now-Iso); entries = @(); error = "hub not found"
        }
        if ($Json) { Write-Output ($obj | ConvertTo-Json -Depth 6 -Compress) }
        else { [Console]::Error.WriteLine("hub not found: $Hub") }
        exit 0
    }

    $cacheDir = Join-Path $Hub "cache"
    if (Test-Path $cacheDir) {
        Get-ChildItem $cacheDir -Directory -ErrorAction SilentlyContinue | Where-Object { $_.Name -like "*.git" } | ForEach-Object {
            $name = $_.Name.Substring(0, $_.Name.Length - 4)
            $sha = Get-BareSha $_.FullName
            [void]$entries.Add([ordered]@{
                name = $name; kind = "cache"; path = $_.FullName; git = $true; branch = ""
                sha = $sha; cache_sha = $sha; dirty_tracked = 0; untracked = 0
            })
        }
    }

    $wtDir = Join-Path $Hub "worktrees"
    if (Test-Path $wtDir) {
        Get-ChildItem $wtDir -Directory -ErrorAction SilentlyContinue | ForEach-Object {
            $name = $_.Name
            $cachePath = Join-Path (Join-Path $Hub "cache") ($name + ".git")
            $csha = ""
            if (Test-Path $cachePath) { $csha = Get-BareSha $cachePath }
            if (Test-IsGit $_.FullName) {
                $cnt = Get-DirtyCounts $_.FullName
                [void]$entries.Add([ordered]@{
                    name = $name; kind = "worktree"; path = $_.FullName; git = $true
                    branch = (Get-Branch $_.FullName); sha = (Get-Head $_.FullName); cache_sha = $csha
                    dirty_tracked = $cnt.Dirty; untracked = $cnt.Untracked
                })
            } else {
                [void]$entries.Add([ordered]@{
                    name = $name; kind = "worktree"; path = $_.FullName; git = $false; branch = ""
                    sha = ""; cache_sha = $csha; dirty_tracked = 0; untracked = 0
                })
            }
        }
    }

    Get-ChildItem $Hub -Directory -ErrorAction SilentlyContinue | ForEach-Object {
        $name = $_.Name
        if ($name -eq "cache" -or $name -eq "worktrees") { return }
        $isBroken = $name -match "\.broken-"
        $kind = "checkout"
        if ($isBroken) { $kind = "other" }
        $cachePath = Join-Path (Join-Path $Hub "cache") ($name + ".git")
        $csha = ""
        if (Test-Path $cachePath) { $csha = Get-BareSha $cachePath }
        if (Test-IsGit $_.FullName) {
            $cnt = Get-DirtyCounts $_.FullName
            [void]$entries.Add([ordered]@{
                name = $name; kind = $kind; path = $_.FullName; git = $true
                branch = (Get-Branch $_.FullName); sha = (Get-Head $_.FullName); cache_sha = $csha
                dirty_tracked = $cnt.Dirty; untracked = $cnt.Untracked
            })
        } else {
            [void]$entries.Add([ordered]@{
                name = $name; kind = $kind; path = $_.FullName; git = $false; branch = ""
                sha = ""; cache_sha = $csha; dirty_tracked = 0; untracked = 0
            })
        }
    }

    $sorted = $entries | Sort-Object @{ Expression = { $_.kind } }, @{ Expression = { $_.name } }
    $obj = [ordered]@{
        schema = "skillhub-inventory.v1"; node = (Node-Name); os = "windows"; hub = $Hub
        generated_at = (Now-Iso); entries = @($sorted)
    }
    if ($Json) {
        Write-Output ($obj | ConvertTo-Json -Depth 6 -Compress)
    } else {
        foreach ($e in $sorted) { Write-Output ("{0,-10} {1,-28} git={2,-5} sha={3}" -f $e.kind, $e.name, $e.git, $e.sha) }
    }
    exit 0
}

# ---------------- bootstrap ----------------
$results = New-Object System.Collections.ArrayList
$drift = $false
$remoteErr = $false

function Add-Result([string]$name, [string]$action, [string]$from, [string]$to, [string]$detail) {
    [void]$results.Add([ordered]@{ name = $name; action = $action; from_sha = $from; to_sha = $to; detail = $detail })
}

function Sync-One([string]$name) {
    $cache = Join-Path (Join-Path $Hub "cache") ($name + ".git")
    $co = ""
    $legacy = Join-Path $Hub $name
    $wt = Join-Path (Join-Path $Hub "worktrees") $name
    if ((Test-Path $legacy) -and (Test-IsGit $legacy)) { $co = $legacy }
    elseif ((Test-Path $wt) -and (Test-IsGit $wt)) { $co = $wt }

    if (-not (Test-Path $cache) -and (-not $co)) {
        if (-not $Apply) {
            Add-Result $name "ABSENT" "" "" "no cache and no checkout"
            return
        }
        New-Item -ItemType Directory -Force -Path (Join-Path $Hub "cache") | Out-Null
        $r = Invoke-Git @("init", "--bare", "--quiet", $cache)
        if ($r.Rc -ne 0) { Add-Result $name "ERROR" "" "" (First-Line $r.Out); return }
        Invoke-Git @("-C", $cache, "remote", "add", "origin", (Remote-Url $name)) | Out-Null
    }

    if (Test-Path $cache) {
        $f = Invoke-Git @("-C", $cache, "fetch", "--prune", "--quiet", "origin", "+refs/heads/*:refs/remotes/origin/*")
        if ($f.Rc -ne 0) { Add-Result $name "ERROR" "" "" (First-Line $f.Out); return }
    }

    $rsha = Get-RemoteSha $cache
    if (-not $rsha) { Add-Result $name "ERROR" "" "" "cannot resolve remote sha (private repo or no branch)"; return }

    if (-not $co) {
        if (-not $Apply) { Add-Result $name "ABSENT" "" $rsha "cache only"; return }
        $co = Join-Path $Hub $name
        $c = Invoke-Git @("clone", "--quiet", $cache, $co)
        if ($c.Rc -ne 0) { Add-Result $name "ERROR" "" "" (First-Line $c.Out); return }
        Invoke-Git @("-C", $co, "remote", "set-url", "origin", (Remote-Url $name)) | Out-Null
        $chk = Invoke-Git @("-C", $co, "checkout", "--quiet", "-B", "main", $rsha)
        if ($chk.Rc -ne 0) { Add-Result $name "ERROR" "" $rsha (First-Line $chk.Out); return }
        Add-Result $name "CLONE" "" $rsha "cloned from cache"
        return
    }

    $lsha = Get-Head $co
    $cnt = Get-DirtyCounts $co
    if ($cnt.Dirty -gt 0) { Add-Result $name "SKIP_DRIFT" $lsha $rsha "tracked changes present"; $script:drift = $true; return }
    if ($lsha -eq $rsha) { Add-Result $name "SKIP_IN_SYNC" $lsha $rsha ""; return }

    $anc = Invoke-Git @("-C", $co, "merge-base", "--is-ancestor", $lsha, $rsha)
    if ($anc.Rc -eq 0) {
        if ($Apply) {
            $m = Invoke-Git @("-C", $co, "merge", "--ff-only", "--quiet", $rsha)
            if ($m.Rc -ne 0) { Add-Result $name "ERROR" $lsha $rsha (First-Line $m.Out); return }
            Add-Result $name "PULL" $lsha $rsha "fast-forward"
        } else {
            Add-Result $name "OUTDATED" $lsha $rsha "fast-forward available"
        }
        return
    }

    $anc2 = Invoke-Git @("-C", $co, "merge-base", "--is-ancestor", $rsha, $lsha)
    if ($anc2.Rc -eq 0) { Add-Result $name "AHEAD" $lsha $rsha "local ahead of origin"; return }

    Add-Result $name "SKIP_DRIFT" $lsha $rsha "diverged"
    $script:drift = $true
}

if ($Apply) { New-Item -ItemType Directory -Force -Path $Hub | Out-Null }

$list = $Skills.Split(",")
foreach ($raw in $list) {
    $name = $raw.Trim()
    if ($name) { Sync-One $name }
}

$obj = [ordered]@{
    schema = "skillhub-bootstrap.v1"; hub = $Hub; remote_base = $RemoteBase
    apply = [bool]$Apply; generated_at = (Now-Iso); entries = @($results)
}
if ($Json) {
    Write-Output ($obj | ConvertTo-Json -Depth 6 -Compress)
} else {
    foreach ($e in $results) { Write-Output ("{0,-13} {1,-28} {2} -> {3}  {4}" -f $e.action, $e.name, $e.from_sha, $e.to_sha, $e.detail) }
}

$rc = 0
if ($FailOnDrift -and $drift) { $rc = 8 }
if ($rc -eq 0 -and $FailOnRemote -and $remoteErr) { $rc = 3 }
exit $rc
