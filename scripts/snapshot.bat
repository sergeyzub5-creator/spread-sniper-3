@echo off
powershell -ExecutionPolicy Bypass -File "%~dp0snapshot.ps1" %*
