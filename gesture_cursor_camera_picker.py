#!/usr/bin/env python3
"""
gesture_cursor.py — point at your screen, the cursor follows. Make a fist to drag.

Same family as its_giving.py (MediaPipe, one detector, one webcam), turned
into an air mouse instead of a meme machine.

Two modes, switched by your hand shape:

  POINTING (any hand shape except a full fist) — your index fingertip IS
  the cursor, at an absolute screen position. Calibration teaches it the
  mapping from "where the finger is in the camera" to "where it's pointing
  on the monitor" once, up front.

  FIST — closing your hand grabs whatever's under the cursor (mouse down)
  and holds it. While your hand stays a fist, moving it drags the cursor
  in the INVERTED direction (see DRAG_INVERT_X / DRAG_INVERT_Y below) — this
  part is relative motion, not absolute position, since curled fingers
  can't be pointed anywhere. Opening your hand drops it (mouse up) and
  pointing takes back over from wherever your fingertip is now.

  ONE HAND ONLY — both hands can be in frame; only one (right by default,
  --hand left to change it, h to swap live) is ever used. The other is ignored.

  python gesture_cursor.py --calibrate        # ~15s, 9 dots, once
  python gesture_cursor.py                    # run it

Keys (preview window focused):
  q   quit
  p   pause / resume moving the cursor (detection keeps running either way)
  c   recalibrate
  h   swap which hand is used (right <-> left)

Gestures:
  point               index finger anywhere, hand not a fist -> cursor follows
  fist, then move     grabs and drags (mouse down, relative motion, mouse up
                       on opening your hand)
  tap thumb to middle finger (hand not a fist) -> click, nothing stays held

A big ring follows the cursor on screen at all times, on top of whatever's
underneath. Green = idle/pointing, red flash = just clicked, blue = mid
fist-drag. The tiny real OS arrow moves to the same spot but is easy to
lose; the ring is the one to actually watch. Needs tkinter (ships with
Python on Windows/macOS; `apt install python3-tk` on Debian/Ubuntu if
it's missing). Pass --no-overlay to skip it.
Pass --voice to also listen for "open <something>" voice commands
(see voice_control.py — needs SpeechRecognition + PyAudio).

Needs: opencv-python, numpy, mediapipe (see requirements.txt for the
version pins), plus pyautogui for the actual cursor:

  pip install pyautogui

On macOS, System Settings > Privacy & Security > Accessibility has to
allow your terminal (or whatever's running this) or moveTo/click do
nothing and throw no error. On Linux under Wayland, pyautogui's mouse
control often doesn't work at all — X11 is fine.
"""
import argparse
import json
import math
import os
import platform
import subprocess
import sys
import time
import urllib.request
from collections import deque

import cv2
import numpy as np
import mediapipe as mp
from mediapipe.tasks import python as mp_tasks
from mediapipe.tasks.python import vision

try:
    import pyautogui
    pyautogui.FAILSAFE = False   # we deliberately move to corners during calibration/use
    pyautogui.PAUSE = 0
except ImportError:
    sys.exit("Needs pyautogui for cursor control:  pip install pyautogui")

try:
    import tkinter as tk
except ImportError:
    tk = None

import voice_control

HERE = os.path.dirname(os.path.abspath(__file__))
MODELS = {
    "hand_landmarker.task": "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task",
}
CALIB_FILE = "gesture_calibration.json"
CALIB_VERSION = 1

# --- tuning -----------------------------------------------------------------
FILTER_MIN_CUTOFF  = 1.0    # pointing steadiness when your hand is slow/still: lower = steadier (Hz)
FILTER_BETA        = 0.008  # how fast smoothing relaxes as you move faster: higher = less lag on sweeps
CLICK_REWIND       = 0.10   # seconds: a click lands where the cursor was this long ago (finger wobbles
                            # while the thumb closes in)
