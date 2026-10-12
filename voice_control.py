"""
voice_control.py — "open <something>" by voice, nothing fancier.

Listens continuously on a background thread. Any recognized phrase that
doesn't start with "open " is thrown away — so a mis-hearing of unrelated
speech just does nothing, rather than doing the wrong thing.

Needs:
  pip install SpeechRecognition PyAudio

PyAudio is the one that gives people trouble on Windows (no wheel on some
Python/pip combos). If `pip install PyAudio` fails:
  pip install pipwin
  pipwin install pyaudio

Recognition goes through Google's free web speech API via the
`speech_recognition` library — no API key needed, but it does need an
internet connection for each phrase. There's no offline mode built in
here; swap recognize_google() for something like Vosk if you need that.
"""
import json
import os
import platform
import subprocess
import sys
import threading
import webbrowser

try:
    import speech_recognition as sr
except ImportError:
    sr = None

HERE = os.path.dirname(os.path.abspath(__file__))
ALIASES_FILE = os.path.join(HERE, "aliases.json")

# Sites worth recognizing by plain name rather than requiring "youtube.com".
SITES = {
    "youtube": "https://youtube.com", "google": "https://google.com",
    "gmail": "https://mail.google.com", "maps": "https://maps.google.com",
    "amazon": "https://amazon.com", "netflix": "https://netflix.com",
    "reddit": "https://reddit.com", "github": "https://github.com",
}

# Things every OS install of that platform can open without any path guessing.
BUILTINS = {
    "Windows": {"notepad": "notepad", "calculator": "calc", "calc": "calc",
                "explorer": "explorer", "file explorer": "explorer", "paint": "mspaint"},
    "Darwin":  {"calculator": "Calculator", "notes": "Notes", "finder": "Finder",
                "terminal": "Terminal", "mail": "Mail", "safari": "Safari"},
    "Linux":   {"calculator": "gnome-calculator", "files": "nautilus", "terminal": "gnome-terminal"},
}


def load_aliases():
    """User-editable {"spoken name": "actual command or path"} — for anything
    BUILTINS and SITES don't cover on your particular machine."""
    if os.path.exists(ALIASES_FILE):
        try:
            with open(ALIASES_FILE) as fh:
                return json.load(fh)
        except (OSError, ValueError):
            pass
    return {}


def resolve_and_open(name, aliases):
    name = name.strip().lower()
    if not name:
        return "Open what?"

    if name in aliases:
        target = aliases[name]
        if target.startswith(("http://", "https://")):
            webbrowser.open(target)
        else:
            _launch(target)
        return f"Opening {name}."

    if name in SITES:
        webbrowser.open(SITES[name])
        return f"Opening {name}."
    if "." in name and " " not in name:  # looks like a bare URL/domain
        webbrowser.open(name if "://" in name else f"https://{name}")
        return f"Opening {name}."

    system_builtins = BUILTINS.get(platform.system(), {})
    if name in system_builtins:
        _launch(system_builtins[name])
        return f"Opening {name}."

    # Last resort: ask the OS to figure it out, same as typing the name into
    # Run/Spotlight/a launcher would. Works for things on PATH, often doesn't
    # for GUI apps installed elsewhere - that's what aliases.json is for.
    if _launch(name):
        return f"Opening {name}."
    return (f"Don't know how to open '{name}' — add it to aliases.json, e.g. "
            f'{{"{name}": "C:\\\\Path\\\\To\\\\App.exe"}}')


def _launch(target):
    system = platform.system()
    try:
        if system == "Windows":
            os.startfile(target)  # noqa: works for paths and PATH-registered names alike
        elif system == "Darwin":
            subprocess.Popen(["open", "-a", target])
        else:
            subprocess.Popen([target])
        return True
    except OSError:
        return False


def _listen_loop(callback, stop_event):
    r = sr.Recognizer()
    mic = sr.Microphone()
    with mic as source:
        r.adjust_for_ambient_noise(source, duration=1)
    print("Voice control listening. Say 'open <something>'.")
    while not stop_event.is_set():
        try:
            with mic as source:
                audio = r.listen(source, timeout=5, phrase_time_limit=6)
            text = r.recognize_google(audio).lower().strip()
        except sr.WaitTimeoutError:
            continue
        except sr.UnknownValueError:
            continue
        except sr.RequestError as e:
            print(f"Voice recognition error (check internet): {e}")
            continue

        if text.startswith("open "):
            aliases = load_aliases()  # re-read each time so edits take effect live
            msg = resolve_and_open(text[len("open "):], aliases)
            print(f"[voice] heard: \"{text}\" -> {msg}")
            if callback:
                callback(text, msg)


def start_voice_control(callback=None):
    """Starts listening on a daemon thread. Returns a stop_event; set it to
    stop listening (the thread exits on its next loop iteration)."""
    if sr is None:
        print("Voice control needs: pip install SpeechRecognition PyAudio")
        return None
    stop_event = threading.Event()
    threading.Thread(target=_listen_loop, args=(callback, stop_event), daemon=True).start()
    return stop_event


if __name__ == "__main__":
    # Standalone smoke test: python voice_control.py, then just talk.
    ev = start_voice_control()
    if ev:
        try:
            while True:
                pass
        except KeyboardInterrupt:
            ev.set()
