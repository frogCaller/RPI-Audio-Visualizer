from flask import Flask, render_template, jsonify, request
from PIL import Image, ImageDraw
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


def load_config(path="config.yaml"):
    try:
        with open(path, "r") as f:
            return yaml.safe_load(f)
    except FileNotFoundError:
        print("⚠️ config.yaml not found — using defaults")
        return {"audio": {"jackInput": False}}
      
config = load_config()

jackInput = config.get("audio", {}).get("jackInput", False)

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

def buffer():
    disp.getbuffer(image)
    disp.ShowImage()

def clear_display():
    draw.rectangle((0, 0, WIDTH, HEIGHT), outline=0, fill=0)
    buffer()

    
def init_audio_jack():
    try:
        os.environ["SDL_AUDIODRIVER"] = "alsa"

        for card in range(5):
            try:
                test_dev = f"plughw:{card},0"
                pygame.mixer.init(frequency=48000, size=-16, channels=2, buffer=2048, devicename=test_dev)
                return
            except Exception as e:
                continue

        pygame.mixer.init(frequency=48000, size=-16, channels=2, buffer=2048)
    except Exception as e:
        os.environ["SDL_AUDIODRIVER"] = "dummy"
        pygame.mixer.init()
        

def init_audio():
    try:
        os.environ["SDL_AUDIODRIVER"] = "alsa"
        os.environ["AUDIODEV"] = "plughw:CARD=Audio,DEV=0"
        pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=512)
    except Exception as e:
        print(f"[Audio init failed: {e}]")

        try:
            cards = subprocess.check_output(["aplay", "-l"], text=True)
        except Exception:
            print("[Could not list ALSA devices]")
            
        os.environ["SDL_AUDIODRIVER"] = "dummy"
        time.sleep(0.5)
        pygame.mixer.init()
    

if jackInput:
    init_audio_jack()
else:
    init_audio()
    

num_bars = WIDTH // 4
bar_width = 4
decay = 0.85
bar_heights = np.zeros(num_bars)
music_visualizer_active = False
music_paused = False

def normalize(s: str) -> str:
    return s.lower().strip().translate(str.maketrans("", "", string.punctuation))

@functools.lru_cache(maxsize=1)
def get_music_library():
    os.makedirs(MUSIC_DIR, exist_ok=True)
    music_files = []
    for ext in ("*.mp3", "*.wav", "*.m4a", "*.flac"):
        music_files.extend(glob.glob(os.path.join(MUSIC_DIR, ext)))
    normalized_index = {normalize(os.path.splitext(os.path.basename(f))[0]): f for f in music_files}
    print(f"[Loaded {len(music_files)} songs]")
    return music_files, normalized_index

visualizer_thread = None

def play_song(user_input=None):
    global music_visualizer_active, bar_heights, current_index, current_song_path
    global cached_samples, cached_path

    # --- Gracefully stop any current playback ---
    music_visualizer_active = False
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
        try:
            pygame.mixer.music.load(chosen_song)
            pygame.mixer.music.play()
            print(f"{os.path.basename(chosen_song)}")
        except Exception as e:
            print(f"[Audio playback error: {e}]")

    threading.Thread(target=start_playback, daemon=True).start()

    # --- Async waveform cache (background) ---
    def preload_samples(path):
        global cached_samples, cached_path
        try:
            sound = pygame.mixer.Sound(path)
            cached_samples = pygame.sndarray.array(sound).mean(axis=1)
            cached_path = path
            print(f"[Cached samples for {os.path.basename(path)}]")
        except Exception as e:
            cached_samples = None
            cached_path = None
            print(f"[Warning: failed to cache samples: {e}]")

    threading.Thread(target=preload_samples, args=(chosen_song,), daemon=True).start()

    # --- Delay visualizer start slightly until audio ready ---
    def start_visualizer_later():
        time.sleep(0.4)  # allow mixer to settle
        if not pygame.mixer.music.get_busy():
            return
        global music_visualizer_active
        music_visualizer_active = True
        threading.Thread(
            target=music_visualizer_thread,
            args=(chosen_song,),
            daemon=True,
            name="VisualizerThread"
        ).start()

    threading.Thread(target=start_visualizer_later, daemon=True).start()

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
            threading.Thread(target=music_visualizer_thread, args=(current_song_path,), daemon=True, name="VisualizerThread").start()

        return "Resumed music."
    return "Nothing to resume."


def music_visualizer_thread(song_file):
    global bar_heights, cached_samples, cached_path
    try:
        for _ in range(20):  # up to ~2s
            if cached_path == song_file and cached_samples is not None:
                break
            time.sleep(0.1)

        if cached_samples is None or cached_path != song_file:
            sound = pygame.mixer.Sound(song_file)
            cached_samples = pygame.sndarray.array(sound).mean(axis=1)
            cached_path = song_file

        samples = cached_samples
        total_len = len(samples)
        chunk_size = max(1, total_len // 5000)

        while music_visualizer_active and pygame.mixer.music.get_busy():
            pos = pygame.mixer.music.get_pos()
            idx = int(pos / 1000 * 44100)
            chunk = samples[idx:idx + chunk_size]
            if len(chunk) == 0:
                time.sleep(0.04)
                continue

            new_heights = []
            chunk_len = len(chunk) // num_bars
            for i in range(num_bars):
                segment = chunk[i * chunk_len:(i + 1) * chunk_len]
                val = np.mean(np.abs(segment)) / 32768
                new_heights.append(val)

            bar_heights = np.maximum(new_heights, bar_heights * decay)

            clear_display()
            for i, h in enumerate(bar_heights):
                bar_h = int(h * HEIGHT * 1.5)
                if bar_h > HEIGHT: bar_h = HEIGHT
                x = i * (bar_width + 1)
                draw.rectangle([x, HEIGHT - bar_h, x + bar_width - 1, HEIGHT], fill=255)
                #draw.rectangle([x, 0, x + bar_width - 1, bar_h], fill=255)
            buffer()
            time.sleep(0.04)
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
    valid_files = [
        f for f in os.listdir(MUSIC_DIR)
        if f.lower().endswith(('.mp3', '.wav', '.flac', '.m4a'))
    ]

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
            "title": title[:30] + ("…" if len(title) > 30 else ""),
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
    save_path = os.path.join(MUSIC_DIR, file.filename)
    file.save(save_path)

    #print(f"[Uploaded new song: {file.filename}]")
    return jsonify({"success": True, "filename": file.filename})
  
@app.route("/audio_mode")
def audio_mode():
    return jsonify({"mode": "jack" if jackInput else "usb"})
  
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
    app.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False)
