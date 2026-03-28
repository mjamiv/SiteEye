#!/usr/bin/env python3
"""SiteEye v2 — Whisplay HAT client for Pi Zero 2W + IMX500

Whisplay HAT provides: WM8960 audio (dual mics + speaker), 1.69" LCD, RGB LED, button
Camera: IMX500 via CSI ribbon cable

Button: tap = voice, long press = camera
LCD: Cozmo-style color eyes + status bar + response text
Audio: WM8960 record → Whisper STT → Molt → TTS → WM8960 playback
"""

import os
import sys
import subprocess
import requests
import time
import json
import threading
import signal
from datetime import datetime
from io import BytesIO

# Add Whisplay driver path
WHISPLAY_DRIVER = os.path.expanduser("~/Whisplay/Driver")
if os.path.exists(WHISPLAY_DRIVER):
    sys.path.insert(0, WHISPLAY_DRIVER)

try:
    from WhisPlay import WhisPlayBoard
    HAS_WHISPLAY = True
except ImportError:
    HAS_WHISPLAY = False
    print("⚠️  WhisPlay driver not found — display/LED/button disabled")

try:
    from PIL import Image, ImageDraw, ImageFont
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

# --- Config ---
PROXY_URL = os.environ.get("SITEEYE_PROXY", "https://molted.tail4a98c5.ts.net")
CAPTURE_WIDTH = 640
CAPTURE_HEIGHT = 480
MAX_RECORD_SECONDS = 10
LONG_PRESS_THRESHOLD = 1.0  # seconds

# LCD dimensions
LCD_W, LCD_H = 240, 280

# Audio config for WM8960
AUDIO_DEVICE = "plughw:wm8960soundcard"
RECORD_FORMAT = "S16_LE"
RECORD_RATE = "16000"
RECORD_CHANNELS = "1"

# Color palette
COLOR_BG = (10, 10, 26)
COLOR_EYE_WHITE = (255, 255, 255)
COLOR_PUPIL = (26, 26, 46)
COLOR_HIGHLIGHT = (136, 204, 255)
COLOR_TEXT = (255, 255, 255)
COLOR_DIM = (102, 102, 136)
COLOR_GREEN = (0, 204, 68)
COLOR_YELLOW = (255, 200, 0)
COLOR_RED = (255, 34, 0)
COLOR_BLUE = (0, 100, 255)
COLOR_PURPLE = (180, 0, 255)

# State
STATE_IDLE = "idle"
STATE_LISTENING = "listening"
STATE_THINKING = "thinking"
STATE_SPEAKING = "speaking"
STATE_CAMERA = "camera"
STATE_ERROR = "error"


def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}")


