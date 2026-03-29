#!/usr/bin/env python3
"""SiteEye v2 — Whisplay HAT client for Pi Zero 2W + IMX500

Whisplay HAT provides:
  - WM8960 audio codec (dual MEMS mics + speaker)
  - 1.69" IPS LCD (240×280, ST7789P3)
  - RGB LED
  - Programmable button (GPIO 17)

Commands via button:
  Short press (<1s) = voice: record → STT → Molt → TTS → speaker
  Long press (>1s)  = camera: snap → GPT-4o vision → TTS → speaker
  Double tap        = device info on LCD

Keyboard fallback:
  v = voice, c = camera, i = info, q = quit
"""

import os
import sys
import time
import json
import subprocess
import threading
import signal
import struct
from datetime import datetime

import requests

# Add Whisplay driver to path
WHISPLAY_DIR = os.path.expanduser("~/Whisplay/Driver")
if os.path.isdir(WHISPLAY_DIR):
    sys.path.insert(0, WHISPLAY_DIR)

# --- Config ---
PROXY_URL = os.environ.get("SITEEYE_PROXY", "https://molted.tail4a98c5.ts.net")
CAPTURE_WIDTH = 640
CAPTURE_HEIGHT = 480
MAX_RECORD_SECONDS = 15
SAMPLE_RATE = 16000
CHANNELS = 1
AUDIO_FORMAT = "S16_LE"

# --- State ---
class State:
    IDLE = "idle"
    LISTENING = "listening"
    PROCESSING = "processing"
    SPEAKING = "speaking"
    CAMERA = "camera"
    ERROR = "error"

current_state = State.IDLE
recording_process = None
press_time = 0.0
whisplay_board = None


def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}")


# ========================
# LCD Display (Whisplay)
# ========================

def init_display():
    """Initialize the Whisplay LCD."""
    global whisplay_board
    try:
        from WhisPlay import WhisPlayBoard
        whisplay_board = WhisPlayBoard()
        whisplay_board.set_backlight(50)
        log("✅ LCD initialized")
        return True
    except Exception as e:
        log(f"⚠️  LCD init failed: {e}")
        return False


def set_rgb(r, g, b):
    """Set RGB LED color."""
    if whisplay_board:
        try:
            whisplay_board.set_rgb(r, g, b)
        except:
            pass


def draw_text_screen(title, body="", color=(255, 255, 255)):
    """Draw simple text screen on LCD."""
    if not whisplay_board:
        return
    try:
        from PIL import Image, ImageDraw, ImageFont
        img = Image.new('RGB', (240, 280), (10, 10, 26))
        draw = ImageDraw.Draw(img)
        
        # Try to load a decent font, fall back to default
        try:
            font_title = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 20)
            font_body = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 14)
        except:
            font_title = ImageFont.load_default()
            font_body = ImageFont.load_default()
        
        # Title
        draw.text((10, 10), title, fill=color, font=font_title)
        
        # Body — word wrap
        if body:
            y = 45
            words = body.split()
            line = ""
            for word in words:
                test = f"{line} {word}".strip()
                bbox = draw.textbbox((0, 0), test, font=font_body)
                if bbox[2] > 220:
                    draw.text((10, y), line, fill=(200, 200, 220), font=font_body)
                    y += 20
                    line = word
                    if y > 260:
                        break
                else:
                    line = test
            if line and y <= 260:
                draw.text((10, y), line, fill=(200, 200, 220), font=font_body)
        
        # Convert to RGB565 and send
        send_image_to_lcd(img)
    except Exception as e:
        log(f"LCD draw error: {e}")


