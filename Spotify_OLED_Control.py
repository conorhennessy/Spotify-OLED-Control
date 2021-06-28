#!/usr/bin/env python3
import os
import threading
import time
from datetime import datetime
from datetime import timedelta
import configparser
import spotipy
from PIL import ImageFont
from luma.core.interface.serial import i2c
from luma.core.render import canvas
from luma.oled.device import ssd1306
from RPi import GPIO

clk = 17
dt = 18
btn = 27

GPIO.setmode(GPIO.BCM)
GPIO.setup(clk, GPIO.IN, pull_up_down=GPIO.PUD_UP)
GPIO.setup(dt, GPIO.IN, pull_up_down=GPIO.PUD_UP)
GPIO.setup(btn, GPIO.IN, pull_up_down=GPIO.PUD_UP)

clkLastState = GPIO.input(clk)

# substitute spi(device=0, port=0) below if using that interface
serial = i2c(port=1, address=0x3C)
# substitute ssd1331(...) or sh1106(...) below if using that device
device = ssd1306(serial)
Width = 128
Height = 64

font_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "fonts", 'cour.ttf'))
font = ImageFont.truetype(font_path, 18)

SCROLL_SPEED = 4
SCROLL_BACK_SPEED = 8
SONG_FONT_SIZE = 18
ARTIST_FONT_SIZE = 15
SEEK_FONT_SIZE = 10

# Get associated values from config file
config = configparser.ConfigParser()
config.read('config.txt')
credentials = config['credentials']

global spotifyData


class Spotify:
    def __init__(self):
        self.username = credentials['username']
        self.scope = 'user-read-playback-state, user-modify-playback-state'
        self.cache_path = ".cache-{}".format(self.username)

        self.track = None
        self.artists = None
        self.durationMs = None
        self.progressMs = None
        self.shuffleState = None
        self.isPlaying = None
        self.volume = self.get_vol()
        if self.volume == 0:
            self.isMuted = True
        else:
            self.isMuted = False

        self.sp = spotipy.Spotify(
            requests_timeout=10,
            auth_manager=spotipy.SpotifyOAuth(
                client_id=credentials['client_id'],
                client_secret=credentials['client_secret'],
                redirect_uri=credentials['redirect_uri'],
                scope=self.scope,
                cache_path=self.cache_path,
                open_browser=False)
        )

    def get_playback(self):
        playback = self.sp.current_playback()
        self.isPlaying = playback['is_playing']
        if self.isPlaying:
            self.track = playback['item']['name']
            self.artists = playback['item']['artists']
            self.durationMs = playback['item']['duration_ms']
            self.progressMs = playback['progress_ms']
            self.shuffleState = playback['shuffle_state']

    def get_vol(self):
        if self.isPlaying:
            playback = self.sp.current_playback()
            self.volume = playback['device']['volume_percent']
            return self.volume

    def __str__(self):
        if self.isPlaying:
            return "Now playing " + self.track + " by " + self.artists[0]["name"] + " from Spotify"
        return "Nothing playing"


class ScrollThread(threading.Thread):
    def __init__(self, word, fontsize, y_pos):
        threading.Thread.__init__(self)
        self.word = word
        self.end = False
        self.Width = Width
        self.x = 5
        self.y_pos = y_pos
        self.font = ImageFont.truetype(font_path, fontsize)
        self.move = False  # True = right
        self.scrolling = False
        with canvas(device) as draw:
            self.w, self.h = draw.textsize(self.word, font=self.font)

    def calc_scrolling(self):
        with canvas(device) as draw:
            self.w, self.h = draw.textsize(self.word, font=self.font)
            if self.w > Width:
                self.scrolling = True

    def run(self):  # scroll
        while True:
            last_move = self.move
            if self.scrolling and not self.end:  # This could be cleaner by only using one while loop & reverse variable
                if self.move:
                    self.x += SCROLL_BACK_SPEED
                else:
                    self.x -= SCROLL_SPEED  # TODO change this scroll logic so scrolls left continuously

                if self.x < ((Width - self.w) - 10) and not self.move:  # Was moving left and has moved enough
                    self.move = True

                else:
                    if self.x > 0 and self.move:  # Was moving right and more than 0
                        self.move = False

                if not self.move and last_move:
                    self.end = True
                    time.sleep(3)
            time.sleep(.2)

    def draw_obj(self):
        draw.text((self.x, self.y_pos), self.word, font=self.font, fill="white")


class SeekThread(threading.Thread):
    def __init__(self, current_pos, song_len, is_playing):
        threading.Thread.__init__(self)
        self.padding = 35
        self.font = ImageFont.truetype(font_path, SEEK_FONT_SIZE)
        self.currentPos = current_pos
        self.lastTime = int(time.time())
        self.songLen = song_len
        self.end = False
        self.isPlaying = is_playing
        self.x_pos = None

    def run(self):
        while True:
            diff = time.time() - self.lastTime
            self.lastTime = time.time()
            if self.isPlaying:
                self.currentPos += diff
            percent = self.currentPos / self.songLen
            self.x_pos = self.padding + int(percent * (Width - self.padding * 2))
            if percent >= 1:
                self.end = True
            else:
                self.end = False
            time.sleep(1)

    def draw_obj(self):
        m, s = divmod(int(self.songLen), 60)
        h, m = divmod(m, 60)
        c_song_len = '{:02d}:{:02d}'.format(m, s)
        draw.text((Width - self.padding + 5, (Height - 11)), c_song_len, font=self.font, fill="white")

        m, s = divmod(int(self.currentPos), 60)
        h, m = divmod(m, 60)
        c_song_pos = '{:02d}:{:02d}'.format(m, s)
        draw.text((0, (Height - 11)), c_song_pos, font=self.font, fill="white")

        if self.isPlaying:
            # draw seek bar outline
            draw.rectangle((self.padding, (Height - 6), (Width - self.padding), (Height - 3)), "black", "white", 1)
            # draw bar within
            draw.rectangle((self.padding, (Height - 5), (self.x_pos + 2), (Height - 4)), "black", "white", 2)
        else:
            # draw pause
            draw.rectangle((67, (Height - 11), 70, Height), "white", "white", 1)
            draw.rectangle((55, (Height - 11), 58, Height), "white", "white", 1)


