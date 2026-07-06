@echo off
title MegaEmbed Scraper
cd /d "%~dp0"
cls
echo ============================================================
echo   MegaEmbed Scraper
echo   Extrator de links diretos de filmes
echo ============================================================
echo.
python mega_scraper.py
if %errorlevel% neq 0 (
    echo.
    echo [!] Ocorreu um erro. Verifique se o Python esta instalado.
    echo [!] Instale em: https://www.python.org/downloads/
    echo.
)
echo.
pause
