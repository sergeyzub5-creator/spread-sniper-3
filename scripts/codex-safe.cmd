@echo off
set SCRIPT_DIR=%~dp0
for %%I in ("%SCRIPT_DIR%..") do set PROJECT_ROOT=%%~fI
cd /d "%PROJECT_ROOT%"
codex --sandbox workspace-write --ask-for-approval untrusted --cd "%PROJECT_ROOT%" %*
