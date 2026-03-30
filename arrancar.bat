@echo off
title TingBot Noctorial
echo.
echo  ========================================
echo   TINGBOT NOCTORIAL - Arrancando...
echo  ========================================
echo.

:: Cargar variables desde .env
for /f "usebackq tokens=1,2 delims==" %%a in (".env") do (
    echo %%a | findstr /r "^[^#]" >nul 2>&1 && set "%%a=%%b"
)

echo  Cuenta:    57366
echo  Servidor:  Noctorial-Trade
echo  Horario:   17:00 - 22:00 (Espana)
echo  Pares:     XAUUSD, TSLA, NVDA, AAPL
echo.
echo  Asegurate de que MT5 esta abierto y conectado.
echo  Pulsa cualquier tecla para arrancar...
pause > nul

python runner_mt5_noctorial.py

echo.
echo  Bot finalizado.
pause
