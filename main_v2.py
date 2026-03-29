#!/usr/bin/env python3
"""SiteEye v2 — Pi Zero 2W + Whisplay HAT + IMX500

Full pipeline:
  - Button tap: voice recording → Whisper STT → Molt → TTS → speaker + LCD
  - Button hold (>1s): camera snap → GPT-4o vision → TTS → speaker + LCD
  - LCD shows premium AI assistant face + response text
  - RGB LED indicates state

Uses WhisPlayBoard's built-in button callbacks (no separate GPIO init).
Display renders at controlled rate to prevent flicker.
"""

import os
import sys
import time
import json
import base64
import signal
import subprocess
import threading
import tempfile
import requests
from datetime import datetime

sys.path.insert(0, '/home/pi-molt/Whisplay/Driver')

from lcd_ui import LcdUI, STATE_IDLE, STATE_LISTENING, STATE_THINKING, STATE_SPEAKING, STATE_CAMERA, STATE_ERROR, STATE_BOOT

# --- Config ---
PROXY_URL = os.environ.get("SITEEYE_PROXY", "https://molted.tail4a98c5.ts.net")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "8358560979:AAHEPmk-qQg9RsmrIR2cXyNP4i4u_Hqtl2U")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "8217278203")
CAPTURE_WIDTH = 640
CAPTURE_HEIGHT = 480
MAX_RECORD_SECONDS = 30
BUTTON_HOLD_THRESHOLD = 1.0  # seconds for camera mode
DOUBLE_TAP_WINDOW = 0.4  # seconds — two presses within this = double tap

# Audio device
AUDIO_DEV = "plughw:0,0"
RECORD_FMT = "S16_LE"
RECORD_RATE = "16000"
RECORD_CHANNELS = "1"

# Display target FPS
TARGET_FPS = 6
FRAME_INTERVAL = 1.0 / TARGET_FPS

# Boot animation frame count (matches lcd_ui boot sequence phases)
BOOT_FRAMES = 45


def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}")


