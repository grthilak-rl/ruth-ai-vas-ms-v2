# app.py - Enhanced Flask Backend with Geofencing & Live Video
from flask import Flask, request, jsonify, Response
from flask_cors import CORS
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, Boolean, ForeignKey, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from datetime import datetime, timedelta
import supervision as sv
from ultralytics import YOLO
import cv2
import numpy as np
from collections import defaultdict, deque
import threading
import queue
import json
import os
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
CORS(app)

# MySQL Configuration
MYSQL_USER = os.getenv('MYSQL_USER', 'root')
MYSQL_PASSWORD = os.getenv('MYSQL_PASSWORD', 'password')
MYSQL_HOST = os.getenv('MYSQL_HOST', 'localhost')
MYSQL_PORT = os.getenv('MYSQL_PORT', '3306')
MYSQL_DATABASE = os.getenv('MYSQL_DATABASE', 'tracking_db')

DATABASE_URL = f'mysql+pymysql://{MYSQL_USER}:{MYSQL_PASSWORD}@{MYSQL_HOST}:{MYSQL_PORT}/{MYSQL_DATABASE}'

print(f"Connecting to MySQL: {MYSQL_DATABASE}")

try:
    engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_recycle=3600)
    Base = declarative_base()
    SessionLocal = sessionmaker(bind=engine)
    print("✓ MySQL connected")
except Exception as e:
    print(f"✗ MySQL failed: {e}")

# Database Models
class Camera(Base):
    __tablename__ = 'cameras'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    source = Column(String(500), nullable=False)
    status = Column(String(50), default='idle')
    active = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    detections = relationship('Detection', back_populates='camera', cascade='all, delete-orphan')
    zones = relationship('Zone', back_populates='camera', cascade='all, delete-orphan')
    events = relationship('Event', back_populates='camera', cascade='all, delete-orphan')

class Detection(Base):
    __tablename__ = 'detections'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    camera_id = Column(Integer, ForeignKey('cameras.id', ondelete='CASCADE'))
    global_id = Column(Integer, nullable=False)
    local_id = Column(Integer, nullable=False)
    object_class = Column(String(50), nullable=False)
    confidence = Column(Float, nullable=False)
    bbox_x1 = Column(Float)
    bbox_y1 = Column(Float)
    bbox_x2 = Column(Float)
    bbox_y2 = Column(Float)
    timestamp = Column(DateTime, default=datetime.utcnow)
    
    camera = relationship('Camera', back_populates='detections')

class Track(Base):
    __tablename__ = 'tracks'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    global_id = Column(Integer, unique=True, nullable=False)
    first_seen = Column(DateTime, default=datetime.utcnow)
    last_seen = Column(DateTime, default=datetime.utcnow)
    total_detections = Column(Integer, default=0)
    cameras_seen = Column(Text)

class Zone(Base):
    __tablename__ = 'zones'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    camera_id = Column(Integer, ForeignKey('cameras.id', ondelete='CASCADE'))
    name = Column(String(100), nullable=False)
    points = Column(Text, nullable=False)
    color = Column(String(50))
    capacity = Column(Integer, default=0)
    alert_enabled = Column(Boolean, default=True)
    current_count = Column(Integer, default=0)
    total_entries = Column(Integer, default=0)
    total_exits = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    camera = relationship('Camera', back_populates='zones')
    events = relationship('Event', back_populates='zone', cascade='all, delete-orphan')

class Event(Base):
    __tablename__ = 'events'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    camera_id = Column(Integer, ForeignKey('cameras.id', ondelete='CASCADE'))
    zone_id = Column(Integer, ForeignKey('zones.id', ondelete='CASCADE'), nullable=True)
    track_id = Column(Integer, nullable=False)
    global_id = Column(Integer, nullable=False)
    event_type = Column(String(50), nullable=False)
    dwell_time = Column(Float, nullable=True)
    timestamp = Column(DateTime, default=datetime.utcnow)
    metadata = Column(Text)
    
    camera = relationship('Camera', back_populates='events')
    zone = relationship('Zone', back_populates='events')

