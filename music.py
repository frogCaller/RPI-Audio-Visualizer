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

# --- OLED Setup ---
disp = SSD1305.SSD1305()
disp.Init()
disp.clear()
WIDTH, HEIGHT = disp.width, disp.height
image = Image.new("1", (WIDTH, HEIGHT))
draw = ImageDraw.Draw(image)

MUSIC_DIR = 'Music'
COVERS_DIR = 'static/covers'
DEFAULT_COVER = '/static/covers/default_art.png'
os.makedirs(MUSIC_DIR, exist_ok=True)
os.makedirs(COVERS_DIR, exist_ok=True)
current_index = 0
current_song_path = None

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

def init_audio():
    try:
        os.environ["SDL_AUDIODRIVER"] = "alsa"
        os.environ["AUDIODEV"] = "plughw:CARD=Audio,DEV=0"
        pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=512)
    except Exception as e:
        print(f"[Audio init failed: {e}]")

        # --- Try detecting available ALSA devices automatically ---
        try:
            cards = subprocess.check_output(["aplay", "-l"], text=True)
            print("[Detected sound devices:]")
            print(cards)
        except Exception:
            print("[Could not list ALSA devices]")

        #print("[Falling back to dummy (silent mode)]")
        os.environ["SDL_AUDIODRIVER"] = "dummy"
        time.sleep(0.5)
        pygame.mixer.init()
        #print("[Running in silent mode (no audio output)]")
        
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

    music_visualizer_active = False
    pygame.mixer.music.stop()
    time.sleep(0.2)

    bar_heights[:] = 0
    clear_display()

    music_files, normalized_index = get_music_library()
    if not music_files:
        return "[Error: No music files in ~/Music]"

    chosen_song = None
    if user_input:
        for f in music_files:
            if os.path.basename(f) == user_input:
                chosen_song = f
                break

    if not chosen_song:
        chosen_song = random.choice(music_files)

    current_song_path = chosen_song

    # --- Load + play song ---
    pygame.mixer.music.load(chosen_song)
    pygame.mixer.music.play()
    print(f"Playing: {os.path.basename(chosen_song)}")

    # --- Start visualizer ---
    music_visualizer_active = True
    visualizer_thread = threading.Thread(target=music_visualizer_thread, args=(chosen_song,), daemon=True)
    visualizer_thread.start()

    # --- Update current_index ---
    try:
        current_index = music_files.index(chosen_song)
    except ValueError:
        current_index = 0

    return f"Playing: {os.path.splitext(os.path.basename(chosen_song))[0]}"

def stop_music():
    global music_visualizer_active, bar_heights
    music_visualizer_active = False
    pygame.mixer.music.stop()
    bar_heights[:] = 0
    clear_display()
    return "Stopped music."

def pause_music():
    global music_paused
    if pygame.mixer.music.get_busy():
        pygame.mixer.music.pause()
        music_paused = True
        return "Paused music."
    return "Nothing playing."

def resume_music():
    global music_paused, music_visualizer_active
    if music_paused:
        pygame.mixer.music.unpause()
        music_paused = False
        music_visualizer_active = True
        return "Resumed music."
    return "Nothing to resume."

def music_visualizer_thread(song_file):
    global bar_heights
    try:
        sound = pygame.mixer.Sound(song_file)
        samples = pygame.sndarray.array(sound).mean(axis=1)
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

# --- SILENCE ACCESS LOGS ---
import logging
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)
# ---------------------------

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
        return "No songs found."
    current_index = (current_index + 1) % len(music_files)
    return play_song(os.path.basename(music_files[current_index]))

@app.route("/prev")
def prev_song():
    global current_index
    music_files, _ = get_music_library()
    if not music_files:
        return "No songs found."
    current_index = (current_index - 1) % len(music_files)
    return play_song(os.path.basename(music_files[current_index]))
  
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

    if not hasattr(app, "cover_cache"):
        app.cover_cache = set()
    if not hasattr(app, "cover_failed"):
        app.cover_failed = set()

    for fname in os.listdir(MUSIC_DIR):
        if not fname.lower().endswith(('.mp3', '.wav', '.flac', '.m4a')):
            continue

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
                # Avoid duplicate queue items
                if not any(task[1] == artist and task[2] == title for task in list(cover_queue.queue)):
                    #print(f"[Queuing cover fetch for {artist} - {title}]")
                    cover_queue.put((path, artist, title, fname))
                    app.cover_failed.add(key)  # mark as attempted once

        songs.append({
            "filename": fname,
            "title": title[:30] + ("…" if len(title) > 30 else ""),
            "artist": artist,
            "art": art
        })

    return jsonify(songs)
  
@app.route("/status")
def current_status():
    global current_song_path

    if pygame.mixer.music.get_busy() and current_song_path:
        song_name = os.path.splitext(os.path.basename(current_song_path))[0]
        return f"Playing: {song_name}"
    elif current_song_path:
        song_name = os.path.splitext(os.path.basename(current_song_path))[0]
        return f"Paused: {song_name}"
    else:
        return "Stopped."
  
@app.route("/play_song/<filename>")
def play_specific_song(filename):
    return play_song(filename)

if __name__ == "__main__":
    clear_display()
    print("Music visualizer server running on http://0.0.0.0:5000")
    app.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False)
