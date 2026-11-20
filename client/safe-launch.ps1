# SPDX-FileCopyrightText: Christian Pfeiffer
# SPDX-License-Identifier: MIT

# Starts Day of Infamy or Insurgency safely, for the Windows client: it drops the console commands a
# malicious Steam invite can smuggle onto the command line (+rcon and its kin, +host_writeconfig,
# +alias; see README.md), keeps the rest (+connect included), refreshes the game's
# cfg\server_blacklist.txt from a maintained list of spammy servers and blocklist-extra.txt next to
# this script, then starts the game. safe-launch.cmd runs it, which install.cmd sets as the game's
# Steam launch options. The blocklist is best effort; the game always starts.

$ErrorActionPreference = 'Continue'
$denied = @('rcon', 'rcon_address', 'rcon_password', 'rcon_port', 'host_writeconfig', 'host_writeconfig_ss', 'alias')
$blocklistUrl = if ($env:NWI_BLOCKLIST_URL) { $env:NWI_BLOCKLIST_URL } else { 'https://content.hl2dm.org/spamfilter/RogueIPs.txt' }

# Split the command line into the tokens to keep and the ones to drop. A denied +command's arguments
# are the tokens up to the next +command or -option.
$keep = [System.Collections.Generic.List[string]]::new()
$dropped = [System.Collections.Generic.List[string]]::new()
$dropping = $false
foreach ($token in $args) {
    if ($token.StartsWith('+')) {
        $dropping = $denied -contains $token.Substring(1).ToLower()
        if ($dropping) { $dropped.Add($token) } else { $keep.Add($token) }
    }
    elseif ($token.StartsWith('-')) {
        $dropping = $false
        $keep.Add($token)
    }
    else {
        if ($dropping) { $dropped.Add($token) } else { $keep.Add($token) }
    }
}

if ($keep.Count -eq 0) { exit }
if ($dropped.Count -gt 0) { [Console]::Error.WriteLine('safe-launch dropped: ' + ($dropped -join ' ')) }

# Refresh the game's server blocklist, best effort: any failure leaves it as it is.
function Write-Blocklist {
    $mod = $null
    for ($i = 0; $i -lt $keep.Count - 1; $i++) { if ($keep[$i] -eq '-game') { $mod = $keep[$i + 1]; break } }
    if (-not $mod) { return }
    $cfg = Join-Path (Split-Path -Parent $keep[0]) (Join-Path $mod 'cfg')
    if (-not (Test-Path -LiteralPath $cfg -PathType Container)) { return }
    $text = (Invoke-WebRequest -Uri $blocklistUrl -TimeoutSec 6 -UseBasicParsing).Content
    $extra = Join-Path $PSScriptRoot 'blocklist-extra.txt'
    if (Test-Path -LiteralPath $extra) { $text += "`n" + (Get-Content -LiteralPath $extra -Raw) }
    $ips = [System.Collections.Generic.List[string]]::new()
    foreach ($line in $text -split "`n") {
        $m = [regex]::Match(($line -split '#|//')[0], '\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b')
        if ($m.Success) { $ips.Add($m.Value) }
    }
    if ($ips.Count -eq 0) { return }
    $sorted = $ips | Sort-Object { [version]$_ } -Unique
    $now = [int][double]::Parse((Get-Date -UFormat %s))
    $out = [System.Text.StringBuilder]::new()
    [void]$out.AppendLine("// Written by safe-launch from $blocklistUrl and blocklist-extra.txt")
    [void]$out.AppendLine('"serverblacklist"'); [void]$out.AppendLine('{')
    foreach ($ip in $sorted) {
        [void]$out.AppendLine('    "server"'); [void]$out.AppendLine('    {')
        [void]$out.AppendLine("        `"name`"    `"Spamfilter $ip`"")
        [void]$out.AppendLine("        `"addr`"    `"$ip`"")
        [void]$out.AppendLine("        `"date`"    `"$now`""); [void]$out.AppendLine('    }')
    }
    [void]$out.AppendLine('}')
    Set-Content -LiteralPath (Join-Path $cfg 'server_blacklist.txt') -Value $out.ToString() -NoNewline -Encoding ascii
}
try { Write-Blocklist } catch { }

# Start the game with the kept tokens.
if ($keep.Count -gt 1) { & $keep[0] @($keep[1..($keep.Count - 1)]) } else { & $keep[0] }
