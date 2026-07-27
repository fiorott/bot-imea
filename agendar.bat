@echo off
REM ---------------------------------------------------------------
REM Cria a tarefa diaria no Agendador de Tarefas do Windows.
REM NAO exige privilegio de administrador: a tarefa roda com o seu
REM usuario, apenas quando voce estiver conectado.
REM
REM Uso:  agendar.bat          -> agenda para as 08:00
REM       agendar.bat 07:30    -> agenda para o horario informado
REM ---------------------------------------------------------------
setlocal
cd /d "%~dp0"

set "HORARIO=%~1"
if "%HORARIO%"=="" set "HORARIO=08:00"

set "NOME_TAREFA=BotIMEA_Indicadores"

echo.
echo Criando a tarefa "%NOME_TAREFA%" para rodar todos os dias as %HORARIO%.
echo Pasta do projeto: %cd%
echo.

schtasks /Create ^
    /TN "%NOME_TAREFA%" ^
    /TR "\"%cd%\run_bot.bat\"" ^
    /SC DAILY ^
    /ST %HORARIO% ^
    /F

if %errorlevel% neq 0 (
    echo.
    echo Nao foi possivel criar a tarefa. Verifique a mensagem acima.
    exit /b %errorlevel%
)

echo.
echo Tarefa criada com sucesso.
echo.
echo Comandos uteis:
echo   Executar agora : schtasks /Run    /TN "%NOME_TAREFA%"
echo   Ver situacao   : schtasks /Query  /TN "%NOME_TAREFA%" /V /FO LIST
echo   Remover        : schtasks /Delete /TN "%NOME_TAREFA%" /F
echo.
endlocal
