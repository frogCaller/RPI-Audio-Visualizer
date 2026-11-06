#coding=utf-8
from . import config
import time
import numpy as np

Device_SPI = config.Device_SPI
Device_I2C = config.Device_I2C

OLED_WIDTH   = 128 #OLED width
OLED_HEIGHT  = 32  #OLED height

#******Rolling Direction******
VERTICAL = True
HORIZONTAL = False

# Scrolling constants
SSD1305_ACTIVATE_SCROLL = 0x2F
SSD1305_DEACTIVATE_SCROLL = 0x2E
SSD1305_SET_VERTICAL_SCROLL_AREA = 0xA3
SSD1305_RIGHT_HORIZONTAL_SCROLL = 0x26
SSD1305_LEFT_HORIZONTAL_SCROLL = 0x27
SSD1305_VERTICAL_AND_RIGHT_HORIZONTAL_SCROLL = 0x29
SSD1305_VERTICAL_AND_LEFT_HORIZONTAL_SCROLL = 0x2A

class SSD1305(object):
    def __init__(self):
        # Call base class constructor.
        self.width = OLED_WIDTH
        self.height = OLED_HEIGHT
        self._pages = self.height // 8
        self._buffer = [0]*(self.width*self._pages)
        #Initialize DC RST pin
        self.RPI = config.RaspberryPi()
        self._dc = self.RPI.GPIO_DC_PIN
        self._rst = self.RPI.GPIO_RST_PIN
        self.Device = self.RPI.Device

    def command(self, cmd):
        if(self.Device == Device_SPI):
            self.RPI.digital_write(self._dc,False)
            self.RPI.spi_writebyte([cmd])
        else:
            self.RPI.i2c_writebyte(0x00, cmd)


    def Init(self):
        if (self.RPI.module_init() != 0):
            return -1
        """Initialize dispaly"""
        self.reset()

        # 128x32 pixel specific initialization.
        self.command(0xAE)#--turn off oled panel
        self.command(0x04)#--Set Lower Column Start Address for Page Addressing Mode
        self.command(0x10)#--Set Higher Column Start Address for Page Addressing Mode
        self.command(0x40)#--Set Display Start Line
        self.command(0x81)#--Set Contrast Control for BANK0
        self.command(0x80)#--Contrast control register is set
        self.command(0xA1)#--Set Segment Re-map
        self.command(0xA6)#--Set Normal/Inverse Display
        self.command(0xA8)#--Set Multiplex Ratio
        self.command(0x1F)
        self.command(0xC8)#--Set COM Output Scan Direction
        self.command(0xD3)#--Set Display Offset
        self.command(0x00)
        self.command(0xD5)#--Set Display Clock Divide Ratio/ Oscillator Frequency
        self.command(0xF0)
        self.command(0xD8)#--Set Area Color Mode ON/OFF & Low Power Display Mode
        self.command(0x05)
        self.command(0xD9)#--Set pre-charge period
        self.command(0xC2)
        self.command(0xDA)#--Set COM Pins Hardware Configuration
        self.command(0x12)
        self.command(0xDB)#--Set VCOMH Deselect Level
        self.command(0x08)#--Set VCOM Deselect Level
        self.command(0xAF)#--Normal Brightness Display ON

    def reset(self):
        """Reset the display"""
        self.RPI.digital_write(self._rst,True)
        time.sleep(0.1)
        self.RPI.digital_write(self._rst,False)
        time.sleep(0.1)
        self.RPI.digital_write(self._rst,True)
        time.sleep(0.1)

    def getbuffer(self, image):
        """Set buffer to value of Python Imaging Library image.  The image should
        be in 1 bit mode and a size equal to the display size.
        """
        if image.mode != '1':
            raise ValueError('Image must be in mode 1.')
        imwidth, imheight = image.size
        if imwidth != self.width or imheight != self.height:
            raise ValueError('Image must be same dimensions as display ({0}x{1}).' \
                .format(self.width, self.height))
        # Pack all pixels at once with numpy instead of looping pixel by pixel.
        # Each byte is one column of 8 rows in a page; row page*8 is bit 0.
        pix = np.asarray(image, dtype=np.uint8)
        pages = pix.reshape(self._pages, 8, self.width)
        self._buffer = np.packbits(pages, axis=1, bitorder='little').tobytes()


    def ShowImage(self):
        w = self.width
        for page in range(0,self._pages):
            row = list(self._buffer[page*w:(page+1)*w])
            if(self.Device == Device_SPI):
                # page address + column address as one command burst
                self.RPI.digital_write(self._dc,False)
                self.RPI.spi_writebytes([0xB0 + page, 0x04, 0x10])
                # whole page of data in one transfer
                self.RPI.digital_write(self._dc,True)
                self.RPI.spi_writebytes(row)
            else :
                self.command(0xB0 + page)
                self.command(0x04)
                self.command(0x10)
                # I2C block writes are limited to 32 bytes
                for i in range(0, w, 32):
                    self.RPI.i2c_writeblock(0x40, row[i:i+32])

    def clear(self):
        """Clear contents of image buffer"""
        _buffer = [0xff]*(self.width * self.height//8)
        self.ShowImage()

    def SSD1305_Scrolling_Set(self):
        self.command(SSD1305_DEACTIVATE_SCROLL)
        if HORIZONTAL:
            self.command(SSD1305_LEFT_HORIZONTAL_SCROLL)
            self.command(0x01)#Set number of column scroll offset
            self.command(0x00)#Define start page address
            self.command(0x00)#Set time interval between each scroll step in terms of frame frequency
            self.command(0x07) #Define end page address
        elif VERTICAL:
            self.command(SSD1305_VERTICAL_AND_RIGHT_HORIZONTAL_SCROLL)
            self.command(0x00)#Set number of column scroll offset
            self.command(0x00)#Define start page address
            self.command(0x00)#Set time interval between each scroll step in terms of frame frequency
            self.command(0x07)#Define end page address
            self.command(0x01)#Vertical scrolling offset
        else:
            self.command(SSD1305_LEFT_HORIZONTAL_SCROLL)
            self.command(0x00) #Set number of column scroll offset
            self.command(0x00) #Define start page address
            self.command(0x00) #Set time interval between each scroll step in terms of frame frequency
            self.command(0x07) #Define end page address

    def SSD1305_Scrolling_Start(self):
        self.command(SSD1305_ACTIVATE_SCROLL)
