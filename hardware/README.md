# SiteEye Hardware — PCB Design

## Overview

Custom PCB to replace breadboard wiring. Eliminates signal integrity issues (SPI speed, I2S timing) and fits the badge-sized wearable form factor.

## Design Goals

1. **Badge form factor:** ~85×55mm, 2-layer PCB
2. **Pi Zero 2W** mounts via 2×20 GPIO header (removable) or castellated pads (permanent)
3. **All peripherals on-board:** OLED, mic, amp, buttons, speaker connector
4. **BLE 5.0 mesh-ready:** Unpopulated footprint for nRF52840 or ESP32-C3 module (future multi-device mesh networking for jobsites without cell service)
5. **PiSugar compatible:** Clearance underneath for PiSugar 3 battery board
6. **Camera:** CSI ribbon passthrough (not on PCB)

## Components

| Ref | Component | Package | Notes |
|-----|-----------|---------|-------|
| U1 | Raspberry Pi Zero 2W | 2×20 header | Host computer |
| U2 | INMP441 | Breakout board | I2S MEMS microphone |
| U3 | MAX98357A | Breakout board | I2S DAC/amplifier |
| U4 | SH1106 1.3" OLED | SPI breakout | Display |
| U5 | nRF52840 module | Castellated (future) | BLE 5.0 mesh radio — DNP v1 |
| SW1 | Tactile button | 6mm 4-pin | Voice trigger |
| SW2 | Tactile button | 6mm 4-pin | Camera trigger |
| LED1 | NeoPixel WS2812B | 5050 SMD | Status RGB LED |
| SP1 | PUI AS04004PO-2-R | Wire pads | 4Ω 3W speaker |
| J1 | CSI ribbon connector | 22-pin FPC | Camera passthrough |
| J2 | JST-PH 2-pin | Through-hole | Speaker connector |
| J3 | 2×20 GPIO header | 2.54mm pitch | Pi Zero mount |

## Net List

### Power Rails
| Net | Source | Destinations |
|-----|--------|-------------|
| 3V3 | Pi Pin 1 | OLED VCC, INMP441 VDD |
| 5V | Pi Pin 2 | MAX98357A VIN |
| GND | Pi Pin 6,9,14 | All components |

### I2S Audio Bus (shared)
| Net | Pi GPIO | Pin | Destinations |
|-----|---------|-----|-------------|
| I2S_BCLK | GPIO 18 | 12 | INMP441 SCK, MAX98357A BCLK |
| I2S_LRCLK | GPIO 19 | 35 | INMP441 WS, MAX98357A LRC |
| I2S_DIN | GPIO 20 | 38 | INMP441 SD (mic data) |
| I2S_DOUT | GPIO 21 | 40 | MAX98357A DIN (speaker data) |

### SPI Display
| Net | Pi GPIO | Pin | Destination |
|-----|---------|-----|------------|
| SPI_MOSI | GPIO 10 | 19 | OLED MOSI |
| SPI_CLK | GPIO 11 | 23 | OLED CLK |
| SPI_CS | GPIO 8 | 24 | OLED CS |
| OLED_DC | GPIO 24 | 18 | OLED DC |
| OLED_RST | GPIO 25 | 22 | OLED RES |

### GPIO
| Net | Pi GPIO | Pin | Destination |
|-----|---------|-----|------------|
| BTN_VOICE | GPIO 27 | 13 | SW1 (pull-up, active low) |
| BTN_CAMERA | GPIO 17 | 11 | SW2 (pull-up, active low) |
| NEOPIXEL | GPIO 16 | 36 | LED1 data in |

### INMP441 Config
| Pin | Connection |
|-----|-----------|
| L/R | GND (left channel select) |

### MAX98357A Config
| Pin | Connection |
|-----|-----------|
| GAIN | GND (24dB fixed gain) |
| SD | NC or pull-up (always on) |

### BLE Mesh Module (future, v2+)
| Net | Pi GPIO | Module Pin | Notes |
|-----|---------|-----------|-------|
| UART_TX | GPIO 14 | RXD | Serial command interface |
| UART_RX | GPIO 15 | TXD | Serial command interface |
| BLE_RST | GPIO 22 | RESET | Module reset |
| BLE_INT | GPIO 23 | IRQ | Interrupt line |
| 3V3 | — | VCC | Shared 3.3V rail |
| GND | — | GND | — |

## PCB Layout Notes

### Layer Stack
- **Top:** Components, signal traces
- **Bottom:** Ground plane, PiSugar clearance

### Placement
```
┌──────────────────────────────┐
│  [OLED]          [CAM ribbon]│
│                              │
│  [MIC]    [nRF52840 future]  │
│                              │
│  [SW1]  [SW2]  [NeoPixel]   │
│                              │
│  ════════════════════════════│ ← Pi Zero GPIO header
│  [MAX98357A]    [Speaker J2] │
└──────────────────────────────┘
        (bottom: PiSugar)
```

### Design Rules
- Trace width: 0.25mm signal, 0.5mm power
- Clearance: 0.2mm minimum
- Via size: 0.3mm drill, 0.6mm pad
- I2S traces: matched length, keep short
- SPI traces: keep under 50mm, ground guard
- Decoupling caps: 100nF on each VCC pin

## BOM (v1 — no mesh radio)

| Qty | Part | Est. Cost |
|-----|------|-----------|
| 1 | Custom PCB (5 pcs) | $5-15 |
| 1 | 2×20 female header | $1 |
| 2 | 6mm tactile button | $0.50 |
| 1 | WS2812B NeoPixel | $0.30 |
| 1 | JST-PH 2-pin connector | $0.20 |
| 4 | 100nF 0805 caps | $0.10 |
| — | **Total per board** | **~$7-17** |

(Breakout boards for INMP441, MAX98357A, OLED, Pi Zero purchased separately)

## Fabrication

Recommended fabs:
- **JLCPCB** — cheapest, 5 boards ~$5, PCBA available
- **PCBWay** — good quality, slightly more
- **OSH Park** — US-based, purple boards, ~$15 for 3

## Future: Bluetooth Mesh (v2+)

The nRF52840 footprint enables BLE 5.0 Mesh networking for multi-device jobsite communication without cell service. Architecture:

```
[SiteEye A] ←BLE Mesh→ [SiteEye B] ←BLE Mesh→ [SiteEye C]
     ↑                       ↑                       ↑
  Worker 1              Worker 2              Worker 3
                             ↓
                    [Gateway Node]
                         ↓
                   [Cloud/Server]
```

- Mesh relay: each device acts as a node, forwarding messages
- Range: ~100m outdoor per hop, multi-hop extends coverage
- Use cases: safety alerts, task coordination, voice relay, location tracking
- Protocol: Bluetooth Mesh (IEEE 802.15.1) or custom on BLE 5.0 advertising
