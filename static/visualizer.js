async function send(path) {
    document.getElementById('status').innerText = "⏳ Loading...";
    const res = await fetch(path);
    const txt = await res.text();
    document.getElementById('status').innerText = txt;
}

async function playSong(filename) {
    const res = await fetch('/play_song/' + encodeURIComponent(filename));
    const txt = await res.text();
    document.getElementById('status').innerText = txt;
}

async function loadSongs() {
    const res = await fetch('/library_json');
    const data = await res.json();
    const grid = document.getElementById('song-grid');
    grid.innerHTML = '';

    data.forEach(s => {
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
        img.addEventListener('load', () => {
            img.classList.add('loaded');
        });
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
