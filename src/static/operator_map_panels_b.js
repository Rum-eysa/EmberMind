/*
 * operator_map monolith split (code-quality audit). Behaviour-preserving:
 * same statements, same order, one shared global lexical scope across
 * classic scripts. panels B: active layers, risk, ui-states, silent, map-tools, timeline, multifire, municipality, notifications, sitrep, handover, webhooks, audit, signal, seasonal, IFA, silent-risk zones.
 */
"use strict";
  async function refreshActiveLayers() {
    for (const meta of catalogLayers) {
      const layer = layers[meta.key];
      if (layer && map.hasLayer(layer)) {
        try { await loadLayer(meta.key); }
        catch (err) { statusLayerError(err); }
      }
    }
  }
  function applyLiveUpdates(updates) {
    if (!updates || !updates.length) return;
    for (const u of updates) { if (u.id > liveLastId) liveLastId = u.id; }
    flashLive(updates);
    // EM-032: risk eşik aşımı uyarıları görsel bant + sesli bildirim üretir.
    const alerts = updates.filter((u) => u.kind === "alert");
    if (alerts.length) {
      raiseAlertNotification(alerts);
    }
    // Birçok güncellemeyi tek katman yenilemesine indirge (debounce).
    if (liveRefreshTimer) return;
    liveRefreshTimer = setTimeout(() => {
      liveRefreshTimer = null;
      refreshActiveLayers();
    }, 800);
  }

  // --- EM-032: eşik aşımı uyarısı (görsel + sesli, histerezis beslemede) -----
  function primeAudio() {
    // WebAudio yalnızca bir kullanıcı hareketinden sonra açılabilir.
    if (alertAudioCtx || typeof (window.AudioContext || window.webkitAudioContext) === "undefined") {
      return;
    }
    try {
      const Ctx = window.AudioContext || window.webkitAudioContext;
      alertAudioCtx = new Ctx();
    } catch (err) { alertAudioCtx = null; }
  }
  function beepTwice() {
    if (!alertSoundOn) return;
    primeAudio();
    if (!alertAudioCtx) return;
    try {
      if (alertAudioCtx.state === "suspended") { alertAudioCtx.resume(); }
      const now = alertAudioCtx.currentTime;
      [0, 0.28].forEach((offset) => {
        const osc = alertAudioCtx.createOscillator();
        const gain = alertAudioCtx.createGain();
        osc.connect(gain); gain.connect(alertAudioCtx.destination);
        osc.type = "square"; osc.frequency.value = 880;
        gain.gain.setValueAtTime(0.0001, now + offset);
        gain.gain.exponentialRampToValueAtTime(0.2, now + offset + 0.02);
        gain.gain.exponentialRampToValueAtTime(0.0001, now + offset + 0.22);
        osc.start(now + offset); osc.stop(now + offset + 0.24);
      });
    } catch (err) { /* sesletim başarısız olursa sessiz devam */ }
  }
  function raiseAlertNotification(alerts) {
    const banner = document.getElementById("alert-banner");
    const last = alerts[alerts.length - 1];
    const text = (last.message || last.title || "Risk eşik aşımı");
    if (banner) {
      banner.textContent = "⚠ " + text;
      banner.classList.add("show");
      clearTimeout(raiseAlertNotification._t);
      raiseAlertNotification._t = setTimeout(() => banner.classList.remove("show"), 12000);
    }
    beepTwice();
    if (typeof navigator !== "undefined" && navigator.vibrate) {
      try { navigator.vibrate([200, 100, 200]); } catch (err) { /* yoksay */ }
    }
  }
  async function evaluateRiskAlerts() {
    // Servisteki seviye eskalasyonunu yokla; uyarılar canlı beslemeden akıyor.
    try {
      await fetch("/api/v1/risk-index/alerts/evaluate", { method: "POST" });
    } catch (err) { /* çevrimdışıysa sessiz */ }
  }
  function startLive() {
    if (typeof WebSocket === "undefined") { startLivePoll(); return; }
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const url = `${proto}://${location.host}/ws/live?since=${liveLastId}`;
    setLive("warn", "● bağlanıyor…", "EM-090: canlı akışa bağlanılıyor");
    let socket;
    try { socket = new WebSocket(url); }
    catch (err) { startLivePoll(); return; }
    liveSocket = socket;
    socket.onopen = () => {
      liveDelay = 1000;
      showConnLost(false);  // EM-079: bağlantı kurulunca bandı kaldır
      setLive("on", "● canlı", "EM-090: canlı akış bağlı — sayfa yenilemeden güncellenir");
    };
    socket.onmessage = ev => {
      let frame;
      try { frame = JSON.parse(ev.data); } catch (err) { return; }
      if (frame.type === "snapshot" || frame.type === "update") {
        applyLiveUpdates(frame.updates);
        if (frame.last_id > liveLastId) liveLastId = frame.last_id;
      }
    };
    socket.onclose = () => {
      if (liveClosed) return;
      showConnLost(true);  // EM-079: 'bağlantı kesildi' bandı (yalnızca koptuysa)
      setLive("warn", "● yeniden bağlanıyor…",
        "EM-090: bağlantı koptu, kaçırılan güncellemeler telafi edilecek");
      setTimeout(startLive, liveDelay);
      liveDelay = Math.min(liveDelay * 2, 30000);
    };
    socket.onerror = () => { try { socket.close(); } catch (err) { /* yoksay */ } };
  }
  function startLivePoll() {
    // WebSocket yoksa aynı telafi semantiğiyle REST yoklamasına düş.
    async function tick() {
      try {
        const res = await fetch(`/api/v1/live/updates?since=${liveLastId}`);
        if (res.ok) {
          const frame = await res.json();
          applyLiveUpdates(frame.updates);
          if (frame.last_id > liveLastId) liveLastId = frame.last_id;
          showConnLost(false);
          setLive("on", "● canlı (yoklama)", "EM-090: WebSocket yedeği — REST yoklaması");
        }
      } catch (err) { showConnLost(true); }
      setTimeout(tick, 5000);
    }
    tick();
  }

  // EM-079: panel durum kataloğu (yükleme/boş/hata) + bağlantı-kesildi bandı.
  async function loadUiStates() {
    try {
      const res = await fetch("/api/v1/ui-states");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      for (const p of data.panels || []) { UI_STATES.panels[p.key] = p; }
      UI_STATES.connection = data.connection || null;
      const retry = document.getElementById("conn-lost-retry");
      if (retry && UI_STATES.connection) {
        retry.textContent = UI_STATES.connection.retry_label || "Yeniden dene";
      }
    } catch (err) {
      // Katalog gelmezse paneller kendi yerel metinlerini kullanmaya devam eder.
      setStatus(`Durum kataloğu alınamadı: ${err.message}`);
    }
  }
  function uiPanel(key) {
    return UI_STATES.panels[key] || null;
  }
  // Katman yükleme hatasında durum satırı: ne olduğu + ne yapılacağı (EM-079).
  function statusLayerError(err) {
    const state = uiPanel("map_layers");
    const what = state ? state.error : "Katman yüklenemedi.";
    const action = state ? state.error_action : "Yeniden deneyin.";
    setStatus(`${what} ${err.message} — ${action}`);
  }
  // Yükleme iskeleti: panel gövdesine kısa bir 'yükleniyor' satırı koyar.
  function panelLoading(box, key) {
    if (!box) return;
    const state = uiPanel(key);
    const text = state ? state.loading : "Yükleniyor…";
    box.innerHTML = `<div class="skel">${escapeHtml(text)}</div>`;
  }
  // Boş durum: katalogdaki 'boş' metnini kullanır.
  function panelEmpty(box, key, fallback) {
    if (!box) return;
    const state = uiPanel(key);
    const text = (state && state.empty) ? state.empty : (fallback || "Kayıt yok.");
    box.innerHTML = `<div class="empty">${escapeHtml(text)}</div>`;
  }
  // Hata: hem ne olduğu hem ne yapılacağı (katalogdaki error + error_action).
  function panelErrorHtml(key, detail) {
    const state = uiPanel(key);
    const what = state ? state.error : "Bir hata oluştu.";
    const action = state ? state.error_action : "Lütfen yeniden deneyin.";
    const extra = detail ? ` (${escapeHtml(detail)})` : "";
    return `<div class="panel-err">${escapeHtml(what)}${extra}`
      + `<span class="act">${escapeHtml(action)}</span></div>`;
  }
  // Bağlantı-kesildi bandı: canlı akış sağlığına göre göster/gizle.
  function showConnLost(on) {
    const band = document.getElementById("conn-lost");
    if (!band) return;
    const conn = UI_STATES.connection;
    if (!on) { band.classList.remove("show"); return; }
    if (conn) {
      document.getElementById("conn-lost-title").textContent = conn.title || "Bağlantı kesildi";
      document.getElementById("conn-lost-text").textContent = conn.text || "";
      document.getElementById("conn-lost-hint").textContent = conn.hint || "";
    }
    band.classList.add("show");
  }

  // EM-078: sessiz bölge güven paneli — bant filtresi, sıralı liste, harita senkron seçim.
  const SILENT_API = "/api/v1/silent-zones";
  const SILENT_BAND_COLORS = { high: "#2e7d32", moderate: "#f9a825", low: "#c62828" };
  async function toggleSilentPanel() {
    const panel = document.getElementById("silent-panel");
    if (silentPanelOpen) {
      silentPanelOpen = false;
      panel.style.display = "none";
      if (silentHighlight) { map.removeLayer(silentHighlight); silentHighlight = null; }
      return;
    }
    silentPanelOpen = true;
    panel.style.display = "block";
    await loadSilentZones();
  }
  async function loadSilentZones() {
    const band = document.getElementById("silent-filter").value || "";
    const url = band ? `${SILENT_API}?confidence=${encodeURIComponent(band)}` : SILENT_API;
    const box = document.getElementById("silent-list");
    panelLoading(box, "silent_zones");
    try {
      const res = await fetch(url);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      renderSilentList(data);
    } catch (err) {
      if (box) { box.innerHTML = panelErrorHtml("silent_zones", err.message); }
      setStatus(`Sessiz bölge paneli açılamadı: ${err.message}`);
    }
  }
  function renderSilentList(data) {
    const box = document.getElementById("silent-list");
    const countEl = document.getElementById("silent-count");
    silentRegions = (data.regions || []).slice();
    box.innerHTML = "";
    const bands = data.band_counts || {};
    if (countEl) {
      countEl.textContent = data.count
        ? `(${data.count} / ${data.count_active_regions})`
        : "(0)";
    }
    if (!silentRegions.length) {
      panelEmpty(box, "silent_zones", "Bu filtrede sessiz bölge yok.");
      return;
    }
    for (const region of silentRegions) {
      const row = document.createElement("div");
      row.className = "item";
      row.setAttribute("role", "button");
      row.tabIndex = 0;
      const color = SILENT_BAND_COLORS[region.confidence_band] || "#9e9e9e";
      const near = region.nearest_fire_km != null
        ? ` &middot; ${escapeHtml(region.nearest_fire_km)} km` : "";
      const overlap = region.overlapping_fire_count
        ? ` <span class="cb-low">⚠${escapeHtml(region.overlapping_fire_count)} yangın</span>` : "";
      row.innerHTML =
        `<span class="dot" style="background:${color}"></span>`
        + `<span><b class="nm">${escapeHtml(region.region_name || "isimsiz")}</b>`
        + `${overlap}<br><span class="cb-${escapeHtml(region.confidence_band)}">`
        + `${escapeHtml(region.confidence_label)} · ${escapeHtml(region.confidence)}${escapeHtml(near)}</span></span>`;
      const select = () => focusSilentRegion(region, row);
      row.addEventListener("click", select);
      row.addEventListener("keydown", e => {
        if (e.key === "Enter" || e.key === " ") { e.preventDefault(); select(); }
      });
      box.appendChild(row);
    }
    const bandsHint = `yüksek:${bands.high || 0} orta:${bands.moderate || 0} düşük:${bands.low || 0}`;
    setStatus(`Sessiz bölgeler — ${bandsHint} — ${data.attribution}`);
  }
  function focusSilentRegion(region, row) {
    for (const el of document.querySelectorAll("#silent-panel .item.sel")) {
      el.classList.remove("sel");
    }
    if (row) row.classList.add("sel");
    // Harita senkron seçim: bölge sınırlarına odaklan ve vurgula.
    const bounds = L.latLngBounds(
      [[region.min_lat, region.min_lon], [region.max_lat, region.max_lon]]);
    map.fitBounds(bounds, { padding: [40, 40] });
    if (silentHighlight) { map.removeLayer(silentHighlight); }
    silentHighlight = L.rectangle(bounds, {
      color: "#616161", weight: 3, dashArray: "6 4",
      fillColor: "#9e9e9e", fillOpacity: 0.15,
    }).addTo(map);
    silentHighlight.bindPopup(
      `<b>${escapeHtml(region.region_name || "sessiz bölge")}</b><br>`
      + `Güven: ${escapeHtml(region.confidence_label)} (${escapeHtml(region.confidence)})`);
    silentHighlight.openPopup();
  }

  // EM-080: harita altlığı seçimi + yer/koordinat arama + mesafe/alan ölçüm aracı.
  const MAPTOOL_API = "/api/v1/map";
  async function toggleMapToolPanel() {
    const panel = document.getElementById("maptool-panel");
    if (maptoolPanelOpen) {
      maptoolPanelOpen = false;
      panel.style.display = "none";
      exitMeasure();
      return;
    }
    maptoolPanelOpen = true;
    panel.style.display = "block";
    await loadMapConfig();
  }
  async function loadMapConfig() {
    const sel = document.getElementById("mt-basemap");
    try {
      const res = await fetch(`${MAPTOOL_API}/config`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      mtConfig = await res.json();
      if (sel && mtConfig.basemaps) {
        sel.innerHTML = "";
        for (const b of mtConfig.basemaps) {
          const opt = document.createElement("option");
          opt.value = b.key;
          opt.textContent = b.label;
          if (b.key === mtConfig.default_basemap) opt.selected = true;
          sel.appendChild(opt);
        }
      }
    } catch (err) {
      setStatus(`Harita aracı durumu alınamadı: ${err.message}`);
    }
  }
  // Altlık değişimi: eski katmanı kaldır, kataloğun URL/attribution/zoom'unu kur.
  function setBasemap(key) {
    const b = (mtConfig && mtConfig.basemaps || []).find(x => x.key === key);
    if (!b) return;
    if (mtBasemapLayer) map.removeLayer(mtBasemapLayer);
    mtBasemapLayer = L.tileLayer(b.url, {
      maxZoom: b.max_zoom, attribution: b.attribution,
    }).addTo(map);
  }
  // Yer adı ya da koordinat araması: sonucu listeler, seçince haritaya odaklar.
  async function runMapSearch() {
    const q = (document.getElementById("mt-query").value || "").trim();
    const box = document.getElementById("mt-results");
    if (!q) { panelEmpty(box, "map_interaction"); return; }
    panelLoading(box, "map_interaction");
    try {
      const res = await fetch(`${MAPTOOL_API}/search?q=${encodeURIComponent(q)}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      renderMapSearch(await res.json());
    } catch (err) {
      if (box) box.innerHTML = panelErrorHtml("map_interaction", err.message);
    }
  }
  function renderMapSearch(data) {
    const box = document.getElementById("mt-results");
    box.innerHTML = "";
    const results = data.results || [];
    if (!results.length) { panelEmpty(box, "map_interaction", "Eşleşen yer/koordinat yok."); return; }
    for (const r of results) {
      const row = document.createElement("div");
      row.className = "item";
      row.tabIndex = 0;
      const badge = r.match === "coordinate" ? "koord" : escapeHtml(r.country || "");
      row.innerHTML = `<span><b class="nm">${escapeHtml(r.name)}</b>`
        + ` <span class="tag">${badge}</span><br>`
        + `<span class="t2">${escapeHtml(r.display)}</span></span>`;
      const focus = () => focusSearchResult(r, row);
      row.addEventListener("click", focus);
      row.addEventListener("keydown", e => {
        if (e.key === "Enter" || e.key === " ") { e.preventDefault(); focus(); }
      });
      box.appendChild(row);
    }
  }
  function focusSearchResult(r, row) {
    for (const el of document.querySelectorAll("#maptool-panel .item.sel")) {
      el.classList.remove("sel");
    }
    if (row) row.classList.add("sel");
    const ll = [r.latitude, r.longitude];
    map.setView(ll, Math.max(map.getZoom(), 11));
    if (mtSearchMarker) map.removeLayer(mtSearchMarker);
    mtSearchMarker = L.circleMarker(ll, {
      radius: 9, color: "#0d47a1", weight: 2, fillColor: "#42a5f5", fillOpacity: 0.8,
    }).addTo(map);
    mtSearchMarker.bindPopup(`<b>${escapeHtml(r.name)}</b><br>${escapeHtml(r.display)}`);
    mtSearchMarker.openPopup();
  }
  // Ölçüm aracı: haritaya tıklanan noktalar üzerinden jeodezik mesafe/alan.
  function enterMeasure(mode) {
    mtMode = mode;
    mtPoints = [];
    if (mtMarkers) { map.removeLayer(mtMarkers); mtMarkers = null; }
    if (mtShape) { map.removeLayer(mtShape); mtShape = null; }
    document.getElementById("mt-mode-distance").classList.toggle("active", mode === "distance");
    document.getElementById("mt-mode-area").classList.toggle("active", mode === "area");
    const hint = document.getElementById("mt-measure");
    if (hint) {
      hint.textContent = mode === "distance"
        ? "Mesafe: haritada en az 2 noktaya tıklayın."
        : "Alan: haritada en az 3 köşeye tıklayın.";
    }
  }
  function exitMeasure() {
    mtMode = null;
    mtPoints = [];
    if (mtMarkers) { map.removeLayer(mtMarkers); mtMarkers = null; }
    if (mtShape) { map.removeLayer(mtShape); mtShape = null; }
    const d = document.getElementById("mt-mode-distance");
    const a = document.getElementById("mt-mode-area");
    if (d) d.classList.remove("active");
    if (a) a.classList.remove("active");
  }
  // Aktif ölçüm modundayken haritaya tıklanan noktayı toplar ve ölçümü yeniler.
  function measureClick(ev) {
    if (!mtMode || !maptoolPanelOpen) return;
    mtPoints.push([ev.latlng.lat, ev.latlng.lng]);
    if (!mtMarkers) mtMarkers = L.layerGroup().addTo(map);
    L.circleMarker(ev.latlng, {
      radius: 5, color: "#bf360c", weight: 2, fillColor: "#ff7043", fillOpacity: 0.9,
    }).addTo(mtMarkers);
    if (mtShape) { map.removeLayer(mtShape); mtShape = null; }
    if (mtMode === "area" && mtPoints.length >= 3) {
      mtShape = L.polygon(mtPoints, {
        color: "#bf360c", weight: 2, dashArray: "4 3",
        fillColor: "#ff7043", fillOpacity: 0.15,
      }).addTo(map);
    } else if (mtPoints.length >= 2) {
      mtShape = L.polyline(mtPoints, { color: "#bf360c", weight: 2, dashArray: "4 3" }).addTo(map);
    }
    postMeasure();
  }
  async function postMeasure() {
    const box = document.getElementById("mt-measure");
    if (!box) return;
    const min = mtMode === "area" ? 3 : 2;
    if (mtPoints.length < min) {
      box.textContent = mtMode === "area"
        ? `Alan için en az ${min} köşe gerekli (${mtPoints.length} tıklandı).`
        : `Mesafe için en az ${min} nokta gerekli (${mtPoints.length} tıklandı).`;
      return;
    }
    const path = mtMode === "area" ? "measure/area" : "measure/distance";
    try {
      const res = await fetch(`${MAPTOOL_API}/${path}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ points: mtPoints }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const d = await res.json();
      box.textContent = d.mode === "area"
        ? `Alan: ${d.area_ha} ha · ${d.area_km2} km² (${mtPoints.length} köşe)`
        : `Mesafe: ${d.distance_km} km (${mtPoints.length} nokta)`;
    } catch (err) {
      box.innerHTML = panelErrorHtml("map_interaction", err.message);
    }
  }

  // EM-081: olay zaman çizelgesi — canlı akış + kabul edilen öneri tek kronolojik akışta.
  const TIMELINE_API = "/api/v1/event-timeline";
  const TIMELINE_DOT_COLORS = {
    fire_event: "#c62828", forecast: "#1565c0", alert: "#e65100",
    accepted_recommendation: "#2e7d32",
  };
  function timelineClock(iso) {
    if (!iso) return "";
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return "";
    return d.toISOString().slice(11, 19);
  }
  async function toggleTimelinePanel() {
    const panel = document.getElementById("timeline-panel");
    if (timelinePanelOpen) {
      timelinePanelOpen = false;
      panel.style.display = "none";
      return;
    }
    timelinePanelOpen = true;
    panel.style.display = "block";
    await loadEventTimeline();
  }
  async function loadEventTimeline() {
    const cat = document.getElementById("timeline-filter").value || "";
    const url = cat ? `${TIMELINE_API}?category=${encodeURIComponent(cat)}` : TIMELINE_API;
    const box = document.getElementById("timeline-list");
    panelLoading(box, "event_timeline");
    try {
      const res = await fetch(url);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      renderTimelineList(data);
    } catch (err) {
      if (box) { box.innerHTML = panelErrorHtml("event_timeline", err.message); }
      setStatus(`Olay zaman çizelgesi açılamadı: ${err.message}`);
    }
  }
  function renderTimelineList(data) {
    const box = document.getElementById("timeline-list");
    const countEl = document.getElementById("timeline-count");
    const entries = data.entries || [];
    if (countEl) {
      countEl.textContent = data.total_matching
        ? `(${entries.length} / ${data.total_matching})`
        : "(0)";
    }
    if (!entries.length) {
      panelEmpty(box, "event_timeline", "Seçili filtrede olay yok.");
      return;
    }
    box.innerHTML = "";
    for (const e of entries) {
      const row = document.createElement("div");
      row.className = "item";
      const color = TIMELINE_DOT_COLORS[e.category] || "#9e9e9e";
      const evt = e.event_key ? ` \u00b7 ${escapeHtml(e.event_key)}` : "";
      const det = e.detail ? `<div class="det">${escapeHtml(e.detail)}</div>` : "";
      row.innerHTML =
        `<div class="head"><span class="dot" style="background:${color}"></span>`
        + `<span class="cat cc-${escapeHtml(e.category)}">${escapeHtml(e.category_label)}</span>`
        + `<span class="ts">${escapeHtml(timelineClock(e.at))}${evt}</span></div>`
        + `<div class="ttl">${escapeHtml(e.title)}</div>${det}`;
      box.appendChild(row);
    }
    const counts = data.category_counts || {};
    const hint = `olay:${counts.fire_event || 0} tahmin:${counts.forecast || 0}`
      + ` uyarı:${counts.alert || 0} kabul:${counts.accepted_recommendation || 0}`;
    setStatus(`Olay zaman çizelgesi — ${hint} — ${data.attribution}`);
  }

  // EM-082: çoklu yangın yönetimi — aktif yangın + konuşlanan kaynak + çakışma uyarısı.
  const MULTIFIRE_API = "/api/v1/multi-fire";
  const SEVERITY_COLORS = { critical: "#b71c1c", high: "#e65100", medium: "#f9a825", low: "#2e7d32" };
  async function toggleMultifirePanel() {
    const panel = document.getElementById("multifire-panel");
    if (multifirePanelOpen) {
      multifirePanelOpen = false;
      panel.style.display = "none";
      return;
    }
    multifirePanelOpen = true;
    panel.style.display = "block";
    await loadMultifire();
  }
  async function loadMultifire() {
    const box = document.getElementById("multifire-list");
    panelLoading(box, "multi_fire");
    const cfBox = document.getElementById("multifire-conflicts");
    if (cfBox) cfBox.innerHTML = "";
    try {
      const res = await fetch(MULTIFIRE_API);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      renderMultifire(data);
    } catch (err) {
      if (box) { box.innerHTML = panelErrorHtml("multi_fire", err.message); }
      setStatus(`Çoklu yangın paneli açılamadı: ${err.message}`);
    }
  }
  function renderMultifire(data) {
    const box = document.getElementById("multifire-list");
    const cfBox = document.getElementById("multifire-conflicts");
    const countEl = document.getElementById("multifire-count");
    const events = data.events || [];
    const totals = data.totals || {};
    if (countEl) {
      countEl.textContent = data.active_event_total
        ? `(${data.active_event_total} yangın · ${totals.committed_units || 0} konuşlu)`
        : "(0)";
    }
    box.innerHTML = "";
    if (!events.length) {
      panelEmpty(box, "multi_fire", "Şu anda aktif yangın yok.");
    } else {
      for (const ev of events) {
        const row = document.createElement("div");
        row.className = "fire";
        const color = SEVERITY_COLORS[ev.severity] || "#9e9e9e";
        const units = (ev.committed || []).map(u => `${escapeHtml(u.name)} (${escapeHtml(u.resource_type)})`).join(", ");
        const roster = ev.committed_count
          ? `<div class="units">${units}</div>`
          : `<div class="none">konuşlanmış kaynak yok</div>`;
        row.innerHTML =
          `<div class="fh"><span class="sev" style="background:${color}"></span>`
          + `<span class="nm">${escapeHtml(ev.name)}</span>`
          + `<span class="cc">${escapeHtml(ev.severity)} · ${ev.committed_count} birim</span></div>`
          + roster;
        box.appendChild(row);
      }
    }
    const cf = data.conflicts || {};
    const orphaned = cf.orphaned_units || [];
    const bases = cf.contended_bases || [];
    const under = cf.understaffed_critical || [];
    if (cfBox) {
      cfBox.innerHTML = "";
      if (!data.has_conflicts) {
        const ok = document.createElement("div");
        ok.className = "cf-ok";
        ok.textContent = "Kaynak paylaşım çakışması yok.";
        cfBox.appendChild(ok);
      } else {
        const head = document.createElement("div");
        head.className = "cf-head";
        head.textContent = `Çakışmalar (${data.conflict_count})`;
        cfBox.appendChild(head);
        for (const o of orphaned) {
          const d = document.createElement("div");
          d.className = "cf orphan";
          d.innerHTML = `⚠ Öksüz: <b>${escapeHtml(o.name)}</b} (${escapeHtml(o.status)}) → ` +
            `${escapeHtml(o.assigned_event || "?")} aktif değil`;
          cfBox.appendChild(d);
        }
        for (const b of bases) {
          const d = document.createElement("div");
          d.className = "cf base";
          d.innerHTML = `⚠ Paylaşılan üs: <b>${escapeHtml(b.base_key)}</b>` +
            ` → ${(b.events || []).map(escapeHtml).join(", ")}`;
          cfBox.appendChild(d);
        }
        for (const u of under) {
          const d = document.createElement("div");
          d.className = "cf under";
          d.innerHTML = `⚠ Eksik konuşlanmış acil: <b>${escapeHtml(u.name)}</b> (${escapeHtml(u.severity)})`;
          cfBox.appendChild(d);
        }
      }
    }
    const hint = `aktif:${totals.active_events || 0} meşgul:${totals.busy_units || 0}`
      + ` müsait:${totals.available_units || 0} çakışma:${data.conflict_count || 0}`;
    setStatus(`Çoklu yangın yönetimi — ${hint} — ${data.attribution}`);
  }

  // EM-083: salt okunur belediye görünümü — bölge için sadeleştirilmiş izleme.
  const BELEDIYE_API = "/api/v1/municipality-view";
  async function toggleBelediyePanel() {
    const panel = document.getElementById("belediye-panel");
    if (belediyePanelOpen) {
      belediyePanelOpen = false;
      panel.style.display = "none";
      return;
    }
    belediyePanelOpen = true;
    panel.style.display = "block";
    await loadBelediye();
  }
  async function loadBelediye() {
    const box = document.getElementById("belediye-list");
    panelLoading(box, "municipality_view");
    const head = document.getElementById("belediye-headline");
    if (head) head.innerHTML = "";
    const cap = document.getElementById("belediye-capacity");
    if (cap) cap.textContent = "";
    try {
      const res = await fetch(BELEDIYE_API);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      renderBelediye(data);
    } catch (err) {
      if (box) { box.innerHTML = panelErrorHtml("municipality_view", err.message); }
      setStatus(`Belediye görünümü alınamadı: ${err.message}`);
    }
  }
  function renderBelediye(data) {
    const box = document.getElementById("belediye-list");
    const head = document.getElementById("belediye-headline");
    const cap = document.getElementById("belediye-capacity");
    const countEl = document.getElementById("belediye-count");
    const region = data.region || {};
    const headline = data.headline || {};
    const fires = data.fires || [];
    const regEl = document.getElementById("belediye-region");
    if (regEl) {
      regEl.textContent = `Salt okunur · ${escapeHtml(region.name || "bölge")}`
        + ` · ${headline.active_fire_count || 0} aktif yangın`;
    }
    if (countEl) {
      countEl.textContent = headline.active_fire_count
        ? `(${headline.active_fire_count})` : "(0)";
    }
    if (head) {
      const severe = (headline.most_severe === "critical"
        || headline.most_severe === "high");
      head.className = "head " + (headline.active_fire_count ? (severe ? "hot" : "") : "calm");
      head.textContent = headline.status || "—";
    }
    box.innerHTML = "";
    if (!fires.length) {
      panelEmpty(box, "municipality_view", "Bölgenizde aktif yangın yok.");
    } else {
      for (const f of fires) {
        const row = document.createElement("div");
        row.className = "fire";
        const color = SEVERITY_COLORS[f.severity] || "#9e9e9e";
        row.innerHTML =
          `<span class="sev" style="background:${color}"></span>`
          + `<span class="nm">${escapeHtml(f.name)}</span>`
          + `<span class="cc">${escapeHtml(f.severity)}</span>`;
        box.appendChild(row);
      }
    }
    const c = data.capacity || {};
    if (cap) {
      cap.textContent = `Bölgede müsait: ${c.local_available_units || 0}`
        + ` · konuşlu: ${c.local_committed_units || 0}`
        + ` · havuz müsait: ${c.pool_available_units || 0}`;
    }
    setStatus(`Belediye görünümü — ${data.attribution}`);
  }

  // EM-086: bildirim merkezi — canlı akıştaki uyarılar okundu/onaylandı + sesli ayar.
  const BILDIRIM_API = "/api/v1/notifications";
  const NOTIF_LEVEL_COLORS = {
    "kritik": "#b71c1c", "kritik-yakin": "#e65100",
    "dikkat": "#f9a825", "normal": "#2e7d32",
  };
  async function toggleBildirimPanel() {
    const panel = document.getElementById("bildirim-panel");
    if (bildirimPanelOpen) {
      bildirimPanelOpen = false;
      panel.style.display = "none";
      return;
    }
    bildirimPanelOpen = true;
    panel.style.display = "block";
    await loadBildirim();
  }
  async function loadBildirim() {
    const box = document.getElementById("bildirim-list");
    panelLoading(box, "notification_center");
    try {
      const res = await fetch(BILDIRIM_API);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      renderBildirim(data);
    } catch (err) {
      if (box) { box.innerHTML = panelErrorHtml("notification_center", err.message); }
      setStatus(`Bildirim merkezi alınamadı: ${err.message}`);
    }
  }
  function renderBildirim(data) {
    const box = document.getElementById("bildirim-list");
    const sum = document.getElementById("bildirim-summary");
    const countEl = document.getElementById("bildirim-count");
    const sound = data.sound || {};
    const s = data.summary || {};
    if (countEl) countEl.textContent = s.unread ? `(${s.unread} okunmadı)` : "";
    if (sum) {
      sum.textContent = `Toplam ${s.total || 0} · bekleyen onay ${s.pending_ack || 0}`
        + ` · sesli çalacak ${s.sounding || 0}`;
    }
    const soundBox = document.getElementById("bildirim-sound");
    if (soundBox) {
      const levels = data.levels || ["normal", "dikkat", "kritik-yakin", "kritik"];
      const opts = levels.map(l =>
        `<option value="${l}"${l === sound.min_level ? " selected" : ""}>${l}</option>`
      ).join("");
      soundBox.innerHTML =
        `<label><input type="checkbox" id="bildirim-sound-on"`
        + `${sound.sound_enabled ? " checked" : ""}> Sesli uyarı</label>`
        + `<label>En az: <select id="bildirim-sound-level">${opts}</select></label>`;
      const onEl = document.getElementById("bildirim-sound-on");
      const lvlEl = document.getElementById("bildirim-sound-level");
      const save = () => saveSound(onEl.checked, lvlEl.value);
      if (onEl) onEl.addEventListener("change", save);
      if (lvlEl) lvlEl.addEventListener("change", save);
    }
    box.innerHTML = "";
    const items = data.notifications || [];
    if (!items.length) {
      panelEmpty(box, "notification_center", "Bekleyen uyarı yok.");
      setStatus(`Bildirim merkezi — ${data.attribution}`);
      return;
    }
    for (const n of items) {
      const row = document.createElement("div");
      row.className = "notif" + (n.is_read ? "" : " unread");
      const color = NOTIF_LEVEL_COLORS[n.level] || "#9e9e9e";
      const badge = n.is_acknowledged ? "onaylandı"
        : (n.requires_ack ? "onay bekliyor" : (n.is_read ? "okundu" : "yeni"));
      row.innerHTML =
        `<span class="lvl" style="background:${color}">`
        + `${escapeHtml(n.level || "?")}</span> `
        + `<strong>${escapeHtml(n.title || n.event_key || "uyarı")}</strong>`
        + `<div class="meta">${escapeHtml(n.message || "")} · ${badge}</div>`
        + `<div class="acts"></div>`;
      const acts = row.querySelector(".acts");
      if (!n.is_read) {
        const b = document.createElement("button");
        b.type = "button";
        b.textContent = "Okundu işaretle";
        b.addEventListener("click", () => markNotifRead(n.live_update_id));
        acts.appendChild(b);
      }
      if (n.requires_ack && !n.is_acknowledged) {
        const b = document.createElement("button");
        b.type = "button";
        b.textContent = "Onayla";
        b.addEventListener("click", () => ackNotif(n.live_update_id));
        acts.appendChild(b);
      }
      box.appendChild(row);
    }
    setStatus(`Bildirim merkezi — ${data.attribution}`);
  }
  async function markNotifRead(id) {
    try { await fetch(`${BILDIRIM_API}/${id}/read`, { method: "POST" }); }
    catch (e) { setStatus(`Okundu işaretlenemedi: ${e.message}`); }
    await loadBildirim();
  }
  async function ackNotif(id) {
    try { await fetch(`${BILDIRIM_API}/${id}/acknowledge`, { method: "POST" }); }
    catch (e) { setStatus(`Onaylanamadı: ${e.message}`); }
    await loadBildirim();
  }
  async function saveSound(enabled, minLevel) {
    try {
      const res = await fetch(`${BILDIRIM_API}/sound`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ sound_enabled: enabled, min_level: minLevel }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setStatus("Sesli uyarı ayarı kaydedildi.");
    } catch (e) {
      setStatus(`Sesli uyarı ayarı kaydedilemedi: ${e.message}`);
    }
  }

  // EM-087: durum raporu (SITREP) — tek sayfa özet + PDF/Yazdır dışa aktarımı.
  const SITREP_API = "/api/v1/sitrep";
  const SITREP_LEVEL_COLORS = {
    "kritik": "#b71c1c", "kritik-yakin": "#e65100",
    "dikkat": "#f9a825", "normal": "#2e7d32",
  };
  let sitrepData = null;
  async function toggleSitrepPanel() {
    const panel = document.getElementById("sitrep-panel");
    if (sitrepPanelOpen) {
      sitrepPanelOpen = false;
      panel.style.display = "none";
      return;
    }
    sitrepPanelOpen = true;
    panel.style.display = "block";
    await loadSitrep();
  }
  async function loadSitrep() {
    const box = document.getElementById("sitrep-body");
    panelLoading(box, "sitrep");
    try {
      const res = await fetch(SITREP_API);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      renderSitrep(data);
    } catch (err) {
      if (box) { box.innerHTML = panelErrorHtml("sitrep", err.message); }
      setStatus(`Durum raporu alınamadı: ${err.message}`);
    }
  }
  function renderSitrep(data) {
    sitrepData = data;
    const box = document.getElementById("sitrep-body");
    const badge = document.getElementById("sitrep-badge");
    const countEl = document.getElementById("sitrep-count");
    const headEl = document.getElementById("sitrep-headline");
    if (countEl) countEl.textContent = `(${data.fire_count || 0})`;
    if (badge) {
      if (data.synthetic && data.synthetic.is_synthetic) {
        badge.textContent = data.synthetic.badge || "SENTETİK VERİ";
        badge.style.display = "block";
      } else {
        badge.style.display = "none";
      }
    }
    const h = data.headline || {};
    if (headEl) {
      headEl.textContent = `Aktif: ${h.active_fire_total || 0}`
        + ` · En ağır: ${h.most_severe || "—"}`
        + ` · En yüksek risk: ${h.max_risk_level || "—"}`
        + ` · ${escapeHtml(data.generated_at || "")}`;
    }
    box.innerHTML = "";
    const fires = data.fires || [];
    if (!fires.length) {
      panelEmpty(box, "sitrep", "Bildirilecek aktif yangın yok.");
    } else {
      for (const fr of fires) {
        const row = document.createElement("div");
        row.className = "fire";
        const color = SITREP_LEVEL_COLORS[fr.peak_level] || "#9e9e9e";
        row.innerHTML =
          `<span class="lvl" style="background:${color}">`
          + `${escapeHtml(fr.peak_level || "?")}</span> `
          + `<strong>${escapeHtml(fr.name || fr.event_key)}</strong>`
          + `<div class="meta">${escapeHtml(fr.severity || "")}`
          + ` · risk ${fr.peak_risk_index == null ? "—" : fr.peak_risk_index}</div>`;
        box.appendChild(row);
      }
    }
    const rec = data.recommendations || {};
    const recEl = document.createElement("div");
    recEl.className = "rec";
    if (rec.available && (rec.items || []).length) {
      recEl.innerHTML = `<div class="rechead">Öneriler (${escapeHtml(rec.for_event || "")})</div>`
        + rec.items.map(r => `<div class="recrow">${escapeHtml(r.name || r.resource_key || "")}`
          + ` · ${escapeHtml(r.travel_mode || "")}`
          + ` · ${r.eta_minutes == null ? "—" : ("ETA " + r.eta_minutes + " dk")}</div>`).join("");
    } else {
      recEl.innerHTML = `<div class="rechead">Öneriler</div>`
        + `<div class="meta">${escapeHtml(rec.reason || "Öneri üretilemedi")}</div>`;
    }
    box.appendChild(recEl);
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "print";
    btn.textContent = "PDF / Yazdır";
    btn.addEventListener("click", printSitrep);
    box.appendChild(btn);
    setStatus(`Durum raporu — ${data.attribution}`);
  }
  function sitrepPrintableHtml(data) {
    const fires = data.fires || [];
    const rec = data.recommendations || {};
    const levelColor = lvl => SITREP_LEVEL_COLORS[lvl] || "#9e9e9e";
    const fireRows = fires.map(f =>
      `<tr><td>${escapeHtml(f.name || f.event_key)}</td>`
      + `<td>${escapeHtml(f.severity || "—")}</td>`
      + `<td><span style="color:${levelColor(f.peak_level)}">${escapeHtml(f.peak_level || "—")}</span></td>`
      + `<td>${f.peak_risk_index == null ? "—" : f.peak_risk_index}</td>`
      + `<td>${escapeHtml(f.started_at || "—")}</td></tr>`).join("");
    const recItems = (rec.items || []).map(r =>
      `<li>${escapeHtml(r.name || r.resource_key || "")} — ${escapeHtml(r.travel_mode || "")}`
      + ` · ${r.eta_minutes == null ? "—" : ("ETA " + r.eta_minutes + " dk")}</li>`).join("");
    const badge = (data.synthetic && data.synthetic.is_synthetic)
      ? `<div class="badge">${escapeHtml(data.synthetic.badge || "SENTETİK VERİ")}</div>` : "";
    const recBlock = (rec.available && recItems)
      ? `<h2>Öneriler (${escapeHtml(rec.for_event || "")})</h2><ul>${recItems}</ul>`
      : `<h2>Öneriler</h2><p class="muted">${escapeHtml(rec.reason || "Öneri yok")}</p>`;
    return `<!DOCTYPE html><html lang="tr"><head><meta charset="utf-8">`
      + `<title>Durum Raporu (SITREP)</title><style>`
      + `body{font-family:Arial,Helvetica,sans-serif;margin:24px;color:#1a1a1a}`
      + `h1{font-size:20px;margin:0 0 2px}h2{font-size:14px;margin:16px 0 4px`
      + `;border-bottom:1px solid #ccc;padding-bottom:2px}`
      + `.stamp{color:#666;font-size:12px;margin-bottom:8px}`
      + `.badge{background:#fbe9e9;color:#b71c1c;border:1px solid #c62828;`
      + `padding:6px 8px;border-radius:6px;font-weight:bold;margin:8px 0}`
      + `table{border-collapse:collapse;width:100%;font-size:12px}`
      + `th,td{border:1px solid #ddd;padding:4px 6px;text-align:left}`
      + `th{background:#f5f5f5}.muted{color:#666}`
      + `.foot{margin-top:18px;color:#888;font-size:11px}</style></head><body>`
      + `<h1>${escapeHtml(data.title || "Durum Raporu (SITREP)")}</h1>`
      + `<div class="stamp">Rapor zamanı: ${escapeHtml(data.generated_at || "—")}</div>`
      + badge
      + `<h2>Aktif Yangınlar</h2>`
      + `<table><thead><tr><th>Olay</th><th>Şiddet</th><th>Risk bandı</th>`
      + `<th>Risk indeksi</th><th>Başlangıç</th></tr></thead>`
      + `<tbody>${fireRows || '<tr><td colspan="5">Aktif yangın yok</td></tr>'}</tbody></table>`
      + recBlock
      + `<div class="foot">${escapeHtml(data.attribution || "")}</div>`
      + `</body></html>`;
  }
  function printSitrep() {
    if (!sitrepData) { setStatus("Önce raporu yükleyin."); return; }
    const html = sitrepPrintableHtml(sitrepData);
    const iframe = document.createElement("iframe");
    iframe.setAttribute("aria-hidden", "true");
    iframe.style.position = "fixed";
    iframe.style.right = "0";
    iframe.style.bottom = "0";
    iframe.style.width = "0";
    iframe.style.height = "0";
    iframe.style.border = "0";
    document.body.appendChild(iframe);
    const doc = iframe.contentWindow.document;
    doc.open();
    doc.write(html);
    doc.close();
    iframe.contentWindow.focus();
    iframe.contentWindow.print();
    setTimeout(() => document.body.removeChild(iframe), 1000);
  }

  // EM-089: vardiya devri notları + tek tık devir özeti.
  const HANDOVER_API = "/api/v1/shift-handover";
  async function toggleHandoverPanel() {
    const panel = document.getElementById("handover-panel");
    if (handoverPanelOpen) {
      handoverPanelOpen = false;
      panel.style.display = "none";
      return;
    }
    handoverPanelOpen = true;
    panel.style.display = "block";
    const evEl = document.getElementById("handover-event");
    if (evEl && !evEl.value && exposureEventKey) { evEl.value = exposureEventKey; }
    await loadHandoverNotes();
  }
  async function loadHandoverNotes() {
    const box = document.getElementById("handover-list");
    panelLoading(box, "shift_handover");
    try {
      const evEl = document.getElementById("handover-event");
      const ek = evEl ? evEl.value.trim() : "";
      const url = HANDOVER_API + "/notes" + (ek ? `?event_key=${encodeURIComponent(ek)}` : "");
      const res = await fetch(url);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      renderHandoverNotes(data);
    } catch (err) {
      if (box) { box.innerHTML = panelErrorHtml("shift_handover", err.message); }
      setStatus(`Vardiya devri notları alınamadı: ${err.message}`);
    }
  }
  function renderHandoverNotes(data) {
    const box = document.getElementById("handover-list");
    const countEl = document.getElementById("handover-count");
    if (countEl) countEl.textContent = `(${data.total_matching || 0} not)`;
    box.innerHTML = "";
    const notes = data.notes || [];
    if (!notes.length) {
      panelEmpty(box, "shift_handover", "Bu vardiyada not yok.");
      setStatus(`Vardiya devri — ${data.attribution}`);
      return;
    }
    for (const n of notes) {
      const row = document.createElement("div");
      row.className = "note";
      row.innerHTML =
        `<div class="meta">${escapeHtml(n.event_key)}`
        + ` · ${escapeHtml(n.author || "operatör")} · ${escapeHtml(n.created_at || "")}</div>`
        + `<div>${escapeHtml(n.body || "")}</div>`
        + `<div class="acts"></div>`;
      const acts = row.querySelector(".acts");
      const del = document.createElement("button");
      del.type = "button";
      del.textContent = "Sil";
      del.addEventListener("click", () => deleteHandoverNote(n.id));
      acts.appendChild(del);
      box.appendChild(row);
    }
    setStatus(`Vardiya devri — ${data.attribution}`);
  }
  async function addHandoverNote() {
    const evEl = document.getElementById("handover-event");
    const bodyEl = document.getElementById("handover-body");
    const authorEl = document.getElementById("handover-author");
    const event_key = evEl ? evEl.value.trim() : "";
    const body = bodyEl ? bodyEl.value.trim() : "";
    if (!event_key) { setStatus("Not için olay anahtarı gerekli."); return; }
    if (!body) { setStatus("Not metni boş olamaz."); return; }
    try {
      const res = await fetch(HANDOVER_API + "/notes", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          event_key, body,
          author: authorEl ? (authorEl.value.trim() || null) : null,
        }),
      });
      if (!res.ok) {
        const e = await res.json().catch(() => ({}));
        throw new Error((e.detail && e.detail.error) || `HTTP ${res.status}`);
      }
      setStatus("Not eklendi.");
      if (bodyEl) bodyEl.value = "";
      await loadHandoverNotes();
    } catch (err) {
      setStatus(`Not eklenemedi: ${err.message}`);
    }
  }
  async function deleteHandoverNote(id) {
    try { await fetch(`${HANDOVER_API}/notes/${id}`, { method: "DELETE" }); }
    catch (e) { setStatus(`Not silinemedi: ${e.message}`); }
    await loadHandoverNotes();
  }
  async function buildHandoverSummary() {
    const box = document.getElementById("handover-summary");
    panelLoading(box, "shift_handover");
    try {
      const evEl = document.getElementById("handover-event");
      const ek = evEl ? evEl.value.trim() : "";
      const url = HANDOVER_API + (ek ? `?event_key=${encodeURIComponent(ek)}` : "");
      const res = await fetch(url);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      renderHandoverSummary(data);
    } catch (err) {
      if (box) { box.innerHTML = panelErrorHtml("shift_handover", err.message); }
      setStatus(`Devir özeti oluşturulamadı: ${err.message}`);
    }
  }
  function renderHandoverSummary(data) {
    const box = document.getElementById("handover-summary");
    box.innerHTML = "";
    const c = data.conflicts || {};
    const head = document.createElement("div");
    head.className = "meta";
    head.textContent = `Aktif olay: ${data.incident_count || 0}`
      + ` · not: ${data.note_count || 0}`
      + ` · çakışma: ${c.total || 0}`
      + ` · ${escapeHtml(data.generated_at || "")}`;
    box.appendChild(head);
    const incs = data.incidents || [];
    if (!incs.length) {
      const p = document.createElement("div");
      p.className = "meta";
      p.textContent = "Aktif yangın yok.";
      box.appendChild(p);
    }
    for (const inc of incs) {
      const row = document.createElement("div");
      row.className = "fire";
      row.innerHTML =
        `<strong>${escapeHtml(inc.name || inc.event_key)}</strong>`
        + `<div class="meta">${escapeHtml(inc.severity || "")}`
        + ` · konuşlu: ${inc.committed_count || 0}`
        + ` · not: ${inc.note_count || 0}`
        + (inc.latest_note ? ` · son: ${escapeHtml(inc.latest_note)}` : "")
        + `</div>`;
      box.appendChild(row);
    }
    const chrono = document.createElement("div");
    chrono.className = "rec";
    const entries = (data.chronology || []).slice(0, 15);
    chrono.innerHTML = `<div class="rechead">Akış (olay + not)</div>`
      + (entries.length ? entries.map(e =>
        `<div class="recrow">${escapeHtml(e.label || e.category)} — ${escapeHtml(e.text || "")}</div>`
      ).join("") : `<div class="meta">Akış boş.</div>`);
    box.appendChild(chrono);
    setStatus(`Vardiya devri özeti — ${data.attribution}`);
  }

  // EM-094: olay & uyarı webhook'ları — abonelik + imzalı teslim geçmişi.
  const WEBHOOK_API = "/api/v1/webhooks";
  const WEBHOOK_STATUS_COLORS = {
    delivered: "#2e7d32", failed: "#b71c1c", pending: "#f9a825",
  };
  const WEBHOOK_KIND_LABELS = {
    fire_event: "Yangın", forecast: "Tahmin", alert: "Uyarı",
  };
  async function toggleWebhookPanel() {
    const panel = document.getElementById("webhook-panel");
    if (webhookPanelOpen) {
      webhookPanelOpen = false;
      panel.style.display = "none";
      return;
    }
    webhookPanelOpen = true;
    panel.style.display = "block";
    await loadWebhooks();
  }
  async function loadWebhooks() {
    const subsBox = document.getElementById("webhook-subs");
    panelLoading(subsBox, "webhooks");
    try {
      const res = await fetch(WEBHOOK_API);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      renderWebhooks(data);
    } catch (err) {
      if (subsBox) { subsBox.innerHTML = panelErrorHtml("webhooks", err.message); }
      setStatus(`Webhook durumu alınamadı: ${err.message}`);
    }
  }
  function renderWebhooks(data) {
    const countEl = document.getElementById("webhook-count");
    const sum = document.getElementById("webhook-summary");
    const s = data.summary || {};
    if (countEl) countEl.textContent = `(${data.count || 0} abone)`;
    if (sum) {
      sum.textContent = `Teslim: teslim edildi ${s.delivered || 0}`
        + ` · başarısız ${s.failed || 0} · bekleyen ${s.pending || 0}`
        + ` · imza: ${escapeHtml(data.signature_header || "")}`;
    }
    renderWebhookSubs(data.subscriptions || []);
    renderWebhookHistory(data.recent_deliveries || []);
    setStatus(`Webhook'lar — ${data.attribution}`);
  }
  function renderWebhookSubs(subs) {
    const box = document.getElementById("webhook-subs");
    box.innerHTML = "";
    if (!subs.length) {
      panelEmpty(box, "webhooks", "Kayıtlı webhook aboneliği yok.");
      return;
    }
    for (const sub of subs) {
      const row = document.createElement("div");
      row.className = "sub";
      const kinds = (sub.event_types || [])
        .map(t => WEBHOOK_KIND_LABELS[t] || t).join(", ");
      row.innerHTML =
        `<strong>${escapeHtml(sub.name || sub.subscription_key)}</strong>`
        + (sub.enabled ? "" : ` <span class="off">(duraklatıldı)</span>`)
        + `<div class="url">${escapeHtml(sub.url || "")}</div>`
        + `<div class="meta">${escapeHtml(kinds)} · ${sub.delivery_count || 0} teslim`
        + ` · anahtar ${sub.has_secret ? "ayarlı" : "yok"}</div>`
        + `<div class="acts"></div>`;
      const acts = row.querySelector(".acts");
      const tog = document.createElement("button");
      tog.type = "button";
      tog.textContent = sub.enabled ? "Duraklat" : "Sürdür";
      tog.addEventListener("click", () => patchWebhookSub(sub.subscription_key, {
        enabled: !sub.enabled,
      }));
      acts.appendChild(tog);
      const del = document.createElement("button");
      del.type = "button";
      del.textContent = "Sil";
      del.addEventListener("click", () => deleteWebhookSub(sub.subscription_key));
      acts.appendChild(del);
      box.appendChild(row);
    }
  }
  function renderWebhookHistory(items) {
    const box = document.getElementById("webhook-history");
    box.innerHTML = "";
    if (!items.length) {
      panelEmpty(box, "webhooks", "Henüz teslim kaydı yok.");
      return;
    }
    for (const d of items) {
      const row = document.createElement("div");
      row.className = "hist";
      const color = WEBHOOK_STATUS_COLORS[d.status] || "#9e9e9e";
      const kind = WEBHOOK_KIND_LABELS[d.event_type] || d.event_type;
      row.innerHTML =
        `<span class="st" style="background:${color}">${escapeHtml(d.status || "?")}</span> `
        + `<strong>${escapeHtml(kind || "olay")}</strong>`
        + `<div class="meta">${escapeHtml(d.subscription_key || "")}`
        + ` · deneme ${d.attempt || 1}`
        + ` · HTTP ${d.http_status == null ? "—" : d.http_status}`
        + ` · ${escapeHtml(d.created_at || "")}</div>`
        + (d.error ? `<div class="meta">hata: ${escapeHtml(d.error)}</div>` : "")
        + (d.next_retry_at ? `<div class="meta">sonraki deneme: ${escapeHtml(d.next_retry_at)}</div>` : "");
      box.appendChild(row);
    }
  }
  function checkedWebhookTypes() {
    const boxes = document.querySelectorAll('#webhook-types input:checked');
    return Array.from(boxes).map(b => b.value);
  }
  async function addWebhookSubscription() {
    const nameEl = document.getElementById("webhook-name");
    const urlEl = document.getElementById("webhook-url");
    const secretEl = document.getElementById("webhook-secret");
    const event_types = checkedWebhookTypes();
    if (!(nameEl && nameEl.value.trim())) { setStatus("Abone adı gerekli."); return; }
    if (!(urlEl && urlEl.value.trim())) { setStatus("Webhook URL'si gerekli."); return; }
    if (!event_types.length) { setStatus("En az bir olay tipi seçilmelidir."); return; }
    try {
      const res = await fetch(WEBHOOK_API + "/subscriptions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: nameEl.value.trim(),
          url: urlEl.value.trim(),
          event_types,
          secret: secretEl && secretEl.value.trim() ? secretEl.value.trim() : null,
          enabled: true,
        }),
      });
      if (!res.ok) {
        const e = await res.json().catch(() => ({}));
        throw new Error((e.detail && e.detail.error) || `HTTP ${res.status}`);
      }
      setStatus("Webhook aboneliği eklendi.");
      nameEl.value = ""; urlEl.value = ""; if (secretEl) secretEl.value = "";
      document.querySelectorAll('#webhook-types input').forEach(b => { b.checked = false; });
      await loadWebhooks();
    } catch (err) {
      setStatus(`Abonelik eklenemedi: ${err.message}`);
    }
  }
  async function patchWebhookSub(key, payload) {
    try {
      const res = await fetch(`${WEBHOOK_API}/subscriptions/${encodeURIComponent(key)}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
    } catch (e) { setStatus(`Abonelik güncellenemedi: ${e.message}`); }
    await loadWebhooks();
  }
  async function deleteWebhookSub(key) {
    try { await fetch(`${WEBHOOK_API}/subscriptions/${encodeURIComponent(key)}`, { method: "DELETE" }); }
    catch (e) { setStatus(`Abonelik silinemedi: ${e.message}`); }
    await loadWebhooks();
  }
  async function dispatchWebhooks() {
    const types = checkedWebhookTypes();
    const targets = types.length ? types : ["fire_event", "forecast", "alert"];
    let created = 0;
    try {
      for (const event_type of targets) {
        const res = await fetch(WEBHOOK_API + "/dispatch", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ event_type, dry_run: false }),
        });
        if (!res.ok) {
          const e = await res.json().catch(() => ({}));
          throw new Error((e.detail && e.detail.error) || `HTTP ${res.status}`);
        }
        const d = await res.json();
        created += d.created || 0;
      }
      setStatus(`Webhook olayları dağıtıldı — ${created} imzalı teslim kaydı.`);
    } catch (err) {
      setStatus(`Olaylar dağıtılamadı: ${err.message}`);
    }
    await loadWebhooks();
  }
  async function retryWebhooks() {
    try {
      const res = await fetch(WEBHOOK_API + "/retry", { method: "POST" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const d = await res.json();
      const r = d.retried || [];
      const x = d.exhausted || [];
      setStatus(`Yeniden deneme — ${r.length} yeniden gönderildi, ${x.length} bütçe tükendi.`);
    } catch (err) {
      setStatus(`Yeniden deneme başarısız: ${err.message}`);
    }
    await loadWebhooks();
  }

  // --- EM-096: birleşik, değişmez denetim kaydı ---------------------------
  const AUDIT_API = "/api/v1/audit";
  async function toggleAuditPanel() {
    const panel = document.getElementById("audit-panel");
    if (auditPanelOpen) {
      auditPanelOpen = false;
      panel.style.display = "none";
      return;
    }
    auditPanelOpen = true;
    panel.style.display = "block";
    await loadAudit();
  }
  async function loadAudit() {
    const box = document.getElementById("audit-list");
    panelLoading(box, "audit_trail");
    try {
      if (!auditConfigLoaded) { await loadAuditConfig(); }
      const params = new URLSearchParams();
      const domSel = document.getElementById("audit-filter-domain");
      const actorEl = document.getElementById("audit-filter-actor");
      if (domSel && domSel.value) params.set("domain", domSel.value);
      if (actorEl && actorEl.value.trim()) params.set("actor", actorEl.value.trim());
      const qs = params.toString();
      const res = await fetch(AUDIT_API + (qs ? `?${qs}` : ""));
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      renderAudit(data);
    } catch (err) {
      if (box) { box.innerHTML = panelErrorHtml("audit_trail", err.message); }
      setStatus(`Denetim kaydı alınamadı: ${err.message}`);
    }
  }
  async function loadAuditConfig() {
    try {
      const res = await fetch(AUDIT_API + "/config");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const cfg = await res.json();
      fillAuditSelect("audit-domain", cfg.domains || []);
      fillAuditSelect("audit-action", cfg.actions || []);
      fillAuditSelect("audit-filter-domain", cfg.domains || [], true);
      auditConfigLoaded = true;
    } catch (err) {
      setStatus(`Denetim sözlüğü yüklenemedi: ${err.message}`);
    }
  }
  function fillAuditSelect(id, values, withAll) {
    const sel = document.getElementById(id);
    if (!sel) return;
    sel.innerHTML = "";
    if (withAll) {
      const all = document.createElement("option");
      all.value = "";
      all.textContent = "tümü";
      sel.appendChild(all);
    }
    for (const v of values) {
      const opt = document.createElement("option");
      opt.value = v;
      opt.textContent = v;
      sel.appendChild(opt);
    }
  }
  function renderAudit(data) {
    const box = document.getElementById("audit-list");
    const countEl = document.getElementById("audit-count");
    const sum = document.getElementById("audit-summary");
    const entries = data.entries || [];
    if (countEl) { countEl.textContent = `(${data.total_matching || 0} kayıt)`; }
    if (sum) {
      const counts = data.counts_by_domain || {};
      const parts = Object.keys(counts).map(d => `${d}: ${counts[d]}`);
      sum.textContent = (data.immutable ? "Değişmez defter · " : "")
        + (parts.length ? parts.join(" · ") : "kayıt yok");
    }
    box.innerHTML = "";
    if (!entries.length) {
      panelEmpty(box, "audit_trail", "Filtrede denetim kaydı yok.");
      return;
    }
    for (const e of entries) {
      const row = document.createElement("div");
      row.className = "row";
      const diff = `${fmtAuditVal(e.old_value)} → ${fmtAuditVal(e.new_value)}`;
      row.innerHTML =
        `<span class="dom">${escapeHtml(e.domain)}</span>`
        + ` <strong>${escapeHtml(e.action)}</strong>`
        + ` <span class="meta">${escapeHtml(e.created_at || "")}</span>`
        + `<div class="meta"><strong>${escapeHtml(e.actor || "?")}</strong>`
        + (e.subject_key ? ` · özne ${escapeHtml(e.subject_key)}` : "") + `</div>`
        + `<div class="meta">${escapeHtml(e.summary || "")}</div>`
        + `<div class="meta">${diff}</div>`;
      box.appendChild(row);
    }
    setStatus(`Denetim kaydı — ${data.attribution}`);
  }
  function fmtAuditVal(v) {
    if (v === null || v === undefined) return "—";
    if (typeof v === "object") {
      try { return JSON.stringify(v); } catch (_e) { return "{…}"; }
    }
    return String(v);
  }
  async function addAuditEntry() {
    const domSel = document.getElementById("audit-domain");
    const actSel = document.getElementById("audit-action");
    const actorEl = document.getElementById("audit-actor");
    const subjEl = document.getElementById("audit-subject");
    const sumEl = document.getElementById("audit-summary-text");
    const body = {
      domain: domSel ? domSel.value : "",
      action: actSel ? actSel.value : "",
      actor: actorEl ? actorEl.value.trim() : "",
      subject_key: subjEl && subjEl.value.trim() ? subjEl.value.trim() : null,
      summary: sumEl && sumEl.value.trim() ? sumEl.value.trim() : null,
    };
    try {
      const res = await fetch(AUDIT_API, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const d = await res.json();
      if (!res.ok) {
        throw new Error((d.detail && d.detail.error) || `HTTP ${res.status}`);
      }
      setStatus(`Denetim kaydı eklendi (silinemez): ${d.entry.audit_key}`);
      if (actorEl) { actorEl.value = ""; }
      if (subjEl) { subjEl.value = ""; }
      if (sumEl) { sumEl.value = ""; }
    } catch (err) {
      setStatus(`Denetim kaydı eklenemedi: ${err.message}`);
    }
    await loadAudit();
  }

  // --- EM-035: bölge bazlı sinyal baz çizgisi (sessizlik ön göstergesi) ----
  const SIGNAL_API = "/api/v1/signal-baseline";
  async function toggleSignalPanel() {
    const panel = document.getElementById("signal-panel");
    if (signalPanelOpen) {
      signalPanelOpen = false;
      panel.style.display = "none";
      if (signalHighlight) { map.removeLayer(signalHighlight); signalHighlight = null; }
      return;
    }
    signalPanelOpen = true;
    panel.style.display = "block";
    await loadSignalBaseline();
  }
  async function loadSignalBaseline() {
    const box = document.getElementById("signal-list");
    panelLoading(box, "signal_baseline");
    try {
      if (!signalConfigLoaded) { await loadSignalConfig(); }
      const params = new URLSearchParams();
      const src = document.getElementById("signal-source").value;
      if (src) params.set("source", src);
      const asof = document.getElementById("signal-asof").value.trim();
      if (asof) params.set("as_of", asof);
      const res = await fetch(`${SIGNAL_API}?${params.toString()}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      renderSignalList(data);
    } catch (err) {
      box.innerHTML = panelErrorHtml("signal_baseline", err.message);
      setStatus(`Sinyal baz çizgisi alınamadı: ${err.message}`);
    }
  }
  async function loadSignalConfig() {
    const res = await fetch(`${SIGNAL_API}/config`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const cfg = await res.json();
    const sel = document.getElementById("signal-source");
    if (sel && !sel.options.length) {
      for (const kind of (cfg.sources.available || [])) {
        const op = document.createElement("option");
        op.value = kind;
        op.textContent = kind;
        sel.appendChild(op);
      }
    }
    signalConfigLoaded = true;
  }
  function renderSignalList(data) {
    const box = document.getElementById("signal-list");
    const countEl = document.getElementById("signal-count");
    // Son yanıtı önbelleğe al: aday süzmesi sunucuya gitmeden yeniden işlenir.
    box.dataset.signalLast = JSON.stringify(data);
    let cells = (data.cells || []).slice();
    const onlyCandidate = document.getElementById("signal-candidate").checked;
    if (onlyCandidate) { cells = cells.filter(c => c.candidate_silent); }
    if (countEl) {
      countEl.textContent = `(${data.candidate_silent_count}/${data.cell_count})`;
    }
    box.innerHTML = "";
    if (!cells.length) {
      panelEmpty(box, "signal_baseline",
        data.synthetic ? "Sessiz adayı yok — akış SENTETİK, gerçek uyarı değil." : null);
      setStatus(`Sinyal baz çizgisi — ${data.as_of}: sessiz adayı yok — ${data.attribution}`);
      return;
    }
    for (const cell of cells) {
      const row = document.createElement("div");
      row.className = "item";
      row.setAttribute("role", "button");
      row.tabIndex = 0;
      const color = cell.candidate_silent ? "#c62828" : "#2e7d32";
      const syn = cell.synthetic ? ' <span class="syn">SENTETİK</span>' : "";
      row.innerHTML =
        `<span class="dot" style="background:${color}"></span>`
        + `<span><b class="nm">${escapeHtml(cell.name || cell.region_key)}</b>${syn}`
        + `<br><span class="meta">baz ${escapeHtml(String(cell.baseline_mean))}`
        + ` · son ${escapeHtml(String(cell.latest_value))}</span></span>`
        + `<span class="z">z=${escapeHtml(String(cell.z_score))}</span>`;
      const select = () => focusSignalCell(cell, row);
      row.addEventListener("click", select);
      row.addEventListener("keydown", e => {
        if (e.key === "Enter" || e.key === " ") { e.preventDefault(); select(); }
      });
      box.appendChild(row);
    }
    setStatus(
      `Sinyal baz çizgisi — ${data.as_of}, ${data.window_days} gün, `
      + `sessiz aday ${data.candidate_silent_count} — ${data.attribution}`);
  }
  function focusSignalCell(cell, row) {
    for (const el of document.querySelectorAll("#signal-panel .item.sel")) {
      el.classList.remove("sel");
    }
    if (row) row.classList.add("sel");
    // Harita senkron seçim: hücre sınırlarına odaklan ve vurgula.
    const bounds = L.latLngBounds(
      [[cell.min_lat, cell.min_lon], [cell.max_lat, cell.max_lon]]);
    map.fitBounds(bounds, { padding: [40, 40] });
    if (signalHighlight) { map.removeLayer(signalHighlight); }
    signalHighlight = L.rectangle(bounds, {
      color: "#2166ac", weight: 3, dashArray: "6 4",
      fillColor: "#2166ac", fillOpacity: 0.12,
    }).addTo(map);
    signalHighlight.bindPopup(
      `<b>${escapeHtml(cell.name || cell.region_key)}</b><br>`
      + `baz: ${escapeHtml(String(cell.baseline_mean))} ± ${escapeHtml(String(cell.baseline_std))}<br>`
      + `son okuma: ${escapeHtml(String(cell.latest_value))} (z=${escapeHtml(String(cell.z_score))})`);
    signalHighlight.openPopup();
  }

  // --- EM-043: mevsimsel sinyal baz çizgisi (saat/hafta günü + önce/sonra) ----
  const SEAS_API = "/api/v1/signal-baseline-seasonal";
  async function toggleSeasPanel() {
    const panel = document.getElementById("seas-panel");
    if (seasPanelOpen) {
      seasPanelOpen = false;
      panel.style.display = "none";
      if (seasHighlight) { map.removeLayer(seasHighlight); seasHighlight = null; }
      return;
    }
    seasPanelOpen = true;
    panel.style.display = "block";
    await loadSeas();
  }
  async function loadSeas() {
    const box = document.getElementById("seas-list");
    panelLoading(box, "signal_baseline_seasonal");
    try {
      if (!seasConfigLoaded) { await loadSeasConfig(); }
      const params = new URLSearchParams();
      const src = document.getElementById("seas-source").value;
      if (src) params.set("source", src);
      const hour = document.getElementById("seas-hour").value;
      if (hour) params.set("hour", hour);
      const asof = document.getElementById("seas-asof").value.trim();
      if (asof) params.set("as_of", asof);
      const res = await fetch(`${SEAS_API}?${params.toString()}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      renderSeas(data);
    } catch (err) {
      box.innerHTML = panelErrorHtml("signal_baseline_seasonal", err.message);
      setStatus(`Mevsimsel baz çizgisi alınamadı: ${err.message}`);
    }
  }
  async function loadSeasConfig() {
    const res = await fetch(`${SEAS_API}/config`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const cfg = await res.json();
    const sel = document.getElementById("seas-source");
    if (sel && !sel.options.length) {
      for (const kind of (cfg.sources.available || [])) {
        const op = document.createElement("option");
        op.value = kind;
        op.textContent = kind;
        sel.appendChild(op);
      }
    }
    seasConfigLoaded = true;
  }
  function renderSeas(data) {
    const box = document.getElementById("seas-list");
    const countEl = document.getElementById("seas-count");
    // Son yanıtı önbelleğe al: aday süzmesi sunucuya gitmeden yeniden işlenir.
    box.dataset.seasLast = JSON.stringify(data);
    let cells = (data.cells || []).slice();
    const onlyCandidate = document.getElementById("seas-candidate").checked;
    if (onlyCandidate) { cells = cells.filter(c => c.candidate_seasonal); }
    if (countEl) {
      countEl.textContent =
        `(${data.seasonal_candidate_count}/${data.cell_count})`;
    }
    const sum = document.getElementById("seas-summary");
    if (sum) {
      sum.style.display = "block";
      const dim = data.hourly_available
        ? "saat + hafta günü" : "yalnızca hafta günü";
      sum.innerHTML =
        `düz aday <b>${escapeHtml(String(data.flat_candidate_count))}</b>`
        + ` → mevsimsel aday <b>${escapeHtml(String(data.seasonal_candidate_count))}</b>`
        + ` · yanlış alarm elenen <b>${escapeHtml(String(data.false_alarms_removed))}</b>`
        + `<br><span class="meta">boyutlar: ${escapeHtml(dim)}`
        + ` · kontrol saati ${escapeHtml(String(data.night_check_hour))}:00`
        + ` · ${escapeHtml(String(data.window_days))} gün</span>`;
    }
    box.innerHTML = "";
    if (!cells.length) {
      panelEmpty(box, "signal_baseline_seasonal",
        data.synthetic ? "Mevsimsel aday yok — akış SENTETİK, gerçek uyarı değil." : null);
      setStatus(`Mevsimsel baz çizgisi — ${data.as_of}: mevsimsel aday yok — ${data.attribution}`);
      return;
    }
    for (const cell of cells) {
      const row = document.createElement("div");
      row.className = "item";
      row.setAttribute("role", "button");
      row.tabIndex = 0;
      const color = cell.candidate_seasonal ? "#c62828" : "#2e7d32";
      const syn = cell.synthetic ? ' <span class="syn">SENTETİK</span>' : "";
      const removed = cell.false_alarm_removed
        ? ' <span class="removed">↩ yanlış alarm elendi</span>' : "";
      row.innerHTML =
        `<span class="dot" style="background:${color}"></span>`
        + `<span><b class="nm">${escapeHtml(cell.name || cell.region_key)}</b>${syn}${removed}`
        + `<br><span class="meta">beklenen ${escapeHtml(String(cell.seasonal_expected))}`
        + ` · son ${escapeHtml(String(cell.latest_value))}`
        + ` · ${escapeHtml(cell.weekday_label || "")}</span></span>`
        + `<span class="z">düz z=${escapeHtml(String(cell.z_flat))}`
        + ` → mevs. z=${escapeHtml(String(cell.z_seasonal))}</span>`;
      const select = () => focusSeasCell(cell, row);
      row.addEventListener("click", select);
      row.addEventListener("keydown", e => {
        if (e.key === "Enter" || e.key === " ") { e.preventDefault(); select(); }
      });
      box.appendChild(row);
    }
    setStatus(
      `Mevsimsel baz çizgisi — ${data.as_of} ${data.night_check_hour}:00, `
      + `${data.window_days} gün, mevsimsel aday ${data.seasonal_candidate_count} `
      + `(düz ${data.flat_candidate_count}), elenen ${data.false_alarms_removed} — ${data.attribution}`);
  }
  function focusSeasCell(cell, row) {
    for (const el of document.querySelectorAll("#seas-panel .item.sel")) {
      el.classList.remove("sel");
    }
    if (row) row.classList.add("sel");
    // Harita senkron seçim: hücre sınırlarına odaklan ve vurgula.
    const bounds = L.latLngBounds(
      [[cell.min_lat, cell.min_lon], [cell.max_lat, cell.max_lon]]);
    map.fitBounds(bounds, { padding: [40, 40] });
    if (seasHighlight) { map.removeLayer(seasHighlight); }
    seasHighlight = L.rectangle(bounds, {
      color: "#2166ac", weight: 3, dashArray: "6 4",
      fillColor: "#2166ac", fillOpacity: 0.12,
    }).addTo(map);
    seasHighlight.bindPopup(
      `<b>${escapeHtml(cell.name || cell.region_key)}</b><br>`
      + `mevsimsel beklenen: ${escapeHtml(String(cell.seasonal_expected))}<br>`
      + `saat faktörü ${escapeHtml(String(cell.hour_factor))} · `
      + `gün faktörü ${escapeHtml(String(cell.weekday_factor))}<br>`
      + `son okuma: ${escapeHtml(String(cell.latest_value))} `
      + `(düz z=${escapeHtml(String(cell.z_flat))} → mevs. z=${escapeHtml(String(cell.z_seasonal))})`);
    seasHighlight.openPopup();
  }
  async function recomputeSeas() {
    const box = document.getElementById("seas-list");
    panelLoading(box, "signal_baseline_seasonal");
    try {
      const params = new URLSearchParams();
      const src = document.getElementById("seas-source").value;
      if (src) params.set("source", src);
      const hour = document.getElementById("seas-hour").value;
      if (hour) params.set("hour", hour);
      const asof = document.getElementById("seas-asof").value.trim();
      if (asof) params.set("as_of", asof);
      const res = await fetch(`${SEAS_API}/refresh?${params.toString()}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setStatus(
        `Mevsimsel baz çizgisi günlük yenilendi — ${data.refreshed_for}, `
        + `${data.recomputed_cells} hücre yeniden hesaplandı (${data.refresh_interval_days} gün aralık) — ${data.attribution}`);
      await loadSeas();
    } catch (err) {
      box.innerHTML = panelErrorHtml("signal_baseline_seasonal", err.message);
      setStatus(`Mevsimsel baz yeniden hesaplanamadı: ${err.message}`);
    }
  }

  // --- EM-036: Isolation Forest anomali skoru (çok-özellikli öğrenilmiş) -------
  const IFA_API = "/api/v1/isolation-forest-anomaly";
  async function toggleIfaPanel() {
    const panel = document.getElementById("ifa-panel");
    if (ifaPanelOpen) {
      ifaPanelOpen = false;
      panel.style.display = "none";
      if (ifaHighlight) { map.removeLayer(ifaHighlight); ifaHighlight = null; }
      return;
    }
    ifaPanelOpen = true;
    panel.style.display = "block";
    await loadIfa();
  }
  async function loadIfa() {
    const box = document.getElementById("ifa-list");
    panelLoading(box, "isolation_forest_anomaly");
    try {
      if (!ifaConfigLoaded) { await loadIfaConfig(); }
      const res = await fetch(`${IFA_API}?${ifaParams().toString()}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      renderIfa(data);
    } catch (err) {
      box.innerHTML = panelErrorHtml("isolation_forest_anomaly", err.message);
      setStatus(`Isolation Forest anomali skoru alınamadı: ${err.message}`);
    }
  }
  function ifaParams() {
    const params = new URLSearchParams();
    const src = document.getElementById("ifa-source").value;
    if (src) params.set("source", src);
    const sigma = document.getElementById("ifa-sigma").value.trim();
    if (sigma) params.set("sigma_multiplier", sigma);
    const win = document.getElementById("ifa-window").value.trim();
    if (win) params.set("window_days", win);
    const asof = document.getElementById("ifa-asof").value.trim();
    if (asof) params.set("as_of", asof);
    return params;
  }
  async function loadIfaConfig() {
    const res = await fetch(`${IFA_API}/config`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const cfg = await res.json();
    const sel = document.getElementById("ifa-source");
    if (sel && !sel.options.length) {
      for (const kind of (cfg.sources.available || [])) {
        const op = document.createElement("option");
        op.value = kind;
        op.textContent = kind;
        sel.appendChild(op);
      }
    }
    const sigma = document.getElementById("ifa-sigma");
    if (sigma && cfg.sigma_multiplier) { sigma.value = cfg.sigma_multiplier.default; }
    const win = document.getElementById("ifa-window");
    if (win && cfg.window_days) { win.value = cfg.window_days.default; }
    ifaConfigLoaded = true;
  }
  function ifaBasisLabel(basis) {
    if (basis === "both") return "istatistikî + IF";
    if (basis === "statistical") return "istatistikî";
    if (basis === "isolation_forest") return "Isolation Forest";
    return "—";
  }
  function renderIfa(data) {
    const box = document.getElementById("ifa-list");
    const countEl = document.getElementById("ifa-count");
    // Son yanıtı önbelleğe al: anomali süzmesi sunucuya gitmeden yeniden işlenir.
    box.dataset.ifaLast = JSON.stringify(data);
    let cells = (data.cells || []).slice();
    const onlyAnomaly = document.getElementById("ifa-anomaly").checked;
    if (onlyAnomaly) { cells = cells.filter(c => c.is_anomaly); }
    if (countEl) {
      countEl.textContent = `(${data.anomaly_count}/${data.cell_count})`;
    }
    const sum = document.getElementById("ifa-summary");
    if (sum) {
      sum.style.display = "block";
      sum.innerHTML =
        `anomali <b>${escapeHtml(String(data.anomaly_count))}</b>`
        + ` · sessiz <b>${escapeHtml(String(data.silent_anomaly_count))}</b>`
        + ` · öğrenilmiş <b>${escapeHtml(String(data.learned_anomaly_count))}</b>`
        + `<br><span class="meta">özellikler: ${escapeHtml((data.features || []).join(", "))}`
        + ` · sigma=${escapeHtml(String(data.sigma_multiplier))}`
        + ` · ${escapeHtml(String(data.window_days))} gün`
        + ` · kirlenme ${escapeHtml(String(data.contamination))}</span>`;
    }
    box.innerHTML = "";
    if (!cells.length) {
      panelEmpty(box, "isolation_forest_anomaly",
        data.synthetic ? "Anomali yok — akış SENTETİK, gerçek uyarı değil." : null);
      setStatus(`Isolation Forest anomali — ${data.as_of}: anomali yok — ${data.attribution}`);
      return;
    }
    for (const cell of cells) {
      const row = document.createElement("div");
      row.className = "item";
      row.setAttribute("role", "button");
      row.tabIndex = 0;
      const color = cell.is_anomaly ? "#c62828" : "#2e7d32";
      const syn = cell.synthetic ? ' <span class="syn">SENTETİK</span>' : "";
      row.innerHTML =
        `<span class="dot" style="background:${color}"></span>`
        + `<span><b class="nm">${escapeHtml(cell.name || cell.region_key)}</b>${syn}`
        + `<br><span class="meta">baz ${escapeHtml(String(cell.baseline_mean))}`
        + ` ± ${escapeHtml(String(cell.baseline_std))}`
        + ` · eşik ${escapeHtml(String(cell.quiet_threshold))}`
        + ` · son ${escapeHtml(String(cell.latest_value))}</span>`
        + `<br><span class="basis">temel: ${escapeHtml(ifaBasisLabel(cell.detection_basis))}</span></span>`
        + `<span class="score">skor ${escapeHtml(String(cell.anomaly_score))}</span>`;
      const select = () => focusIfaCell(cell, row);
      row.addEventListener("click", select);
      row.addEventListener("keydown", e => {
        if (e.key === "Enter" || e.key === " ") { e.preventDefault(); select(); }
      });
      box.appendChild(row);
    }
    setStatus(
      `Isolation Forest anomali — ${data.as_of}, ${data.window_days} gün, `
      + `sigma ${data.sigma_multiplier}, anomali ${data.anomaly_count}/${data.cell_count} — ${data.attribution}`);
  }
  function focusIfaCell(cell, row) {
    for (const el of document.querySelectorAll("#ifa-panel .item.sel")) {
      el.classList.remove("sel");
    }
    if (row) row.classList.add("sel");
    // Harita senkron seçim: hücre sınırlarına odaklan ve vurgula.
    const bounds = L.latLngBounds(
      [[cell.min_lat, cell.min_lon], [cell.max_lat, cell.max_lon]]);
    map.fitBounds(bounds, { padding: [40, 40] });
    if (ifaHighlight) { map.removeLayer(ifaHighlight); }
    ifaHighlight = L.rectangle(bounds, {
      color: "#2166ac", weight: 3, dashArray: "6 4",
      fillColor: "#2166ac", fillOpacity: 0.12,
    }).addTo(map);
    ifaHighlight.bindPopup(
      `<b>${escapeHtml(cell.name || cell.region_key)}</b><br>`
      + `anomali skoru: ${escapeHtml(String(cell.anomaly_score))} `
      + `(temel: ${escapeHtml(ifaBasisLabel(cell.detection_basis))})<br>`
      + `baz: ${escapeHtml(String(cell.baseline_mean))} ± ${escapeHtml(String(cell.baseline_std))}<br>`
      + `sessizlik eşiği: ${escapeHtml(String(cell.quiet_threshold))} · son: ${escapeHtml(String(cell.latest_value))}`);
    ifaHighlight.openPopup();
  }
  async function scanIfaLatest() {
    const box = document.getElementById("ifa-list");
    panelLoading(box, "isolation_forest_anomaly");
    try {
      const res = await fetch(`${IFA_API}/latest?${ifaParams().toString()}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      const keys = (data.anomaly_region_keys || []);
      setStatus(
        `Anlık anomali taraması — ${data.scored_at} (aralık ${data.interval_minutes} dk): `
        + `${data.anomaly_count}/${data.cell_count} hücre anomali`
        + (keys.length ? ` (${escapeHtml(keys.slice(0, 6).join(", "))}${keys.length > 6 ? "…" : ""})` : "")
        + ` — ${data.attribution}`);
      await loadIfa();
    } catch (err) {
      box.innerHTML = panelErrorHtml("isolation_forest_anomaly", err.message);
      setStatus(`Anlık anomali taraması yapılamadı: ${err.message}`);
    }
  }

  // --- EM-037: yüksek öncelikli sessiz bölge (yayılım riski × sessizlik) ----
  const SRISK_API = "/api/v1/silent-region-risk";
  async function toggleSRiskPanel() {
    const panel = document.getElementById("srisk-panel");
    if (sriskPanelOpen) {
      sriskPanelOpen = false;
      panel.style.display = "none";
      if (sriskHighlight) { map.removeLayer(sriskHighlight); sriskHighlight = null; }
      return;
    }
    sriskPanelOpen = true;
    panel.style.display = "block";
    await loadSRisk();
  }
  async function loadSRisk() {
    const box = document.getElementById("srisk-list");
    panelLoading(box, "silent_region_risk");
    try {
      const res = await fetch(`${SRISK_API}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      renderSRiskList(data);
    } catch (err) {
      box.innerHTML = panelErrorHtml("silent_region_risk", err.message);
      setStatus(`Sessiz bölge risk kesişimi alınamadı: ${err.message}`);
    }
  }
  function renderSRiskList(data) {
    const box = document.getElementById("srisk-list");
    const countEl = document.getElementById("srisk-count");
    // Son yanıtı önbelleğe al: öncelik süzmesi sunucuya gitmeden yeniden işlenir.
    box.dataset.sriskLast = JSON.stringify(data);
    let rows = (data.regions || []).slice();
    const onlyFlagged = document.getElementById("srisk-flagged").checked;
    if (onlyFlagged) { rows = rows.filter(r => r.is_high_priority); }
    const s = data.summary || {};
    if (countEl) {
      countEl.textContent = `(${s.high_priority_regions || 0}/${s.active_silent_regions || 0})`;
    }
    box.innerHTML = "";
    if (!rows.length) {
      panelEmpty(box, "silent_region_risk",
        "Yayılım tahmini ulaşan yüksek öncelikli sessiz bölge yok.");
      setStatus(`Yüksek öncelikli sessiz bölge — öncelik dışı — ${data.attribution}`);
      return;
    }
    for (const region of rows) {
      const row = document.createElement("div");
      row.className = "item";
      row.setAttribute("role", "button");
      row.tabIndex = 0;
      const color = region.is_high_priority ? "#c62828" : "#9e9e9e";
      const riskPct = Math.round((region.risk_degree || 0) * 100);
      const silPct = Math.round((region.silence_degree || 0) * 100);
      const threat = region.worst_threat
        ? `<br><span class="threat">← ${escapeHtml(region.worst_threat.fire_name)}`
          + ` (${escapeHtml(String(region.worst_threat.horizon_minutes))} dk)</span>`
        : "";
      row.innerHTML =
        `<span class="dot" style="background:${color}"></span>`
        + `<span><b class="nm">${escapeHtml(region.region_name)}</b>`
        + `<br><span class="meta">risk %${riskPct} · sessiz %${silPct}</span>${threat}</span>`
        + `<span class="pri">${escapeHtml(String(region.priority_score))}</span>`;
      const select = () => focusSRiskRegion(region, row);
      row.addEventListener("click", select);
      row.addEventListener("keydown", e => {
        if (e.key === "Enter" || e.key === " ") { e.preventDefault(); select(); }
      });
      box.appendChild(row);
    }
    setStatus(
      `Yüksek öncelikli sessiz bölge — kesişen ${s.intersecting_regions || 0}, `
      + `öncelikli ${s.high_priority_regions || 0} — ${data.attribution}`);
  }
  function focusSRiskRegion(region, row) {
    for (const el of document.querySelectorAll("#srisk-panel .item.sel")) {
      el.classList.remove("sel");
    }
    if (row) row.classList.add("sel");
    // Harita senkron seçim: bölge kutusuna odaklan ve vurgula.
    const bounds = L.latLngBounds(
      [[region.min_lat, region.min_lon], [region.max_lat, region.max_lon]]);
    map.fitBounds(bounds, { padding: [40, 40] });
    if (sriskHighlight) { map.removeLayer(sriskHighlight); }
    const stroke = region.is_high_priority ? "#c62828" : "#616161";
    sriskHighlight = L.rectangle(bounds, {
      color: stroke, weight: 3, dashArray: "6 4",
      fillColor: stroke, fillOpacity: 0.14,
    }).addTo(map);
    const threat = region.worst_threat
      ? `<br>tehdit: ${escapeHtml(region.worst_threat.fire_name)}`
        + ` (${escapeHtml(region.worst_threat.severity)})`
      : "";
    sriskHighlight.bindPopup(
      `<b>${escapeHtml(region.region_name)}</b><br>`
      + `risk: ${escapeHtml(String(region.risk_degree))}`
      + ` · sessizlik: ${escapeHtml(String(region.silence_degree))}`
      + `<br>öncelik: ${escapeHtml(String(region.priority_score))}${threat}`);
    sriskHighlight.openPopup();
  }

  // --- EM-038: yanlış alarm önleme — sessiz aday güven etiketi --------------
  const SZC_API = "/api/v1/silent-zone-confidence";
  const SZC_COLORS = { high: "#c62828", medium: "#ef6c00", low: "#9e9e9e" };
  async function toggleSZCPanel() {
    const panel = document.getElementById("szc-panel");
    if (szcPanelOpen) {
      szcPanelOpen = false;
      panel.style.display = "none";
      if (szcHighlight) { map.removeLayer(szcHighlight); szcHighlight = null; }
      return;
    }
    szcPanelOpen = true;
    panel.style.display = "block";
    await loadSZC();
  }
  async function loadSZC() {
    const box = document.getElementById("szc-list");
    panelLoading(box, "silent_zone_confidence");
    try {
      const res = await fetch(`${SZC_API}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      renderSZCList(data);
    } catch (err) {
      box.innerHTML = panelErrorHtml("silent_zone_confidence", err.message);
      setStatus(`Sessiz bölge güven etiketleri alınamadı: ${err.message}`);
    }
  }
  function renderSZCList(data) {
    const box = document.getElementById("szc-list");
    const countEl = document.getElementById("szc-count");
    // Son yanıtı önbelleğe al: güven süzmesi sunucuya gitmeden yeniden işlenir.
    box.dataset.szcLast = JSON.stringify(data);
    let rows = (data.candidates || []).slice();
    const pick = document.getElementById("szc-confidence").value;
    if (pick && pick !== "all") { rows = rows.filter(r => r.confidence_code === pick); }
    const s = data.summary || {};
    if (countEl) {
      countEl.textContent = `(yüksek ${s.high_confidence || 0}/${s.candidate_silent_count || 0})`;
    }
    box.innerHTML = "";
    if (!rows.length) {
      panelEmpty(box, "silent_zone_confidence",
        "Seçilen güven bandında etiketlenmiş sessiz aday yok.");
      return;
    }
    for (const cell of rows) {
      const row = document.createElement("div");
      row.className = "item";
      row.setAttribute("role", "button");
      row.tabIndex = 0;
      const color = SZC_COLORS[cell.confidence_code] || "#9e9e9e";
      const weak = (cell.coverage_strength === "weak" || cell.coverage_strength === "insufficient_data")
        ? `<br><span class="weak">zayıf kapsama — yanlış alarm olabilir</span>` : "";
      const synTag = data.synthetic
        ? `<span class="syn">SENTETİK</span> ` : "";
      row.innerHTML =
        `<span class="dot" style="background:${color}"></span>`
        + `<span><b class="nm">${synTag}${escapeHtml(cell.name)}</b>`
        + `<br><span class="meta">baz ${escapeHtml(String(cell.baseline_mean))}`
        + ` · z=${escapeHtml(String(cell.z_score))}</span>${weak}</span>`
        + `<span class="cf">${escapeHtml(cell.confidence_label)}</span>`;
      const select = () => focusSZCRegion(cell, row);
      row.addEventListener("click", select);
      row.addEventListener("keydown", e => {
        if (e.key === "Enter" || e.key === " ") { e.preventDefault(); select(); }
      });
      box.appendChild(row);
    }
    setStatus(
      `Yanlış alarm önleme — yüksek ${s.high_confidence || 0}, orta ${s.medium_confidence || 0}, `
      + `düşük ${s.low_confidence || 0} — ${data.attribution}`);
  }
  function focusSZCRegion(cell, row) {
    for (const el of document.querySelectorAll("#szc-panel .item.sel")) {
      el.classList.remove("sel");
    }
    if (row) row.classList.add("sel");
    // Harita senkron seçim: hücre kutusuna odaklan ve vurgula.
    const bounds = L.latLngBounds(
      [[cell.min_lat, cell.min_lon], [cell.max_lat, cell.max_lon]]);
    map.fitBounds(bounds, { padding: [40, 40] });
    if (szcHighlight) { map.removeLayer(szcHighlight); }
    const stroke = SZC_COLORS[cell.confidence_code] || "#616161";
    szcHighlight = L.rectangle(bounds, {
      color: stroke, weight: 3, dashArray: "6 4",
      fillColor: stroke, fillOpacity: 0.14,
    }).addTo(map);
    const reason = (cell.confidence_reasons || []).map(escapeHtml).join("<br>");
    szcHighlight.bindPopup(
      `<b>${escapeHtml(cell.name)}</b><br>`
      + `güven: ${escapeHtml(cell.confidence_label)} · kapsama: ${escapeHtml(cell.coverage_strength)}<br>`
      + `baz: ${escapeHtml(String(cell.baseline_mean))} · z=${escapeHtml(String(cell.z_score))}<br>${reason}`);
    szcHighlight.openPopup();
  }

  // --- EM-042: sessiz bölge performans ölçümü — sentetik senaryo ------------
  const SDP_API = "/api/v1/silent-detection-performance";
  async function toggleSDPPanel() {
    const panel = document.getElementById("sdp-panel");
    if (sdpPanelOpen) { sdpPanelOpen = false; panel.style.display = "none"; return; }
    sdpPanelOpen = true;
    panel.style.display = "block";
    await loadSDP();
  }
  async function loadSDP() {
    const box = document.getElementById("sdp-list");
    panelLoading(box, "silent_detection_performance");
    const horizon = document.getElementById("sdp-horizon").value;
    try {
      const res = await fetch(`${SDP_API}?horizon_days=${encodeURIComponent(horizon)}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      renderSDP(data);
    } catch (err) {
      box.innerHTML = panelErrorHtml("silent_detection_performance", err.message);
      setStatus(`Sessiz bölge performans ölçümü alınamadı: ${err.message}`);
    }
  }
  function _sdpPct(v) {
    return v === null || v === undefined ? "—" : `${Math.round(v * 1000) / 10}%`;
  }
  function renderSDP(data) {
    const box = document.getElementById("sdp-list");
    const metricsBox = document.getElementById("sdp-metrics");
    const countEl = document.getElementById("sdp-count");
    box.dataset.sdpLast = JSON.stringify(data);
    const c = data.confusion || {};
    const delay = data.alert_delay || {};
    if (countEl) {
      countEl.textContent = `(epizot ${data.episode_count || 0}, hücre-gün ${c.evaluated_cell_days || 0})`;
    }
    if (metricsBox) {
      metricsBox.innerHTML =
        `<div><b>TPR</b> ${_sdpPct(data.tpr)}</div>`
        + `<div><b>FPR</b> ${_sdpPct(data.fpr)}</div>`
        + `<div><b>kesginlik</b> ${_sdpPct(data.precision)}</div>`
        + `<div><b>F1</b> ${_sdpPct(data.f1)}</div>`
        + `<div><b>gecikme ort.</b> ${escapeHtml(String(delay.mean_days ?? "—"))} gün</div>`
        + `<div><b>kaçırılan</b> ${escapeHtml(String(delay.undetected_episodes ?? 0))}</div>`;
    }
    box.innerHTML = "";
    const episodes = (data.episodes || []).slice();
    if (!episodes.length) {
      panelEmpty(box, "silent_detection_performance",
        "Enjekte edilmiş sessiz epizot yok; enjekte oranını/ufku artırın.");
      return;
    }
    for (const ep of episodes) {
      const row = document.createElement("div");
      row.className = "item";
      const color = ep.detected ? "#2e7d32" : "#b71c1c";
      const scenTag = data.synthetic ? `<span class="scen">SENTETİK SEN.</span> ` : "";
      const delayTxt = ep.detected
        ? `gecikme ${escapeHtml(String(ep.alert_delay_days))} gün`
        : `<span class="miss">kaçırıldı</span>`;
      row.innerHTML =
        `<span class="dot" style="background:${color}"></span>`
        + `<span><b class="nm">${scenTag}${escapeHtml(ep.region_key)}</b>`
        + `<br><span class="meta">başlangıç ${escapeHtml(ep.onset)} · ${ep.positive_cell_days} pozitif gün</span></span>`
        + `<span class="cf">${delayTxt}</span>`;
      box.appendChild(row);
    }
    setStatus(
      `Sessiz bölge performans — TPR ${_sdpPct(data.tpr)}, FPR ${_sdpPct(data.fpr)}, `
      + `gecikme ort. ${delay.mean_days ?? "—"} gün — ${data.scenario_label}`);
  }

  // --- EM-040: sessiz bölge uyarıları — yüksek öncelikli bölge uyarı beslemesi
  const SRA_API = "/api/v1/silent-region-alerts";
  const SRA_COLORS = { kritik: "#b71c1c", yuksek: "#e65100", orta: "#f9a825", dusuk: "#9e9e9e" };
  // --- EM-041: sessiz bölge doğrulama — operatör hükmü (doğrulandı/yanlış alarm/inceleniyor)
  const SZV_API = "/api/v1/silent-zone-verifications";
  const SZV_STATUS = [
    { code: "verified", label: "Doğrulandı", color: "#1b5e20" },
    { code: "false_alarm", label: "Yanlış alarm", color: "#b71c1c" },
    { code: "under_review", label: "İnceleniyor", color: "#f9a825" },
  ];
  async function toggleSRAPanel() {
    const panel = document.getElementById("sra-panel");
    if (sraPanelOpen) {
      sraPanelOpen = false;
      panel.style.display = "none";
      if (sraHighlight) { map.removeLayer(sraHighlight); sraHighlight = null; }
      return;
    }
    sraPanelOpen = true;
    panel.style.display = "block";
    await loadSRA();
  }
  async function loadSRA() {
    const box = document.getElementById("sra-list");
    panelLoading(box, "silent_region_alert");
    try {
      const res = await fetch(`${SRA_API}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      renderSRA(data);
      // EM-041: hükümler + geri bildirim özetini paralel çek, satırları zenginleştir.
      await Promise.all([loadSZVVerdicts(), loadSZVFeedback()]);
      const cached = box.dataset.sraLast;
      if (cached) renderSRA(JSON.parse(cached));
    } catch (err) {
      box.innerHTML = panelErrorHtml("silent_region_alert", err.message);
      setStatus(`Sessiz bölge uyarıları alınamadı: ${err.message}`);
    }
  }
  async function loadSZVVerdicts() {
    try {
      const res = await fetch(`${SZV_API}/current`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      szvVerdicts = {};
      for (const v of (data.verdicts || [])) { szvVerdicts[v.region_id] = v; }
    } catch (err) {
      setStatus(`Doğrulama hükümleri alınamadı: ${err.message}`);
    }
  }
  async function loadSZVFeedback() {
    const el = document.getElementById("szv-feedback");
    try {
      const res = await fetch(`${SZV_API}/feedback`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      szvFeedback = await res.json();
      renderSZVFeedback();
    } catch (err) {
      szvFeedback = null;
      if (el) el.style.display = "none";
    }
  }
  function renderSZVFeedback() {
    const el = document.getElementById("szv-feedback");
    if (!el) return;
    const f = szvFeedback;
    if (!f || !f.total_verifications) { el.style.display = "none"; return; }
    const by = f.by_status || {};
    const rate = (f.false_alarm_rate === null || f.false_alarm_rate === undefined)
      ? "—" : `${Math.round(f.false_alarm_rate * 100)}%`;
    el.style.display = "block";
    el.innerHTML =
      `Doğrulama geri bildirimi — `
      + `<b>${by.verified || 0}</b> doğrulandı · `
      + `<b>${by.false_alarm || 0}</b> yanlış alarm · `
      + `<b>${by.under_review || 0}</b> inceleniyor<br>`
      + `Yanlış alarm oranı: <b>${escapeHtml(rate)}</b> `
      + `(${f.adjudicated_region_count || 0} bölge karara bağlandı)`;
  }
  async function markSRA(regionId, status, regionName) {
    const opEl = document.getElementById("sra-operator");
    const verifiedBy = opEl ? opEl.value.trim() : "";
    setStatus(`İşleniyor: ${regionName} → ${status}…`);
    try {
      const res = await fetch(`${SZV_API}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          region_id: regionId, status, region_name: regionName,
          verified_by: verifiedBy || null,
        }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.error || `HTTP ${res.status}`);
      }
      await loadSZVVerdicts();
      await loadSZVFeedback();
      const box = document.getElementById("sra-list");
      if (box.dataset.sraLast) renderSRA(JSON.parse(box.dataset.sraLast));
      setStatus(`${regionName} hükmi kaydedildi — ${status}`);
    } catch (err) {
      setStatus(`Doğrulama kaydedilemedi: ${err.message}`);
    }
  }
  function renderSRA(data) {
    const box = document.getElementById("sra-list");
    const countEl = document.getElementById("sra-count");
    // Son yanıtı önbelleğe al: risk seviyesi süzmesi sunucuya gitmeden yeniden işlenir.
    box.dataset.sraLast = JSON.stringify(data);
    let rows = (data.alerts || []).slice();
    const pick = document.getElementById("sra-level").value;
    if (pick && pick !== "all") { rows = rows.filter(a => a.risk_level_code === pick); }
    const s = data.summary || {};
    if (countEl) {
      countEl.textContent = `(${rows.length}/${s.high_priority_regions || 0})`;
    }
    box.innerHTML = "";
    if (!rows.length) {
      panelEmpty(box, "silent_region_alert",
        "Yayılım tehdidi ulaşan yüksek öncelikli sessiz bölge yok.");
      return;
    }
    for (const alert of rows) {
      const row = document.createElement("div");
      row.className = "item";
      row.setAttribute("role", "button");
      row.tabIndex = 0;
      const color = SRA_COLORS[alert.risk_level_code] || "#9e9e9e";
      const supp = alert.suppressed_duplicate_alerts > 0
        ? `<br><span class="supp">+${alert.suppressed_duplicate_alerts} tekrar uyarı bastırıldı</span>` : "";
      const threat = alert.threatening_fire_count > 0
        ? `<span class="threat">← ${alert.threatening_fire_count} aktif yangın</span>` : "";
      // EM-041: bu bölgenin güncel operatör hükmü (yoksa boş).
      const verdict = szvVerdicts[alert.region_id];
      const vMeta = SZV_STATUS.find(s => s.code === (verdict && verdict.status));
      const vBadge = verdict
        ? ` <span class="verdict" style="background:${vMeta ? vMeta.color : "#616161"}">`
          + `${escapeHtml(verdict.status_label || verdict.status)}</span>`
        : "";
      row.innerHTML =
        `<span class="dot" style="background:${color}"></span>`
        + `<span style="flex:1"><b class="nm">${escapeHtml(alert.region_name)}</b>${vBadge}`
        + `<br><span class="meta">${escapeHtml(String(alert.silence_duration_hours))} saattir sessiz`
        + ` · ${escapeHtml(String(alert.silence_duration_days))} gün</span>`
        + `<br>${threat}${supp}`
        + `<div class="markrow"></div></span>`
        + `<span class="lvl" style="background:${color}">${escapeHtml(alert.risk_level_label)}</span>`;
      // Satır içi işaretleme düğmeleri: mevcut hükümde ilgili düğme pasif.
      const markHost = row.querySelector(".markrow");
      for (const s of SZV_STATUS) {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.textContent = s.label;
        if (verdict && verdict.status === s.code) { btn.disabled = true; }
        btn.addEventListener("click", e => {
          e.stopPropagation();
          markSRA(alert.region_id, s.code, alert.region_name);
        });
        markHost.appendChild(btn);
      }
      const select = () => focusSRARegion(alert, row);
      row.addEventListener("click", select);
      row.addEventListener("keydown", e => {
        if (e.key === "Enter" || e.key === " ") { e.preventDefault(); select(); }
      });
      box.appendChild(row);
    }
    setStatus(
      `Sessiz bölge uyarıları — ${s.emitted_alerts || 0} uyarı, `
      + `${s.suppressed_duplicate_alerts || 0} tekrar bastırıldı — ${data.attribution}`);
  }
  function focusSRARegion(alert, row) {
    for (const el of document.querySelectorAll("#sra-panel .item.sel")) {
      el.classList.remove("sel");
    }
    if (row) row.classList.add("sel");
    // Harita senkron seçim: uyarı bölgesinin kutusuna odaklan ve vurgula.
    const bb = alert.bounding_box || {};
    const bounds = L.latLngBounds([[bb.min_lat, bb.min_lon], [bb.max_lat, bb.max_lon]]);
    map.fitBounds(bounds, { padding: [40, 40] });
    if (sraHighlight) { map.removeLayer(sraHighlight); }
    const stroke = SRA_COLORS[alert.risk_level_code] || "#616161";
    sraHighlight = L.rectangle(bounds, {
      color: stroke, weight: 3, dashArray: "6 4",
      fillColor: stroke, fillOpacity: 0.14,
    }).addTo(map);
    sraHighlight.bindPopup(
      `<b>${escapeHtml(alert.region_name)}</b><br>`
      + `risk: ${escapeHtml(alert.risk_level_label)} · öncelik ${escapeHtml(String(alert.priority_score))}<br>`
      + `${escapeHtml(String(alert.silence_duration_hours))} saattir sessiz<br>`
      + `${escapeHtml(String(alert.threatening_fire_count))} aktif yangın tehdidi`);
    sraHighlight.openPopup();
  }

  // --- EM-044: sessiz bölge hassasiyet ve eşik ayarı — bölge bazlı editör
  const SZT_API = "/api/v1/silent-zone-tuning";
  async function toggleSZTPanel() {
    const panel = document.getElementById("szt-panel");
    if (sztPanelOpen) {
      sztPanelOpen = false;
      panel.style.display = "none";
      return;
    }
    sztPanelOpen = true;
    panel.style.display = "block";
    await loadSZTConfig();
    await loadSZT();
  }
  async function loadSZTConfig() {
    if (sztConfig) { renderSZTConfig(); return; }
    try {
      const res = await fetch(`${SZT_API}/config`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      sztConfig = await res.json();
      renderSZTConfig();
    } catch (err) {
      setStatus(`Ayar sınırları alınamadı: ${err.message}`);
    }
  }
  function renderSZTConfig() {
    const el = document.getElementById("szt-config");
    if (!el || !sztConfig) return;
    const d = sztConfig.defaults || {};
    const b = sztConfig.bounds || {};
    const zb = b.sensitivity_z || {};
    const hb = b.min_silence_hours || {};
    el.style.display = "block";
    el.innerHTML =
      `Varsayılan — eşik (z): <b>${escapeHtml(String(d.sensitivity_z ?? "—"))}</b> `
      + `(sınır ${escapeHtml(String(zb.min ?? "—"))}–${escapeHtml(String(zb.max ?? "—"))}), `
      + `min sessizlik: <b>${escapeHtml(String(d.min_silence_hours ?? "—"))}</b> sa `
      + `(sınır ${escapeHtml(String(hb.min ?? "—"))}–${escapeHtml(String(hb.max ?? "—"))})<br>`
      + `Ayarlanmamış bölge varsayılanı devralır; her değişiklik denetim kaydına yazılır.`;
  }
  async function loadSZT() {
    const box = document.getElementById("szt-list");
    panelLoading(box, "silent_zone_tuning");
    try {
      const res = await fetch(`${SZT_API}/effective`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      renderSZT(data);
    } catch (err) {
      box.innerHTML = panelErrorHtml("silent_zone_tuning", err.message);
      setStatus(`Sessiz bölge ayarları alınamadı: ${err.message}`);
    }
  }
  function renderSZT(data) {
    const box = document.getElementById("szt-list");
    const countEl = document.getElementById("szt-count");
    const rows = data.regions || [];
    const tuned = rows.filter(r => r.is_overridden).length;
    if (countEl) { countEl.textContent = `(${rows.length} bölge · ${tuned} ayarlanmış)`; }
    box.innerHTML = "";
    if (!rows.length) {
      panelEmpty(box, "silent_zone_tuning",
        "Etkin sessiz bölge yok; ayarlanacak bölge önce sessiz bölge olarak kaydedilmeli.");
      return;
    }
    const def = (sztConfig && sztConfig.defaults) || {};
    for (const r of rows) {
      const item = document.createElement("div");
      item.className = "item";
      const srcTag = r.is_overridden
        ? `<span class="src ovr">ayarlandı${r.updated_by ? " · " + escapeHtml(r.updated_by) : ""}</span>`
        : `<span class="src">varsayılan</span>`;
      item.innerHTML =
        `<b class="nm">${escapeHtml(r.region_name)}</b> #${escapeHtml(String(r.region_id))} ${srcTag}`
        + `<div class="knobs">`
        + `<label>Eşik (z-skoru)<input type="number" step="0.1" class="z" `
        + `value="${escapeHtml(String(r.sensitivity_z))}" `
        + `placeholder="vars. ${escapeHtml(String(def.sensitivity_z ?? ""))}"></label>`
        + `<label>Min sessizlik (sa)<input type="number" step="0.5" class="h" `
        + `value="${escapeHtml(String(r.min_silence_hours))}" `
        + `placeholder="vars. ${escapeHtml(String(def.min_silence_hours ?? ""))}"></label>`
        + `</div>`
        + `<div class="acts"><button type="button" class="save">Kaydet</button>`
        + `<button type="button" class="reset">Varsayılana dön</button></div>`;
      item.querySelector(".save").addEventListener("click", () => {
        const z = item.querySelector(".z").value;
        const h = item.querySelector(".h").value;
        saveSZT(r.region_id, r.region_name, z, h);
      });
      item.querySelector(".reset").addEventListener("click", () => {
        resetSZT(r.region_id, r.region_name);
      });
      box.appendChild(item);
    }
    setStatus(`Sessiz bölge ayarları — ${rows.length} bölge, ${tuned} ayarlanmış — ${data.attribution || ""}`);
  }
  async function saveSZT(regionId, regionName, zVal, hVal) {
    const opEl = document.getElementById("szt-operator");
    const actor = opEl ? opEl.value.trim() : "";
    const body = { region_id: regionId, actor: actor || null };
    if (zVal !== "") { body.sensitivity_z = Number(zVal); }
    if (hVal !== "") { body.min_silence_hours = Number(hVal); }
    if (body.sensitivity_z === undefined && body.min_silence_hours === undefined) {
      setStatus("En az bir alan doldurulmalı (eşik veya min sessizlik).");
      return;
    }
    setStatus(`Kaydediliyor: ${regionName}…`);
    try {
      const res = await fetch(`${SZT_API}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error((err.detail && err.detail.error) || err.error || `HTTP ${res.status}`);
      }
      await loadSZT();
      setStatus(`${regionName} ayarı kaydedildi — denetim kaydına yazıldı`);
    } catch (err) {
      setStatus(`Ayar kaydedilemedi: ${err.message}`);
    }
  }
  async function resetSZT(regionId, regionName) {
    const opEl = document.getElementById("szt-operator");
    const actor = opEl ? opEl.value.trim() : "";
    setStatus(`Varsayılana döndürülüyor: ${regionName}…`);
    try {
      const res = await fetch(`${SZT_API}/reset`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ region_id: regionId, actor: actor || null }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error((err.detail && err.detail.error) || err.error || `HTTP ${res.status}`);
      }
      await loadSZT();
      setStatus(`${regionName} varsayılana döndürüldü`);
    } catch (err) {
      setStatus(`Varsayılana döndürülemedi: ${err.message}`);
    }
  }

