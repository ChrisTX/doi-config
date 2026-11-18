@echo off
REM SPDX-FileCopyrightText: Christian Pfeiffer
REM SPDX-License-Identifier: MIT

REM Drops the console commands a malicious Steam invite can smuggle onto the game's command line (see
REM client\README.md), then starts the game with the rest. Day of Infamy and Insurgency take +commands
REM from their command line, and an invite's connect string is appended to it, so an invite can point
REM the client's RCON client at a server of the attacker's (+rcon_address, +rcon) or write to the
REM client's config (+host_writeconfig). This wrapper removes those, as a client never needs them, and
REM passes everything else on, +connect included, so invites and the launch options still work.
REM
REM Set it as the game's launch options in Steam (Properties, General), with %%command%% after it:
REM     "C:\path\to\safe-launch.cmd" %%command%%

setlocal enabledelayedexpansion
set "KEEP="
set "DROPPED="
set "DROP=0"

:loop
if "%~1"=="" goto run
set "TOKEN=%~1"
set "FIRST=!TOKEN:~0,1!"
if "!FIRST!"=="+" (
	set "DROP=0"
	call :denied "!TOKEN!"
) else if "!FIRST!"=="-" (
	set "DROP=0"
)
if "!DROP!"=="1" (
	set "DROPPED=!DROPPED! %1"
) else (
	set "KEEP=!KEEP! %1"
)
shift
goto loop

REM The +commands a client never needs, which an invite abuses: deny the token and, through DROP, its
REM arguments up to the next +command or -option.
:denied
if /i "%~1"=="+rcon" set "DROP=1"
if /i "%~1"=="+rcon_address" set "DROP=1"
if /i "%~1"=="+rcon_password" set "DROP=1"
if /i "%~1"=="+rcon_port" set "DROP=1"
if /i "%~1"=="+host_writeconfig" set "DROP=1"
if /i "%~1"=="+host_writeconfig_ss" set "DROP=1"
if /i "%~1"=="+alias" set "DROP=1"
goto :eof

:run
if not "!DROPPED!"=="" echo safe-launch dropped:!DROPPED!>&2
endlocal & %KEEP%
