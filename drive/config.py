# /*****************************************************************************
# * | File        :       config.py
# * | Author      :   Waveshare team
# * | Function    :   Hardware underlying interface,for Raspberry pi
# * | Info        :
# *----------------
# * | This version:   V1.0
# * | Date        :   2020-06-17
# * | Info        :
# ******************************************************************************/
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documnetation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to  whom the Software is
# furished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS OR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.
#


import os, time, ctypes
from gpiozero import *
import spidev
from smbus import SMBus

# Pin definition
RST_PIN = 25
DC_PIN  = 24

Device_SPI = 1
Device_I2C = 0

class RaspberryPi:
    def __init__(self, spi_freq=40000000, rst=27, dc=25, bl=18, bl_freq=1000, i2c=None):
        self.INPUT  = False
        self.OUTPUT = True
        self.Device = None
        self.spi    = None
        self.bus    = None

        # --- Detect available interfaces ---
        if os.path.exists("/dev/spidev0.0"):
            try:
                self.Device = Device_SPI
                self.spi = spidev.SpiDev()
                self.spi.open(0, 0)
                self.spi.max_speed_hz = spi_freq
                self.spi.mode = 0b11
                print("[INFO] SPI device initialized.")
            except Exception as e:
                print(f"[WARN] SPI init failed: {e}")
                self.Device = None
        elif os.path.exists("/dev/i2c-1"):
            try:
                self.Device = Device_I2C
                self.bus = SMBus(1)
                self.address = 0x3c
                print("[INFO] I2C device initialized (0x3C).")
            except Exception as e:
                print(f"[WARN] I2C init failed: {e}")
                self.Device = None
        else:
            print("[WARN] No SPI/I2C device found — running in dummy mode.")
            self.Device = None

        # --- Setup GPIO pins safely ---
        try:
            self.GPIO_RST_PIN = self.gpio_mode(RST_PIN, self.OUTPUT)
            self.GPIO_DC_PIN  = self.gpio_mode(DC_PIN,  self.OUTPUT)
        except Exception as e:
            print(f"[WARN] GPIO setup skipped: {e}")
            self.GPIO_RST_PIN = None
            self.GPIO_DC_PIN  = None

    # --- GPIO helpers ---
    def delay_ms(self, delaytime):
        time.sleep(delaytime / 1000.0)

    def gpio_mode(self, Pin, Mode):
        if Mode:
            return DigitalOutputDevice(Pin, active_high=True, initial_value=False)
        else:
            return DigitalInputDevice(Pin, pull_up=None, active_state=True)

    def gpio_pwm(self, Pin):
        return PWMOutputDevice(Pin, frequency=10000)

    def set_pwm_Duty_cycle(self, Pin, value):
        Pin.value = value

    def digital_write(self, Pin, value):
        if not Pin: return
        Pin.on() if value else Pin.off()

    def digital_read(self, Pin):
        if not Pin: return None
        return Pin.value

    # --- SPI / I2C communication ---
    def spi_writebyte(self, data):
        if self.spi:
            self.spi.writebytes([data[0]])

    def i2c_writebyte(self, reg, value):
        if self.bus:
            self.bus.write_byte_data(self.address, reg, value)

    # --- Lifecycle ---
    def module_init(self):
        if self.GPIO_RST_PIN: self.digital_write(self.GPIO_RST_PIN, False)
        if self.Device == Device_SPI:
            self.spi.max_speed_hz = 1000000
            self.spi.mode = 0b11
        if self.GPIO_DC_PIN: self.digital_write(self.GPIO_DC_PIN, False)
        return 0

    def module_exit(self):
        if self.Device == Device_SPI and self.spi:
            self.spi.close()
        elif self.Device == Device_I2C and self.bus:
            self.bus.close()
        if self.GPIO_RST_PIN: self.digital_write(self.GPIO_RST_PIN, False)
        if self.GPIO_DC_PIN:  self.digital_write(self.GPIO_DC_PIN, False)
