#Greetings JI! Geo Fencing System

A comprehensive real-time zone tracking system with multi-camera support, MySQL database integration

## 🌟 Features

- ✅ **Multi-Camera Support** - Track across multiple camera feeds simultaneously
- ✅ **Real-Time Alerts** - Instant notifications when people enter zones
- ✅ **Red Zone Highlighting** - Zones turn RED when occupied
- ✅ **MySQL Database** - Persistent data storage and analytics
- ✅ **Person Tracking** - YOLO-based person detection and tracking
- ✅ **Zone Analytics** - Entry/exit counts, dwell time, capacity monitoring
- ✅ **Heat Maps** - Visual representation of high-traffic areas
- ✅ **Alert Management** - Configurable alerts for capacity, loitering, and entry
- ✅ **Cross-Camera Tracking** - Track individuals across multiple cameras

### System Requirements
- Python 3.8+
- CUDA-compatible GPU (recommended for real-time processing)
- MySQL Server 8.0+
- Webcam(s) or IP camera(s)

### Python Dependencies

```bash
pip install ultralytics opencv-python numpy mysql-connector-python
```

### Full Requirements

 `requirements:

```
ultralytics>=8.0.0
opencv-python>=4.8.0
numpy>=1.24.0
mysql-connector-python>=8.0.0
torch>=2.0.0
torchvision>=0.15.0
```

Install all dependencies:

```bash
pip install -r requirements.txt
```

## 🗄️ Database Setup

### 1. Install MySQL Server

**Ubuntu/Debian:**
```bash
sudo apt update
sudo apt install mysql-server
sudo systemctl start mysql
sudo systemctl enable mysql
```

**Windows:**
Download and install from [MySQL Official Site](https://dev.mysql.com/downloads/installer/)

### 2. Create Database and User

```bash
# Login to MySQL
sudo mysql -u root -p

# In MySQL prompt
CREATE DATABASE zone_tracking;
CREATE USER 'tracker_user'@'localhost' IDENTIFIED BY 'SecurePassword123!';
GRANT ALL PRIVILEGES ON zone_tracking.* TO 'tracker_user'@'localhost';
FLUSH PRIVILEGES;
EXIT;
```

### 3. Configure Database Connection

Edit the `db_config` in the Python script:

```python
db_config = {
    'host': 'localhost',
    'user': 'tracker_user',
    'password': 'SecurePassword123!',
    'database': 'zone_tracking'
}
```

### 4. Database Schema

The system automatically creates these tables:
- `cameras` - Camera registration and status
- `zones` - Zone definitions and configurations
- `events` - All tracking events (entry/exit)
- `alerts` - Alert history
- `zone_stats` - Periodic statistics snapshots
- `cross_camera_tracks` - Multi-camera person tracking

## 🎯 Model Setup

### Option 1: Use Pre-trained YOLO Model


use our current person_best.pt


### For updation: TrainModel

```python
from ultralytics import YOLO

# Load a model
model = YOLO('yolov8n.pt')

# Train the model on your dataset
results = model.train(
    data='path/to/your/dataset.yaml',
    epochs=100,
    imgsz=640,
    device=0  # GPU
)



## 🚀 Quick Start

### Single Camera Setup

```python
from multi_camera_tracker import MultiCameraZoneTracker

# Configure database
db_config = {
    'host': 'localhost',
    'user': 'tracker_user',
    'password': 'SecurePassword123!',
    'database': 'zone_tracking'
}

# Initialize tracker
tracker = MultiCameraZoneTracker(
    model_path='person_best.pt',
    db_config=db_config,
    camera_id=0,
    camera_name='Main Entrance'
)

# Run the tracker
tracker.run_camera()
```

### Multi-Camera Setup

```python
from multi_camera_tracker import run_multi_camera

# Database configuration
db_config = {
    'host': 'localhost',
    'user': 'tracker_user',
    'password': 'SecurePassword123!',
    'database': 'zone_tracking'
}

# Configure multiple cameras
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
        'camera_name': 'Parking Lot',
        'zone_file': 'parking_zones.json',
        'model_path': 'person_best.pt'
    }
]

# Run all cameras
run_multi_camera(camera_configs, db_config)
```

## 🎨 Zone Configuration

### Creating Zones Interactively

1. **Start the application**
2. **Press 'd'** to enter drawing mode
3. **Click on the video** to add zone boundary points (minimum 3 points)
4. **Press 'c'** to complete the zone
5. **Enter zone details:**
   - Zone name
   - Maximum capacity (0 for unlimited)
   - Enable/disable alerts (y/n)