class Alert(Base):
    __tablename__ = 'alerts'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    camera_id = Column(Integer, ForeignKey('cameras.id', ondelete='CASCADE'))
    zone_id = Column(Integer, ForeignKey('zones.id', ondelete='SET NULL'), nullable=True)
    alert_type = Column(String(50), nullable=False)
    severity = Column(String(20), default='medium')
    message = Column(Text, nullable=False)
    track_id = Column(Integer, nullable=True)
    acknowledged = Column(Boolean, default=False)
    timestamp = Column(DateTime, default=datetime.utcnow)

class PersonVerification(Base):
    __tablename__ = 'person_verification'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    global_id = Column(Integer, nullable=False)
    zone_id = Column(Integer, ForeignKey('zones.id', ondelete='CASCADE'))
    entry_time = Column(DateTime, nullable=False)
    exit_time = Column(DateTime, nullable=True)
    dwell_time = Column(Float, nullable=True)
    status = Column(String(20), default='inside')
    last_seen = Column(DateTime, nullable=False)

# Create tables
try:
    Base.metadata.create_all(engine)
    print("✓ Tables created/verified")
except Exception as e:
    print(f"✗ Table creation failed: {e}")

# Enhanced Tracker with Geofencing
class EnhancedTracker:
    def __init__(self, camera_id, source, model_path="yolov8n.pt"):
        self.camera_id = camera_id
        self.source = source
        self.model = YOLO(model_path)
        
        self.global_id_map = defaultdict(dict)
        self.next_global_id = 0
        self.object_features = {}
        self.track_history = defaultdict(lambda: deque(maxlen=50))
        
        self.zones = []
        self.zone_counts = defaultdict(int)
        self.object_zone_status = {}
        self.object_entry_times = {}
        
        self.cap = None
        self.is_running = False
        self.current_frame = None
        self.frame_lock = threading.Lock()
        
        self.fps = 30
        self.process_every_n_frames = 2
        self.frame_count = 0
        
        self.tracker = sv.ByteTrack(
            track_activation_threshold=0.25,
            lost_track_buffer=30,
            minimum_matching_threshold=0.8,
            frame_rate=30
        )
    
    def load_zones(self):
        """Load zones from database"""
        session = SessionLocal()
        zones = session.query(Zone).filter_by(camera_id=self.camera_id).all()
        
        self.zones = []
        for zone in zones:
            zone_data = {
                'id': zone.id,
                'name': zone.name,
                'points': json.loads(zone.points),
                'color': tuple(map(int, zone.color.split(','))) if zone.color else (0, 255, 0),
                'capacity': zone.capacity,
                'alert_enabled': zone.alert_enabled,
                'current_count': 0
            }
            self.zones.append(zone_data)
        
        session.close()
        print(f"Loaded {len(self.zones)} zones for camera {self.camera_id}")
    
    def point_in_polygon(self, point, polygon):
        """Check if point inside polygon"""
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
        """Get center of bounding box"""
        x1, y1, x2, y2 = box
        return (int((x1 + x2) / 2), int((y1 + y2) / 2))
    
    def extract_features(self, frame, bbox):
        """Extract appearance features"""
        x1, y1, x2, y2 = bbox.astype(int)
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(frame.shape[1], x2), min(frame.shape[0], y2)
        
        crop = frame[y1:y2, x1:x2]
        if crop.size == 0:
            return np.zeros(128)
        
        crop_resized = cv2.resize(crop, (64, 128))
        hist = cv2.calcHist([crop_resized], [0, 1, 2], None, [8, 8, 8], 
                           [0, 256, 0, 256, 0, 256])
        hist = cv2.normalize(hist, hist).flatten()
        return hist
    
    def compute_similarity(self, feat1, feat2):
        """Compute cosine similarity"""
        if np.linalg.norm(feat1) == 0 or np.linalg.norm(feat2) == 0:
            return 0.0
        return np.dot(feat1, feat2) / (np.linalg.norm(feat1) * np.linalg.norm(feat2))
    
    def match_global_id(self, local_id, features, threshold=0.7):
        """Match to global ID"""
        if local_id in self.global_id_map[self.camera_id]:
            return self.global_id_map[self.camera_id][local_id]
        
        best_id = None
        best_sim = 0.0
        
        for gid, stored in self.object_features.items():
            sim = self.compute_similarity(features, stored)
            if sim > best_sim and sim > threshold:
                best_sim = sim
                best_id = gid
        
        if best_id is not None:
            global_id = best_id
            self.object_features[global_id] = 0.7 * self.object_features[global_id] + 0.3 * features
        else:
            global_id = self.next_global_id
            self.next_global_id += 1
            self.object_features[global_id] = features
            self.save_track(global_id)
        
        self.global_id_map[self.camera_id][local_id] = global_id
        return global_id
    
    def save_track(self, global_id):
        """Save new track"""
        try:
            session = SessionLocal()
            track = Track(
                global_id=global_id,
                first_seen=datetime.utcnow(),
                last_seen=datetime.utcnow(),
                total_detections=0,
                cameras_seen=json.dumps([self.camera_id])
            )
            session.add(track)
            session.commit()
            session.close()
        except Exception as e:
            print(f"Error saving track: {e}")
    
    def log_event(self, zone_id, track_id, global_id, event_type, dwell_time=None):
        """Log event to database"""
        try:
            session = SessionLocal()
            event = Event(
                camera_id=self.camera_id,
                zone_id=zone_id,
                track_id=track_id,
                global_id=global_id,
                event_type=event_type,
                dwell_time=dwell_time,
                timestamp=datetime.utcnow()
            )
            session.add(event)
            
            zone = session.query(Zone).filter_by(id=zone_id).first()
            if zone:
                if event_type == 'entry':
                    zone.total_entries += 1
                    zone.current_count += 1
                elif event_type == 'exit':
                    zone.total_exits += 1
                    zone.current_count = max(0, zone.current_count - 1)
            
            session.commit()
            session.close()
        except Exception as e:
            print(f"Error logging event: {e}")
    
    def create_alert(self, zone_id, alert_type, severity, message, track_id=None):
        """Create alert"""
        try:
            session = SessionLocal()
            alert = Alert(
                camera_id=self.camera_id,
                zone_id=zone_id,
                alert_type=alert_type,
                severity=severity,
                message=message,
                track_id=track_id,
                timestamp=datetime.utcnow()
            )
            session.add(alert)
            session.commit()
            session.close()
            print(f"🚨 ALERT: {message}")
        except Exception as e:
            print(f"Error creating alert: {e}")
    
    def update_verification(self, global_id, zone_id, event_type):
        """Track person entry/exit"""
        try:
            session = SessionLocal()
            
            if event_type == 'entry':
                verification = PersonVerification(
                    global_id=global_id,
                    zone_id=zone_id,
                    entry_time=datetime.utcnow(),
                    status='inside',
                    last_seen=datetime.utcnow()
                )
                session.add(verification)
            elif event_type == 'exit':
                verification = session.query(PersonVerification).filter_by(
                    global_id=global_id,
                    zone_id=zone_id,
                    status='inside'
                ).first()
                
                if verification:
                    verification.exit_time = datetime.utcnow()
                    verification.status = 'exited'
                    verification.dwell_time = (verification.exit_time - verification.entry_time).total_seconds()
                else:
                    zone = session.query(Zone).filter_by(id=zone_id).first()
                    if zone:
                        self.create_alert(zone_id, 'mismatch', 'high', 
                                        f"Person {global_id} exited {zone.name} without entry!")
            
            session.commit()
            session.close()
        except Exception as e:
            print(f"Error updating verification: {e}")
    
    def check_missing(self):
        """Check for people who haven't exited"""
        try:
            session = SessionLocal()
            threshold = datetime.utcnow() - timedelta(minutes=30)
            
            missing = session.query(PersonVerification).filter(
                PersonVerification.status == 'inside',
                PersonVerification.last_seen < threshold
            ).all()
            
            for person in missing:
                person.status = 'missing'
                zone = session.query(Zone).filter_by(id=person.zone_id).first()
                if zone:
                    self.create_alert(person.zone_id, 'loitering', 'high',
                                    f"Person {person.global_id} in {zone.name} > 30 min!")
            
            session.commit()
            session.close()
        except Exception as e:
            print(f"Error checking missing: {e}")
    
    def draw_zones(self, frame):
        """Draw zones with counts"""
        overlay = frame.copy()
        
        for zone in self.zones:
            pts = np.array(zone['points'], np.int32)
            color = zone['color']
            
            if zone['current_count'] > 0 and zone['alert_enabled']:
                color = (0, 0, 255)
            
            if zone['capacity'] > 0 and zone['current_count'] > zone['capacity']:
                color = (0, 0, 139)
            
            cv2.fillPoly(overlay, [pts], color)
            cv2.polylines(frame, [pts], True, color, 3)
            
            centroid = np.mean(pts, axis=0).astype(int)
            text = f"{zone['name']}: {zone['current_count']}"
            if zone['capacity'] > 0:
                text += f"/{zone['capacity']}"
            
            cv2.putText(frame, text, tuple(centroid),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
        
        cv2.addWeighted(overlay, 0.3, frame, 0.7, 0, frame)
        return frame
    
    def process_frame(self, frame):
        """Process frame with tracking"""
        self.frame_count += 1
        
        if self.frame_count % self.process_every_n_frames != 0:
            return frame
        
        for zone in self.zones:
            zone['current_count'] = 0
        
        results = self.model(frame, verbose=False)[0]
        detections = sv.Detections.from_ultralytics(results)
        detections = detections.with_nms(threshold=0.5)
        detections = self.tracker.update_with_detections(detections)
        
        if len(detections) > 0:
            for i, (bbox, local_id, class_id, conf) in enumerate(
                zip(detections.xyxy, detections.tracker_id, 
                    detections.class_id, detections.confidence)
            ):
                center = self.get_box_center(bbox)
                features = self.extract_features(frame, bbox)
                global_id = self.match_global_id(local_id, features)
                
                self.track_history[local_id].append(center)
                
                current_zone = None
                for zone in self.zones:
                    if self.point_in_polygon(center, zone['points']):
                        current_zone = zone
                        zone['current_count'] += 1
                        break
                
                previous_zone = self.object_zone_status.get(local_id)
                
                if current_zone != previous_zone:
                    if previous_zone is not None:
                        entry_time = self.object_entry_times.get(local_id, {}).get(previous_zone['id'])
                        if entry_time:
                            dwell = (datetime.utcnow() - entry_time).total_seconds()
                            self.log_event(previous_zone['id'], local_id, global_id, 'exit', dwell)
                            self.update_verification(global_id, previous_zone['id'], 'exit')
                    
                    if current_zone is not None:
                        self.log_event(current_zone['id'], local_id, global_id, 'entry')
                        self.update_verification(global_id, current_zone['id'], 'entry')
                        
                        if local_id not in self.object_entry_times:
                            self.object_entry_times[local_id] = {}
                        self.object_entry_times[local_id][current_zone['id']] = datetime.utcnow()
                        
                        if current_zone['alert_enabled']:
                            self.create_alert(current_zone['id'], 'entry', 'medium',
                                            f"Person {global_id} entered {current_zone['name']}", local_id)
                
                self.object_zone_status[local_id] = current_zone
                
                self.save_detection(local_id, global_id, class_id, conf, bbox)
                
                x1, y1, x2, y2 = bbox.astype(int)
                color = (0, 0, 255) if (current_zone and current_zone['alert_enabled']) else (0, 255, 0)
                
                cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
                label = f"ID:{global_id}"
                if current_zone:
                    label += f" | {current_zone['name']}"
                
                cv2.putText(frame, label, (x1, y1 - 10),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)
                
                if len(self.track_history[local_id]) > 1:
                    points = np.array(self.track_history[local_id], dtype=np.int32)
                    cv2.polylines(frame, [points], False, color, 2)
        
        return frame
    
    def save_detection(self, local_id, global_id, class_id, conf, bbox):
        """Save detection"""
        try:
            session = SessionLocal()
            detection = Detection(
                camera_id=self.camera_id,
                global_id=global_id,
                local_id=local_id,
                object_class=self.model.names[class_id],
                confidence=float(conf),
                bbox_x1=float(bbox[0]),
                bbox_y1=float(bbox[1]),
                bbox_x2=float(bbox[2]),
                bbox_y2=float(bbox[3]),
                timestamp=datetime.utcnow()
            )
            session.add(detection)
            
            track = session.query(Track).filter_by(global_id=global_id).first()
            if track:
                track.last_seen = datetime.utcnow()
                track.total_detections += 1
            
            session.commit()
            session.close()
        except Exception as e:
            print(f"Error saving detection: {e}")
    
    def start(self):
        """Start camera"""
        self.cap = cv2.VideoCapture(self.source)
        if not self.cap.isOpened():
            print(f"✗ Failed to open camera {self.camera_id}")
            return False
        
        self.is_running = True
        self.load_zones()
        
        thread = threading.Thread(target=self._process_loop, daemon=True)
        thread.start()
        
        print(f"✓ Camera {self.camera_id} started")
        return True
    
    def _process_loop(self):
        """Main processing loop"""
        while self.is_running and self.cap.isOpened():
            ret, frame = self.cap.read()
            if not ret:
                break
            
            if len(self.zones) > 0:
                frame = self.draw_zones(frame)
            
            frame = self.process_frame(frame)
            
            with self.frame_lock:
                self.current_frame = frame.copy()
            
            if self.frame_count % 900 == 0:
                self.check_missing()
    
    def get_frame(self):
        """Get current frame as JPEG"""
        with self.frame_lock:
            if self.current_frame is not None:
                ret, buffer = cv2.imencode('.jpg', self.current_frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
                return buffer.tobytes()
        return None
    
    def stop(self):
        """Stop camera"""
        self.is_running = False
        if self.cap:
            self.cap.release()

# Global trackers
trackers = {}
tracker_lock = threading.Lock()

# API Routes
@app.route('/api/cameras', methods=['GET'])
def get_cameras():
    try:
        session = SessionLocal()
        cameras = session.query(Camera).all()
        session.close()
        
        return jsonify([{
            'id': cam.id,
            'name': cam.name,
            'source': cam.source,
            'status': cam.status,
            'active': cam.active
        } for cam in cameras])
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/cameras', methods=['POST'])
def add_camera():
    try:
        data = request.json
        session = SessionLocal()
        
        camera = Camera(
            name=data['name'],
            source=data['source'],
            active=data.get('active', False)
        )
        session.add(camera)
        session.commit()
        
        camera_id = camera.id
        session.close()
        
        return jsonify({'id': camera_id, 'message': 'Camera added'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/zones', methods=['GET'])
def get_zones():
    try:
        camera_id = request.args.get('camera_id', type=int)
        session = SessionLocal()
        
        query = session.query(Zone)
        if camera_id:
            query = query.filter_by(camera_id=camera_id)
        
        zones = query.all()
        session.close()
        
        return jsonify([{
            'id': z.id,
            'camera_id': z.camera_id,
            'name': z.name,
            'points': json.loads(z.points),
            'color': z.color,
            'capacity': z.capacity,
            'alert_enabled': z.alert_enabled,
            'current_count': z.current_count,
            'total_entries': z.total_entries,
            'total_exits': z.total_exits
        } for z in zones])
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/zones', methods=['POST'])
def add_zone():
    try:
        data = request.json
        session = SessionLocal()
        
        zone = Zone(
            camera_id=data['camera_id'],
            name=data['name'],
            points=json.dumps(data['points']),
            color=','.join(map(str, data.get('color', [0, 255, 0]))),
            capacity=data.get('capacity', 0),
            alert_enabled=data.get('alert_enabled', True)
        )
        session.add(zone)
        session.commit()
        
        zone_id = zone.id
        session.close()
        
        with tracker_lock:
            if data['camera_id'] in trackers:
                trackers[data['camera_id']].load_zones()
        
        return jsonify({'id': zone_id, 'message': 'Zone added'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/video_feed/<int:camera_id>')
def video_feed(camera_id):
    """Video streaming route"""
    def generate():
        with tracker_lock:
            tracker = trackers.get(camera_id)
        
        if not tracker:
            return
        
        while True:
            frame = tracker.get_frame()
            if frame is None:
                continue
            
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')
    
    return Response(generate(), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/api/tracking/start', methods=['POST'])
def start_tracking():
    try:
        data = request.json
        model_type = data.get('modelType', 'yolov8n')
        
        session = SessionLocal()
        cameras = session.query(Camera).filter_by(active=True).all()
        
        if not cameras:
            session.close()
            return jsonify({'error': 'No active cameras'}), 400
        
        with tracker_lock:
            for cam in cameras:
                if cam.id not in trackers:
                    tracker = EnhancedTracker(
                        camera_id=cam.id,
                        source=cam.source,
                        model_path=f"{model_type}.pt"
                    )
                    if tracker.start():
                        trackers[cam.id] = tracker
                        cam.status = 'running'
        
        session.commit()
        session.close()
        
        return jsonify({'message': f'Tracking started on {len(trackers)} cameras'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/tracking/stop', methods=['POST'])
def stop_tracking():
    try:
        with tracker_lock:
            for tracker in trackers.values():
                tracker.stop()
            trackers.clear()
        
        session = SessionLocal()
        cameras = session.query(Camera).all()
        for cam in cameras:
            cam.status = 'idle'
        session.commit()
        session.close()
        
        return jsonify({'message': 'Tracking stopped'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/alerts', methods=['GET'])
def get_alerts():
    try:
        limit = request.args.get('limit', 50, type=int)
        
        session = SessionLocal()
        alerts = session.query(Alert).order_by(Alert.timestamp.desc()).limit(limit).all()
        session.close()
        
        return jsonify([{
            'id': a.id,
            'camera_id': a.camera_id,
            'zone_id': a.zone_id,
            'alert_type': a.alert_type,
            'severity': a.severity,
            'message': a.message,
            'track_id': a.track_id,
            'acknowledged': a.acknowledged,
            'timestamp': a.timestamp.isoformat()
        } for a in alerts])
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/person_verification', methods=['GET'])
def get_person_verification():
    try:
        status = request.args.get('status', None)
        zone_id = request.args.get('zone_id', type=int)
        
        session = SessionLocal()
        query = session.query(PersonVerification)
        
        if status:
            query = query.filter_by(status=status)
        if zone_id:
            query = query.filter_by(zone_id=zone_id)
        
        verifications = query.order_by(PersonVerification.entry_time.desc()).limit(100).all()
        session.close()
        
        return jsonify([{
            'id': v.id,
            'global_id': v.global_id,
            'zone_id': v.zone_id,
            'entry_time': v.entry_time.isoformat(),
            'exit_time': v.exit_time.isoformat() if v.exit_time else None,
            'dwell_time': v.dwell_time,
            'status': v.status,
            'last_seen': v.last_seen.isoformat()
        } for v in verifications])
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/stats', methods=['GET'])
def get_stats():
    try:
        session = SessionLocal()
        
        total_detections = session.query(Detection).count()
        total_tracks = session.query(Track).count()
        active_cameras = session.query(Camera).filter_by(active=True).count()
        unacknowledged_alerts = session.query(Alert).filter_by(acknowledged=False).count()
        people_inside = session.query(PersonVerification).filter_by(status='inside').count()
        
        session.close()
        
        return jsonify({
            'total_detections': total_detections,
            'total_tracks': total_tracks,
            'active_cameras': active_cameras,
            'unacknowledged_alerts': unacknowledged_alerts,
            'people_inside_zones': people_inside
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/health', methods=['GET'])
def health_check():
    try:
        session = SessionLocal()
        session.execute('SELECT 1')
        session.close()
        
        return jsonify({
            'status': 'healthy',
            'database': 'connected',
            'active_trackers': len(trackers),
            'timestamp': datetime.utcnow().isoformat()
        })
    except Exception as e:
        return jsonify({
            'status': 'unhealthy',
            'error': str(e)
        }), 500

if __name__ == '__main__':
    print("\n" + "="*60)
    print("Enhanced Multi-Camera Tracking with Geofencing")
    print("="*60)
    print(f"Database: MySQL ({MYSQL_DATABASE})")
    print(f"Server: http://0.0.0.0:5000")
    print("="*60 + "\n")
    
    app.run(host='0.0.0.0', port=5000, debug=True, threaded=True)