from flask import Flask, render_template, jsonify, request, Response, send_from_directory
from PIL import Image, ImageDraw
import base64
from drive import SSD1305
import numpy as np
import os
import pygame
import threading, time, glob, random, string, functools, subprocess
import requests
from mutagen import File
from queue import Queue
import re
import yaml
import json, shutil, signal, sys, secrets, importlib.util

# --- OLED Setup ---
disp = SSD1305.SSD1305()
disp.Init()
disp.clear()
WIDTH, HEIGHT = disp.width, disp.height
image = Image.new("1", (WIDTH, HEIGHT))
draw = ImageDraw.Draw(image)
cached_samples = None
cached_path = None
current_index = 0
current_song_path = None
MUSIC_DIR = 'Music'
os.makedirs(MUSIC_DIR, exist_ok=True)
COVERS_DIR = 'static/covers'
DEFAULT_COVER = '/static/covers/default_art.png'

display_lock = threading.RLock()   # one thread talks to the OLED at a time
samples_lock = threading.Lock()    # one song decode at a time
mixer_lock = threading.Lock()      # never decode a Sound while music.load() runs
last_frame = None                  # last bytes sent to the OLED
play_gen = 0                       # bumps on every new song; old visualizer threads exit
frame_cond = threading.Condition() # wakes the web page's live screen view
frame_seq = 0                      # counts frames sent to the OLED
music_volume = 1.0                 # kept here because pygame resets volume on load
song_lengths = {}                  # song path -> length in seconds
audio_ok = False                   # False when no speaker could be opened (silent mode)
audio_error = None                 # why there's no sound: "nocard", "failed", "busy" or "missing"
listener = None                    # browser tab playing the sound itself, or None for the Pi
CONFIG_PATH = "config.yaml"


def load_config(path=CONFIG_PATH):
    try:
        with open(path, "r") as f:
            return yaml.safe_load(f)
    except FileNotFoundError:
        print("⚠️ config.yaml not found — using defaults")
        return {"audio": {"jackInput": False}}
      
config = load_config()

jackInput = config.get("audio", {}).get("jackInput", False)


def save_config():
    """Remember the speaker choice made on the web page."""
    cfg = config if isinstance(config, dict) else {}
    audio = cfg.get("audio") if isinstance(cfg.get("audio"), dict) else {}
    audio["jackInput"] = bool(jackInput)
    cfg["audio"] = audio
    tmp = CONFIG_PATH + ".tmp"
    with open(tmp, "w") as f:
        yaml.safe_dump(cfg, f, default_flow_style=False, sort_keys=False)
    os.replace(tmp, CONFIG_PATH)

def safe_filename(name):
    return re.sub(r'[^A-Za-z0-9._-]+', '_', name)

cover_queue = Queue()
def cover_fetch_worker():
    """fetching missing cover art."""
    while True:
        try:
            task = cover_queue.get()
            if task is None:
                break
            filepath, artist, title, filename = task
            #print(f"[Background fetching cover for: {artist} - {title}]")
            ensure_cover_for_song(filepath, artist, title, filename)
            cover_queue.task_done()
        except Exception as e:
            print(f"[Cover worker error: {e}]")

threading.Thread(target=cover_fetch_worker, daemon=True).start()

def fetch_cover_from_web(artist, title):
    try:
        if not artist or not title:
            return None

        query = f"{artist} {title}"
        url = f"https://itunes.apple.com/search?term={requests.utils.quote(query)}&limit=1&media=music"

        r = requests.get(url, timeout=5)
        if r.status_code != 200:
            return None

        data = r.json()
        if not data.get("results"):
            return None

        artwork_url = data["results"][0].get("artworkUrl100")
        if not artwork_url:
            return None

        artwork_url = artwork_url.replace("100x100bb", "600x600bb")

        img = requests.get(artwork_url, timeout=5)
        if img.status_code == 200:
            return img.content

    except Exception as e:
        print(f"[Error fetching cover art: {e}]")

    return None

def ensure_cover_for_song(filepath, artist, title, filename):
    """Ensure a cover exists locally; fetch it if needed."""
    os.makedirs(COVERS_DIR, exist_ok=True)

    cover_filename = f"{safe_filename(artist)}-{safe_filename(title)}.jpg"
    local_path = os.path.join(COVERS_DIR, cover_filename)

    if os.path.exists(local_path):
        return f"/static/covers/{cover_filename}"

    try:
        audio = File(filepath)
        if audio and audio.tags:
            if "APIC:" in audio.tags:
                apic = audio.tags["APIC:"]
                with open(local_path, "wb") as f:
                    f.write(apic.data)
                return f"/static/covers/{cover_filename}"
    except Exception as e:
        pass

    img_data = fetch_cover_from_web(artist, title)
    if img_data:
        try:
            with open(local_path, 'wb') as f:
                f.write(img_data)
            return f"/static/covers/{cover_filename}"
        except Exception as e:
            print(f"[Failed to save cover: {e}]")

    return DEFAULT_COVER