CLICK_HOLD         = 0.35   # seconds the cursor holds still after a click so it doesn't wander
PALM_SMOOTH_ALPHA  = 0.55   # smooths the fist's tracked position before diffing, while dragging
POINT_GAIN         = 1.6    # pointing sensitivity: 1.0 = exactly as calibrated, higher = smaller finger
                            # movements cover more screen (scaled about the screen centre)
DRAG_GAIN          = 1200   # screen px dragged per (hand-width of physical fist motion); was 2600
DRAG_INVERT_X      = True   # flip left/right of the drag motion
DRAG_INVERT_Y      = True   # flip up/down of the drag motion
DEFAULT_HAND       = "right"  # the one hand that's allowed to control the cursor
TOUCH_ON           = 0.35   # thumb-to-middle-finger distance (in hand-widths) that counts as a click
TOUCH_OFF          = 0.55   # has to open back up past this before it can click again
DWELL_FRAMES       = 18     # ~0.6s at 30fps: how long you hold still on a calib dot
DWELL_JITTER       = 14.0   # px of allowed wobble during dwell, in camera pixels


def dist(a, b):
    return float(np.linalg.norm(np.asarray(a) - np.asarray(b)))


def ensure_models():
    mdir = os.path.join(HERE, "models")
    os.makedirs(mdir, exist_ok=True)
    paths = {}
    for name, url in MODELS.items():
        path = os.path.join(mdir, name)
        if not os.path.exists(path):
            print(f"Downloading {name} ...")
            urllib.request.urlretrieve(url, path)
        paths[name] = path
    return paths


def preflight(model_path):
    """Open a detector in a throwaway subprocess: bad macOS builds abort() uncatchably."""
    code = (
        "import sys\n"
        "from mediapipe.tasks import python as t\n"
        "from mediapipe.tasks.python import vision\n"
        "vision.HandLandmarker.create_from_options(vision.HandLandmarkerOptions(\n"
        "    base_options=t.BaseOptions(model_asset_path=sys.argv[1]),\n"
        "    running_mode=vision.RunningMode.VIDEO, num_hands=1)).close()\n"
    )
    proc = subprocess.run([sys.executable, "-c", code, model_path], capture_output=True, text=True)
    if proc.returncode == 0:
        return
    err = (proc.stderr or "") + (proc.stdout or "")
    print(f"\nMediaPipe cannot start a detector here (python {platform.python_version()}, "
          f"mediapipe {getattr(mp, '__version__', '?')}, exit {proc.returncode}).\n")
    if "Service is unavailable" in err or "MetalHelper" in err or proc.returncode == -6:
        print("Cause: mediapipe 0.10.30+ ships macOS wheels that abort on startup.\n"
              "Fix (Python 3.11 or 3.12):\n"
              '  pip install "mediapipe==0.10.21" "numpy<2" "opencv-python<5" "opencv-contrib-python<5"\n')
    else:
        print(err[-1500:])
    sys.exit(1)


class Clock:
    """Strictly increasing timestamps for the life of a detector, recalibrations included."""

    def __init__(self):
        self.t0, self.last = time.monotonic(), -1

    def next(self):
        self.last = max(int((time.monotonic() - self.t0) * 1000), self.last + 1)
        return self.last


class Hand:
    """One hand, in raw (unflipped) camera pixel coordinates."""

    def __init__(self, lms, W, H):
        p = np.array([[l.x * W, l.y * H] for l in lms], np.float32)
        self.wrist, self.index, self.thumb, self.middle = p[0], p[8], p[4], p[12]
        # a stable tracking point built from every finger's base knuckle plus
        # the wrist — stays visible even when fingertips curl into a fist,
        # unlike any single fingertip would; used while dragging
        self.palm = p[[0, 5, 9, 13, 17]].mean(0)
        self.scale = max(dist(p[0], p[9]), 1.0)  # wrist -> middle-knuckle: this hand's current "ruler"
        ext = [dist(p[0], p[t]) > 1.2 * dist(p[0], p[t - 2]) for t in (8, 12, 16, 20)]
        self.index_ext, self.middle_ext, self.ring_ext, self.pinky_ext = ext
        self.fist = not any(ext)
        # click = thumb taps middle finger. Only checked while not a fist, so
        # closing your hand to drag can never be misread as a click.
        self.click_dist = dist(self.thumb, self.middle) / self.scale


