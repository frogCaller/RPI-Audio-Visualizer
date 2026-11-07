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
- **Other sound sources:** a USB microphone, a cable from a TV into a USB sound card, or Bluetooth from a phone or TV. The bars follow whatever is playing.
- **Add songs from the page:** drag and drop files, use Add songs, or get a song from YouTube as an MP3.
- **Cover art:** fetched and saved automatically.

## What you need
* [Raspberry Pi Zero 2 W](https://amzn.to/4qtC0pm)
* [Micro SD card](https://amzn.to/4erXgWD)
* [2.23" OLED HAT](https://amzn.to/3V2gCKb)
* [UPS HAT (C)](https://amzn.to/4oGmKnB) (optional, for battery power)
* [Mini speaker](https://amzn.to/43DTbL4)
* USB microphone or USB sound card with an input (optional, for Mic or cable). A Pi Zero has one USB port, so use a small USB hub for more than one device.

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

## Usage
```bash
python3 start.py
```
Then open `http://<your-pi-ip>:5000` on a phone or computer on the same Wi-Fi. If you don't know the Pi's IP, run `hostname -I`.

**Play from:** at the top of the player, pick **Songs**, **Mic or cable** (the bars follow what a USB microphone hears, or a cable into a USB sound card), or **Bluetooth** (the Pi shows up as a Bluetooth speaker for a phone or TV; needs Raspberry Pi OS Lite). The Pi remembers your choice.

**Choosing where the sound plays:** tap **USB speaker**, **Headphone jack** (on Pis that have one), or **This computer** / **This phone** to hear it on the device you're using. The screen on the Pi keeps moving either way.

**Adding songs:** drop MP3, WAV, FLAC or M4A files onto the page, or copy them into the `Music/` folder. For cover art to be found, name files like `Song Name - Artist.mp3`, for example `Blinding Lights - The Weeknd.mp3`.

**From YouTube:** tap **YouTube**, paste a link to the video, and check the song name and artist. Only the MP3 is kept, saved as `Song Name - Artist.mp3`.

**Keyboard shortcuts** (on a computer): Space to play or pause, ← and → for previous and next, / to search.

## Troubleshooting
- **Screen stays blank:** check that SPI and I2C are on and the HAT is pressed all the way down.
- **No sound:** check the speaker choice on the web page. If it says it can't find the speaker, plug it in and tap it again, or tap **This computer** to listen on your device.
- **Page won't load:** make sure your device is on the same network as the Pi and the address ends in `:5000`.
- **Phone or TV can't find the Pi over Bluetooth:** pick **Bluetooth** on the page first. The Pi only shows up while it's chosen. After running setup, restart the Pi once.
- **YouTube downloads stop working:** YouTube changes often. Run `sudo bash setup.sh` again to update the downloader.
- More about the screen: [Waveshare 2.23" OLED HAT wiki](https://www.waveshare.com/wiki/2.23inch_OLED_HAT)

---
Sample song: "Lukewarm Banjo" by Kevin MacLeod, from [FreePD.com](https://freepd.com).