def build_library_json():
    songs = []
    for fname in os.listdir(MUSIC_DIR):
        if fname.lower().endswith(('.mp3', '.wav', '.flac', '.m4a')):
            path = os.path.join(MUSIC_DIR, fname)
            artist, title = "Unknown", os.path.splitext(fname)[0]

            try:
                audio = File(path, easy=True)
                tag_artist = audio.get('artist', [None])[0]
                tag_title = audio.get('title', [None])[0]

                if tag_artist:
                    artist = tag_artist
                if tag_title:
                    title = tag_title
                elif "-" in os.path.splitext(fname)[0]:
                    parts = os.path.splitext(fname)[0].split(" - ", 1)
                    if len(parts) == 2:
                        artist, title = parts[0].strip(), parts[1].strip()
            except Exception as e:
                print(f"[Warning: failed to read tags for {fname}: {e}]")
                if "-" in os.path.splitext(fname)[0]:
                    parts = os.path.splitext(fname)[0].split(" - ", 1)
                    if len(parts) == 2:
                        artist, title = parts[0].strip(), parts[1].strip()

            art = ensure_cover_for_song(path, artist, title, fname)

            songs.append({
                "filename": fname,
                "title": title,
                "artist": artist,
                "art": art
            })
    return songs

def buffer(force=False):
    global last_frame, frame_seq
    with display_lock:
        disp.getbuffer(image)
        frame = bytes(disp._buffer)
        # skip the SPI/I2C transfer when the picture hasn't changed
        if force or frame != last_frame:
            disp.ShowImage()
            last_frame = frame
            with frame_cond:
                frame_seq += 1
                frame_cond.notify_all()

def clear_display():
    with display_lock:
        draw.rectangle((0, 0, WIDTH, HEIGHT), outline=0, fill=0)
        buffer(force=True)

    
ASOUND_CARDS = "/proc/asound/cards"


def sound_cards():
    """Sound cards the Pi can see: [(number, name, driver, long name)],
    e.g. (1, "Device", "USB-Audio", "USB2.0 Device")."""
    cards = []
    try:
        with open(ASOUND_CARDS) as f:
            for line in f:
                m = re.match(r"\s*(\d+)\s+\[(\S+)\s*\]:\s*(\S+)(?:\s+-\s+(.*))?", line)
                if m:
                    cards.append((int(m.group(1)), m.group(2), m.group(3), (m.group(4) or m.group(2)).strip()))
    except OSError:
        pass
    return cards


def has_jack():
    """True if the Pi has a headphone jack (or the card list can't be read)."""
    if not os.path.exists(ASOUND_CARDS):
        return True
    return any(name in ("Headphones", "ALSA") or driver.startswith("bcm2835")
               for _, name, driver, _ in sound_cards())


def silent_mode():
    """No speaker could be opened: keep everything running without sound."""
    os.environ["SDL_AUDIODRIVER"] = "dummy"
    time.sleep(0.5)
    pygame.mixer.init()


def init_audio_jack():
    global audio_ok, audio_error
    try:
        os.environ["SDL_AUDIODRIVER"] = "alsa"

        # the Pi's own headphone jack by name first, if it has one
        if any(name == "Headphones" for _, name, _, _ in sound_cards()):
            try:
                pygame.mixer.init(frequency=48000, size=-16, channels=2, buffer=2048,
                                  devicename="plughw:CARD=Headphones,DEV=0")
                print("[Audio: headphone jack]")
                audio_ok, audio_error = True, None
                return
            except Exception as e:
                print(f"[Headphone jack failed: {e}]")

        for card in range(5):
            try:
                test_dev = f"plughw:{card},0"
                pygame.mixer.init(frequency=48000, size=-16, channels=2, buffer=2048, devicename=test_dev)
                audio_ok, audio_error = True, None
                return
            except Exception as e:
                continue

        pygame.mixer.init(frequency=48000, size=-16, channels=2, buffer=2048)
        audio_ok, audio_error = True, None
    except Exception as e:
        print(f"[Jack audio init failed: {e}] Using silent mode.")
        audio_ok = False
        audio_error = "busy" if "busy" in str(e).lower() else "missing"
        silent_mode()


def init_audio():
    global audio_ok, audio_error
    # the card name that worked before first, then every USB sound card the Pi can see
    devices = ["plughw:CARD=Audio,DEV=0"]
    usb_cards = [name for _, name, driver, _ in sound_cards() if driver == "USB-Audio"]
    for name in usb_cards:
        dev = f"plughw:CARD={name},DEV=0"
        if dev not in devices:
            devices.append(dev)

    errors = []
    for dev in devices:
        try:
            os.environ["SDL_AUDIODRIVER"] = "alsa"
            os.environ["AUDIODEV"] = dev
            pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=512)
            print(f"[Audio: {dev}]")
            audio_ok, audio_error = True, None
            return
        except Exception as e:
            errors.append(f"{dev}: {e}")

    print("[Audio init failed] " + " | ".join(errors))
    print("[USB sound cards found: " + (", ".join(usb_cards) or "none") + "] Using silent mode.")
    audio_ok = False
    if any("busy" in e.lower() for e in errors):
        audio_error = "busy"      # another program has the speaker
    elif usb_cards:
        audio_error = "failed"    # the Pi sees a USB speaker but couldn't open it
    else:
        audio_error = "nocard"    # the Pi doesn't see a USB speaker at all
    silent_mode()


def start_audio():
    if jackInput:
        init_audio_jack()
    else:
        init_audio()


start_audio()
    

