let isPlaying = false;

async function togglePlayPause() {
  const btn = document.getElementById("toggle-btn");
  const icon = btn.querySelector("i");

  try {
    if (isPlaying) {
      await fetch("/pause");
      icon.classList.remove("fa-pause");
      icon.classList.add("fa-play");
      isPlaying = false;
    } else {
      await fetch("/resume");
      icon.classList.remove("fa-play");
      icon.classList.add("fa-pause");
      isPlaying = true;
    }
  } catch (err) {
    console.error("[⚠️ Toggle error]", err);
  }
}

function onSongPlay() {
  const btn = document.getElementById("toggle-btn");
  const icon = btn.querySelector("i");
  icon.classList.remove("fa-play");
  icon.classList.add("fa-pause");
  isPlaying = true;
}

function onSongStop() {
  const btn = document.getElementById("toggle-btn");
  const icon = btn.querySelector("i");
  icon.classList.remove("fa-pause");
  icon.classList.add("fa-play");
  isPlaying = false;
}

async function send(path) {
  document.getElementById('status').innerText = "⏳ Loading...";
  const res = await fetch(path);
  const txt = await res.text();
  document.getElementById('status').innerText = txt;

  if (path.includes('/stop')) onSongStop();
  else if (path.includes('/play') || path.includes('/resume')) onSongPlay();
}

async function playSong(filename) {
    const res = await fetch('/play_song/' + encodeURIComponent(filename));
    const txt = await res.text();
    document.getElementById('status').innerText = txt;

    if (typeof onSongPlay === "function") onSongPlay();
}

async function nextSong() {
  const res = await fetch('/next');
  const txt = await res.text();
  document.getElementById('status').innerText = txt;

  if (typeof onSongPlay === "function") onSongPlay();
}

async function prevSong() {
  const res = await fetch('/prev');
  const txt = await res.text();
  document.getElementById('status').innerText = txt;

  if (typeof onSongPlay === "function") onSongPlay();
}

async function loadSongs() {
    const res = await fetch('/library_json');
    const data = await res.json();
    const grid = document.getElementById('song-grid');
    grid.innerHTML = '';

    // Handle empty case
    if (data.empty) {
        document.getElementById('empty-message').style.display = 'block';
        return;
    }
    document.getElementById('empty-message').style.display = 'none';

    // Use data.songs instead of data
    data.songs.forEach(s => {
        const card = document.createElement('div');
        card.className = 'song-card';
        card.onclick = () => playSong(s.filename);

        const art = document.createElement('div');
        art.className = 'art';

        if (s.art && s.art !== "/static/covers/default_art.png") {
            art.innerHTML = `<img src="${s.art}" alt="cover for ${s.title}" loading="lazy">`;
        } else {
            art.textContent = '🎵';
        }

        const info = document.createElement('div');
        info.className = 'info';
        info.innerHTML = `
            <div class="title" title="${s.title}">${s.title}</div>
            <div class="artist">${s.artist || 'Unknown'}</div>
        `;
        card.appendChild(art);
        card.appendChild(info);
        grid.appendChild(card);
    });

    document.querySelectorAll('img[loading="lazy"]').forEach(img => {
        img.addEventListener('load', () => img.classList.add('loaded'));
    });
}
async function refreshStatus() {
    const res = await fetch('/status');
    const txt = await res.text();
    document.getElementById('status').innerText = txt;
}
// Auto-refresh every 5 seconds
window.addEventListener('load', () => {
    loadSongs();
    refreshStatus();
});

  
const dropZone = document.getElementById("drop-zone");

window.addEventListener("dragover", (e) => {
  e.preventDefault();
  dropZone.style.display = "block";
});

window.addEventListener("dragleave", (e) => {
  if (e.target === dropZone) dropZone.style.display = "none";
});

window.addEventListener("drop", async (e) => {
  e.preventDefault();
  dropZone.style.display = "none";

  const files = Array.from(e.dataTransfer.files);
  if (!files.length) return;

  for (const file of files) {
    if (!file.name.match(/\.(mp3|wav|flac|m4a)$/i)) {
      alert(`Skipping unsupported file: ${file.name}`);
      continue;
    }

    const formData = new FormData();
    formData.append("file", file);

    try {
      const res = await fetch("/upload", { method: "POST", body: formData });
      const data = await res.json();

      if (data.success) {
        console.log(`[✅ Uploaded] ${file.name}`);
      } else {
        console.error(`[❌ Failed] ${file.name}: ${data.message}`);
      }
    } catch (err) {
      console.error(`[⚠️ Error uploading ${file.name}]`, err);
    }
  }
  // Instantly reload the song list after uploads
  if (typeof loadLibrary === "function") {
    setTimeout(() => loadLibrary(), 300); // small delay for safety
  }
});
