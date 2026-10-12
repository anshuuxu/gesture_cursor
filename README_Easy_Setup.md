# Gesture Cursor — Easy Setup and Troubleshooting (Windows)

Move your mouse pointer with your hand in front of a webcam. This project uses Python, OpenCV, MediaPipe, and PyAutoGUI.

> **Recommended:** Windows 10/11, Python **3.12 or 3.11 (64-bit)**, and a working webcam.
> Do not use Python 3.13/3.14 for this project's pinned MediaPipe setup unless you have tested compatible wheels.

## 1. What should be in your project folder?

Keep these files together in one folder:

- `gesture_cursor_camera_picker.py` — version that lets you choose a camera
- `gesture_cursor.py` — original version (optional if using the camera-picker version)
- `voice_control.py`
- `gesture_calibration.json`
- `requirements.txt`
- `Launch_Gesture_Cursor.bat`
- `Create_Desktop_Shortcut.ps1`

The first run downloads the MediaPipe hand-tracking model into a `models` folder. An internet connection is needed for that first download.

## 2. Install Python

1. Install Python 3.12 (64-bit) or Python 3.11 (64-bit) from <https://www.python.org/downloads/windows/>.
2. During installation, tick **Add python.exe to PATH** if that option appears.
3. Open **Command Prompt** and check:

```bat
py -3.12 --version
```

If that says Python was not found, try:

```bat
py -3.11 --version
```

Use the version that works in the commands below. The examples use Python 3.12.

## 3. Create a virtual environment and install packages

Open the project folder in File Explorer. Click the address bar, type `cmd`, and press Enter. A Command Prompt opens in the project folder.

Run these commands one at a time:

```bat
py -3.12 -m venv venv
venv\Scripts\python.exe -m pip install --upgrade pip setuptools wheel
venv\Scripts\python.exe -m pip install -r requirements.txt
```

If you installed Python 3.11 instead, replace `py -3.12` with `py -3.11` in the first command.

A virtual environment keeps this project's packages separate from other Python projects. You do not have to activate it when using the commands above.

### Optional: voice commands

Voice support is optional. The cursor works without it. If your `requirements.txt` includes `SpeechRecognition` and `PyAudio`, the PyAudio install can fail on some Windows/Python combinations. If that happens, first install the core requirements and get the cursor working. Then try voice support separately:

```bat
venv\Scripts\python.exe -m pip install SpeechRecognition
venv\Scripts\python.exe -m pip install PyAudio
```

If the second command fails, skip voice support for now. Do not install random unofficial wheels from untrusted websites.

## 4. Start the camera-picker version

```bat
venv\Scripts\python.exe gesture_cursor_camera_picker.py
```

Choose the camera index in the picker. Index `0` is usually the default webcam; try `1`, `2`, and so on if needed. If the picker does not appear, the script may use a console prompt depending on the version.

To launch the original script with a specific camera:

```bat
venv\Scripts\python.exe gesture_cursor.py --camera 0
```

Change `0` to `1` or `2` to try another camera.

## 5. Calibrate the cursor

Run calibration once, then follow the dots shown on screen:

```bat
venv\Scripts\python.exe gesture_cursor.py --calibrate
```

If using the camera-picker version, run:

```bat
venv\Scripts\python.exe gesture_cursor_camera_picker.py --calibrate
```

If cursor accuracy gets worse after you move your camera, seat, or screen, run calibration again. Press `c` in the preview window to recalibrate if supported by the running version.

## 6. Make a desktop shortcut (Windows)

1. Keep `Launch_Gesture_Cursor.bat` in the same folder as your Python scripts.
2. Right-click `Create_Desktop_Shortcut.ps1` and choose **Run with PowerShell**. On Windows 11, you may need **Show more options** first.
3. If the shortcut script is blocked, open Command Prompt in the project folder and run:

```bat
powershell -NoProfile -ExecutionPolicy Bypass -File ".\Create_Desktop_Shortcut.ps1"
```

4. Look for **Gesture Cursor** on your desktop and double-click it.

Only run scripts you trust. `-ExecutionPolicy Bypass` applies to this one PowerShell process; it does not permanently change the computer's policy.

## 7. Common errors and fixes

### A. `py` is not recognized / Python was not found

Check whether Python Launcher is installed:

```bat
python --version
where python
where py
```

If none work, install Python 3.12 or 3.11 (64-bit), reopen Command Prompt, and retry. If `python` opens the Microsoft Store, use `py -3.12` or disable the Windows App Execution Alias for Python in Windows Settings.

### B. `No module named cv2`, `mediapipe`, `numpy`, or `pyautogui`

Install packages using the same Python executable that runs the script:

```bat
venv\Scripts\python.exe -m pip install -r requirements.txt
```

Check imports:

```bat
venv\Scripts\python.exe -c "import cv2, mediapipe, numpy, pyautogui; print('Imports OK')"
```

### C. `No matching distribution found for mediapipe`

You may be using an unsupported Python version or 32-bit Python. Check:

```bat
py -3.12 -c "import sys,struct; print(sys.version); print(struct.calcsize('P')*8, 'bit')"
```