num_bars = WIDTH // 4
bar_width = 4
decay = 0.85          # how much a bar keeps per frame (higher = slower fall)
FRAME_TIME = 0.04     # seconds per frame (0.04 = 25 fps)
bar_heights = np.zeros(num_bars)
music_visualizer_active = False
music_paused = False


def mixer_rate():
    """Sample rate the mixer is actually running at (44100 USB, 48000 jack)."""
    try:
        init = pygame.mixer.get_init()
        if init:
            return init[0]
    except pygame.error:
        pass
    return 44100


def decode_levels(path):
    """Decode a song once and keep only what the bars need:
    |left + right| per sample as uint16 (about 1/4 the RAM of the old float cache)."""
    # pygame can crash if a Sound decode and music.load() run at the same
    # time (e.g. skipping songs quickly), so they share a lock
    with mixer_lock:
        sound = pygame.mixer.Sound(path)
        raw = pygame.sndarray.array(sound)
        del sound
    n = raw.shape[0]
    levels = np.empty(n, dtype=np.uint16)
    step = 1 << 18
    for s in range(0, n, step):
        block = raw[s:s + step].astype(np.int32)
        if block.ndim == 2:
            block = block.sum(axis=1) * 2 // block.shape[1]
        else:
            block = block * 2
        levels[s:s + step] = np.minimum(np.abs(block), 65535)
    del raw
    return levels


def get_levels(path, gen):
    """Cached levels for a song, decoded only once. None if a newer song started."""
    global cached_samples, cached_path
    with samples_lock:
        if cached_path == path and cached_samples is not None:
            return cached_samples
        if gen != play_gen:
            return None
        cached_samples, cached_path = None, None  # free the previous song first
        try:
            levels = decode_levels(path)
        except Exception as e:
            print(f"[Warning: failed to cache samples: {e}]")
            return None
        cached_samples, cached_path = levels, path
        print(f"[Cached samples for {os.path.basename(path)}]")
        return levels

def normalize(s: str) -> str:
    return s.lower().strip().translate(str.maketrans("", "", string.punctuation))

@functools.lru_cache(maxsize=1)
def get_music_library():
    os.makedirs(MUSIC_DIR, exist_ok=True)
    music_files = []
    for ext in ("*.mp3", "*.wav", "*.m4a", "*.flac"):
        music_files.extend(glob.glob(os.path.join(MUSIC_DIR, ext)))
    # same order as the web page grid, so next/prev go to the neighbouring song
    music_files.sort(key=lambda p: os.path.basename(p).lower())
    normalized_index = {normalize(os.path.splitext(os.path.basename(f))[0]): f for f in music_files}
    print(f"[Loaded {len(music_files)} songs]")
    return music_files, normalized_index

visualizer_thread = None

def play_song(user_input=None):
    global music_visualizer_active, bar_heights, current_index, current_song_path
    global play_gen, music_paused

    # --- Gracefully stop any current playback ---
    play_gen += 1
    gen = play_gen
    music_visualizer_active = False
    music_paused = False
    try:
        if pygame.mixer.music.get_busy():
            pygame.mixer.music.fadeout(200)
        time.sleep(0.1)
    except Exception:
        pass

    bar_heights[:] = 0
    clear_display()

    music_files, normalized_index = get_music_library()
    if not music_files:
        return "[Error: No music files in ~/Music]"

    # --- Choose song ---
    chosen_song = None
    if user_input:
        for f in music_files:
            if os.path.basename(f) == user_input:
                chosen_song = f
                break
    if not chosen_song:
        chosen_song = random.choice(music_files)

    current_song_path = chosen_song
    print(f"Loading: {os.path.basename(chosen_song)}")

    # --- Start playback asynchronously ---
    def start_playback():
        global music_visualizer_active
        try:
            with mixer_lock:
                if gen != play_gen:
                    return  # another song was picked while waiting
                pygame.mixer.music.load(chosen_song)
                pygame.mixer.music.play()
                apply_volume()
            print(f"{os.path.basename(chosen_song)}")
        except Exception as e:
            print(f"[Audio playback error: {e}]")
            return

        # --- Waveform cache (background), only after playback has started ---
        threading.Thread(target=get_levels, args=(chosen_song, gen), daemon=True).start()

        # --- Delay visualizer start slightly until audio ready ---
        time.sleep(0.4)  # allow mixer to settle
        if gen != play_gen or not pygame.mixer.music.get_busy():
            return
        music_visualizer_active = True
        threading.Thread(
            target=music_visualizer_thread,
            args=(chosen_song, gen),
            daemon=True,
            name="VisualizerThread"
        ).start()

    threading.Thread(target=start_playback, daemon=True).start()

    # --- Update current_index ---
    try:
        current_index = music_files.index(chosen_song)
    except ValueError:
        current_index = 0

    return f"{os.path.splitext(os.path.basename(chosen_song))[0]}"


def stop_music():
    global music_visualizer_active, bar_heights
    music_visualizer_active = False
    pygame.mixer.music.stop()
    bar_heights[:] = 0
    clear_display()
    return "Music stopped."

def pause_music():
    global music_paused
    if pygame.mixer.music.get_busy():
        pygame.mixer.music.pause()
        music_paused = True
        return "Music paused."
    return "Nothing playing."

