/*
 * operator_map monolith split (code-quality audit). Behaviour-preserving:
 * same statements, same order, one shared global lexical scope across
 * classic scripts. core: strict-mode header, page state consts, DOM refs, base map init.
 */
"use strict";
  const API = "/api/v1/map/layers";
  const HORIZONS = [30, 60, 120];
  const HORIZON_COLORS = { 30: "#ffd400", 60: "#ff7f00", 120: "#d62728" };
  const LAYER_STYLE = {
    fires: f => f.properties.kind === "fire_event"
      ? { radius: 8, color: "#7c1a12", fillColor: "#e74c3c", fillOpacity: 0.85 }
      : { radius: 6, color: "#9c5a00", fillColor: "#f39c12", fillOpacity: 0.8 },
    fuel: { radius: 4, color: "#1b4d1e", fillColor: "#2e7d32", fillOpacity: 0.7 },
    "silent-regions": { color: "#616161", weight: 2, dashArray: "6 4",
                        fillColor: "#9e9e9e", fillOpacity: 0.35 },
    resources: f => {
      // EM-103 envanter varlıkları türe göre, üsler mavi; müsait olmayan gri.
      const assetFills = { crew: "#1565c0", helicopter: "#6a1b9a", uav: "#00838f" };
      const isAsset = f.properties.kind === "suppression_resource";
      const fill = isAsset ? (assetFills[f.properties.resource_type] || "#1565c0")
                           : "#1565c0";
      return f.properties.available
        ? { radius: 7, color: "#0d3c78", fillColor: fill, fillOpacity: 0.9 }
        : { radius: 7, color: "#5c5c5c", fillColor: "#9e9e9e", fillOpacity: 0.6 };
    },
    roads: { color: "#6d4c41", weight: 2, opacity: 0.65 },
    // EM-023: tehdit altındaki yapı — mor ailesi (risk bölgesi renklerinden ayrışır).
    exposure: f => {
      const t = f.properties.first_impact_minutes;
      const c = t <= 30 ? "#7b1fa2" : t <= 60 ? "#ab47bc" : "#ce93d8";
      return { radius: 7, weight: 2, color: "#4a148c", fillColor: c,
               fillOpacity: 0.9, opacity: 0.95 };
    },
    // EM-052: konuşlanma noktası (Point) turkuaz, önerilen rota (LineString) koyu turkuaz.
    positioning: f => (f.geometry && f.geometry.type === "Point")
      ? { radius: 8, weight: 2, color: "#004d40", fillColor: "#26a69a",
          fillOpacity: 0.95, opacity: 0.95 }
      : { color: "#00897b", weight: 3, opacity: 0.9 },
    // EM-020: kötümser zarf kesikli kırmızı, iyimser zarf noktalı yeşil.
    uncertainty: f => f.properties && f.properties.band === "pessimistic"
      ? { color: "#d62728", weight: 2, dashArray: "6 4",
          fillColor: "#d62728", fillOpacity: 0.08 }
      : { color: "#2e7d32", weight: 1, dashArray: "2 4",
          fillColor: "#2e7d32", fillOpacity: 0.05 },
  };

  const map = L.map("map", { zoomControl: true }).setView([37.75, 28.0], 9);
  const baseTiles = L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: "&copy; <a href=\"https://www.openstreetmap.org/copyright\">OpenStreetMap</a> contributors",
  }).addTo(map);

  const layers = {};        // key -> L.LayerGroup (display layer)
  let forecastByHorizon = {}; // horizon -> L.GeoJSON
  let forecastAll = null;   // raw FeatureCollection cache
  let uncertaintyAll = null; // EM-020 band FeatureCollection cache
  let sliderIndex = 2;      // 0..2 -> 30/60/120 dk
  let fireEvents = [];      // EM-023: {event_key, name} for the exposure filter
  let exposureEventKey = null; // EM-023: current exposure list/layer event filter
  // EM-052: son konumlandırma katmanı ögeleri ve rota referansları (odaklama için).
  let positioningFeatures = [];
  let positioningLayerRefs = {};   // proposal_id -> Leaflet rota katmanı
  // EM-055: what-if rüzgar senaryosu durumu.
  let whatifEnabled = false;
  let whatifResult = null;         // son what-if yanıtı (poligon+metrik)
  let whatifScenarioLayer = null;  // senaryo poligon katmanı (L.GeoJSON)
  let whatifAbort = null;          // devam eden istek iptal edici
  let whatifTimer = null;          // kaydırıcı debounce zamanlayıcısı
  let mapClickPoint = null;        // haritaya son tıklanan ignisyon noktası
  // EM-078: sessiz bölge güven paneli durumu.
  let silentPanelOpen = false;
  let silentRegions = [];           // son güven sıralı bölge listesi
  let silentHighlight = null;       // seçili bölgenin vurgu dikdörtgeni (L.Rectangle)
  // EM-081: olay zaman çizelgesi paneli durumu.
  let timelinePanelOpen = false;
  // EM-082: çoklu yangın yönetimi paneli durumu.
  let multifirePanelOpen = false;
  // EM-083: salt okunur belediye görünümü paneli durumu.
  let belediyePanelOpen = false;
  // EM-086: bildirim merkezi paneli durumu.
  let bildirimPanelOpen = false;
  // EM-087: durum raporu (SITREP) paneli durumu.
  let sitrepPanelOpen = false;
  // EM-089: vardiya devri notları + tek tık devir özeti paneli durumu.
  let handoverPanelOpen = false;
  // EM-094: olay & uyarı webhook'ları paneli durumu.
  let webhookPanelOpen = false;
  // EM-096: birleşik denetim kaydı paneli durumu.
  let auditPanelOpen = false;
  let auditConfigLoaded = false;
  // EM-035: sinyal baz çizgisi paneli durumu.
  let signalPanelOpen = false;
  let signalConfigLoaded = false;
  let signalHighlight = null;      // seçili hücrenin vurgu dikdörtgeni (L.Rectangle)
  // EM-043: mevsimsel sinyal baz çizgisi paneli durumu.
  let seasPanelOpen = false;
  let seasConfigLoaded = false;
  let seasHighlight = null;        // seçili hücrenin vurgu dikdörtgeni (L.Rectangle)
  // EM-036: Isolation Forest anomali skoru paneli durumu.
  let ifaPanelOpen = false;
  let ifaConfigLoaded = false;
  let ifaHighlight = null;         // seçili hücrenin vurgu dikdörtgeni (L.Rectangle)
  // EM-037: yüksek öncelikli sessiz bölge paneli durumu.
  let sriskPanelOpen = false;
  let sriskHighlight = null;       // seçili bölgenin vurgu dikdörtgeni (L.Rectangle)
  // EM-038: yanlış alarm önleme güven etiketi paneli durumu.
  let szcPanelOpen = false;
  let szcHighlight = null;         // seçili hücrenin vurgu dikdörtgeni (L.Rectangle)
  // EM-042: sessiz bölge performans ölçümü paneli durumu.
  let sdpPanelOpen = false;
  // EM-040: sessiz bölge uyarıları paneli durumu.
  let sraPanelOpen = false;
  let sraHighlight = null;       // seçili uyarı bölgesinin vurgu dikdörtgeni (L.Rectangle)
  // EM-041: sessiz bölge doğrulama — güncel hükümler (bölge_id → hüküm) + geri bildirim özeti.
  let szvVerdicts = {};
  let szvFeedback = null;
  // EM-044: sessiz bölge hassasiyet/eşik ayarı — panel durumu + config (sınırlar/varsayılanlar).
  let sztPanelOpen = false;
  let sztConfig = null;
  // EM-080: harita altlığı seçimi + yer/koordinat arama + mesafe/alan ölçüm aracı.
  let maptoolPanelOpen = false;
  let mtConfig = null;               // /api/v1/map/config yanıtı (altlıklar + sınırlar)
  let mtBasemapLayer = baseTiles;    // aktif altlık katmanı (başlangıç: sokak/OSM)
  let mtMode = null;                 // null | "distance" | "area" — ölçüm modu
  let mtPoints = [];                 // ölçüm için toplanan [enlem, boylam] noktaları
  let mtMarkers = null;              // ölçüm tepe işaretleri (L.LayerGroup)
  let mtShape = null;                // ölçüm poliline/poligon katmanı
  let mtSearchMarker = null;         // arama sonucu odak işareti
  // EM-084: saha görünümü — telefondan okunur görev kartı + yakın risk bölgesi.
  let fieldviewPanelOpen = false;
  let fvConfig = null;               // /api/v1/field-view/config yanıtı (yarıçap/sınır)
  // EM-085: erişilebilirlik — renk körü güvenli risk kodlaması + genel kısayollar.
  let a11yPanelOpen = false;
  let a11yConfig = null;             // /api/v1/accessibility/config yanıtı (kısayol/kodlama)
  let a11yPanelKeys = [];            // Alt+P ile gezilen operatör paneli anahtarları
  let a11yPanelIndex = -1;           // gezilen panelin sırası
  // EM-098: kimlik doğrulama — Bearer oturum sessionStorage'da yaşar (sekme-özel).
  let authPanelOpen = false;
  let authConfig = null;             // /api/v1/auth/config yanıtı (TTL/idle/kilitleme)
  let authToken = null;              // ham bearer token — yalnızca sessionStorage'da
  let authSession = null;            // /api/v1/auth/me yanıtı (girişliyse dolu)
  // EM-099: rol tabanlı yetkilendirme — /api/v1/authz/effective yanıtı.
  let authPerms = null;              // {enforced, authenticated, role, can_decide,...}
  // EM-101: kullanici ve rol yonetimi — /api/v1/users/manage yanitlari.
  let userMgmtPanelOpen = false;
  // EM-100: guvenlik/gizlilik uygunlugu — /api/v1/security-privacy (persistence: none).
  let securityPrivacyPanelOpen = false;
  let userMgmtConfig = null;         // /api/v1/users/manage/config (rol/ulke kataloğu)
  let userMgmtList = null;           // /api/v1/users/manage yanıtı (hesaplar)
  // EM-079: panel yükleme/boş/hata durumları + bağlantı-kesildi bandı kataloğu.
  const UI_STATES = { panels: {}, connection: null };  // /api/v1/ui-states'ten dolar

  // EM-090: canlı güncelleme (WebSocket) durumu.
  let catalogLayers = [];      // kataloğun meta listesi (canlı yenileme için)
  let liveSocket = null;       // /ws/live bağlantısı
  let liveLastId = 0;          // uygulanan son akış id'si (yeniden bağlanma imleci)
  let liveDelay = 1000;        // yeniden bağlanma geri çekilmesi (ms)
  let liveClosed = false;      // sayfa kapanıyor, yeniden bağlanmayı durdur
  let liveRefreshTimer = null; // katman yenilemelerini birleştirme (debounce)

  // EM-032: eşik aşımı uyarısı — sesli bildirim durumu ve değerlendirme yoklaması.
  let alertSoundOn = true;         // operatör kapatabilir (ses düğmesi)
  let alertAudioCtx = null;        // WebAudio bağlamı (ilk kullanıcı hareketiyle açılır)
  let alertEvalTimer = null;       // periyodik risk-uysalı değerlendirme

  const statusBox = document.getElementById("status");
  function setStatus(text) { statusBox.textContent = text; }

  // XSS guard: OSM asset names and live-feed messages are external data and
  // must never be interpolated raw into innerHTML. Delegates to the shared
  // helper (app.js) with this page's exact contract: String(value) and the
  // apostrophe escaped.
  function escapeHtml(value) {
    return WFS.escapeHtml(value, { escapeApostrophe: true });
  }

  function popupHtml(feature) {
    const p = feature.properties || {};
    // EM-052: konuşlanma noktası ve rota ögeleri komutan-dili özet.
    if (p.kind === "positioning_route" || p.kind === "deployment_point") {
      const eta = p.eta_minutes != null ? `T+${escapeHtml(p.eta_minutes)} dk` : "—";
      const km = p.distance_km != null ? ` &bull; ${escapeHtml(p.distance_km)} km` : "";
      const mode = p.travel_mode === "air" ? " &bull; Hava (kuş uçuşu)"
        : p.travel_mode === "road" ? " &bull; Kara (yol ağı)" : "";
      const head = p.kind === "deployment_point" ? "KONUŞLANMA" : "ROTA";
      return `<div style="font-size:12px;line-height:1.4">`
        + `<b>${head}: ${escapeHtml(p.name || "kaynak")}</b><br>`
        + `Tahmini varış: <b>${eta}</b>${km}<br>`
        + `<i>${escapeHtml(p.resource_type || "")}${mode}</i></div>`;
    }
    // EM-023: tehdit listesi ögeleri komutan-dili özet; diğerleri ham alan listesi.
    if (p.asset_type) {
      const label = ASSET_LABELS[p.asset_type] || p.asset_type;
      const name = p.name || "isimsiz";
      const pop = p.population ? ` &bull; ${escapeHtml(p.population)} kişi` : "";
      const demo = p.source && String(p.source).indexOf("demo") >= 0
        ? ' &bull; <i>demo verisi</i>' : "";
      const horizon = p.impact_horizon_minutes ? ` (${escapeHtml(p.impact_horizon_minutes)} dk dilimi)` : "";
      return `<div style="font-size:12px;line-height:1.4">`
        + `<b>${escapeHtml(label)}: ${escapeHtml(name)}</b><br>`
        + `İlk etki: <b>T+${escapeHtml(p.first_impact_minutes)} dk</b>${horizon}<br>`
        + `Öncelik skoru: <b>${p.priority_score != null ? escapeHtml(p.priority_score) : "—"}</b>`
        + `${pop}${demo}</div>`;
    }
    const lines = Object.entries(p)
      .filter(([, v]) => v !== null && v !== undefined)
      .map(([k, v]) => `<li><b>${escapeHtml(k)}</b>: ${escapeHtml(v)}</li>`);
    return `<ul style="margin:0;padding-left:16px;font-size:12px">${lines.join("")}</ul>`;
  }

  function styleFor(key, feature, isForecast) {
    if (isForecast) {
      const h = feature.properties.horizon_minutes;
      return { color: HORIZON_COLORS[h] || "#c0392b", weight: 2,
               fillColor: HORIZON_COLORS[h] || "#c0392b", fillOpacity: 0.25 };
    }
    const s = LAYER_STYLE[key];
    return typeof s === "function" ? s(feature) : s;
  }

  // EM-020: model güveni rozeti (Yüksek / Orta / Düşük / Bilinmiyor).
  const CONFIDENCE_COLORS = { high: "#2e7d32", moderate: "#f9a825",
                              low: "#c62828", unknown: "#9e9e9e" };
  function renderConfidence(conf) {
    const badge = document.getElementById("confidence-badge");
    if (!conf) { badge.textContent = "Model güveni: —"; return; }
    const band = conf.band || "unknown";
    const label = conf.label || band;
    const score = conf.score === null || conf.score === undefined ? "" : ` (${conf.score})`;
    badge.textContent = `Model güveni: ${label}${score}`;
    badge.style.background = CONFIDENCE_COLORS[band] || CONFIDENCE_COLORS.unknown;
    badge.title = conf.inputs_scored
      ? `EM-020: ${conf.inputs_scored} girdi kaynağından hesaplandı`
      : "EM-020: girdi kaynağı bilgisi yok";
  }

  function makeGeoJsonLayer(key) {
    return L.geoJSON(null, {
      style: f => styleFor(key, f, key === "forecasts"),
      pointToLayer: (f, latlng) => {
        const s = styleFor(key, f, false);
        return L.circleMarker(latlng, { stroke: true, ...s });
      },
      onEachFeature: (f, layer) => {
        if (f.properties) layer.bindPopup(popupHtml(f));
        // EM-052: rota çizgisi üzerinde sabit ETA etiketi; odaklama için referans.
        if (f.properties && f.properties.kind === "positioning_route") {
          if (f.properties.eta_minutes != null) {
            layer.bindTooltip(`T+${f.properties.eta_minutes} dk`,
              { permanent: true, direction: "center", className: "route-eta" });
          }
          if (f.properties.proposal_id) {
            positioningLayerRefs[f.properties.proposal_id] = layer;
          }
        }
      },
    });
  }