def remove_feat(track_name):
    if "(feat." in track_name:
        start = track_name.index("(feat")
        end = track_name.index(")") + 2
        return track_name.replace(track_name[start:end], "")
    else:
        return track_name


def concat_artists(artists):
    if len(artists) > 1:
        names = ""
        names += artists[0]["name"]
        for i in range(1, len(artists)):
            names += "," + artists[i]["name"]
        return names
    else:
        return artists[0]["name"]


def rotary_callback():
    global clkLastState
    clk_state = GPIO.input(clk)
    if clk_state != clkLastState:
        dt_state = GPIO.input(dt)
        if dt_state != clk_state and spotifyData.get_vol() < 100:
            spotifyData.sp.volume(spotifyData.get_vol() + 10)
        elif spotifyData.get_vol() > 0:
            spotifyData.sp.volume(spotifyData.get_vol() - 10)
        print(spotifyData.get_vol())
        clkLastState = clk_state


if __name__ == "__main__":
    try:
        with canvas(device) as draw:
            draw.text((Width / 2, 32), "loading", font=ImageFont.truetype(font_path, 12), fill="white")

        spotifyData = Spotify()
        lastSong = ""
        spotifyData.get_playback()

        clkLastState = GPIO.input(clk)
        GPIO.add_event_detect(clk, GPIO.BOTH, callback=rotary_callback, bouncetime=100)

        NETWORK_TIMEOUT = 1
        drawTime = datetime.now() + timedelta(seconds=NETWORK_TIMEOUT)

        songScrollThread = ScrollThread(word=remove_feat(spotifyData.track), fontsize=SONG_FONT_SIZE, y_pos=5)
        songScrollThread.start()

        artistScrollThread = ScrollThread(word=concat_artists(spotifyData.artists), fontsize=ARTIST_FONT_SIZE, y_pos=30)
        artistScrollThread.start()

        with canvas(device) as draw:
            songScrollThread.draw_obj()
            artistScrollThread.draw_obj()

        try:
            lastSong = spotifyData.track + spotifyData.artists[0]["name"]
        except AttributeError:
            pass

        seekThread = SeekThread((spotifyData.progressMs / 1000), (spotifyData.durationMs / 1000), spotifyData.isPlaying)
        seekThread.start()

        while True:
            try:
                lastSong = spotifyData.track + spotifyData.artists[0]["name"]
            except AttributeError:
                pass
            print(spotifyData)

            songScrollThread.scrolling = False
            songScrollThread.x = 0
            songScrollThread.word = remove_feat(spotifyData.track)
            songScrollThread.calc_scrolling()

            artistScrollThread.scrolling = False
            artistScrollThread.x = 0
            artistScrollThread.word = concat_artists(spotifyData.artists)
            artistScrollThread.calc_scrolling()

            seekThread.songLen = spotifyData.durationMs / 1000
            seekThread.currentPos = spotifyData.progressMs / 1000
            seekThread.isPlaying = spotifyData.isPlaying

            if spotifyData.progressMs < spotifyData.durationMs:
                seekThread.end = False

            while not seekThread.end:
                with canvas(device) as draw:
                    songScrollThread.draw_obj()
                    artistScrollThread.draw_obj()
                    seekThread.draw_obj()

                if datetime.now() > drawTime:
                    if not songScrollThread.scrolling:  # Check if both are not scrolling
                        print("Checking song playback")
                        spotifyData.get_playback()
                        seekThread.currentPos = spotifyData.progressMs / 1000
                        seekThread.isPlaying = spotifyData.isPlaying
                        drawTime = datetime.now() + timedelta(seconds=NETWORK_TIMEOUT)

                        if spotifyData.track + spotifyData.artists[0]["name"] != lastSong:
                            break
                        else:
                            artistScrollThread.end = False
                    else:
                        if songScrollThread.end:  # TODO potentially should check if both scrolls are at 0
                            print("Scroll ended, checking song playback")
                            spotifyData.get_playback()
                            seekThread.currentPos = spotifyData.progressMs / 1000
                            seekThread.isPlaying = spotifyData.isPlaying
                            if spotifyData.track + spotifyData.artists[0]["name"] != lastSong:
                                print("Song changed")
                                break
                            else:
                                songScrollThread.end = False
                                artistScrollThread.end = False
                                drawTime = datetime.now() + timedelta(seconds=NETWORK_TIMEOUT)
                else:
                    pass

            spotifyData.get_playback()
            print("Song ended or changed")

    except KeyboardInterrupt:
        GPIO.cleanup()
        pass
