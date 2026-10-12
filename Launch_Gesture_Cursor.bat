@echo off
setlocal
cd /d "%~dp0"

REM Use the project's virtual environment when it exists.
if exist "venv\Scripts\python.exe" (
    "venv\Scripts\python.exe" "gesture_cursor_camera_picker.py" %*
    goto :end
)

REM Otherwise try Python 3.12, then the default Python launcher.
py -3.12 "gesture_cursor_camera_picker.py" %*
if %errorlevel% equ 0 goto :end
python "gesture_cursor_camera_picker.py" %*

:end
if not "%errorlevel%"=="0" (
    echo.
    echo Gesture Cursor exited with an error. Check the setup in README.md.
    pause
)
endlocal
