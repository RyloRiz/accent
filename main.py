import sys
import re
import json
import base64
import os
import subprocess
import tempfile
import time
import urllib.request
import argparse
from types import SimpleNamespace

import atomacos
from PyQt6.QtWidgets import QApplication, QWidget
from PyQt6.QtCore import Qt, QRect, QTimer
from PyQt6.QtGui import QPainter, QPen, QColor, QFont

OLLAMA_BASE = 'http://localhost:11434'
OLLAMA_URL = f'{OLLAMA_BASE}/api/generate'
DEFAULT_VISION_MODEL = 'gemma4:e2b'


class VisionElement:
    """Wraps static screen coordinates returned by the vision model."""
    def __init__(self, frame):
        self._frame = frame

    @property
    def AXFrame(self):
        return self._frame


class VisualGuideOverlay(QWidget):
    def __init__(self, ax_element, label_text="Click Here"):
        super().__init__()
        self.ax_element = ax_element
        self.label_text = label_text
        self.current_frame = ax_element.AXFrame

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.WindowTransparentForInput
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        screen_geo = QApplication.primaryScreen().geometry()
        self.setGeometry(screen_geo)
        self.show()

        # Raise above Dock and all other system UI (Dock is ~level 20, screensaver is 1000)
        self._raise_above_all()

        # Poll element position every 100ms and redraw if it moved
        self._poll_timer = QTimer()
        self._poll_timer.timeout.connect(self._refresh_frame)
        self._poll_timer.start(100)

        QTimer.singleShot(8000, self.close)

    def _raise_above_all(self):
        try:
            import objc
            from AppKit import NSScreenSaverWindowLevel
            ns_view = objc.objc_object(c_void_p=int(self.winId()))
            ns_window = ns_view.window()
            ns_window.setLevel_(NSScreenSaverWindowLevel)
        except Exception as e:
            print(f"Could not raise window level: {e}")

    def _refresh_frame(self):
        try:
            new_frame = self.ax_element.AXFrame
            if (new_frame.x != self.current_frame.x or
                    new_frame.y != self.current_frame.y or
                    new_frame.width != self.current_frame.width or
                    new_frame.height != self.current_frame.height):
                self.current_frame = new_frame
                self.update()
        except Exception:
            pass

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        f = self.current_frame
        origin_x = int(f.x)
        origin_y = int(f.y)
        width = int(f.width)
        height = int(f.height)

        rect = QRect(origin_x, origin_y, width, height)

        pen = QPen(QColor(255, 0, 0, 200))
        pen.setWidth(6)
        painter.setPen(pen)
        painter.drawEllipse(rect.adjusted(-5, -5, 5, 5))

        painter.setFont(QFont("Arial", 18, QFont.Weight.Bold))
        painter.setPen(QColor(0, 0, 0, 150))
        painter.drawText(origin_x + 2, origin_y - 8, self.label_text)
        painter.setPen(QColor(255, 255, 255))
        painter.drawText(origin_x, origin_y - 10, self.label_text)


# ── Accessibility search ──────────────────────────────────────────────────────

def extract_target(query):
    stop_words = {
        'open', 'click', 'press', 'tap', 'launch', 'start', 'show', 'find',
        'where', 'can', 'i', 'how', 'do', 'to', 'me',
        'the', 'a', 'an', 'my', 'button', 'app', 'application', 'on', 'in',
    }
    words = query.lower().split()
    target_words = [w for w in words if w not in stop_words]
    return ' '.join(target_words) if target_words else query.lower()


def element_matches(target, *text_fields):
    for field in text_fields:
        if field and target in field.lower():
            return True
    return False


def search_app(app_ref, target, roles=None):
    """Search an app's accessibility tree; returns (element, display_text)."""
    if roles is None:
        roles = ['AXButton', 'AXMenuItem', 'AXMenuBarItem', 'AXStaticText',
                 'AXLink', 'AXCheckBox', 'AXRadioButton', 'AXTab']
    for role in roles:
        try:
            elements = app_ref.findAllR(AXRole=role)
        except Exception:
            continue
        for el in elements:
            try:
                title = el.AXTitle or ''
                desc = getattr(el, 'AXDescription', '') or ''
                label = getattr(el, 'AXLabel', '') or ''
                if element_matches(target, title, desc, label):
                    display = title or desc or label or target
                    return el, display
            except Exception:
                continue
    return None, None


def find_element_by_accessibility(query):
    target = extract_target(query)

    # 1. Dock — app icons for "Open X" queries
    try:
        dock = atomacos.getAppRefByBundleId('com.apple.dock')
        el, label = search_app(dock, target, roles=['AXDockItem', 'AXIcon'])
        if el:
            return el, f"Open {label}"
    except Exception as e:
        print(f"Dock search error: {e}")

    # 2. Frontmost app — most likely for in-app controls
    try:
        active_app = atomacos.getFrontmostApp()
        el, label = search_app(active_app, target)
        if el:
            return el, label
    except Exception as e:
        print(f"Active app search error: {e}")

    # 3. All visible regular apps
    try:
        import AppKit
        for ns_app in AppKit.NSWorkspace.sharedWorkspace().runningApplications():
            if ns_app.activationPolicy() != AppKit.NSApplicationActivationPolicyRegular:
                continue
            try:
                app_ref = atomacos.getAppRefByPid(ns_app.processIdentifier())
                el, label = search_app(app_ref, target)
                if el:
                    return el, label
            except Exception:
                continue
    except Exception as e:
        print(f"Running apps search error: {e}")

    return None, None


