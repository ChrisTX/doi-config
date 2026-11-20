#!/usr/bin/env pwsh
# SPDX-FileCopyrightText: Christian Pfeiffer
# SPDX-License-Identifier: MIT

# Checks the PowerShell scripts given as arguments with PSScriptAnalyzer, the way shellcheck checks the
# shell scripts, with the rules of PSScriptAnalyzerSettings.psd1 next to this file. Any finding fails
# the check. The git hooks and GitHub Actions run it (.pre-commit-config.yaml).

$ErrorActionPreference = 'Stop'
$settings = Join-Path $PSScriptRoot 'PSScriptAnalyzerSettings.psd1'
$findings = foreach ($file in $args) {
    Invoke-ScriptAnalyzer -Path $file -Settings $settings
}
if ($findings) {
    $findings | Format-Table -AutoSize RuleName, Severity, ScriptName, Line, Message
    exit 1
}
