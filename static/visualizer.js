// RPi Music web page: library, player controls, uploads and a live view of the OLED.
(() => {
  const $ = (id) => document.getElementById(id);
  const AUDIO_RE = /\.(mp3|wav|flac|m4a)$/i;
  const PLACEHOLDER_TONES = ["#1D372D", "#26372A", "#1F3340", "#33303F", "#38352A", "#203A3A"];
  const narrow = window.matchMedia("(max-width: 899px)");

  let library = [];               // [{filename, title, artist, art}]
  const tiles = new Map();        // filename -> tile button
  let activeTile = null;
  let status = { state: "stopped", filename: null, position: 0, length: 0, volume: 1 };
  let statusAt = performance.now();
  let nowFilename = undefined;    // which song the "now playing" art is showing
  let offlineShown = false;
  let pollTimer = null;
  let volumeTouchedAt = 0;
  let playerVisible = true;

  // ---------- helpers ----------
  const fmt = (s) => {
    s = Math.max(0, Math.floor(s || 0));
    return Math.floor(s / 60) + ":" + String(s % 60).padStart(2, "0");
  };
  const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;
  const songFor = (filename) => library.find((s) => s.filename === filename);
  const stem = (filename) => (filename || "").replace(/\.[^.]+$/, "");

  function tone(text) {
    let h = 0;
    for (const c of text) h = (h * 31 + c.charCodeAt(0)) >>> 0;
    return PLACEHOLDER_TONES[h % PLACEHOLDER_TONES.length];
  }

  // cover art, or the first letter of the title on a muted tile
  function fillArt(el, song, fallbackTitle) {
    el.textContent = "";
    el.style.background = "";
    const title = (song && song.title) || fallbackTitle || "";
    const letter = () => {
      el.textContent = title.trim().charAt(0).toUpperCase() || "♪";
      el.style.background = tone(title || "?");
    };
    if (song && song.art && !song.art.endsWith("default_art.png")) {
      const img = new Image();
      img.alt = "";
      img.decoding = "async";
      img.loading = "lazy";
      img.onerror = () => { img.remove(); letter(); };
      img.src = song.art;
      el.appendChild(img);
    } else if (title) {
      letter();
    }
  }

  let toastTimer = null;
  function toast(message, ms = 3500) {
    const t = $("toast");
    t.textContent = message;
    t.classList.add("show");
    clearTimeout(toastTimer);
    if (ms) toastTimer = setTimeout(() => t.classList.remove("show"), ms);
  }

  async function api(path) {
    const res = await fetch(path, { cache: "no-store" });
    if (!res.ok) throw new Error(`${path}: ${res.status}`);
    return res;
  }

  function cantReach() {
    if (offlineShown) return;
    offlineShown = true;
    toast("Can't reach the Pi. Check that it's on and connected to Wi-Fi.", 6000);
  }

  // ---------- library ----------
  async function loadLibrary() {
    let data;
    try {
      data = await (await api("/library_json")).json();
    } catch {
      cantReach();
      return;
    }
    library = data.empty ? [] : data.songs;

    const grid = $("grid");
    grid.textContent = "";
    tiles.clear();
    activeTile = null;

    for (const song of library) {
      const tile = document.createElement("button");
      tile.type = "button";
      tile.className = "tile";
      tile.title = `${song.title} by ${song.artist || "Unknown artist"}`;

      const art = document.createElement("span");
      art.className = "tile-art";
      fillArt(art, song);

      const title = document.createElement("span");
      title.className = "tile-title";
      title.textContent = song.title;

      const artist = document.createElement("span");
      artist.className = "tile-artist";
      artist.textContent = song.artist || "Unknown artist";

      tile.append(art, title, artist);
      tile.addEventListener("click", () => playSong(song.filename));
      grid.appendChild(tile);
      tiles.set(song.filename, tile);
    }

    applySearch();
    nowFilename = undefined; // redraw now-playing art with fresh cover URLs
    render();
  }

  function applySearch() {
    const q = $("search").value.trim().toLowerCase();
    let shown = 0;
    for (const song of library) {
      const hit = !q || `${song.title} ${song.artist} ${song.filename}`.toLowerCase().includes(q);
      tiles.get(song.filename).hidden = !hit;
      if (hit) shown++;
    }
    $("empty-library").hidden = library.length > 0;
    document.querySelector(".library-bar").hidden = !library.length;
    $("empty-search").hidden = !(library.length && q && !shown);
    if (q && !shown) $("empty-search-title").textContent = `No songs match "${$("search").value.trim()}"`;
    $("count").textContent = !library.length ? "" : q ? `${shown} of ${library.length}` : plural(library.length, "song");
  }

  // ---------- player state ----------
  function position() {
    let p = status.position || 0;
    if (status.state === "playing") p += (performance.now() - statusAt) / 1000;
    return status.length ? Math.min(p, status.length) : p;
  }

  async function poll() {
    try {
      const next = await (await api("/state")).json();
      status = next;
      statusAt = performance.now();
      offlineShown = false;
    } catch {
      cantReach();
      return;
    }
    if (status.filename && !songFor(status.filename) && library.length) {
      // a song we don't know about yet (added from another device)
      loadLibrary();
    }
    render();
  }

  function startPolling() {
    if (!pollTimer) pollTimer = setInterval(poll, 2000);
  }
  function stopPolling() {
    clearInterval(pollTimer);
    pollTimer = null;
  }
  // playback starts in the background on the Pi, so check back shortly after a tap
  function checkSoon() {
    setTimeout(poll, 450);
    setTimeout(poll, 1300);
  }

  function render() {
    const song = songFor(status.filename);
    const has = !!status.filename;
    const title = song ? song.title : has ? stem(status.filename) : "Nothing playing";
    const artist = song ? song.artist || "Unknown artist" : has ? "" : "Pick a song to start";
    const playing = status.state === "playing";

    $("now-title").textContent = title;
    $("now-artist").textContent = artist;
    $("mini-title").textContent = title;
    $("mini-artist").textContent = artist;

    if (nowFilename !== status.filename) {
      nowFilename = status.filename;
      fillArt($("now-art"), song, has ? title : "");
      fillArt($("mini-art"), song, has ? title : "");
    }

    for (const id of ["play-btn", "mini-play"]) {
      const b = $(id);
      b.classList.toggle("is-playing", playing);
      b.setAttribute("aria-label", playing ? "Pause" : "Play");
      b.title = playing ? "Pause" : "Play";
    }

    // gold on the current song's tile
    const tile = tiles.get(status.filename) || null;
    if (tile !== activeTile) {
      if (activeTile) { activeTile.classList.remove("is-current"); activeTile.removeAttribute("aria-current"); }
      if (tile) { tile.classList.add("is-current"); tile.setAttribute("aria-current", "true"); }
      activeTile = tile;
    }

    if (Date.now() - volumeTouchedAt > 3000) setVolumeSlider(Math.round((status.volume ?? 1) * 100));

    document.title = playing ? `${title} - RPi Music` : "RPi Music";
    updateProgress();
    updateMini();
  }

  function updateProgress() {
    const p = position();
    const len = status.length || 0;
    $("time-pos").textContent = fmt(p);
    $("time-len").textContent = len ? fmt(len) : "--:--";
    const pct = len ? Math.min(100, (p / len) * 100) : 0;
    $("bar-fill").style.width = pct + "%";
    $("mini-bar").style.width = pct + "%";
  }
  setInterval(() => { if (status.state === "playing") updateProgress(); }, 250);

  // ---------- actions ----------
  async function playSong(filename) {
    status = { ...status, state: "playing", filename, position: 0, length: 0 };
    statusAt = performance.now();
    render();
    try {
      await api("/play_song/" + encodeURIComponent(filename));
    } catch {
      cantReach();
    }
    checkSoon();
  }

  async function togglePlay() {
    try {
      if (status.state === "playing") {
        const p = position();
        await api("/pause");
        status = { ...status, state: "paused", position: p };
      } else if (status.state === "paused") {
        await api("/resume");
        status = { ...status, state: "playing" };
      } else if (status.filename) {
        return playSong(status.filename); // song finished: play it again
      } else {
        return shuffle();
      }
      statusAt = performance.now();
      render();
    } catch {
      cantReach();
    }
    checkSoon();
  }

  async function step(direction) {
    if (!library.length) return toast("Add some songs first.");
    try {
      const data = await (await api(direction > 0 ? "/next" : "/prev")).json();
      if (data.success) {
        status = { ...status, state: "playing", filename: data.filename, position: 0, length: 0 };
        statusAt = performance.now();
        render();
      } else {
        toast(data.message);
      }
    } catch {
      cantReach();
    }
    checkSoon();
  }

  async function shuffle() {
    if (!library.length) return toast("Add some songs first.");
    try {
      await api("/play");
    } catch {
      cantReach();
    }
    checkSoon();
  }

  // ---------- volume ----------
  const volume = $("volume");
  function setVolumeSlider(v) {
    volume.value = v;
    volume.style.setProperty("--val", v + "%");
  }
  let volumeTimer = null;
  volume.addEventListener("input", () => {
    volumeTouchedAt = Date.now();
    setVolumeSlider(volume.value);
    clearTimeout(volumeTimer);
    volumeTimer = setTimeout(() => {
      api("/volume?level=" + (volume.value / 100).toFixed(2)).catch(cantReach);
    }, 120);
  });

  // ---------- adding songs ----------
  async function addFiles(fileList) {
    const files = [...fileList];
    if (!files.length) return;
    const audio = files.filter((f) => AUDIO_RE.test(f.name));
    const skipped = files.length - audio.length;
    if (!audio.length) return toast("Only MP3, WAV, FLAC and M4A files can be added.", 5000);

    let added = 0;
    const failed = [];
    for (let i = 0; i < audio.length; i++) {
      toast(audio.length > 1 ? `Adding ${i + 1} of ${audio.length}…` : `Adding ${audio[i].name}…`, 0);
      const form = new FormData();
      form.append("file", audio[i]);
      try {
        const data = await (await fetch("/upload", { method: "POST", body: form })).json();
        data.success ? added++ : failed.push(audio[i].name);
      } catch {
        failed.push(audio[i].name);
      }
    }

    await loadLibrary();
    const parts = [];
    if (added) parts.push(`Added ${plural(added, "song")}.`);
    if (failed.length) parts.push(`Couldn't add ${failed.join(", ")}.`);
    if (skipped) parts.push(`Skipped ${plural(skipped, "file")} that ${skipped === 1 ? "isn't" : "aren't"} MP3, WAV, FLAC or M4A.`);
    toast(parts.join(" "), 5000);
    if (added) setTimeout(loadLibrary, 6000); // pick up cover art fetched in the background
  }

  const fileInput = $("file-input");
  const pickFiles = () => fileInput.click();
  $("add-btn").addEventListener("click", pickFiles);
  $("empty-add-btn").addEventListener("click", pickFiles);
  fileInput.addEventListener("change", async () => {
    await addFiles(fileInput.files);
    fileInput.value = "";
  });

  const drop = $("drop");
  let dragDepth = 0;
  const hasFiles = (e) => [...(e.dataTransfer?.types || [])].includes("Files");
  window.addEventListener("dragenter", (e) => {
    if (!hasFiles(e)) return;
    e.preventDefault();
    dragDepth++;
    drop.hidden = false;
  });
  window.addEventListener("dragover", (e) => {
    if (!hasFiles(e)) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = "copy";
  });
  window.addEventListener("dragleave", (e) => {
    if (!hasFiles(e)) return;
    dragDepth = Math.max(0, dragDepth - 1);
    if (!dragDepth) drop.hidden = true;
  });
  window.addEventListener("drop", (e) => {
    if (!hasFiles(e)) return;
    e.preventDefault();
    dragDepth = 0;
    drop.hidden = true;
    addFiles(e.dataTransfer.files);
  });

  // ---------- buttons, search, keys ----------
  $("play-btn").addEventListener("click", togglePlay);
  $("mini-play").addEventListener("click", togglePlay);
  $("prev-btn").addEventListener("click", () => step(-1));
  $("next-btn").addEventListener("click", () => step(1));
  $("mini-next").addEventListener("click", () => step(1));
  $("shuffle-btn").addEventListener("click", shuffle);
  $("search").addEventListener("input", applySearch);
  $("clear-search-btn").addEventListener("click", () => {
    $("search").value = "";
    applySearch();
    $("search").focus();
  });
  $("mini-text").addEventListener("click", () => {
    const smooth = !window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    $("player").scrollIntoView({ behavior: smooth ? "smooth" : "auto", block: "start" });
  });

  // Space: play/pause, arrows: previous/next, "/": search
  document.addEventListener("keydown", (e) => {
    const tag = (e.target.tagName || "").toLowerCase();
    if (e.metaKey || e.ctrlKey || e.altKey || tag === "input" || tag === "textarea") return;
    if (e.key === " " && tag !== "button") { e.preventDefault(); togglePlay(); }
    else if (e.key === "ArrowRight") { e.preventDefault(); step(1); }
    else if (e.key === "ArrowLeft") { e.preventDefault(); step(-1); }
    else if (e.key === "/") { e.preventDefault(); $("search").focus(); }
  });

  // ---------- mini player on phones ----------
  function updateMini() {
    const show = narrow.matches && !playerVisible && !!status.filename;
    $("mini").hidden = !show;
    document.body.classList.toggle("has-mini", show);
  }
  if ("IntersectionObserver" in window) {
    new IntersectionObserver((entries) => {
      playerVisible = entries[0].isIntersecting;
      updateMini();
    }).observe($("player"));
  }
  narrow.addEventListener?.("change", updateMini);

  // ---------- live view of the OLED (128 x 32) ----------
  const canvas = $("screen");
  const ctx = canvas.getContext("2d");
  const frame = new Uint8Array(512); // 4 pages x 128 columns, bit k = row page*8 + k
  let scale = 4;
  let unlit = null;

  function sizeScreen() {
    const w = canvas.clientWidth * (window.devicePixelRatio || 1);
    scale = Math.max(3, Math.round(w / 128)); // at least 3 so pixel gaps show
    canvas.width = 128 * scale;
    canvas.height = 32 * scale;
    // sharp when the browser scales up, smooth when it scales down a little
    canvas.style.imageRendering = canvas.width > w ? "auto" : "pixelated";
    // faint grid of unlit pixels, drawn once
    unlit = document.createElement("canvas");
    unlit.width = canvas.width;
    unlit.height = canvas.height;
    const u = unlit.getContext("2d");
    const gap = pixelGap();
    u.fillStyle = "rgba(232, 238, 231, 0.045)";
    for (let y = 0; y < 32; y++) for (let x = 0; x < 128; x++) u.fillRect(x * scale, y * scale, scale - gap, scale - gap);
    drawScreen();
  }

  // a thin gap between pixels, like the real OLED
  const pixelGap = () => Math.max(1, Math.round(scale * 0.2));

  function drawScreen() {
    const size = scale - pixelGap();
    ctx.fillStyle = "#000";
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    if (unlit) ctx.drawImage(unlit, 0, 0);
    ctx.beginPath();
    for (let page = 0; page < 4; page++) {
      for (let x = 0; x < 128; x++) {
        const byte = frame[page * 128 + x];
        if (!byte) continue;
        for (let k = 0; k < 8; k++) {
          if (byte & (1 << k)) ctx.rect(x * scale, (page * 8 + k) * scale, size, size);
        }
      }
    }
    ctx.fillStyle = "#F1F7F3";
    ctx.fill();
  }

  let drawQueued = false;
  function queueDraw() {
    if (drawQueued) return;
    drawQueued = true;
    requestAnimationFrame(() => { drawQueued = false; drawScreen(); });
  }

  let stream = null;
  function connectScreen() {
    if (stream || document.hidden || !window.EventSource) return;
    stream = new EventSource("/screen");
    stream.onmessage = (e) => {
      const bin = atob(e.data);
      if (bin.length !== 512) return;
      for (let i = 0; i < 512; i++) frame[i] = bin.charCodeAt(i);
      queueDraw();
    };
  }
  function disconnectScreen() {
    if (stream) { stream.close(); stream = null; }
  }

  if ("ResizeObserver" in window) new ResizeObserver(sizeScreen).observe(canvas);
  else window.addEventListener("resize", sizeScreen);

  // stop streaming and polling while the tab is in the background, to spare the Pi
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) {
      disconnectScreen();
      stopPolling();
    } else {
      connectScreen();
      startPolling();
      poll();
    }
  });

  // ---------- start ----------
  sizeScreen();
  loadLibrary().then(poll);
  startPolling();
  connectScreen();
})();