def resume_music():
    global music_paused, music_visualizer_active
    if music_paused:
        pygame.mixer.music.unpause()
        music_paused = False
        music_visualizer_active = True

        if not any(t.name == "VisualizerThread" and t.is_alive() for t in threading.enumerate()):
            threading.Thread(target=music_visualizer_thread, args=(current_song_path, play_gen), daemon=True, name="VisualizerThread").start()

        return "Resumed music."
    return "Nothing to resume."


def music_visualizer_thread(song_file, gen=None):
    global bar_heights
    if gen is None:
        gen = play_gen
    try:
        # waits for the background decode instead of decoding a second copy
        samples = get_levels(song_file, gen)
        if samples is None:
            return

        rate = mixer_rate()
        total_len = len(samples)
        chunk_size = max(1, total_len // 5000)
        last = time.monotonic()
        next_frame = last

        while music_visualizer_active and gen == play_gen and pygame.mixer.music.get_busy():
            pos = pygame.mixer.music.get_pos()
            idx = int(pos / 1000 * rate)
            chunk = samples[idx:idx + chunk_size]
            chunk_len = len(chunk) // num_bars
            if chunk_len == 0:
                time.sleep(FRAME_TIME)
                continue

            # all bars in one numpy call
            new_heights = chunk[:chunk_len * num_bars].reshape(num_bars, chunk_len).mean(axis=1) / 65536.0

            # same fall per frame as before, kept steady if a frame runs late
            now = time.monotonic()
            fall = decay ** ((now - last) / FRAME_TIME)
            last = now
            bar_heights = np.maximum(new_heights, bar_heights * fall)

            with display_lock:
                if gen != play_gen or not music_visualizer_active:
                    break
                # clear the image only; the OLED gets one frame, not a blank one first
                draw.rectangle((0, 0, WIDTH, HEIGHT), outline=0, fill=0)
                for i, h in enumerate(bar_heights):
                    bar_h = int(h * HEIGHT * 1.5)
                    if bar_h > HEIGHT: bar_h = HEIGHT
                    x = i * (bar_width + 1)
                    draw.rectangle([x, HEIGHT - bar_h, x + bar_width - 1, HEIGHT], fill=255)
                    #draw.rectangle([x, 0, x + bar_width - 1, bar_h], fill=255)
                buffer()

            # steady frame rate: sleep only what's left of this frame
            next_frame += FRAME_TIME
            wait = next_frame - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            else:
                next_frame = time.monotonic()
    except Exception as e:
        print("[Visualizer error:", e, "]")

# --- Flask Web UI ---
app = Flask(__name__)

@app.route("/")
def index():
    return render_template("music.html")

@app.route("/play")
def play_route():
    return play_song()

@app.route("/pause")
def pause_route():
    return pause_music()

@app.route("/resume")
def resume_route():
    return resume_music()

@app.route("/stop")
def stop_route():
    return stop_music()

@app.route("/next")
def next_song():
    global current_index
    music_files, _ = get_music_library()
    if not music_files:
        return jsonify(success=False, message="No songs found.")
    current_index = (current_index + 1) % len(music_files)
    filename = os.path.basename(music_files[current_index])
    name, _ = os.path.splitext(filename)
    play_song(filename)
    return jsonify(success=True, filename=filename, message=f"{name}")

@app.route("/prev")
def prev_song():
    global current_index
    music_files, _ = get_music_library()
    if not music_files:
        return jsonify(success=False, message="No songs found.")
    current_index = (current_index - 1) % len(music_files)
    filename = os.path.basename(music_files[current_index])
    name, _ = os.path.splitext(filename)
    play_song(filename)
    return jsonify(success=True, filename=filename, message=f"{name}")

@app.route("/library")
def list_songs():
    music_files, _ = get_music_library()
    html = "<h2>🎵 Music Library</h2>"
    for f in music_files:
        name = os.path.basename(f)
        html += f"<p><a href='/play_song/{name}' style='color:lightgreen;text-decoration:none;'>{name}</a></p>"
    html += "<p><a href='/'>⬅️ Back</a></p>"
    return html

@app.route("/library_json")
def library_json():
    songs = []
    os.makedirs(COVERS_DIR, exist_ok=True)
    os.makedirs(MUSIC_DIR, exist_ok=True)  # Ensure Music folder exists

    if not hasattr(app, "cover_cache"):
        app.cover_cache = set()
    if not hasattr(app, "cover_failed"):
        app.cover_failed = set()

    # Get all valid audio files
    valid_files = sorted((
        f for f in os.listdir(MUSIC_DIR)
        if f.lower().endswith(('.mp3', '.wav', '.flac', '.m4a'))
    ), key=str.lower)

    # ---If no songs found, show friendly message ---
    if not valid_files:
        return jsonify({
            "empty": True,
            "message": "No music found. Please add songs to the Music/ folder."
        })

    # ---Process available songs ---
    for fname in valid_files:
        path = os.path.join(MUSIC_DIR, fname)
        artist, title = "Unknown", os.path.splitext(fname)[0]

        try:
            audio = File(path, easy=True)
            tag_artist = audio.get('artist', [None])[0]
            tag_title = audio.get('title', [None])[0]
            if tag_artist:
                artist = tag_artist
            if tag_title:
                title = tag_title
        except Exception:
            pass

        if artist == "Unknown" or not artist:
            name = os.path.splitext(fname)[0]
            if " - " in name:
                parts = name.split(" - ", 1)
                if len(parts) == 2:
                    first, second = parts[0].strip(), parts[1].strip()
                    if len(second.split()) <= 3 and any(c.isupper() for c in second):
                        title, artist = first, second
                    else:
                        artist, title = first, second

        artist = artist.strip().title() if artist else "Unknown"
        title = title.strip().title() if title else os.path.splitext(fname)[0]
        key = f"{artist}-{title}"

        cover_filename = f"{safe_filename(artist)}-{safe_filename(title)}.jpg"
        local_path = os.path.join(COVERS_DIR, cover_filename)

        if os.path.isfile(local_path) and os.path.getsize(local_path) > 1024:
            art = f"/static/covers/{cover_filename}"
            app.cover_cache.add(key)
        else:
            art = DEFAULT_COVER

            if key not in app.cover_cache and key not in app.cover_failed:
                if not any(task[1] == artist and task[2] == title for task in list(cover_queue.queue)):
                    cover_queue.put((path, artist, title, fname))
                    app.cover_failed.add(key)

        songs.append({
            "filename": fname,
            "title": title,  # the page shortens long titles itself
            "artist": artist,
            "art": art
        })

    # Return normal song list
    return jsonify({"empty": False, "songs": songs})

@app.route("/status")
def current_status():
    global current_song_path

    try:
        busy = pygame.mixer.get_init() and pygame.mixer.music.get_busy()
    except pygame.error:
        busy = False
    
    if busy and current_song_path:
        song_name = os.path.splitext(os.path.basename(current_song_path))[0]
        return f"{song_name}"
    elif current_song_path:
        song_name = os.path.splitext(os.path.basename(current_song_path))[0]
        return f"Paused"
    else:
        return " "

@app.route("/play_song/<filename>")
def play_specific_song(filename):
    return play_song(filename)
  
@app.route("/upload", methods=["POST"])
def upload_song():
    if "file" not in request.files:
        return jsonify({"success": False, "message": "No file part"})

    file = request.files["file"]
    if file.filename == "":
        return jsonify({"success": False, "message": "No selected file"})

    if not file.filename.lower().endswith(('.mp3', '.wav', '.flac', '.m4a')):
        return jsonify({"success": False, "message": "Invalid file type"})

    os.makedirs(MUSIC_DIR, exist_ok=True)
    filename = os.path.basename(file.filename)  # keep uploads inside Music/
    save_path = os.path.join(MUSIC_DIR, filename)
    file.save(save_path)
    get_music_library.cache_clear()  # so the new song can be played right away

    #print(f"[Uploaded new song: {filename}]")
    return jsonify({"success": True, "filename": filename})

# ---------- YouTube downloads ----------
# yt-dlp downloads the audio into a working folder and converts it to MP3 with FFmpeg.
# Only the MP3 is moved into Music/ (with the name you pick); everything else is deleted.
YT_TMP = os.path.abspath(".youtube-tmp")
YT_URL_RE = re.compile(r"^https?://([a-z0-9-]+\.)?(youtube\.com|youtu\.be)/", re.I)
YT_ACTIVE = ("starting", "downloading", "converting")
yt_job = None
yt_lock = threading.Lock()
shutil.rmtree(YT_TMP, ignore_errors=True)  # leftovers if the Pi was switched off mid-download

YT_NOISE = re.compile(
    r"\s*[\(\[\{][^\)\]\}]*\b(official|video|audio|lyrics?|visuali[sz]er|hd|hq|4k|mv|m/v)\b[^\)\]\}]*[\)\]\}]",
    re.I)


def youtube_missing():
    """Programs the Pi still needs for YouTube downloads (empty when ready)."""
    missing = []
    if importlib.util.find_spec("yt_dlp") is None:
        missing.append("yt-dlp")
    if not shutil.which("ffmpeg"):
        missing.append("FFmpeg")
    return missing


def clean_yt_title(text):
    text = YT_NOISE.sub("", text or "")
    text = text.split(" | ")[0]
    return re.sub(r"\s+", " ", text).strip(" -–—_")


def guess_names(info):
    """Song name and artist from the video's details, to fill in the rename boxes."""
    artists = info.get("artists") or info.get("creators") or []
    artist = (artists[0] if artists else None) or info.get("artist") or info.get("creator")
    track = info.get("track")
    if track and artist:
        return clean_yt_title(track), artist.split(",")[0].strip()
    title = clean_yt_title(info.get("title"))
    m = re.match(r"^(.+?)\s+[-–—]\s+(.+)$", title)  # "Artist - Song"
    if m:
        return m.group(2).strip(), m.group(1).strip()
    channel = info.get("uploader") or info.get("channel") or ""
    channel = re.sub(r"\s*-\s*Topic$|VEVO$", "", channel).strip()
    return title, channel


def clean_name(text, limit):
    """Make a song or artist name safe to use in a file name."""
    text = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "", text or "")
    text = text.replace(" - ", " – ")  # " - " separates song and artist in the file name
    return re.sub(r"\s+", " ", text).strip(" .")[:limit].strip()


