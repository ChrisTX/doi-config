# SPDX-FileCopyrightText: Christian Pfeiffer
# SPDX-License-Identifier: MIT

# PSScriptAnalyzer settings for the PowerShell scripts (client/*.ps1), used by
# checks/psscriptanalyzer.ps1. The default rules run, minus a few that are about designing a reusable
# PowerShell module and its exported cmdlets. These scripts are standalone, interactive end-user tools
# -- install.cmd runs install.ps1, and safe-launch.cmd runs safe-launch.ps1 as the game's Steam launch
# options -- not a module, so for them console output with Write-Host and plural, positional internal
# helpers are fine, and ShouldProcess (-WhatIf/-Confirm) plumbing on an internal helper isn't wanted.
# The rules that catch real problems (unused variables, empty catch blocks, and the rest) still run.
@{
    IncludeDefaultRules = $true
    ExcludeRules        = @(
        'PSAvoidUsingWriteHost'
        'PSUseSingularNouns'
        'PSUseShouldProcessForStateChangingFunctions'
        'PSAvoidUsingPositionalParameters'
    )
}