Use Python 3.12 or 3.11, 64-bit, then recreate the environment:

```bat
rmdir /s /q venv
py -3.12 -m venv venv
venv\Scripts\python.exe -m pip install --upgrade pip setuptools wheel
venv\Scripts\python.exe -m pip install -r requirements.txt
```

**Warning:** `rmdir /s /q venv` deletes only the virtual-environment folder named `venv`. Do not run it if you stored your own files in that folder.

### D. `Could not find a version that satisfies ...` or dependency conflicts

Do not randomly upgrade NumPy, MediaPipe, or OpenCV independently. This project uses version constraints because those packages need to work together. Recreate the environment using the commands in section C. If it still fails, copy the complete error text and check the exact Python version.

### E. `ImportError: DLL load failed` or OpenCV/MediaPipe fails to import

Close the program, then reinstall the pinned packages in the virtual environment:

```bat
venv\Scripts\python.exe -m pip uninstall -y mediapipe opencv-python opencv-contrib-python numpy
venv\Scripts\python.exe -m pip install -r requirements.txt
```

If the error persists, confirm you are using 64-bit Python 3.11/3.12 and that you are running `venv\Scripts\python.exe`, not a different Python installation.

### F. `Could not open camera`, black preview, or camera is busy

1. Close Camera, Zoom, Teams, browser video calls, and other apps using the webcam.
2. Try another camera index:

```bat
venv\Scripts\python.exe gesture_cursor.py --camera 0
venv\Scripts\python.exe gesture_cursor.py --camera 1
venv\Scripts\python.exe gesture_cursor.py --camera 2
```

3. In Windows, open **Settings → Privacy & security → Camera** and allow camera access for desktop apps.
4. Unplug and reconnect a USB webcam, then try again.

Camera indexes are device numbers; they do not always match camera names.

### G. `ModuleNotFoundError: No module named 'voice_control'`

Keep `voice_control.py` in the same folder as the gesture cursor script. Do not move the Python file by itself.

### H. PyAudio install error / `No module named pyaudio`

Voice control is optional. The basic cursor does not need voice packages. First get the cursor working without `--voice`. Try installing voice packages separately:

```bat
venv\Scripts\python.exe -m pip install SpeechRecognition
venv\Scripts\python.exe -m pip install PyAudio
```

If PyAudio fails, leave voice support disabled rather than breaking the core installation.

### I. `PermissionError`, mouse does not move, or clicks do nothing

- Close the app and restart it normally.
- On Windows, check that no security tool is blocking the script.
- Avoid running as administrator unless a specific, trusted application requires it.
- Test the pointer over a safe, empty area first. Gesture control can move the real system cursor and perform clicks.

### J. Hand not detected

- Improve room lighting and keep your full hand in the camera view.
- Move the camera so your hand is not too close or too far away.
- Close other apps using the webcam.
- Wait for the first-run model download to finish; check that the computer is online.
- Re-run calibration after adjusting camera placement.

### K. PowerShell says scripts are disabled

Use this from Command Prompt in the project folder:

```bat
powershell -NoProfile -ExecutionPolicy Bypass -File ".\Create_Desktop_Shortcut.ps1"
```

If the script still fails, you can make a shortcut manually: right-click `Launch_Gesture_Cursor.bat` → **Show more options** → **Create shortcut**, then move that shortcut to the desktop.

### L. Window opens and closes immediately

Open Command Prompt in the project folder and run the script there so the error remains visible:

```bat
venv\Scripts\python.exe gesture_cursor_camera_picker.py
```

Copy the full traceback text when asking for help.

## 8. Useful commands

Check pip and installed package versions:

```bat
venv\Scripts\python.exe -m pip --version
venv\Scripts\python.exe -m pip show mediapipe numpy opencv-contrib-python pyautogui
venv\Scripts\python.exe -m pip check
```

Check whether OpenCV can see camera 0:

```bat
venv\Scripts\python.exe -c "import cv2; c=cv2.VideoCapture(0); print('Camera opened:', c.isOpened()); c.release()"
```

## 9. Should I upgrade `requirements.txt`?

**Do not upgrade every package to its newest version just for the sake of it.** MediaPipe, NumPy, and OpenCV have compatibility constraints in this project. Keep the existing pins until the project has been tested with a new set.

One practical improvement is to keep voice packages optional so a PyAudio installation problem cannot block the basic cursor. If you want to make that change, use a core `requirements.txt` containing:

```text
mediapipe==0.10.21
numpy<2
opencv-python<5
opencv-contrib-python<5
pyautogui
```

And a separate `requirements-voice.txt` containing:

```text
-r requirements.txt
SpeechRecognition
PyAudio
```

Then install core packages with `venv\Scripts\python.exe -m pip install -r requirements.txt`. Only if you want voice commands, run `venv\Scripts\python.exe -m pip install -r requirements-voice.txt`.

These files are a conservative setup suggestion, not a guarantee for every computer. If your current requirements already install successfully, you do not need to upgrade them.

## 10. Quit and safety

- Press `q` while the preview window is focused to quit.
- Test hand gestures over a safe area first because clicks and drags affect the real desktop.
- Keep the webcam and monitor stable after calibration.