def youtube_error(lines):
    text = "\n".join(lines)
    low = text.lower()
    if "no module named yt_dlp" in low:
        return "The YouTube downloader isn't installed on the Pi. Run setup.sh again."
    if "ffmpeg" in low and ("not found" in low or "not installed" in low):
        return "FFmpeg isn't installed on the Pi. Run setup.sh again."
    if "javascript runtime" in low or "js runtime" in low:
        return "The Pi is missing Deno, which YouTube downloads need. Run setup.sh again."
    if "confirm your age" in low or "age-restricted" in low or "age restricted" in low:
        return "This video is age-restricted, so it can't be downloaded."
    if "not a bot" in low:
        return "YouTube is blocking downloads from this Pi for now. Try again later."
    if "private video" in low:
        return "This video is private."
    if "video unavailable" in low or "is not available" in low:
        return "This video isn't available."
    if "http error 404" in low:
        return "That video couldn't be found. Check the link."
    if "http error 403" in low or "http error 429" in low:
        return "YouTube is blocking downloads from this Pi for now. Try again later."
    if any(s in low for s in ("unable to download webpage", "name or service not known",
                              "temporary failure in name resolution", "network is unreachable",
                              "failed to resolve")):
        return "The Pi couldn't reach YouTube. Check its internet connection."
    if "unsupported url" in low:
        return "That link doesn't point to a YouTube video."
    errors = [l for l in lines if l.startswith("ERROR:")]
    detail = re.sub(r"^ERROR:\s*(\[[^\]]+\]\s*)*", "", errors[-1]) if errors else ""
    return "Couldn't download this song." + (f" ({detail[:160]})" if detail else "")


