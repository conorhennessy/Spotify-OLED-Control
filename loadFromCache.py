import spotipy
from spotipy.oauth2 import SpotifyOAuth

sp = spotipy.Spotify(
    requests_timeout=10,
    auth_manager=spotipy.SpotifyOAuth(
        client_id="4b4f61b0ff88410089d738feb934a63a",
        client_secret="64190a3d0c0541ee8ad84da8e8144e94",
        scope='user-read-playback-state, user-modify-playback-state, user-top-read',
        cache_path=".cache-conorhennessy_")
)

# Shows playing devices, just to show this is working
res = sp.devices()
print(res)
if res is not None:
    print("working")

# playback = sp.current_playback()
# isPlaying = playback['is_playing']
# if isPlaying:
#     track = playback['item']['name']
#     artists = playback['item']['artists']
#     durationMs = playback['item']['duration_ms']
#     progressMs = playback['progress_ms']
#     shuffleState = playback['shuffle_state']
#
# print(track)
# print(artists)

