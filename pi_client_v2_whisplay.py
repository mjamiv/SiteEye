#!/usr/bin/env python3
"""SiteEye v2 — Whisplay HAT client for Pi Zero 2W

Hardware: Pi Zero 2W + Whisplay HAT (WM8960 + LCD + mic + speaker + LED + button) + IMX500 camera
Software: VPS proxy at SITEEYE_PROXY for Whisper STT + GPT-4o vision + OpenClaw Gateway + TTS

Button:
  Short press (<1s) = voice: record → STT → Molt → TTS → speaker
  Long press (>1s)  = camera: snap → vision → TTS → speaker
  Press during processing = cancel

Commands (keyboard fallback):
  v = voice (record until Enter)
  c = camera snap → vision
  i = info (IP, temp, battery)
  q = quit
"""

import os
import sys
import time
import json
import signal
import subprocess
import threading
import requests
from datetime import datetime

# ──────────────────────────────────────────────
# Config
# ──────────────────────────────────────────────
PROXY_URL = os.environ.get("SITEEYE_PROXY", "https://molted.tail4a98c5.ts.net")
CAPTURE_WIDTH = 640
CAPTURE_HEIGHT = 480
MAX_RECORD_SECONDS = 15
SAMPLE_RATE = 16000

# Whisplay driver path
WHISPLAY_DRIVER_PATH = os.path.expanduser("~/Whisplay/Driver")
sys.path.insert(0, WHISPLAY_DRIVER_PATH)

# ──────────────────────────────────────────────
# Globals
# ──────────────────────────────────────────────
board = None          # WhisPlayBoard instance
recording = False
processing = False
cancel_flag = False
press_time = 0.0


def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}")


# ──────────────────────────────────────────────
# Whisplay HAT — LCD, LED, Button
# ──────────────────────────────────────────────

def init_whisplay():
    """Initialize the Whisplay HAT — LCD, LED, button."""
    global board
    try:
        from WhisPlay import WhisPlayBoard
        board = WhisPlayBoard()
        board.set_backlight(60)
        set_led("green")
        log("✅ Whisplay HAT initialized")
        return True
    except Exception as e:
        log(f"⚠️  Whisplay init failed: {e}")
        log("   Running in keyboard-only mode")
        return False


def set_led(color):
    """Set RGB LED color. Active-low PWM."""
    if not board:
        return
    colors = {
        "green":   (0, 255, 0),
        "blue":    (0, 100, 255),
        "yellow":  (255, 200, 0),
        "purple":  (180, 0, 255),
        "red":     (255, 0, 0),
        "white":   (255, 255, 255),
        "off":     (0, 0, 0),
    }
    r, g, b = colors.get(color, (0, 0, 0))
    try:
        board.set_rgb(r, g, b)
    except:
        pass


def lcd_text(lines, clear=True):
    """Display text lines on LCD. Simple text rendering."""
    if not board:
        return
    try:
        from PIL import Image, ImageDraw, ImageFont
        img = Image.new('RGB', (240, 280), (10, 10, 26))
        draw = ImageDraw.Draw(img)
        
        # Try to load a nice font, fall back to default
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 18)
            font_small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 14)
        except:
            font = ImageFont.load_default()
            font_small = font
        
        y = 20
        for i, line in enumerate(lines):
            f = font if i == 0 else font_small
            draw.text((10, y), line, fill=(255, 255, 255), font=f)
            y += 28 if i == 0 else 22
        
        # Convert to RGB565 and send to display
        pixel_data = []
        for py in range(280):
            for px in range(240):
                r, g, b = img.getpixel((px, py))
                rgb565 = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
                pixel_data.extend([(rgb565 >> 8) & 0xFF, rgb565 & 0xFF])
        
        board.draw_image(0, 0, 240, 280, pixel_data)
    except Exception as e:
        log(f"LCD error: {e}")


