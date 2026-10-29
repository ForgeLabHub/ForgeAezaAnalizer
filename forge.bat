@echo off
setlocal EnableDelayedExpansion
chcp 65001 >nul 2>&1
title ForgeAezaAnalizer — управление проектом

rem ForgeAezaAnalizer — управление проектом для Windows.
rem Зеркало forge.sh: те же команды, нативная реализация без bash.
rem   forge.bat              меню
rem   forge.bat help         список команд
rem   forge.bat start        запуск в фоне + открыть браузер
rem   forge.bat status       что запущено

cd /d "%~dp0"
set "NAME=ForgeAezaAnalizer"
set "PORT=8000"
set "FRONTEND_PORT=5173"
set "URL=http://localhost:8000/api/v1/docs"
set "ROOT=%CD%"
set "RUN=%ROOT%\.run"
if not exist "%RUN%" mkdir "%RUN%"
set "PY=.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"

set "CMD=%~1"
if "%CMD%"=="" set "CMD=menu"
shift >nul 2>&1

if /i "%CMD%"=="help"   goto :help
if /i "%CMD%"=="-h"     goto :help
if /i "%CMD%"=="--help" goto :help
if /i "%CMD%"=="menu"   goto :menu
if /i "%CMD%"=="status" goto :status
if /i "%CMD%"=="start"  goto :start
if /i "%CMD%"=="stop"   goto :stop
if /i "%CMD%"=="restart" goto :restart
if /i "%CMD%"=="doctor" goto :doctor
if /i "%CMD%"=="install" goto :install
if /i "%CMD%"=="setup"  goto :install
if /i "%CMD%"=="test"   goto :test
if /i "%CMD%"=="lint"   goto :lint
if /i "%CMD%"=="build"  goto :build
if /i "%CMD%"=="verify" goto :verify
if /i "%CMD%"=="logs"   goto :logs
if /i "%CMD%"=="open"   goto :open
if /i "%CMD%"=="db"     goto :db
if /i "%CMD%"=="docker" goto :docker
if /i "%CMD%"=="clean"  goto :clean
if /i "%CMD%"=="version" goto :version

echo Неизвестная команда: %CMD%
goto :help

:help
echo.
echo   ForgeAezaAnalizer — управление проектом
echo.
echo   forge.bat [команда]
echo.
echo   status    что запущено              test     тесты
echo   start     запустить                lint     статический анализ
echo   stop      остановить               build    собрать
echo   restart   перезапустить            verify   lint+test+docs
echo   logs      логи (logs имя)          doctor   проверка окружения
echo   open      открыть в браузере       install  зависимости
echo   db backup^|restore  база            clean    убрать артефакты
echo   docker up^|down^|logs              version  версия
echo.
exit /b 0

:menu
cls
echo.
echo   ForgeAezaAnalizer
echo   ----------------------------------------
echo    1^) status          7^) build
echo    2^) start           8^) verify
echo    3^) stop            9^) docker up
echo    4^) restart        10^) docker down
echo    5^) logs           11^) db migrate
echo    6^) test           12^) doctor
echo   13^) backup базы        14^) smoke-test
echo    0^) выход
echo.
set /p "CH=выбор: "
if "%CH%"=="1" goto :status
if "%CH%"=="2" goto :start
if "%CH%"=="3" goto :stop
if "%CH%"=="4" goto :restart
if "%CH%"=="5" goto :logs
if "%CH%"=="6" goto :test
if "%CH%"=="7" goto :build
if "%CH%"=="8" goto :verify
if "%CH%"=="9" ( call "%~f0" docker up & goto :menu )
if "%CH%"=="10" ( call "%~f0" docker down & goto :menu )
if "%CH%"=="11" ( call "%~f0" db migrate & goto :menu )
if "%CH%"=="12" goto :doctor
if "%CH%"=="13" ( call "%~f0" db backup & goto :menu )
if "%CH%"=="14" ( make smoke-test & goto :menu )
if "%CH%"=="0" exit /b 0
goto :menu