class HandPicker:
    """Sees every hand in the frame but only ever hands back ONE of them.

    With both hands visible, a plain "give me the first hand" flips between
    them at random and the cursor jumps. Instead we pick by which physical
    hand it is (right by default) and ignore the other completely: its fist,
    its taps, its position all do nothing. If several detections claim the
    chosen side, the one nearest where we last saw it wins.
    """

    def __init__(self, which="right"):
        self.which = which
        self.last_wrist = None
        self.n_ignored = 0

    def toggle(self):
        self.which = "left" if self.which == "right" else "right"
        self.last_wrist = None

    def pick(self, result, W, H):
        found = list(zip(result.hand_landmarks, result.handedness)) if result.hand_landmarks else []
        # MediaPipe's Left/Right label assumes a mirrored (selfie) image. We feed it the
        # raw, unflipped frame, so the label is the opposite of the physical hand.
        want = "Left" if self.which == "right" else "Right"
        mine = [(lms, h[0].score) for lms, h in found if h and h[0].category_name == want]
        self.n_ignored = len(found) - (1 if mine else 0)
        if not mine:
            self.last_wrist = None
            return None
        if self.last_wrist is not None and len(mine) > 1:
            mine.sort(key=lambda m: dist((m[0][0].x * W, m[0][0].y * H), self.last_wrist))
        else:
            mine.sort(key=lambda m: -m[1])
        hand = Hand(mine[0][0], W, H)
        self.last_wrist = hand.wrist.copy()
        return hand


class OneEuro:
    """Adaptive smoothing (a "One Euro" filter) for the 2-D pointing cursor.

    Hand barely moving -> heavy smoothing, so the cursor sits still instead of
    shaking. Hand moving fast -> almost no smoothing, so it doesn't lag behind
    when you sweep across the screen. A fixed blend can't do both.
    """

    def __init__(self, min_cutoff, beta, d_cutoff=1.0):
        self.min_cutoff, self.beta, self.d_cutoff = min_cutoff, beta, d_cutoff
        self.reset()

    def reset(self):
        self.x, self.dx, self.t = None, None, None

    @staticmethod
    def _alpha(cutoff, dt):
        tau = 1.0 / (2 * math.pi * cutoff)
        return 1.0 / (1.0 + tau / dt)

    def __call__(self, x, t):
        x = np.asarray(x, np.float32)
        if self.x is None:                       # first sample after a reset: no history, so no lag
            self.x, self.dx, self.t = x.copy(), np.zeros(2, np.float32), t
            return self.x.copy()
        dt = max(t - self.t, 1e-3)
        self.t = t
        a_d = self._alpha(self.d_cutoff, dt)
        self.dx = a_d * ((x - self.x) / dt) + (1 - a_d) * self.dx
        cutoff = self.min_cutoff + self.beta * float(np.linalg.norm(self.dx))
        a = self._alpha(cutoff, dt)
        self.x = a * x + (1 - a) * self.x
        return self.x.copy()


def rewind(trail, t_wanted, fallback):
    """Cursor position from about `t_wanted` (oldest remembered one if the trail is shorter)."""
    pos = trail[0][1] if trail else fallback
    for t, p in trail:                           # oldest -> newest
        if t > t_wanted:
            break
        pos = p
    return pos.copy()


