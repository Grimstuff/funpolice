@echo off
title Fun Police Discord Bot - Multi-Server Edition

:: Change to the directory where the script is located
cd /d %~dp0

:: Set path to your virtual environment
SET VENV_FOLDER=venv
SET VENV_PATH=%VENV_FOLDER%\Scripts\activate.bat
SET BOT_SCRIPT=funpolice.py

echo ===============================================
echo  Fun Police Discord Bot - Multi-Server Edition
echo              Auto Restarter                   
echo ===============================================

:: Check if bot script exists
if not exist %BOT_SCRIPT% (
    echo Error: %BOT_SCRIPT% not found!
    echo Please make sure the bot script exists in this directory.
    pause
    exit /b 1
)

:: Check if secrets.json exists, if not, prompt for API key and create it
if not exist secrets.json (
    :prompt_token
    echo secrets.json not found. Please enter your Discord application API key:
    set /p BOT_TOKEN=
    if "%BOT_TOKEN%"=="" (
        echo API key cannot be empty. Please try again.
        goto prompt_token
    )
    echo { "BOT_TOKEN": "%BOT_TOKEN%" } > secrets.json
    echo secrets.json created successfully.
)

:: Remove old config.json if it exists (migration from single-server version)
if exist config.json (
    echo.
    echo ================================================
    echo  MIGRATION NOTICE
    echo ================================================
    echo Old single-server config.json detected!
    echo The bot now uses server-specific config files.
    echo.
    echo Your old config.json will be renamed to config_backup.json
    echo You'll need to re-add your filters using /addfilter commands
    echo in each server where you want them to apply.
    echo.
    ren config.json config_backup.json
    echo Old config backed up as config_backup.json
    echo ================================================
    echo.
)

:: Check if venv exists, if not, create it and install dependencies
if not exist %VENV_FOLDER% (
    echo Virtual environment not found. Setting up for first time use...
    
    :: Check if Python is installed
    python --version >nul 2>&1
    if %errorlevel% neq 0 (
        echo Error: Python is not installed or not in PATH
        echo Please install Python 3.8 or higher and try again.
        pause
        exit /b 1
    )
    
    echo ------------------------------------------------
    echo Creating virtual environment...
    python -m venv %VENV_FOLDER%
    
    if %errorlevel% neq 0 (
        echo Failed to create virtual environment.
        pause
        exit /b 1
    )
    
    echo Installing required packages...
    call %VENV_PATH% && python -m pip install --upgrade pip && pip install discord.py
    
    if %errorlevel% neq 0 (
        echo Failed to install dependencies.
        pause
        exit /b 1
    )
    
    echo ------------------------------------------------
    echo Setup complete! Starting the bot for the first time...
    echo ------------------------------------------------
) else (
    echo Using existing virtual environment at: %VENV_FOLDER%
)

echo Bot script: %BOT_SCRIPT%
echo.

:: Show setup instructions only if configs folder does not exist (first run)
if not exist configs (
    echo ================================================
    echo  SETUP INSTRUCTIONS
    echo ================================================
    echo 1. Invite the bot to your Discord server(s) with these permissions:
    echo.
    echo    REQUIRED PERMISSIONS:
    echo    - Send Messages ^(to send filtered replacement messages^)
    echo    - Manage Messages ^(to delete original filtered messages^)
    echo    - Manage Webhooks ^(to send messages as the original user^)
    echo    - Use Slash Commands ^(for admin configuration commands^)
    echo    - Read Message History ^(to fetch replied-to messages for context^)
    echo    - View Channels ^(to see messages in channels where bot operates^)
    echo.
    echo    OPTIONAL BUT RECOMMENDED:
    echo    - Add Reactions ^(future feature compatibility^)
    echo    - Attach Files ^(for preserving attachments in filtered messages^)
    echo.
    echo    NOTE: The bot needs these permissions in every channel where
    echo          you want word filtering to work.
    echo.
    echo 2. In each server, use /addfilter to create server-specific word filters
    echo    Example: /addfilter replacement:kitten words:cat,feline
    echo.
    echo 3. Each server will have its own config file in the configs/ folder
    echo    Format: config_SERVERID_ServerName.json
    echo.
    echo 4. Use /listfilters to see filters for the current server
    echo    Use /deletefilter to remove individual words
    echo    Use /deletereplacement to remove entire replacement categories
    echo.
    echo 5. All slash commands require Administrator permissions to use
    echo ================================================
    echo.
    mkdir configs
)

:: Main loop that restarts the bot if it crashes
:loop
echo Starting the Discord bot...
echo ------------------------------------------------
echo Date/Time: %date% %time%
echo ------------------------------------------------

:: Activate the virtual environment and run the bot
call %VENV_PATH% && python %BOT_SCRIPT%

:: If the bot exits with an error (non-zero exit code)
echo.
echo Bot has exited or crashed with exit code: %errorlevel%
echo Restarting in 5 seconds...
echo.

:: Wait 5 seconds before restarting
timeout /t 5 /nobreak >nul
goto loop