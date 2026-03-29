#!/usr/bin/env python3
"""SiteEye v2 — Pi Zero 2W + Whisplay HAT + IMX500

Full pipeline:
  - Button tap: voice recording → Whisper STT → Molt → TTS → speaker + LCD
  - Button hold (>1s): camera snap → GPT-4o vision → TTS → speaker + LCD
  - LCD shows neural mesh face + response text
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
CAPTURE_WIDTH = 640
CAPTURE_HEIGHT = 480
MAX_RECORD_SECONDS = 15
BUTTON_HOLD_THRESHOLD = 1.0  # seconds for camera mode

# Audio device
AUDIO_DEV = "plughw:0,0"
RECORD_FMT = "S16_LE"
RECORD_RATE = "16000"
RECORD_CHANNELS = "1"

# Display target FPS — 6fps is smooth enough for expressions, minimizes SPI load
TARGET_FPS = 6
FRAME_INTERVAL = 1.0 / TARGET_FPS


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
        self._busy = False  # prevent overlapping operations

        # Register button callbacks with WhisPlayBoard's built-in system
        # The board already owns GPIO in BOARD mode and has edge detection set up.
        self.board.button_press_callback = self._on_button_press
        self.board.button_release_callback = self._on_button_release
        log("Button registered via WhisPlayBoard callbacks")

        # Set volume
        try:
            subprocess.run(["amixer", "-D", "hw:wm8960soundcard", "sset", "Speaker", "90%"],
                           capture_output=True, timeout=5)
            subprocess.run(["amixer", "-D", "hw:wm8960soundcard", "sset", "Capture", "80%"],
                           capture_output=True, timeout=5)
        except:
            pass

    def _on_button_press(self):
        """Called by WhisPlayBoard when button is pressed (HIGH)."""
        self._press_time = time.time()

    def _on_button_release(self):
        """Called by WhisPlayBoard when button is released (LOW)."""
        if self._busy:
            if self._recording:
                self._stop_recording()
            return

        duration = time.time() - self._press_time
        if self._recording:
            self._stop_recording()
        elif duration > BUTTON_HOLD_THRESHOLD:
            threading.Thread(target=self._camera_flow, daemon=True).start()
        else:
            threading.Thread(target=self._voice_flow, daemon=True).start()

    def _voice_flow(self):
        """Full voice pipeline: record → proxy → TTS → speaker."""
        if self._busy:
            return
        self._busy = True

        log("🎙 Voice flow started")
        self.ui.set_state(STATE_LISTENING)

        audio_path = "/tmp/siteeye_voice.wav"
        try:
            # Start recording — set proc BEFORE setting _recording flag
            proc = subprocess.Popen(
                ["arecord", "-D", AUDIO_DEV, "-f", RECORD_FMT, "-r", RECORD_RATE,
                 "-c", RECORD_CHANNELS, "-d", str(MAX_RECORD_SECONDS), audio_path],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            self._record_proc = proc
            self._recording = True
            log("Recording... (press button to stop, or wait)")

            start = time.time()
            while self._recording and (time.time() - start) < MAX_RECORD_SECONDS:
                time.sleep(0.1)
                if proc.poll() is not None:
                    break

            self._stop_recording()
        except Exception as e:
            log(f"Record error: {e}")
            self.ui.set_state(STATE_ERROR, "Record failed")
            time.sleep(2)
            self.ui.set_state(STATE_IDLE)
            self._busy = False
            return

        if not os.path.exists(audio_path) or os.path.getsize(audio_path) < 1000:
            log("Recording too short")
            self.ui.set_state(STATE_IDLE)
            self._busy = False
            return

        # Capture background image for context
        img_path = self._capture_photo()

        self.ui.set_state(STATE_THINKING)
        log("🔄 Sending to proxy...")

        try:
            files = {"audio": ("voice.wav", open(audio_path, "rb"), "audio/wav")}
            if img_path:
                files["image"] = ("snap.jpg", open(img_path, "rb"), "image/jpeg")

            r = requests.post(f"{PROXY_URL}/voice_all", files=files, timeout=60)

            for f in files.values():
                try:
                    f[1].close()
                except:
                    pass

            if r.status_code == 200:
                data = r.json()
                transcription = data.get("transcription", "")
                response = data.get("response", "")
                audio_b64 = data.get("audio")

                log(f"📝 You: {transcription}")
                log(f"🤖 Molt: {response}")

                self.ui.set_state(STATE_SPEAKING, response)

                if audio_b64:
                    self._play_audio_b64(audio_b64)
                else:
                    time.sleep(2)

                # Keep text visible briefly, then clear
                time.sleep(3)
                self.ui.response_text = ""
            else:
                log(f"❌ Proxy error: {r.status_code}")
                self.ui.set_state(STATE_ERROR, f"Error {r.status_code}")
                time.sleep(2)
        except Exception as e:
            log(f"❌ {e}")
            self.ui.set_state(STATE_ERROR, str(e)[:40])
            time.sleep(2)

        for p in [audio_path, img_path]:
            try:
                if p:
                    os.remove(p)
            except:
                pass

        self.ui.set_state(STATE_IDLE)
        self._busy = False

    def _camera_flow(self):
        """Camera pipeline: snap → vision → TTS → speaker."""
        if self._busy:
            return
        self._busy = True

        log("📷 Camera flow started")
        self.ui.set_state(STATE_CAMERA)
        time.sleep(0.3)

        img_path = self._capture_photo()
        if not img_path:
            log("❌ Camera failed")
            self.ui.set_state(STATE_ERROR, "Camera failed")
            time.sleep(2)
            self.ui.set_state(STATE_IDLE)
            self._busy = False
            return

        self.ui.set_state(STATE_THINKING, "Analyzing image...")
        log("🔄 Sending to proxy for vision...")

        try:
            with open(img_path, "rb") as f:
                r = requests.post(f"{PROXY_URL}/vision",
                    files={"image": ("snap.jpg", f, "image/jpeg")},
                    data={"prompt": "What do you see? Be concise and conversational."},
                    timeout=60)

            if r.status_code == 200:
                data = r.json()
                response = data.get("response", "No response")
                log(f"🤖 {response}")
                self.ui.set_state(STATE_SPEAKING, response)

                # Use /voice_all with dummy silent audio to get TTS back
                # This is more reliable than /tts endpoint
                try:
                    # Create a minimal silent WAV for the proxy
                    import struct, io
                    silent = io.BytesIO()
                    # WAV header for 0.1s of silence at 16kHz mono S16_LE
                    n_samples = 1600
                    data_size = n_samples * 2
                    silent.write(b'RIFF')
                    silent.write(struct.pack('<I', 36 + data_size))
                    silent.write(b'WAVEfmt ')
                    silent.write(struct.pack('<IHHIIHH', 16, 1, 1, 16000, 32000, 2, 16))
                    silent.write(b'data')
                    silent.write(struct.pack('<I', data_size))
                    silent.write(b'\x00' * data_size)
                    silent.seek(0)

                    # Use /tts endpoint directly with response text
                    tts_r = requests.post(f"{PROXY_URL}/tts",
                        json={"text": response}, timeout=60)
                    if tts_r.status_code == 200:
                        tts_data = tts_r.json()
                        if tts_data.get("audio"):
                            self._play_audio_b64(tts_data["audio"])
                        else:
                            log("⚠️ TTS returned no audio")
                            time.sleep(3)
                    else:
                        log(f"⚠️ TTS error: {tts_r.status_code}")
                        time.sleep(3)
                except Exception as e:
                    log(f"⚠️ TTS failed: {e}")
                    time.sleep(3)

                # Keep text visible briefly, then clear
                time.sleep(3)
                self.ui.response_text = ""
            else:
                log(f"❌ Vision error: {r.status_code}")
                self.ui.set_state(STATE_ERROR, "Vision failed")
                time.sleep(2)
        except Exception as e:
            log(f"❌ {e}")
            self.ui.set_state(STATE_ERROR, str(e)[:40])
            time.sleep(2)

        try:
            os.remove(img_path)
        except:
            pass

        self.ui.set_state(STATE_IDLE)
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
            except:
                self._record_proc.kill()
        self._record_proc = None

    def _play_audio_b64(self, audio_b64):
        try:
            audio_bytes = base64.b64decode(audio_b64)
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
        """Background loop rendering LCD at controlled framerate."""
        while self._running:
            frame_start = time.time()
            try:
                self.ui.render_frame()
            except Exception as e:
                log(f"Display error: {e}")

            # Rate limit to TARGET_FPS
            elapsed = time.time() - frame_start
            sleep_time = FRAME_INTERVAL - elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)

    def _keyboard_loop(self):
        """Keyboard fallback for testing without button."""
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
        log("═══ SiteEye v2 — Whisplay + IMX500 ═══")
        log(f"Proxy: {PROXY_URL}")

        # Boot
        self.ui.set_state(STATE_BOOT)
        # Render boot animation frames
        for _ in range(35):
            frame_start = time.time()
            self.ui.render_frame()
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
        except:
            log("⚠️ Proxy unreachable")
            self.ui.set_status("Offline")

        self.ui.set_state(STATE_IDLE)

        # Start display loop
        display_thread = threading.Thread(target=self._display_loop, daemon=True)
        display_thread.start()

        log("\nControls:")
        log("  Button tap = voice | Button hold (>1s) = camera")
        log("  Keyboard: v=voice c=camera s=stop q=quit\n")

        try:
            self._keyboard_loop()
        except:
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