def youtube_public(job):
    if job is None:
        return {"state": "none"}
    keys = ("id", "state", "percent", "song", "artist", "title", "error", "filename", "waiting")
    return {k: job.get(k) for k in keys}


def youtube_cleanup(job):
    shutil.rmtree(job["dir"], ignore_errors=True)


def youtube_finish(job):
    """Tag the MP3, give it the chosen name and move it into Music/. Call with yt_lock held."""
    song = clean_name(job["wanted"][0], 80)
    artist = clean_name(job["wanted"][1], 60)
    filename = f"{song} - {artist}.mp3" if artist else f"{song}.mp3"
    dest = os.path.join(MUSIC_DIR, filename)
    if os.path.exists(dest):
        job["error"] = f'There\'s already a song called "{filename[:-4]}". Change the name.'
        job["waiting"] = False
        return False
    try:
        from mutagen.easyid3 import EasyID3
        from mutagen.id3 import ID3NoHeaderError
        try:
            tags = EasyID3(job["mp3"])
        except ID3NoHeaderError:
            tags = EasyID3()
        tags["title"] = song
        if artist:
            tags["artist"] = artist
        elif "artist" in tags:
            del tags["artist"]
        tags.save(job["mp3"])
    except Exception as e:
        print(f"[Couldn't tag {filename}: {e}]")  # the file name still carries the names
    os.makedirs(MUSIC_DIR, exist_ok=True)
    shutil.move(job["mp3"], dest)
    youtube_cleanup(job)
    get_music_library.cache_clear()
    job.update(state="saved", filename=filename, waiting=False, error=None)
    print(f"[Added from YouTube: {filename}]")
    return True


def youtube_worker(job):
    os.makedirs(job["dir"], exist_ok=True)
    cmd = [sys.executable, "-m", "yt_dlp",
           "--ignore-config", "--no-playlist",
           "--js-runtimes", "deno", "--js-runtimes", "node",
           "-f", "bestaudio/best",
           "-x", "--audio-format", "mp3", "--audio-quality", "192K",
           "--no-mtime",
           "-o", os.path.join(job["dir"], "song.%(ext)s"),
           "--newline", "--progress",
           "--progress-template", "download:PROGRESS %(progress._percent_str)s",
           "--print", "video:INFO %(.{title,track,artist,artists,creator,creators,uploader,channel})j",
           "--print", "after_move:FILE %(filepath)s",
           job["url"]]
    if shutil.which("nice"):
        cmd = ["nice", "-n", "10"] + cmd  # let the music and the screen go first
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    errors = []
    with yt_lock:
        if job["state"] == "cancelled":  # cancelled before it got going
            youtube_cleanup(job)
            return
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                    encoding="utf-8", errors="replace", bufsize=1,
                                    start_new_session=True, env=env)
        except Exception as e:
            job.update(state="failed", error=f"Couldn't start the downloader ({e}).")
            youtube_cleanup(job)
            return
        job["proc"] = proc

    def read_errors():
        for line in proc.stderr:
            errors.append(line.strip())
            del errors[:-40]
    threading.Thread(target=read_errors, daemon=True).start()

    for line in proc.stdout:
        line = line.strip()
        with yt_lock:
            if job["state"] == "cancelled":
                continue
            if line.startswith("INFO "):
                try:
                    info = json.loads(line[5:])
                    job["title"] = info.get("title")
                    job["song"], job["artist"] = guess_names(info)
                except ValueError:
                    pass
                if job["state"] == "starting":
                    job["state"] = "downloading"
            elif line.startswith("PROGRESS "):
                m = re.search(r"([\d.]+)%", line)
                if m:
                    job["percent"] = min(100.0, float(m.group(1)))
                    job["state"] = "converting" if job["percent"] >= 100 else "downloading"
            elif line.startswith("FILE "):
                job["mp3"] = line[5:].strip()
    proc.wait()

    with yt_lock:
        if job["state"] == "cancelled":
            pass
        elif proc.returncode == 0 and job.get("mp3") and os.path.isfile(job["mp3"]):
            job.update(state="ready", percent=100.0)
            if job.get("waiting"):
                youtube_finish(job)
        else:
            job.update(state="failed", error=youtube_error(errors))
            print("[YouTube download failed] " + " | ".join(errors[-3:]))
    if job["state"] in ("cancelled", "failed"):
        youtube_cleanup(job)


