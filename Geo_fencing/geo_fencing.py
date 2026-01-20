import cv2
import numpy as np
from ultralytics import YOLO
from collections import defaultdict, deque
import json
import os
from datetime import datetime, timedelta
import mysql.connector
from mysql.connector import Error
from pathlib import Path
import threading
import queue
import time

class MultiCameraZoneTracker:
    def __init__(self, model_path='person_best.pt', 
                 db_config=None, camera_id=0, camera_name=None):
        """Enhanced multi-camera zone tracking system with MySQL and alerts"""
        print(f"Initializing camera {camera_id}: {camera_name}")
        print(f"Loading model: {model_path}")
        
        self.model = YOLO(model_path)
        self.camera_id = camera_id
        self.camera_name = camera_name or f"Camera_{camera_id}"
        
        # Database configuration
        self.db_config = db_config or {
            'host': 'localhost',
            'user': 'root',
            'password': 'your_password',
            'database': 'zone_tracking'
        }
        
        # Zone configuration
        self.zones = []
        self.zone_names = []
        self.zone_colors = []
        self.zone_capacities = []
        self.zone_directions = []
        self.zone_alert_enabled = []  # Alert flag per zone
        
        # Tracking data
        self.track_history = defaultdict(lambda: deque(maxlen=50))
        self.zone_counts = defaultdict(int)
        self.zone_total_entries = defaultdict(int)
        self.zone_total_exits = defaultdict(int)
        self.object_zone_status = {}
        self.object_entry_times = {}
        self.object_dwell_times = defaultdict(list)
        
        # Alert system
        self.active_alerts = []
        self.alert_queue = queue.Queue()
        self.alert_sound_enabled = True
        self.alert_display_time = 5  # seconds
        
        # Multi-camera sync
        self.global_track_map = {}  # Maps local track_id to global_track_id
        self.cross_camera_tracks = {}  # Shared across cameras
        
        # Performance optimization
        self.process_every_n_frames = 2
        self.frame_count = 0
        self.last_processed_frame = None
        
        # Drawing mode
        self.drawing_mode = False
        self.current_zone = []
        self.temp_point = None
        
        # Configuration
        self.conf_threshold = 0.5
        self.iou_threshold = 0.5
        self.dwell_time_threshold = 10.0
        
        # Analytics
        self.fps = 30
        self.start_time = datetime.now()
        
        # Database setup
        self.init_database()
        
        # Heatmap
        self.heatmap = None
        self.show_heatmap = False
        
        # Alert thread
        self.alert_thread = threading.Thread(target=self.process_alerts, daemon=True)
        self.alert_thread.start()
        
    def get_db_connection(self):
        """Create and return MySQL database connection"""
        try:
            connection = mysql.connector.connect(**self.db_config)
            if connection.is_connected():
                return connection
        except Error as e:
            print(f"Error connecting to MySQL: {e}")
            return None
    
    def init_database(self):
        """Initialize MySQL database and create tables if they don't exist"""
        connection = self.get_db_connection()
        if not connection:
            print("Failed to connect to database. Creating database...")
            # Try to create database if it doesn't exist
            try:
                temp_config = self.db_config.copy()
                db_name = temp_config.pop('database')
                connection = mysql.connector.connect(**temp_config)
                cursor = connection.cursor()
                cursor.execute(f"CREATE DATABASE IF NOT EXISTS {db_name}")
                print(f"Database '{db_name}' created successfully")
                connection.close()
                connection = self.get_db_connection()
            except Error as e:
                print(f"Error creating database: {e}")
                return
        
        cursor = connection.cursor()
        
        # Create cameras table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS cameras (
                camera_id INT PRIMARY KEY,
                camera_name VARCHAR(100) NOT NULL,
                status ENUM('active', 'inactive') DEFAULT 'active',
                last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Create zones table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS zones (
                zone_id INT AUTO_INCREMENT PRIMARY KEY,
                camera_id INT,
                zone_name VARCHAR(100) NOT NULL,
                zone_data JSON,
                capacity INT DEFAULT 0,
                alert_enabled BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (camera_id) REFERENCES cameras(camera_id) ON DELETE CASCADE
            )
        ''')
        
        # Create events table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS events (
                event_id BIGINT AUTO_INCREMENT PRIMARY KEY,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                camera_id INT,
                track_id INT,
                global_track_id VARCHAR(100),
                zone_name VARCHAR(100),
                event_type ENUM('entry', 'exit', 'loitering', 'capacity_breach'),
                dwell_time FLOAT,
                metadata JSON,
                INDEX idx_timestamp (timestamp),
                INDEX idx_camera (camera_id),
                INDEX idx_zone (zone_name),
                FOREIGN KEY (camera_id) REFERENCES cameras(camera_id) ON DELETE CASCADE
            )
        ''')
        
        # Create alerts table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS alerts (
                alert_id BIGINT AUTO_INCREMENT PRIMARY KEY,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                camera_id INT,
                zone_name VARCHAR(100),
                alert_type ENUM('entry', 'capacity', 'loitering', 'unauthorized'),
                severity ENUM('low', 'medium', 'high', 'critical'),
                message TEXT,
                track_id INT,
                acknowledged BOOLEAN DEFAULT FALSE,
                acknowledged_at TIMESTAMP NULL,
                INDEX idx_timestamp (timestamp),
                INDEX idx_acknowledged (acknowledged),
                FOREIGN KEY (camera_id) REFERENCES cameras(camera_id) ON DELETE CASCADE
            )
        ''')
        
        # Create zone_stats table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS zone_stats (
                stat_id BIGINT AUTO_INCREMENT PRIMARY KEY,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                camera_id INT,
                zone_name VARCHAR(100),
                total_entries INT DEFAULT 0,
                total_exits INT DEFAULT 0,
                current_count INT DEFAULT 0,
                avg_dwell_time FLOAT,
                max_dwell_time FLOAT,
                INDEX idx_timestamp (timestamp),
                FOREIGN KEY (camera_id) REFERENCES cameras(camera_id) ON DELETE CASCADE
            )
        ''')
        
        # Create cross_camera_tracks table for multi-camera sync
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS cross_camera_tracks (
                global_track_id VARCHAR(100) PRIMARY KEY,
                first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                cameras_visited JSON,
                total_zones_visited INT DEFAULT 0,
                metadata JSON
            )
        ''')
        
        connection.commit()
        
        # Register this camera
        cursor.execute('''
            INSERT INTO cameras (camera_id, camera_name, status)
            VALUES (%s, %s, 'active')
            ON DUPLICATE KEY UPDATE 
            camera_name = VALUES(camera_name),
            status = 'active',
            last_seen = CURRENT_TIMESTAMP
        ''', (self.camera_id, self.camera_name))
        
        connection.commit()
        connection.close()
        print("Database initialized successfully")
    
    def log_event(self, track_id, zone_name, event_type, dwell_time=None, metadata=None):
        """Log tracking event to database"""
        connection = self.get_db_connection()
        if not connection:
            return
        
        cursor = connection.cursor()
        global_track_id = self.global_track_map.get(track_id, f"C{self.camera_id}_T{track_id}")
        
        cursor.execute('''
            INSERT INTO events (camera_id, track_id, global_track_id, zone_name, 
                              event_type, dwell_time, metadata)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        ''', (self.camera_id, track_id, global_track_id, zone_name, 
              event_type, dwell_time, json.dumps(metadata) if metadata else None))
        
        connection.commit()
        connection.close()
    
    def create_alert(self, zone_name, alert_type, severity, message, track_id=None):
        """Create an alert in the database and trigger notification"""
        connection = self.get_db_connection()
        if not connection:
            return
        
        cursor = connection.cursor()
        cursor.execute('''
            INSERT INTO alerts (camera_id, zone_name, alert_type, severity, message, track_id)
            VALUES (%s, %s, %s, %s, %s, %s)
        ''', (self.camera_id, zone_name, alert_type, severity, message, track_id))
        
        alert_id = cursor.lastrowid
        connection.commit()
        connection.close()
        
        # Add to alert queue for display
        alert_data = {
            'alert_id': alert_id,
            'timestamp': datetime.now(),
            'camera_name': self.camera_name,
            'zone_name': zone_name,
            'alert_type': alert_type,
            'severity': severity,
            'message': message,
            'track_id': track_id
        }
        self.alert_queue.put(alert_data)
        print(f"🚨 ALERT: {message}")
    
    def process_alerts(self):
        """Process alerts in background thread"""
        while True:
            try:
                alert = self.alert_queue.get(timeout=1)
                self.active_alerts.append({
                    **alert,
                    'display_until': datetime.now() + timedelta(seconds=self.alert_display_time)
                })
                
                # Play alert sound (optional)
                if self.alert_sound_enabled:
                    # You can add sound playback here using pygame or playsound
                    print(f"🔔 Alert sound for: {alert['message']}")
                    
            except queue.Empty:
                # Clean up expired alerts
                current_time = datetime.now()
                self.active_alerts = [
                    a for a in self.active_alerts 
                    if a['display_until'] > current_time
                ]
            except Exception as e:
                print(f"Error processing alert: {e}")
    
    def save_zone_stats(self):
        """Save current zone statistics to database"""
        connection = self.get_db_connection()
        if not connection:
            return
        
        cursor = connection.cursor()
        
        for i, name in enumerate(self.zone_names):
            avg_dwell = np.mean(self.object_dwell_times[i]) if self.object_dwell_times[i] else 0
            max_dwell = max(self.object_dwell_times[i]) if self.object_dwell_times[i] else 0
            
            cursor.execute('''
                INSERT INTO zone_stats (camera_id, zone_name, total_entries, 
                                      total_exits, current_count, avg_dwell_time, max_dwell_time)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            ''', (self.camera_id, name, self.zone_total_entries[i],
                  self.zone_total_exits[i], self.zone_counts[i], avg_dwell, max_dwell))
        
        connection.commit()
        connection.close()
    
    def point_in_polygon(self, point, polygon):
        """Check if point is inside polygon using ray casting"""
        x, y = point
        n = len(polygon)
        inside = False
        
        p1x, p1y = polygon[0]
        for i in range(1, n + 1):
            p2x, p2y = polygon[i % n]
            if y > min(p1y, p2y):
                if y <= max(p1y, p2y):
                    if x <= max(p1x, p2x):
                        if p1y != p2y:
                            xinters = (y - p1y) * (p2x - p1x) / (p2y - p1y) + p1x
                        if p1x == p2x or x <= xinters:
                            inside = not inside
            p1x, p1y = p2x, p2y
        
        return inside
    
    def get_box_center(self, box):
        """Get center point of bounding box"""
        x1, y1, x2, y2 = box
        return (int((x1 + x2) / 2), int((y1 + y2) / 2))
    
    def calculate_speed(self, track_id):
        """Calculate object speed in pixels per second"""
        if len(self.track_history[track_id]) < 2:
            return 0
        
        points = list(self.track_history[track_id])
        dist = np.linalg.norm(np.array(points[-1]) - np.array(points[0]))
        time_elapsed = len(points) / self.fps
        
        return dist / time_elapsed if time_elapsed > 0 else 0
    
    def check_alerts(self, zone_idx, track_id):
        """Check for alert conditions and trigger alerts"""
        zone_name = self.zone_names[zone_idx]
        
        # Check if alerts are enabled for this zone
        if not self.zone_alert_enabled[zone_idx]:
            return
        
        # Capacity alert
        if self.zone_capacities[zone_idx] > 0:
            if self.zone_counts[zone_idx] > self.zone_capacities[zone_idx]:
                message = f"{zone_name} is OVERCROWDED: {self.zone_counts[zone_idx]}/{self.zone_capacities[zone_idx]} people"
                self.create_alert(zone_name, 'capacity', 'high', message)
        
        # Dwell time alert (loitering)
        if track_id in self.object_entry_times:
            entry_time = self.object_entry_times[track_id].get(zone_idx)
            if entry_time:
                dwell_time = (datetime.now() - entry_time).total_seconds()
                if dwell_time > self.dwell_time_threshold:
                    message = f"Person {track_id} loitering in {zone_name} for {dwell_time:.1f}s"
                    self.create_alert(zone_name, 'loitering', 'medium', message, track_id)
    
    def update_heatmap(self, center, frame_shape):
        """Update heatmap with object position"""
        if self.heatmap is None:
            self.heatmap = np.zeros(frame_shape[:2], dtype=np.float32)
        
        cv2.circle(self.heatmap, center, 20, 1, -1)
        self.heatmap = cv2.GaussianBlur(self.heatmap, (15, 15), 0)
    
    def mouse_callback(self, event, x, y, flags, param):
        """Handle mouse events for zone creation"""
        if event == cv2.EVENT_LBUTTONDOWN and self.drawing_mode:
            self.current_zone.append((x, y))
            print(f"Point added: ({x}, {y})")
        
        elif event == cv2.EVENT_MOUSEMOVE and self.drawing_mode:
            self.temp_point = (x, y)
    
    def add_zone(self, points, name=None, color=None, capacity=0, 
                 direction=None, alert_enabled=True):
        """Add a new zone with configuration"""
        if len(points) < 3:
            print("Zone must have at least 3 points")
            return False
        
        self.zones.append(points)
        zone_id = len(self.zones) - 1
        
        if name is None:
            name = f"Zone {zone_id + 1}"
        self.zone_names.append(name)
        
        if color is None:
            color = tuple(np.random.randint(100, 255, 3).tolist())
        self.zone_colors.append(color)
        
        self.zone_capacities.append(capacity)
        self.zone_directions.append(direction)
        self.zone_alert_enabled.append(alert_enabled)
        
        # Save to database
        connection = self.get_db_connection()
        if connection:
            cursor = connection.cursor()
            zone_data = {
                'points': points,
                'color': color,
                'direction': direction
            }
            cursor.execute('''
                INSERT INTO zones (camera_id, zone_name, zone_data, capacity, alert_enabled)
                VALUES (%s, %s, %s, %s, %s)
            ''', (self.camera_id, name, json.dumps(zone_data), capacity, alert_enabled))
            connection.commit()
            connection.close()
        
        print(f"Zone '{name}' added | Capacity: {capacity if capacity > 0 else 'Unlimited'} | Alerts: {'ON' if alert_enabled else 'OFF'}")
        return True
    
    def save_zones(self, filename='zones_config.json'):
        """Save zones configuration to file"""
        config = {
            'camera_id': self.camera_id,
            'camera_name': self.camera_name,
            'zones': [
                {
                    'points': zone,
                    'name': name,
                    'color': color,
                    'capacity': capacity,
                    'direction': direction,
                    'alert_enabled': alert_enabled
                }
                for zone, name, color, capacity, direction, alert_enabled in zip(
                    self.zones, self.zone_names, self.zone_colors, 
                    self.zone_capacities, self.zone_directions, self.zone_alert_enabled
                )
            ]
        }
        with open(filename, 'w') as f:
            json.dump(config, f, indent=4)
        print(f"Zones saved to {filename}")
    
    def load_zones(self, filename='zones_config.json'):
        """Load zones configuration from file"""
        if not os.path.exists(filename):
            print(f"Config file {filename} not found")
            return False
        
        with open(filename, 'r') as f:
            config = json.load(f)
        
        self.zones = []
        self.zone_names = []
        self.zone_colors = []
        self.zone_capacities = []
        self.zone_directions = []
        self.zone_alert_enabled = []
        
        for zone_data in config['zones']:
            self.zones.append(zone_data['points'])
            self.zone_names.append(zone_data['name'])
            self.zone_colors.append(tuple(zone_data['color']))
            self.zone_capacities.append(zone_data.get('capacity', 0))
            self.zone_directions.append(zone_data.get('direction', None))
            self.zone_alert_enabled.append(zone_data.get('alert_enabled', True))
        
        print(f"Loaded {len(self.zones)} zones from {filename}")
        return True
    
    def draw_zones(self, frame):
        """Draw all zones with statistics - RED if occupied"""
        overlay = frame.copy()
        
        for i, (zone, name, color) in enumerate(zip(self.zones, self.zone_names, self.zone_colors)):
            pts = np.array(zone, np.int32)
            
            # Use RED color if zone has people AND alerts are enabled
            if self.zone_counts[i] > 0 and self.zone_alert_enabled[i]:
                zone_color = (0, 0, 255)  # RED in BGR
                border_color = (0, 0, 255)
                border_thickness = 4
            else:
                zone_color = color
                border_color = color
                border_thickness = 3
            
            # Check for overcrowding
            if (self.zone_capacities[i] > 0 and 
                self.zone_counts[i] > self.zone_capacities[i]):
                border_color = (0, 0, 255)
                border_thickness = 5
            
            # Draw filled polygon
            cv2.fillPoly(overlay, [pts], zone_color)
            cv2.polylines(frame, [pts], True, border_color, border_thickness)
            
            # Draw zone info
            centroid = np.mean(pts, axis=0).astype(int)
            text_color = (255, 255, 255)
            
            # Zone name with alert indicator
            alert_indicator = " 🚨" if (self.zone_counts[i] > 0 and self.zone_alert_enabled[i]) else ""
            cv2.putText(frame, f"{name}{alert_indicator}", tuple(centroid), 
                       cv2.FONT_HERSHEY_SIMPLEX, 0.8, text_color, 2)
            
            # Statistics
            capacity_str = f"/{self.zone_capacities[i]}" if self.zone_capacities[i] > 0 else ""
            stats_text = f"Now: {self.zone_counts[i]}{capacity_str} | In: {self.zone_total_entries[i]} | Out: {self.zone_total_exits[i]}"
            cv2.putText(frame, stats_text, (centroid[0], centroid[1] + 25),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.5, text_color, 2)
            
            # Average dwell time
            if self.object_dwell_times[i]:
                avg_dwell = np.mean(self.object_dwell_times[i])
                cv2.putText(frame, f"Avg Stay: {avg_dwell:.1f}s", 
                          (centroid[0], centroid[1] + 45),
                          cv2.FONT_HERSHEY_SIMPLEX, 0.5, text_color, 2)
        
        # Blend overlay
        cv2.addWeighted(overlay, 0.3, frame, 0.7, 0, frame)
        
        return frame
    
    def draw_alerts(self, frame):
        """Draw active alerts on frame"""
        y_offset = 100
        for alert in self.active_alerts[-5:]:
            severity_colors = {
                'low': (0, 255, 255),
                'medium': (0, 165, 255),
                'high': (0, 0, 255),
                'critical': (0, 0, 139)
            }
            color = severity_colors.get(alert['severity'], (0, 0, 255))
            
            alert_text = f"🚨 [{alert['severity'].upper()}] {alert['message']}"
            
            # Draw background box
            text_size = cv2.getTextSize(alert_text, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)[0]
            cv2.rectangle(frame, (5, y_offset - 25), 
                         (15 + text_size[0], y_offset + 5), 
                         color, -1)
            
            # Draw text
            cv2.putText(frame, alert_text, (10, y_offset),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
            y_offset += 40
        
        return frame
    
    def draw_heatmap(self, frame):
        """Draw heatmap overlay"""
        if self.heatmap is not None and self.show_heatmap:
            heatmap_norm = cv2.normalize(self.heatmap, None, 0, 255, cv2.NORM_MINMAX)
            heatmap_colored = cv2.applyColorMap(heatmap_norm.astype(np.uint8), cv2.COLORMAP_JET)
            frame = cv2.addWeighted(frame, 0.7, heatmap_colored, 0.3, 0)
        
        return frame
    
    def draw_current_zone(self, frame):
        """Draw the zone currently being created"""
        if len(self.current_zone) > 0:
            for point in self.current_zone:
                cv2.circle(frame, point, 5, (0, 255, 0), -1)
            
            for i in range(len(self.current_zone) - 1):
                cv2.line(frame, self.current_zone[i], self.current_zone[i + 1], (0, 255, 0), 2)
            
            if self.temp_point and len(self.current_zone) > 0:
                cv2.line(frame, self.current_zone[-1], self.temp_point, (0, 255, 0), 2)
            
            if len(self.current_zone) > 2 and self.temp_point:
                cv2.line(frame, self.temp_point, self.current_zone[0], (0, 255, 0), 1)
        
        return frame
    
    def process_frame(self, frame):
        """Process frame with YOLO and track objects"""
        self.frame_count += 1
        
        if self.frame_count % self.process_every_n_frames != 0 and self.last_processed_frame is not None:
            return self.last_processed_frame
        
        results = self.model.track(
            frame, 
            persist=True,
            conf=self.conf_threshold,
            iou=self.iou_threshold,
            classes=[0]
        )
        
        # Reset zone counts
        for i in range(len(self.zones)):
            self.zone_counts[i] = 0
        
        if results[0].boxes is not None and results[0].boxes.id is not None:
            boxes = results[0].boxes.xyxy.cpu().numpy()
            track_ids = results[0].boxes.id.cpu().numpy().astype(int)
            confidences = results[0].boxes.conf.cpu().numpy()
            
            for box, track_id, conf in zip(boxes, track_ids, confidences):
                x1, y1, x2, y2 = box
                center = self.get_box_center(box)
                
                self.track_history[track_id].append(center)
                self.update_heatmap(center, frame.shape)
                
                if track_id not in self.object_entry_times:
                    self.object_entry_times[track_id] = {}
                
                current_zone = None
                for zone_idx, zone in enumerate(self.zones):
                    if self.point_in_polygon(center, zone):
                        current_zone = zone_idx
                        self.zone_counts[zone_idx] += 1
                        self.check_alerts(zone_idx, track_id)
                        break
                
                previous_zone = self.object_zone_status.get(track_id, None)
                
                if current_zone != previous_zone:
                    if previous_zone is not None:
                        self.zone_total_exits[previous_zone] += 1
                        
                        if previous_zone in self.object_entry_times[track_id]:
                            entry_time = self.object_entry_times[track_id][previous_zone]
                            dwell_time = (datetime.now() - entry_time).total_seconds()
                            self.object_dwell_times[previous_zone].append(dwell_time)
                            
                            self.log_event(track_id, self.zone_names[previous_zone], 
                                         'exit', dwell_time)
                            
                            del self.object_entry_times[track_id][previous_zone]
                    
                    if current_zone is not None:
                        self.zone_total_entries[current_zone] += 1
                        self.object_entry_times[track_id][current_zone] = datetime.now()
                        
                        self.log_event(track_id, self.zone_names[current_zone], 'entry')
                        
                        # Trigger entry alert if enabled
                        if self.zone_alert_enabled[current_zone]:
                            message = f"Person {track_id} entered {self.zone_names[current_zone]}"
                            self.create_alert(self.zone_names[current_zone], 'entry', 
                                            'medium', message, track_id)
                
                self.object_zone_status[track_id] = current_zone
                
                speed = self.calculate_speed(track_id)
                color = (0, 0, 255) if (current_zone is not None and 
                                       self.zone_alert_enabled[current_zone]) else (255, 0, 0)
                
                cv2.rectangle(frame, (int(x1), int(y1)), (int(x2), int(y2)), color, 2)
                
                label = f"ID:{track_id} ({conf:.2f})"
                if current_zone is not None:
                    label += f" | {self.zone_names[current_zone]}"
                
                cv2.putText(frame, label, (int(x1), int(y1) - 10),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)
                
                if len(self.track_history[track_id]) > 1:
                    points = np.array(self.track_history[track_id], dtype=np.int32)
                    cv2.polylines(frame, [points], False, color, 2)
        
        self.last_processed_frame = frame.copy()
        return frame
    
    def run_camera(self):
        """Run the tracker on camera feed"""
        cap = cv2.VideoCapture(self.camera_id)
        
        if not cap.isOpened():
            print(f"Error: Cannot open camera {self.camera_id}")
            return
        
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
        
        self.fps = cap.get(cv2.CAP_PROP_FPS) or 30
        
        window_name = f'Zone Tracker - {self.camera_name}'
        cv2.namedWindow(window_name)
        cv2.setMouseCallback(window_name, self.mouse_callback)
        
        print("\n=== CONTROLS ===")
        print("'d' - Start/Stop drawing zone")
        print("'c' - Complete current zone")
        print("'r' - Reset current zone")
        print("'s' - Save zones to file")
        print("'l' - Load zones from file")
        print("'h' - Toggle heatmap")
        print("'a' - Toggle alert sound")
        print("'q' - Quit")
        print("================\n")
        
        stats_save_interval = 60
        frame_counter = 0
        
        while True:
            ret, frame = cap.read()
            if not ret:
                print("Error: Cannot read frame")
                break
            
            if len(self.zones) > 0:
                frame = self.draw_zones(frame)
            
            if self.drawing_mode:
                frame = self.draw_current_zone(frame)
            
            if not self.drawing_mode and len(self.zones) > 0:
                frame = self.process_frame(frame)
                frame = self.draw_alerts(frame)
            
            if self.show_heatmap:
                frame = self.draw_heatmap(frame)
            
            # Draw camera info and status
            status = "DRAWING MODE" if self.drawing_mode else "TRACKING MODE"
            cv2.putText(frame, f"{self.camera_name} - {status}", (10, 30), 
                       cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 255), 2)
            
            if self.drawing_mode:
                cv2.putText(frame, "Click to add points | 'c' complete | 'r' reset", 
                          (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)
            
            cv2.putText(frame, f"FPS: {self.fps:.1f} | Alerts: {len(self.active_alerts)}", 
                       (frame.shape[1] - 250, 30),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)
            
            cv2.imshow(window_name, frame)
            
            frame_counter += 1
            if frame_counter % stats_save_interval == 0:
                self.save_zone_stats()
            
            key = cv2.waitKey(1) & 0xFF
            
            if key == ord('q'):
                break
            elif key == ord('d'):
                self.drawing_mode = not self.drawing_mode
                if self.drawing_mode:
                    print("Drawing mode ON")
                else:
                    print("Drawing mode OFF")
                    self.current_zone = []
            elif key == ord('c'):
                if len(self.current_zone) >= 3:
                    zone_name = input("Enter zone name: ") or f"Zone {len(self.zones) + 1}"
                    capacity = input("Enter max capacity (0 for unlimited): ")
                    capacity = int(capacity) if capacity.isdigit() else 0
                    alert_enabled = input("Enable alerts for this zone? (y/n): ").lower() == 'y'
                    self.add_zone(self.current_zone.copy(), name=zone_name, 
                                capacity=capacity, alert_enabled=alert_enabled)
                    self.current_zone = []
                    self.drawing_mode = False
                else:
                    print("Need at least 3 points")
            elif key == ord('r'):
                self.current_zone = []
                print("Current zone reset")
            elif key == ord('s'):
                self.save_zones(f'{self.camera_name}_zones.json')
            elif key == ord('l'):
                self.load_zones(f'{self.camera_name}_zones.json')
            elif key == ord('h'):
                self.show_heatmap = not self.show_heatmap
                print(f"Heatmap: {'ON' if self.show_heatmap else 'OFF'}")
            elif key == ord('a'):
                self.alert_sound_enabled = not self.alert_sound_enabled
                print(f"Alert Sound: {'ON' if self.alert_sound_enabled else 'OFF'}")
        
        self.save_zone_stats()
        cap.release()
        cv2.destroyAllWindows()
        
        print("\n=== FINAL STATISTICS ===")
        for i, name in enumerate(self.zone_names):
            print(f"{name}:")
            print(f"  Entries: {self.zone_total_entries[i]} | Exits: {self.zone_total_exits[i]}")
            if self.object_dwell_times[i]:
                print(f"  Avg Dwell: {np.mean(self.object_dwell_times[i]):.1f}s")


def run_multi_camera(camera_configs, db_config):
    """Run multiple cameras simultaneously"""
    trackers = []
    threads = []
    
    for config in camera_configs:
        tracker = MultiCameraZoneTracker(
            model_path=config.get('model_path', 'person_best.pt'),
            db_config=db_config,
            camera_id=config['camera_id'],
            camera_name=config.get('camera_name', f"Camera_{config['camera_id']}")
        )
        
        # Load zones if config file exists
        zone_file = config.get('zone_file')
        if zone_file and os.path.exists(zone_file):
            tracker.load_zones(zone_file)
        
        trackers.append(tracker)
        
        # Start each camera in a separate thread
        thread = threading.Thread(target=tracker.run_camera, daemon=False)
        threads.append(thread)
        thread.start()
    
    # Wait for all threads
    for thread in threads:
        thread.join()


if __name__ == "__main__":
    # Database configuration
    db_config = {
        'host': 'localhost',
        'user': 'root',
        'password': 'your_password',
        'database': 'zone_tracking'
    }
    
    # Single camera mode
    tracker = MultiCameraZoneTracker(
        model_path='person_best.pt',
        db_config=db_config,
        camera_id=0,
        camera_name='Main Camera'
    )
    tracker.run_camera()
    
    # Multi-camera mode (uncomment to use)
    """
    camera_configs = [
        {
            'camera_id': 0,
            'camera_name': 'Entrance Camera',
            'zone_file': 'entrance_zones.json',
            'model_path': 'person_best.pt'
        },
        {
            'camera_id': 1,
            'camera_name': 'Exit Camera',
            'zone_file': 'exit_zones.json',
            'model_path': 'person_best.pt'
        },
        {
            'camera_id': 2,
            'camera_name': 'Parking Camera',
            'zone_file': 'parking_zones.json',
            'model_path': 'person_best.pt'
        }
    ]
    
    run_multi_camera(camera_configs, db_config)
    """