#!/usr/bin/env python3
"""SiteEye v1-Lite — Camera-only client for Pi Zero 2W + IMX500

No OLED, no mic, no speaker. Just:
  - Camera snapshot → VPS proxy → GPT-4o vision → Telegram
  - On-chip IMX500 object detection (if models installed)
  - Timelapse mode
  - Remote trigger via proxy polling

Commands:
  c = camera snapshot → AI vision analysis → Telegram
  d = on-chip object detection (IMX500 YOLO)
  t = timelapse mode (capture every N seconds)
  i = device info (IP, uptime, temp, disk)
  q = quit
"""

import os
import subprocess
import requests
import time
import json
import sys
import signal
import threading
from datetime import datetime

# --- Config ---
PROXY_URL = os.environ.get("SITEEYE_PROXY", "https://molted.tail4a98c5.ts.net")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "8217278203")
CAPTURE_WIDTH = 640
CAPTURE_HEIGHT = 480

# COCO class names for detection
COCO_CLASSES = [
    "person", "bicycle", "car", "motorcycle", "airplane", "bus", "train", "truck",
    "boat", "traffic light", "fire hydrant", "stop sign", "parking meter", "bench",
    "bird", "cat", "dog", "horse", "sheep", "cow", "elephant", "bear", "zebra",
    "giraffe", "backpack", "umbrella", "handbag", "tie", "suitcase", "frisbee",
    "skis", "snowboard", "sports ball", "kite", "baseball bat", "baseball glove",
    "skateboard", "surfboard", "tennis racket", "bottle", "wine glass", "cup",
    "fork", "knife", "spoon", "bowl", "banana", "apple", "sandwich", "orange",
    "broccoli", "carrot", "hot dog", "pizza", "donut", "cake", "chair", "couch",
    "potted plant", "bed", "dining table", "toilet", "tv", "laptop", "mouse",
    "remote", "keyboard", "cell phone", "microwave", "oven", "toaster", "sink",
    "refrigerator", "book", "clock", "vase", "scissors", "teddy bear",
    "hair drier", "toothbrush"
]

# IMX500 model paths
IMX500_MODELS = {
    "nanodet": "/usr/share/imx500-models/imx500_network_nanodet_plus_416x416_pp.rpk",
    "efficientdet": "/usr/share/imx500-models/imx500_network_efficientdet_lite0_pp.rpk",
    "ssd_mobilenet": "/usr/share/imx500-models/imx500_network_ssd_mobilenetv2_fpnlite_320x320_pp.rpk",
}


def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}")


def capture_image(filename="/tmp/siteeye_capture.jpg", width=None, height=None):
    w = width or CAPTURE_WIDTH
    h = height or CAPTURE_HEIGHT
    try:
        os.remove(filename)
    except FileNotFoundError:
        pass
    result = subprocess.run(
        ["/usr/bin/rpicam-still", "-o", filename,
         "--width", str(w), "--height", str(h),
         "--nopreview", "-t", "2000", "--vflip", "--hflip"],
        capture_output=True, text=True, timeout=15
    )
    if os.path.exists(filename) and os.path.getsize(filename) > 0:
        return filename
    return None


def send_vision(image_path, prompt="What do you see? Be concise."):
    try:
        with open(image_path, "rb") as f:
            response = requests.post(
                f"{PROXY_URL}/vision",
                files={"image": ("capture.jpg", f, "image/jpeg")},
                data={"prompt": prompt},
                timeout=60
            )
        if response.status_code == 200:
            return response.json()
        return {"error": f"Proxy returned {response.status_code}"}
    except requests.exceptions.ConnectionError:
        return {"error": "Cannot reach proxy — check network"}
    except requests.exceptions.Timeout:
        return {"error": "Proxy timeout (60s)"}
    except Exception as e:
        return {"error": str(e)[:80]}


def send_telegram(text, image_path=None):
    if not TELEGRAM_BOT_TOKEN:
        return False
    try:
        if image_path:
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
            with open(image_path, "rb") as f:
                r = requests.post(url,
                    data={"chat_id": TELEGRAM_CHAT_ID, "caption": text[:1024]},
                    files={"photo": f}, timeout=15)
        else:
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
            r = requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": text}, timeout=10)
        return r.status_code == 200
    except Exception as e:
        log(f"Telegram send failed: {e}")
        return False


def cmd_camera():
    log("📷 Capturing...")
    img = capture_image()
    if not img:
        log("❌ Camera capture failed")
        return

    log(f"📤 Sending to proxy ({os.path.getsize(img)} bytes)...")
    result = send_vision(img)

    if "error" in result:
        log(f"❌ {result['error']}")
    else:
        response = result.get("response", "No response")
        log(f"🤖 {response}")
        send_telegram(f"📷 SiteEye\n\n🤖 {response}", image_path=img)

    try:
        os.remove(img)
    except:
        pass


