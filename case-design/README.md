# SiteEye Case Design — 3D Printed Wearable Enclosure

**v6 design** — Full redesign per 13-point review, March 17, 2026

---

## Form Factor

**Badge-sized wearable lanyard** — think of it as a smarter ID badge.

| Dimension | Value |
|-----------|-------|
| Width | 58mm |
| Height | 82mm |
| Assembled Depth | 34mm (front shell 16mm + back shell 18mm) |
| Corner Radius | 4mm fillets |
| Wall Thickness | 2mm |
| Estimated Weight | ~85g assembled |

Portrait orientation, worn on a lanyard at chest level. Camera faces forward (toward what you're looking at). OLED faces you (readable by glancing down). Matches the badge convention — at home on a construction jobsite.

---

## Two-Piece Snap-Fit Design

The enclosure splits into **front shell** and **back shell**, joined by snap-fit clips at all four corners. Optional M2 screws for ruggedized/job-site use.

```
FRONT SHELL (camera side)           BACK SHELL (OLED side)
┌─────────────────────┐             ┌─────────────────────┐
│  ○  lanyard loop    │             │  ○  lanyard loop    │
│                     │             │                     │
│   ░░░░░ speaker     │             │  ┌───────────────┐  │
│   ░░░░░ vents       │             │  │  1.3" OLED    │  │
│                     │             │  │  128 × 64     │  │
│    ┌───┐  camera    │             │  └───────────────┘  │
│    │ ◉ │  lens      │             │                     │
│    └───┘            │             │  [BTN1]    [BTN2]   │
│                     │             │                     │
│  "Site Eye"         │             │                     │
│  "Prototype v1"     │             │                     │
│                     │             │                     │
│   ◎  mic vent       │             │                     │
│                     │             │                     │
└────────┬────────────┘             └─────────────────────┘
         │
    micro-USB (bottom)
```

**Print orientation:** Each shell face-down (outer face on build plate). Best surface finish on the visible face, snap-fit clips print vertically for maximum strength.

---

## Component Mounting

| Component | Location | Mounting Method |
|-----------|----------|-----------------|
| Pi Zero 2W | Back shell interior | M2.5 standoffs, 23×58mm c-c pattern |
| IMX500 AI Camera | Front shell (forward-facing) | Camera cradle, 8mm lens opening with bezel |
| 1.3" OLED (SH1106) | Back shell (user-facing) | 4-post mount, 30mm c-c, 3mm screw holes |
| Speaker (4Ω 3W oval) | Front shell | 36mm speaker cradle behind vent slots |
| MEMS Microphone (INMP441) | Front shell top | 14mm mic cradle behind vent hole |
| PiSugar 3 LiPo battery | Back shell, between Pi and back wall | Snap-in, accessible from bottom |
| Tactile buttons (×2) | Back shell, below OLED | Cutouts for right-thumb access |

**CSI ribbon cable** routes through internal channel from camera (front) to Pi (back), with 180° fold.

---

## v6 Design — 13-Point Redesign

Version 6 is a full redesign addressing 13 issues from prototype review (March 17, 2026):

1. **Labels mirrored** — correct exterior reading (right-reading when printed face-down)
2. **Labels on camera (front) side** — smaller font, cleaner look
3. **Camera moved down ~19mm** — better FOV from chest-level position
4. **OLED mounts corrected** — 30mm c-c, 3mm holes, 35.5×33.5mm module, 34×18.5mm screen window
5. **Assembled depth 34mm** — 16mm front + 18mm back = 30mm+ internal clearance for all components
6. **Front mic opening added** — dedicated vent hole for INMP441 microphone
7. **Side micro-USB slot** — 10mm deep × 20mm wide, 15mm from top, for power access
8. **Bottom opening** — single centered hole for micro-USB access (cleaner than per-shell holes)
9. **36mm speaker cradle** — behind front vent slots, sized for PUI Audio AS04004PO-2-R
10. **14mm mic cradle** — behind front mic opening, holds INMP441 in position
11. **Single inset lanyard loop** — at top center (replaces dual lanyard holes, stronger)
12. **Pi Zero 2W screw holes** — 23×58mm c-c, centered on back plate
13. **Tactile button cutouts** — on back shell below OLED (replaced removed back vents)

---

## Files

### OpenSCAD Source
| File | Description |
|------|-------------|
| `molt-case.scad` | Main parametric model (v6, all components) |
| `export-front.scad` | Front shell export (with text labels) |
| `export-front-notext.scad` | Front shell export (no text, cleaner) |
| `export-back.scad` | Back shell export |
| `render-preview.scad` | Assembled preview render |

### STL Exports
| File | Description |
|------|-------------|
| `molt-case-front-v6.stl` | **Current** — front shell with labels |
| `molt-case-front-v6-notext.stl` | **Current** — front shell, no text |
| `molt-case-back-v6.stl` | **Current** — back shell |
| `molt-case-front-v5.stl` | v5 front (reference) |
| `molt-case-front-v4-siteeye.stl` | v4 front with SiteEye branding |
| `molt-case-back-v4.stl` | v4 back (reference) |

### Visualization
| File | Description |
|------|-------------|
| `front-preview-siteeye.png` | Rendered preview of front shell |

---

## Printing Instructions

### Recommended Settings

| Parameter | Value |
|-----------|-------|
| **Material** | PETG (black) — preferred for heat/impact resistance |
| **Alternative** | PLA — faster iteration during development |
| **Layer Height** | 0.2mm |
| **Wall Perimeters** | 3 (strength for snap-fits) |
| **Infill** | 15-20% gyroid or honeycomb |
| **Print Temperature** | 230°C (PETG) / 215°C (PLA) |
| **Bed Temperature** | 70°C (PETG) / 60°C (PLA) |
| **Supports** | Minimal — button cutouts may need minimal support |
| **Orientation** | Face-down on bed (outer surface = best finish) |

### Time & Material
- Front shell: ~2.5 hrs, ~12g
- Back shell: ~2 hrs, ~10g
- Total filament: ~22g per enclosure (~$1.10 in PETG)

---

## Assembly Guide

### Tools Needed
- M2.5 × 6mm standoffs (4×)
- M2.5 × 4mm screws (8×)
- M2 × 6mm screws (2×, optional — for snap-fit reinforcement)
- Tweezers for ribbon cable routing
- Thin double-sided tape for wire management

### Step-by-Step

1. **Install Pi standoffs** — Thread 4× M2.5 standoffs into back shell mounting holes (23×58mm pattern, centered)

2. **Mount Pi Zero 2W** — Seat on standoffs, screw with M2.5 × 4mm screws. Leave GPIO header accessible.

3. **Route CSI ribbon** — Thread camera ribbon cable through the internal channel. Leave slack for 180° fold.

4. **Install OLED** — Seat into 4-post mount on back shell. Ribbon or wire down to Pi GPIO (SPI: pins 8, 10, 11, 24, 25).

5. **Install buttons** — Press tactile switches into button cutouts on back shell. Wire to Pi GPIO 17 (camera) and GPIO 27 (voice).

6. **Install microphone** — Seat INMP441 into 14mm mic cradle behind front shell mic vent. Route wires through interior.

7. **Install speaker** — Seat speaker into 36mm front-shell cradle behind vent slots. Connect to MAX98357A amp.

8. **Attach PiSugar battery** — Connect to Pi Zero 2W (attaches underneath Pi). Add last — interferes with debugging.

9. **Connect camera** — Attach IMX500 AI Camera to Pi CSI port via ribbon. Seat camera in front-shell lens pocket.

10. **Snap shells together** — Align front and back shell, press at all four corners until clips engage.

11. **Thread lanyard** — Route through top inset loop, attach breakaway clasp.

> ⚠️ **Add PiSugar last.** The battery module physically blocks GPIO access once installed.

---

## Version History

| Version | Date | Key Changes |
|---------|------|-------------|
| v1/v2 | Feb 2026 | Initial concept — badge form factor proof |
| v3 | Mar 2026 | First printable model |
| v4 | Mar 2026 | SiteEye branding, camera bezel |
| v5 | Mar 2026 | OLED mount fixes, button placement |
| **v6** | **Mar 17, 2026** | **13-point redesign — current version** |

---

## Design Rationale

| Decision | Choice | Why |
|----------|--------|-----|
| Orientation | Portrait (vertical) | Matches badge convention, natural chest hang |
| Camera side | Front shell (forward-facing) | Captures user's perspective |
| OLED side | Back shell (user-facing) | Readable by glancing down |
| Buttons | Back shell, below OLED | Right-thumb access while hanging |
| Assembly | Snap-fit + optional screws | Fast iteration + job-site durability |
| Material | PETG (black) | Heat/impact resistant, professional look |
| Cooling | Passive vents only | Pi Zero 2W thermals manageable without fan |
| Lanyard | Single loop (breakaway) | Safety-critical for construction sites |
| Depth | 34mm assembled | Accommodates all components including PiSugar |
| Labels | Camera (front) side only | Clean OLED side, branded front |

---

*Designed by Molt AI for Michael Martello. Living document — updates with each revision.*
