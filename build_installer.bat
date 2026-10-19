@echo off
REM Fixbot Installer Builder
REM Requires Inno Setup to be installed: https://jrsoftware.org/isdl.php

REM Try common ISCC installation paths
set "ISCC="
if exist "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" (
    set "ISCC=C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
) else if exist "C:\Program Files\Inno Setup 6\ISCC.exe" (
    set "ISCC=C:\Program Files\Inno Setup 6\ISCC.exe"
) else if exist "C:\Program Files (x86)\Inno Setup 5\ISCC.exe" (
    set "ISCC=C:\Program Files (x86)\Inno Setup 5\ISCC.exe"
) else if exist "C:\Program Files\Inno Setup 5\ISCC.exe" (
    set "ISCC=C:\Program Files\Inno Setup 5\ISCC.exe"
)

if not defined ISCC (
    echo [!] Inno Setup Compiler not found!
    echo [!] Please install Inno Setup from: https://jrsoftware.org/isdl.php
    echo.
    echo Or manually run:
    echo   "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer_x86.iss
    exit /b 1
)

setlocal enabledelayedexpansion

echo [*] Found ISCC at: %ISCC%
echo.

echo [*] Compiling 32-bit installer...
"%ISCC%" installer_x86.iss
if %ERRORLEVEL% EQU 0 (
    echo [?] x86 installer compiled: installer_output\FixbotAI_x86_Setup.exe
) else (
    echo [!] x86 installer compilation failed!
    exit /b 1
)

echo.
echo [?] Installer compilation complete!

endlocal