class SiteEyeV2:
    def __init__(self):
        self.state = STATE_IDLE
        self.board = None
        self.recording = False
        self.record_process = None
        self._press_time = 0
        self._running = True
        self._last_response = ""
        self._blink_timer = 0

        # Init Whisplay
        if HAS_WHISPLAY:
            try:
                self.board = WhisPlayBoard()
                self.board.set_backlight(50)
                log("✅ Whisplay HAT initialized")
            except Exception as e:
                log(f"⚠️  Whisplay init failed: {e}")
                self.board = None

        # Set initial LED
        self.set_led(STATE_IDLE)

    # --- LED Control ---
    def set_led(self, state):
        if not self.board:
            return
        try:
            colors = {
                STATE_IDLE: (0, 80, 0),       # dim green
                STATE_LISTENING: (0, 100, 255), # blue
                STATE_THINKING: (255, 200, 0),  # yellow
                STATE_SPEAKING: (180, 0, 255),  # purple
                STATE_CAMERA: (255, 255, 255),  # white flash
                STATE_ERROR: (255, 0, 0),       # red
            }
            r, g, b = colors.get(state, (0, 80, 0))
            self.board.set_rgb(r, g, b)
        except Exception as e:
            pass

    # --- LCD Drawing ---
    def draw_frame(self, state=None, text=None, battery=None):
        """Draw a complete LCD frame."""
        if not self.board or not HAS_PIL:
            return

        state = state or self.state
        img = Image.new('RGB', (LCD_W, LCD_H), COLOR_BG)
        draw = ImageDraw.Draw(img)

        # Status bar (top 22px)
        self._draw_status_bar(draw, battery)

        # Eyes (centered, y=80-160)
        self._draw_eyes(draw, state)

        # Text area (bottom 100px)
        if text:
            self._draw_text(draw, text, y_start=180)
        elif self._last_response:
            self._draw_text(draw, self._last_response, y_start=180)

        # Mode bar (bottom 20px)
        mode_text = {
            STATE_IDLE: "● Ready",
            STATE_LISTENING: "● Listening...",
            STATE_THINKING: "● Thinking...",
            STATE_SPEAKING: "● Speaking...",
            STATE_CAMERA: "● Camera",
            STATE_ERROR: "● Error",
        }.get(state, "● Ready")

        try:
            font_small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 12)
        except:
            font_small = ImageFont.load_default()
        draw.text((8, LCD_H - 20), mode_text, fill=COLOR_DIM, font=font_small)

        # Send to display
        self._send_to_lcd(img)

    def _draw_status_bar(self, draw, battery=None):
        """Status bar with battery, wifi, time."""
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 11)
        except:
            font = ImageFont.load_default()

        # Time
        now = datetime.now().strftime("%I:%M %p").lstrip("0")
        draw.text((LCD_W - 70, 4), now, fill=COLOR_DIM, font=font)

        # Battery
        if battery is not None:
            batt_color = COLOR_GREEN if battery > 50 else COLOR_YELLOW if battery > 20 else COLOR_RED
            draw.text((8, 4), f"🔋 {battery}%", fill=batt_color, font=font)

        # Divider
        draw.line([(0, 22), (LCD_W, 22)], fill=(40, 40, 60), width=1)

    def _draw_eyes(self, draw, state):
        """Draw Cozmo-style eyes."""
        # Eye positions
        left_cx, right_cx = 72, 168
        eye_cy = 105
        eye_hw, eye_hh = 36, 30  # half-width, half-height
        corner_r = 9

        # Eye shape based on state
        if state == STATE_LISTENING:
            eye_hh = 34  # wider eyes
            pupil_dy = -4
        elif state == STATE_THINKING:
            eye_hh = 22  # squinted
            pupil_dy = -6
            pupil_dx = 8  # look right
        elif state == STATE_SPEAKING:
            eye_hh = 28
            pupil_dy = 0
        elif state == STATE_CAMERA:
            eye_hh = 34
            pupil_dy = 0
        else:
            pupil_dy = 0

        if state != STATE_THINKING:
            pupil_dx = 0

        for cx in [left_cx, right_cx]:
            # Eye white
            draw.rounded_rectangle(
                [cx - eye_hw, eye_cy - eye_hh, cx + eye_hw, eye_cy + eye_hh],
                radius=corner_r, fill=COLOR_EYE_WHITE
            )
            # Pupil
            pr = 10
            px = cx + pupil_dx
            py = eye_cy + pupil_dy
            draw.ellipse([px - pr, py - pr, px + pr, py + pr], fill=COLOR_PUPIL)

            # Highlight
            hr = 4
            hx, hy = px - 4, py - 5
            draw.ellipse([hx - hr, hy - hr, hx + hr, hy + hr], fill=COLOR_HIGHLIGHT)

            # Small secondary highlight
            draw.ellipse([px + 3, py + 2, px + 6, py + 5], fill=(200, 230, 255))

    def _draw_text(self, draw, text, y_start=180):
        """Draw wrapped response text."""
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 13)
        except:
            font = ImageFont.load_default()

        # Word wrap
        words = text.split()
        lines = []
        current = ""
        max_w = LCD_W - 16
        for word in words:
            test = f"{current} {word}".strip()
            bbox = draw.textbbox((0, 0), test, font=font)
            if bbox[2] > max_w:
                if current:
                    lines.append(current)
                current = word
            else:
                current = test
        if current:
            lines.append(current)

        # Draw (max ~5 lines)
        y = y_start
        for line in lines[:6]:
            draw.text((8, y), line, fill=COLOR_TEXT, font=font)
            y += 16

    def _send_to_lcd(self, img):
        """Convert PIL image to RGB565 and send to Whisplay LCD."""
        if not self.board:
            return
        try:
            # Resize if needed
            if img.size != (LCD_W, LCD_H):
                img = img.resize((LCD_W, LCD_H))

            # Convert to RGB565
            pixels = img.tobytes()
            pixel_data = bytearray(LCD_W * LCD_H * 2)
            for i in range(0, len(pixels), 3):
                r, g, b = pixels[i], pixels[i+1], pixels[i+2]
                rgb565 = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
                idx = (i // 3) * 2
                pixel_data[idx] = (rgb565 >> 8) & 0xFF
                pixel_data[idx + 1] = rgb565 & 0xFF

            self.board.draw_image(0, 0, LCD_W, LCD_H, list(pixel_data))
        except Exception as e:
            log(f"LCD send error: {e}")

    # --- Audio ---
    def record_audio(self, filename="/tmp/siteeye_record.wav"):
        """Record from WM8960 dual MEMS mics."""
        try:
            os.remove(filename)
        except FileNotFoundError:
            pass

        self.record_process = subprocess.Popen(
            ["arecord", "-D", AUDIO_DEVICE, "-f", RECORD_FORMAT,
             "-r", RECORD_RATE, "-c", RECORD_CHANNELS,
             "-d", str(MAX_RECORD_SECONDS), filename],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        self.recording = True
        log(f"🎤 Recording (max {MAX_RECORD_SECONDS}s)...")

    def stop_recording(self):
        """Stop recording."""
        if self.record_process:
            self.record_process.terminate()
            self.record_process.wait()
            self.record_process = None
        self.recording = False
        log("🎤 Recording stopped")

    def play_audio(self, filename):
        """Play audio through WM8960 speaker."""
        try:
            subprocess.run(
                ["aplay", "-D", AUDIO_DEVICE, filename],
                capture_output=True, timeout=30
            )
        except subprocess.TimeoutExpired:
            log("⚠️  Playback timeout")
        except Exception as e:
            log(f"⚠️  Playback error: {e}")

    # --- Camera ---
    def capture_photo(self, filename="/tmp/siteeye_capture.jpg"):
        """Capture photo from IMX500."""
        try:
            os.remove(filename)
        except FileNotFoundError:
            pass

        result = subprocess.run(
            ["rpicam-still", "-o", filename, "--width", str(CAPTURE_WIDTH),
             "--height", str(CAPTURE_HEIGHT), "--nopreview", "-t", "1500",
             "--vflip", "--hflip"],
            capture_output=True, text=True, timeout=15
        )
        if os.path.exists(filename) and os.path.getsize(filename) > 0:
            return filename
        return None

    # --- Network ---
    def send_voice(self, audio_path):
        """Send audio to proxy → Whisper STT → Molt → TTS."""
        try:
            with open(audio_path, "rb") as f:
                r = requests.post(
                    f"{PROXY_URL}/voice_all",
                    files={"audio": ("recording.wav", f, "audio/wav")},
                    timeout=30
                )
            if r.ok:
                return r.json()
            return {"error": f"Proxy returned {r.status_code}"}
        except Exception as e:
            return {"error": str(e)[:80]}

    def send_vision(self, image_path, prompt="What do you see? Be concise."):
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
            return {"error": str(e)[:80]}

    # --- Flows ---
    def voice_flow(self):
        """Full voice pipeline: record → STT → Molt → TTS → play."""
        self.state = STATE_LISTENING
        self.set_led(STATE_LISTENING)
        self.draw_frame(STATE_LISTENING, "Listening...")

        audio_path = "/tmp/siteeye_record.wav"
        self.record_audio(audio_path)

        # Wait for button release or timeout
        log("Press button again to stop recording (or wait for timeout)")
        if self.record_process:
            self.record_process.wait()
        self.recording = False

        if not os.path.exists(audio_path) or os.path.getsize(audio_path) < 1000:
            log("❌ Recording too short or failed")
            self.state = STATE_IDLE
            self.set_led(STATE_IDLE)
            self.draw_frame(STATE_IDLE)
            return

        # Send to proxy
        self.state = STATE_THINKING
        self.set_led(STATE_THINKING)
        self.draw_frame(STATE_THINKING, "Thinking...")

        result = self.send_voice(audio_path)

        if "error" in result:
            log(f"❌ {result['error']}")
            self.state = STATE_ERROR
            self.set_led(STATE_ERROR)
            self.draw_frame(STATE_ERROR, result['error'])
            time.sleep(3)
        else:
            response_text = result.get("response", "No response")
            tts_path = result.get("tts_path")
            self._last_response = response_text
            log(f"🤖 {response_text[:100]}")

            # Play TTS
            self.state = STATE_SPEAKING
            self.set_led(STATE_SPEAKING)
            self.draw_frame(STATE_SPEAKING, response_text)

            if tts_path:
                # Download TTS audio from proxy
                try:
                    tts_url = f"{PROXY_URL}{tts_path}"
                    r = requests.get(tts_url, timeout=15)
                    if r.ok:
                        local_tts = "/tmp/siteeye_tts.wav"
                        with open(local_tts, "wb") as f:
                            f.write(r.content)
                        self.play_audio(local_tts)
                except Exception as e:
                    log(f"⚠️  TTS playback failed: {e}")

        # Return to idle
        self.state = STATE_IDLE
        self.set_led(STATE_IDLE)
        self.draw_frame(STATE_IDLE)

        # Cleanup
        for f in [audio_path, "/tmp/siteeye_tts.wav"]:
            try:
                os.remove(f)
            except:
                pass

    def camera_flow(self):
        """Camera pipeline: snap → vision AI → display + TTS."""
        self.state = STATE_CAMERA
        self.set_led(STATE_CAMERA)
        self.draw_frame(STATE_CAMERA, "📸 Capturing...")

        img_path = self.capture_photo()
        if not img_path:
            log("❌ Camera capture failed")
            self.state = STATE_ERROR
            self.set_led(STATE_ERROR)
            self.draw_frame(STATE_ERROR, "Camera failed")
            time.sleep(3)
            self.state = STATE_IDLE
            self.set_led(STATE_IDLE)
            self.draw_frame(STATE_IDLE)
            return

        log(f"📷 Captured {os.path.getsize(img_path)} bytes")

        # Send to proxy
        self.state = STATE_THINKING
        self.set_led(STATE_THINKING)
        self.draw_frame(STATE_THINKING, "Analyzing...")

        result = self.send_vision(img_path)

        if "error" in result:
            log(f"❌ {result['error']}")
            self._last_response = result['error']
            self.state = STATE_ERROR
            self.set_led(STATE_ERROR)
            self.draw_frame(STATE_ERROR, result['error'])
            time.sleep(3)
        else:
            response_text = result.get("response", "No response")
            self._last_response = response_text
            log(f"🤖 {response_text[:100]}")

            self.state = STATE_SPEAKING
            self.set_led(STATE_SPEAKING)
            self.draw_frame(STATE_SPEAKING, response_text)
            time.sleep(5)  # Display response

        # Return to idle
        self.state = STATE_IDLE
        self.set_led(STATE_IDLE)
        self.draw_frame(STATE_IDLE)

        try:
            os.remove(img_path)
        except:
            pass

    # --- Button Handler ---
    def on_button_press(self):
        self._press_time = time.time()

    def on_button_release(self):
        if self._press_time == 0:
            return
        duration = time.time() - self._press_time
        self._press_time = 0

        if self.recording:
            self.stop_recording()
            return

        if duration >= LONG_PRESS_THRESHOLD:
            log("📷 Long press → camera")
            threading.Thread(target=self.camera_flow, daemon=True).start()
        else:
            log("🎤 Short press → voice")
            threading.Thread(target=self.voice_flow, daemon=True).start()

    # --- Main Loop ---
    def setup_button(self):
        """Register Whisplay button callbacks."""
        if not self.board:
            return
        try:
            import RPi.GPIO as GPIO
            GPIO.setmode(GPIO.BCM)
            GPIO.setup(17, GPIO.IN)
            GPIO.add_event_detect(17, GPIO.RISING,
                callback=lambda ch: self.on_button_press(), bouncetime=200)
            GPIO.add_event_detect(17, GPIO.FALLING,
                callback=lambda ch: self.on_button_release(), bouncetime=200)
            log("✅ Button configured (GPIO 17)")
        except Exception as e:
            log(f"⚠️  Button setup failed: {e}")

    def run_keyboard(self):
        """Keyboard fallback when button not available."""
        print("\nCommands: v=voice c=camera i=info q=quit\n")
        while self._running:
            try:
                cmd = input("siteeye> ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                break
            if cmd == "q":
                break
            elif cmd == "v":
                self.voice_flow()
            elif cmd == "c":
                self.camera_flow()
            elif cmd == "i":
                self.show_info()
            elif cmd == "":
                continue
            else:
                print(f"  Unknown: '{cmd}'")

    def show_info(self):
        """Print device info."""
        try:
            temp = int(open("/sys/class/thermal/thermal_zone0/temp").read().strip()) / 1000
        except:
            temp = 0
        try:
            ip = subprocess.check_output(["hostname", "-I"], text=True).strip().split()[0]
        except:
            ip = "?"
        try:
            uptime_s = float(open("/proc/uptime").read().split()[0])
            h, m = int(uptime_s // 3600), int((uptime_s % 3600) // 60)
            uptime = f"{h}h{m}m"
        except:
            uptime = "?"

        whisplay = "✅" if self.board else "❌"
        print(f"""
╔══ SiteEye v2 ═══════════════╗
║ IP:       {ip}
║ Uptime:   {uptime}
║ Temp:     {temp:.1f}°C
║ Whisplay: {whisplay}
║ Camera:   IMX500
║ Proxy:    {PROXY_URL}
╚═════════════════════════════╝""")

    def check_proxy(self):
        try:
            r = requests.get(f"{PROXY_URL}/health", timeout=5)
            return r.status_code == 200
        except:
            return False

    def run(self):
        """Main entry point."""
        print("═══ SiteEye v2 — Whisplay + IMX500 ═══")
        print(f"Proxy: {PROXY_URL}")
        print(f"Whisplay: {'✅' if self.board else '❌ (keyboard mode)'}")

        if self.check_proxy():
            log("✅ Proxy connected")
        else:
            log("⚠️  Proxy unreachable")

        # Draw initial face
        self.draw_frame(STATE_IDLE)

        if self.board:
            self.setup_button()
            log("Button mode — tap=voice, hold=camera")
            log("Also accepting keyboard: v=voice c=camera i=info q=quit")

        self.run_keyboard()

        # Cleanup
        if self.board:
            self.board.set_rgb(0, 0, 0)
            self.board.set_backlight(0)
            self.board.cleanup()
        log("Goodbye! 👋")


def main():
    device = SiteEyeV2()
    device.run()


if __name__ == "__main__":
    main()