def draw_eyes(state=State.IDLE):
    """Draw Cozmo-style eyes on LCD."""
    if not whisplay_board:
        return
    try:
        from PIL import Image, ImageDraw
        img = Image.new('RGB', (240, 280), (10, 10, 26))
        draw = ImageDraw.Draw(img)
        
        # Eye parameters based on state
        eye_y = 110
        left_x, right_x = 72, 168
        eye_w, eye_h = 36, 32
        pupil_r = 10
        
        # State-specific modifications
        if state == State.IDLE:
            eye_color = (255, 255, 255)
            pupil_color = (26, 26, 46)
            highlight_color = (136, 204, 255)
        elif state == State.LISTENING:
            eye_color = (255, 255, 255)
            pupil_color = (0, 40, 100)
            highlight_color = (0, 100, 255)
            eye_h = 38  # wider eyes
        elif state == State.PROCESSING:
            eye_color = (255, 255, 255)
            pupil_color = (50, 40, 0)
            highlight_color = (255, 200, 0)
            eye_h = 24  # squinting
        elif state == State.SPEAKING:
            eye_color = (255, 255, 255)
            pupil_color = (40, 0, 60)
            highlight_color = (180, 0, 255)
        elif state == State.CAMERA:
            eye_color = (255, 255, 255)
            pupil_color = (26, 26, 46)
            highlight_color = (255, 255, 255)
        else:  # error
            eye_color = (255, 200, 200)
            pupil_color = (100, 0, 0)
            highlight_color = (255, 50, 50)
        
        # Draw eyes (rounded rectangles)
        for cx in [left_x, right_x]:
            # Eye white
            draw.rounded_rectangle(
                [cx - eye_w, eye_y - eye_h, cx + eye_w, eye_y + eye_h],
                radius=12, fill=eye_color
            )
            # Pupil
            draw.ellipse(
                [cx - pupil_r, eye_y - pupil_r, cx + pupil_r, eye_y + pupil_r],
                fill=pupil_color
            )
            # Highlight
            draw.ellipse(
                [cx - pupil_r + 4, eye_y - pupil_r - 2,
                 cx - pupil_r + 10, eye_y - pupil_r + 4],
                fill=highlight_color
            )
        
        # Status text at bottom
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 12)
        except:
            from PIL import ImageFont
            font = ImageFont.load_default()
        
        status_text = {
            State.IDLE: "● Ready",
            State.LISTENING: "● Listening...",
            State.PROCESSING: "● Thinking...",
            State.SPEAKING: "● Speaking...",
            State.CAMERA: "● 📸 Capturing...",
            State.ERROR: "● Error",
        }.get(state, "")
        
        from PIL import ImageFont as IF
        try:
            sfont = IF.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 12)
        except:
            sfont = IF.load_default()
        draw.text((10, 258), status_text, fill=highlight_color, font=sfont)
        
        send_image_to_lcd(img)
    except Exception as e:
        log(f"Eyes draw error: {e}")


def send_image_to_lcd(img):
    """Convert PIL Image to RGB565 and send to Whisplay LCD."""
    if not whisplay_board:
        return
    try:
        pixel_data = []
        for y in range(280):
            for x in range(240):
                r, g, b = img.getpixel((x, y))
                rgb565 = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
                pixel_data.extend([(rgb565 >> 8) & 0xFF, rgb565 & 0xFF])
        whisplay_board.draw_image(0, 0, 240, 280, pixel_data)
    except Exception as e:
        log(f"LCD send error: {e}")


def set_state(new_state):
    """Update state, LED, and eyes."""
    global current_state
    current_state = new_state
    
    led_map = {
        State.IDLE:       (0, 128, 0),     # dim green
        State.LISTENING:  (0, 100, 255),    # blue
        State.PROCESSING: (255, 200, 0),    # yellow
        State.SPEAKING:   (180, 0, 255),    # purple
        State.CAMERA:     (255, 255, 255),  # white
        State.ERROR:      (255, 0, 0),      # red
    }
    r, g, b = led_map.get(new_state, (0, 0, 0))
    set_rgb(r, g, b)
    draw_eyes(new_state)


# ========================
# Audio (WM8960)
# ========================

def find_audio_device():
    """Find the WM8960 ALSA device."""
    try:
        result = subprocess.run(["aplay", "-l"], capture_output=True, text=True)
        for line in result.stdout.split("\n"):
            if "wm8960" in line.lower():
                # Extract card number
                card = line.split(":")[0].replace("card ", "").strip()
                return f"plughw:{card},0"
    except:
        pass
    return "plughw:0,0"


def record_audio(duration=None):
    """Record from WM8960 mics, return WAV path."""
    global recording_process
    dur = duration or MAX_RECORD_SECONDS
    device = find_audio_device()
    path = "/tmp/siteeye_recording.wav"
    
    try:
        os.remove(path)
    except:
        pass
    
    cmd = [
        "arecord", "-D", device,
        "-f", AUDIO_FORMAT,
        "-r", str(SAMPLE_RATE),
        "-c", str(CHANNELS),
        "-d", str(dur),
        path
    ]
    
    log(f"🎤 Recording ({dur}s max, device={device})...")
    recording_process = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return path


