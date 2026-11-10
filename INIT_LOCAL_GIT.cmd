@echo off
setlocal EnableExtensions
cd /d "%~dp0" || goto :failed

where git >nul 2>nul
if errorlevel 1 (
    echo Git is not installed or not in PATH.
    echo Install Git for Windows: https://git-scm.com/downloads/win
    goto :failed
)

if not exist ".git\HEAD" (
    echo Initializing local Git repository on main...
    git init -b main
    if errorlevel 1 goto :failed
) else (
    echo Existing Git repository detected; leaving its history intact.
)

git remote get-url upstream >nul 2>nul
if errorlevel 1 (
    git remote add upstream https://github.com/horizon-rust/horizon.git
    if errorlevel 1 goto :failed
)

git config core.hooksPath .githooks
if errorlevel 1 goto :failed

echo.
echo Local Git is ready.
git branch --show-current
git remote -v
echo.
echo No git add, commit, fetch, clone or push was performed.
echo This is NOT a GitHub fork. See GIT_SETUP.md for publication steps.
echo.
pause
exit /b 0

:failed
echo.
echo Setup did not finish. Existing source files were not removed.
pause
exit /b 1
