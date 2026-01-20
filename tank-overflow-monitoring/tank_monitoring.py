import cv2
import numpy as np
from collections import deque
import mysql.connector
from datetime import datetime
import json
import tkinter as tk
from tkinter import messagebox
import threading

class SimpleTankMonitor:
    """
    Simple Petroleum Tank Level Monitor
    - Click 4 corners of tank to define measurement area
    - Automatically detects liquid level
    - Shows percentage and liters
    - Alert popup when level >= 90%
    """
    
    def __init__(self, camera_source=0, tank_capacity_liters=1000):
       
        self.camera_source = camera_source
        self.capacity = tank_capacity_liters
        
        # Database config
        self.db_config = {
            'host': 'localhost',
            'user': 'root',
            'password': 'your_password',
            'database': 'tank_monitor'
        }
        
        # Tank measurement area (4 corner points)
        self.tank_corners = []
        self.drawing = False
        self.temp_point = None
        
        # Level detection
        self.current_level_percent = 0.0
        self.level_history = deque(maxlen=30)  # Smooth over 30 frames
        
        # Alert settings
        self.alert_threshold = 90  # Alert at 90%
        self.last_alert_time = 0
        self.alert_cooldown = 60  # 60 seconds between alerts
        
        # Initialize database
        self.setup_database()
        
    def setup_database(self):
        """Create database and tables if they don't exist"""
        try:
            # Connect without database first
            conn = mysql.connector.connect(
                host=self.db_config['host'],
                user=self.db_config['user'],
                password=self.db_config['password']
            )
            cursor = conn.cursor()
            
            # Create database
            cursor.execute(f"CREATE DATABASE IF NOT EXISTS {self.db_config['database']}")
            cursor.execute(f"USE {self.db_config['database']}")
            
            # Create readings table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS tank_readings (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    level_percent FLOAT,
                    level_liters FLOAT,
                    INDEX(timestamp)
                )
            ''')
            
            # Create alerts table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS tank_alerts (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    level_percent FLOAT,
                    message TEXT
                )
            ''')
            
            conn.commit()
            conn.close()
            print("✓ Database setup complete")
            
        except Exception as e:
            print(f"Database setup error: {e}")
    
    def save_reading(self, level_percent, level_liters):
        """Save reading to database"""
        try:
            conn = mysql.connector.connect(**self.db_config)
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO tank_readings (level_percent, level_liters) VALUES (%s, %s)",
                (level_percent, level_liters)
            )
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"Save error: {e}")
    
    def save_alert(self, level_percent, message):
        """Save alert to database"""
        try:
            conn = mysql.connector.connect(**self.db_config)
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO tank_alerts (level_percent, message) VALUES (%s, %s)",
                (level_percent, message)
            )
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"Alert save error: {e}")
    
    def show_alert_popup(self, message):
        """Show alert popup window"""
        def popup():
            root = tk.Tk()
            root.withdraw()
            messagebox.showwarning("⚠️ TANK ALERT", message)
            root.destroy()
        
        threading.Thread(target=popup, daemon=True).start()
    
    def mouse_callback(self, event, x, y, flags, param):
        """Handle mouse clicks to define tank corners"""
        if event == cv2.EVENT_LBUTTONDOWN and self.drawing:
            if len(self.tank_corners) < 4:
                self.tank_corners.append([x, y])
                print(f"Corner {len(self.tank_corners)}/4: ({x}, {y})")
                
                if len(self.tank_corners) == 4:
                    self.drawing = False
                    self.save_config()
                    print("✓ Tank area defined!")
        
        elif event == cv2.EVENT_MOUSEMOVE and self.drawing:
            self.temp_point = (x, y)
    
    def detect_liquid_level(self, frame):
        """
        Detect liquid level in the tank
        Uses edge detection to find the liquid surface line
        """
        if len(self.tank_corners) != 4:
            return None
        
        # Get tank region
        pts = np.array(self.tank_corners, dtype=np.int32)
        x, y, w, h = cv2.boundingRect(pts)
        
        # Extract tank ROI
        roi = frame[y:y+h, x:x+w]
        if roi.size == 0:
            return None
        
        # Convert to grayscale
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        
        # Enhance contrast
        gray = cv2.equalizeHist(gray)
        
        # Blur to reduce noise
        blur = cv2.GaussianBlur(gray, (5, 5), 0)
        
        # Edge detection
        edges = cv2.Canny(blur, 30, 100)
        
        # Find horizontal lines (liquid surface)
        lines = cv2.HoughLinesP(edges, 1, np.pi/180, 30, minLineLength=20, maxLineGap=10)
        
        if lines is None:
            return None
        
        # Find topmost horizontal line
        top_line_y = None
        for line in lines:
            x1, y1, x2, y2 = line[0]
            # Check if roughly horizontal (within 15 degrees)
            if abs(y1 - y2) < h * 0.1:
                if top_line_y is None or y1 < top_line_y:
                    top_line_y = y1
        
        if top_line_y is None:
            return None
        
        # Calculate percentage
        # Liquid fills from bottom up
        empty_height = top_line_y
        total_height = h
        filled_height = total_height - empty_height
        percentage = (filled_height / total_height) * 100
        
        # Clamp between 0 and 100
        return max(0, min(100, percentage))
    
    def draw_tank_visualization(self, frame):
        """Draw tank outline and level information"""
        if len(self.tank_corners) != 4:
            return frame
        
        pts = np.array(self.tank_corners, dtype=np.int32)
        
        # Determine color based on level
        if self.current_level_percent >= 95:
            color = (0, 0, 255)  # Red - Critical
            status = "CRITICAL - OVERFLOW RISK"
        elif self.current_level_percent >= 90:
            color = (0, 140, 255)  # Orange - Warning
            status = "WARNING - NEARLY FULL"
        elif self.current_level_percent >= 75:
            color = (0, 255, 255)  # Yellow - High
            status = "HIGH"
        elif self.current_level_percent <= 10:
            color = (0, 0, 139)  # Dark Red - Critical Low
            status = "CRITICAL LOW"
        elif self.current_level_percent <= 25:
            color = (0, 165, 255)  # Orange - Low
            status = "LOW"
        else:
            color = (0, 255, 0)  # Green - Normal
            status = "NORMAL"
        
        # Draw tank outline
        cv2.polylines(frame, [pts], True, color, 3)
        
        # Get tank dimensions
        x, y, w, h = cv2.boundingRect(pts)
        
        # Draw fill level
        fill_height = int((self.current_level_percent / 100) * h)
        fill_y = y + h - fill_height
        
        overlay = frame.copy()
        fill_pts = np.array([
            [x, fill_y],
            [x + w, fill_y],
            [x + w, y + h],
            [x, y + h]
        ], dtype=np.int32)
        cv2.fillPoly(overlay, [fill_pts], color)
        cv2.addWeighted(overlay, 0.3, frame, 0.7, 0, frame)
        
        # Draw liquid surface line
        cv2.line(frame, (x, fill_y), (x + w, fill_y), (255, 255, 255), 3)
        
        # Calculate liters
        liters = (self.current_level_percent / 100) * self.capacity
        
        # Draw information box
        info_x = x
        info_y = y - 100
        
        # Background box
        cv2.rectangle(frame, (info_x - 5, info_y - 5), 
                     (info_x + 350, info_y + 95), (0, 0, 0), -1)
        cv2.rectangle(frame, (info_x - 5, info_y - 5), 
                     (info_x + 350, info_y + 95), color, 2)
        
        # Text information
        cv2.putText(frame, f"TANK LEVEL: {self.current_level_percent:.1f}%", 
                   (info_x, info_y + 25), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
        
        cv2.putText(frame, f"Volume: {liters:.1f}L / {self.capacity}L", 
                   (info_x, info_y + 55), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
        
        cv2.putText(frame, f"Status: {status}", 
                   (info_x, info_y + 85), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)
        
        # Draw progress bar
        bar_x = x
        bar_y = y + h + 20
        bar_w = w
        bar_h = 30
        
        # Background
        cv2.rectangle(frame, (bar_x, bar_y), (bar_x + bar_w, bar_y + bar_h), 
                     (50, 50, 50), -1)
        
        # Fill
        fill_w = int((self.current_level_percent / 100) * bar_w)
        cv2.rectangle(frame, (bar_x, bar_y), (bar_x + fill_w, bar_y + bar_h), 
                     color, -1)
        
        # Border
        cv2.rectangle(frame, (bar_x, bar_y), (bar_x + bar_w, bar_y + bar_h), 
                     (255, 255, 255), 2)
        
        # Percentage text on bar
        text = f"{self.current_level_percent:.1f}%"
        text_size = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.8, 2)[0]
        text_x = bar_x + (bar_w - text_size[0]) // 2
        text_y = bar_y + (bar_h + text_size[1]) // 2
        cv2.putText(frame, text, (text_x, text_y), 
                   cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
        
        return frame
    
    def draw_setup_guide(self, frame):
        """Draw setup instructions"""
        if self.drawing:
            # Draw current corners
            for i, corner in enumerate(self.tank_corners):
                cv2.circle(frame, tuple(corner), 8, (0, 255, 0), -1)
                cv2.putText(frame, str(i+1), (corner[0]+10, corner[1]+10),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
            
            # Draw lines between corners
            for i in range(len(self.tank_corners) - 1):
                cv2.line(frame, tuple(self.tank_corners[i]), 
                        tuple(self.tank_corners[i+1]), (0, 255, 0), 2)
            
            # Preview line to cursor
            if len(self.tank_corners) > 0 and self.temp_point:
                cv2.line(frame, tuple(self.tank_corners[-1]), 
                        self.temp_point, (0, 255, 0), 1)
            
            # Closing line preview
            if len(self.tank_corners) == 3 and self.temp_point:
                cv2.line(frame, self.temp_point, 
                        tuple(self.tank_corners[0]), (0, 255, 0), 1)
            
            # Instructions
            remaining = 4 - len(self.tank_corners)
            cv2.putText(frame, f"SETUP: Click {remaining} corner(s) of the tank", 
                       (10, 40), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
        
        return frame
    
    def check_alert(self):
        """Check if alert needs to be triggered"""
        if self.current_level_percent >= self.alert_threshold:
            current_time = datetime.now().timestamp()
            
            # Check cooldown
            if current_time - self.last_alert_time > self.alert_cooldown:
                liters = (self.current_level_percent / 100) * self.capacity
                message = f"⚠️ TANK LEVEL CRITICAL!\n\nCurrent Level: {self.current_level_percent:.1f}%\nVolume: {liters:.1f}L / {self.capacity}L\n\nTank is nearly full!"
                
                # Show popup
                self.show_alert_popup(message)
                
                # Save to database
                self.save_alert(self.current_level_percent, message)
                
                self.last_alert_time = current_time
                print(f"🚨 ALERT: Tank at {self.current_level_percent:.1f}%")
    
    def save_config(self):
        """Save tank configuration"""
        config = {
            'tank_corners': self.tank_corners,
            'capacity': self.capacity,
            'alert_threshold': self.alert_threshold
        }
        with open('tank_config.json', 'w') as f:
            json.dump(config, f, indent=4)
        print("✓ Configuration saved")
    
    def load_config(self):
        """Load tank configuration"""
        try:
            with open('tank_config.json', 'r') as f:
                config = json.load(f)
            self.tank_corners = config.get('tank_corners', [])
            self.capacity = config.get('capacity', self.capacity)
            self.alert_threshold = config.get('alert_threshold', 90)
            print("✓ Configuration loaded")
            return True
        except FileNotFoundError:
            print("No saved configuration found")
            return False
    
    def run(self):
        """Start the tank monitor"""
        # Try to load existing config
        self.load_config()
        
        # Open camera
        cap = cv2.VideoCapture(self.camera_source)
        
        if not cap.isOpened():
            print(f"❌ Error: Cannot open camera {self.camera_source}")
            return
        
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
        
        window_name = 'Petroleum Tank Level Monitor'
        cv2.namedWindow(window_name)
        cv2.setMouseCallback(window_name, self.mouse_callback)
        
        print("\n" + "="*50)
        print("PETROLEUM TANK LEVEL MONITOR")
        print("="*50)
        print("\nCONTROLS:")
        print("  SPACE - Start setup (click 4 tank corners)")
        print("  R     - Reset tank area")
        print("  S     - Save configuration")
        print("  Q     - Quit")
        print("\nWARNING LEVELS:")
        print(f"  🟢 Normal:  0-74%")
        print(f"  🟡 High:    75-89%")
        print(f"  🟠 Warning: 90-94%")
        print(f"  🔴 Critical: 95-100%")
        print("="*50 + "\n")
        
        frame_count = 0
        
        while True:
            ret, frame = cap.read()
            if not ret:
                print("❌ Error: Cannot read frame")
                break
            
            frame_count += 1
            
            # Process level detection
            if len(self.tank_corners) == 4:
                level = self.detect_liquid_level(frame)
                
                if level is not None:
                    # Smooth the reading
                    self.level_history.append(level)
                    self.current_level_percent = np.mean(self.level_history)
                    
                    # Save to database every 5 seconds (at 30fps = 150 frames)
                    if frame_count % 150 == 0:
                        liters = (self.current_level_percent / 100) * self.capacity
                        self.save_reading(self.current_level_percent, liters)
                    
                    # Check for alerts
                    self.check_alert()
                
                # Draw visualization
                frame = self.draw_tank_visualization(frame)
            
            # Draw setup guide
            if self.drawing or len(self.tank_corners) < 4:
                frame = self.draw_setup_guide(frame)
            
            # Draw status
            status = "SETUP MODE" if self.drawing else "MONITORING" if len(self.tank_corners) == 4 else "READY"
            cv2.putText(frame, f"Status: {status}", (10, frame.shape[0] - 20),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)
            
            cv2.imshow(window_name, frame)
            
            # Handle keyboard
            key = cv2.waitKey(1) & 0xFF
            
            if key == ord('q'):
                break
            elif key == ord('d'):  # 'd' to start setup
                self.drawing = True
                self.tank_corners = []
                print("Click 4 corners of the tank...")
            elif key == ord('r'):  # Reset
                self.tank_corners = []
                self.drawing = False
                print("Tank area reset")
            elif key == ord('s'):  # Save
                self.save_config()
        
        cap.release()
        cv2.destroyAllWindows()
        
        print(f"\n✓ Monitoring session ended")
        print(f"Final level: {self.current_level_percent:.1f}%")


# ==================== USAGE ====================

if __name__ == "__main__":
    # For Webcam
    monitor = SimpleTankMonitor(
        camera_source=r'C:\Users\ATGIN-Intern\test-ss\tank_monitoring\water.mp4',           # 0 = default webcam, 1 = second webcam
        tank_capacity_liters=1  # Your tank capacity
    )
    
    # For IP Camera (RTSP)
    # monitor = SimpleTankMonitor(
    #     camera_source='rtsp://username:password@192.168.1.100:554/stream',
    #     tank_capacity_liters=1000
    # )
    
    # For HTTP/MJPEG Camera
    # monitor = SimpleTankMonitor(
    #     camera_source='http://192.168.1.100:8080/video',
    #     tank_capacity_liters=1000
    # )
    
    monitor.run()