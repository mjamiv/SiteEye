#!/usr/bin/env python3
"""SiteEye v2 — Pi Zero 2W + Whisplay HAT + IMX500

Full pipeline:
  - Button tap: voice recording → Whisper STT → Molt → TTS → speaker + LCD
  - Button hold (>1s): camera snap → GPT-4o vision → TTS → speaker + LCD
  - LCD shows Cozmo-style animated eyes + response text
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

sys.path.insert(0, '/home/pi-molt/Whisplay/Driver')
from WhisPlay import WhisPlayBoard

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
        self._button_handled = False

        # Set up button callback
        try:
            import RPi.GPIO as GPIO
            GPIO.setmode(GPIO.BCM)
            GPIO.setup(17, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)
            GPIO.add_event_detect(17, GPIO.BOTH, callback=self._button_event, bouncetime=50)
            log("Button on GPIO 17 ready")
        except Exception as e:
            log(f"Button setup failed: {e} — keyboard fallback active")

        # Set volume
        try:
            subprocess.run(["amixer", "-D", "hw:wm8960soundcard", "sset", "Speaker", "90%"],
                           capture_output=True, timeout=5)
            subprocess.run(["amixer", "-D", "hw:wm8960soundcard", "sset", "Capture", "80%"],
                           capture_output=True, timeout=5)
        except:
            pass

    def _button_event(self, channel):
        """GPIO button callback — rising edge = press, falling = release."""
        import RPi.GPIO as GPIO
        if GPIO.input(17):  # Button pressed (HIGH)
            self._press_time = time.time()
            self._button_handled = False
        else:  # Button released (LOW)
            if self._button_handled:
                return
            self._button_handled = True
            duration = time.time() - self._press_time
            if self._recording:
                # Stop recording
                self._stop_recording()
            elif duration > BUTTON_HOLD_THRESHOLD:
                # Long press — camera
                threading.Thread(target=self._camera_flow, daemon=True).start()
            else:
                # Short press — start voice recording
                threading.Thread(target=self._voice_flow, daemon=True).start()

    def _voice_flow(self):
        """Full voice pipeline: record → proxy → TTS → speaker."""
        log("🎙 Voice flow started")
        self.ui.set_state(STATE_LISTENING)

        # Record audio
        audio_path = "/tmp/siteeye_voice.wav"
        try:
            self._recording = True
            self._record_proc = subprocess.Popen(
                ["arecord", "-D", AUDIO_DEV, "-f", RECORD_FMT, "-r", RECORD_RATE,
                 "-c", RECORD_CHANNELS, "-d", str(MAX_RECORD_SECONDS), audio_path],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            log("Recording... (press button or wait)")

            # Wait for button press to stop, or timeout
            start = time.time()
            while self._recording and (time.time() - start) < MAX_RECORD_SECONDS:
                time.sleep(0.1)
                if self._record_proc.poll() is not None:
                    break

            self._stop_recording()
        except Exception as e:
            log(f"Record error: {e}")
            self.ui.set_state(STATE_ERROR, "Record failed")
            time.sleep(2)
            self.ui.set_state(STATE_IDLE)
            return

        if not os.path.exists(audio_path) or os.path.getsize(audio_path) < 1000:
            log("Recording too short")
            self.ui.set_state(STATE_IDLE)
            return

        # Also capture image for context (sent but only used if vision triggered)
        img_path = self._capture_photo()

        # Send to proxy
        self.ui.set_state(STATE_THINKING)
        log("🔄 Sending to proxy...")

        try:
            files = {"audio": ("voice.wav", open(audio_path, "rb"), "audio/wav")}
            if img_path:
                files["image"] = ("snap.jpg", open(img_path, "rb"), "image/jpeg")

            r = requests.post(f"{PROXY_URL}/voice_all", files=files, timeout=60)

            # Close file handles
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

                # Show response on LCD
                self.ui.set_state(STATE_SPEAKING, response)

                # Play TTS audio
                if audio_b64:
                    self._play_audio_b64(audio_b64)
                else:
                    time.sleep(2)
            else:
                log(f"❌ Proxy error: {r.status_code}")
                self.ui.set_state(STATE_ERROR, f"Error {r.status_code}")
                time.sleep(2)
        except Exception as e:
            log(f"❌ {e}")
            self.ui.set_state(STATE_ERROR, str(e)[:40])
            time.sleep(2)

        # Clean up
        for p in [audio_path, img_path]:
            try:
                if p:
                    os.remove(p)
            except:
                pass

        self.ui.set_state(STATE_IDLE)

    def _camera_flow(self):
        """Camera pipeline: snap → vision → TTS → speaker."""
        log("📷 Camera flow started")
        self.ui.set_state(STATE_CAMERA)
        time.sleep(0.3)  # Brief flash

        img_path = self._capture_photo()
        if not img_path:
            log("❌ Camera failed")
            self.ui.set_state(STATE_ERROR, "Camera failed")
            time.sleep(2)
            self.ui.set_state(STATE_IDLE)
            return

        self.ui.set_state(STATE_THINKING)
        log("🔄 Sending to proxy for vision...")

        try:
            with open(img_path, "rb") as f:
                r = requests.post(f"{PROXY_URL}/vision",
                    files={"image": ("snap.jpg", f, "image/jpeg")},
                    data={"prompt": "What do you see? Be concise."},
                    timeout=60)

            if r.status_code == 200:
                data = r.json()
                response = data.get("response", "No response")
                log(f"🤖 {response}")
                self.ui.set_state(STATE_SPEAKING, response)

                # Get TTS for the response
                try:
                    tts_r = requests.post(f"{PROXY_URL}/tts",
                        json={"text": response}, timeout=30)
                    if tts_r.status_code == 200:
                        tts_data = tts_r.json()
                        if tts_data.get("audio"):
                            self._play_audio_b64(tts_data["audio"])
                        else:
                            time.sleep(3)
                    else:
                        time.sleep(3)
                except:
                    time.sleep(3)
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

    def _capture_photo(self):
        """Capture photo from IMX500."""
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
        """Stop the recording process."""
        self._recording = False
        if self._record_proc and self._record_proc.poll() is None:
            self._record_proc.terminate()
            try:
                self._record_proc.wait(timeout=2)
            except:
                self._record_proc.kill()
        self._record_proc = None

    def _play_audio_b64(self, audio_b64):
        """Decode base64 WAV and play through speaker."""
        try:
            audio_bytes = base64.b64decode(audio_b64)
            tmp_path = "/tmp/siteeye_tts.wav"
            with open(tmp_path, "wb") as f:
                f.write(audio_bytes)

            # Convert to playable format and play
            subprocess.run(
                ["aplay", "-D", AUDIO_DEV, tmp_path],
                capture_output=True, timeout=30
            )
            os.remove(tmp_path)
        except Exception as e:
            log(f"Playback error: {e}")

    def _display_loop(self):
        """Background loop rendering LCD frames."""
        while self._running:
            try:
                self.ui.render_frame()
                time.sleep(0.08)  # ~12 FPS
            except Exception as e:
                log(f"Display error: {e}")
                time.sleep(0.5)

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
                    # Stop recording
                    self._stop_recording()
            except (EOFError, KeyboardInterrupt):
                self._running = False
                break

    def run(self):
        """Main entry point."""
        log("═══ SiteEye v2 — Whisplay + IMX500 ═══")
        log(f"Proxy: {PROXY_URL}")

        # Boot animation
        self.ui.set_state(STATE_BOOT)
        self.ui.render_frame()
        time.sleep(1.5)

        # Check proxy
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
        log("  Button tap = voice | Button hold = camera")
        log("  Keyboard: v=voice c=camera s=stop q=quit")
        log("")

        # Keyboard fallback in main thread
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