@app.route("/youtube")
def youtube_status():
    with yt_lock:
        data = youtube_public(yt_job)
    data["missing"] = youtube_missing()
    return jsonify(data)


@app.route("/youtube/start", methods=["POST"])
def youtube_start():
    global yt_job
    url = ((request.get_json(silent=True) or {}).get("url") or "").strip()
    if not YT_URL_RE.match(url):
        return jsonify({"error": "That doesn't look like a YouTube link. Copy the link from the video's Share button."}), 400
    if "/playlist" in url and "v=" not in url:
        return jsonify({"error": "That's a link to a playlist. Paste a link to one song."}), 400
    missing = youtube_missing()
    if missing:
        return jsonify({"error": "The Pi needs " + " and ".join(missing) + " for this. Run setup.sh again."}), 400
    with yt_lock:
        if yt_job and yt_job["state"] in YT_ACTIVE:
            return jsonify({"error": "Another song is downloading. Wait for it to finish."}), 409
        if yt_job and yt_job["state"] == "ready":
            youtube_cleanup(yt_job)  # an earlier download nobody saved
        job_id = secrets.token_hex(6)
        yt_job = {"id": job_id, "url": url, "state": "starting", "percent": 0.0,
                  "song": "", "artist": "", "title": None, "error": None, "filename": None,
                  "waiting": False, "wanted": None, "mp3": None, "proc": None,
                  "dir": os.path.join(YT_TMP, job_id)}
        job = yt_job
    threading.Thread(target=youtube_worker, args=(job,), daemon=True).start()
    return jsonify(youtube_public(job))


@app.route("/youtube/save", methods=["POST"])
def youtube_save():
    data = request.get_json(silent=True) or {}
    song = clean_name(data.get("song"), 80)
    artist = clean_name(data.get("artist"), 60)
    with yt_lock:
        job = yt_job
        if not job or job["id"] != data.get("id"):
            return jsonify({"error": "This download is no longer running. Start it again."}), 404
        if not song:
            return jsonify({"error": "Give the song a name."}), 400
        job["wanted"] = (song, artist)
        job["error"] = None
        if job["state"] == "ready":
            youtube_finish(job)
        elif job["state"] in YT_ACTIVE:
            job["waiting"] = True  # saved as soon as the download finishes
        return jsonify(youtube_public(job))


@app.route("/youtube/cancel", methods=["POST"])
def youtube_cancel():
    data = request.get_json(silent=True) or {}
    with yt_lock:
        job = yt_job
        if not job or job["id"] != data.get("id"):
            return jsonify({"state": "none"})
        if job["state"] in YT_ACTIVE:
            job["state"] = "cancelled"
            proc = job.get("proc")
            if proc and proc.poll() is None:
                try:
                    os.killpg(proc.pid, signal.SIGTERM)  # yt-dlp and the FFmpeg it started
                except (ProcessLookupError, PermissionError):
                    pass
        elif job["state"] == "ready":
            job["state"] = "cancelled"
            youtube_cleanup(job)
        return jsonify(youtube_public(job))


switch_lock = threading.Lock()  # one speaker change at a time (a tap and the plug-in watcher)


def switch_audio(jack):
    """Change speaker while the app runs. Stops playback; returns True if the choice was saved."""
    global jackInput, music_visualizer_active, play_gen, music_paused, cached_samples, cached_path
    with switch_lock:
        play_gen += 1                      # any visualizer thread for the old mixer exits
        music_visualizer_active = False
        music_paused = False
        with mixer_lock:
            try:
                pygame.mixer.music.stop()
            except pygame.error:
                pass
            pygame.mixer.quit()
            jackInput = jack
            start_audio()
        with samples_lock:
            cached_samples, cached_path = None, None  # cached levels depend on the mixer's sample rate
        clear_display()
    try:
        save_config()
        return True
    except Exception as e:
        print(f"[Could not save {CONFIG_PATH}: {e}]")
        return False


def apply_volume():
    """The Pi stays silent while a browser plays the sound; otherwise use the volume slider."""
    try:
        pygame.mixer.music.set_volume(0.0 if listener else music_volume)
    except pygame.error:
        pass


def usb_speakers():
    """Names of the USB speakers the Pi can see, e.g. ["USB2.0 Device"]."""
    return [long_name for _, _, driver, long_name in sound_cards() if driver == "USB-Audio"]


def speaker_watch():
    """Plug in a USB speaker while there's no sound, and the Pi starts using it by itself."""
    tried = None
    while True:
        time.sleep(3)
        try:
            if audio_ok:
                tried = None
                continue
            cards = tuple(usb_speakers())
            if jackInput or listener or not cards or cards == tried:
                continue  # nothing new to try (a failed speaker is retried once it's replugged)
            tried = cards
            song = current_song_path if (pygame.mixer.music.get_busy() or music_paused) else None
            print(f"[USB speaker plugged in: {', '.join(cards)}]")
            switch_audio(False)
            if song:
                # keep the music going: with sound if the speaker worked, silently (screen only) if not
                play_song(os.path.basename(song))
        except Exception as e:
            print(f"[Speaker check failed: {e}]")


