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
    console.error("[Toggle error]", err);
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
  const res  = await fetch('/play');
  const name = await res.text(); 
  const filename = name.includes('.') ? name : name + '.mp3';

  updateStatus(name, "up");
  document.querySelectorAll('.song-card').forEach(card => {
    card.classList.toggle('active-song', card.dataset.filename === filename);
  });
  onSongPlay();
}

async function playSong(filename) {
    document.querySelectorAll('.song-card').forEach(card => {
        card.classList.toggle('active-song', card.dataset.filename === filename);
    });
    try {
        const res = await fetch('/play_song/' + encodeURIComponent(filename));
        const txt = await res.text();
        updateStatus(txt, "up");
    } catch (err) {
        console.error('Error playing song:', err);
    }
    if (typeof onSongPlay === "function") onSongPlay();
}


async function nextSong() {
  const res = await fetch('/next');
  const data = await res.json();

  if (data.success) {
    updateStatus(data.message, "up");
    document.querySelectorAll('.song-card').forEach(card => {
      card.classList.toggle('active-song', card.dataset.filename === data.filename);
    });
    if (typeof onSongPlay === "function") onSongPlay();
  } else {
    updateStatus(data.message);
  }
}

async function prevSong() {
  const res = await fetch('/prev');
  const data = await res.json();

  if (data.success) {
    updateStatus(data.message, "down");
    document.querySelectorAll('.song-card').forEach(card => {
      card.classList.toggle('active-song', card.dataset.filename === data.filename);
    });
    if (typeof onSongPlay === "function") onSongPlay();
  } else {
    updateStatus(data.message);
  }
}

async function loadSongs() {
    const res = await fetch('/library_json');
    const data = await res.json();
    const grid = document.getElementById('song-grid');
    grid.innerHTML = '';

    if (data.empty) {
        document.getElementById('empty-message').style.display = 'block';
        return;
    }
    document.getElementById('empty-message').style.display = 'none';

    data.songs.forEach(s => {
        const card = document.createElement('div');
        card.className = 'song-card';
        card.dataset.filename = s.filename;
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
  if (typeof loadLibrary === "function") {
    setTimeout(() => loadLibrary(), 300);
  }
});

function updateStatus(text, direction = "up") {
  const statusEl = document.getElementById("status");
  statusEl.classList.remove("animate-up", "animate-down");
  void statusEl.offsetWidth;
  statusEl.innerText = text;
  if (direction === "down") statusEl.classList.add("animate-down");
  else statusEl.classList.add("animate-up");
}

async function updatePlayButtonState() {
  try {
    const res = await fetch('/status');
    const txt = await res.text();

    const btn = document.getElementById("toggle-btn");
    const icon = btn.querySelector("i");

    if (txt.includes("Playing") || txt.includes("Now playing")) {
      icon.classList.remove("fa-play");
      icon.classList.add("fa-pause");
      isPlaying = true;
    } else {
      icon.classList.remove("fa-pause");
      icon.classList.add("fa-play");
      isPlaying = false;
    }
  } catch (err) {
    console.warn("Could not update play button state:", err);
  }
}

const fileInput = document.getElementById("file-input");

fileInput.addEventListener("change", async (e) => {
  const files = Array.from(e.target.files);
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

  // Refresh song list after upload
  await loadSongs();

  // Reset the input so selecting the same file again works
  fileInput.value = "";
});
