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

from threading import Thread

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

        try:
            self.token = util.prompt_for_user_token(username, scope, client_id, client_secret, redirect_uri)

        except (AttributeError, JSONDecodeError):
            os.remove(".cache-{}".format(username))
            self.token = util.prompt_for_user_token(username, scope, client_id, client_secret, redirect_uri)

    def reload(self):
        if self.token:
            sp = spotipy.Spotify(auth=self.token)

            try:
                playback = sp.current_playback()
            except spotipy.client.SpotifyException:
                print("key expired getting new")
                # re-authenticate when token expires
                self.token = util.prompt_for_user_token(username, scope, client_id, client_secret, redirect_uri)
                sp = spotipy.Spotify(auth=self.token)
                playback = sp.current_playback()

            try:
                self.track = playback['item']['name']
                self.artists = playback['item']['artists']
                self.durationMs = playback['item']['duration_ms']
                self.progressMs = playback['progress_ms']
                self.shuffleState = playback['shuffle_state']
                self.isPlaying = playback['is_playing']
            except TypeError:
                print("nothing playing")

        else:
            print("Unable to retrieve current playback - Can't get token for ", username)

    def __str__(self):
        if self.isPlaying:
            return "Now playing " + self.track + " by " + self.artists[0]["name"] + " from Spotify"
        return "Nothing playing"


class ScrollThread(Thread):

    def __init__(self, word, fontsize, ypos):
        Thread.__init__(self)
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


class Seekthread(Thread):
    def __init__(self, currentpos, songlen, isplaying):
        Thread.__init__(self)
        self.padding = 35
        self.font = ImageFont.truetype(font_path, seekfontsize)
        self.currentpos = currentpos
        self.lasttime = int(time.time())
        self.songlen = songlen
        self.end = False
        self.isplaying = isplaying

    def run(self):
        while True:
            diff = time.time() - self.lasttime
            self.lasttime = time.time()
            self.currentpos += diff
            percent = self.currentpos / self.songlen
            self.xpos = self.padding + int(percent * (Width - self.padding * 2))
            if percent >= 1:
                self.end = True
            else:
                self.end = False
            time.sleep(1)

    def set_current_pos(self, currentpos):
        self.currentpos = currentpos

    def draw_obj(self):
        m, s = divmod(int(self.songlen), 60)
        h, m = divmod(m, 60)
        c_song_leng = '{:02d}:{:02d}'.format(m, s)
        draw.text((Width - self.padding + 5, (Height - 11)), c_song_leng, font=self.font, fill="white")

        m, s = divmod(int(self.currentpos), 60)
        h, m = divmod(m, 60)
        c_song_pos = '{:02d}:{:02d}'.format(m, s)
        draw.text((0, (Height - 11)), c_song_pos, font=self.font, fill="white")

        if self.isplaying:
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
        spotifyobj = Spotify(username=username, scope=scope, client_id=client_id, client_secret=client_secret,
                             redirect_uri=redirect_uri)
        lastsong = ""
        spotifyobj.reload()

        networktimeout = 1  # ten seconds
        justdrawtime = datetime.now() + timedelta(seconds=networktimeout)

        songscrollthread = ScrollThread(word=remove_feat(spotifyobj.track), fontsize=songfontsize, ypos=5)
        songscrollthread.start()

        artistscrollthread = ScrollThread(word=concat_artists(spotifyobj.artists), fontsize=artistfontsize, ypos=30)
        artistscrollthread.start()

        with canvas(device) as draw:
            songscrollthread.draw_obj()
            artistscrollthread.draw_obj()

        playing = True
        try:
            playing = spotifyobj.isPlaying
            lastsong = spotifyobj.track + spotifyobj.artists[0]["name"]
        except AttributeError:
            pass

        seekthread = Seekthread((spotifyobj.progressMs / 1000), (spotifyobj.durationMs / 1000), isplaying=playing)
        seekthread.start()

        while True:

            try:
                playing = spotifyobj.isPlaying
                lastsong = spotifyobj.track + spotifyobj.artists[0]["name"]
            except AttributeError:
                pass
            print(spotifyobj)

            songscrollthread.scrolling = False
            songscrollthread.x = 0
            songscrollthread.word = remove_feat(spotifyobj.track)
            songscrollthread.calc_scrolling()

            artistscrollthread.scrolling = False
            artistscrollthread.x = 0
            artistscrollthread.word = concat_artists(spotifyobj.artists)
            artistscrollthread.calc_scrolling()

            seekthread.songlen = spotifyobj.durationMs / 1000
            seekthread.currentpos = spotifyobj.progressMs / 1000
            seekthread.isplaying = spotifyobj.isPlaying

            if spotifyobj.progressMs < spotifyobj.durationMs:
                seekthread.end = False

            while not seekthread.end:
                with canvas(device) as draw:
                    songscrollthread.draw_obj()
                    artistscrollthread.draw_obj()
                    seekthread.draw_obj()

                if datetime.now() > justdrawtime:
                    if not songscrollthread.scrolling:  # potentially should check if both are not scrolling
                        print("checking song")
                        spotifyobj.reload()
                        seekthread.currentpos = spotifyobj.progressMs / 1000
                        seekthread.isplaying = spotifyobj.isPlaying
                        justdrawtime = datetime.now() + timedelta(seconds=networktimeout)

                        if spotifyobj.track + spotifyobj.artists[0]["name"] != lastsong:
                            break
                        else:
                            artistscrollthread.end = False
                    else:
                        if songscrollthread.end:  # TODO potentially should check if both scrolls are at 0
                            print("Scroll ended, checking song playback")
                            spotifyobj.reload()
                            seekthread.currentpos = spotifyobj.progressMs / 1000
                            seekthread.isplaying = spotifyobj.isPlaying
                            if spotifyobj.track + spotifyobj.artists[0]["name"] != lastsong:
                                print("diff song")
                                break
                            else:
                                songscrollthread.end = False
                                artistscrollthread.end = False
                                justdrawtime = datetime.now() + timedelta(seconds=networktimeout)
                else:
                    pass

            spotifyobj.reload()
            print("song ended or changed")

    except KeyboardInterrupt:
        pass
