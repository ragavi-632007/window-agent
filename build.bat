@echo off
REM Fixbot Windows Executable Builder
REM This script uses PyInstaller to bundle sysdoc/main.py with all dependencies

setlocal enabledelayedexpansion

if /I "%~1"=="x64" (
    echo [!] Warning: This repository has been migrated to x86-only.
    echo [!] Defaulting to 32-bit (x86) build targets...
    echo.
)

set "VENV=.venv32"
set "EXE_NAME=Fixbot_x86"
set "DIST=dist32"
set "BUILD=build32"

REM Activate virtual environment
if not exist "%VENV%\Scripts\activate.bat" (
    echo [!] Virtual environment "%VENV%" not found.
    echo [!] Create it first or pass the other build target.
    exit /b 1
)
call "%VENV%\Scripts\activate.bat"

echo [*] Ensuring PyInstaller is installed...
python -m pip install pyinstaller --quiet

echo [*] Installing runtime requirements...
python -m pip install -r sysdoc\requirements.txt --quiet

echo [*] Building %EXE_NAME%...
echo.

REM Main PyInstaller command with all required flags
python -m PyInstaller ^
  --clean ^
  --name=%EXE_NAME% ^
  --onefile ^
  --console ^
  --add-data="sysdoc\.env;sysdoc" ^
  --add-data="sysdoc\core;sysdoc\core" ^
  --add-data="sysdoc\display;sysdoc\display" ^
  --add-data="sysdoc\games;sysdoc\games" ^
  --add-data="sysdoc\gitpilot;sysdoc\gitpilot" ^
  --add-data="sysdoc\modules;sysdoc\modules" ^
  --add-data="sysdoc\tickets;sysdoc\tickets" ^
  --collect-all=prompt_toolkit ^
  --collect-all=rich ^
  --collect-all=google.generativeai ^
  --hidden-import=google.generativeai ^
  --hidden-import=prompt_toolkit ^
  --hidden-import=rich ^
  --hidden-import=psutil ^
  --hidden-import=wmi ^
  --hidden-import=winshell ^
  --hidden-import=sysdoc.core.conversation_memory ^
  --hidden-import=sysdoc.core.executor ^
  --hidden-import=sysdoc.core.gemini_client ^
  --hidden-import=sysdoc.core.intent_engine ^
  --hidden-import=sysdoc.core.permission_gate ^
  --hidden-import=sysdoc.core.prompt_builder ^
  --hidden-import=sysdoc.core.report_generator ^
  --hidden-import=sysdoc.core.verifier ^
  --hidden-import=sysdoc.display.animations ^
  --hidden-import=sysdoc.display.banner ^
  --hidden-import=sysdoc.display.formatter ^
  --hidden-import=sysdoc.games.ticket_rush ^
  --hidden-import=sysdoc.gitpilot.ai_helper ^
  --hidden-import=sysdoc.gitpilot.config ^
  --hidden-import=sysdoc.gitpilot.git_ops ^
  --hidden-import=sysdoc.gitpilot.main ^
  --hidden-import=sysdoc.modules.dev_env ^
  --hidden-import=sysdoc.modules.file_finder ^
  --hidden-import=sysdoc.modules.installer ^
  --hidden-import=sysdoc.modules.network ^
  --hidden-import=sysdoc.modules.storage ^
  --hidden-import=sysdoc.modules.system_health ^
  --hidden-import=sysdoc.modules.updater ^
  --hidden-import=sysdoc.tickets.ticket_manager ^
  --distpath=%DIST% ^
  --workpath=%BUILD% ^
  --specpath=. ^
  sysdoc\main.py

if %ERRORLEVEL% EQU 0 (
    echo.
    echo [?] Build complete!
    echo [?] Output: %DIST%\%EXE_NAME%.exe
    echo.
    echo Next step: Compile installer.iss with Inno Setup
) else (
    echo.
    echo [?] Build failed!
    echo [?] Check output above for errors.
    exit /b 1
)

endlocal
