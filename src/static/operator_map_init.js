/*
 * operator_map monolith split (code-quality audit). Behaviour-preserving:
 * same statements, same order, one shared global lexical scope across
 * classic scripts. init bootstrap: init() wiring + final init().catch() launch (must stay last).
 */
"use strict";
  async function init() {
    const res = await fetch(API);
    if (!res.ok) throw new Error(`Katman kataloğu alınamadı: HTTP ${res.status}`);
    const catalog = await res.json();
    if (!catalog || !Array.isArray(catalog.layers)) throw new Error("Geçersiz katalog yanıtı");
    catalogLayers = catalog.layers;
    for (const meta of catalog.layers) {
      layers[meta.key] = makeGeoJsonLayer(meta.key);
    }
    // Toggleable overlays: operator aç/kapa yapabilir (Leaflet layer control).
    const overlays = {};
    for (const meta of catalog.layers) {
      if (layers[meta.key]) overlays[meta.title] = layers[meta.key];
    }
    const baseLayers = { "Temel harita": baseTiles };
    L.control.layers(baseLayers, overlays, { collapsed: false })
      .addTo(map);

    document.getElementById("horizon-slider").addEventListener("input", e => {
      sliderIndex = Number(e.target.value);
      renderHorizons();
    });
    document.getElementById("horizon-cumulative").addEventListener("change", renderHorizons);

    // EM-055: what-if rüzgar senaryosu panelini bağla.
    const whatifOpen = document.getElementById("whatif-open");
    if (whatifOpen) {
      whatifOpen.addEventListener("click", () => {
        if (whatifEnabled) { closeWhatif(); } else { openWhatif(); }
      });
    }
    for (const id of ["whatif-dir", "whatif-speed", "whatif-temp", "whatif-humidity"]) {
      const el = document.getElementById(id);
      if (el) el.addEventListener("input", scheduleWhatif);
    }
    const whatifRot45 = document.getElementById("whatif-rot45");
    if (whatifRot45) {
      whatifRot45.addEventListener("click", () => {
        document.getElementById("whatif-dir").value = "45";
        runWhatif();
      });
    }
    const whatifReset = document.getElementById("whatif-reset");
    if (whatifReset) {
      whatifReset.addEventListener("click", () => {
        document.getElementById("whatif-dir").value = "0";
        document.getElementById("whatif-speed").value = "100";
        document.getElementById("whatif-temp").value = "0";
        document.getElementById("whatif-humidity").value = "0";
        if (whatifEnabled) { runWhatif(); }
      });
    }
    // EM-059: senaryo kaydet / yükle / paylaş düğmeleri.
    const scenSave = document.getElementById("whatif-scen-save");
    if (scenSave) scenSave.addEventListener("click", saveScenario);
    const scenLoad = document.getElementById("whatif-scen-load");
    if (scenLoad) scenLoad.addEventListener("click", loadScenario);
    const scenShare = document.getElementById("whatif-scen-share");
    if (scenShare) scenShare.addEventListener("click", shareScenario);
    // EM-062: geçmiş geri alma / temizleme düğmeleri.
    const histRevert = document.getElementById("whatif-hist-revert");
    if (histRevert) histRevert.addEventListener("click", revertHistory);
    const histClear = document.getElementById("whatif-hist-clear");
    if (histClear) histClear.addEventListener("click", clearHistory);
    // Haritaya tıklama, olay seçili değilken ignisyon noktası olur.
    map.on("click", ev => {
      mapClickPoint = ev.latlng;
      updateWhatifIgnitionHint();
      if (whatifEnabled) { scheduleWhatif(); }
    });

    // EM-023: olay filtresi değişince hem listeyi hem harita katmanını yenile.
    const exposureSel = document.getElementById("exposure-event");
    if (exposureSel) {
      exposureSel.addEventListener("change", async e => {
        exposureEventKey = e.target.value || null;
        if (layers.exposure && map.hasLayer(layers.exposure)) {
          try { await loadLayer("exposure"); }
          catch (err) { statusLayerError(err); }
        } else {
          document.getElementById("exposure-panel").style.display = "none";
        }
        // EM-052: olay değişince konumlandırma katmanı da yeniden hesaplanır.
        if (layers.positioning && map.hasLayer(layers.positioning)) {
          try { await loadLayer("positioning"); }
          catch (err) { statusLayerError(err); }
        } else {
          document.getElementById("positioning-panel").style.display = "none";
        }
        // EM-055: olay değişince what-if ignisyon noktası da güncellenir.
        updateWhatifIgnitionHint();
        if (whatifEnabled) { scheduleWhatif(); }
      });
    }

    // Aktif yangın + risk bölgeleri varsayılan açık; diğerleri tembel yüklenir.
    const controlDiv = document.querySelector(".leaflet-control-layers");
    if (controlDiv) {
      controlDiv.addEventListener("change", async () => {
        for (const meta of catalog.layers) {
          const layer = layers[meta.key];
          if (!layer) continue;
          const on = map.hasLayer(layer);
          if (on && !layer._loaded) {
            layer._loaded = true;
            try { await loadLayer(meta.key); }
            catch (err) { statusLayerError(err); }
          }
          if (!on && meta.key === "exposure") {
            document.getElementById("exposure-panel").style.display = "none";
          }
          if (!on && meta.key === "positioning") {
            document.getElementById("positioning-panel").style.display = "none";
          }
        }
      });
    }

    for (const key of ["fires", "forecasts"]) {
      const layer = layers[key];
      if (!layer) continue;
      layer.addTo(map);
      layer._loaded = true;
      try { await loadLayer(key); } catch (err) { statusLayerError(err); }
    }

    // EM-090: canlı akışı başlat; sayfa kapanırken yeniden bağlanmayı durdur.
    window.addEventListener("beforeunload", () => {
      liveClosed = true;
      if (alertEvalTimer) { clearInterval(alertEvalTimer); alertEvalTimer = null; }
      if (liveSocket) { try { liveSocket.close(); } catch (err) { /* yoksay */ } }
    });
    startLive();

    // EM-079: panel durum kataloğunu çek ve bağlantı bandı yeniden-dene düğmesini bağla.
    await loadUiStates();
    const connRetry = document.getElementById("conn-lost-retry");
    if (connRetry) {
      connRetry.addEventListener("click", () => {
        showConnLost(false);
        if (liveSocket) { try { liveSocket.close(); } catch (err) { /* yoksay */ } }
        startLive();
      });
    }

    // EM-032: risk eşik aşımı değerlendirmesini periyodik yokla (uyarılar
    // canlı beslemeye yazılır ve WebSocket/REST yordamıyla tüm istemcilere akar).
    const soundBtn = document.getElementById("sound-toggle");
    if (soundBtn) {
      // İlk kullanıcı hareketi WebAudio kilitini açar.
      const unlock = () => { primeAudio(); document.removeEventListener("pointerdown", unlock); };
      document.addEventListener("pointerdown", unlock);
      soundBtn.addEventListener("click", () => {
        alertSoundOn = !alertSoundOn;
        soundBtn.classList.toggle("off", !alertSoundOn);
        soundBtn.textContent = alertSoundOn ? "🔔 Ses" : "🔇 Ses";
        if (alertSoundOn) { primeAudio(); }
      });
    }
    evaluateRiskAlerts();
    alertEvalTimer = setInterval(evaluateRiskAlerts, 30000);

    // EM-078: sessiz bölge güven paneli düğmesi + bant filtresi.
    const silentBtn = document.getElementById("silent-open");
    if (silentBtn) silentBtn.addEventListener("click", toggleSilentPanel);
    const silentFilter = document.getElementById("silent-filter");
    if (silentFilter) silentFilter.addEventListener("change", loadSilentZones);

    // EM-081: olay zaman çizelgesi düğmesi + kategori filtresi.
    const timelineBtn = document.getElementById("timeline-open");
    if (timelineBtn) timelineBtn.addEventListener("click", toggleTimelinePanel);
    const timelineFilter = document.getElementById("timeline-filter");
    if (timelineFilter) timelineFilter.addEventListener("change", loadEventTimeline);

    // EM-082: çoklu yangın yönetimi düğmesi.
    const multifireBtn = document.getElementById("multifire-open");
    if (multifireBtn) multifireBtn.addEventListener("click", toggleMultifirePanel);

    // EM-083: salt okunur belediye görünümü düğmesi.
    const belediyeBtn = document.getElementById("belediye-open");
    if (belediyeBtn) belediyeBtn.addEventListener("click", toggleBelediyePanel);

    // EM-086: bildirim merkezi düğmesi.
    const bildirimBtn = document.getElementById("bildirim-open");
    if (bildirimBtn) bildirimBtn.addEventListener("click", toggleBildirimPanel);

    // EM-087: durum raporu (SITREP) düğmesi.
    const sitrepBtn = document.getElementById("sitrep-open");
    if (sitrepBtn) sitrepBtn.addEventListener("click", toggleSitrepPanel);

    // EM-089: vardiya devri düğmeleri + not formu.
    const handoverBtn = document.getElementById("handover-open");
    if (handoverBtn) handoverBtn.addEventListener("click", toggleHandoverPanel);
    const handoverAdd = document.getElementById("handover-add");
    if (handoverAdd) handoverAdd.addEventListener("click", addHandoverNote);
    const handoverRefresh = document.getElementById("handover-listen");
    if (handoverRefresh) handoverRefresh.addEventListener("click", loadHandoverNotes);
    const handoverSummaryBtn = document.getElementById("handover-summary-btn");
    if (handoverSummaryBtn) handoverSummaryBtn.addEventListener("click", buildHandoverSummary);

    // EM-094: webhook düğmeleri + abonelik formu.
    const webhookBtn = document.getElementById("webhook-open");
    if (webhookBtn) webhookBtn.addEventListener("click", toggleWebhookPanel);
    const webhookAdd = document.getElementById("webhook-add");
    if (webhookAdd) webhookAdd.addEventListener("click", addWebhookSubscription);
    const webhookDispatch = document.getElementById("webhook-dispatch");
    if (webhookDispatch) webhookDispatch.addEventListener("click", dispatchWebhooks);
    const webhookRetry = document.getElementById("webhook-retry");
    if (webhookRetry) webhookRetry.addEventListener("click", retryWebhooks);
    const webhookRefresh = document.getElementById("webhook-refresh");
    if (webhookRefresh) webhookRefresh.addEventListener("click", loadWebhooks);

    // EM-096: denetim kaydı düğmeleri + filtre/ekleme formu.
    const auditBtn = document.getElementById("audit-open");
    if (auditBtn) auditBtn.addEventListener("click", toggleAuditPanel);
    const auditAdd = document.getElementById("audit-add");
    if (auditAdd) auditAdd.addEventListener("click", addAuditEntry);
    const auditRefresh = document.getElementById("audit-refresh");
    if (auditRefresh) auditRefresh.addEventListener("click", loadAudit);
    const auditFilterDomain = document.getElementById("audit-filter-domain");
    if (auditFilterDomain) auditFilterDomain.addEventListener("change", loadAudit);

    // EM-035: sinyal baz çizgisi düğmeleri + kaynak/tarih/filtre seçimleri.
    const signalBtn = document.getElementById("signal-open");
    if (signalBtn) signalBtn.addEventListener("click", toggleSignalPanel);
    const signalRefresh = document.getElementById("signal-refresh");
    if (signalRefresh) signalRefresh.addEventListener("click", loadSignalBaseline);
    const signalSource = document.getElementById("signal-source");
    if (signalSource) signalSource.addEventListener("change", loadSignalBaseline);
    const signalAsof = document.getElementById("signal-asof");
    if (signalAsof) signalAsof.addEventListener("change", loadSignalBaseline);
    const signalCandidate = document.getElementById("signal-candidate");
    if (signalCandidate) signalCandidate.addEventListener("change", () => {
      // Ön yüz süzme: son yanıt yeniden işlenir, sunucuya gidilmez.
      const box = document.getElementById("signal-list");
      if (box && box.dataset.signalLast) {
        renderSignalList(JSON.parse(box.dataset.signalLast));
      }
    });

    // EM-043: mevsimsel baz çizgisi düğmeleri + kaynak/saat/tarih/filtre seçimleri.
    const seasBtn = document.getElementById("seas-open");
    if (seasBtn) seasBtn.addEventListener("click", toggleSeasPanel);
    const seasRefresh = document.getElementById("seas-refresh");
    if (seasRefresh) seasRefresh.addEventListener("click", loadSeas);
    const seasRecompute = document.getElementById("seas-recompute");
    if (seasRecompute) seasRecompute.addEventListener("click", recomputeSeas);
    const seasSource = document.getElementById("seas-source");
    if (seasSource) seasSource.addEventListener("change", loadSeas);
    const seasHour = document.getElementById("seas-hour");
    if (seasHour) seasHour.addEventListener("change", loadSeas);
    const seasAsof = document.getElementById("seas-asof");
    if (seasAsof) seasAsof.addEventListener("change", loadSeas);
    const seasCandidate = document.getElementById("seas-candidate");
    if (seasCandidate) seasCandidate.addEventListener("change", () => {
      // Ön yüz süzme: son yanıt yeniden işlenir, sunucuya gidilmez.
      const box = document.getElementById("seas-list");
      if (box && box.dataset.seasLast) {
        renderSeas(JSON.parse(box.dataset.seasLast));
      }
    });

    // EM-036: Isolation Forest anomali düğmeleri + kaynak/sigma/pencere/tarih/süzme.
    const ifaBtn = document.getElementById("ifa-open");
    if (ifaBtn) ifaBtn.addEventListener("click", toggleIfaPanel);
    const ifaRefresh = document.getElementById("ifa-refresh");
    if (ifaRefresh) ifaRefresh.addEventListener("click", loadIfa);
    const ifaLatest = document.getElementById("ifa-latest");
    if (ifaLatest) ifaLatest.addEventListener("click", scanIfaLatest);
    const ifaSource = document.getElementById("ifa-source");
    if (ifaSource) ifaSource.addEventListener("change", loadIfa);
    const ifaSigma = document.getElementById("ifa-sigma");
    if (ifaSigma) ifaSigma.addEventListener("change", loadIfa);
    const ifaWindow = document.getElementById("ifa-window");
    if (ifaWindow) ifaWindow.addEventListener("change", loadIfa);
    const ifaAsof = document.getElementById("ifa-asof");
    if (ifaAsof) ifaAsof.addEventListener("change", loadIfa);
    const ifaAnomaly = document.getElementById("ifa-anomaly");
    if (ifaAnomaly) ifaAnomaly.addEventListener("change", () => {
      // Ön yüz süzme: son yanıt yeniden işlenir, sunucuya gidilmez.
      const box = document.getElementById("ifa-list");
      if (box && box.dataset.ifaLast) {
        renderIfa(JSON.parse(box.dataset.ifaLast));
      }
    });

    // EM-037: yüksek öncelikli sessiz bölge düğmeleri + öncelik süzmesi.
    const sriskBtn = document.getElementById("srisk-open");
    if (sriskBtn) sriskBtn.addEventListener("click", toggleSRiskPanel);
    const sriskRefresh = document.getElementById("srisk-refresh");
    if (sriskRefresh) sriskRefresh.addEventListener("click", loadSRisk);
    const sriskFlagged = document.getElementById("srisk-flagged");
    if (sriskFlagged) sriskFlagged.addEventListener("change", () => {
      // Ön yüz süzme: son yanıt yeniden işlenir, sunucuya gidilmez.
      const box = document.getElementById("srisk-list");
      if (box && box.dataset.sriskLast) {
        renderSRiskList(JSON.parse(box.dataset.sriskLast));
      }
    });

    // EM-038: yanlış alarm önleme güven paneli düğmeleri + güven süzmesi.
    const szcBtn = document.getElementById("szc-open");
    if (szcBtn) szcBtn.addEventListener("click", toggleSZCPanel);
    const szcRefresh = document.getElementById("szc-refresh");
    if (szcRefresh) szcRefresh.addEventListener("click", loadSZC);
    const szcConfidence = document.getElementById("szc-confidence");
    if (szcConfidence) szcConfidence.addEventListener("change", () => {
      // Ön yüz süzme: son yanıt yeniden işlenir, sunucuya gidilmez.
      const box = document.getElementById("szc-list");
      if (box && box.dataset.szcLast) {
        renderSZCList(JSON.parse(box.dataset.szcLast));
      }
    });

    // EM-042: sessiz bölge performans paneli düğmeleri + ufuk seçimi.
    const sdpBtn = document.getElementById("sdp-open");
    if (sdpBtn) sdpBtn.addEventListener("click", toggleSDPPanel);
    const sdpRefresh = document.getElementById("sdp-refresh");
    if (sdpRefresh) sdpRefresh.addEventListener("click", loadSDP);
    const sdpHorizon = document.getElementById("sdp-horizon");
    if (sdpHorizon) sdpHorizon.addEventListener("change", loadSDP);

    // EM-040: sessiz bölge uyarıları paneli düğmeleri + risk seviyesi süzmesi.
    const sraBtn = document.getElementById("sra-open");
    if (sraBtn) sraBtn.addEventListener("click", toggleSRAPanel);
    const sraRefresh = document.getElementById("sra-refresh");
    if (sraRefresh) sraRefresh.addEventListener("click", loadSRA);
    const sraLevel = document.getElementById("sra-level");
    if (sraLevel) sraLevel.addEventListener("change", () => {
      const box = document.getElementById("sra-list");
      if (box.dataset.sraLast) {
        renderSRA(JSON.parse(box.dataset.sraLast));
      }
    });

    // EM-044: sessiz bölge hassasiyet/eşik ayarı paneli düğmeleri.
    const sztBtn = document.getElementById("szt-open");
    if (sztBtn) sztBtn.addEventListener("click", toggleSZTPanel);
    const sztRefresh = document.getElementById("szt-refresh");
    if (sztRefresh) sztRefresh.addEventListener("click", loadSZT);

    // EM-080: harita aracı — altlık seçici + arama + ölçüm modu düğmeleri.
    const maptoolBtn = document.getElementById("maptool-open");
    if (maptoolBtn) maptoolBtn.addEventListener("click", toggleMapToolPanel);
    const mtBasemapSel = document.getElementById("mt-basemap");
    if (mtBasemapSel) mtBasemapSel.addEventListener("change", e => setBasemap(e.target.value));
    const mtSearchBtn = document.getElementById("mt-search");
    if (mtSearchBtn) mtSearchBtn.addEventListener("click", runMapSearch);
    const mtQuery = document.getElementById("mt-query");
    if (mtQuery) mtQuery.addEventListener("keydown", e => {
      if (e.key === "Enter") { e.preventDefault(); runMapSearch(); }
    });
    const mtDistBtn = document.getElementById("mt-mode-distance");
    if (mtDistBtn) mtDistBtn.addEventListener("click", () => enterMeasure("distance"));
    const mtAreaBtn = document.getElementById("mt-mode-area");
    if (mtAreaBtn) mtAreaBtn.addEventListener("click", () => enterMeasure("area"));
    const mtClearBtn = document.getElementById("mt-clear");
    if (mtClearBtn) mtClearBtn.addEventListener("click", () => {
      const keepMode = mtMode;
      exitMeasure();
      if (keepMode) enterMeasure(keepMode);
      const box = document.getElementById("mt-measure");
      if (box) box.innerHTML = "";
    });
    // Ölçüm modundayken haritaya tıklama noktayı toplar (EM-078 panelleriyle çakışmaz).
    map.on("click", measureClick);

    // EM-084: saha görünümü — aç/kapa + olay/kaynak/konum denetimleri.
    const fieldviewBtn = document.getElementById("fieldview-open");
    if (fieldviewBtn) fieldviewBtn.addEventListener("click", toggleFieldViewPanel);
    const fvRefresh = document.getElementById("fv-refresh");
    if (fvRefresh) fvRefresh.addEventListener("click", loadFieldView);
    const fvEventSel = document.getElementById("fv-event");
    if (fvEventSel) fvEventSel.addEventListener("change", loadFieldView);

    // EM-085: erişilebilirlik — panel düğmesi + katalog (tema/kodlama/kısayol) + genel kısayollar.
    const a11yBtn = document.getElementById("a11y-open");
    if (a11yBtn) a11yBtn.addEventListener("click", toggleAccessibilityPanel);
    await loadAccessibility();
    if (a11yConfig && a11yConfig.theme) a11yApplyTheme(a11yConfig.theme.default);
    bindGlobalShortcuts();

    // EM-098: kimlik doğrulama — panel düğmesi + sessiz oturum geri yükleme.
    const authBtn = document.getElementById("auth-open");
    if (authBtn) authBtn.addEventListener("click", toggleAuthPanel);
    await loadAuth();

    // EM-101: kullanici ve rol yonetimi — panel dugmesi (talep uzerine yuklenir).
    const userMgmtBtn = document.getElementById("user-mgmt-open");
    if (userMgmtBtn) userMgmtBtn.addEventListener("click", toggleUserMgmtPanel);

    // EM-100: guvenlik/gizlilik uygunlugu — panel dugmesi (talep uzerine yuklenir).
    const securityPrivacyBtn = document.getElementById("security-privacy-open");
    if (securityPrivacyBtn) securityPrivacyBtn.addEventListener("click", toggleSecurityPrivacyPanel);

    // EM-097: karar destek çerçevesi - öneri ekranında sorumluluk/versiyon şeridi
    // ve sentetik veri durumunda SENARYO VERİSİ rozeti (bir kez yüklenir).
    loadDecisionSupport();
  }

  init().catch(err => setStatus(`Harita başlatılamadı: ${err.message}`));