def stop_recording():
    """Stop current recording."""
    global recording_process
    if recording_process:
        recording_process.terminate()
        recording_process.wait(timeout=5)
        recording_process = None


def play_audio(path):
    """Play audio through WM8960 speaker."""
    device = find_audio_device()
    try:
        subprocess.run(
            ["aplay", "-D", device, path],
            capture_output=True, timeout=30
        )
    except subprocess.TimeoutExpired:
        log("⚠️  Playback timeout")
    except Exception as e:
        log(f"⚠️  Playback error: {e}")


def set_volume(percent=80):
    """Set speaker volume via ALSA mixer."""
    try:
        subprocess.run(
            ["amixer", "-D", "hw:wm8960soundcard", "sset", "Speaker", f"{percent}%"],
            capture_output=True
        )
    except:
        pass


# ========================
# Proxy Communication
# ========================

def send_voice(audio_path, image_path=None):
    """Send audio (+ optional image) to proxy for STT → Molt → TTS."""
    try:
        files = {"audio": open(audio_path, "rb")}
        if image_path and os.path.exists(image_path):
            files["image"] = open(image_path, "rb")
        
        r = requests.post(f"{PROXY_URL}/voice_all", files=files, timeout=60)
        
        for f in files.values():
            f.close()
        
        if r.ok:
            data = r.json()
            # Save TTS audio if present
            if "tts_audio" in data:
                tts_path = "/tmp/siteeye_tts.wav"
                audio_bytes = __import__('base64').b64decode(data["tts_audio"])
                with open(tts_path, "wb") as f:
                    f.write(audio_bytes)
                data["tts_path"] = tts_path
            return data
        return {"error": f"Proxy returned {r.status_code}"}
    except Exception as e:
        return {"error": str(e)[:100]}


def send_vision(image_path, prompt="What do you see? Be concise."):
    """Send image to proxy for GPT-4o vision analysis."""
    try:
        with open(image_path, "rb") as f:
            r = requests.post(
                f"{PROXY_URL}/vision",
                files={"image": ("capture.jpg", f, "image/jpeg")},
                data={"prompt": prompt},
                timeout=60
            )
        if r.ok:
            return r.json()
        return {"error": f"Proxy returned {r.status_code}"}
    except Exception as e:
        return {"error": str(e)[:100]}


# ========================
# Camera
# ========================

def capture_image():
    """Capture photo from IMX500."""
    path = "/tmp/siteeye_capture.jpg"
    try:
        os.remove(path)
    except:
        pass
    result = subprocess.run(
        ["/usr/bin/rpicam-still", "-o", path,
         "--width", str(CAPTURE_WIDTH), "--height", str(CAPTURE_HEIGHT),
         "--nopreview", "-t", "1500", "--vflip", "--hflip"],
        capture_output=True, text=True, timeout=15
    )
    if os.path.exists(path) and os.path.getsize(path) > 0:
        return path
    return None


# ========================
# Command Flows
# ========================

def flow_voice():
    """Voice flow: record → STT → Molt → TTS → speaker."""
    set_state(State.LISTENING)
    audio_path = record_audio(duration=MAX_RECORD_SECONDS)
    
    # Wait for recording to finish (button release or timeout)
    if recording_process:
        recording_process.wait()
    
    if not os.path.exists(audio_path) or os.path.getsize(audio_path) < 1000:
        log("❌ Recording too short or failed")
        set_state(State.ERROR)
        time.sleep(1)
        set_state(State.IDLE)
        return
    
    set_state(State.PROCESSING)
    log("🔄 Sending to proxy...")
    result = send_voice(audio_path)
    
    if "error" in result:
        log(f"❌ {result['error']}")
        draw_text_screen("Error", result['error'], color=(255, 80, 80))
        set_state(State.ERROR)
        time.sleep(2)
        set_state(State.IDLE)
        return
    
    transcript = result.get("transcript", "")
    response = result.get("response", "")
    log(f"🗣 You: {transcript}")
    log(f"🤖 Molt: {response}")
    
    # Show response on LCD
    draw_text_screen("Molt", response)
    
    # Play TTS
    if result.get("tts_path"):
        set_state(State.SPEAKING)
        play_audio(result["tts_path"])
    
    # Return to idle after a pause
    time.sleep(2)
    set_state(State.IDLE)


