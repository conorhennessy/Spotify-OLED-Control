#!/usr/bin/env python3
import os
import time

from json.decoder import JSONDecodeError

import spotipy
import spotipy.util as util

from luma.core.render import canvas

from PIL import ImageFont

from luma.core.interface.serial import i2c, spi
from luma.core.render import canvas
from luma.oled.device import ssd1306, ssd1309, ssd1325, ssd1331, sh1106

import threading

from datetime import datetime
from datetime import timedelta

import configparser

font_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "fonts", 'cour.ttf'))

font = ImageFont.truetype(font_path, 18)

# substitute spi(device=0, port=0) below if using that interface
serial = i2c(port=1, address=0x3C)

# substitute ssd1331(...) or sh1106(...) below if using that device
device = ssd1306(serial)
Width = 128
Height = 64

scrollspeed = 4
scrollbackspeed = 8
songfontsize = 18
artistfontsize = 15
seekfontsize = 10

# Get associated values from config file
config = configparser.ConfigParser()
config.read('config.txt')
credentialValues = config['credentials']

client_id = credentialValues['client_id']
client_secret = credentialValues['client_secret']
redirect_uri = credentialValues['redirect_uri']
username = credentialValues['username']

scope = 'user-read-playback-state'


class Spotify:
    def __init__(self, username, scope, client_id, client_secret, redirect_uri):
        self.username = username
        self.scope = scope
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri
        self.cache_path = ".cache-{}".format(username)

        self.track = None
        self.artists = None
        self.durationMs = None
        self.progressMs = None
        self.shuffleState = None
        self.isPlaying = None

        self.sp = spotipy.Spotify(
            auth_manager=spotipy.SpotifyOAuth(
                client_id=client_id,
                client_secret=client_secret,
                redirect_uri=redirect_uri,
                scope=self.scope,
                cache_path=self.cache_path)
        )

    def get_playback(self):
        playback = self.sp.current_playback()

        try:
            self.track = playback['item']['name']
            self.artists = playback['item']['artists']
            self.durationMs = playback['item']['duration_ms']
            self.progressMs = playback['progress_ms']
            self.shuffleState = playback['shuffle_state']
            self.isPlaying = playback['is_playing']
        # TypeError is raised when nothing is playing
        except TypeError:
            self.isPlaying = False

    def __str__(self):
        if self.isPlaying:
            return "Now playing " + self.track + " by " + self.artists[0]["name"] + " from Spotify"
        return "Nothing playing"


class ScrollThread(threading.Thread):
    def __init__(self, word, fontsize, ypos):
        threading.Thread.__init__(self)
        self.word = word
        self.end = False
        self.Width = Width
        self.x = 5
        self.ypos = ypos
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
            lastmove = self.move
            if self.scrolling and not self.end:  # This could be cleaner by only using one while loop & reverse variable
                if self.move:
                    self.x += scrollbackspeed
                else:
                    self.x -= scrollspeed

                if self.x < ((Width - self.w) - 10) and not self.move:  # Was moving left and has moved enough
                    self.move = True

                else:
                    if self.x > 0 and self.move:  # Was moving right and more than 0
                        self.move = False

                if not self.move and lastmove:
                    self.end = True
                    time.sleep(3)
            time.sleep(.2)

    def draw_obj(self):
        draw.text((self.x, self.ypos), self.word, font=self.font, fill="white")


class SeekThread(threading.Thread):
    def __init__(self, current_pos, song_len, isplaying):
        threading.Thread.__init__(self)
        self.padding = 35
        self.font = ImageFont.truetype(font_path, seekfontsize)
        self.currentPos = current_pos
        self.lastTime = int(time.time())
        self.songLen = song_len
        self.end = False
        self.isPlaying = isplaying
        self.xpos = None

    def run(self):
        while True:
            diff = time.time() - self.lastTime
            self.lastTime = time.time()
            if self.isPlaying:
                self.currentPos += diff
            percent = self.currentPos / self.songLen
            self.xpos = self.padding + int(percent * (Width - self.padding * 2))
            if percent >= 1:
                self.end = True
            else:
                self.end = False
            time.sleep(1)

    def draw_obj(self):
        m, s = divmod(int(self.songLen), 60)
        h, m = divmod(m, 60)
        c_song_leng = '{:02d}:{:02d}'.format(m, s)
        draw.text((Width - self.padding + 5, (Height - 11)), c_song_leng, font=self.font, fill="white")

        m, s = divmod(int(self.currentPos), 60)
        h, m = divmod(m, 60)
        c_song_pos = '{:02d}:{:02d}'.format(m, s)
        draw.text((0, (Height - 11)), c_song_pos, font=self.font, fill="white")

        if self.isPlaying:
            # draw seek bar outline
            draw.rectangle((self.padding, (Height - 6), (Width - self.padding), (Height - 3)), "black", "white", 1)
            # draw bar within
            draw.rectangle((self.padding, (Height - 5), (self.xpos + 2), (Height - 4)), "black", "white", 2)
        else:
            # draw pause
            draw.rectangle((67, (Height - 11), 70, Height), "white", "white", 1)
            draw.rectangle((55, (Height - 11), 58, Height), "white", "white", 1)


def remove_feat(trackname):
    if "(feat." in trackname:
        start = trackname.index("(feat")
        end = trackname.index(")") + 2
        return trackname.replace(trackname[start:end], "")
    else:
        return trackname


def concat_artists(artists):
    if len(artists) > 1:
        names = ""
        names += artists[0]["name"]
        for i in range(1, len(artists)):
            names += "," + artists[i]["name"]
        return names
    else:
        return artists[0]["name"]


if __name__ == "__main__":
    try:
        with canvas(device) as draw:
            draw.text((Width / 2, 32), "loading", font=ImageFont.truetype(font_path, 12), fill="white")

        spotifyData = Spotify(username=username, scope=scope, client_id=client_id, client_secret=client_secret,
                              redirect_uri=redirect_uri)
        lastSong = ""
        spotifyData.get_playback()

        NETWORKTIMEOUT = 1  # ten seconds
        drawTime = datetime.now() + timedelta(seconds=NETWORKTIMEOUT)

        songScrollThread = ScrollThread(word=remove_feat(spotifyData.track), fontsize=songfontsize, ypos=5)
        songScrollThread.start()

        artistScrollThread = ScrollThread(word=concat_artists(spotifyData.artists), fontsize=artistfontsize, ypos=30)
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
                        drawTime = datetime.now() + timedelta(seconds=NETWORKTIMEOUT)

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
                                drawTime = datetime.now() + timedelta(seconds=NETWORKTIMEOUT)
                else:
                    pass

            spotifyData.get_playback()
            print("Song ended or changed")

    except KeyboardInterrupt:
        pass