:doctor
echo.
echo   Окружение
where python >nul 2>&1 && ( echo   ok    python найден ) || echo   fail  python не найден
if exist "%PY%" ( echo   ok    %PY% ) else ( echo   warn  .venv нет — forge.bat install )
if exist .env ( echo   ok    .env на месте ) else ( echo   warn  .env нет — см. .env.example )
if exist .git (
  git ls-files --error-unmatch .env >nul 2>&1 && ( echo   fail  .env отслеживается git ) || ( echo   ok    .env не отслеживается git )
)
netstat -ano | findstr /r /c:":%PORT% .*LISTENING" >nul 2>&1 && ( echo   warn  порт %PORT% занят ) || ( echo   ok    порт %PORT% свободен )
exit /b 0

:status
echo.
echo   ForgeAezaAnalizer
if exist "%RUN%\*.pid" (
  for %%f in ("%RUN%\*.pid") do (
    set "P=%%~nf"
    set /p PID=<"%%f"
    tasklist /FI "PID eq !PID!" 2>nul | findstr /i "!PID!" >nul && echo   ok    !P! запущен ^(pid !PID!^) || echo   warn  !P! не запущен
  )
) else (
  echo   warn  ничего не запущено — forge.bat start
)
netstat -ano | findstr /r /c:":%PORT% .*LISTENING" >nul 2>&1 && echo   ok    порт %PORT% слушается || echo   warn  порт %PORT% свободен
exit /b 0

:start
call :start_services
timeout /t 2 /nobreak >nul
start "" "%URL%"
goto :status

:start_services
set "SVC=api"
set "ARGS=-m uvicorn main:app --host 127.0.0.1 --port %PORT%"
set "WD="
if not exist "%PY%" (
  echo   fail  python не найден — forge.bat install
  exit /b 1
)
powershell -NoProfile -Command ^
  "$p = Start-Process -FilePath '%PY%' -ArgumentList '%ARGS%' -WorkingDirectory '%ROOT%%WD%' -RedirectStandardOutput '%RUN%\%SVC%.log' -RedirectStandardError '%RUN%\%SVC%.err.log' -PassThru -WindowStyle Hidden; $p.Id | Out-File -Encoding ascii '%RUN%\%SVC%.pid'"
echo   ok    %SVC% запущен
if exist frontend\node_modules (
  start "web" cmd /c "cd frontend && npm run dev"
  echo   ok    web запущен ^(порт %FRONTEND_PORT%^)
)
exit /b 0

:stop
if exist "%RUN%\*.pid" (
  for %%f in ("%RUN%\*.pid") do (
    set "P=%%~nf"
    set /p PID=<"%%f"
    taskkill /PID !PID! /T /F >nul 2>&1 && echo   ok    !P! остановлен || echo   warn  !P! уже не работал
    del /q "%%f" >nul 2>&1
  )
)
echo   ok    остановлено
exit /b 0

:restart
call :stop
call :start_services
goto :status

:logs
set "L=%~1"
if "%L%"=="" (
  for %%f in ("%RUN%\*.log") do ( echo. & echo   --- %%~nxf & powershell -NoProfile -Command "Get-Content -Tail 30 '%%f'" )
) else (
  powershell -NoProfile -Command "Get-Content -Tail 50 -Wait '%RUN%\%L%.log'"
)
exit /b 0

:open
start "" "%URL%"
start "" "http://localhost:%FRONTEND_PORT%" >nul 2>&1
exit /b 0

:install
if not exist .venv python -m venv .venv
call .venv\Scripts\python.exe -m pip install -q --upgrade pip
call .venv\Scripts\pip.exe install -q -r backend\requirements.lock.txt
make doctor
exit /b 0

:test
call .venv\Scripts\python.exe -m pytest backend\tests -q
exit /b 0

:lint
call .venv\Scripts\python.exe backend\scripts\export_openapi.py --check
call .venv\Scripts\python.exe backend\scripts\check_docs.py
exit /b 0

:build
make build
exit /b 0

:verify
call :lint
call :test
make docs-check
exit /b 0

:db
if /i "%~1"=="backup" make backup
if /i "%~1"=="restore" make restore
exit /b 0

:docker
exit /b 0

:clean
if exist "%RUN%" rmdir /s /q "%RUN%"
echo   ok    артефакты и логи удалены ^(.venv и node_modules сохранены^)
exit /b 0

:version
echo   ForgeAezaAnalizer
if exist .git for /f %%i in ('git rev-parse --short HEAD 2^>nul') do echo   коммит: %%i
echo   скрипт: forge.bat v1.0
exit /b 0
