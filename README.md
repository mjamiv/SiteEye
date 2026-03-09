# SiteEye v0.1-beta

*AI-powered wearable for construction sites. Voice + vision in a badge-sized form factor.*

---

## What Is It

A wearable AI device built on a Raspberry Pi Zero 2W with camera, mic, speaker, and OLED display. Press a button to talk, press another to snap a photo. It sees what you see and talks back.

Designed for construction jobsites — hands-free AI that clips to your vest.

---

## Hardware

### Core
| Part | Model | Notes |
|------|-------|-------|
| Computer | Raspberry Pi Zero 2W | 64-bit, WiFi, BT |
| Camera | Sony IMX500 AI Camera | On-chip neural net, CSI ribbon |
| Display | Inland 1.3" OLED (SH1106) | SPI mode, IIC/SPI jumper board |
| Microphone | INMP441 I2S MEMS | Digital mic, low output (needs +25dB gain) |
| Amplifier | MAX98357A I2S DAC/Amp | 3W class D, GAIN→GND for 24dB |
| Speaker | PUI Audio AS04004PO-2-R | 4Ω 3W oval |
| Battery | PiSugar 3 + 1200mAh LiPo | Portable power |
| Buttons | Tactile push buttons (×2) | Voice + Camera triggers |

### Form Factor
- Wearable lanyard, badge-sized (~85×55×15-20mm)
- Camera forward, speaker outward, mic hole top
- OLED for glanceable status (animated eyes)

---

## Pin Map

| Pi Pin | GPIO | Device | Function |
|--------|------|--------|----------|
| 1 | 3.3V | OLED | VCC |
| 2 | 5V | MAX98357A | VIN |
| 6 | GND | OLED | GND |
| 9 | GND | INMP441 | GND + L/R (both to GND) |
| 11 | GPIO 17 | Button 2 | Camera |
| 12 | GPIO 18 | INMP441 + MAX | SCK / BCLK (shared) |
| 13 | GPIO 27 | Button 1 | Voice |
| 14 | GND | MAX98357A | GND |
| 17 | 3.3V | INMP441 | VDD |
| 18 | GPIO 24 | OLED | DC |
| 19 | GPIO 10 | OLED | MOSI |
| 22 | GPIO 25 | OLED | RES |
| 23 | GPIO 11 | OLED | CLK |
| 24 | GPIO 8 | OLED | CS |
| 35 | GPIO 19 | INMP441 + MAX | WS / LRC (shared) |
| 38 | GPIO 20 | INMP441 | SD (data in) |
| 40 | GPIO 21 | MAX98357A | DIN (data out) |

### Reserved (future)
| Pi Pin | GPIO | Purpose |
|--------|------|---------|
| 36 | GPIO 16 | NeoPixel RGB LED |

---

## Software Stack

### OS
- Raspberry Pi OS Lite (64-bit, Bookworm)

### /boot/firmware/config.txt additions
```
dtparam=spi=on
dtparam=i2s=on
dtoverlay=googlevoicehat-soundcard
```

### Dependencies
```bash
sudo apt install -y python3-pip python3-pil python3-spidev sox libsox-fmt-all
pip3 install luma.oled gpiozero
```

### Audio Config

**~/.asoundrc** (and /etc/asound.conf):
```
pcm.speaker {
    type dmix
    ipc_key 1024
    slave {
        pcm "hw:1,0"
        rate 48000
        channels 2
        format S32_LE
    }
}
```

**Amp keepalive service** (eliminates click on play):
```ini
# /etc/systemd/system/amp-keepalive.service
[Unit]
Description=Keep I2S amp alive (no click)
After=sound.target
[Service]
ExecStart=/etc/systemd/system/amp-keepalive.sh
Restart=always
[Install]
WantedBy=multi-user.target
```

---

## Architecture

```
┌─────────────┐     ┌──────────────┐     ┌──────────────┐
│   SiteEye   │────▶│  VPS Proxy   │────▶│  AI Backend  │
│  (Pi Zero)  │◀────│  :5757       │◀────│              │
└─────────────┘     └──────────────┘     └──────────────┘
      │                    │
      │                    ├──▶ Whisper (STT)
      ├──▶ TTS Engine      ├──▶ GPT-4o (Vision)
      ├──▶ Telegram Bot     └──▶ Sonnet (Chat)
      └──▶ OLED Display
```

### Voice Flow
1. Press Voice button → eyes go wide ("listening")
2. Record I2S mic (S32_LE, 48kHz, stereo)
3. Press again → stop recording
4. Sox boost +25dB, convert to 16kHz mono → Whisper STT
5. Eyes squint ("thinking") → Proxy `/chat` → AI response
6. Response on OLED → TTS → sox EQ → speaker
7. Eyes return to idle animation

### Camera Flow
1. Press Camera button → eyes look up ("capturing")
2. rpicam-still 640×480 with vflip/hflip
3. Photo sent to Telegram via bot API
4. Eyes squint ("thinking") → Proxy `/vision` → GPT-4o analysis
5. Response on OLED → TTS → speaker
6. Eyes return to idle

### Audio EQ
```
bass +6 | treble -7 3000 | lowpass 8000
```
De-esses sibilance, adds warmth. Tuned for small speaker output.

---

## Key Files

| File | Purpose |
|------|---------|
| `main.py` | Device client |
| `oled_ui.py` | OLED animated eyes display |
| `server.py` | VPS proxy server |

---

## Known Issues & TODO
- [ ] NeoPixel LED not purchased/wired
- [ ] Auto-start systemd service for main.py
- [ ] OLED sometimes needs `sudo killall python3` before restart (GPIO not released)
- [ ] Custom enclosure design pending

---

## Lessons Learned
1. **SPI speed matters on breadboard.** Default 8MHz fails — 500kHz works reliably with jumper wires.
2. **Process exit resets OLED.** luma.oled cleans up GPIO on exit — display goes blank. Keep process alive.
3. **INMP441 records low.** Always boost +20-25dB with sox before sending to STT.
4. **I2S format must match exactly.** 48kHz stereo S32_LE for both record and playback.
5. **Breadboard rows can be unreliable.** DIN wire worked direct but not through breadboard.
6. **Amp keepalive eliminates click.** dmix + silent background stream prevents power cycle pop.
7. **Buttons wire across, not along.** Same-side legs are always connected — wire to opposite legs.
8. **Kill all python3 before restarting.** GPIO won't allocate if previous process still holds pins.
9. **De-ess small speakers.** treble -7 @3kHz + lowpass 8kHz tames sibilance without killing clarity.

---

## License

MIT
