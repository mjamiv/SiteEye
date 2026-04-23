# Raspberry Pi Setup — From Blank SD Card to SSH

This guide covers setting up a Raspberry Pi Zero 2W from scratch using your phone's personal hotspot. Each Pi is tied to a specific phone's hotspot name and password. The Pi connects automatically whenever the hotspot is on — no site WiFi needed.

## What You Need

- Raspberry Pi Zero 2W
- Micro SD card (16GB+)
- SD card adapter for your computer
- PiSugar S Plus battery (or USB power)
- iPhone (or Android) with personal hotspot
- Computer with [Raspberry Pi Imager](https://www.raspberrypi.com/software/) installed (Mac or Windows)

## Step 0: Find Your iPhone Hotspot Name and Password

The Pi will connect to your phone's hotspot, so you need the exact name and password.

### Find your hotspot name

Your hotspot name is your iPhone's name:

1. Open **Settings → General → About → Name**
2. Write it down exactly (spaces and capitalization matter)

> **Tip:** iPhone names often include special characters like apostrophes (e.g., "John's iPhone"). To avoid issues, rename your phone to something simple like `JohnSiteEye`. Go to **Settings → General → About → Name** to change it.

### Find your hotspot password

1. Open **Settings → Personal Hotspot**
2. Your WiFi password is shown on that screen
3. Write it down exactly

### Turn on the hotspot

1. **Settings → Personal Hotspot → Allow Others to Join** → On
2. **Maximize Compatibility** → On (this forces 2.4GHz, which the Pi requires)

> **IMPORTANT — Changing your hotspot password or phone name:** If you change your iPhone hotspot password or phone name after the Pi is set up, the Pi will no longer be able to connect. See [Fixing WiFi After a Hotspot Change](#fixing-wifi-after-a-hotspot-change) below — you do NOT need to re-flash.

> **IMPORTANT — 2.4GHz required:** The Pi Zero 2W only supports 2.4GHz WiFi. "Maximize Compatibility" must be ON in your hotspot settings, otherwise the Pi cannot connect.

### Android

1. Open **Settings → Network → Hotspot & tethering → Wi-Fi hotspot**
2. Note the **Network name** and **Password**
3. Set the **band** to 2.4GHz if the option is available

---

## Step 1: Flash the SD Card

### Mac

1. Insert SD card into your Mac via adapter
2. Open **Raspberry Pi Imager**
3. **Device** → Raspberry Pi Zero 2W
4. **OS** → Raspberry Pi OS (other) → **Raspberry Pi OS Lite (32-bit)**
5. **Storage** → select your SD card
6. Click **Next**, then **Edit Settings** when prompted

### Windows

1. Insert SD card into your PC via adapter
2. Open **Raspberry Pi Imager** (install from [raspberrypi.com/software](https://www.raspberrypi.com/software/) if needed)
3. **Device** → Raspberry Pi Zero 2W
4. **OS** → Raspberry Pi OS (other) → **Raspberry Pi OS Lite (32-bit)**
5. **Storage** → select your SD card (be careful to pick the right drive)
6. Click **Next**, then **Edit Settings** when prompted

### OS Customization Settings (Mac and Windows)

**General tab:**

| Setting | Value | What is it? |
|---------|-------|--------------|
| Hostname | `pi-molt` | The name of the Pi on the network — this is how you find it (e.g., `pi-molt.local`). If setting up multiple devices, use unique names like `pi-molt-01`, `pi-molt-02`, etc. |
| Timezone / City | your capital city | Pick your city — this sets the timezone AND the WiFi country code. The Pi's WiFi radio won't work without a valid country. |
| Username | your choice | The login account on the Pi. This will be your SSH login name. |
| Password | your choice | The password you'll type every time you SSH in. Pick something you'll remember. |
| WiFi SSID | your phone's hotspot name (from Step 0) |
| WiFi Password | your phone's hotspot password (from Step 0) |

**Services tab:**

| Setting | Value |
|---------|-------|
| Enable SSH | Yes |
| Authentication | Password |

Then:

7. Click **Save**, then **Write**
8. Wait for flash + verification to complete
9. Eject the SD card

> **Note:** The hostname you set here determines the `.local` address. If you set `pi-molt`, you'll SSH to `pi-molt@pi-molt.local` (not `raspberrypi.local`).

---

## Step 2: First Boot

1. Make sure your phone's hotspot is **on** with **Maximize Compatibility** enabled
2. **Connect your computer to the same phone hotspot** — on Mac, click the WiFi icon in the menu bar, find your phone's name in the list, and connect to it. On Windows, open WiFi settings and connect to your phone's hotspot. Your computer and the Pi must be on the same network to SSH.
3. Insert micro SD card into the Pi
4. Power on the Pi:
   - **With PiSugar:** Short press the PiSugar button (green LED on), release, then long press until green LEDs light up one by one and a blue LED turns on (power to Pi). The Pi's green LED will start flickering as it boots.
   - **Without PiSugar:** Plug a micro USB cable into the Pi's PWR port.
4. Wait ~60 seconds for first boot (green LED on Pi should flicker)
5. From your computer, SSH into the Pi:

**Mac** (Terminal):
```bash
ssh <username>@<hostname>.local
# Example: ssh pi-molt@pi-molt.local
```

**Windows** (PowerShell or Command Prompt):
```
ssh <username>@<hostname>.local
# Example: ssh pi-molt@pi-molt.local
```

> Windows 10/11 has SSH built in. If `ssh` is not recognized, install [PuTTY](https://www.putty.org/) and connect to `<hostname>.local` with your username.

6. Type `yes` to accept the SSH fingerprint, then enter your password

### Troubleshooting — Can't Connect

- **No response / timeout:** Wait another 30 seconds — Pi Zero 2W is slow on first boot
- **Unknown host:** Your computer and the Pi must be on the **same network**. If using a phone hotspot, your computer must also be connected to that hotspot (WiFi or USB tethering)
- **Wrong hostname:** The `.local` name matches the hostname you set in the imager, not always `raspberrypi`
- **WiFi won't connect:** Make sure **Maximize Compatibility** is ON in your iPhone hotspot settings. The Pi Zero 2W can only connect to 2.4GHz
- **Still can't find it:** Check your phone's hotspot screen — it shows how many devices are connected. If it says 0, the Pi isn't connecting to the hotspot. Double-check the SSID and password match exactly

### Fixing WiFi After a Hotspot Change

The Pi stores the WiFi name and password from when it was flashed. If you changed your phone's hotspot password or phone name, the Pi can't connect anymore. **You do NOT need to re-flash the SD card.** Your software, config, and everything else stays intact.

**Option A — Edit the SD card from your computer (no SSH needed):**

1. Power off the Pi
2. Remove the micro SD card and insert it into your Mac or PC
3. Your computer will mount a partition called **bootfs**
4. Open the file `network-config` in a text editor
5. Find the section that looks like this:
```yaml
  wifis:
    wlan0:
      dhcp4: true
      regulatory-domain: "US"
      access-points:
        "OldPhoneName":
          password: "long-hashed-password-here"
```
6. Replace `"OldPhoneName"` with your new hotspot name
7. Replace the password with your new hotspot password in plain text (it will be hashed on next boot)
8. Save the file, eject the SD card, put it back in the Pi, and power on

> **Note:** This file is only read on first boot on some OS versions. If Option A doesn't work, use Option B.

**Option B — Edit from another WiFi network:**

If you can temporarily connect the Pi to a different network (home WiFi, another hotspot):

1. SSH into the Pi from that network
2. Edit the WiFi config:
```bash
sudo nano /etc/NetworkManager/system-connections/preconfigured.nmconnection
```
3. Update the `ssid=` and `psk=` lines with the new hotspot name and password
4. Save and restart networking:
```bash
sudo systemctl restart NetworkManager
```
5. Turn on your new hotspot — the Pi should connect within 30 seconds


---

## Step 3: Update and Install Basics

```bash
# Update system packages
sudo apt update && sudo apt upgrade -y

# Install common tools
sudo apt install -y python3-venv python3-pip git
```

Your Pi is now ready. See the [README](README.md) for SiteEye-specific setup (clone, dependencies, service install).
