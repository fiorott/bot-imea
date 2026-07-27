@echo off
REM ---------------------------------------------------------------
REM Cria o repositorio no GitHub e envia o projeto.
REM Execute uma unica vez. Depois disso, use os comandos git normais.
REM ---------------------------------------------------------------
setlocal
cd /d "%~dp0"

set "GH=gh"
where gh >nul 2>&1 || set "GH=C:\Program Files\GitHub CLI\gh.exe"

if not exist "%GH%" (
    where gh >nul 2>&1 || (
        echo GitHub CLI nao encontrado. Instale com: winget install GitHub.cli
        exit /b 1
    )
)

echo.
echo === 1/3 - Verificando o login no GitHub ===
"%GH%" auth status >nul 2>&1
if errorlevel 1 (
    echo Voce ainda nao esta autenticado. Abrindo o login...
    echo Escolha: GitHub.com  ^>  HTTPS  ^>  Login with a web browser
    "%GH%" auth login
    if errorlevel 1 (
        echo Login nao concluido. Execute novamente quando estiver pronto.
        exit /b 1
    )
)

echo.
echo === 2/3 - Criando o repositorio bot-imea ===
"%GH%" repo create bot-imea --private --source=. --remote=origin --description "Bot de coleta diaria dos indicadores do IMEA com saida para Power BI"
if errorlevel 1 (
    echo.
    echo O repositorio pode ja existir. Tentando apenas vincular...
    git remote remove origin 2>nul
    for /f "delims=" %%U in ('"%GH%" api user --jq .login') do set "USUARIO=%%U"
    git remote add origin https://github.com/%USUARIO%/bot-imea.git
)

echo.
echo === 3/3 - Enviando os arquivos ===
git push -u origin main
if errorlevel 1 (
    echo.
    echo Falha no envio. Verifique a mensagem acima.
    exit /b 1
)

echo.
echo ================================================================
echo  Projeto publicado com sucesso.
echo  Abrindo o repositorio no navegador...
echo ================================================================
"%GH%" repo view --web

endlocal
