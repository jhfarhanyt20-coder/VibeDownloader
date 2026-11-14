@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title Build VibeDownloader Full Installer

rem Bootstrap build-only tools locally: no winget/choco/scoop and no admin install.
set "BUILD_HOME=%LOCALAPPDATA%\VibeDownloaderBuildTools"
set "PY_HOME=%BUILD_HOME%\Python313"
set "PY_EXE=%PY_HOME%\python.exe"
set "PY_INSTALLER=%BUILD_HOME%\python-3.13.17-amd64.exe"
set "PY_URL=https://www.python.org/ftp/python/3.13.17/python-3.13.17-amd64.exe"
set "NSIS_HOME=%BUILD_HOME%\NSIS-3.13"
set "NSIS_ZIP=%BUILD_HOME%\nsis-3.13.zip"
set "NSIS_URL=https://downloads.sourceforge.net/project/nsis/NSIS%%203/3.13/nsis-3.13.zip"
set "NSIS_EXE="

if not defined LOCALAPPDATA (
  echo ERROR: LOCALAPPDATA is unavailable. Please run this from a normal Windows user account.
  pause
  exit /b 1
)

if /i "%PROCESSOR_ARCHITECTURE%"=="x86" if not defined PROCESSOR_ARCHITEW6432 (
  echo ERROR: Build VibeDownloader on Windows x64, not 32-bit Windows.
  pause
  exit /b 1
)

if not exist "%BUILD_HOME%" mkdir "%BUILD_HOME%"
if errorlevel 1 goto :fail

echo ============================================================
echo  VibeDownloader - self-contained Windows x64 installer
echo ============================================================
echo Build tools will be stored locally in:
echo   %BUILD_HOME%
echo They are only used to build the installer; end users do not need them.
echo.

rem Use a private Python install so an existing Python 3.15 setup is not changed.
if exist "%PY_EXE%" goto :python_ready

echo [0/4] Downloading Python 3.13.17 x64 from python.org...
if not exist "%PY_INSTALLER%" (
  powershell -NoProfile -ExecutionPolicy Bypass -Command "$ProgressPreference='SilentlyContinue'; [Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -UseBasicParsing -Uri '%PY_URL%' -OutFile '%PY_INSTALLER%'"
  if errorlevel 1 (
    echo ERROR: Could not download the official Python installer. Check internet access and try again.
    goto :fail
  )
)

for %%F in ("%PY_INSTALLER%") do if %%~zF LSS 10000000 (
  echo ERROR: The downloaded Python installer is too small and may be incomplete.
  del /q "%PY_INSTALLER%" >nul 2>&1
  goto :fail
)

echo Installing Python privately under the current user's AppData; PATH and system Python are unchanged...
"%PY_INSTALLER%" /quiet InstallAllUsers=0 TargetDir="%PY_HOME%" Include_pip=1 Include_launcher=0 Include_test=0 PrependPath=0 Shortcuts=0
if errorlevel 1 goto :fail
if not exist "%PY_EXE%" (
  echo ERROR: Python installation did not create %PY_EXE%
  goto :fail
)

:python_ready
echo Using build Python:
"%PY_EXE%" --version
if errorlevel 1 goto :fail
"%PY_EXE%" -c "import sys; assert sys.maxsize > 2**32, '64-bit Python required'"
if errorlevel 1 goto :fail

rem Reuse an installed NSIS if possible; otherwise download the official portable ZIP.
where makensis >nul 2>&1
if not errorlevel 1 set "NSIS_EXE=makensis"
if not defined NSIS_EXE if exist "%ProgramFiles(x86)%\NSIS\makensis.exe" set "NSIS_EXE=%ProgramFiles(x86)%\NSIS\makensis.exe"
if not defined NSIS_EXE if exist "%ProgramFiles%\NSIS\makensis.exe" set "NSIS_EXE=%ProgramFiles%\NSIS\makensis.exe"
if defined NSIS_EXE goto :nsis_ready
if exist "%NSIS_HOME%\makensis.exe" set "NSIS_EXE=%NSIS_HOME%\makensis.exe"
if defined NSIS_EXE goto :nsis_ready

if not exist "%NSIS_HOME%" mkdir "%NSIS_HOME%"
if errorlevel 1 goto :fail
echo.
echo [0/4] Downloading portable NSIS 3.13 from SourceForge...
if not exist "%NSIS_ZIP%" (
  powershell -NoProfile -ExecutionPolicy Bypass -Command "$ProgressPreference='SilentlyContinue'; [Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -UseBasicParsing -Uri '%NSIS_URL%' -OutFile '%NSIS_ZIP%'"
  if errorlevel 1 (
    echo ERROR: Could not download NSIS. Check internet access and try again.
    goto :fail
  )
)
for %%F in ("%NSIS_ZIP%") do if %%~zF LSS 1000000 (
  echo ERROR: The downloaded NSIS ZIP is too small and may be incomplete.
  del /q "%NSIS_ZIP%" >nul 2>&1
  goto :fail
)
powershell -NoProfile -ExecutionPolicy Bypass -Command "Expand-Archive -LiteralPath '%NSIS_ZIP%' -DestinationPath '%NSIS_HOME%' -Force"
if errorlevel 1 goto :fail
if exist "%NSIS_HOME%\makensis.exe" set "NSIS_EXE=%NSIS_HOME%\makensis.exe"
if not defined NSIS_EXE for /r "%NSIS_HOME%" %%F in (makensis.exe) do set "NSIS_EXE=%%F"
if not defined NSIS_EXE (
  echo ERROR: makensis.exe was not found in the downloaded NSIS archive.
  goto :fail
)

:nsis_ready
echo Using NSIS compiler: %NSIS_EXE%

echo.
echo [1/4] Installing build dependencies and running checks...
"%PY_EXE%" -m ensurepip --upgrade
if errorlevel 1 goto :fail
"%PY_EXE%" -m pip install --upgrade pip
if errorlevel 1 goto :fail
"%PY_EXE%" -m pip install -r requirements-build.txt
if errorlevel 1 goto :fail
"%PY_EXE%" -m py_compile main.py downloader.py yt_helper.py prepare_build.py
if errorlevel 1 goto :fail
"%PY_EXE%" -m unittest discover -s tests -v
if errorlevel 1 goto :fail

echo.
echo [2/4] Preparing bundled assets. This downloads yt-dlp and FFmpeg for the installer...
"%PY_EXE%" prepare_build.py
if errorlevel 1 goto :fail

echo.
echo [3/4] Building the self-contained app executable...
"%PY_EXE%" -m PyInstaller --clean --noconfirm VibeDownloader.spec
if errorlevel 1 goto :fail
if not exist "dist\VibeDownloader.exe" (
  echo ERROR: PyInstaller did not create dist\VibeDownloader.exe
  goto :fail
)

echo.
echo [4/4] Compiling the NSIS installer...
"%NSIS_EXE%" /V2 installer.nsi
if errorlevel 1 goto :fail
if not exist "VibeDownloader_Installer.exe" goto :fail

echo.
echo SUCCESS! One installer created:
echo   %CD%\VibeDownloader_Installer.exe
echo It bundles the app, Python runtime, UI packages, FFmpeg, FFprobe, yt-dlp and extension files.
echo End users do not need Python, pip, FFmpeg, or yt-dlp installed separately.
echo Build-only tools are kept in %BUILD_HOME%.
echo.
pause
exit /b 0

:fail
echo.
echo BUILD FAILED. Read the error above and fix that step before distributing.
pause
exit /b 1