def lcd_eyes(state="idle"):
    """Draw Cozmo-style eyes on LCD."""
    if not board:
        return
    try:
        from PIL import Image, ImageDraw
        img = Image.new('RGB', (240, 280), (10, 10, 26))
        draw = ImageDraw.Draw(img)
        
        # Eye parameters
        eye_y = 110
        left_x, right_x = 72, 168
        eye_w, eye_h = 36, 32
        pupil_r = 10
        corner_r = 9
        
        # Eye expressions
        if state == "idle":
            lid_top = 0
        elif state == "listening":
            lid_top = -5  # wider
            eye_h = 36
        elif state == "thinking":
            lid_top = 8  # squinting
            eye_h = 24
        elif state == "speaking":
            lid_top = 2  # relaxed
        elif state == "camera":
            lid_top = -3
        else:
            lid_top = 0
        
        for cx in [left_x, right_x]:
            # Eyeball (white rounded rect)
            x1, y1 = cx - eye_w, eye_y - eye_h + lid_top
            x2, y2 = cx + eye_w, eye_y + eye_h
            draw.rounded_rectangle([x1, y1, x2, y2], radius=corner_r, fill=(255, 255, 255))
            
            # Pupil
            draw.ellipse([cx - pupil_r, eye_y - pupil_r, cx + pupil_r, eye_y + pupil_r],
                        fill=(26, 26, 46))
            
            # Highlight
            draw.ellipse([cx - 4, eye_y - 8, cx + 2, eye_y - 2],
                        fill=(136, 204, 255))
        
        # State text below eyes
        state_text = {
            "idle": "Ready",
            "listening": "Listening...",
            "thinking": "Thinking...",
            "speaking": "Speaking...",
            "camera": "📸 Capturing...",
        }
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 16)
        except:
            from PIL import ImageFont
            font = ImageFont.load_default()
        
        from PIL import ImageFont
        text = state_text.get(state, "")
        if text:
            try:
                font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 16)
            except:
                font = ImageFont.load_default()
            bbox = draw.textbbox((0, 0), text, font=font)
            tw = bbox[2] - bbox[0]
            draw.text(((240 - tw) // 2, 200), text, fill=(102, 102, 136), font=font)
        
        # Convert and send
        pixel_data = []
        for py in range(280):
            for px in range(240):
                r, g, b = img.getpixel((px, py))
                rgb565 = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
                pixel_data.extend([(rgb565 >> 8) & 0xFF, rgb565 & 0xFF])
        
        board.draw_image(0, 0, 240, 280, pixel_data)
    except Exception as e:
        log(f"Eyes error: {e}")


# ──────────────────────────────────────────────
# Audio — Record & Play via WM8960
# ──────────────────────────────────────────────

def record_audio(duration=None):
    """Record from WM8960 dual MEMS mics. Returns WAV path or None."""
    duration = duration or MAX_RECORD_SECONDS
    wav_path = "/tmp/siteeye_recording.wav"
    try:
        os.remove(wav_path)
    except FileNotFoundError:
        pass

    log(f"🎙 Recording ({duration}s max)...")
    set_led("blue")
    lcd_eyes("listening")

    try:
        result = subprocess.run(
            ["arecord", "-D", "plughw:wm8960soundcard",
             "-f", "S16_LE", "-r", str(SAMPLE_RATE), "-c", "1",
             "-d", str(duration), wav_path],
            capture_output=True, text=True, timeout=duration + 5
        )
        if os.path.exists(wav_path) and os.path.getsize(wav_path) > 1000:
            size = os.path.getsize(wav_path)
            log(f"✅ Recorded {size} bytes")
            return wav_path
        else:
            log(f"❌ Recording too small or missing")
            return None
    except subprocess.TimeoutExpired:
        log("❌ Recording timeout")
        return None
    except Exception as e:
        log(f"❌ Record error: {e}")
        return None


def play_audio(wav_path):
    """Play WAV file through WM8960 speaker."""
    if not os.path.exists(wav_path):
        return
    log("🔊 Playing...")
    set_led("purple")
    lcd_eyes("speaking")
    try:
        subprocess.run(
            ["aplay", "-D", "plughw:wm8960soundcard", wav_path],
            capture_output=True, timeout=30
        )
    except Exception as e:
        log(f"Playback error: {e}")


def set_volume(percent=80):
    """Set speaker volume via ALSA mixer."""
    try:
        subprocess.run(
            ["amixer", "-D", "hw:wm8960soundcard", "sset", "Speaker", f"{percent}%"],
            capture_output=True
        )
    except:
        pass


# ──────────────────────────────────────────────
# Camera
# ──────────────────────────────────────────────

def capture_image(filename="/tmp/siteeye_capture.jpg"):
    """Capture from IMX500."""
    try:
        os.remove(filename)
    except FileNotFoundError:
        pass
    
    set_led("white")
    lcd_eyes("camera")
    
    result = subprocess.run(
        ["/usr/bin/rpicam-still", "-o", filename,
         "--width", str(CAPTURE_WIDTH), "--height", str(CAPTURE_HEIGHT),
         "--nopreview", "-t", "1500", "--vflip", "--hflip"],
        capture_output=True, text=True, timeout=15
    )
    if os.path.exists(filename) and os.path.getsize(filename) > 0:
        return filename
    return None


# ──────────────────────────────────────────────
# Proxy Communication
# ──────────────────────────────────────────────

def send_voice(wav_path, image_path=None):
    """Send voice recording (+ optional image) to proxy. Returns response dict."""
    set_led("yellow")
    lcd_eyes("thinking")
    
    try:
        files = {"audio": ("recording.wav", open(wav_path, "rb"), "audio/wav")}
        if image_path and os.path.exists(image_path):
            files["image"] = ("capture.jpg", open(image_path, "rb"), "image/jpeg")
        
        r = requests.post(f"{PROXY_URL}/voice_all", files=files, timeout=60)
        
        # Close file handles
        for f in files.values():
            try:
                f[1].close()
            except:
                pass
        
        if r.ok:
            return r.json()
        return {"error": f"Proxy returned {r.status_code}"}
    except Exception as e:
        return {"error": str(e)[:100]}


def send_vision(image_path, prompt="What do you see? Be concise."):
    """Send image to proxy for vision analysis."""
    set_led("yellow")
    lcd_eyes("thinking")
    
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


# ──────────────────────────────────────────────
# Command Flows
# ──────────────────────────────────────────────

def cmd_voice():
    """Voice flow: record → STT → Molt → TTS → speaker."""
    wav = record_audio(duration=10)
    if not wav:
        set_led("red")
        lcd_text(["❌ Recording failed"])
        time.sleep(2)
        set_led("green")
        lcd_eyes("idle")
        return

    log("🔄 Sending to proxy...")
    result = send_voice(wav)
    
    if "error" in result:
        log(f"❌ {result['error']}")
        set_led("red")
        lcd_text(["Error", result['error'][:40]])
        time.sleep(3)
    else:
        transcript = result.get("transcript", "")
        response = result.get("response", "No response")
        tts_url = result.get("tts_url", "")
        
        log(f"👤 You: {transcript}")
        log(f"🤖 Molt: {response}")
        
        # Show response on LCD
        # Word-wrap response text
        words = response.split()
        lines = ["🤖 Molt:"]
        current = ""
        for w in words:
            if len(current + " " + w) > 28:
                lines.append(current.strip())
                current = w
            else:
                current = (current + " " + w).strip()
        if current:
            lines.append(current.strip())
        lcd_text(lines[:10])  # max 10 lines on screen
        
        # Play TTS if available
        if tts_url:
            try:
                tts_r = requests.get(tts_url, timeout=30)
                if tts_r.ok:
                    tts_path = "/tmp/siteeye_tts.wav"
                    with open(tts_path, "wb") as f:
                        f.write(tts_r.content)
                    play_audio(tts_path)
            except Exception as e:
                log(f"TTS playback error: {e}")
        
        # Keep response on screen for a bit
        time.sleep(3)
    
    set_led("green")
    lcd_eyes("idle")
    
    # Cleanup
    for f in ["/tmp/siteeye_recording.wav", "/tmp/siteeye_tts.wav"]:
        try:
            os.remove(f)
        except:
            pass


def cmd_camera():
    """Camera flow: snap → vision → TTS → speaker."""
    log("📷 Capturing...")
    img = capture_image()
    if not img:
        log("❌ Camera capture failed")
        set_led("red")
        lcd_text(["❌ Capture failed"])
        time.sleep(2)
        set_led("green")
        lcd_eyes("idle")
        return
    
    log(f"📤 Sending to proxy ({os.path.getsize(img)} bytes)...")
    result = send_vision(img)
    
    if "error" in result:
        log(f"❌ {result['error']}")
        set_led("red")
        lcd_text(["Error", result['error'][:40]])
        time.sleep(3)
    else:
        response = result.get("response", "No response")
        log(f"🤖 {response}")
        
        # Word-wrap for LCD
        words = response.split()
        lines = ["📷 Vision:"]
        current = ""
        for w in words:
            if len(current + " " + w) > 28:
                lines.append(current.strip())
                current = w
            else:
                current = (current + " " + w).strip()
        if current:
            lines.append(current.strip())
        lcd_text(lines[:10])
        
        # Play TTS of vision response
        tts_url = result.get("tts_url", "")
        if tts_url:
            try:
                tts_r = requests.get(tts_url, timeout=30)
                if tts_r.ok:
                    tts_path = "/tmp/siteeye_tts.wav"
                    with open(tts_path, "wb") as f:
                        f.write(tts_r.content)
                    play_audio(tts_path)
            except:
                pass
        
        time.sleep(5)
    
    set_led("green")
    lcd_eyes("idle")
    
    for f in ["/tmp/siteeye_capture.jpg", "/tmp/siteeye_tts.wav"]:
        try:
            os.remove(f)
        except:
            pass


def cmd_info():
    """Display device info."""
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
    
    # PiSugar battery (if available)
    battery = "N/A"
    try:
        import smbus2
        bus = smbus2.SMBus(1)
        pct = bus.read_byte_data(0x57, 0x2A)
        battery = f"{min(pct, 100)}%"
        bus.close()
    except:
        pass
    
    info_lines = [
        "SiteEye v2",
        f"IP: {ip}",
        f"Temp: {temp:.1f}°C",
        f"Uptime: {uptime}",
        f"Battery: {battery}",
        f"Camera: IMX500 ✅",
        f"Audio: WM8960",
    ]
    
    lcd_text(info_lines)
    
    for line in info_lines:
        print(f"  {line}")
    
    time.sleep(5)
    lcd_eyes("idle")


# ──────────────────────────────────────────────
# Button Handler
# ──────────────────────────────────────────────

def setup_button():
    """Set up Whisplay HAT button (GPIO 17) with press/release timing."""
    if not board:
        return False
    
    try:
        import RPi.GPIO as GPIO
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(17, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)
        
        def on_press(channel):
            global press_time
            press_time = time.time()
        
        def on_release(channel):
            global press_time, processing, cancel_flag
            duration = time.time() - press_time
            
            if processing:
                cancel_flag = True
                log("🚫 Cancelled")
                return
            
            if duration > 1.0:
                # Long press → camera
                processing = True
                try:
                    cmd_camera()
                finally:
                    processing = False
                    cancel_flag = False
            else:
                # Short press → voice
                processing = True
                try:
                    cmd_voice()
                finally:
                    processing = False
                    cancel_flag = False
        
        GPIO.add_event_detect(17, GPIO.RISING, callback=on_press, bouncetime=200)
        GPIO.add_event_detect(17, GPIO.FALLING, callback=on_release, bouncetime=200)
        log("✅ Button configured (GPIO 17)")
        return True
    except Exception as e:
        log(f"⚠️  Button setup failed: {e}")
        return False


# ──────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────

def check_proxy():
    try:
        r = requests.get(f"{PROXY_URL}/health", timeout=5)
        return r.status_code == 200
    except:
        return False


def main():
    print("═══ SiteEye v2 — Whisplay HAT ═══")
    print(f"Proxy: {PROXY_URL}")
    
    # Initialize hardware
    has_whisplay = init_whisplay()
    
    if has_whisplay:
        set_volume(80)
        # Try button setup (may fail if GPIO already in use by WhisPlay driver)
        # setup_button()  # uncomment when button wiring confirmed
    
    # Check proxy
    if check_proxy():
        log("✅ Proxy connected")
    else:
        log("⚠️  Proxy unreachable — will retry on commands")
    
    # Show boot screen
    if has_whisplay:
        lcd_text(["SiteEye v2", "", "🎸 Ready", "", f"Proxy: {'✅' if check_proxy() else '❌'}"])
        time.sleep(2)
        lcd_eyes("idle")
    
    print("\nCommands: v=voice c=camera i=info q=quit\n")
    
    while True:
        try:
            cmd = input("siteeye> ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            break
        
        if cmd == "q":
            break
        elif cmd == "v":
            cmd_voice()
        elif cmd == "c":
            cmd_camera()
        elif cmd == "i":
            cmd_info()
        elif cmd == "":
            continue
        else:
            print(f"  Unknown: '{cmd}' — try v/c/i/q")
    
    # Cleanup
    if board:
        set_led("off")
        try:
            board.set_backlight(0)
            board.cleanup()
        except:
            pass
    
    log("Goodbye! 👋")


if __name__ == "__main__":
    main()
