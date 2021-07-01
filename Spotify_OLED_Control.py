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
import multiprocessing as mp
import time
from threading import Thread

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

SCROLL_SPEED = 3
SCROLL_BACK_SPEED = 6
SCROLL_REST_TIME = 15
SONG_FONT_SIZE = 22
ARTIST_FONT_SIZE = 18
SEEK_FONT_SIZE = 10


# Get associated values from config file
config = configparser.ConfigParser()
config.read('config.txt')
credentials = config['credentials']

global spotifyData

class ScrollDataClass():
    def __init__(self, textlen, string):
        self.x = 0
        self.textlen = textlen
        self.string = string
        self.scrolling  = textlen > Width
        self.end = not self.scrolling #scroll has reached the end of its movement
        self.movingLeft = True #scrolling direction
        self.restCounter = 0


        #TODO modify scroll speed based on text length
    def calcifEnded(self):
        if not self.end:
            if self.movingLeft:
                if self.x < 0-self.textlen + Width:
                    self.end = True
                    #print("scroll ended")
            else:
                if self.x >= 0:
                    self.end = True
                    #print("scroll ended")

class SeekbarDataClass():

    def __init__(self, current_pos, song_len):
        self.currentPos = current_pos
        self.lastTime = int(time.time())
        self.songLen = song_len
        self.totalTimeString = self.calcTimeString(song_len)
        self.currentPosString = self.calcTimeString(self.currentPos)
        self.x_pos = 0
        self.padding = 35
        self.end = False

    def calcTimeString(self, song_len):
        m, s = divmod(song_len, 60)
        h, m = divmod(m, 60)
        c_song_len = '{:02d}:{:02d}'.format(m, s)
        return c_song_len


class UIThread():
    def __init__(self, spotifyData):
        self.dataAvailable = False
        if spotifyData.track is not None and spotifyData.artists is not None:
            self.track = spotifyData.track
            self.artist = concat_artists(spotifyData.artists)
            self.trackfont = ImageFont.truetype(font_path, SONG_FONT_SIZE)
            self.artistfont = ImageFont.truetype(font_path, ARTIST_FONT_SIZE)
            self.dataAvailable = True

        self.seekBarFont = ImageFont.truetype(font_path, SEEK_FONT_SIZE)


    def run(self):  # scroll
        if self.dataAvailable:
            with canvas(device) as draw:
                trackw, self.h = draw.textsize(self.track, font=self.trackfont)
                artistw, self.h = draw.textsize(self.artist, font=self.artistfont)

            trackscrollinfo = ScrollDataClass(trackw, self.track)
            artistscrollinfo = ScrollDataClass(artistw, self.artist)
            scrollinfos = [trackscrollinfo, artistscrollinfo]

        seekbarinfo = SeekbarDataClass(int(spotifyData.progressMs/1000), int(spotifyData.durationMs/1000))

        while True:
            if self.dataAvailable:
                scrollinfos = self.nextScrollFrame(scrollinfos)

            seekbarinfo = self.nextSeekFrame(seekbarinfo, spotifyData.isPlaying)

            with canvas(device) as draw:
                if self.dataAvailable:
                    #track name scroller
                    draw.text((scrollinfos[0].x, 0), trackscrollinfo.string, font=self.trackfont, fill="white")
                    #artist name scroller
                    draw.text((scrollinfos[1].x, 24), artistscrollinfo.string, font=self.artistfont, fill="white")

                if not spotifyData.isPlaying:
                    # draw pause symbol
                    draw.rectangle((67, (Height - 11), 70, Height), "white", "white", 1)
                    draw.rectangle((55, (Height - 11), 58, Height), "white", "white", 1)
                else:
                    # draw seek bar outline
                    draw.rectangle((seekbarinfo.padding, (Height - 6), (Width - seekbarinfo.padding), (Height - 3)), "black", "white", 1)
                    # draw bar within
                    draw.rectangle((seekbarinfo.padding, (Height - 5), (seekbarinfo.x_pos + 2), (Height - 4)), "black", "white", 2)

                #draw current time
                draw.text((0, (Height - 11)), seekbarinfo.currentPosString, font=self.seekBarFont, fill="white")
                #end time
                draw.text((Width - seekbarinfo.padding + 5, (Height - 11)), seekbarinfo.totalTimeString, font=self.seekBarFont, fill="white")



    def nextScrollFrame(self, scrollinfos):
        scrollingcount = 0
        for scroll in scrollinfos:
            scroll.calcifEnded()
            if scroll.scrolling:
                scrollingcount += 1

        # true if both scroll bars are finished scrolling at the starting position
        allended = scrollinfos[0].end and scrollinfos[0].movingLeft ==False and scrollinfos[1].end and scrollinfos[1].movingLeft == False

        for scroll in scrollinfos:
            if scroll.scrolling:
                if scroll.end:  #if end of scrolling movement, on either side
                        if scroll.movingLeft:
                            scroll.end = False
                            scroll.movingLeft = not scroll.movingLeft
                        else:
                            if allended or scrollingcount==1:       #if both scrolls back at begining or only one scrolling
                                if scroll.restCounter > SCROLL_REST_TIME:
                                    scroll.end=False
                                    scroll.movingLeft = not scroll.movingLeft
                                    scroll.restCounter = 0
                                else:
                                    scroll.restCounter+=1
                else:
                    if scroll.movingLeft:
                        scroll.x -= SCROLL_SPEED
                    else:
                        scroll.x += SCROLL_BACK_SPEED
        return scrollinfos

    def nextSeekFrame(self, seekbarinfo, isPlaying):
        diff = time.time() - seekbarinfo.lastTime
        seekbarinfo.lastTime = time.time()
        if isPlaying:
            seekbarinfo.currentPos += diff
        percent = seekbarinfo.currentPos / seekbarinfo.songLen
        seekbarinfo.x_pos = seekbarinfo.padding + int(percent * (Width - seekbarinfo.padding * 2))
        if percent >= 1:
            seekbarinfo.end = True
        else:
            seekbarinfo.end = False

        seekbarinfo.currentPosString = seekbarinfo.calcTimeString(int(seekbarinfo.currentPos))
        return seekbarinfo

    def finish(self):
        self.proc.terminate()


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
        self.isPlaying = None               #play /pause
        self.nothingPlaying = True          #a track is playing / no playback
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
        try:
            playback = self.sp.current_playback()
            self.isPlaying = playback['is_playing']
            try:
                if self.isPlaying:
                    self.track = playback['item']['name']
                    self.artists = playback['item']['artists']
                    self.durationMs = playback['item']['duration_ms']
                    self.progressMs = playback['progress_ms']
                    self.nothingPlaying = False
                else:
                    pass
                    # self.track = None
                    # self.artists = None
                    # self.durationMs = None
                    # self.progressMs = None

                # shuffle doesn't change
                self.shuffleState = playback['shuffle_state']
            except TypeError:
                self.nothingPlaying = True
                print("type error getting data")

        except:
            #TODO do something if this get hit lots
            #print("AUGUGHGH CRASHED - something about timing out maybe?")
            self.nothingPlaying = True
            self.track = None
            self.artists = None
            self.durationMs = None
            self.progressMs = None


    def get_vol(self):
        if self.isPlaying:
            playback = self.sp.current_playback()
            self.volume = playback['device']['volume_percent']
            return self.volume

    def __str__(self):
        if self.isPlaying:
            return "Now playing " + self.track + " by " + self.artists[0]["name"] + " from Spotify"
        if self.nothingPlaying:
            return "Nothing playing"
        else:
            return "paused"


