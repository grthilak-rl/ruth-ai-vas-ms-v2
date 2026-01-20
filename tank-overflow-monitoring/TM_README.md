# 🛢️ Petroleum Tank Level Monitor - Simple Version

A simple computer vision system to monitor petroleum tank levels using just a camera. Shows real-time level percentage and volume, with automatic alerts when tank reaches 90%.

## ✨ Features

- 📹 **Camera-Only Detection** - No sensors needed, just a camera view
- 📊 **Real-Time Level Display** - Shows percentage and liters
- 🚨 **Automatic Alerts** - Popup warning at 90% (configurable)
- 🎯 **Simple Setup** - Just click 4 corners of your tank
- 💾 **MySQL Database** - Stores all readings and alerts
- 🎨 **Visual Indicators** - Color-coded levels (Green→Yellow→Orange→Red)

## 🚀 Quick Start

### 1. Install Dependencies

```bash
pip install opencv-python numpy mysql-connector-python
```

### 2. Setup MySQL

```bash
# Login to MySQL
mysql -u root -p

# Create database (optional - script auto-creates)
CREATE DATABASE tank_monitor;
```

### 3. Update Database Config

Edit in the script:
```python
self.db_config = {
    'host': 'localhost',
    'user': 'root',
    'password': 'YOUR_PASSWORD',  # ← Change this
    'database': 'tank_monitor'
}
```

### 4. Run the Monitor

```python
python simple_tank_monitor.py
```

## 📋 How to Use

### First Time Setup

1. **Run the script** - Camera window opens
2. **Press SPACE** - Enters setup mode
3. **Click 4 corners** of the tank in order:
   - Top-left corner
   - Top-right corner
   - Bottom-right corner
   - Bottom-left corner
4. **Done!** - Monitor starts automatically

The configuration is saved and will load next time.

### Controls

| Key | Action |
|-----|--------|
| `SPACE` | Start setup (define tank area) |
| `R` | Reset tank area |
| `S` | Save configuration |
| `Q` | Quit |

## 📊 Alert Levels

| Level | Color | Status | Action |
|-------|-------|--------|--------|
| 0-74% | 🟢 Green | Normal | - |
| 75-89% | 🟡 Yellow | High | Monitor |
| 90-94% | 🟠 Orange | **WARNING** | **Alert Popup** |
| 95-100% | 🔴 Red | **CRITICAL** | **Immediate Action** |

## 🎥 Camera Options

### Webcam
```python
monitor = SimpleTankMonitor(
    camera_source=0,  # 0 = default webcam
    tank_capacity_liters=1000
)
```

### IP Camera (RTSP)
```python
monitor = SimpleTankMonitor(
    camera_source='rtsp://admin:password@192.168.1.100:554/stream1',
    tank_capacity_liters=5000
)
```

### HTTP/MJPEG Camera
```python
monitor = SimpleTankMonitor(
    camera_source='http://192.168.1.100:8080/video',
    tank_capacity_liters=2000
)
```

### Multiple Cameras (Different Tanks)

```python
# Tank 1
import threading

def monitor_tank_1():
    monitor1 = SimpleTankMonitor(
        camera_source=0,
        tank_capacity_liters=1000
    )
    monitor1.run()

def monitor_tank_2():
    monitor2 = SimpleTankMonitor(
        camera_source='rtsp://192.168.1.101:554/stream',
        tank_capacity_liters=2000
    )
    monitor2.run()

# Run both
t1 = threading.Thread(target=monitor_tank_1)
t2 = threading.Thread(target=monitor_tank_2)
t1.start()
t2.start()
```

## 🔧 Configuration

### Change Alert Threshold

```python
monitor = SimpleTankMonitor(camera_source=0, tank_capacity_liters=1000)
monitor.alert_threshold = 85  # Alert at 85% instead of 90%
```

### Change Alert Cooldown

```python
monitor.alert_cooldown = 120  # 2 minutes between alerts (default: 60)
```

### Tank Capacity

```python
monitor = SimpleTankMonitor(
    camera_source=0,
    tank_capacity_liters=5000  # Set your tank capacity
)
```

