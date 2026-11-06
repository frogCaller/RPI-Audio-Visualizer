# Raspberry Pi Audio Visualizer

<div style="display: flex; gap: 10px;">
    <img src="images/visualizer.GIF" width="250">
    <img src="images/visualizer2.GIF" width="250">
</div>

A small music player for the Raspberry Pi with a 2.23" OLED HAT. Bars on the screen move with the music, and you pick songs from a web page on your phone or computer.

## Features
- **OLED visualizer:** bars that follow the music, at a steady 25 fps.
- **Web page:** play, pause, skip, random song, volume, and search your library.
- **Live screen view:** the web page shows exactly what's on the OLED.
- **Add songs from the page:** drag and drop files, or use Add songs.
- **Cover art:** fetched and saved automatically.

## What you need
* [Raspberry Pi Zero 2 W](https://amzn.to/4qtC0pm)
* [Micro SD card](https://amzn.to/4erXgWD)
* [2.23" OLED HAT](https://amzn.to/3V2gCKb)
* [UPS HAT (C)](https://amzn.to/4oGmKnB)
* [Mini speaker](https://amzn.to/43DTbL4)

(Amazon affiliate links)

## Setup
1. **Install Raspberry Pi OS (64-bit)** on the SD card.

2. **Attach the OLED HAT** to the Pi, plus the UPS HAT if you're using one.

3. **Enable SPI and I2C:** run `sudo raspi-config`, open **Interface Options**, and turn on **SPI** and **I2C**.

4. **Download and install:**
   ```bash
   sudo apt install -y git
   git clone https://github.com/frogCaller/RPI-Audio-Visualizer.git
   cd RPI-Audio-Visualizer
   sudo bash setup.sh
   ```
   `setup.sh` creates a Python environment (`Music_env`) and installs everything into it.

5. **Pick your speaker** in `config.yaml`:
   ```yaml
   audio:
     jackInput: false  # false = USB speaker, true = headphone jack (on Pis that have one)
   ```

## Usage
```bash
python3 start.py
```
Then open `http://<your-pi-ip>:5000` on a phone or computer on the same Wi-Fi. If you don't know the Pi's IP, run `hostname -I`.

**Adding songs:** drop MP3, WAV, FLAC or M4A files onto the page, or copy them into the `Music/` folder. For cover art to be found, name files like `Song Name - Artist.mp3`, for example `Blinding Lights - The Weeknd.mp3`.

**Keyboard shortcuts** (on a computer): Space to play or pause, ← and → for previous and next, / to search.

## Troubleshooting
- **Screen stays blank:** check that SPI and I2C are on and the HAT is pressed all the way down.
- **No sound:** check `jackInput` in `config.yaml` matches your speaker, and plug in a USB speaker before starting. If the terminal says it's using silent mode, the Pi couldn't open the speaker.
- **Page won't load:** make sure your device is on the same network as the Pi and the address ends in `:5000`.
- More about the screen: [Waveshare 2.23" OLED HAT wiki](https://www.waveshare.com/wiki/2.23inch_OLED_HAT)

---
Sample song: "Lukewarm Banjo" by Kevin MacLeod, from [FreePD.com](https://freepd.com).
