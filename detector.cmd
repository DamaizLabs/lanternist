@echo off
rem El detector de la marca de IA en una pagina local, para quien no usa un terminal: un doble clic lo arranca y abre
rem el navegador, y cerrar esta ventana lo para. Lo explica docs\ai-marking.md, en "Checking a file".
title Lanternist AI mark detector
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Lanternist is not installed in this folder yet: install it with instala.py, then open detector.cmd again.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" scripts\detector_web.py
if errorlevel 1 pause
