# Raspberry Pi Audio Visualizer

<div style="display: flex; gap: 10px;">   
    <img src="images/visualizer.GIF" width="250">
    <img src="images/visualizer2.GIF" width="250">
</div>

A music visualizer for Raspberry Pi using a 2.23-inch OLED HAT.

## Features
- **OLED Visualizer**: Real-time bar graph visualization of audio frequencies on the 2.23-inch OLED HAT.
- **Web UI**: Browse and play songs from a local webui.
- **Audio Playback**: Uses Pygame for playback.
- **Cover Art**: Automatically fetches and caches album covers.

# Materials
* [Raspberry Pi Zero 2 W](https://amzn.to/4qtC0pm)<br />
* [Micro SD Cards](https://amzn.to/4erXgWD)<br />
* [2.23inch OLED HAT](https://amzn.to/3V2gCKb)<br />
* [UPS Hat (C)](https://amzn.to/4oGmKnB)<br />
* [Mini Speaker](https://amzn.to/43DTbL4)<br />
* [Cable adapter](https://amzn.to/479eGpn)<br />

(Amazon affiliate links)<br />

1. **Install OS:**
   - RaspberryPi OS (64-bit) <br />

# Wiring and Setup
2. **Connect 2.13inch e-Ink HAT to Raspberry Pi:**
   - Connect the 2.23inch OLED HAT to your Raspberry Pi. <br />
   - Connect the UPS Hat for continuous power supply. This will allow you to move the project anywhere without worrying about power interruptions.

3. **Enable SPI & I2C:**
   - Open a terminal on your Raspberry Pi.
   - Run `sudo raspi-config`
   - Navigate to Interfacing Options -> SPI -> Enable.
   - Navigate to Interfacing Options -> I2C -> Enable.
  
4. **Clone the repository:**
   ```bash
   sudo apt install -y git
   git clone https://github.com/frogCaller/RPI-Audio-Visualizer.git
   cd RPI-Audio-Visualizer
   ```

5. **Install System and Python Dependencies:**

   - Automatically creates a dedicated Python virtual environment (`Music_env`) and installs the required dependencies.
    
   ```bash
   chmod +x setup.sh
   ./setup.sh

# Usage
-  By default, the app includes one sample song.
-  To expand your library, add more songs to the Music folder before starting the app.
   ```bash
   python3 start.py
   ```
   Open a browser and go to:
   ```bash
   http://<raspberrypi-IP>:5000
   ```
   Replace <raspberrypi-IP> with your Raspberry Pi’s actual IP address (e.i. http://192.168.0.78:5000).

# Troubleshooting
- Common Issues:
   - Ensure SPI & I2C are enabled in the Raspberry Pi configuration.
   - Check all connections if the screen does not display anything.
   - Verify all required packages are installed correctly.
   - [More Info](https://www.waveshare.com/wiki/2.23inch_OLED_HAT)
