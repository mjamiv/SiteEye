#!/usr/bin/env python3
"""SiteEye — Pi Zero 2W + Whisplay HAT + IMX500

Pipeline:
  - Button tap:        voice recording → Whisper STT → Molt AI → TTS → speaker + LCD
  - Button hold (>1s): camera snap → GPT-4o vision → TTS → speaker + LCD
  - Button double-tap: info dashboard — BTC / Calendar / Weather / Device stats
  - LCD shows animated AI face + response text
  - RGB LED indicates state
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

sys.path.insert(0, os.path.expanduser('~/Whisplay/Driver'))

from lcd_ui import (
    LcdUI,
    STATE_IDLE, STATE_LISTENING, STATE_THINKING, STATE_SPEAKING,
    STATE_CAMERA, STATE_ERROR, STATE_BOOT, STATE_DASHBOARD,
)

# --- Config (set via environment variables) ---
PROXY_URL = os.environ.get("SITEEYE_PROXY", "https://your-proxy.example.com")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# --- Hardware ---
CAPTURE_WIDTH = 640
CAPTURE_HEIGHT = 480
MAX_RECORD_SECONDS = 30
BUTTON_HOLD_THRESHOLD = 1.0   # seconds → camera mode
DOUBLE_TAP_WINDOW = 0.4       # seconds — two presses within this = double tap
AUDIO_DEV = "plughw:0,0"
RECORD_FMT = "S16_LE"
RECORD_RATE = "16000"
RECORD_CHANNELS = "1"

# --- Display ---
TARGET_FPS = 6
FRAME_INTERVAL = 1.0 / TARGET_FPS
BOOT_FRAMES = 48   # Must exceed highest frame in lcd_ui boot phases

# --- Dashboard ---
DASHBOARD_PANELS = 4          # BTC, Calendar, Weather, Device
DASHBOARD_TIMEOUT = 8.0       # seconds idle → return to face


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
        self._busy = False

        self._base_dir = os.path.dirname(os.path.abspath(__file__))
        self._press_time = 0
        self._held_long = False
        self._press_id = 0
        self._tap_count = 0
        self._dispatch_timer = None

        # Dashboard state
        self._dashboard_active = False
        self._dashboard_panel = 0          # 0-3 current panel index
        self._dashboard_data = {}          # cached data from proxy
        self._dashboard_last_tap = 0.0     # timestamp of last interaction
        self._dashboard_thread = None

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

    # ------------------------------------------------------------------
    # Telegram mirroring
    # ------------------------------------------------------------------

    def _send_telegram(self, text, image_path=None):
        """Mirror device activity to Telegram."""
        if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
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

    # ------------------------------------------------------------------
    # Dashboard
    # ------------------------------------------------------------------

    def _fetch_dashboard_data(self):
        """Fetch all dashboard data from proxy in one call."""
        try:
            r = requests.get(f"{PROXY_URL}/dashboard", timeout=8)
            if r.status_code == 200:
                self._dashboard_data = r.json()
                log(f"Dashboard data: {list(self._dashboard_data.keys())}")
        except Exception as e:
            log(f"Dashboard fetch failed: {e}")

    def _get_device_stats(self):
        """Gather local device stats (CPU temp, uptime, IP, disk)."""
        stats = {}
        try:
            with open("/sys/class/thermal/thermal_zone0/temp") as f:
                temp_c = int(f.read().strip()) / 1000
            stats["cpu_temp"] = f"{temp_c:.1f}°C"
        except Exception:
            stats["cpu_temp"] = "N/A"

        try:
            with open("/proc/uptime") as f:
                secs = float(f.read().split()[0])
            h, m = int(secs // 3600), int((secs % 3600) // 60)
            stats["uptime"] = f"{h}h {m}m"
        except Exception:
            stats["uptime"] = "N/A"

        try:
            result = subprocess.run(["hostname", "-I"], capture_output=True, text=True, timeout=3)
            stats["ip"] = result.stdout.strip().split()[0]
        except Exception:
            stats["ip"] = "N/A"

        try:
            result = subprocess.run(["df", "-h", "/"], capture_output=True, text=True, timeout=3)
            lines = result.stdout.strip().split("\n")
            if len(lines) > 1:
                parts = lines[1].split()
                stats["disk"] = f"{parts[2]}/{parts[1]} ({parts[4]})"
        except Exception:
            stats["disk"] = "N/A"

        return stats

    def _open_dashboard(self):
        """Open dashboard at panel 0, fetch data, start timeout watcher."""
        if self._busy and not self._dashboard_active:
            return

        log("📊 Dashboard opened")
        self._dashboard_active = True
        self._dashboard_panel = 0
        self._dashboard_last_tap = time.time()
        self._busy = True

        # Fetch proxy data (background so UI doesn't block)
        threading.Thread(target=self._fetch_dashboard_data, daemon=True).start()

        # Gather device stats immediately (local, fast)
        self._dashboard_data["device"] = self._get_device_stats()

        self.ui.set_state(STATE_DASHBOARD)
        self._show_dashboard_panel()

        # Start timeout watcher
        self._dashboard_thread = threading.Thread(target=self._dashboard_timeout_watcher, daemon=True)
        self._dashboard_thread.start()

    def _next_dashboard_panel(self):
        """Cycle to the next panel."""
        if not self._dashboard_active:
            return
        self._dashboard_panel = (self._dashboard_panel + 1) % DASHBOARD_PANELS
        self._dashboard_last_tap = time.time()
        log(f"📊 Dashboard panel {self._dashboard_panel}")
        self._show_dashboard_panel()

    def _show_dashboard_panel(self):
        """Push current panel to LCD."""
        panel = self._dashboard_panel

        if panel == 0:
            # BTC
            btc = self._dashboard_data.get("btc", {})
            panel_data = {
                "type": "btc",
                "price": btc.get("price", 0),
                "change": btc.get("change", 0.0),
            }
        elif panel == 1:
            # Calendar
            cal = self._dashboard_data.get("calendar", {})
            panel_data = {
                "type": "calendar",
                "summary": cal.get("summary", "No events"),
                "start": cal.get("start", ""),
            }
        elif panel == 2:
            # Weather
            wx = self._dashboard_data.get("weather", {})
            panel_data = {
                "type": "weather",
                "temp": wx.get("temp", "--"),
                "condition": wx.get("condition", ""),
            }
        else:
            # Device stats
            dev = self._dashboard_data.get("device", {})
            panel_data = {
                "type": "device",
                "cpu_temp": dev.get("cpu_temp", "N/A"),
                "uptime": dev.get("uptime", "N/A"),
                "ip": dev.get("ip", "N/A"),
                "disk": dev.get("disk", "N/A"),
            }

        self.ui.render_dashboard(panel_data, self._dashboard_panel, DASHBOARD_PANELS)

    def _close_dashboard(self):
        """Exit dashboard, return to idle face."""
        log("📊 Dashboard closed")
        self._dashboard_active = False
        self._dashboard_panel = 0
        self._busy = False
        self.ui.set_status("")
        self.ui.set_state(STATE_IDLE)

    def _dashboard_timeout_watcher(self):
        """Auto-close dashboard after DASHBOARD_TIMEOUT seconds of inactivity."""
        while self._dashboard_active:
            time.sleep(0.5)
            if time.time() - self._dashboard_last_tap > DASHBOARD_TIMEOUT:
                self._close_dashboard()
                break

    # ------------------------------------------------------------------
    # Button handling
    # ------------------------------------------------------------------

    def _on_button_press(self):
        """Button pressed."""
        self._press_time = time.time()
        self._held_long = False
        self._press_id += 1
        current_id = self._press_id

        # During recording, any press = stop
        if self._recording:
            self._play_feedback("click.wav")
            self._stop_recording()
            return

        # During dashboard, any press = next panel
        if self._dashboard_active:
            self._play_feedback("click.wav")
            self._next_dashboard_panel()
            return

        if self._busy:
            return

        self._play_feedback("click.wav")

        # Cancel any pending single-tap dispatch
        if self._dispatch_timer and self._dispatch_timer.is_alive():
            self._dispatch_timer.cancel()
            self._dispatch_timer = None

        # Hold detection — runs in background
        def _check_hold():
            time.sleep(BUTTON_HOLD_THRESHOLD)
            if current_id == self._press_id and not self._busy:
                self._held_long = True
                self._play_feedback("camera_beep.wav")
                self.ui.set_status("Release to capture")

        threading.Thread(target=_check_hold, daemon=True).start()

    def _on_button_release(self):
        """Button released — route to voice, camera, or dashboard."""
        if self._dashboard_active:
            return  # handled on press

        if self._busy or self._recording:
            return

        duration = time.time() - self._press_time
        if duration < 0.05:
            return

        # Long press = camera
        if self._held_long or duration > BUTTON_HOLD_THRESHOLD:
            self._tap_count = 0
            threading.Thread(target=self._camera_flow, daemon=True).start()
            return

        # Short tap — count it
        self._tap_count += 1

        if self._tap_count == 1:
            def _dispatch():
                if self._tap_count == 1 and not self._busy:
                    self._tap_count = 0
                    self._voice_flow()
                self._tap_count = 0

            self._dispatch_timer = threading.Timer(DOUBLE_TAP_WINDOW, _dispatch)
            self._dispatch_timer.daemon = True
            self._dispatch_timer.start()

        elif self._tap_count >= 2:
            # Double tap → dashboard
            self._tap_count = 0
            if self._dispatch_timer:
                self._dispatch_timer.cancel()
                self._dispatch_timer = None
            threading.Thread(target=self._open_dashboard, daemon=True).start()

    # ------------------------------------------------------------------
    # Voice flow
    # ------------------------------------------------------------------

    def _voice_flow(self):
        """Full voice pipeline: record → proxy → TTS → speaker."""
        if self._busy:
            return
        self._busy = True

        log("🎙 Voice flow started")
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
            self.ui.set_status("")
            self.ui.set_state(STATE_IDLE)
            self._busy = False
            return

        if not os.path.exists(audio_path) or os.path.getsize(audio_path) < 1000:
            log("Recording too short")
            self.ui.set_status("")
            self.ui.set_state(STATE_IDLE)
            self._busy = False
            return

        self.ui.set_status("Processing")
        self.ui.set_state(STATE_THINKING)
        log("🔄 Sending to proxy...")

        try:
            files = {"audio": ("voice.wav", open(audio_path, "rb"), "audio/wav")}
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

                log(f"📝 You: {transcription}")
                log(f"🤖 Molt: {response}")

                threading.Thread(target=self._send_telegram,
                    args=(f"🎙 You: {transcription}\n\n🤖 {response}",), daemon=True).start()

                self.ui.set_status("Speaking")
                self.ui.set_state(STATE_SPEAKING, response)

                if audio_b64:
                    self._play_audio_b64(audio_b64)
                else:
                    time.sleep(2)

                time.sleep(1)
                self.ui.response_text = ""
            else:
                log(f"❌ Proxy error: {r.status_code}")
                self.ui.set_state(STATE_ERROR, f"Error {r.status_code}")
                time.sleep(1)
        except Exception as e:
            log(f"❌ {e}")
            self.ui.set_state(STATE_ERROR, str(e)[:40])
            time.sleep(1)

        try:
            os.remove(audio_path)
        except Exception:
            pass

        self.ui.set_status("")
        self.ui.set_state(STATE_IDLE)
        self._busy = False

    # ------------------------------------------------------------------
    # Camera flow
    # ------------------------------------------------------------------

    def _camera_flow(self):
        """Camera pipeline: capture → show still → vision → TTS."""
        if self._busy:
            return
        self._busy = True

        log("📷 Camera flow started")
        self.ui.set_status("Capturing...")
        self.ui.set_state(STATE_CAMERA)
        self._play_feedback("click.wav")

        img_path = self._capture_photo()
        if not img_path:
            log("❌ Camera failed")
            self.ui.set_state(STATE_ERROR, "Camera failed")
            self._play_feedback("error.wav")
            time.sleep(2)
            self.ui.set_status("")
            self.ui.set_state(STATE_IDLE)
            self._busy = False
            return

        self.ui.show_captured_image(img_path)
        log("🔄 Sending to proxy for vision+TTS...")

        try:
            with open(img_path, "rb") as f:
                r = requests.post(f"{PROXY_URL}/vision_tts",
                    files={"image": ("snap.jpg", f, "image/jpeg")},
                    data={"prompt": "What do you see? Be concise and conversational."},
                    timeout=60)

            if r.status_code == 200:
                data = r.json()
                response = data.get("response", "No response")
                audio_b64 = data.get("audio")
                log(f"🤖 {response}")

                self.ui.set_photo_text(response)

                threading.Thread(target=self._send_telegram,
                    args=(f"📷 SiteEye\n\n🤖 {response}", img_path), daemon=True).start()

                if audio_b64:
                    self._play_audio_b64(audio_b64)
                else:
                    time.sleep(1)

                time.sleep(1.5)
            else:
                log(f"❌ Vision error: {r.status_code}")
                self.ui.set_photo_text(f"Error {r.status_code}")
                time.sleep(1)
        except Exception as e:
            log(f"❌ {e}")
            self.ui.set_photo_text(str(e)[:40])
            time.sleep(1)

        self.ui.clear_photo()

        try:
            os.remove(img_path)
        except Exception:
            pass

        self.ui.set_status("")
        self.ui.set_state(STATE_IDLE)
        self._busy = False

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _capture_photo(self):
        path = "/tmp/siteeye_snap.jpg"
        try:
            subprocess.run(
                ["rpicam-still", "-o", path, "--width", str(CAPTURE_WIDTH),
                 "--height", str(CAPTURE_HEIGHT), "--nopreview", "-t", "800",
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

    def _play_feedback(self, name):
        """Play a short audio feedback file (non-blocking)."""
        path = os.path.join(self._base_dir, "assets", name)
        if os.path.exists(path):
            threading.Thread(target=lambda: subprocess.run(
                ["aplay", "-D", AUDIO_DEV, path],
                capture_output=True, timeout=5
            ), daemon=True).start()

    # ------------------------------------------------------------------
    # Loops
    # ------------------------------------------------------------------

    def _display_loop(self):
        while self._running:
            frame_start = time.time()
            try:
                if not self._dashboard_active:
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
                elif cmd == "d":
                    threading.Thread(target=self._open_dashboard, daemon=True).start()
                elif cmd == "q":
                    self._running = False
                    break
                elif cmd == "s":
                    if self._recording:
                        self._stop_recording()
                    elif self._dashboard_active:
                        self._close_dashboard()
            except (EOFError, KeyboardInterrupt):
                self._running = False
                break

    # ------------------------------------------------------------------
    # Main entry
    # ------------------------------------------------------------------

    def run(self):
        log("══ SiteEye — Whisplay + IMX500 ══")
        log(f"Proxy: {PROXY_URL}")

        # Boot animation
        self.ui.set_state(STATE_BOOT)
        chime_played = False
        base_dir = os.path.dirname(os.path.abspath(__file__))
        for i in range(BOOT_FRAMES):
            frame_start = time.time()
            self.ui.render_frame()

            if i == 8 and not chime_played:
                chime_path = os.path.join(base_dir, "assets", "chime.wav")
                if os.path.exists(chime_path):
                    threading.Thread(target=lambda: subprocess.run(
                        ["aplay", "-D", AUDIO_DEV, chime_path],
                        capture_output=True, timeout=10
                    ), daemon=True).start()
                    chime_played = True

            elapsed = time.time() - frame_start
            if FRAME_INTERVAL - elapsed > 0:
                time.sleep(FRAME_INTERVAL - elapsed)

        # Health check
        try:
            r = requests.get(f"{PROXY_URL}/health", timeout=5)
            if r.status_code == 200:
                log("✅ Proxy connected")
                self.ui.set_status("Connected")
            else:
                log("⚠️ Proxy unhealthy")
                self.ui.set_status("Proxy error")
        except Exception:
            log("⚠️ Proxy unreachable")
            self.ui.set_status("Offline")

        self.ui.set_status("")
        self.ui.set_state(STATE_IDLE)

        # Startup audio
        startup_wav = os.path.join(base_dir, "assets", "startup.wav")
        if os.path.exists(startup_wav):
            try:
                subprocess.run(["aplay", "-D", AUDIO_DEV, startup_wav],
                               capture_output=True, timeout=10)
            except Exception:
                pass
        log("🔊 Startup audio played")

        # Start display loop
        display_thread = threading.Thread(target=self._display_loop, daemon=True)
        display_thread.start()

        log("\nControls:")
        log("  Button tap = voice | Button hold (>1s) = camera | Double-tap = dashboard")
        log("  Keyboard: v=voice  c=camera  d=dashboard  s=stop  q=quit\n")

        if sys.stdin.isatty():
            try:
                self._keyboard_loop()
            except Exception:
                pass
        else:
            log("Headless mode — button only")
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