threading.Thread(target=speaker_watch, daemon=True, name="SpeakerWatch").start()


def speaker_info():
    return {
        "mode": "jack" if jackInput else "usb",
        "ok": audio_ok,
        "error": audio_error,
        "cards": usb_speakers(),
        "hasJack": has_jack(),
        "listener": listener,
    }


@app.route("/audio_mode")
def audio_mode():
    """GET /audio_mode tells where sound plays.
    ?set=usb or ?set=jack plays it on the Pi; ?set=browser&client=<id> plays it in that browser tab."""
    global listener
    choice = request.args.get("set")
    result = {}
    if choice == "browser":
        client = request.args.get("client", "")
        if re.fullmatch(r"[A-Za-z0-9_-]{1,40}", client):
            listener = client
            apply_volume()  # the Pi keeps playing silently so the screen and timing carry on
            result["saved"] = True
    elif choice in ("usb", "jack"):
        listener = None
        want_jack = choice == "jack"
        if want_jack == jackInput and audio_ok:
            apply_volume()  # same speaker and it works: carry on playing, just unmute
            result["saved"], result["restarted"] = True, False
        else:
            result["saved"], result["restarted"] = switch_audio(want_jack), True
    result.update(speaker_info())
    return jsonify(result)


AUDIO_TYPES = {".mp3": "audio/mpeg", ".wav": "audio/wav", ".flac": "audio/flac", ".m4a": "audio/mp4"}


@app.route("/audio/<path:filename>")
def song_file(filename):
    """The song itself, for a browser that plays the sound (supports seeking)."""
    ext = os.path.splitext(filename)[1].lower()
    if ext not in AUDIO_TYPES:
        return jsonify({"error": "not a song"}), 404
    # abspath: same folder the rest of the app uses (Flask would otherwise resolve it from music.py's folder)
    return send_from_directory(os.path.abspath(MUSIC_DIR), filename,
                               mimetype=AUDIO_TYPES[ext], conditional=True)


def song_length(path):
    if path not in song_lengths:
        try:
            audio = File(path)  # note: a file with no tags is falsy, so test for None
            info = getattr(audio, "info", None) if audio is not None else None
            song_lengths[path] = float(info.length) if info and info.length else 0.0
        except Exception:
            song_lengths[path] = 0.0
    return song_lengths[path]


@app.route("/state")
def player_state():
    """What the web page shows: playing/paused/stopped, song, position, volume."""
    path = current_song_path
    try:
        busy = bool(pygame.mixer.get_init()) and pygame.mixer.music.get_busy()
        pos_ms = pygame.mixer.music.get_pos() if path else -1
    except pygame.error:
        busy, pos_ms = False, -1

    if busy:
        state = "playing"
    elif path and music_paused:
        state = "paused"
    else:
        state = "stopped"

    return jsonify({
        "state": state,
        "filename": os.path.basename(path) if path else None,
        "position": max(0, pos_ms) / 1000 if state != "stopped" else 0,
        "length": song_length(path) if path else 0,
        "volume": round(music_volume, 2),
        "speaker": "jack" if jackInput else "usb",
        "speakerOk": audio_ok,
        "speakerError": audio_error,
        "speakerCards": usb_speakers(),
        "hasJack": has_jack(),
        "listener": listener,
    })


@app.route("/volume")
def set_volume():
    global music_volume
    level = request.args.get("level", type=float)
    if level is not None:
        music_volume = max(0.0, min(1.0, level))
        apply_volume()
    return jsonify({"volume": round(music_volume, 2)})


@app.route("/screen")
def screen_stream():
    """Live copy of the OLED for the web page (server-sent events).
    Sends each new frame as base64; nothing is sent while the screen is still."""
    def frames():
        seen = None
        while True:
            with frame_cond:
                if seen == frame_seq:
                    frame_cond.wait(timeout=15)
                changed = seen != frame_seq
                seen = frame_seq
                frame = last_frame
            if changed and frame is not None:
                yield "data: " + base64.b64encode(frame).decode() + "\n\n"
            else:
                yield ": still here\n\n"  # keep-alive, also lets closed tabs drop off
    return Response(frames(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
  
def preload_all_covers():
    print("[Preloading album covers before startup...]")

    songs = build_library_json()
    total = len(songs)
    cached = 0
    fetched = 0

    for s in songs:
        art = s.get("art")
        if art and art != DEFAULT_COVER:
            cached += 1
            continue

        if os.uname().machine not in ("armv7l", "aarch64"):
            continue

        artist, title, filename = s["artist"], s["title"], s["filename"]
        path = os.path.join(MUSIC_DIR, filename)
        try:
            ensure_cover_for_song(path, artist, title, filename)
            fetched += 1
        except Exception as e:
            print(f"[Cover preload error for {filename}: {e}]")

        time.sleep(0.05)

    print(f"[Cached {cached} / Fetched {fetched} / Total {total}]")

if __name__ == "__main__":
    clear_display()
    preload_all_covers()
    print("Music visualizer server running on http://0.0.0.0:5000")
    app.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False, threaded=True)
