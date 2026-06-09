@echo off
REM ───────────────────────────────────────────────────────────────────────────
REM e-con DepthVista Helix iToF — Isaac Sim installer (Windows)
REM
REM Clones/verifies the repo, locates Isaac Sim, and registers the econ.itof.menu extension
REM so the cameras appear under Create -> Sensors -> Camera and Depth Sensors -> e-con on
REM every launch. Pure Python — nothing to compile.
REM
REM Usage:
REM   build.bat                 - clone (if needed) + register
REM   build.bat <repo-url>      - override REPO_URL
REM   set REPO_URL=... & set INSTALL_DIR=... & set ISAACSIM_PATH=... & build.bat
REM ───────────────────────────────────────────────────────────────────────────
setlocal enabledelayedexpansion
set "SCRIPT_DIR=%~dp0"
if "%SCRIPT_DIR:~-1%"=="\" set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"

REM ── Configuration (override via env or 1st arg) ──────────────────────────────
if not defined REPO_URL set "REPO_URL=%~1"
if not defined REPO_URL set "REPO_URL=https://github.com/Thagasheriff64/econ-isaac-sim.git"
if not defined EXT_NAME set "EXT_NAME=econ.itof.menu"

REM If run from inside a clone (exts\<EXT_NAME> beside the script), install in place.
if not defined INSTALL_DIR (
    if exist "%SCRIPT_DIR%\exts\%EXT_NAME%" (
        set "INSTALL_DIR=%SCRIPT_DIR%"
    ) else (
        set "INSTALL_DIR=%USERPROFILE%\econ-isaac-sim"
    )
)

REM ── 1. Clone or update the repo ──────────────────────────────────────────────
where git >nul 2>&1
if errorlevel 1 (
    echo [ERROR] git is not installed. Install git and re-run.
    exit /b 1
)

if exist "%INSTALL_DIR%\.git" (
    echo [INFO] Updating existing clone at %INSTALL_DIR% ...
    git -C "%INSTALL_DIR%" pull --ff-only
) else if exist "%INSTALL_DIR%\exts\%EXT_NAME%" (
    echo [INFO] Running from inside the repo at %INSTALL_DIR% - skipping clone.
) else (
    echo [INFO] Cloning %REPO_URL% -^> %INSTALL_DIR% ...
    git clone "%REPO_URL%" "%INSTALL_DIR%"
    if errorlevel 1 (
        echo [ERROR] git clone failed.
        exit /b 1
    )
)

REM ── 2. Sanity-check the extension is present (do NOT build anything) ─────────
set "EXT_DIR=%INSTALL_DIR%\exts\%EXT_NAME%"
if not exist "%EXT_DIR%" (
    echo [ERROR] Extension not found at %EXT_DIR%.
    echo [ERROR] The cloned repo must contain exts\%EXT_NAME%\ ^(config\extension.toml + python^).
    exit /b 1
)
echo [INFO] Found extension: %EXT_DIR%

REM ── 3. Locate the Isaac Sim install (holds isaac-sim.bat) ────────────────────
if not defined ISAACSIM_PATH if defined ISAAC_SIM_PATH set "ISAACSIM_PATH=%ISAAC_SIM_PATH%"
REM Detection: env -> common locations -> ask the user. No machine-specific hard-coded path.
if not defined ISAACSIM_PATH (
    for %%D in (
        "%LOCALAPPDATA%\ov\pkg\isaac-sim-*"
        "%LOCALAPPDATA%\ov\pkg\isaac_sim-*"
        "%USERPROFILE%\isaacsim"
        "%USERPROFILE%\isaac-sim"
        "%USERPROFILE%\Downloads\isaacsim"
        "%USERPROFILE%\Downloads\isaac-sim*"
        "C:\isaacsim"
        "C:\isaac-sim"
    ) do (
        for /d %%P in (%%~D) do (
            if exist "%%~P\isaac-sim.bat" set "ISAACSIM_PATH=%%~P"
        )
        if not defined ISAACSIM_PATH if exist "%%~D\isaac-sim.bat" set "ISAACSIM_PATH=%%~D"
    )
)

:ask_isaac
if defined ISAACSIM_PATH if exist "%ISAACSIM_PATH%\isaac-sim.bat" goto :have_isaac
echo [WARN] Isaac Sim not auto-detected.
set "ISAACSIM_PATH="
set /p "ISAACSIM_PATH=Enter the Isaac Sim folder (contains isaac-sim.bat), or blank to abort: "
if not defined ISAACSIM_PATH echo [ERROR] Aborted - no Isaac Sim path given. & exit /b 1
if not exist "%ISAACSIM_PATH%\isaac-sim.bat" echo [ERROR] No isaac-sim.bat in "%ISAACSIM_PATH%". & goto :ask_isaac

:have_isaac
echo [INFO] Using Isaac Sim at: %ISAACSIM_PATH%

REM ── 4. Register so it auto-loads on every normal launch ──────────────────────
REM Copy the extension into <isaac>\extsUser (on the search path) and add it to the Full app's
REM .kit [dependencies], which Isaac reads fresh each launch (the persistent config is unreliable).
set "EXTSUSER=%ISAACSIM_PATH%\extsUser"
if not exist "%EXTSUSER%" mkdir "%EXTSUSER%"
echo [INFO] Copying extension into %EXTSUSER%\%EXT_NAME% ...
robocopy "%EXT_DIR%" "%EXTSUSER%\%EXT_NAME%" /MIR /NJH /NJS /NDL /NFL >nul

set "PYEXE="
where py  >nul 2>&1 && set "PYEXE=py"
if not defined PYEXE ( where python >nul 2>&1 && set "PYEXE=python" )
if not defined PYEXE echo [ERROR] python not found - needed to register the extension. & exit /b 1
"!PYEXE!" "%INSTALL_DIR%\scripts\patch_kit.py" "%ISAACSIM_PATH%\apps" "%EXT_NAME%" || ( echo [ERROR] Could not patch the Isaac Sim .kit files. & exit /b 1 )

REM ── 5. Done ──────────────────────────────────────────────────────────────────
echo.
echo [SUCCESS] e-con DepthVista Helix installed ^(auto-loads on every launch^).
echo.
echo   If Isaac Sim is open, fully close and reopen it. Launch normally - no special command.
echo   Then: Create -^> Sensors -^> Camera and Depth Sensors -^> e-con
echo           - DepthVista Helix iToF ^(USB^)
echo           - DepthVista Helix iToF ^(GMSL^)
echo.
echo   Uninstall (reverts everything): uninstall.bat
exit /b 0
