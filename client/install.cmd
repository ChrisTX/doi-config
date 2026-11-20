@echo off
REM SPDX-FileCopyrightText: Christian Pfeiffer
REM SPDX-License-Identifier: MIT
REM Double-click to protect Day of Infamy and Insurgency: runs install.ps1 (see README.md).
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1"
echo.
pause