## 📊 Database Queries

### Get Latest Reading
```sql
SELECT * FROM tank_readings 
ORDER BY timestamp DESC 
LIMIT 1;
```

### Get Average Level Today
```sql
SELECT AVG(level_percent) as avg_level 
FROM tank_readings 
WHERE DATE(timestamp) = CURDATE();
```

### Get All Alerts Today
```sql
SELECT * FROM tank_alerts 
WHERE DATE(timestamp) = CURDATE() 
ORDER BY timestamp DESC;
```

### Get Level History (Last 24 Hours)
```sql
SELECT 
    DATE_FORMAT(timestamp, '%H:%i') as time,
    level_percent,
    level_liters
FROM tank_readings 
WHERE timestamp >= NOW() - INTERVAL 24 HOUR
ORDER BY timestamp;
```

## 🎯 How Detection Works

The system uses **edge detection** to find the liquid surface:

1. **Captures** the tank area you defined
2. **Converts** to grayscale
3. **Detects edges** using Canny algorithm
4. **Finds horizontal lines** (liquid surface)
5. **Calculates percentage** from top of tank
6. **Smooths reading** over 30 frames for stability

### Best Results Tips

✅ **Good lighting** - Tank should be well-lit
✅ **Clear view** - Camera should see entire tank clearly
✅ **Stable camera** - Mount camera firmly (no shaking)
✅ **Transparent/translucent tank** - Can see liquid level
✅ **High contrast** - Dark liquid shows better

## 🐛 Troubleshooting

### Camera Not Opening
```python
# Test which camera IDs work
for i in range(10):
    cap = cv2.VideoCapture(i)
    if cap.isOpened():
        print(f"Camera {i} available")
        cap.release()
```

### Level Detection Not Working

1. **Check lighting** - Add more light to tank area
2. **Adjust camera angle** - Should see clear liquid line
3. **Redefine tank area** - Press SPACE and click corners again
4. **Check tank type** - Works best with transparent/translucent tanks

### Database Connection Error
```bash
# Check MySQL is running
sudo systemctl status mysql

# Test connection
mysql -u root -p -h localhost
```

### Alert Not Showing

- Check if level is actually ≥ 90%
- Wait for cooldown period (60 seconds default)
- Check terminal for error messages

## 📱 Integration Ideas

### REST API
```python
from flask import Flask, jsonify

app = Flask(__name__)

@app.route('/api/level')
def get_level():
    # Query database
    conn = mysql.connector.connect(**db_config)
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM tank_readings ORDER BY timestamp DESC LIMIT 1")
    reading = cursor.fetchone()
    conn.close()
    return jsonify(reading)

app.run(port=5000)
```

### SMS Alerts (using Twilio)
```python
from twilio.rest import Client

def send_sms_alert(level):
    client = Client('ACCOUNT_SID', 'AUTH_TOKEN')
    message = client.messages.create(
        body=f'Tank Alert: {level}% full!',
        from_='+1234567890',
        to='+0987654321'
    )
```

### Email Alerts
```python
import smtplib

def send_email_alert(level):
    smtp = smtplib.SMTP('smtp.gmail.com', 587)
    smtp.starttls()
    smtp.login('your@email.com', 'password')
    
    message = f'Subject: Tank Alert\n\nTank level: {level}%'
    smtp.sendmail('your@email.com', 'receiver@email.com', message)
    smtp.quit()
```

## 📊 Advanced Analytics

### Daily Report Query
```sql
SELECT 
    DATE(timestamp) as date,
    MIN(level_percent) as min_level,
    MAX(level_percent) as max_level,
    AVG(level_percent) as avg_level,
    COUNT(*) as readings_count
FROM tank_readings
GROUP BY DATE(timestamp)
ORDER BY date DESC
LIMIT 30;
```

### Consumption Rate
```sql
SELECT 
    timestamp,
    level_liters,
    level_liters - LAG(level_liters) OVER (ORDER BY timestamp) as consumption
FROM tank_readings
WHERE timestamp >= NOW() - INTERVAL 24 HOUR;
```
