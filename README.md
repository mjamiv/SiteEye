# SiteEye — Wearable AI Field Assistant

A wearable AI device that sees, hears, and speaks. Built on Raspberry Pi Zero 2W with LCD face, camera, mic, and speaker. Press a button to talk to your AI, hold it to analyze what you see.

Designed for construction jobsites — hands-free AI that clips to your vest.

<p align="center">
  <img src="build-photos/siteeye-front.jpg" width="380" alt="SiteEye — Front (LCD face + camera)">
  <img src="build-photos/siteeye-back.jpg" width="380" alt="SiteEye — Back (PiSugar battery + Pi Zero 2W)">
</p>

---

## Features

- **Voice AI** — Tap the button, ask anything. Whisper STT → AI → TTS through the speaker.
- **Camera Vision** — Hold the button, snap a photo. GPT-4o analyzes what you see and speaks the answer.
- **Animated LCD Face** — Cozmo-style eyes with blinks, saccades, and expressions. Reacts to state changes.
- **Info Dashboard** — Double-tap to cycle through BTC price, calendar, weather, and device stats.
- **Telegram Mirror** — Every interaction is mirrored to your phone via Telegram bot.

## Hardware

| Part | Component | Link | ~Price |
|------|-----------|------|--------|
| Computer | Raspberry Pi Zero 2W | [Amazon](https://www.amazon.com/dp/B0FWRPF4FV) | $24 |
| HAT | Whisplay HAT for Pi Zero | [Amazon](https://www.amazon.com/dp/B0FPG8S6K6) | $30 |
| Camera | Raspberry Pi AI Camera (IMX500) | [Amazon](https://www.amazon.com/dp/B0DJ8VFWKM) | $70 |
| Battery | PiSugar S Plus (1200mAh) | [Amazon](https://www.amazon.com/dp/B0FB3N1YSK) | $40 |
| Case | 3D printed | See `case-design/` | — |

**Total BOM: ~$164**

> **Note:** A standard [Pi Camera Module 3](https://www.amazon.com/dp/B0BRY6MVXL) (~$54) works as a drop-in replacement if you don't need on-device AI inference. All vision processing is cloud-based.

The Whisplay HAT provides the LCD display (1.69" IPS, 240×280, ST7789), WM8960 audio codec (dual MEMS mics + speaker amp), RGB LED, and a programmable button — all in one board.

## Architecture

```
┌──────────────────────┐     HTTPS      ┌──────────────────────┐
│  Pi Zero 2W          │ ◄────────────► │  Proxy Server (VPS)  │
│                      │                │                      │
│  main.py             │                │  server.py           │
│  ├─ Button input     │                │  ├─ /voice_all       │
│  ├─ Audio record     │  audio+image   │  │  ├─ Whisper STT   │
│  ├─ Camera capture   │ ──────────────►│  │  ├─ AI chat       │
│  ├─ LCD face         │                │  │  └─ TTS           │
│  └─ Speaker playback │◄──────────────│  ├─ /vision_tts      │
│                      │  text+audio    │  ├─ /dashboard       │
│  lcd_ui.py           │                │  └─ /health          │
│  └─ Animated eyes    │                │                      │
└──────────────────────┘                └──────────────────────┘
```

## Controls

| Action | Input | Result |
|--------|-------|--------|
| **Voice** | Tap button | Record → AI → Speak response |
| **Camera** | Hold button (>1s) | Snap → Vision analysis → Speak |
| **Dashboard** | Double-tap | Cycle: BTC → Calendar → Weather → Device |
| **Stop** | Tap during recording | Stop recording, send to AI |

## Setup

### 1. Pi Client

#### 1a. Install Whisplay HAT Driver

This installs the display, audio (WM8960), LED, and button drivers for the Whisplay HAT.

```bash
# Clone the Whisplay driver
git clone https://github.com/PiSugar/Whisplay.git --depth 1 ~/Whisplay

# Install the WM8960 audio codec driver (also enables I2S and I2C)
cd ~/Whisplay/Driver
sudo bash install_wm8960_drive.sh

# Reboot to load the audio driver
sudo reboot
```

After reboot, SSH back in (`ssh <username>@<hostname>.local`) and verify:

```bash
# Should show "wm8960soundcard"
aplay -l | grep wm8960
```

#### 1b. Install PiSugar Battery Manager

This enables battery level monitoring on the status bar and device dashboard.

```bash
curl https://cdn.pisugar.com/release/pisugar-power-manager.sh | sudo bash
```

Verify it's running:

```bash
# Should return something like "battery: 75.00"
echo "get battery" | nc -q 0 127.0.0.1 8423
```

#### 1c. Enable Camera and SPI

```bash
sudo raspi-config
```

Enable:
- **Interface Options → SPI** (for the LCD display)

> **Note:** On newer Raspberry Pi OS (Bookworm), the camera is enabled by default and may not appear in raspi-config. You can verify later with `rpicam-still -o test.jpg`.

```bash
sudo reboot
```

#### 1d. Install SiteEye

SSH back in after reboot:

```bash
# Install SiteEye dependencies
sudo apt install -y python3-numpy python3-pil

# Clone SiteEye
git clone https://github.com/mjamiv/SiteEye.git ~/siteeye
cd ~/siteeye

# Create virtual environment and install Python packages
python3 -m venv --system-site-packages venv
source venv/bin/activate
pip install requests

# Configure environment
cp .env.example ~/.env
nano ~/.env  # Fill in SITEEYE_PROXY, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

# Install service — creates a background process that runs SiteEye
# automatically every time the Pi powers on. After this, you don't
# need to manually start SiteEye — just turn on the Pi and it runs.
chmod +x setup-service.sh
./setup-service.sh
```

### 2. Proxy Server

The proxy server handles all AI processing (STT, chat, TTS, vision). You can run it on a VPS or on your laptop — the Pi just needs to reach it over the network.

#### Option A: Run on your laptop (easiest to get started)

Your laptop and the Pi must be on the same network (e.g., both on your phone's hotspot).

**1. Find your laptop's IP address:**

**Mac:**
```bash
ipconfig getifaddr en0
```

**Windows:**
```
ipconfig | findstr "IPv4"
```

Write down the IP (e.g., `172.20.10.2`).

**2. Install dependencies and run the server:**

```bash
cd ~/siteeye  # or wherever you cloned the repo

# Install dependencies
pip install flask openai requests

# Copy the example config and fill in your OpenAI API key
cp .env.server.example .env
nano .env

# Load the config and start the server
set -a && source .env && set +a
python server.py
```

> **Tip:** If you get `ModuleNotFoundError`, try `python server.py` instead of `python3 server.py` (or vice versa). Use whichever Python has your packages installed — check with `python -c "import flask"` or `python3 -c "import flask"`.

The server runs on port 5757. Leave this terminal open — the server must stay running.

**3. Point the Pi to your laptop:**

SSH into the Pi (`ssh <username>@<hostname>.local`) and edit the `.env` file:

```bash
nano ~/.env
```

Set `SITEEYE_PROXY` to your laptop's IP:

```
SITEEYE_PROXY=http://172.20.10.2:5757
```

Then restart the service:

```bash
sudo systemctl restart siteeye
```

> **Note:** Your laptop's IP may change each time you reconnect to the hotspot. If SiteEye stops working, check your IP and update the Pi's `.env` if it changed.

#### Option B: Run on a VPS (always-on, no laptop needed)

```bash
# On your VPS
cd server/
pip install flask openai requests

# Configure
cp .env.server.example .env
nano .env  # Fill in OPENAI_API_KEY, OPENCLAW_URL, OPENCLAW_TOKEN

# Run
python3 server.py
```

Set `SITEEYE_PROXY` on the Pi to your VPS URL (e.g., `https://your-server.com:5757`).

### Environment Variables

**Pi Client** (`.env`):
| Variable | Required | Description |
|----------|----------|-------------|
| `SITEEYE_PROXY` | Yes | URL of your proxy server (laptop IP or VPS URL) |
| `TELEGRAM_BOT_TOKEN` | No | Telegram bot token for mirroring |
| `TELEGRAM_CHAT_ID` | No | Telegram chat ID to mirror to |

**Proxy Server** (`.env` or environment):
| Variable | Required | Description |
|----------|----------|-------------|
| `OPENAI_API_KEY` | Yes | OpenAI API key (Whisper STT + TTS + GPT-4o vision) |
| `OPENCLAW_URL` | No | OpenClaw gateway URL for AI chat |
| `OPENCLAW_TOKEN` | No | OpenClaw auth token |

## LCD States

The animated face reflects device state:

- **Idle** — Relaxed eyes with random blinks and saccades
- **Listening** — Wide eyes, raised brows, audio level bars
- **Thinking** — Squinted eyes looking up, animated dots
- **Speaking** — Relaxed eyes, mouth animation, waveform pulse
- **Camera** — Viewfinder overlay with crosshair
- **Dashboard** — Info panels with page indicator dots

## Project Structure

```
├── RPI_SETUP.md         # Pi setup guide — from blank SD card to SSH
├── main.py              # Pi client — button handling, voice/camera flows
├── lcd_ui.py            # LCD display — animated face, dashboard panels
├── server.py            # Proxy server — STT, AI, TTS, vision, dashboard API
├── siteeye.service      # systemd service file
├── setup-service.sh     # Service installer
├── .env.example         # Pi environment template
├── .env.server.example  # Server environment template
├── assets/              # Audio feedback files (chime, click, etc.)
├── hardware/            # Wiring diagrams and pin references
├── case-design/         # 3D printable case files
├── build-photos/        # Build documentation photos
└── archive/             # Previous versions (v1-v7, OLED, etc.)
```

## Build Photos

See `build-photos/` for the full build journey.

## License

MIT

## Credits

Built by [Michael Martello](https://github.com/mjamiv) and [Molt](https://github.com/mjamiv/SiteEye) — a bridge engineer and his AI, proving that a single engineer with a laptop can build anything.
