@echo off
title Fun Police Discord Bot

:: Change to the directory where the script is located
cd /d %~dp0

:: Set path to your virtual environment
SET VENV_FOLDER=venv
SET VENV_PATH=%VENV_FOLDER%\Scripts\activate.bat
SET BOT_SCRIPT=funpolice.py

:: Colors for console output (Note: Requires ANSI support in cmd)
SET RED=[91m
SET GREEN=[92m
SET YELLOW=[93m
SET BLUE=[94m
SET MAGENTA=[95m
SET CYAN=[96m
SET WHITE=[97m
SET RESET=[0m

echo %CYAN%===============================================%RESET%
echo %CYAN%    Fun Police Discord Bot - Auto Restarter    %RESET%
echo %CYAN%===============================================%RESET%

:: Check if bot script exists
if not exist %BOT_SCRIPT% (
    echo %RED%Error: %BOT_SCRIPT% not found!%RESET%
    echo %YELLOW%Please make sure the bot script exists in this directory.%RESET%
    pause
    exit /b 1
)

:: Check if config.json exists
if not exist config.json (
    echo %RED%Error: config.json not found!%RESET%
    echo %YELLOW%Please make sure config.json exists in this directory.%RESET%
    pause
    exit /b 1
)

:: Check if secrets.json exists, if not, prompt for API key and create it
if not exist secrets.json (
    echo %YELLOW%secrets.json not found. Please enter your Discord application API key:%RESET%
    set /p BOT_TOKEN=
    if "%BOT_TOKEN%"=="" (
        echo %RED%Error: API key cannot be empty.%RESET%
        pause
        exit /b 1
    )
    echo { "BOT_TOKEN": "%BOT_TOKEN%" } > secrets.json
    echo %GREEN%secrets.json created successfully.%RESET%
)

:: Check if venv exists, if not, create it and install dependencies
if not exist %VENV_FOLDER% (
    echo %YELLOW%Virtual environment not found. Setting up for first time use...%RESET%
    
    :: Check if Python is installed
    python --version >nul 2>&1
    if %errorlevel% neq 0 (
        echo %RED%Error: Python is not installed or not in PATH%RESET%
        echo %YELLOW%Please install Python 3.8 or higher and try again.%RESET%
        pause
        exit /b 1
    )
    
    echo %CYAN%------------------------------------------------%RESET%
    echo %GREEN%Creating virtual environment...%RESET%
    python -m venv %VENV_FOLDER%
    
    if %errorlevel% neq 0 (
        echo %RED%Failed to create virtual environment.%RESET%
        pause
        exit /b 1
    )
    
    echo %GREEN%Installing required packages...%RESET%
    call %VENV_PATH% && python -m pip install --upgrade pip && pip install discord.py
    
    if %errorlevel% neq 0 (
        echo %RED%Failed to install dependencies.%RESET%
        pause
        exit /b 1
    )
    
    echo %CYAN%------------------------------------------------%RESET%
    echo %GREEN%Setup complete! Starting the bot for the first time...%RESET%
    echo %CYAN%------------------------------------------------%RESET%
) else (
    echo %GREEN%Using existing virtual environment at: %VENV_FOLDER%%RESET%
)

echo %GREEN%Bot script: %BOT_SCRIPT%%RESET%
echo.

:: Main loop that restarts the bot if it crashes
:loop
echo %YELLOW%Starting the Discord bot...%RESET%
echo %CYAN%------------------------------------------------%RESET%
echo %BLUE%Date/Time: %date% %time%%RESET%
echo %CYAN%------------------------------------------------%RESET%

:: Activate the virtual environment and run the bot
call %VENV_PATH% && python %BOT_SCRIPT%

:: If the bot exits with an error (non-zero exit code)
echo.
echo %RED%Bot has exited or crashed with exit code: %errorlevel%%RESET%
echo %YELLOW%Restarting in 5 seconds...%RESET%
echo.

:: Wait 5 seconds before restarting
timeout /t 5 /nobreak >nul
goto loop