# ── Vision search (Gemma 4 via Ollama) ───────────────────────────────────────

def ensure_ollama_ready(model):
    """Start Ollama server if not running, then pull the model if not available."""
    # 1. Start server if needed
    server_was_down = False
    try:
        urllib.request.urlopen(f'{OLLAMA_BASE}/', timeout=2)
    except Exception:
        print("Ollama not running — starting server...")
        subprocess.Popen(
            ['ollama', 'serve'],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        server_was_down = True
        for _ in range(20):
            time.sleep(0.5)
            try:
                urllib.request.urlopen(f'{OLLAMA_BASE}/', timeout=1)
                print("Ollama server ready.")
                break
            except Exception:
                continue
        else:
            raise RuntimeError("Ollama server failed to start after 10s")

    # 2. Pull model if not available
    try:
        req = urllib.request.Request(f'{OLLAMA_BASE}/api/tags')
        with urllib.request.urlopen(req, timeout=5) as resp:
            tags = json.loads(resp.read())
        available = {m['name'] for m in tags.get('models', [])}
        if model not in available:
            print(f"Pulling {model} (this may take a while)...")
            subprocess.run(['ollama', 'pull', model], check=True)
            print(f"Model {model} ready.")
    except Exception as e:
        print(f"Warning: could not verify/pull model: {e}")


def find_element_by_vision(query, model=DEFAULT_VISION_MODEL):
    """Take a screenshot and ask Gemma 4 locally to locate the element."""
    screen = QApplication.primaryScreen().geometry()
    screen_w, screen_h = screen.width(), screen.height()

    tmp = tempfile.NamedTemporaryFile(suffix='.png', delete=False)
    screenshot_path = tmp.name
    tmp.close()

    try:
        ensure_ollama_ready(model)

        subprocess.run(
            ['screencapture', '-x', '-t', 'png', screenshot_path],
            check=True, capture_output=True
        )

        with open(screenshot_path, 'rb') as f:
            img_b64 = base64.b64encode(f.read()).decode('utf-8')

        prompt = (
            f'Find the UI element matching this description: "{query}". '
            'Return ONLY a JSON object with keys x, y, width, height '
            'as fractions of the image dimensions (values between 0.0 and 1.0). '
            'Example: {"x": 0.45, "y": 0.30, "width": 0.08, "height": 0.04}. '
            'If the element is not visible, return {"found": false}.'
        )

        payload = json.dumps({
            "model": model,
            "prompt": prompt,
            "images": [img_b64],
            "stream": False,
        }).encode()

        req = urllib.request.Request(
            OLLAMA_URL,
            data=payload,
            headers={'Content-Type': 'application/json'},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read())

        text = result.get('response', '')
        print(f"Vision response: {text[:200]}")

        m = re.search(r'\{[^{}]+\}', text)
        if not m:
            print("Vision: no JSON found in response")
            return None, None

        data = json.loads(m.group())
        if data.get('found') is False or 'x' not in data:
            print("Vision: element not found")
            return None, None

        frame = SimpleNamespace(
            x=data['x'] * screen_w,
            y=data['y'] * screen_h,
            width=data['width'] * screen_w,
            height=data['height'] * screen_h,
        )
        label = query.strip().capitalize()
        return VisionElement(frame), label

    except Exception as e:
        print(f"Vision search error: {e}")
        return None, None
    finally:
        try:
            os.unlink(screenshot_path)
        except Exception:
            pass


# ── Entry point ───────────────────────────────────────────────────────────────

def find_element_by_intent(query, model=DEFAULT_VISION_MODEL):
    print(f"Query: '{query}'")

    # Fast path: native accessibility tree
    el, label = find_element_by_accessibility(query)
    if el:
        print(f"Found via accessibility: {label}")
        return el, label

    # Fallback: vision model (works for web content, images, anything on screen)
    print(f"Accessibility came up empty — trying vision fallback with {model}...")
    el, label = find_element_by_vision(query, model=model)
    if el:
        print(f"Found via vision: {label}")
    return el, label


def main():
    parser = argparse.ArgumentParser(description="Visual UI guide overlay")
    parser.add_argument('query', nargs='*', default=['Music'], help='What to find on screen')
    parser.add_argument('--model', default=DEFAULT_VISION_MODEL,
                        help=f'Ollama vision model to use (default: {DEFAULT_VISION_MODEL})')
    args = parser.parse_args()

    user_query = ' '.join(args.query)

    app = QApplication(sys.argv)
    el, label = find_element_by_intent(user_query, model=args.model)

    if el:
        guide = VisualGuideOverlay(el, label)
        sys.exit(app.exec())
    else:
        print("UI element not found. Check accessibility permissions or whether the app/page is visible.")


if __name__ == "__main__":
    main()
