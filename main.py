import sys
import atomacos
from PyQt6.QtWidgets import QApplication, QWidget
from PyQt6.QtCore import Qt, QRect, QTimer
from PyQt6.QtGui import QPainter, QPen, QColor, QFont

class VisualGuideOverlay(QWidget):
    def __init__(self, target_frame, label_text="Click Here"):
        super().__init__()
        self.target_frame = target_frame
        self.label_text = label_text
        
        # Window Setup: Transparent, Always on Top, Ignore Mouse Clicks
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | 
            Qt.WindowType.WindowStaysOnTopHint | 
            Qt.WindowType.WindowTransparentForInput
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        
        # In a real app, you would map this to the specific monitor coordinates
        self.showFullScreen()
        
        # Auto-close after 8 seconds
        QTimer.singleShot(8000, self.close)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        f = self.target_frame
        # Accessibility coordinates: (x, y, w, h)
        origin_x = int(f['origin'][0])
        origin_y = int(f['origin'][1])
        width = int(f['size'][0])
        height = int(f['size'][1])
        
        rect = QRect(origin_x, origin_y, width, height)
        
        # Draw the Guide Circle (Red)
        pen = QPen(QColor(255, 0, 0, 200))
        pen.setWidth(6)
        painter.setPen(pen)
        painter.drawEllipse(rect.adjusted(-5, -5, 5, 5))
        
        # Draw Label Shadow
        painter.setFont(QFont("Arial", 18, QFont.Weight.Bold))
        painter.setPen(QColor(0, 0, 0, 150))
        painter.drawText(origin_x + 2, origin_y - 8, self.label_text)
        
        # Draw Label Text
        painter.setPen(QColor(255, 255, 255))
        painter.drawText(origin_x, origin_y - 10, self.label_text)

def find_element_by_intent(query):
    query = query.lower()
    try:
        # Check Dock for 'Open' commands
        dock = atomacos.getAppRefByBundleId('com.apple.dock')
        
        if "music" in query:
            el = dock.findFirstR(AXTitle='Music')
            return el.AXFrame, "Click to Open Apple Music"
            
        if "chrome" in query or "browser" in query:
            el = dock.findFirstR(AXTitle='Google Chrome')
            return el.AXFrame, "Open Browser"

        # Check the frontmost app for internal controls (e.g., Unmute)
        active_app = atomacos.getFrontmostApp()
        if "mute" in query or "unmute" in query:
            # Find any button with 'mute' in the title or description
            btns = active_app.findAllR(AXRole='AXButton')
            for btn in btns:
                search_blob = f"{(btn.AXTitle or '')} {(btn.AXDescription or '')}".lower()
                if "mute" in search_blob:
                    return btn.AXFrame, f"Toggle {btn.AXTitle or 'Mute'}"

    except Exception as e:
        print(f"Error: {e}")
    return None, None

def main():
    # Pass intent as an argument: python macos_guide_app.py "unmute my zoom"
    user_query = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "Music"

    app = QApplication(sys.argv)
    frame, label = find_element_by_intent(user_query)
    
    if frame:
        guide = VisualGuideOverlay(frame, label)
        guide.show()
        sys.exit(app.exec())
    else:
        print("UI element not found. Check permissions or if app is visible.")

if __name__ == "__main__":
    main()
