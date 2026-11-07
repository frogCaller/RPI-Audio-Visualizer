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

  // this tab's id, so the Pi knows which device plays the sound (kept when the tab reloads)
  const CLIENT_ID = (() => {
    const make = () => Math.random().toString(36).slice(2, 12);
    try {
      let id = sessionStorage.getItem("rpi-music-tab");
      if (!id) { id = make(); sessionStorage.setItem("rpi-music-tab", id); }
      return id;
    } catch {
      return make();
    }
  })();
  const HERE = /Mobi|Android|iPhone|iPad|iPod/i.test(navigator.userAgent) ? "this phone" : "this computer";
  const HERE_LABEL = HERE.charAt(0).toUpperCase() + HERE.slice(1);
  const listening = () => !!status.listener && status.listener === CLIENT_ID;

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

  // every 2 s, or every 1 s while this device plays the sound
  let pollGen = 0;
  function startPolling() {
    if (pollTimer !== null) return;
    const gen = ++pollGen;
    const loop = async () => {
      await poll();
      if (gen === pollGen) pollTimer = setTimeout(loop, listening() ? 1000 : 2000);
    };
    pollTimer = setTimeout(loop, 2000);
  }
  function stopPolling() {
    pollGen++;
    clearTimeout(pollTimer);
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

    if (Date.now() - volumeTouchedAt > 3000) {
      setVolumeSlider(listening() ? localVolume : Math.round((status.volume ?? 1) * 100));
    }

    document.title = playing ? `${title} - RPi Music` : "RPi Music";
    updateProgress();
    updateMini();
    if (!speakerBusy) renderSpeaker();
    syncLocal();
  }

  // ---------- where the sound plays ----------
  const SPEAKER_NAMES = { usb: "USB speaker", jack: "Headphone jack" };
  let speakerBusy = false;
  $("here-btn").textContent = HERE_LABEL;

  function renderSpeaker() {
    if (!status.speaker) return; // older server without speaker info
    const me = listening();
    for (const b of document.querySelectorAll("#speaker button")) {
      const on = b.dataset.mode === "browser" ? me : !status.listener && b.dataset.mode === status.speaker;
      b.setAttribute("aria-pressed", String(on));
    }
    // most Pis used for this (like the Zero 2 W) have no headphone jack
    $("jack-btn").hidden = status.hasJack === false && status.speaker !== "jack";

    let text = "";
    let warn = false;
    if (me && localBlocked) {
      text = `Tap play to hear it on ${HERE}.`;
    } else if (status.listener && !me) {
      text = `Sound is playing on another phone or computer. Tap ${HERE_LABEL} to hear it here instead.`;
    } else if (!status.listener && status.speakerOk === false) {
      warn = true;
      const name = SPEAKER_NAMES[status.speaker];
      if (status.speakerError === "busy") {
        text = `Another program on the Pi is using the ${name.toLowerCase()}. Restart the Pi, then tap ${name}.`;
      } else if (status.speaker === "usb") {
        text = `Can't find the USB speaker. Plug it in and tap USB speaker, or tap ${HERE_LABEL} to hear it here.`;
      } else {
        text = "Can't use the headphone jack. Tap Headphone jack to try again, or pick another option.";
      }
    }
    const note = $("speaker-note");
    note.hidden = !text;
    note.textContent = text;
    note.classList.toggle("is-warning", warn);
  }

  function applySpeakerInfo(data) {
    status = {
      ...status,
      speaker: data.mode, speakerOk: data.ok, speakerError: data.error,
      hasJack: data.hasJack, listener: data.listener,
    };
  }

  async function chooseSpeaker(mode) {
    if (speakerBusy) return;

    if (mode === "browser") {
      if (listening()) return;
      localBlocked = false;
      unlockLocal();                                 // has to happen inside the tap
      status = { ...status, listener: CLIENT_ID };
      render();                                      // starts the sound here right away
      try {
        applySpeakerInfo(await (await api("/audio_mode?set=browser&client=" + CLIENT_ID)).json());
        toast(`Sound plays on ${HERE} now.`);
      } catch {
        cantReach();
      }
      render();
      return;
    }

    const name = SPEAKER_NAMES[mode];
    const wasPlaying = status.state === "playing";
    status = { ...status, listener: null, speaker: mode, speakerOk: true };
    render();                                        // stops the sound here right away
    speakerBusy = true;
    $("speaker").setAttribute("aria-busy", "true");
    toast(`Switching to ${name}…`, 0);
    try {
      const data = await (await api("/audio_mode?set=" + mode)).json();
      applySpeakerInfo(data);
      if (!data.ok) {
        toast(mode === "usb" ? "Couldn't find the USB speaker." : "Couldn't use the headphone jack.", 5000);
      } else if (data.saved === false) {
        toast(`Switched to ${name}, but the Pi couldn't save it for next time.`, 6000);
      } else {
        toast(`Switched to ${name}.` + (data.restarted && wasPlaying ? " Press play to continue." : ""), 5000);
      }
    } catch {
      cantReach();
    }
    speakerBusy = false;
    $("speaker").removeAttribute("aria-busy");
    render();
    poll();
  }

  // ---------- playing the sound on this device ----------
  // The Pi keeps time (so its screen matches); this device plays the same song in step with it.
  const local = new Audio();
  local.preload = "auto";
  let localFile = null;      // song loaded here
  let localBlocked = false;  // the browser wants a tap before it plays sound
  let lastSeek = 0;
  let unlocked = false;
  let localVolume = 100;
  try {
    const v = parseInt(localStorage.getItem("rpi-music-volume-here"), 10);
    if (v >= 0 && v <= 100) localVolume = v;
  } catch {}
  local.volume = localVolume / 100;

  // a moment of silence played inside a tap, so phones allow sound later without another tap
  function unlockLocal() {
    if (unlocked || localFile) return;
    unlocked = true;
    const n = 800, buf = new Uint8Array(44 + n), v = new DataView(buf.buffer);
    const put = (o, s) => { for (let i = 0; i < s.length; i++) buf[o + i] = s.charCodeAt(i); };
    put(0, "RIFF"); v.setUint32(4, 36 + n, true); put(8, "WAVEfmt "); v.setUint32(16, 16, true);
    v.setUint16(20, 1, true); v.setUint16(22, 1, true); v.setUint32(24, 8000, true);
    v.setUint32(28, 8000, true); v.setUint16(32, 1, true); v.setUint16(34, 8, true);
    put(36, "data"); v.setUint32(40, n, true); buf.fill(128, 44);
    local.src = URL.createObjectURL(new Blob([buf], { type: "audio/wav" }));
    local.play().catch(() => {});
  }

  function playLocal() {
    const p = local.play();
    if (!p || !p.then) return;
    p.then(() => {
      if (localBlocked) { localBlocked = false; renderSpeaker(); }
    }).catch((err) => {
      if (err && err.name === "NotAllowedError" && listening()) { localBlocked = true; renderSpeaker(); }
    });
  }

  function syncLocal() {
    if (!listening() || !status.filename || status.state === "stopped") {
      if (!local.paused) local.pause();
      if (!listening() && localFile) {
        localFile = null;
        local.removeAttribute("src");
        local.load();
      }
      return;
    }
    if (localFile !== status.filename) {
      localFile = status.filename;
      local.src = "/audio/" + encodeURIComponent(localFile);
      local.playbackRate = 1;
    }
    if (local.readyState >= 1) {
      const target = position();
      const diff = local.currentTime - target;
      const now = performance.now();
      if (Math.abs(diff) > 0.35 && (status.state !== "playing" || now - lastSeek > 2500)) {
        local.currentTime = target;
        lastSeek = now;
        local.playbackRate = 1;
      } else if (status.state === "playing") {
        // small drift: run a touch faster or slower instead of jumping
        local.playbackRate = Math.abs(diff) < 0.04 ? 1 : diff > 0 ? 0.98 : 1.02;
      }
    }
    if (status.state === "paused") {
      if (!local.paused) local.pause();
    } else if (local.paused && !localBlocked) {
      playLocal();
    }
  }

  local.addEventListener("loadedmetadata", () => {
    if (!listening() || !localFile || local.src.startsWith("blob:")) return;
    local.currentTime = position();
    lastSeek = performance.now();
  });
  local.addEventListener("error", () => {
    if (listening() && localFile) toast(`This song can't play on ${HERE}.`, 5000);
  });
  setInterval(() => { if (listening()) syncLocal(); }, 500);

  for (const b of document.querySelectorAll("#speaker button")) {
    b.addEventListener("click", () => chooseSpeaker(b.dataset.mode));
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
    // the Pi is playing, but this device was waiting for a tap before making sound
    if (listening() && status.state === "playing" && local.paused) {
      localBlocked = false;
      playLocal();
      renderSpeaker();
      return;
    }
    let path;
    if (status.state === "playing") {
      status = { ...status, state: "paused", position: position() };
      path = "/pause";
    } else if (status.state === "paused") {
      status = { ...status, state: "playing", position: position() };
      path = "/resume";
    } else if (status.filename) {
      return playSong(status.filename); // song finished: play it again
    } else {
      return shuffle();
    }
    statusAt = performance.now();
    render(); // pauses or resumes the sound here straight away
    try {
      await api(path);
    } catch {
      cantReach();
    }
    checkSoon();
  }

  async function step(direction) {
    if (!library.length) return toast("Add some songs first.");
    if (listening()) unlockLocal();
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
    if (listening()) unlockLocal();
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
    if (listening()) {
      // this device's own volume; the Pi's volume stays as it was
      localVolume = Number(volume.value);
      local.volume = localVolume / 100;
      try { localStorage.setItem("rpi-music-volume-here", String(localVolume)); } catch {}
      return;
    }
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

  // ---------- getting a song from YouTube ----------
  const yt = {
    dialog: $("yt-dialog"), form: $("yt-form"), url: $("yt-url"), get: $("yt-get"),
    link: $("yt-link-row"), job: $("yt-job"), status: $("yt-status"), bar: $("yt-bar"),
    song: $("yt-song"), artist: $("yt-artist"), file: $("yt-filename"),
    error: $("yt-error"), save: $("yt-save"), cancel: $("yt-cancel"),
  };
  const YT_RUNNING = ["starting", "downloading", "converting"];
  const ytActive = (j) => !!j && (YT_RUNNING.includes(j.state) || j.state === "ready");
  let ytJob = null;     // latest state of this page's download, from the Pi
  let ytTimer = null;
  let ytEdited = { song: false, artist: false };
  let ytMissing = [];

  async function ytPost(path, body) {
    const res = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    return { ok: res.ok, data: await res.json().catch(() => ({})) };
  }

  // same clean-up the Pi does, so the preview matches the saved file
  const ytClean = (s) => s.replace(/[\\/:*?"<>|]/g, "").replace(/ - /g, " – ").replace(/\s+/g, " ").trim();
  function ytFileName() {
    const song = ytClean(yt.song.value), artist = ytClean(yt.artist.value);
    return song ? (artist ? `${song} - ${artist}.mp3` : `${song}.mp3`) : "";
  }

  function renderYt(message) {
    const j = ytJob;
    const active = ytActive(j);
    yt.link.hidden = active;
    yt.job.hidden = !active;
    yt.save.hidden = !active;
    yt.cancel.textContent = active ? "Cancel" : "Close";
    yt.get.disabled = ytMissing.length > 0;
    const err = message || (j && j.error) || "";
    yt.error.hidden = !err;
    yt.error.textContent = err;
    if (!active) return;

    // fill in the names YouTube gives, unless you've already typed your own
    if (!ytEdited.song && j.song) yt.song.value = j.song;
    if (!ytEdited.artist && j.artist) yt.artist.value = j.artist;

    const pct = Math.round(j.percent || 0);
    let text;
    if (j.state === "starting") text = "Looking up the song…";
    else if (j.state === "downloading") text = `Downloading… ${pct}%`;
    else if (j.state === "converting") text = "Converting to MP3…";
    else text = "Ready. Check the name, then save it.";
    if (j.waiting && j.state !== "ready") text += " It will be saved when it's done.";
    yt.status.textContent = text;
    yt.bar.style.width = (j.state === "starting" ? 0 : j.state === "downloading" ? pct : 100) + "%";

    const name = ytFileName();
    yt.file.textContent = name || "…";
    yt.save.textContent = j.state === "ready" ? "Save song" : "Save when ready";
    yt.save.disabled = !name || !!j.waiting;
  }

  // returns true when this download is over (saved, failed or stopped)
  function ytSettle() {
    const j = ytJob;
    if (!j) return true;
    if (j.state === "saved") {
      ytJob = null;
      try { sessionStorage.removeItem("rpi-music-yt"); } catch {}
      yt.dialog.close();
      toast(`Added "${(j.filename || "").replace(/\.mp3$/i, "")}".`, 5000);
      loadLibrary();
      setTimeout(loadLibrary, 6000); // pick up cover art fetched in the background
      return true;
    }
    if (j.state === "failed" || j.state === "cancelled" || j.state === "none") {
      const msg = j.state === "failed" ? j.error : "The download was stopped.";
      ytJob = null;
      renderYt(msg);
      return true;
    }
    return false;
  }

  function ytPoll() {
    clearTimeout(ytTimer);
    ytTimer = setTimeout(async () => {
      if (!ytJob) return;
      try {
        const data = await (await api("/youtube")).json();
        ytJob = data.id === ytJob.id ? data : { state: "none" };
      } catch {
        return ytPoll(); // the Pi is busy or briefly unreachable: keep trying
      }
      if (ytSettle()) return;
      renderYt();
      if (YT_RUNNING.includes(ytJob.state)) ytPoll();
    }, 800);
  }

  async function ytStart() {
    const url = yt.url.value.trim();
    if (!url) {
      renderYt("Paste a link to a YouTube video first.");
      yt.url.focus();
      return;
    }
    yt.get.disabled = true;
    ytEdited = { song: false, artist: false };
    yt.song.value = "";
    yt.artist.value = "";
    try {
      const { ok, data } = await ytPost("/youtube/start", { url });
      if (!ok) {
        renderYt(data.error || "Couldn't start the download.");
        return;
      }
      ytJob = data;
      try { sessionStorage.setItem("rpi-music-yt", data.id); } catch {}
      renderYt();
      yt.song.focus();
      ytPoll();
    } catch {
      renderYt("Can't reach the Pi. Check that it's on and connected to Wi-Fi.");
    } finally {
      yt.get.disabled = ytMissing.length > 0;
    }
  }

  async function ytSave() {
    if (!ytJob) return;
    if (!ytFileName()) {
      renderYt("Give the song a name.");
      yt.song.focus();
      return;
    }
    yt.save.disabled = true;
    try {
      const { ok, data } = await ytPost("/youtube/save", {
        id: ytJob.id, song: yt.song.value, artist: yt.artist.value,
      });
      if (!ok) {
        renderYt(data.error || "Couldn't save the song.");
        return;
      }
      ytJob = data;
      if (ytSettle()) return;
      renderYt();
      if (YT_RUNNING.includes(ytJob.state)) ytPoll();
    } catch {
      renderYt("Can't reach the Pi. Check that it's on and connected to Wi-Fi.");
    }
  }

  function ytClose() {
    const j = ytJob;
    if (ytActive(j)) ytPost("/youtube/cancel", { id: j.id }).catch(() => {}); // deletes what was downloaded
    ytJob = null;
    clearTimeout(ytTimer);
    try { sessionStorage.removeItem("rpi-music-yt"); } catch {}
    yt.dialog.close();
  }

  async function ytOpen() {
    if (!yt.dialog.open) yt.dialog.showModal();
    if (!ytJob) {
      yt.url.value = "";
      renderYt();
      yt.url.focus();
    }
    try {
      const data = await (await api("/youtube")).json();
      ytMissing = data.missing || [];
      let mine = null;
      try { mine = sessionStorage.getItem("rpi-music-yt"); } catch {}
      if (!ytJob && ytActive(data) && data.id === mine) {
        ytJob = data; // this tab's download, still going after a reload
        renderYt();
        ytPoll();
      } else if (!ytJob) {
        renderYt(ytMissing.length
          ? `The Pi needs ${ytMissing.join(" and ")} for this. On the Pi, run "sudo bash setup.sh" again, then restart the app.`
          : "");
      }
    } catch {
      if (!ytJob) renderYt("Can't reach the Pi. Check that it's on and connected to Wi-Fi.");
    }
  }

  yt.form.addEventListener("submit", (e) => {
    e.preventDefault();
    if (ytActive(ytJob)) ytSave(); // Enter in the name boxes saves
    else ytStart();
  });
  yt.save.addEventListener("click", ytSave);
  yt.cancel.addEventListener("click", ytClose);
  yt.dialog.addEventListener("cancel", (e) => { e.preventDefault(); ytClose(); }); // Esc key
  for (const key of ["song", "artist"]) {
    yt[key].addEventListener("input", () => { ytEdited[key] = true; renderYt(); });
  }
  $("yt-btn").addEventListener("click", ytOpen);
  $("empty-yt-btn").addEventListener("click", ytOpen);

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
    if (document.querySelector("dialog[open]")) return;
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
  // (keep polling if this device is playing the sound, so it stays in step)
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) {
      disconnectScreen();
      if (!listening()) stopPolling();
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
  // reopen the YouTube dialog if this tab was in the middle of a download
  try {
    const mine = sessionStorage.getItem("rpi-music-yt");
    if (mine) {
      api("/youtube").then((r) => r.json()).then((d) => {
        if (d.id === mine && ytActive(d)) ytOpen();
        else sessionStorage.removeItem("rpi-music-yt");
      }).catch(() => {});
    }
  } catch {}
})();
