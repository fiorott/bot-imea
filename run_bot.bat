@echo off
REM ---------------------------------------------------------------
REM Executa o Bot IMEA. Usado tambem pelo Agendador de Tarefas.
REM ---------------------------------------------------------------
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
    set "PY=.venv\Scripts\python.exe"
) else (
    set "PY=python"
)

echo [%date% %time%] Iniciando o Bot IMEA...
"%PY%" main.py %*
set CODIGO=%errorlevel%

if %CODIGO% neq 0 (
    echo [%date% %time%] Bot finalizado COM ERRO. Consulte a pasta logs.
) else (
    echo [%date% %time%] Bot finalizado com sucesso.
)

exit /b %CODIGO%