class SiteEye:
    def __init__(self):
        self.ui = LcdUI()
        self.board = self.ui.board
        self._running = True
        self._recording = False
        self._record_proc = None
        self._press_time = 0
        self._busy = False

        # Audio feedback files
        self._base_dir = os.path.dirname(os.path.abspath(__file__))
        self._held_long = False
        self._press_id = 0
        self._last_release_time = 0  # for double-tap detection
        self._tap_count = 0
        self._tap_timer = None

        # Register button callbacks
        self.board.button_press_callback = self._on_button_press
        self.board.button_release_callback = self._on_button_release
        log("Button registered via WhisPlayBoard callbacks")

        # Set volume to max
        try:
            subprocess.run(["amixer", "-D", "hw:wm8960soundcard", "sset", "Speaker", "100%"],
                           capture_output=True, timeout=5)
            subprocess.run(["amixer", "-D", "hw:wm8960soundcard", "sset", "Speaker AC Volume", "5"],
                           capture_output=True, timeout=5)
            subprocess.run(["amixer", "-D", "hw:wm8960soundcard", "sset", "Speaker DC Volume", "5"],
                           capture_output=True, timeout=5)
            subprocess.run(["amixer", "-D", "hw:wm8960soundcard", "sset", "Playback", "100%"],
                           capture_output=True, timeout=5)
            subprocess.run(["amixer", "-D", "hw:wm8960soundcard", "sset", "Headphone", "100%"],
                           capture_output=True, timeout=5)
            subprocess.run(["amixer", "-D", "hw:wm8960soundcard", "sset", "Capture", "80%"],
                           capture_output=True, timeout=5)
            log("All volume controls maxed")
        except Exception:
            pass

    def _send_telegram(self, text, image_path=None):
        """Send text/photo to Telegram — mirrors device activity to phone."""
        if not TELEGRAM_BOT_TOKEN:
            return
        try:
            if image_path and os.path.exists(image_path):
                url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
                with open(image_path, "rb") as f:
                    requests.post(url,
                        data={"chat_id": TELEGRAM_CHAT_ID, "caption": text[:1024]},
                        files={"photo": f}, timeout=15)
            else:
                url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
                requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": text}, timeout=10)
        except Exception as e:
            log(f"Telegram send failed: {e}")

    def _info_screen(self):
        """Double-tap: show device info on LCD for 5 seconds."""
        if self._busy:
            return
        self._busy = True
        self._play_feedback("click.wav")
        log("ℹ️ Device info screen")

        try:
            temp = int(open("/sys/class/thermal/thermal_zone0/temp").read().strip()) / 1000
        except Exception:
            temp = 0
        try:
            uptime_s = float(open("/proc/uptime").read().split()[0])
            hours, mins = int(uptime_s // 3600), int((uptime_s % 3600) // 60)
            uptime = f"{hours}h {mins}m"
        except Exception:
            uptime = "?"
        try:
            ip = subprocess.check_output(["hostname", "-I"], text=True).strip().split()[0]
        except Exception:
            ip = "no network"
        try:
            df = subprocess.check_output(["df", "-h", "/"], text=True).split("\n")[1].split()
            disk = f"{df[2]} / {df[1]}"
        except Exception:
            disk = "?"

        info_lines = [
            f"IP: {ip}",
            f"Temp: {temp:.1f} C",
            f"Uptime: {uptime}",
            f"Disk: {disk}",
            f"Proxy: {'Online' if self._check_proxy() else 'Offline'}",
        ]
        self.ui.set_status("Device Info")
        self.ui.set_state(STATE_IDLE)
        self.ui.response_text = "\n".join(info_lines)
        self.ui._last_buf = None
        time.sleep(5)
        self.ui.response_text = ""
        self.ui.set_status("")
        self.ui.set_state(STATE_IDLE)
        self._busy = False

    def _check_proxy(self):
        try:
            r = requests.get(f"{PROXY_URL}/health", timeout=3)
            return r.status_code == 200
        except Exception:
            return False

    def _play_feedback(self, name):
        """Play a short audio feedback file (non-blocking)."""
        path = os.path.join(self._base_dir, "assets", name)
        if os.path.exists(path):
            threading.Thread(target=lambda: subprocess.run(
                ["aplay", "-D", AUDIO_DEV, path],
                capture_output=True, timeout=5
            ), daemon=True).start()

    def _on_button_press(self):
        """Button pressed — immediate feedback + hold detection."""
        self._press_time = time.time()
        self._held_long = False
        self._press_id += 1
        current_id = self._press_id

        # During recording, any press = stop recording
        if self._recording:
            self._play_feedback("click.wav")
            self._stop_recording()
            return

        if self._busy:
            return

        # Immediate feedback
        self._play_feedback("click.wav")
        self.ui.set_status("Hold → Camera  |  Release → Voice")

        # Background timer: if still held after threshold, switch to camera mode
        def _check_hold():
            time.sleep(BUTTON_HOLD_THRESHOLD)
            # Only fire if this is still the same press (not stale)
            if current_id == self._press_id and not self._busy and not self._recording:
                self._held_long = True
                self._play_feedback("camera_beep.wav")
                self.ui.set_status("📷 Release to capture")

        threading.Thread(target=_check_hold, daemon=True).start()

    def _on_button_release(self):
        """Button released — dispatch voice, camera, or double-tap info."""
        if self._busy or self._recording:
            return

        duration = time.time() - self._press_time
        if duration < 0.05:
            return  # Debounce

        # Long hold = camera (already detected)
        if self._held_long or duration > BUTTON_HOLD_THRESHOLD:
            self._tap_count = 0
            threading.Thread(target=self._camera_flow, daemon=True).start()
            return

        # Short tap — check for double-tap
        now = time.time()
        if now - self._last_release_time < DOUBLE_TAP_WINDOW:
            # Double tap detected!
            self._tap_count = 0
            self._last_release_time = 0
            if self._tap_timer:
                self._tap_timer.cancel()
            threading.Thread(target=self._info_screen, daemon=True).start()
            return

        self._last_release_time = now
        self._tap_count = 1

        # Wait briefly to see if a second tap comes
        def _delayed_voice():
            time.sleep(DOUBLE_TAP_WINDOW + 0.05)
            if self._tap_count == 1 and not self._busy:
                self._tap_count = 0
                self._voice_flow()

        self._tap_timer = threading.Thread(target=_delayed_voice, daemon=True)
        self._tap_timer.start()

    def _voice_flow(self):
        """Full voice pipeline: record → proxy → TTS → speaker."""
        if self._busy:
            return
        self._busy = True

        log("\U0001f399 Voice flow started")
        self.ui.set_status("Listening")
        self.ui.set_state(STATE_LISTENING)

        audio_path = "/tmp/siteeye_voice.wav"
        try:
            proc = subprocess.Popen(
                ["arecord", "-D", AUDIO_DEV, "-f", RECORD_FMT, "-r", RECORD_RATE,
                 "-c", RECORD_CHANNELS, "-d", str(MAX_RECORD_SECONDS), audio_path],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            self._record_proc = proc
            self._recording = True
            log("Recording... (press button to stop)")

            start = time.time()
            while self._recording and (time.time() - start) < MAX_RECORD_SECONDS:
                elapsed = int(time.time() - start)
                self.ui.set_status(f"Recording {elapsed}s — press to stop")
                time.sleep(0.1)
                if proc.poll() is not None:
                    break

            self._stop_recording()
        except Exception as e:
            log(f"Record error: {e}")
            self.ui.set_state(STATE_ERROR, "Record failed")
            self._play_feedback("error.wav")
            time.sleep(2)
            self.ui.set_status(""); self.ui.set_state(STATE_IDLE)
            self._busy = False
            return

        if not os.path.exists(audio_path) or os.path.getsize(audio_path) < 1000:
            log("Recording too short")
            self.ui.set_status(""); self.ui.set_state(STATE_IDLE)
            self._busy = False
            return

        # Capture background image for context
        img_path = self._capture_photo()

        self.ui.set_status("Processing")
        self.ui.set_state(STATE_THINKING)
        log("\U0001f504 Sending to proxy...")

        try:
            files = {"audio": ("voice.wav", open(audio_path, "rb"), "audio/wav")}
            if img_path:
                files["image"] = ("snap.jpg", open(img_path, "rb"), "image/jpeg")

            r = requests.post(f"{PROXY_URL}/voice_all", files=files, timeout=60)

            for f in files.values():
                try:
                    f[1].close()
                except Exception:
                    pass

            if r.status_code == 200:
                data = r.json()
                transcription = data.get("transcription", "")
                response = data.get("response", "")
                audio_b64 = data.get("audio")

                log(f"\U0001f4dd You: {transcription}")
                log(f"\U0001f916 Molt: {response}")

                # Mirror to Telegram
                threading.Thread(target=self._send_telegram,
                    args=(f"🎙 You: {transcription}\n\n🤖 {response}",), daemon=True).start()

                self.ui.set_status("Speaking")
                self.ui.set_state(STATE_SPEAKING, response)

                if audio_b64:
                    self._play_audio_b64(audio_b64)
                else:
                    time.sleep(2)

                # Keep text visible briefly, then clear
                time.sleep(3)
                self.ui.response_text = ""
            else:
                log(f"\u274c Proxy error: {r.status_code}")
                self.ui.set_status("Error")
                self.ui.set_state(STATE_ERROR, f"Error {r.status_code}")
                time.sleep(2)
        except Exception as e:
            log(f"\u274c {e}")
            self.ui.set_state(STATE_ERROR, str(e)[:40])
            time.sleep(2)

        for p in [audio_path, img_path]:
            try:
                if p:
                    os.remove(p)
            except Exception:
                pass

        self.ui.set_status(""); self.ui.set_state(STATE_IDLE)
        self._busy = False

    def _camera_flow(self):
        """Camera pipeline: live viewfinder → press to capture → vision → TTS."""
        if self._busy:
            return
        self._busy = True

        log("\U0001f4f7 Camera flow — live viewfinder")
        self.ui.set_status("Viewfinder — press to capture")

        # Live viewfinder loop: stream camera to LCD until button press
        self._camera_shutter = False
        try:
            from picamera2 import Picamera2
            picam2 = Picamera2()
            config = picam2.create_preview_configuration(
                main={'size': (240, 280), 'format': 'RGB888'})
            picam2.configure(config)
            picam2.start()
            time.sleep(0.3)  # Let auto-exposure settle

            # Set up shutter trigger
            def _shutter_press():
                self._camera_shutter = True
            # Temporarily override button callback for shutter
            old_press = self.board.button_press_callback
            self.board.button_press_callback = _shutter_press

            log("Live viewfinder active — press button to capture")
            frame_count = 0
            while not self._camera_shutter and self._running:
                try:
                    frame = picam2.capture_array()
                    self.ui.show_live_frame(frame)
                    frame_count += 1
                except Exception:
                    pass
                time.sleep(0.08)  # ~12fps target for viewfinder
                # Safety timeout: 30 seconds
                if frame_count > 375:
                    break

            # Restore button callback
            self.board.button_press_callback = old_press

            # Capture final still at full resolution
            self._play_feedback("click.wav")
            self.ui.set_status("Capturing...")
            img_path = "/tmp/siteeye_snap.jpg"
            picam2.switch_mode_and_capture_file(
                picam2.create_still_configuration(), img_path)
            picam2.stop()
            picam2.close()
        except Exception as e:
            log(f"Camera error: {e}")
            try:
                picam2.stop()
                picam2.close()
            except Exception:
                pass
            self.ui.set_state(STATE_ERROR, "Camera failed")
            self._play_feedback("error.wav")
            time.sleep(2)
            self.ui.set_status(""); self.ui.set_state(STATE_IDLE)
            self._busy = False
            return

        if not os.path.exists(img_path) or os.path.getsize(img_path) < 1000:
            log("\u274c Capture failed")
            self.ui.set_state(STATE_ERROR, "Capture failed")
            self._play_feedback("error.wav")
            time.sleep(2)
            self.ui.set_status(""); self.ui.set_state(STATE_IDLE)
            self._busy = False
            return

        # Show captured still on LCD
        self.ui.show_captured_image(img_path)
        log("\U0001f504 Sending to proxy for vision...")

        try:
            with open(img_path, "rb") as f:
                r = requests.post(f"{PROXY_URL}/vision",
                    files={"image": ("snap.jpg", f, "image/jpeg")},
                    data={"prompt": "What do you see? Be concise and conversational."},
                    timeout=60)

            if r.status_code == 200:
                data = r.json()
                response = data.get("response", "No response")
                log(f"\U0001f916 {response}")

                self.ui.set_photo_text(response)

                # Mirror photo + response to Telegram
                threading.Thread(target=self._send_telegram,
                    args=(f"📷 SiteEye\n\n🤖 {response}", img_path), daemon=True).start()

                try:
                    tts_r = requests.post(f"{PROXY_URL}/tts",
                        json={"text": response}, timeout=60)
                    if tts_r.status_code == 200 and len(tts_r.content) > 100:
                        self._play_audio_raw(tts_r.content)
                    else:
                        log(f"\u26a0\ufe0f TTS error: status={tts_r.status_code} len={len(tts_r.content)}")
                        time.sleep(3)
                except Exception as e:
                    log(f"\u26a0\ufe0f TTS failed: {e}")
                    time.sleep(3)

                # Keep photo + text visible briefly after speech
                time.sleep(4)
            else:
                log(f"\u274c Vision error: {r.status_code}")
                self.ui.set_photo_text(f"Error {r.status_code}")
                time.sleep(3)
        except Exception as e:
            log(f"\u274c {e}")
            self.ui.set_photo_text(str(e)[:40])
            time.sleep(3)

        self.ui.clear_photo()

        try:
            os.remove(img_path)
        except Exception:
            pass

        self.ui.set_status(""); self.ui.set_state(STATE_IDLE)
        self._busy = False

    def _capture_photo(self):
        path = "/tmp/siteeye_snap.jpg"
        try:
            subprocess.run(
                ["rpicam-still", "-o", path, "--width", str(CAPTURE_WIDTH),
                 "--height", str(CAPTURE_HEIGHT), "--nopreview", "-t", "1500",
                 "--vflip", "--hflip"],
                capture_output=True, timeout=15
            )
            if os.path.exists(path) and os.path.getsize(path) > 0:
                return path
        except Exception as e:
            log(f"Camera error: {e}")
        return None

    def _stop_recording(self):
        self._recording = False
        if self._record_proc and self._record_proc.poll() is None:
            self._record_proc.terminate()
            try:
                self._record_proc.wait(timeout=2)
            except Exception:
                self._record_proc.kill()
        self._record_proc = None

    def _play_audio_b64(self, audio_b64):
        try:
            audio_bytes = base64.b64decode(audio_b64)
            self._play_audio_raw(audio_bytes)
        except Exception as e:
            log(f"Playback error: {e}")

    def _play_audio_raw(self, audio_bytes):
        try:
            tmp_path = "/tmp/siteeye_tts.wav"
            with open(tmp_path, "wb") as f:
                f.write(audio_bytes)
            subprocess.run(
                ["aplay", "-D", AUDIO_DEV, tmp_path],
                capture_output=True, timeout=120
            )
            os.remove(tmp_path)
        except Exception as e:
            log(f"Playback error: {e}")

    def _display_loop(self):
        while self._running:
            frame_start = time.time()
            try:
                self.ui.render_frame()
            except Exception as e:
                log(f"Display error: {e}")

            elapsed = time.time() - frame_start
            sleep_time = FRAME_INTERVAL - elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)

    def _keyboard_loop(self):
        while self._running:
            try:
                cmd = input("").strip().lower()
                if cmd == "v":
                    threading.Thread(target=self._voice_flow, daemon=True).start()
                elif cmd == "c":
                    threading.Thread(target=self._camera_flow, daemon=True).start()
                elif cmd == "q":
                    self._running = False
                    break
                elif cmd == "s":
                    self._stop_recording()
            except (EOFError, KeyboardInterrupt):
                self._running = False
                break

    def run(self):
        log("\u2550\u2550\u2550 SiteEye v2 \u2014 Whisplay + IMX500 \u2550\u2550\u2550")
        log(f"Proxy: {PROXY_URL}")

        # Boot animation
        self.ui.set_state(STATE_BOOT)
        for _ in range(BOOT_FRAMES):
            frame_start = time.time()
            self.ui.render_frame()
            elapsed = time.time() - frame_start
            if FRAME_INTERVAL - elapsed > 0:
                time.sleep(FRAME_INTERVAL - elapsed)

        # Health check
        try:
            r = requests.get(f"{PROXY_URL}/health", timeout=5)
            if r.status_code == 200:
                log("\u2705 Proxy connected")
                self.ui.set_status("Connected")
            else:
                log("\u26a0\ufe0f Proxy unhealthy")
                self.ui.set_status("Proxy error")
        except Exception:
            log("\u26a0\ufe0f Proxy unreachable")
            self.ui.set_status("Offline")

        self.ui.set_status(""); self.ui.set_state(STATE_IDLE)

        # Startup audio: chime → voice announcement
        base_dir = os.path.dirname(os.path.abspath(__file__))
        for sound in ["assets/chime.wav", "assets/startup.wav"]:
            sound_path = os.path.join(base_dir, sound)
            if os.path.exists(sound_path):
                try:
                    subprocess.run(["aplay", "-D", AUDIO_DEV, sound_path],
                                   capture_output=True, timeout=10)
                except Exception:
                    pass
        log("\U0001f50a Startup audio played")

        # Start display loop
        display_thread = threading.Thread(target=self._display_loop, daemon=True)
        display_thread.start()

        log("\nControls:")
        log("  Button tap = voice | Button hold (>1s) = camera")
        log("  Keyboard: v=voice c=camera s=stop q=quit\n")

        if sys.stdin.isatty():
            try:
                self._keyboard_loop()
            except Exception:
                pass
        else:
            log("Headless mode \u2014 button only")
            try:
                while self._running:
                    time.sleep(1)
            except Exception:
                pass

        log("Shutting down...")
        self._running = False
        self.ui.cleanup()
        log("Goodbye!")


def main():
    app = SiteEye()

    def handle_signal(sig, frame):
        app._running = False

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    app.run()


if __name__ == "__main__":
    main()
