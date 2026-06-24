@echo off
if exist "%~dp0python.exe" (
  "%~dp0python.exe" -m divapply %*
) else (
  python -m divapply %*
)
