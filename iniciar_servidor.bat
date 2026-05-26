@echo off
title EKopy Server
echo ==================================================
echo           INICIANDO O SERVIDOR EKOPY
echo ==================================================
echo.
cd /d "%~dp0"
venv\Scripts\python main.py
if %errorlevel% neq 0 (
    echo.
    echo [ERRO] O servidor parou inesperadamente.
    pause
)
