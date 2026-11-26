@echo off
setlocal

REM ============================================================
REM  INICIAR MAX
REM  Este ficheiro:
REM    1) Verifica se o Ollama já está a correr; se não, arranca-o
REM       numa janela separada.
REM    2) Corre o max.py com o Python correto (o da Microsoft
REM       Store, onde os pacotes foram instalados), independentemente
REM       de qual "python" estiver primeiro no PATH.
REM ============================================================

REM --- Caminho para o Python correto (ajusta se for diferente no teu PC) ---
set PYTHON_EXE=C:\Users\rodri\AppData\Local\Microsoft\WindowsApps\python.exe

REM --- Pasta onde este .bat e o max.py estão guardados ---
cd /d "%~dp0"

echo ============================================
echo   A verificar se o Ollama esta a correr...
echo ============================================

REM Testa se o servidor do Ollama já responde em localhost:11434
curl -s -o nul -w "%%{http_code}" http://127.0.0.1:11434 > "%TEMP%\ollama_status.txt" 2>nul
set /p OLLAMA_STATUS=<"%TEMP%\ollama_status.txt"

if "%OLLAMA_STATUS%"=="200" (
    echo Ollama ja esta a correr. A avancar...
) else (
    echo Ollama nao esta a correr. A arrancar numa janela separada...
    start "Ollama Server" ollama serve
    echo A aguardar o Ollama arrancar...
    timeout /t 5 /nobreak > nul
)

echo.
echo ============================================
echo   A arrancar o MAX...
echo ============================================
echo.

"%PYTHON_EXE%" max.py

echo.
echo MAX terminou. Pressiona uma tecla para fechar esta janela.
pause > nul