def cmd_detect():
    available = {k: v for k, v in IMX500_MODELS.items() if os.path.exists(v)}
    if not available:
        log("❌ No IMX500 models installed. Run: sudo apt install imx500-models")
        return

    model_name = "nanodet" if "nanodet" in available else list(available.keys())[0]
    log(f"🔍 Running {model_name} detection...")

    detect_script = f'''
import json
try:
    from picamera2 import Picamera2
    from picamera2.devices.imx500 import IMX500
    imx = IMX500("{available[model_name]}")
    picam2 = Picamera2(imx.camera_num)
    config = picam2.create_still_configuration(buffer_count=2)
    picam2.start(config)
    import time; time.sleep(10)
    picam2.capture_file("/tmp/siteeye_detect.jpg")
    metadata = picam2.capture_metadata()
    outputs = imx.get_outputs(metadata)
    picam2.stop(); picam2.close()
    results = []
    if outputs is not None and len(outputs) >= 3:
        boxes, scores, classes = outputs[0], outputs[1], outputs[2]
        for i in range(len(scores)):
            if scores[i] > 0.35:
                box = boxes[i] if i < len(boxes) else [0,0,0,0]
                results.append({{"class": int(classes[i]), "conf": float(scores[i]), "box": [float(b) for b in box]}})
    print(json.dumps(results))
except Exception as e:
    print(json.dumps({{"error": str(e)}}))
'''
    try:
        result = subprocess.run(["python3", "-c", detect_script],
            capture_output=True, text=True, timeout=90)
        if result.returncode == 0 and result.stdout.strip():
            data = json.loads(result.stdout.strip())
            if isinstance(data, dict) and "error" in data:
                log(f"❌ Detection error: {data['error']}")
                return
            img_path = "/tmp/siteeye_detect.jpg"
            if not os.path.exists(img_path):
                log("❌ Detection image capture failed")
                return
            if not data:
                log("👁 Nothing detected")
                return
            lines = []
            for d in data:
                cls_id = d.get("class", 0)
                name = COCO_CLASSES[cls_id] if cls_id < len(COCO_CLASSES) else f"class_{cls_id}"
                conf = d.get("conf", 0)
                lines.append(f"  {name}: {conf:.0%}")
                log(f"  → {name}: {conf:.0%}")
            send_telegram(f"🔍 SiteEye detection ({model_name}):\n" + "\n".join(lines), image_path=img_path)
        else:
            log(f"❌ Detection failed: {result.stderr[:80]}")
    except subprocess.TimeoutExpired:
        log("❌ Detection timeout (90s)")
    except Exception as e:
        log(f"❌ {e}")


def cmd_info():
    try:
        temp = int(open("/sys/class/thermal/thermal_zone0/temp").read().strip()) / 1000
    except:
        temp = 0
    try:
        uptime_s = float(open("/proc/uptime").read().split()[0])
        hours, mins = int(uptime_s // 3600), int((uptime_s % 3600) // 60)
        uptime = f"{hours}h{mins}m"
    except:
        uptime = "?"
    try:
        ip = subprocess.check_output(["hostname", "-I"], text=True).strip().split()[0]
    except:
        ip = "no network"
    try:
        df = subprocess.check_output(["df", "-h", "/"], text=True).split("\n")[1].split()
        disk = f"{df[2]}/{df[1]} used"
    except:
        disk = "?"
    models = sum(1 for v in IMX500_MODELS.values() if os.path.exists(v))
    print(f"""
╔══ SiteEye v1 ══════════════╗
║ IP:     {ip}
║ Uptime: {uptime}
║ Temp:   {temp:.1f}°C
║ Disk:   {disk}
║ Camera: IMX500 ✅
║ AI:     {models} on-chip models
╚════════════════════════════╝""")


def check_proxy():
    try:
        r = requests.get(f"{PROXY_URL}/health", timeout=5)
        return r.status_code == 200
    except:
        return False


def main():
    print("═══ SiteEye v1-Lite — Camera + Vision AI ═══")
    print(f"Proxy: {PROXY_URL}")

    if check_proxy():
        log("✅ Proxy connected")
    else:
        log("⚠️  Proxy unreachable — vision commands will fail")

    print("\nCommands: c=camera d=detect t=timelapse i=info q=quit\n")

    while True:
        try:
            cmd = input("siteeye> ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            break
        if cmd == "q":
            break
        elif cmd == "c":
            cmd_camera()
        elif cmd == "d":
            cmd_detect()
        elif cmd == "i":
            cmd_info()
        elif cmd == "":
            continue
        else:
            print(f"  Unknown: '{cmd}' — try c/d/i/q")

    log("Goodbye!")


if __name__ == "__main__":
    main()