def updateAllUis(ui, spotifyData):
    print(spotifyData)
    terminateThreads(ui)
    ui = StartThreads(spotifyData)
    return ui


def StartThreads(spotifyData):
    # print("starting UI threads")
    UIObjs = []
    #TODO spotify data should not have None fields! where possible cache previous value
    UIObjs.append(UIThread(spotifyData))


    for i, obj in enumerate(UIObjs):
        p = mp.Process(target=obj.run)
        obj.proc = p
        p.start()
    mp.active_children()
    return UIObjs


def terminateThreads(UIObjs):
    for p in UIObjs:
        p.finish()


def remove_feat(track_name):
    if "(feat." in track_name:
        start = track_name.index("(feat")
        end = track_name.index(")") + 2
        return track_name.replace(track_name[start:end], "")
    else:
        return track_name


def concat_artists(artists):
    try:
        if len(artists) > 1:
            names = ""
            names += artists[0]["name"]
            for i in range(1, len(artists)):
                names += "," + artists[i]["name"]
            return names
        else:
            return artists[0]["name"]
    except:
        return None


if __name__ == "__main__":
    spotifyData = Spotify()
    lastSong = ""
    lastIsPlaying = False
    lastSongPos = 0
    ui = []
    spotifyData.get_playback()
    print(spotifyData)
    if spotifyData.isPlaying:
        ui = StartThreads(spotifyData)

    while True:
        try:
            lastSong = spotifyData.track + spotifyData.artists[0]["name"]
        except TypeError:
            lastSong = None  # This means that nothing is playing

        if spotifyData.progressMs is not None:
            lastSongPos = int(spotifyData.progressMs/1000)
        lastIsPlaying = spotifyData.isPlaying
        spotifyData.get_playback()
        if spotifyData.nothingPlaying:
            print("nothing playing")
            time.sleep(2)
            continue

        #if spotifyData.track is None and lastSong is not None:  # paused
        if spotifyData.isPlaying is False and lastIsPlaying is True:
            #print("paused")
            ui = updateAllUis(ui, spotifyData)
            continue

        #if lastSong is None and spotifyData.track is not None:  # unpaused
        if spotifyData.isPlaying is True and lastIsPlaying is False:
            print("unpaused")
            ui = updateAllUis(ui, spotifyData)
            continue

        if spotifyData.isPlaying:
            if spotifyData.track + spotifyData.artists[0]["name"] != lastSong:
                print("Song changed")
                ui = updateAllUis(ui, spotifyData)
                continue

            if abs(lastSongPos - int(spotifyData.progressMs / 1000)) > 5:
                print("woah time skipped")
                ui = updateAllUis(ui, spotifyData)
                continue