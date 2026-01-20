#!/home/ruth-ai-vas-ms-v2/ai/venv/bin/python3
"""
Simple Tank Overflow Detection Test
Test with a coffee mug and webcam - no database required
"""

import cv2
import numpy as np
import sys
import os

# Add AI models path
sys.path.insert(0, '/home/ruth-ai-vas-ms-v2/ai/models/tank_overflow_monitoring/1.0.0')
from tank_detector import TankOverflowDetector


class MugTester:
    """Test tank detection with a coffee mug"""

    def __init__(self, camera_id=0, mug_capacity_ml=300):
        self.camera_id = camera_id
        self.capacity = mug_capacity_ml
        self.detector = TankOverflowDetector()

        # Mug corners (will be set by user)
        self.mug_corners = []
        self.drawing = False
        self.window_name = "Tank Overflow Test - Press SPACE to define mug area, Q to quit"

    def mouse_callback(self, event, x, y, flags, param):
        """Handle mouse clicks to define mug area"""
        if event == cv2.EVENT_LBUTTONDOWN and self.drawing:
            if len(self.mug_corners) < 4:
                self.mug_corners.append([x, y])
                print(f"Corner {len(self.mug_corners)}/4: ({x}, {y})")

                if len(self.mug_corners) == 4:
                    self.drawing = False
                    print("✓ Mug area defined! Monitoring started.")

    def draw_overlay(self, frame, result):
        """Draw detection overlay on frame"""
        display = frame.copy()

        # Draw mug area
        if len(self.mug_corners) == 4:
            pts = np.array(self.mug_corners, dtype=np.int32)
            cv2.polylines(display, [pts], True, (0, 255, 0), 2)

            # Label corners
            for i, corner in enumerate(self.mug_corners):
                cv2.circle(display, tuple(corner), 5, (0, 255, 0), -1)
                cv2.putText(display, str(i+1),
                           (corner[0]+10, corner[1]+10),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)

        # Draw liquid surface if detected
        if result and result.get('detections'):
            for det in result['detections']:
                surface_y = det.get('surface_y')
                if surface_y is not None:
                    # Draw surface line
                    x1 = self.mug_corners[0][0]
                    x2 = self.mug_corners[1][0]
                    y = self.mug_corners[0][1] + surface_y
                    cv2.line(display, (x1, y), (x2, y), (0, 0, 255), 2)

        # Draw info panel
        if result:
            level = result.get('level_percent', 0)
            conf = result.get('confidence', 0)
            volume_ml = (level / 100.0) * self.capacity

            # Choose color based on level
            if level >= 90:
                color = (0, 0, 255)  # Red
                status = "ALERT!"
            elif level >= 75:
                color = (0, 165, 255)  # Orange
                status = "High"
            elif level >= 50:
                color = (0, 255, 255)  # Yellow
                status = "Medium"
            else:
                color = (0, 255, 0)  # Green
                status = "Normal"

            # Info box
            cv2.rectangle(display, (10, 10), (350, 150), (0, 0, 0), -1)
            cv2.rectangle(display, (10, 10), (350, 150), (255, 255, 255), 2)

            # Text
            cv2.putText(display, f"Level: {level:.1f}%",
                       (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.8, color, 2)
            cv2.putText(display, f"Volume: {volume_ml:.0f}ml / {self.capacity}ml",
                       (20, 70), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)
            cv2.putText(display, f"Status: {status}",
                       (20, 100), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)
            cv2.putText(display, f"Confidence: {conf:.2f}",
                       (20, 130), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)

        # Instructions
        if self.drawing:
            msg = f"Click corner {len(self.mug_corners)+1}/4 of the mug opening"
            cv2.putText(display, msg, (10, frame.shape[0]-20),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)
        elif len(self.mug_corners) == 0:
            cv2.putText(display, "Press SPACE to define mug area",
                       (10, frame.shape[0]-20),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)

        return display

    def run(self):
        """Run the test"""
        print("\n" + "="*60)
        print("Tank Overflow Detection Test")
        print("="*60)
        print(f"Camera ID: {self.camera_id}")
        print(f"Mug capacity: {self.capacity}ml")
        print("\nInstructions:")
        print("1. Press SPACE to start defining mug area")
        print("2. Click 4 corners of mug opening (top-left, top-right, bottom-right, bottom-left)")
        print("3. Fill/empty the mug to test detection")
        print("4. Press Q to quit")
        print("="*60 + "\n")

        # Open camera
        cap = cv2.VideoCapture(self.camera_id)
        if not cap.isOpened():
            print(f"✗ Failed to open camera {self.camera_id}")
            print("\nTrying to find available cameras...")
            for i in range(5):
                test_cap = cv2.VideoCapture(i)
                if test_cap.isOpened():
                    print(f"  Camera {i}: Available")
                    test_cap.release()

            return

        print(f"✓ Camera {self.camera_id} opened")

        # Create window and set mouse callback
        cv2.namedWindow(self.window_name)
        cv2.setMouseCallback(self.window_name, self.mouse_callback)

        while True:
            ret, frame = cap.read()
            if not ret:
                print("✗ Failed to read frame")
                break

            # Run detection if mug area is defined
            result = None
            if len(self.mug_corners) == 4:
                config = {
                    "tank_corners": self.mug_corners,
                    "capacity_liters": self.capacity / 1000.0,  # Convert to liters
                    "alert_threshold": 90
                }
                result = self.detector.detect_level(frame, config)

                # Print results to console
                if result:
                    level = result.get('level_percent', 0)
                    print(f"Level: {level:.1f}% | Confidence: {result.get('confidence', 0):.2f}", end='\r')

            # Draw overlay
            display = self.draw_overlay(frame, result)

            # Show frame
            cv2.imshow(self.window_name, display)

            # Handle keys
            key = cv2.waitKey(1) & 0xFF
            if key == ord('q') or key == 27:  # Q or ESC
                break
            elif key == ord(' '):  # Space
                if not self.drawing:
                    self.mug_corners = []
                    self.drawing = True
                    print("\nDefining mug area... Click 4 corners:")
            elif key == ord('r'):  # Reset
                self.mug_corners = []
                self.drawing = False
                print("\nMug area reset. Press SPACE to redefine.")

        cap.release()
        cv2.destroyAllWindows()
        print("\n\nTest complete!")


if __name__ == "__main__":
    # Configuration
    CAMERA_ID = 0  # Change if using different camera
    MUG_CAPACITY_ML = 300  # Typical coffee mug capacity

    # You can override from command line
    if len(sys.argv) > 1:
        CAMERA_ID = int(sys.argv[1])
    if len(sys.argv) > 2:
        MUG_CAPACITY_ML = int(sys.argv[2])

    tester = MugTester(camera_id=CAMERA_ID, mug_capacity_ml=MUG_CAPACITY_ML)
    tester.run()