class CursorOverlay:
    """A big ring, always on top, that follows the cursor — the thing you
    actually watch, since the real OS arrow is small and easy to lose track
    of. The centre pixel is left as a hole in the ring so a click underneath
    it can land on whatever's really there.

    True click-through (so the ring itself never eats a click) only works on
    Windows, via -transparentcolor. Elsewhere we fall back to yanking the
    window out of the way for the instant a click actually happens.
    """

    SIZE = 46
    TRANSPARENT = "#010203"  # a colour nothing else is likely to use

    def __init__(self):
        self.ok = tk is not None
        if not self.ok:
            return
        self.click_through = platform.system() == "Windows"
        self.root = tk.Tk()
        self.root.withdraw()
        self.win = tk.Toplevel(self.root)
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        try:
            self.win.attributes("-alpha", 0.9)
        except tk.TclError:
            pass
        bg = self.TRANSPARENT
        if self.click_through:
            try:
                self.win.wm_attributes("-transparentcolor", self.TRANSPARENT)
            except tk.TclError:
                self.click_through = False
        self.canvas = tk.Canvas(self.win, width=self.SIZE, height=self.SIZE,
                                 highlightthickness=0, bg=bg)
        self.canvas.pack()
        self._visible = True
        self._draw("idle")

    def _draw(self, state):
        self.canvas.delete("all")
        colour = {"idle": "#33d17a", "click": "#ff3b3b", "drag": "#3b9bff"}.get(state, "#33d17a")
        self.canvas.create_oval(3, 3, self.SIZE - 3, self.SIZE - 3, outline=colour, width=4)

    def show_at(self, x, y, state="idle"):
        if not self.ok:
            return
        self._draw(state)
        half = self.SIZE // 2
        self.win.geometry(f"+{int(x - half)}+{int(y - half)}")
        if not self._visible:
            self.win.deiconify()
            self._visible = True
        self.root.update_idletasks()
        self.root.update()

    def hide(self):
        if not self.ok or not self._visible:
            return
        self.win.withdraw()
        self._visible = False
        self.root.update_idletasks()
        self.root.update()

    def close(self):
        if self.ok:
            self.root.destroy()


def build_detector(model_path):
    return vision.HandLandmarker.create_from_options(vision.HandLandmarkerOptions(
        base_options=mp_tasks.BaseOptions(model_asset_path=model_path),
        # detect both hands so HandPicker can choose one on purpose; with num_hands=1
        # MediaPipe picks for us and can hop between hands
        running_mode=vision.RunningMode.VIDEO, num_hands=2))


def open_camera(index, size):
    cap = cv2.VideoCapture(index)
    if cap.isOpened():
        # less lag and more frames per second = a more accurate, smoother cursor.
        # (cameras that don't support these just ignore them)
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        cap.set(cv2.CAP_PROP_FPS, 60)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    if cap.isOpened() and "x" in size:
        w, h = size.lower().split("x")
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, int(w))
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, int(h))
    ok, frame = False, None
    if cap.isOpened():
        for _ in range(5):
            ok, frame = cap.read()
            if not ok:
                break
    if not ok:
        sys.exit(f"Could not read from camera {index}.\n"
                  "  - try --camera 1\n"
                  "  - allow camera access for your terminal app in system privacy settings")
    return cap, frame.shape[1], frame.shape[0]


def calib_points(sw, sh, n):
    """A grid of reference points, inset from the edges — pointing at a screen's
    literal corner is uncomfortable, and you rarely need the cursor to actually
    reach the last pixel."""
    if n == 4:
        rows, cols, margin = 2, 2, 0.10
    else:
        rows, cols, margin = 3, 3, 0.08
    xs = np.linspace(margin, 1 - margin, cols) * (sw - 1)
    ys = np.linspace(margin, 1 - margin, rows) * (sh - 1)
    return [(float(x), float(y)) for y in ys for x in xs]