### Zone Configuration File Format

```json
{
  "camera_id": 0,
  "camera_name": "Main Entrance",
  "zones": [
    {
      "points": [[100, 100], [500, 100], [500, 400], [100, 400]],
      "name": "Restricted Area",
      "color": [0, 0, 255],
      "capacity": 2,
      "direction": null,
      "alert_enabled": true
    },
    {
      "points": [[600, 100], [900, 100], [900, 400], [600, 400]],
      "name": "Waiting Area",
      "color": [0, 255, 0],
      "capacity": 10,
      "direction": null,
      "alert_enabled": false
    }
  ]
}
```

Save zones: Press **'s'** during runtime
Load zones: Press **'l'** during runtime

## 🎮 Keyboard Controls 

| Key | Action |
|-----|--------|
| `d` | Toggle drawing mode for creating zones |
| `c` | Complete current zone (drawing mode) |
| `r` | Reset current zone (drawing mode) |
| `s` | Save zones to JSON file |
| `l` | Load zones from JSON file |
| `h` | Toggle heatmap overlay |
| `a` | Toggle alert sound |
| `q` | Quit application |

## 🚨 Alert System

### Alert Types

1. **Entry Alert** (Medium Severity)
   - Triggered when person enters a zone with alerts enabled
   - Zone turns RED
   - Pop-up notification displayed

2. **Capacity Alert** (High Severity)
   - Triggered when zone exceeds maximum capacity
   - Red border thickness increases
   - Critical notification

3. **Loitering Alert** (Medium Severity)
   - Triggered when person stays in zone beyond threshold
   - Default: 10 seconds (configurable)

### Alert Configuration

```python
tracker = MultiCameraZoneTracker(
    model_path='person_best.pt',
    db_config=db_config,
    camera_id=0,
    camera_name='Camera 1'
)

# Configure alert settings
tracker.dwell_time_threshold = 15.0  # Loitering threshold in seconds
tracker.alert_display_time = 5  # Alert display duration
tracker.alert_sound_enabled = True  # Enable/disable sound
```

## 📊 Database Queries

### Get Real-Time Zone Status

```sql
SELECT 
    z.zone_name,
    zs.current_count,
    z.capacity,
    zs.avg_dwell_time
FROM zone_stats zs
JOIN zones z ON zs.zone_name = z.zone_name
WHERE zs.timestamp = (
    SELECT MAX(timestamp) 
    FROM zone_stats 
    WHERE camera_id = 0
);
```

### Get All Alerts Today

```sql
SELECT 
    timestamp,
    camera_name,
    zone_name,
    alert_type,
    severity,
    message
FROM alerts a
JOIN cameras c ON a.camera_id = c.camera_id
WHERE DATE(timestamp) = CURDATE()
AND acknowledged = FALSE
ORDER BY timestamp DESC;
```

### Get Entry/Exit Events

```sql
SELECT 
    timestamp,
    track_id,
    zone_name,
    event_type,
    dwell_time
FROM events
WHERE camera_id = 0
AND DATE(timestamp) = CURDATE()
ORDER BY timestamp DESC
LIMIT 100;
```

### Zone Analytics Report

```sql
SELECT 
    zone_name,
    SUM(total_entries) as total_entries,
    SUM(total_exits) as total_exits,
    AVG(avg_dwell_time) as avg_dwell_time,
    MAX(current_count) as peak_occupancy
FROM zone_stats
WHERE camera_id = 0
AND DATE(timestamp) = CURDATE()
GROUP BY zone_name;
```

## 🔧 Configuration Options

### Tracker Parameters

```python
tracker = MultiCameraZoneTracker(
    model_path='person_best.pt',  # Path to YOLO model
    db_config=db_config,           # Database configuration
    camera_id=0,                   # Camera ID/index
    camera_name='Camera 1'         # Human-readable name
)

# Detection settings
tracker.conf_threshold = 0.5       # Confidence threshold (0-1)
tracker.iou_threshold = 0.5        # IOU threshold for tracking
tracker.process_every_n_frames = 2 # Process every N frames (performance)

# Alert settings
tracker.dwell_time_threshold = 10.0  # Loitering time in seconds
tracker.alert_display_time = 5       # Alert display duration
tracker.alert_sound_enabled = True   # Enable alert sounds
```

## 🔌 IP Camera Integration

### RTSP Streams

```python
# Replace camera_id with RTSP URL
tracker = MultiCameraZoneTracker(
    model_path='person_best.pt',
    db_config=db_config,
    camera_id='rtsp://username:password@192.168.1.100:554/stream1',
    camera_name='IP Camera 1'
)
```

