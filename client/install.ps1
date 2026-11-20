# SPDX-FileCopyrightText: Christian Pfeiffer
# SPDX-License-Identifier: MIT

# Sets safe-launch.cmd as the Steam launch options of Day of Infamy and Insurgency on the Windows
# client, so the game runs through it (see README.md). install.cmd runs this. It finds the games
# Steam has installed, copies the wrapper to a folder of its own, writes each game's blocklist, and
# puts the wrapper before %command% in each game's launch options, keeping anything that's there. Run
# it with Steam closed, as Steam rewrites its config when it exits. It backs up the config it edits.

$ErrorActionPreference = 'Stop'
$games = @{ '447820' = @('dayofinfamy', 'doi'); '222880' = @('insurgency2', 'insurgency') }
$blocklistUrl = if ($env:NWI_BLOCKLIST_URL) { $env:NWI_BLOCKLIST_URL } else { 'https://content.hl2dm.org/spamfilter/RogueIPs.txt' }
$installDir = Join-Path $env:LOCALAPPDATA 'nwi-safe-launch'

function Get-SteamPath {
    if ($env:NWI_STEAM_ROOT) { return $env:NWI_STEAM_ROOT }
    try {
        $p = (Get-ItemProperty 'HKCU:\Software\Valve\Steam' -ErrorAction Stop).SteamPath
        if ($p) { return $p.Replace('/', '\') }
    }
    catch {}
    $default = "${env:ProgramFiles(x86)}\Steam"
    if (Test-Path $default) { return $default }
    return $null
}

function Get-Libraries($root) {
    $libs = @($root)
    $vdf = Join-Path $root 'steamapps\libraryfolders.vdf'
    if (Test-Path $vdf) {
        foreach ($m in [regex]::Matches((Get-Content -Raw $vdf), '"path"\s+"([^"]+)"')) {
            $libs += $m.Groups[1].Value.Replace('\\', '\')
        }
    }
    return $libs
}

function Set-LaunchOptions($text, $app, $insert) {
    # Set app's LaunchOptions so insert runs before %command%, changing only that line. Returns
    # @(status, newtext): 'changed', 'already' or 'absent'.
    $want = @('userlocalconfigstore', 'software', 'valve', 'steam', 'apps', $app.ToLower())
    $nl = if ($text.Contains("`r`n")) { "`r`n" } else { "`n" }
    $stack = [System.Collections.Generic.List[string]]::new()
    $pending = ''
    $out = [System.Collections.Generic.List[string]]::new()
    $entered = $false; $changed = $false; $seen = $false
    function InApp { ($stack.ToArray() | ForEach-Object { $_.ToLower() }) -join '/' -eq ($want -join '/') }
    foreach ($line in ($text -split "`n") | ForEach-Object { $_.TrimEnd("`r") }) {
        $pair = [regex]::Match($line, '^(\s*)"([^"]*)"(\s+)"(.*)"\s*$')
        if ($pair.Success -and (InApp) -and $pair.Groups[2].Value.ToLower() -eq 'launchoptions') {
            $seen = $true
            $value = $pair.Groups[4].Value
            if ($value.Contains($insert)) { $out.Add($line) }
            else {
                $new = if ($value.Contains('%command%')) { $value -replace [regex]::Escape('%command%'), ($insert + ' %command%') }
                elseif ($value -eq '') { $insert + ' %command%' } else { $insert + ' %command% ' + $value }
                $out.Add($pair.Groups[1].Value + '"' + $pair.Groups[2].Value + '"' + $pair.Groups[3].Value + '"' + $new + '"')
                $changed = $true
            }
            continue
        }
        $close = [regex]::Match($line, '^(\s*)\}\s*$')
        if ($close.Success -and (InApp) -and -not $seen) {
            $out.Add($close.Groups[1].Value + "`t`"LaunchOptions`"`t`t`"" + $insert + ' %command%"')
            $changed = $true
        }
        $key = [regex]::Match($line, '^(\s*)"([^"]*)"\s*$')
        if ($key.Success) { $pending = $key.Groups[2].Value }
        elseif ($line -match '^\s*\{\s*$') { $stack.Add($pending); if (InApp) { $entered = $true } }
        elseif ($close.Success) { if ($stack.Count) { $stack.RemoveAt($stack.Count - 1) } }
        $out.Add($line)
    }
    if ($changed) { return @('changed', ($out -join $nl) + $(if ($text.EndsWith("`n")) { $nl } else { '' })) }
    if ($entered) { return @('already', $null) }
    return @('absent', $null)
}

function Write-Blocklist($cfg) {
    $text = (Invoke-WebRequest -Uri $blocklistUrl -TimeoutSec 10 -UseBasicParsing).Content
    $extra = Join-Path $installDir 'blocklist-extra.txt'
    if (Test-Path $extra) { $text += "`n" + (Get-Content -Raw $extra) }
    $ips = [System.Collections.Generic.List[string]]::new()
    foreach ($line in $text -split "`n") {
        $m = [regex]::Match(($line -split '#|//')[0], '\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b')
        if ($m.Success) { $ips.Add($m.Value) }
    }
    $sorted = $ips | Sort-Object { [version]$_ } -Unique
    $now = [int][double]::Parse((Get-Date -UFormat %s))
    $sb = [System.Text.StringBuilder]::new()
    [void]$sb.AppendLine('// Written by nwi safe-launch'); [void]$sb.AppendLine('"serverblacklist"'); [void]$sb.AppendLine('{')
    foreach ($ip in $sorted) {
        [void]$sb.AppendLine('    "server"'); [void]$sb.AppendLine('    {')
        [void]$sb.AppendLine("        `"name`"    `"Spamfilter $ip`""); [void]$sb.AppendLine("        `"addr`"    `"$ip`"")
        [void]$sb.AppendLine('        "date"    "0"'); [void]$sb.AppendLine('    }')
    }
    [void]$sb.AppendLine('}')
    Set-Content -LiteralPath (Join-Path $cfg 'server_blacklist.txt') -Value $sb.ToString() -NoNewline -Encoding ascii
    return $sorted.Count
}

$root = Get-SteamPath
if (-not $root) { Write-Host 'Could not find Steam. Is it installed?'; return }
if (Get-Process -Name steam -ErrorAction SilentlyContinue) {
    Write-Host 'Steam is running, and would undo this when it exits. Close Steam fully (right-click the tray icon, Exit) and run this again.'
    return
}
New-Item -ItemType Directory -Force $installDir | Out-Null
foreach ($f in 'safe-launch.cmd', 'safe-launch.ps1', 'blocklist-extra.txt') {
    $src = Join-Path $PSScriptRoot $f
    if (Test-Path $src) { Copy-Item $src (Join-Path $installDir $f) -Force }
}
$wrapper = Join-Path $installDir 'safe-launch.cmd'
Write-Host "Installed the wrapper to $wrapper"
$insert = '\"' + $wrapper.Replace('\', '\\') + '\"'

$anyGame = $false
foreach ($app in $games.Keys) {
    $install, $mod = $games[$app]
    $name = if ($mod -eq 'doi') { 'Day of Infamy' } else { 'Insurgency' }
    $folder = $null
    foreach ($lib in Get-Libraries $root) {
        if (Test-Path (Join-Path $lib "steamapps\appmanifest_$app.acf")) {
            $folder = Join-Path $lib "steamapps\common\$install\$mod"
        }
    }
    if (-not $folder -or -not (Test-Path $folder)) { continue }
    $anyGame = $true
    try { $count = Write-Blocklist (Join-Path $folder 'cfg'); Write-Host "${name}: wrote $count servers to its blocklist" }
    catch { Write-Host "${name}: couldn't write the blocklist ($_)" }
    foreach ($config in Get-ChildItem "$root\userdata\*\config\localconfig.vdf" -ErrorAction SilentlyContinue) {
        $text = Get-Content -Raw $config
        if ($text -notmatch "`"$app`"") { continue }
        $status, $new = Set-LaunchOptions $text $app $insert
        if ($status -eq 'already') { Write-Host "${name}: launch options already set" }
        elseif ($status -eq 'absent') { Write-Host "${name}: no launch-options entry yet; start the game once from Steam, close it, then run this again" }
        elseif ($new) {
            Copy-Item $config "$($config.FullName).nwi-backup" -Force
            Set-Content -LiteralPath $config.FullName -Value $new -NoNewline -Encoding utf8
            Write-Host "${name}: set its launch options (backed up to $($config.Name).nwi-backup)"
        }
    }
}
if (-not $anyGame) { Write-Host 'Neither Day of Infamy nor Insurgency is installed in Steam.' }
else { Write-Host "`nDone. Start Steam and play as usual." }