def flow_camera():
    """Camera flow: snap → vision → TTS → speaker."""
    set_state(State.CAMERA)
    log("📷 Capturing...")
    
    img = capture_image()
    if not img:
        log("❌ Camera capture failed")
        set_state(State.ERROR)
        time.sleep(1)
        set_state(State.IDLE)
        return
    
    set_state(State.PROCESSING)
    log(f"📤 Sending to proxy ({os.path.getsize(img)} bytes)...")
    result = send_vision(img)
    
    if "error" in result:
        log(f"❌ {result['error']}")
        draw_text_screen("Error", result['error'], color=(255, 80, 80))
        set_state(State.ERROR)
        time.sleep(2)
        set_state(State.IDLE)
        return
    
    response = result.get("response", "No response")
    log(f"🤖 {response}")
    
    # Show on LCD
    draw_text_screen("Vision", response)
    
    # TODO: TTS the response via proxy /tts endpoint
    
    time.sleep(5)
    set_state(State.IDLE)


def flow_info():
    """Show device info on LCD."""
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
    
    info = f"IP: {ip}\nUptime: {uptime}\nTemp: {temp:.1f}C\nProxy: {PROXY_URL}"
    draw_text_screen("SiteEye v2", info, color=(124, 196, 255))
    time.sleep(5)
    set_state(State.IDLE)


# ========================
# Button Handler
# ========================

def setup_button():
    """Set up Whisplay button on GPIO 17."""
    try:
        import RPi.GPIO as GPIO
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(17, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)
        
        def on_press(channel):
            global press_time
            press_time = time.time()
        
        def on_release(channel):
            global press_time
            duration = time.time() - press_time
            if current_state == State.LISTENING:
                # Stop recording
                stop_recording()
            elif current_state == State.IDLE:
                if duration > 1.0:
                    threading.Thread(target=flow_camera, daemon=True).start()
                else:
                    threading.Thread(target=flow_voice, daemon=True).start()
        
        GPIO.add_event_detect(17, GPIO.RISING, callback=on_press, bouncetime=50)
        GPIO.add_event_detect(17, GPIO.FALLING, callback=on_release, bouncetime=50)
        log("✅ Button configured (GPIO 17)")
        return True
    except Exception as e:
        log(f"⚠️  Button setup failed: {e}")
        return False


# ========================
# Main
# ========================

def main():
    print("═══ SiteEye v2 — Whisplay HAT ═══")
    print(f"Proxy: {PROXY_URL}")
    
    # Initialize hardware
    lcd_ok = init_display()
    
    # Set initial volume
    set_volume(80)
    
    # Try button setup (may fail without GPIO soldered)
    button_ok = setup_button()
    
    # Check proxy
    try:
        r = requests.get(f"{PROXY_URL}/health", timeout=5)
        proxy_ok = r.status_code == 200
    except:
        proxy_ok = False
    
    log(f"LCD: {'✅' if lcd_ok else '❌'}  Button: {'✅' if button_ok else '❌'}  Proxy: {'✅' if proxy_ok else '❌'}")
    
    # Show boot screen
    if lcd_ok:
        draw_text_screen("SiteEye v2", "Booting...\n\nWhisplay HAT ready", color=(124, 196, 255))
        time.sleep(1)
    
    set_state(State.IDLE)
    
    print("\nKeyboard: v=voice c=camera i=info q=quit")
    if button_ok:
        print("Button: short=voice, long=camera\n")
    
    while True:
        try:
            cmd = input("siteeye> ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            break
        
        if cmd == "q":
            break
        elif cmd == "v":
            flow_voice()
        elif cmd == "c":
            flow_camera()
        elif cmd == "i":
            flow_info()
        elif cmd == "":
            continue
        else:
            print(f"  Unknown: '{cmd}' — try v/c/i/q")
    
    # Cleanup
    set_rgb(0, 0, 0)
    if whisplay_board:
        try:
            whisplay_board.set_backlight(0)
            whisplay_board.cleanup()
        except:
            pass
    
    try:
        import RPi.GPIO as GPIO
        GPIO.cleanup()
    except:
        pass
    
    log("Goodbye!")


if __name__ == "__main__":
    main()