### HTTP/MJPEG Streams

```python
tracker = MultiCameraZoneTracker(
    model_path='person_best.pt',
    db_config=db_config,
    camera_id='http://192.168.1.100:8080/video',
    camera_name='WiFi Camera'
)
```

## 📈 Performance Optimization

### GPU Acceleration

```python
# Check CUDA availability
import torch
print(f"CUDA Available: {torch.cuda.is_available()}")
print(f"CUDA Device: {torch.cuda.get_device_name(0)}")

# The system automatically uses GPU if available
```

### Frame Processing

```python
# Reduce processing load
tracker.process_every_n_frames = 3  # Process every 3rd frame

# Lower resolution for faster processing
cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
```

## 🐛 Troubleshooting

### Database Connection Issues

```bash
# Test MySQL connection
mysql -h localhost -u tracker_user -p

# Check if database exists
SHOW DATABASES;

# Verify user privileges
SHOW GRANTS FOR 'tracker_user'@'localhost';
```

### Camera Not Detected

```python
# List available cameras
import cv2

for i in range(10):
    cap = cv2.VideoCapture(i)
    if cap.isOpened():
        print(f"Camera {i} available")
        cap.release()
```

### Low FPS

1. Reduce resolution
2. Increase `process_every_n_frames`
3. Use GPU acceleration
4. Close other applications
5. Use lighter YOLO model (yolov8n instead of yolov8x)

### MySQL Connection Timeout

```python
db_config = {
    'host': 'localhost',
    'user': 'tracker_user',
    'password': 'SecurePassword123!',
    'database': 'zone_tracking',
    'connect_timeout': 10,
    'pool_size': 5,
    'pool_reset_session': True
}
```

## 📱 Integration Examples

### REST API Integration

```python
from flask import Flask, jsonify
import mysql.connector

app = Flask(__name__)

@app.route('/api/zones/status')
def get_zone_status():
    conn = mysql.connector.connect(**db_config)
    cursor = conn.cursor(dictionary=True)
    
    cursor.execute("""
        SELECT zone_name, current_count, capacity, avg_dwell_time
        FROM zone_stats
        WHERE timestamp > NOW() - INTERVAL 1 MINUTE
    """)
    
    zones = cursor.fetchall()
    conn.close()
    
    return jsonify(zones)

@app.route('/api/alerts/active')
def get_active_alerts():
    conn = mysql.connector.connect(**db_config)
    cursor = conn.cursor(dictionary=True)
    
    cursor.execute("""
        SELECT * FROM alerts
        WHERE acknowledged = FALSE
        ORDER BY timestamp DESC
        LIMIT 10
    """)
    
    alerts = cursor.fetchall()
    conn.close()
    
    return jsonify(alerts)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
```

### WebSocket Real-Time Updates

```python
import asyncio
import websockets
import json

async def send_alerts(websocket, path):
    while True:
        # Query database for new alerts
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor(dictionary=True)
        
        cursor.execute("""
            SELECT * FROM alerts
            WHERE timestamp > NOW() - INTERVAL 5 SECOND
            AND acknowledged = FALSE
        """)
        
        alerts = cursor.fetchall()
        conn.close()
        
        if alerts:
            await websocket.send(json.dumps(alerts))
        
        await asyncio.sleep(1)

start_server = websockets.serve(send_alerts, "localhost", 8765)
asyncio.get_event_loop().run_until_complete(start_server)
asyncio.get_event_loop().run_forever()
```

## 📊 Analytics Dashboard

### Daily Summary Report

```sql
-- Save as daily_report.sql
SELECT 
    c.camera_name,
    z.zone_name,
    COUNT(DISTINCT e.track_id) as unique_visitors,
    SUM(CASE WHEN e.event_type = 'entry' THEN 1 ELSE 0 END) as total_entries,
    AVG(e.dwell_time) as avg_dwell_time,
    MAX(zs.current_count) as peak_occupancy,
    COUNT(a.alert_id) as total_alerts
FROM cameras c
LEFT JOIN zones z ON c.camera_id = z.camera_id
LEFT JOIN events e ON z.zone_name = e.zone_name AND DATE(e.timestamp) = CURDATE()
LEFT JOIN zone_stats zs ON z.zone_name = zs.zone_name
LEFT JOIN alerts a ON z.zone_name = a.zone_name AND DATE(a.timestamp) = CURDATE()
WHERE c.status = 'active'
GROUP BY c.camera_name, z.zone_name
ORDER BY c.camera_name, total_entries DESC;
```