def run_calibration(cap, hand_det, clock, W, H, sw, sh, n_points, picker):
    targets = calib_points(sw, sh, n_points)
    win = "gesture_cursor calibration"
    cv2.namedWindow(win, cv2.WINDOW_NORMAL)
    cv2.setWindowProperty(win, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)

    cam_pts, screen_pts = [], []
    print(f"\nCalibrating on {len(targets)} points. Point your index finger at each dot and "
          "hold still. It captures itself; SPACE forces a capture, q cancels.")

    for (tx, ty) in targets:
        buf, captured = [], False
        while not captured:
            ok, frame = cap.read()
            if not ok:
                print("Camera stopped returning frames.")
                return None
            mp_img = mp.Image(image_format=mp.ImageFormat.SRGB, data=cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
            hr = hand_det.detect_for_video(mp_img, clock.next())
            hand = picker.pick(hr, W, H)

            canvas = np.zeros((sh, sw, 3), np.uint8)
            ready = hand is not None and not hand.fist
            if ready:
                buf.append(hand.index.copy())
                if len(buf) > DWELL_FRAMES:
                    buf.pop(0)
            else:
                buf.clear()

            progress = min(len(buf) / DWELL_FRAMES, 1.0)
            jitter = float(np.std(np.array(buf), axis=0).mean()) if len(buf) >= 4 else 999.0
            stable = len(buf) >= DWELL_FRAMES and jitter < DWELL_JITTER

            colour = (0, 220, 0) if stable else ((0, 165, 255) if ready else (60, 60, 220))
            cv2.circle(canvas, (int(tx), int(ty)), 26, colour, 3)
            cv2.circle(canvas, (int(tx), int(ty)), int(4 + 22 * progress), colour, -1)
            msg = "hold still..." if ready else f"point your {picker.which} index finger at the dot"
            cv2.putText(canvas, msg, (int(sw * 0.06), int(sh * 0.92)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 2)
            cv2.putText(canvas, f"{len(cam_pts) + 1} / {len(targets)}", (int(sw * 0.06), int(sh * 0.08)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 2)
            cv2.imshow(win, canvas)
            key = cv2.waitKey(1) & 0xFF

            if stable or key == ord(" "):
                pt = np.array(buf, np.float32).mean(0) if buf else (hand.index if hand else None)
                if pt is None:
                    continue
                cam_pts.append(pt)
                screen_pts.append((tx, ty))
                captured = True
            elif key == ord("q"):
                cv2.destroyWindow(win)
                print("Calibration cancelled.")
                return None

    cv2.destroyWindow(win)
    cam_pts = np.array(cam_pts, np.float32)
    screen_pts = np.array(screen_pts, np.float32)
    homography, _ = cv2.findHomography(cam_pts, screen_pts)
    if homography is None:
        print("Could not fit a mapping from those points — try again, hold steadier.")
        return None
    return {
        "version": CALIB_VERSION,
        "made": time.strftime("%Y-%m-%d %H:%M"),
        "screen_size": [sw, sh],
        "cam_size": [W, H],
        "cam_points": cam_pts.tolist(),
        "screen_points": screen_pts.tolist(),
    }


def load_calibration(path):
    try:
        with open(path) as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    if data.get("version") != CALIB_VERSION:
        return None
    cam_pts = np.array(data["cam_points"], np.float32)
    screen_pts = np.array(data["screen_points"], np.float32)
    homography, _ = cv2.findHomography(cam_pts, screen_pts)
    if homography is None:
        return None
    data["homography"] = homography
    return data


def direct_homography(W, H, sw, sh, margin=0.10):
    """No calibration: map the camera view straight onto the screen.

    Your fingertip's spot in the (mirrored) camera view becomes the cursor's
    spot on screen. The camera image we process is unflipped, so left/right
    are swapped here to make it feel like a mirror. `margin` ignores the
    outer edge of the frame so you don't have to reach the very corners.
    """
    mx, my = W * margin, H * margin
    cam = np.array([[W - mx, my], [mx, my], [mx, H - my], [W - mx, H - my]], np.float32)
    scr = np.array([[0, 0], [sw - 1, 0], [sw - 1, sh - 1], [0, sh - 1]], np.float32)
    homography, _ = cv2.findHomography(cam, scr)
    return homography


def to_screen(homography, cam_pt, sw, sh, gain=1.0):
    pt = cv2.perspectiveTransform(np.array([[cam_pt]], np.float32), homography)[0, 0]
    # gain > 1 stretches the calibrated mapping outward from the screen centre, so a
    # smaller finger movement reaches the same spot (the calibration file stays valid)
    cx, cy = (sw - 1) / 2, (sh - 1) / 2
    x = cx + (float(pt[0]) - cx) * gain
    y = cy + (float(pt[1]) - cy) * gain
    return float(np.clip(x, 0, sw - 1)), float(np.clip(y, 0, sh - 1))


def choose_camera_index(max_index=7):
    """Show a small camera-index picker when --camera is not supplied."""
    available = []
    for index in range(max_index + 1):
        cap = cv2.VideoCapture(index)
        ok, frame = cap.read() if cap.isOpened() else (False, None)
        if ok and frame is not None:
            available.append(index)
        cap.release()

    # Prefer a GUI picker, but keep a console fallback for systems without Tk.
    try:
        import tkinter as tk
        from tkinter import ttk, messagebox

        root = tk.Tk()
        root.title("Gesture Cursor — Select Camera")
        root.resizable(False, False)
        root.attributes("-topmost", True)

        tk.Label(root, text="Choose the camera to use:", padx=18, pady=12).pack()
        choices = [f"Camera {i}" + ("  (detected)" if i in available else "  (try manually)") 
                   for i in range(max_index + 1)]
        default_index = available[0] if available else 0
        selected = tk.StringVar(value=choices[default_index])
        combo = ttk.Combobox(root, textvariable=selected, values=choices,
                             state="readonly", width=28)
        combo.pack(padx=18, pady=4)
        if available:
            tk.Label(root, text="Detected camera indexes: " + ", ".join(map(str, available)),
                     padx=18, pady=5).pack()
        else:
            tk.Label(root, text="No camera detected automatically. You can still try an index.",
                     padx=18, pady=5).pack()

        result = {"index": None}
        def start():
            result["index"] = int(selected.get().split()[1])
            root.destroy()
        def cancel():
            root.destroy()

        buttons = tk.Frame(root, pady=12)
        buttons.pack()
        ttk.Button(buttons, text="Start", command=start).pack(side="left", padx=5)
        ttk.Button(buttons, text="Cancel", command=cancel).pack(side="left", padx=5)
        root.protocol("WM_DELETE_WINDOW", cancel)
        root.mainloop()
        if result["index"] is None:
            raise SystemExit("Camera selection cancelled.")
        return result["index"]
    except (ImportError, tk.TclError if 'tk' in locals() else Exception):
        if available:
            print("Detected camera indexes:", ", ".join(map(str, available)))
        else:
            print("No camera was detected automatically.")
        raw = input(f"Enter camera index (0-{max_index}) [0]: ").strip()
        return int(raw) if raw else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--camera", type=int, default=None,
                    help="camera index; omit this option to choose from a picker")
    ap.add_argument("--calibrate", action="store_true", help="learn the pointing-to-screen mapping, save, exit")
    ap.add_argument("--points", type=int, default=9, choices=(4, 9), help="calibration grid density")
    ap.add_argument("--size", default="1280x720", help="capture size, e.g. 640x480 for a faster loop")
    ap.add_argument("--steady", type=float, default=1.0,
                    help="pointing steadiness multiplier: above 1 = steadier but slightly slower "
                         "when aiming, below 1 = snappier but shakier (default 1.0)")
    ap.add_argument("--direct", action="store_true",
                    help="ignore any saved calibration and map the camera view straight onto the screen")
    ap.add_argument("--point-sensitivity", type=float, default=1.0,
                    help="multiplier on pointing sensitivity (default 1.0; POINT_GAIN is applied on top)")
    ap.add_argument("--hand", choices=("right", "left"), default=DEFAULT_HAND,
                    help="which hand controls the cursor; the other is ignored (default: right)")
    ap.add_argument("--drag-sensitivity", type=float, default=1.0,
                     help="multiplier on drag speed while fisted (default 1.0)")
    ap.add_argument("--skip-check", action="store_true", help="skip the MediaPipe startup check")
    ap.add_argument("--no-overlay", action="store_true", help="don't draw the on-screen ring cursor")
    ap.add_argument("--voice", action="store_true", help='also listen for "open <something>" voice commands')
    args = ap.parse_args()
    if args.camera is None:
        args.camera = choose_camera_index()

    calib_path = os.path.join(HERE, CALIB_FILE)
    sw, sh = pyautogui.size()
    drag_gain = DRAG_GAIN * args.drag_sensitivity
    point_gain = POINT_GAIN * args.point_sensitivity
    picker = HandPicker(args.hand)

    model_paths = ensure_models()
    if not args.skip_check:
        preflight(model_paths["hand_landmarker.task"])

    cap, W, H = open_camera(args.camera, args.size)
    print(f"Camera {args.camera}: {W}x{H}   Screen: {sw}x{sh}")
    clock = Clock()
    hand_det = build_detector(model_paths["hand_landmarker.task"])

    overlay = None

    try:
        if args.calibrate:
            new = run_calibration(cap, hand_det, clock, W, H, sw, sh, args.points, picker)
            if new is None:
                sys.exit(1)
            with open(calib_path, "w") as fh:
                json.dump(new, fh, indent=1)
            print(f"Saved {CALIB_FILE}. Now run:  python {os.path.basename(__file__)}")
            return

        calib = None if args.direct else load_calibration(calib_path)
        if calib is None:
            # no calibration needed: fingertip position in the camera view -> same spot on screen
            homography = direct_homography(W, H, sw, sh)
            print("No calibration in use: the cursor goes where your finger is in the camera view. "
                  "(Run with --calibrate once if you want it tuned to your screen.)")
        else:
            homography = calib["homography"]

        window = "gesture_cursor  (q quit, p pause, c recalibrate, h swap hand)"
        cursor = np.array([sw / 2, sh / 2], np.float32)
        pointer_filter = OneEuro(FILTER_MIN_CUTOFF / max(args.steady, 0.1), FILTER_BETA)
        trail = deque(maxlen=40)     # recent (time, cursor) positions, for stable clicks
        touch_t = 0.0
        smoothed_palm, prev_smoothed_palm = None, None
        was_fist, dragging = False, False
        click_touching, paused = False, False
        click_flash = 0

        overlay = None if args.no_overlay else CursorOverlay()
        if overlay is not None and not overlay.ok:
            print("tkinter isn't available — running without the ring cursor (--no-overlay to silence this).")
            overlay = None

        voice_stop = voice_control.start_voice_control() if args.voice else None

        print("Running. Point to move the cursor. Make a fist to grab and drag; "
              "open your hand to drop. Tap thumb+middle finger to click.")

        while True:
            ok, frame = cap.read()
            if not ok:
                print("Camera stopped returning frames.")
                break
            ts = clock.next()
            mp_img = mp.Image(image_format=mp.ImageFormat.SRGB, data=cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
            hr = hand_det.detect_for_video(mp_img, ts)
            hand = picker.pick(hr, W, H)

            active = hand is not None and not paused
            state = "idle"

            if active:
                if hand.fist:
                    raw_palm = hand.palm
                    smoothed_palm = raw_palm if smoothed_palm is None else (
                        PALM_SMOOTH_ALPHA * raw_palm + (1 - PALM_SMOOTH_ALPHA) * smoothed_palm
                    )
                    if not was_fist:
                        # just closed: grab whatever's currently under the cursor
                        if overlay is not None and not overlay.click_through:
                            overlay.hide()
                        pyautogui.mouseDown()
                        dragging = True
                    elif prev_smoothed_palm is not None:
                        delta = (smoothed_palm - prev_smoothed_palm) / hand.scale
                        if DRAG_INVERT_X:
                            delta[0] = -delta[0]
                        if DRAG_INVERT_Y:
                            delta[1] = -delta[1]
                        cursor = cursor + delta * drag_gain
                        cursor[0] = float(np.clip(cursor[0], 0, sw - 1))
                        cursor[1] = float(np.clip(cursor[1], 0, sh - 1))
                        pyautogui.moveTo(int(cursor[0]), int(cursor[1]))
                    was_fist = True
                    prev_smoothed_palm = smoothed_palm
                    state = "drag"
                else:
                    if was_fist:
                        # just opened: drop
                        if overlay is not None and not overlay.click_through:
                            overlay.hide()
                        pyautogui.mouseUp()
                        dragging = False
                    was_fist = False
                    smoothed_palm, prev_smoothed_palm = None, None

                    now_t = time.perf_counter()
                    now_click_touching = hand.click_dist < (TOUCH_OFF if click_touching else TOUCH_ON)
                    if now_click_touching and not click_touching:
                        # fingers just met. The fingertip wobbles while the thumb closes in,
                        # so click where the cursor was a moment ago, not where it drifted to.
                        touch_t = now_t
                        cursor = rewind(trail, now_t - CLICK_REWIND, cursor)
                        pyautogui.moveTo(int(cursor[0]), int(cursor[1]))
                        if overlay is not None and not overlay.click_through:
                            overlay.hide()
                        pyautogui.click()
                        click_flash = 6
                    elif not (now_click_touching and now_t - touch_t < CLICK_HOLD):
                        # normal pointing (the cursor holds still briefly after a click)
                        target = np.array(to_screen(homography, hand.index, sw, sh, point_gain), np.float32)
                        cursor = pointer_filter(target, now_t)
                        trail.append((now_t, cursor.copy()))
                        pyautogui.moveTo(int(cursor[0]), int(cursor[1]))
                    click_touching = now_click_touching
                    state = "click" if click_flash > 0 else "idle"

                click_flash = max(0, click_flash - 1)
            else:
                if was_fist:
                    pyautogui.mouseUp()
                    dragging = False
                was_fist = False
                smoothed_palm, prev_smoothed_palm = None, None

            if not (active and not hand.fist):
                # not pointing (fist, no hand, or paused): forget smoothing history so the
                # next pointing frame starts fresh at the fingertip instead of gliding from stale state
                pointer_filter.reset()
                trail.clear()

            if overlay is not None:
                if active:
                    overlay.show_at(cursor[0], cursor[1], state)
                else:
                    overlay.hide()

            preview = cv2.flip(frame, 1)
            if hand is not None:
                # ring on the fingertip of the hand that's actually in control
                cv2.circle(preview, (int(W - hand.index[0]), int(hand.index[1])), 12, (0, 220, 0), 2)
            status = "PAUSED" if paused else (f"{picker.which} hand seen" if hand else f"no {picker.which} hand")
            if picker.n_ignored:
                status += "  (other hand ignored)"
            if hand and hand.fist:
                status += "  FIST"
            if dragging:
                status += "  DRAGGING"
            colour = (0, 165, 255) if paused else ((0, 220, 0) if active else (0, 0, 220))
            cv2.putText(preview, status, (10, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.6, colour, 2)
            cv2.imshow(window, preview)
            key = cv2.waitKey(1) & 0xFF
            if key == ord("q"):
                break
            elif key == ord("p"):
                paused = not paused
                if paused:
                    if dragging:
                        pyautogui.mouseUp()
                        dragging = False
                    was_fist = False
                    smoothed_palm, prev_smoothed_palm = None, None
            elif key == ord("h"):
                # swap which hand is in charge; let go of anything the old one was holding
                picker.toggle()
                if dragging:
                    pyautogui.mouseUp()
                    dragging = False
                was_fist, click_touching = False, False
                smoothed_palm, prev_smoothed_palm = None, None
                print(f"Now using your {picker.which} hand only.")
            elif key == ord("c"):
                cv2.destroyWindow(window)
                new = run_calibration(cap, hand_det, clock, W, H, sw, sh, args.points, picker)
                if new is not None:
                    with open(calib_path, "w") as fh:
                        json.dump(new, fh, indent=1)
                    calib = load_calibration(calib_path)
                    homography = calib["homography"]
                    print(f"Saved {CALIB_FILE}.")
                pointer_filter.reset()
                trail.clear()
    finally:
        if 'dragging' in dir() and dragging:
            pyautogui.mouseUp()
        if overlay is not None:
            overlay.close()
        if 'voice_stop' in dir() and voice_stop is not None:
            voice_stop.set()
        cap.release()
        hand_det.close()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
