@echo off
REM SPDX-FileCopyrightText: Christian Pfeiffer
REM SPDX-License-Identifier: MIT
REM Runs safe-launch.ps1, which filters the command line and starts the game (see README.md).
REM install.cmd sets "...\safe-launch.cmd" %%command%% as the game's Steam launch options.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0safe-launch.ps1" %*
