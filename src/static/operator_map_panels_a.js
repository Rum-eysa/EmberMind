/*
 * operator_map monolith split (code-quality audit). Behaviour-preserving:
 * same statements, same order, one shared global lexical scope across
 * classic scripts. panels A: layer load, decision-support, assignments, field-view, auth, users, feedback, localization, what-if, scenarios, history.
 */
"use strict";
  async function loadLayer(key) {
    let url = `${API}/${key}`;
    if ((key === "exposure" || key === "positioning") && exposureEventKey) {
      url += `?event_key=${encodeURIComponent(exposureEventKey)}`;
    }
    const res = await fetch(url);
    if (!res.ok) throw new Error(`${key}: HTTP ${res.status}`);
    const data = await res.json();
    if (key === "fires") {
      // EM-023: olay filtresi için yangın olaylarını (tekrarsız) yakala.
      const seen = new Set();
      fireEvents = [];
      for (const f of data.features || []) {
        const p = f.properties || {};
        if (p.kind === "fire_event" && p.event_key && !seen.has(p.event_key)) {
          seen.add(p.event_key);
          const c = (f.geometry && f.geometry.coordinates) || [];
          // EM-055: what-if ignisyon noktası olay koordinatını kullanır.
          fireEvents.push({
            event_key: p.event_key, name: p.name,
            latitude: c.length ? c[1] : null, longitude: c.length ? c[0] : null,
          });
        }
      }
      populateExposureEvents();
      populateFieldViewEvents();
    }
    if (key === "forecasts") {
      forecastAll = data;
      renderHorizons();
      setStatus(`Risk bölgeleri: ${data.count} poligon`);
    } else if (key === "uncertainty") {
      // EM-020: bantlar ufuk seçimine göre renderHorizons içinde çizilir.
      uncertaintyAll = data;
      renderConfidence(data.model_confidence);
      renderHorizons();
      setStatus(`Belirsizlik bandı: ${data.count} poligon — ${data.attribution}`);
    } else {
      if (key === "positioning") { positioningLayerRefs = {}; }
      layers[key].clearLayers();
      layers[key].addData(data);
      setStatus(`${data.title}: ${data.count} öge`);
      if (key === "exposure") renderExposureList(data);
      if (key === "positioning") renderPositioningList(data);
    }
    if (data.attribution) setStatus(`${data.title}: ${data.count} öge — ${data.attribution}`);
    return data;
  }

  // EM-023: tehdit altındaki yerleşim/yol/altyapı için sıralı öncelik listesi.
  const ASSET_LABELS = { settlement: "Yerleşim", power_line: "Enerji hattı", road: "Yol" };
  function impactColor(t) { return t <= 30 ? "#7b1fa2" : t <= 60 ? "#ab47bc" : "#ce93d8"; }
  function populateExposureEvents() {
    const sel = document.getElementById("exposure-event");
    if (!sel) return;
    const current = sel.value;
    sel.innerHTML = '<option value="">Tüm yangınlar</option>';
    for (const ev of fireEvents) {
      const opt = document.createElement("option");
      opt.value = ev.event_key;
      opt.textContent = ev.name || ev.event_key;
      sel.appendChild(opt);
    }
    if (current) sel.value = current;
  }
  function renderExposureList(data) {
    const panel = document.getElementById("exposure-panel");
    const box = document.getElementById("exposure-list");
    const countEl = document.getElementById("exposure-count");
    panel.style.display = "block";
    box.innerHTML = "";
    const feats = (data.features || []).slice();
    if (countEl) countEl.textContent = feats.length ? `(${feats.length})` : "(0)";
    if (!feats.length) {
      panelEmpty(box, "exposure",
        "Seçili olayın tahmin poligonlarında tehdit altındaki yapı yok.");
      return;
    }
    // Backend öncelik skoruna göre sıralı; UI de aynı sırayı korur.
    feats.sort((a, b) =>
      (b.properties.priority_score || 0) - (a.properties.priority_score || 0)
      || a.properties.first_impact_minutes - b.properties.first_impact_minutes);
    for (const f of feats) {
      const p = f.properties;
      const row = document.createElement("div");
      row.className = "item";
      const label = ASSET_LABELS[p.asset_type] || p.asset_type;
      const name = p.name || "isimsiz";
      const pop = p.population ? ` (${escapeHtml(p.population)} kişi)` : "";
      const demo = p.source && String(p.source).indexOf("demo") >= 0
        ? ' <span class="badge">demo</span>' : "";
      row.innerHTML =
        `<span class="dot" style="background:${impactColor(p.first_impact_minutes)}"></span>` +
        `<span><b>${escapeHtml(label)}</b>: ${escapeHtml(name)}${pop}${demo}</span>` +
        `<span class="t">T+${escapeHtml(p.first_impact_minutes)} dk</span>` +
        `<span class="pri" title="Öncelik skoru (EM-023)">${p.priority_score != null ? escapeHtml(p.priority_score) : ""}</span>`;
      box.appendChild(row);
    }
  }

  // EM-097: karar destek çerçevesi - sorumluluk/versiyon şeridi + senaryo rozeti.
  async function loadDecisionSupport() {
    const frame = document.getElementById("ds-frame");
    const badge = document.getElementById("ds-scenario");
    if (!frame) return;
    try {
      const res = await fetch("/api/v1/decision-support");
      const j = await res.json();
      if (!res.ok) {
        frame.innerHTML = '<div class="ds-notice">Karar destek çerçevesi'
          + ' yüklenemedi.</div>';
        return;
      }
      let html = '<div class="ds-resp">' + escapeHtml(j.responsibility_statement || "")
        + '</div>';
      html += '<div class="ds-ver">model: ' + escapeHtml(j.model_version || "—")
        + ' · veri: ' + escapeHtml(j.data_version || "—") + '</div>';
      if (j.scenario_data) {
        html += '<div class="ds-notice">'
          + escapeHtml(j.scenario_notice || "Sentetik senaryo verisi.") + '</div>';
      }
      frame.innerHTML = html;
      if (badge) {
        badge.hidden = !j.scenario_data;
        if (j.scenario_badge) badge.textContent = j.scenario_badge;
      }
    } catch (err) {
      frame.innerHTML = '<div class="ds-notice">Karar destek çerçevesi'
        + ' yüklenemedi: ' + escapeHtml(err.message) + '</div>';
    }
  }

  // EM-100: guvenlik/gizlilik uygunluk karti — privacy-by-design + sır hijyeni + aktarım.
  async function toggleSecurityPrivacyPanel() {
    const panel = document.getElementById("security-privacy-panel");
    if (!panel) return;
    if (securityPrivacyPanelOpen) {
      securityPrivacyPanelOpen = false;
      panel.style.display = "none";
      return;
    }
    securityPrivacyPanelOpen = true;
    panel.style.display = "block";
    await loadSecurityPrivacy();
  }

  async function loadSecurityPrivacy() {
    const box = document.getElementById("security-privacy-body");
    if (!box) return;
    panelLoading(box, "security_privacy");
    try {
      const res = await fetch("/api/v1/security-privacy");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const j = await res.json();
      renderSecurityPrivacy(box, j);
    } catch (err) {
      box.innerHTML = panelErrorHtml("security_privacy", err.message);
    }
  }

  function spBadge(verdict) {
    const okCls = (verdict === "PASS" || verdict === "OK") ? "sp-pass" : "sp-warn";
    return `<span class="sp-badge ${okCls}">${escapeHtml(verdict)}</span>`;
  }

  function renderSecurityPrivacy(box, j) {
    const pr = j.privacy_by_design || {};
    const sh = j.secret_hygiene || {};
    const ts = j.transport_security || {};
    let html = "";
    // Overall verdict.
    html += `<div class="sp-section"><div class="sp-title">Genel uygunluk ${spBadge(j.overall)}</div>`;
    html += `<div class="sp-meta">${escapeHtml(j.attribution || "")}</div></div>`;
    // Privacy by design.
    html += `<div class="sp-section"><div class="sp-title">Gizlilik-tasarım ${spBadge(pr.verdict)}</div>`;
    html += `<div class="sp-meta">${pr.domain_tables || 0} gözlem/alan tablosu tarandı; `
      + `${pr.geo_keyed_count || 0} tanesi hücre/bölge/koordinat ile anahtarlı.</div>`;
    const findings = pr.personal_data_findings || [];
    if (findings.length) {
      html += `<div class="sp-warn">Bulgular: ` + findings.map((f) =>
        `${escapeHtml(f.table)}→${escapeHtml(f.columns)}`).join(", ") + `</div>`;
    } else {
      html += `<div class="sp-meta">Alan tablolarında kişisel-veri sütunu bulunmadı (KVKK/GDPR: kişi bazlı değil, bölge/hücre bazlı).</div>`;
    }
    const acct = pr.account_tables || [];
    if (acct.length) {
      html += `<div class="sp-meta">Hesap tabloları (personel girişi/denetimi, EM-098/EM-096): `
        + acct.map((t) => escapeHtml(t)).join(", ") + `</div>`;
    }
    html += `</div>`;
    // Secret hygiene.
    html += `<div class="sp-section"><div class="sp-title">Gizli-anahtar hijyeni ${spBadge(sh.verdict)}</div>`;
    html += `<div class="sp-meta">Değerler asla gösterilmez — yalnızca durum. Kaynak koduna gömülü sır: ${sh.hardcoded_secrets_in_source || 0}.</div>`;
    (sh.secrets || []).forEach((s) => {
      const stateLabel = s.state === "configured" ? "yapılandırıldı"
        : (s.state === "insecure_default" ? "GÜVENSİZ VARSAYILAN" : "ayarlanmadı");
      const cls = s.state === "configured" ? "sp-pass" : "sp-warn";
      html += `<div class="sp-secret-row"><span>${escapeHtml(s.setting)}</span>`
        + `<span class="${cls}">${escapeHtml(stateLabel)}${s.is_set ? ` (len ${s.value_length})` : ""}</span></div>`;
    });
    if ((sh.insecure_default_settings || []).length) {
      html += `<div class="sp-warn">Üretime geçmeden şu varsayılanları değiştirin: `
        + sh.insecure_default_settings.map((x) => escapeHtml(x)).join(", ") + `</div>`;
    }
    html += `</div>`;
    // Transport security (honest).
    html += `<div class="sp-section"><div class="sp-title">Aktarım güvenliği</div>`;
    html += `<div class="sp-meta">TLS sonlandırma: ${escapeHtml(ts.tls_terminated_by || "—")} · uygulama TLS sağlıyor mu: ${ts.app_provides_tls ? "evet" : "hayır"}.</div>`;
    html += `<div class="sp-meta">ters-vekil SSL başlığı: ${ts.trust_proxy_ssl_header ? "AÇIK" : "kapalı"} · oturum çerezi Secure: ${ts.session_cookie_secure ? "AÇIK" : "kapalı"}.</div>`;
    html += `<div class="sp-meta">${escapeHtml(ts.note || "")}</div>`;
    html += `</div>`;
    html += `<div class="sp-meta" style="margin-top:6px">${escapeHtml(pr.note || "")}</div>`;
    box.innerHTML = html;
  }

  // EM-052: önerilen konuşlanma listesi + seçilen rotaya otomatik odaklama.
  function focusProposal(proposalId) {
    const routeFeature = positioningFeatures.find(
      f => f.properties && f.properties.kind === "positioning_route"
         && f.properties.proposal_id === proposalId);
    if (routeFeature) {
      const bounds = L.geoJSON(routeFeature).getBounds();
      if (bounds.isValid()) map.fitBounds(bounds, { padding: [30, 30] });
    }
    const layer = positioningLayerRefs[proposalId];
    if (layer && layer.openPopup) layer.openPopup();
  }
  function renderPositioningList(data) {
    const panel = document.getElementById("positioning-panel");
    const box = document.getElementById("positioning-list");
    const countEl = document.getElementById("positioning-count");
    positioningFeatures = (data.features || []).slice();
    panel.style.display = "block";
    box.innerHTML = "";
    const points = positioningFeatures.filter(
      f => f.properties && f.properties.kind === "deployment_point");
    if (countEl) countEl.textContent = points.length ? `(${points.length})` : "(0)";
    // EM-048: uygulanirsA vs uygulanmazsa etki karsilastirmasi butonu.
    const impactBtn = document.getElementById("positioning-impact-btn");
    if (impactBtn) impactBtn.hidden = !points.length || !exposureEventKey;
    const impactBox = document.getElementById("positioning-impact");
    if (impactBox) { impactBox.hidden = true; impactBox.innerHTML = ""; }
    if (!points.length) {
      panelEmpty(box, "positioning",
        "Öneri yok. Yukarıdan bir olay seçin; seçili olay için müsait kaynak ve yol ağı olmalı.");
      return;
    }
    for (const f of points) {
      const p = f.properties;
      const row = document.createElement("div");
      row.className = "item";
      row.setAttribute("role", "button");
      row.tabIndex = 0;
      const eta = p.eta_minutes != null ? `T+${escapeHtml(p.eta_minutes)} dk` : "—";
      const km = p.distance_km != null ? ` &middot; ${escapeHtml(p.distance_km)} km` : "";
      const type = p.resource_type ? escapeHtml(p.resource_type) : "";
      const modeBadge = p.travel_mode === "air" ? ' <span class="mode mode-air">Hava</span>'
        : p.travel_mode === "road" ? ' <span class="mode mode-road">Kara</span>' : "";
      const decided = p.resource_key ? "" : " disabled";
      row.innerHTML =
        `<span><b>${escapeHtml(p.name || "kaynak")}</b>`
        + `${type ? ` <i>(${type})</i>` : ""}${modeBadge}${km}</span>`
        + `<span class="t">${eta}</span>`
        + `<span class="decide">`
        + `<button type="button" class="db db-why">Neden?</button>`
        + `<button type="button" class="db db-accept"${decided}>Kabul</button>`
        + `<button type="button" class="db db-edit"${decided}>Düzenle</button>`
        + `<button type="button" class="db db-reject"${decided}>Reddet</button>`
        + `</span>`
        + `<div class="why" hidden></div>`;
      const focus = () => focusProposal(p.proposal_id);
      row.addEventListener("click", focus);
      row.addEventListener("keydown", e => {
        if (e.key === "Enter" || e.key === " ") { e.preventDefault(); focus(); }
      });
      // EM-047: operatör öneri üzerinde nihai kararı verir.
      row.querySelector(".db-why")?.addEventListener("click", e => {
        e.stopPropagation(); explainProposal(p, row.querySelector(".why"));
      });
      row.querySelector(".db-accept")?.addEventListener("click", e => {
        e.stopPropagation(); decideProposal("accept", p);
      });
      row.querySelector(".db-edit")?.addEventListener("click", e => {
        e.stopPropagation(); decideProposal("edit", p);
      });
      row.querySelector(".db-reject")?.addEventListener("click", e => {
        e.stopPropagation(); decideProposal("reject", p);
      });
      box.appendChild(row);
    }
    // EM-099: karar düğmelerini rol yetkisine göre hemen kisitla.
    applyAuthorization();
    // EM-050: kısıt ihlali nedeniyle üretilmeyen öneriler + elenme nedenleri.
    const rejBox = document.createElement("div");
    rejBox.id = "positioning-rejected";
    rejBox.innerHTML = '<div class="rj-h">Kısıt nedeniyle elenen öneriler yükleniyor…</div>';
    box.appendChild(rejBox);
    loadRejectedProposals(rejBox);
  }

  // EM-050: menzil/mesai/gece/yol kapalılığı nedeniyle elenenleri getir.
  async function loadRejectedProposals(rejBox) {
    if (!exposureEventKey) { rejBox.innerHTML = ""; return; }
    try {
      const res = await fetch("/api/v1/positioning/proposals?event_key="
        + encodeURIComponent(exposureEventKey));
      const j = await res.json();
      if (!res.ok) { rejBox.innerHTML = ""; return; }
      const rej = j.rejected || [];
      if (!rej.length) {
        rejBox.innerHTML = '<div class="rj-h">Kısıt nedeniyle elenen öneri yok.</div>';
        return;
      }
      let html = '<div class="rj-h">Kısıt nedeniyle elenen öneri: <b>'
        + rej.length + '</b> (EM-050)</div>';
      for (const r of rej) {
        const cs = (r.constraints || []).map(c => escapeHtml(c)).join(", ");
        html += '<div class="rj-item"><b>' + escapeHtml(r.name || r.resource_key)
          + '</b> (' + escapeHtml(r.resource_type || "?") + ')' +
          ' <span class="rj-c">' + cs + '</span>'
          + '<div class="rj-r">' + escapeHtml(r.reason || "") + '</div></div>';
      }
      rejBox.innerHTML = html;
    } catch (err) {
      rejBox.innerHTML = '<div class="rj-h">Elenenler alinamadi.</div>';
    }
  }

  // EM-048: öneri uygulanırsa/uygulanmazsa risk karsilastirmasini getir, yan yana göster.
  async function loadImpactComparison() {
    const box = document.getElementById("positioning-impact");
    if (!box || !exposureEventKey) return;
    if (!box.hidden && box.dataset.loaded === exposureEventKey) { box.hidden = true; return; }
    box.hidden = false;
    box.innerHTML = '<div class="empty">Hesaplanıyor…</div>';
    try {
      const res = await fetch("/api/v1/recommendations/impact?event_key="
        + encodeURIComponent(exposureEventKey));
      const j = await res.json();
      if (!res.ok) {
        box.innerHTML = '<div class="empty">'
          + escapeHtml((j && j.detail && j.detail.error) || "Karsilastirma alinamadi.")
          + "</div>";
        return;
      }
      box.dataset.loaded = exposureEventKey;
      box.innerHTML = renderImpact(j);
    } catch (err) {
      box.innerHTML = '<div class="empty">Karsilastirma alinamadi.</div>';
    }
  }

  function renderImpact(j) {
    const s = j.summary || {};
    const cap = j.capacity || {};
    const rows = (j.side_by_side || []).map(r => {
      const na = r.if_not_applied || {}, ap = r.if_applied || {};
      return "<tr>"
        + `<td>T+${escapeHtml(r.horizon_minutes)} dk</td>`
        + `<td class="lv lv-${escapeHtml(na.level || "normal")}">${escapeHtml(na.level || "-")}</td>`
        + `<td class="lv lv-${escapeHtml(ap.level || "normal")}">${escapeHtml(ap.level || "-")}</td>`
        + `<td>${escapeHtml(r.risk_index_delta != null ? r.risk_index_delta : "—")}</td>`
        + "</tr>";
    }).join("");
    const committed = (j.committed_resources || [])
      .map(c => `${escapeHtml(c.name || c.resource_key)} (${escapeHtml(c.resource_type)})`)
      .join(", ") || "—";
    const value = s.decision_has_value ? "Evet" : "Hayır";
    return `<div class="imp-h">Kararın değeri: <b>${value}</b>`
      + ` &middot; bu olaya ayrılan kapasite: <b>${escapeHtml(cap.committed_ha_h)}</b>`
      + ` ${escapeHtml(j.unit || "")}/sa`
      + `<div class="imp-c">Önerilen kaynaklar: ${committed}</div>`
      + `<table class="imp-t"><thead><tr><th>Ufuk</th><th>Uygulanmazsa</th>`
      + `<th>Uygulanırsa</th><th>Δ risk</th></tr></thead>`
      + `<tbody>${rows}</tbody></table></div>`;
  }

  // EM-047: kabul/ret/düzenleme kararini sunucuya yaz ve kaynagi guncelle.
  async function decideProposal(action, p) {
    if (!p.resource_key) { setStatus("Oneri kaynagi belirsiz; karar verilemedi."); return; }
    let reason = null;
    let arrival = null;
    if (action === "reject") {
      const r = window.prompt("Ret gerekcesi (istege bagli):", "");
      if (r === null) return;
      reason = r || null;
    } else if (action === "edit") {
      const r = window.prompt("Varsis suresi (dk) — bos birakilirsa onerilen kalsin:", p.eta_minutes != null ? String(p.eta_minutes) : "");
      if (r === null) return;
      if (r.trim() !== "") { arrival = Number(r); }
      const g = window.prompt("Karar gerekcesi/not (istege bagli):", "");
      if (g === null) return;
      reason = g || null;
    }
    const body = {
      resource_key: p.resource_key,
      action,
      event_key: p.event_key || null,
      proposal_id: p.proposal_id || null,
      reason,
      arrival_minutes: arrival,
      detail: { name: p.name, resource_type: p.resource_type, eta_minutes: p.eta_minutes, distance_km: p.distance_km },
    };
    try {
      const res = await fetch("/api/v1/recommendations/decisions", {
        method: "POST",
        headers: Object.assign(
          { "Content-Type": "application/json" },
          authToken ? { Authorization: `Bearer ${authToken}` } : {}
        ),
        body: JSON.stringify(body),
      });
      const j = await res.json();
      if (!res.ok) {
        if (res.status === 403 || res.status === 401) {
          setStatus("Karar reddedildi (EM-099): bu rol için yetki yok / oturum gerekli.");
          return;
        }
        setStatus("Karar kaydedilemedi: " + (j.detail && j.detail.error ? j.detail.error : res.status));
        return;
      }
      const label = action === "accept" ? "Kabul" : action === "edit" ? "Duzenle-Kabul" : "Ret";
      const after = j.resource_status_after || "";
      setStatus(`Karar kaydedildi (${label}) — ${p.name || p.resource_key}: ${after}`);
      reloadPositioning();
      refreshTaskCards();
      refreshFeedback();
    } catch (err) {
      setStatus("Karar hatasi: " + err);
    }
  }

  // EM-047: karar sonrasi oneri listesini (ve kaynak durumunu) tazele.
  function reloadPositioning() {
    loadLayer("positioning").catch(() => {});
  }

  // EM-053: aktif atamalari goster; her satirda musaite al + bitenleri otomatik birak.
  function toggleAssignments() {
    const box = document.getElementById("positioning-assign");
    if (!box) return;
    if (!box.hidden) { box.hidden = true; return; }
    box.hidden = false;
    loadAssignments();
  }

  async function loadAssignments() {
    const box = document.getElementById("positioning-assign");
    if (!box) return;
    box.innerHTML = '<div class="empty">Yukleniyor…</div>';
    try {
      const res = await fetch("/api/v1/recommendations/assignments");
      const j = await res.json();
      if (!res.ok) { box.innerHTML = '<div class="empty">Atamalar alinamadi.</div>'; return; }
      const rows = j.assignments || [];
      let html = '<div class="as-h">Aktif atama: <b>' + rows.length + '</b></div>';
      if (!rows.length) {
        html += '<div class="empty">Atanmis kaynak yok.</div>';
      } else {
        html += '<table class="as-t"><thead><tr><th>Kaynak</th><th>Olay</th><th>Olay durumu</th><th></th></tr></thead><tbody>';
        for (const a of rows) {
          const evSt = a.event_status || "(bulunamadi)";
          html += '<tr>'
            + '<td>' + escapeHtml(a.resource_key) + '</td>'
            + '<td>' + escapeHtml(a.event_key || "—") + '</td>'
            + '<td>' + escapeHtml(evSt) + '</td>'
            + '<td><button type="button" class="db db-release"'
            + ' data-key="' + escapeHtml(a.resource_key) + '"'
            + ' data-event="' + escapeHtml(a.event_key || "") + '">Müsaite al</button></td>'
            + '</tr>';
        }
        html += '</tbody></table>';
      }
      html += '<button type="button" class="pi-btn" onclick="releaseCompleted()">'
        + 'Biten olaylari otomatik musaite al</button>';
      box.innerHTML = html;
      box.querySelectorAll(".db-release").forEach(btn => {
        btn.addEventListener("click", () => releaseAssignment(
          btn.getAttribute("data-key"), btn.getAttribute("data-event") || null));
      });
    } catch (err) {
      box.innerHTML = '<div class="empty">Atamalar alinamadi.</div>';
    }
  }

  async function releaseAssignment(resourceKey, eventKey) {
    try {
      const res = await fetch("/api/v1/recommendations/decisions/release", {
        method: "POST",
        headers: Object.assign(
          { "Content-Type": "application/json" },
          authToken ? { Authorization: `Bearer ${authToken}` } : {}
        ),
        body: JSON.stringify({ resource_key: resourceKey, event_key: eventKey }),
      });
      const j = await res.json();
      if (!res.ok) {
        if (res.status === 403 || res.status === 401) {
          setStatus("Musaite reddedildi (EM-099): bu rol için yetki yok / oturum gerekli.");
          return;
        }
        setStatus("Musaite alinamadi: " + (j.detail && j.detail.error ? j.detail.error : res.status));
        return;
      }
      setStatus(j.released ? (`Kaynak musaite alindi: ${resourceKey}`) : (`Kaynak zaten musaitti: ${resourceKey}`));
      loadAssignments();
      reloadPositioning();
    } catch (err) {
      setStatus("Musaite hatasi: " + err);
    }
  }

  async function releaseCompleted() {
    try {
      const res = await fetch("/api/v1/recommendations/assignments/release-completed", { method: "POST" });
      const j = await res.json();
      if (!res.ok) { setStatus("Otomatik birakma basarisiz."); return; }
      setStatus(`Otomatik musaite alinan: ${(j.count != null ? j.count : (j.released || []).length)}`);
      loadAssignments();
      reloadPositioning();
    } catch (err) {
      setStatus("Otomatik birakma hatasi: " + err);
    }
  }

  // EM-051: kabul edilen onerilerden saha gorev kartlarini ac/kapa.
  function toggleTaskCards() {
    const box = document.getElementById("positioning-taskcards");
    if (!box) return;
    if (!box.hidden) { box.hidden = true; return; }
    box.hidden = false;
    loadTaskCards();
  }

  // EM-051: panel aciksa karar/atama sonrasi kartlari tazele.
  function refreshTaskCards() {
    const box = document.getElementById("positioning-taskcards");
    if (box && !box.hidden) loadTaskCards();
  }

  async function loadTaskCards() {
    const box = document.getElementById("positioning-taskcards");
    if (!box) return;
    box.innerHTML = '<div class="empty">Yukleniyor…</div>';
    const qs = exposureEventKey
      ? "?event_key=" + encodeURIComponent(exposureEventKey) : "";
    try {
      const res = await fetch("/api/v1/recommendations/task-cards" + qs);
      const j = await res.json();
      if (!res.ok) {
        box.innerHTML = '<div class="empty">'
          + escapeHtml((j && j.detail && j.detail.error) || "Kartlar alinamadi.")
          + "</div>";
        return;
      }
      const cards = j.cards || [];
      let html = '<div class="as-h">Görev kartı: <b>' + cards.length + '</b>'
        + (exposureEventKey ? ' · olay: ' + escapeHtml(exposureEventKey) : '') + '</div>';
      if (!cards.length) {
        html += '<div class="empty">Kabul edilmiş görev yok.</div>';
      } else {
        for (const c of cards) html += renderTaskCard(c);
      }
      box.innerHTML = html;
    } catch (err) {
      box.innerHTML = '<div class="empty">Kartlar alinamadi.</div>';
    }
  }

  function renderTaskCard(c) {
    const t = c.target || {};
    const rn = c.risk_note;
    const risk = rn
      ? `<span class="lv lv-${escapeHtml(rn.level || "normal")}">${escapeHtml(rn.level || "-")}</span>`
        + ` risk ${escapeHtml(rn.risk_index != null ? rn.risk_index : "—")}`
        + ` (T+${escapeHtml(rn.horizon_minutes != null ? rn.horizon_minutes : "—")} dk)`
      : "risk notu yok";
    const eta = c.eta_minutes != null
      ? `ETA ${escapeHtml(c.eta_minutes)} dk` : "ETA —";
    const travel = c.travel_mode ? ` · ${escapeHtml(c.travel_mode)}` : "";
    const dist = c.distance_km != null ? ` · ${escapeHtml(c.distance_km)} km` : "";
    const arrival = c.arrival_eta ? ` · varış ${escapeHtml(c.arrival_eta)}` : "";
    const by = c.decided_by ? ` · ${escapeHtml(c.decided_by)}` : "";
    return '<div class="tc-card">'
      + '<div class="tc-h"><span>' + escapeHtml(c.resource_name || c.resource_key)
      + ' (' + escapeHtml(c.resource_type || "?") + ' → '
      + escapeHtml(c.resource_status || "?") + ')</span>'
      + '<span>' + escapeHtml(t.name || c.event_key || "—") + '</span></div>'
      + '<div class="tc-meta">Hedef: ' + escapeHtml(t.name || "—")
      + (t.latitude != null ? ` (${escapeHtml(t.latitude)}, ${escapeHtml(t.longitude)})` : "")
      + ` · ${eta}${travel}${dist}${arrival}</div>`
      + '<div class="tc-meta">' + risk + ' · kabul: '
      + escapeHtml(c.accepted_at || "—") + by + '</div>'
      + '</div>';
  }

  // EM-084: saha görünümü — telefondan okunur görev kartı + en yakın risk bölge(leri).
  const FIELDVIEW_API = "/api/v1/field-view";
  function populateFieldViewEvents() {
    const sel = document.getElementById("fv-event");
    if (!sel) return;
    const current = sel.value;
    sel.innerHTML = '<option value="">Tüm atanmış görevler</option>';
    for (const ev of fireEvents) {
      const opt = document.createElement("option");
      opt.value = ev.event_key;
      opt.textContent = ev.name || ev.event_key;
      sel.appendChild(opt);
    }
    if (current) sel.value = current;
  }
  async function toggleFieldViewPanel() {
    const panel = document.getElementById("fieldview-panel");
    if (fieldviewPanelOpen) {
      fieldviewPanelOpen = false;
      panel.style.display = "none";
      return;
    }
    fieldviewPanelOpen = true;
    panel.style.display = "block";
    await loadFieldViewConfig();
    loadFieldView();
  }
  async function loadFieldViewConfig() {
    try {
      const res = await fetch(`${FIELDVIEW_API}/config`);
      if (!res.ok) return;
      fvConfig = await res.json();
    } catch (err) {
      fvConfig = null;
    }
  }
  async function loadFieldView() {
    const box = document.getElementById("fv-body");
    if (!box) return;
    panelLoading(box, "field_view");
    const params = new URLSearchParams();
    const ev = (document.getElementById("fv-event") || {}).value || "";
    const rk = ((document.getElementById("fv-resource") || {}).value || "").trim();
    const lat = ((document.getElementById("fv-lat") || {}).value || "").trim();
    const lon = ((document.getElementById("fv-lon") || {}).value || "").trim();
    if (ev) params.set("event_key", ev);
    if (rk) params.set("resource_key", rk);
    if (lat !== "") params.set("latitude", lat);
    if (lon !== "") params.set("longitude", lon);
    const qs = params.toString();
    try {
      const res = await fetch(FIELDVIEW_API + (qs ? `?${qs}` : ""));
      const j = await res.json();
      if (!res.ok) {
        box.innerHTML = panelErrorHtml("field_view",
          (j && j.detail && j.detail.error) || "Saha görünümü alınamadı.");
        return;
      }
      renderFieldView(j);
    } catch (err) {
      box.innerHTML = panelErrorHtml("field_view", "Saha görünümü alınamadı: " + err.message);
      setStatus(`Saha görünümü alınamadı: ${err.message}`);
    }
  }
  function renderFieldView(j) {
    const box = document.getElementById("fv-body");
    const countEl = document.getElementById("fv-count");
    const cards = j.cards || [];
    const risks = j.nearby_risks || [];
    if (countEl) countEl.textContent = `(${cards.length})`;
    if (!cards.length && !risks.length) {
      panelEmpty(box, "field_view",
        "Atanmış görev yok; bir kaynak/olay seçin veya konum girin.");
      return;
    }
    const ref = j.reference || {};
    const originLabel = ref.origin === "coordinates" ? "konumunuz"
      : ref.origin === "task_card_target" ? "hedefiniz" : "—";
    let html = '<div class="fv-meta">Merkez: ' + originLabel
      + (ref.latitude != null
        ? ` (${escapeHtml(ref.latitude)}, ${escapeHtml(ref.longitude)})` : "")
      + ` · yarıçap ${escapeHtml(j.radius_km)} km</div>`;
    html += '<div class="fv-h">Görev kartı</div>';
    if (!cards.length) {
      html += '<div class="empty">Bu ekip için atanmış görev yok.</div>';
    } else {
      for (const c of cards) html += renderFieldViewCard(c);
    }
    html += '<div class="fv-h">Yakın risk bölgeleri</div>';
    if (!risks.length) {
      html += '<div class="empty">Yarıçap içinde aktif risk bölgesi yok.</div>';
    } else {
      for (const r of risks) html += renderFieldViewRisk(r);
    }
    box.innerHTML = html;
  }
  function renderFieldViewCard(c) {
    const t = c.target || {};
    const rn = c.risk_note;
    const eta = c.eta_minutes != null
      ? `ETA ${escapeHtml(c.eta_minutes)} dk` : "ETA —";
    const dist = c.distance_km != null ? ` · ${escapeHtml(c.distance_km)} km` : "";
    const arrival = c.arrival_eta ? ` · varış ${escapeHtml(c.arrival_eta)}` : "";
    const risk = rn
      ? `<span class="lv lv-${escapeHtml(rn.level || "normal")}">${escapeHtml(rn.level || "-")}</span>`
      : "risk notu yok";
    return '<div class="fv-card">'
      + '<div class="fv-h">' + escapeHtml(c.resource_name || c.resource_key)
      + ' (' + escapeHtml(c.resource_type || "?") + ')</div>'
      + '<div class="fv-meta">Hedef: ' + escapeHtml(t.name || "—")
      + (t.latitude != null ? ` (${escapeHtml(t.latitude)}, ${escapeHtml(t.longitude)})` : "")
      + ` · ${eta}${dist}${arrival}</div>`
      + '<div class="fv-meta">' + risk + '</div>'
      + '</div>';
  }
  function renderFieldViewRisk(r) {
    const lv = r.peak_level || "normal";
    const bearing = r.bearing_deg != null ? ` · ${escapeHtml(r.bearing_deg)}°` : "";
    const idx = r.peak_risk_index != null ? ` risk ${escapeHtml(r.peak_risk_index)}` : "";
    const horizon = r.peak_horizon_minutes != null
      ? ` (T+${escapeHtml(r.peak_horizon_minutes)} dk)` : "";
    return '<div class="fv-risk">'
      + '<span><b>' + escapeHtml(r.name || r.event_key) + '</b>'
      + `<span class="lv lv-${escapeHtml(lv)}">${escapeHtml(lv)}</span>${idx}${horizon}</span>`
      + '<span class="fv-dist">' + escapeHtml(r.distance_km) + ' km' + bearing + '</span>'
      + '</div>';
  }

  // EM-085: erişilebilirlik — renk körü güvenli risk kodlaması + tema + genel kısayol kataloğu.
  const ACCESSIBILITY_API = "/api/v1/accessibility";
  function a11yIsTyping(e) {
    const t = e.target;
    if (!t || !t.tagName) return false;
    const tag = t.tagName.toLowerCase();
    return tag === "input" || tag === "textarea" || tag === "select" || t.isContentEditable;
  }
  function a11yApplyTheme(theme) {
    const root = document.documentElement;
    if (theme === "light") root.setAttribute("data-theme", "light");
    else if (theme === "dark") root.setAttribute("data-theme", "dark");
    else root.removeAttribute("data-theme");  // auto -> prefers-color-scheme karari
  }
  function toggleTheme() {
    const cur = document.documentElement.getAttribute("data-theme");
    a11yApplyTheme(cur === "dark" ? "light" : "dark");
  }
  function cyclePanel() {
    // Panel düğmeleri arasinda sirayla odaklan (klavye ile erisim).
    const btns = Array.from(document.querySelectorAll('button[id$="-open"]'));
    if (!btns.length) return;
    a11yPanelIndex = (a11yPanelIndex + 1) % btns.length;
    btns[a11yPanelIndex].focus();
  }
  function dismissOverlays() {
    // Acik durumdaki operatör panellerini kapat; panel durumlarini sifirla.
    document.querySelectorAll('.panel').forEach(p => {
      if (p.id !== "status" && p.style && p.style.display === "block") p.style.display = "none";
    });
    a11yPanelOpen = false;
    fieldviewPanelOpen = false;
  }
  function a11yRunAction(action) {
    if (action === "toggle_theme") toggleTheme();
    else if (action === "cycle_panel") cyclePanel();
    else if (action === "focus_search") {
      const q = document.getElementById("mt-query");
      if (q) q.focus();
    } else if (action === "toggle_help") toggleAccessibilityPanel();
    else if (action === "dismiss") dismissOverlays();
  }
  function matchShortcut(e, combo) {
    const parts = combo.split("+");
    const key = parts[parts.length - 1].toUpperCase();
    const wantAlt = parts.includes("Alt");
    const wantShift = parts.includes("Shift");
    const wantCtrl = parts.includes("Ctrl") || parts.includes("Cmd");
    if (e.key.toUpperCase() !== key && !(key === "ESCAPE" && e.key === "Esc")) return false;
    return !!e.altKey === wantAlt && !!e.shiftKey === wantShift && !!e.ctrlKey === wantCtrl;
  }
  function bindGlobalShortcuts() {
    document.addEventListener("keydown", e => {
      // Esc her zaman calisir; diger kisollar yazarken tetiklenmez.
      if (e.key === "Escape") { a11yRunAction("dismiss"); return; }
      if (a11yIsTyping(e)) return;
      const list = (a11yConfig && a11yConfig.keyboard_shortcuts) || [];
      for (const s of list) {
        if (matchShortcut(e, s.combo)) { e.preventDefault(); a11yRunAction(s.action); return; }
      }
    });
  }
  async function toggleAccessibilityPanel() {
    const panel = document.getElementById("a11y-panel");
    if (!panel) return;
    if (a11yPanelOpen) {
      a11yPanelOpen = false;
      panel.style.display = "none";
      return;
    }
    a11yPanelOpen = true;
    panel.style.display = "block";
    await loadAccessibility();
  }
  async function loadAccessibility() {
    const box = document.getElementById("a11y-body");
    if (!box) return;
    panelLoading(box, "accessibility");
    try {
      const res = await fetch(`${ACCESSIBILITY_API}/config`);
      const j = await res.json();
      if (!res.ok) {
        box.innerHTML = panelErrorHtml("accessibility",
          (j && j.detail && j.detail.error) || "Erişilebilirlik kataloğu alınamadı.");
        return;
      }
      a11yConfig = j;
      renderAccessibility(j);
    } catch (err) {
      box.innerHTML = panelErrorHtml("accessibility", "Erişilebilirlik kataloğu alınamadı: " + err.message);
    }
  }
  function renderAccessibility(j) {
    const box = document.getElementById("a11y-body");
    if (!box) return;
    const enc = j.risk_encodings || [];
    const sc = j.keyboard_shortcuts || [];
    const theme = (j.theme && j.theme.default) || "dark";
    let html = '<div class="a11y-h">Tema</div>';
    html += `<div class="a11y-meta">Varsayılan: <b>${escapeHtml(theme)}</b> · gece vardiyası hazır`
      + ` · <span class="kbd">Alt+T</span> geçiş</div>`;
    html += '<div class="a11y-h">Risk kodlaması (renk + etiket + şekil + desen)</div>';
    if (!enc.length) {
      html += '<div class="empty">Risk kodlaması kataloğu boş.</div>';
    } else {
      for (const r of enc) html += renderA11yEncoding(r);
    }
    html += '<div class="a11y-h">Klavye kısayolları</div>';
    if (!sc.length) {
      html += '<div class="empty">Kısayol tanımlı değil.</div>';
    } else {
      html += '<ul class="a11y-sc">';
      for (const s of sc) html += renderA11yShortcut(s);
      html += '</ul>';
    }
    box.innerHTML = html;
  }
  function renderA11yEncoding(r) {
    const color = escapeHtml(r.color || "#888");
    return '<div class="a11y-enc">'
      + `<span class="a11y-swatch" style="background:${color}"></span>`
      + `<span class="a11y-glyph" aria-hidden="true">${escapeHtml(r.glyph || "?")}</span>`
      + `<span class="a11y-label">${escapeHtml(r.label || r.level)}</span>`
      + `<span class="a11y-pattern">${escapeHtml(r.pattern || "")}</span>`
      + '</div>';
  }
  function renderA11yShortcut(s) {
    return `<li><span class="kbd">${escapeHtml(s.combo)}</span> ${escapeHtml(s.description || "")}</li>`;
  }

  // EM-098: kimlik doğrulama — e-posta/parola girişi, Bearer oturum, güvenli çıkış.
  const AUTH_API = "/api/v1/auth";
  const AUTH_TOKEN_KEY = "embermind.auth.token";

  async function toggleAuthPanel() {
    const panel = document.getElementById("auth-panel");
    if (!panel) return;
    if (authPanelOpen) { authPanelOpen = false; panel.style.display = "none"; return; }
    authPanelOpen = true;
    panel.style.display = "block";
    await loadAuth();
  }

  async function loadAuth() {
    const box = document.getElementById("auth-body");
    if (!box) return;
    panelLoading(box, "auth");
    try {
      authToken = sessionStorage.getItem(AUTH_TOKEN_KEY) || null;
      if (!authConfig) {
        const cfg = await fetch(`${AUTH_API}/config`);
        authConfig = await cfg.json();
      }
      if (authToken) {
        const me = await fetch(`${AUTH_API}/me`, { headers: { Authorization: `Bearer ${authToken}` } });
        if (me.ok) authSession = await me.json();
        else { authSession = null; if (me.status === 401) sessionStorage.removeItem(AUTH_TOKEN_KEY); }
      } else {
        authSession = null;
      }
      await loadAuthorization();
      renderAuth(box);
    } catch (err) {
      box.innerHTML = panelErrorHtml("auth", "Kimlik doğrulama hizmeti yanıt vermedi: " + err.message);
    }
  }

  // EM-099: giris yapildiysa rolun efektif yetkilerini getir (UI dügme kisiti).
  async function loadAuthorization() {
    try {
      const res = await fetch("/api/v1/authz/effective", {
        headers: authToken ? { Authorization: `Bearer ${authToken}` } : {},
      });
      authPerms = res.ok ? await res.json() : null;
    } catch (err) {
      authPerms = null;
    }
    applyAuthorization();
  }

  // EM-099: uygulandigi ve izleyici oldugu durumda karar dügmelerini pasif kıl.
  function authzCannotDecide() {
    // Yalnızca uygulama ACIK + kimlik dogrulanmıs + karar yetkisi YOKSA kisitla.
    return Boolean(authPerms && authPerms.enforced && authPerms.authenticated
      && authPerms.can_decide === false);
  }

  function applyAuthorization() {
    const box = document.getElementById("positioning-list");
    if (!box) return;
    const blocked = authzCannotDecide();
    box.querySelectorAll(".db-accept, .db-edit, .db-reject").forEach((btn) => {
      btn.disabled = blocked;
      btn.title = blocked
        ? "Rolünüz öneri kararı vermeye yetkili değil (EM-099)"
        : "";
    });
  }

  function renderAuth(box) {
    if (authSession && authSession.user) {
      const u = authSession.user;
      const exp = new Date(authSession.session.expires_at);
      let authzLine = "";
      if (authPerms && authPerms.authenticated) {
        const perms = (authPerms.permissions || []).join(", ") || "—";
        const mode = authPerms.enforced ? "uygulanıyor" : "yalnızca görüntüleme (kapalı)";
        authzLine =
          `<div class="auth-meta">Yetki (EM-099): rol <b>${escapeHtml(String(authPerms.role))}</b>` +
          ` · yetkiler: ${escapeHtml(perms)} · durum: ${escapeHtml(mode)}</div>` +
          (authPerms.enforced && authPerms.can_decide === false
            ? `<div class="auth-err">Bu rol öneri kararı veremez (Kabul/Düzenle/Reddet pasif).</div>`
            : "");
      }
      box.innerHTML =
        `<div class="auth-user"><strong>${escapeHtml(u.display_name)}</strong>` +
        ` <span class="auth-role">${escapeHtml(u.role)}</span></div>` +
        `<div class="auth-meta">${escapeHtml(u.email)} · oturum bitişi ${escapeHtml(exp.toLocaleString())}` +
        ` · hareketsizlik limiti ${authConfig ? authConfig.session.idle_timeout_minutes : "?"} dk</div>` +
        authzLine +
        `<div style="margin-top:8px"><button type="button" id="auth-logout">Güvenli çıkış</button></div>`;
      const btn = document.getElementById("auth-logout");
      if (btn) btn.addEventListener("click", authLogout);
      return;
    }
    const s = authConfig ? authConfig.session : { ttl_minutes: "?", idle_timeout_minutes: "?" };
    box.innerHTML =
      `<div class="auth-meta">Oturum: mutlak ${escapeHtml(String(s.ttl_minutes))} dk` +
      ` · hareketsizlik ${escapeHtml(String(s.idle_timeout_minutes))} dk ·` +
      ` hatalı girişte hesap geçici kilitlenir</div>` +
      `<form id="auth-login-form" style="margin-top:8px;display:flex;flex-direction:column;gap:6px">` +
      `<input id="auth-email" type="email" placeholder="e-posta" autocomplete="username" required>` +
      `<input id="auth-password" type="password" placeholder="parola" autocomplete="current-password" required>` +
      `<button type="submit" class="btn">Giriş yap</button></form>`;
    const form = document.getElementById("auth-login-form");
    if (form) form.addEventListener("submit", authSubmit);
  }

  async function authSubmit(ev) {
    ev.preventDefault();
    const email = document.getElementById("auth-email").value;
    const password = document.getElementById("auth-password").value;
    const box = document.getElementById("auth-body");
    try {
      const res = await fetch(`${AUTH_API}/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password }),
      });
      const j = await res.json();
      if (!res.ok) {
        const why = (j && j.detail && j.detail.error) || "giriş başarısız";
        box.innerHTML =
          `<div class="auth-err">Giriş reddedildi: ${escapeHtml(String(why))}</div>` +
          `<div class="auth-meta">Reddi yanıtı birleşiktir — hesap varlığı hakkında bilgi verilmez.</div>`;
        return;
      }
      authToken = j.token;
      sessionStorage.setItem(AUTH_TOKEN_KEY, j.token);
      await loadAuth();
    } catch (err) {
      box.innerHTML = panelErrorHtml("auth", "Giriş isteği başarısız: " + err.message);
    }
  }

  async function authLogout() {
    try {
      await fetch(`${AUTH_API}/logout`, {
        method: "POST",
        headers: { Authorization: `Bearer ${authToken || ""}` },
      });
    } catch (e) { /* sunucu ulaşılamazsa yerel temizlik yine yapılır */ }
    sessionStorage.removeItem(AUTH_TOKEN_KEY);
    authToken = null;
    authSession = null;
    await loadAuth();
  }

  // EM-101: kullanici ve rol yonetimi — ekle/duzenle/devre birak + rol + ulke.
  const UM_API = "/api/v1/users/manage";

  function umHeaders(withBody) {
    const h = withBody ? { "Content-Type": "application/json" } : {};
    if (authToken) h.Authorization = `Bearer ${authToken}`;
    return h;
  }

  function umError(j, res) {
    const why = (j && j.detail && j.detail.error) || `istek başarısız (${res.status})`;
    return String(why);
  }

  async function toggleUserMgmtPanel() {
    const panel = document.getElementById("user-mgmt-panel");
    if (!panel) return;
    if (userMgmtPanelOpen) { userMgmtPanelOpen = false; panel.style.display = "none"; return; }
    userMgmtPanelOpen = true;
    panel.style.display = "block";
    await loadUserMgmt();
  }

  async function loadUserMgmt() {
    const box = document.getElementById("user-mgmt-body");
    if (!box) return;
    panelLoading(box, "user_management");
    try {
      if (!userMgmtConfig) {
        const cfg = await fetch(`${UM_API}/config`);
        userMgmtConfig = cfg.ok ? await cfg.json() : null;
      }
      const res = await fetch(UM_API, { headers: umHeaders(false) });
      userMgmtList = res.ok ? await res.json() : null;
      renderUserMgmt(box);
    } catch (err) {
      box.innerHTML = panelErrorHtml("user_management", "Kullanıcı yönetimi açılamadı: " + err.message);
    }
  }

  function renderUserMgmt(box) {
    const roles = userMgmtConfig ? userMgmtConfig.roles : ["operator"];
    const countries = userMgmtConfig ? userMgmtConfig.countries : [];
    const labels = (userMgmtConfig && userMgmtConfig.country_labels) || {};
    const users = userMgmtList ? userMgmtList.users : [];
    const enforced = Boolean(authPerms && authPerms.enforced);
    let html = "";
    html += enforced
      ? `<div class="um-meta">Yetki uygulaması AÇIK (EM-099). Yönetim izni olmayan rol 403 alır; işlem sahibi kanıtlanmış oturumdan yazılır.</div>`
      : `<div class="um-meta">Yetki uygulaması KAPALI — işlemler aşağıdaki operatör etiketiyle ('actor') EM-096 denetim defterine yazılır.</div>`;
    // Add-account form.
    const roleOpts = roles.map((r) => `<option value="${r}">${r}</option>`).join("");
    const countryOpts = `<option value="">global</option>` +
      countries.map((c) => `<option value="${c}">${escapeHtml(labels[c] || c)}</option>`).join("");
    const defaultActor = (authSession && authSession.user && authSession.user.email) || "";
    html += `<form id="um-add-form" class="um-subform">` +
      `<div class="um-meta"><b>Yeni hesap</b></div>` +
      `<input id="um-email" type="email" placeholder="e-posta" required>` +
      `<input id="um-password" type="password" placeholder="parola" autocomplete="new-password" required>` +
      `<input id="um-name" type="text" placeholder="görünen ad" required>` +
      `<div class="um-actions"><select id="um-role">${roleOpts}</select>` +
      `<select id="um-country">${countryOpts}</select>` +
      `<input id="um-actor" type="text" placeholder="işlem sahibi (actor)" value="${escapeHtml(defaultActor)}">` +
      `<button type="submit" class="btn">Ekle</button></div>` +
      `<div id="um-add-msg"></div></form>`;
    // Managed account list.
    html += `<div id="um-list" style="margin-top:8px">`;
    if (!users.length) {
      html += `<div class="empty">Yönetilen hesap yok.</div>`;
    }
    users.forEach((u) => {
      const inactiveCls = u.is_active ? "" : " um-inactive";
      const rowRole = roles.map((r) =>
        `<option value="${r}"${r === u.role ? " selected" : ""}>${r}</option>`).join("");
      const rowCountry = `<option value=""${u.country ? "" : " selected"}>global</option>` +
        countries.map((c) =>
          `<option value="${c}"${c === u.country ? " selected" : ""}>${escapeHtml(labels[c] || c)}</option>`).join("");
      html += `<div class="um-row${inactiveCls}" data-id="${u.id}">` +
        `<div class="um-name">${escapeHtml(String(u.display_name))} ` +
        `<span class="um-badge">${escapeHtml(String(u.role))}</span>` +
        `<span class="um-badge">${escapeHtml(u.country ? (labels[u.country] || u.country) : "global")}</span>` +
        `<span class="um-badge">${u.is_active ? "etkin" : "devre dışı"}</span></div>` +
        `<div class="um-meta">${escapeHtml(String(u.email))}</div>` +
        `<div class="um-actions">` +
        `<select class="um-f-role">${rowRole}</select>` +
        `<select class="um-f-country">${rowCountry}</select>` +
        `<button type="button" class="btn um-save">Kaydet</button>` +
        `<button type="button" class="btn um-toggle">${u.is_active ? "Devre dışı bırak" : "Etkinleştir"}</button>` +
        `</div><div class="um-row-msg"></div></div>`;
    });
    html += `</div>`;
    html += `<div class="um-meta" style="margin-top:6px">Kaynak: ${escapeHtml(String(userMgmtList ? userMgmtList.persistence : ""))}</div>`;
    box.innerHTML = html;
    const form = document.getElementById("um-add-form");
    if (form) form.addEventListener("submit", umAdd);
    box.querySelectorAll(".um-row").forEach((row) => {
      const id = row.getAttribute("data-id");
      const saveBtn = row.querySelector(".um-save");
      const toggleBtn = row.querySelector(".um-toggle");
      if (saveBtn) saveBtn.addEventListener("click", () => umEdit(id, row));
      if (toggleBtn) toggleBtn.addEventListener("click", () => {
        const active = toggleBtn.textContent.indexOf("Etkin") === 0;
        umSetActive(id, !active, row);
      });
    });
  }

  async function umAdd(ev) {
    ev.preventDefault();
    const msg = document.getElementById("um-add-msg");
    const body = {
      email: document.getElementById("um-email").value,
      password: document.getElementById("um-password").value,
      display_name: document.getElementById("um-name").value,
      role: document.getElementById("um-role").value,
      country: document.getElementById("um-country").value,
      actor: document.getElementById("um-actor").value || null,
    };
    try {
      const res = await fetch(UM_API, { method: "POST", headers: umHeaders(true), body: JSON.stringify(body) });
      const j = await res.json();
      if (!res.ok) { msg.innerHTML = `<div class="um-err">${escapeHtml(umError(j, res))}</div>`; return; }
      await loadUserMgmt();
    } catch (err) {
      msg.innerHTML = `<div class="um-err">İstek başarısız: ${escapeHtml(err.message)}</div>`;
    }
  }

  async function umEdit(id, row) {
    const msg = row.querySelector(".um-row-msg");
    const body = {
      role: row.querySelector(".um-f-role").value,
      country: row.querySelector(".um-f-country").value,
      actor: (document.getElementById("um-actor") || {}).value || null,
    };
    try {
      const res = await fetch(`${UM_API}/${id}`, { method: "PATCH", headers: umHeaders(true), body: JSON.stringify(body) });
      const j = await res.json();
      if (!res.ok) { msg.innerHTML = `<div class="um-err">${escapeHtml(umError(j, res))}</div>`; return; }
      await loadUserMgmt();
    } catch (err) {
      msg.innerHTML = `<div class="um-err">İstek başarısız: ${escapeHtml(err.message)}</div>`;
    }
  }

  async function umSetActive(id, nextActive, row) {
    const msg = row.querySelector(".um-row-msg");
    try {
      const res = await fetch(`${UM_API}/${id}/active`, {
        method: "POST",
        headers: umHeaders(true),
        body: JSON.stringify({ is_active: nextActive, actor: (document.getElementById("um-actor") || {}).value || null }),
      });
      const j = await res.json();
      if (!res.ok) { msg.innerHTML = `<div class="um-err">${escapeHtml(umError(j, res))}</div>`; return; }
      await loadUserMgmt();
    } catch (err) {
      msg.innerHTML = `<div class="um-err">İstek başarısız: ${escapeHtml(err.message)}</div>`;
    }
  }

  // EM-054: kabul/ret geri bildirim döngüsü raporunu ac/kapa.
  function toggleFeedback() {
    const box = document.getElementById("positioning-feedback");
    if (!box) return;
    if (!box.hidden) { box.hidden = true; return; }
    box.hidden = false;
    loadFeedback();
  }

  // EM-054: panel aciksa karar sonrasi raporu tazele.
  function refreshFeedback() {
    const box = document.getElementById("positioning-feedback");
    if (box && !box.hidden) loadFeedback();
  }

  function _fbPct(v) {
    return v == null ? "—" : (Math.round(v * 100) + "%");
  }

  async function loadFeedback() {
    const box = document.getElementById("positioning-feedback");
    if (!box) return;
    box.innerHTML = '<div class="empty">Yukleniyor…</div>';
    const qs = exposureEventKey
      ? "?event_key=" + encodeURIComponent(exposureEventKey) : "";
    try {
      const res = await fetch("/api/v1/recommendations/feedback" + qs);
      const j = await res.json();
      if (!res.ok) {
        box.innerHTML = '<div class="empty">'
          + escapeHtml((j && j.detail && j.detail.error) || "Geri bildirim alinamadi.")
          + "</div>";
        return;
      }
      box.innerHTML = renderFeedback(j);
    } catch (err) {
      box.innerHTML = '<div class="empty">Geri bildirim alinamadi.</div>';
    }
  }

  function renderFeedback(j) {
    const t = j.totals || {}, r = j.rates || {};
    let html = '<div class="as-h">Kabul/ret analizi · kapsam: '
      + escapeHtml(j.scope || "tumu") + ' · karar: <b>' + escapeHtml(t.decisions || 0) + '</b></div>';
    html += '<div class="fb-rates">'
      + '<span>Kabul: <b>' + _fbPct(r.accept_rate) + '</b> (' + escapeHtml(t.accept || 0) + ')</span>'
      + '<span>Ret: <b>' + _fbPct(r.reject_rate) + '</b> (' + escapeHtml(t.reject || 0) + ')</span>'
      + '<span>Düzenle: <b>' + _fbPct(r.edit_rate) + '</b> (' + escapeHtml(t.edit || 0) + ')</span>'
      + '</div>';
    const rej = j.most_rejected_types || [];
    if (rej.length) {
      html += '<div class="rj-h">En çok reddilen tipler</div>';
      for (const row of rej) {
        html += '<div class="rj-item">' + escapeHtml(row.resource_type)
          + ' · ret ' + escapeHtml(row.reject) + ' (' + _fbPct(row.reject_rate) + ')</div>';
      }
    }
    const reasons = j.rejection_reasons || [];
    if (reasons.length) {
      html += '<div class="rj-h">Sık ret gerekçeleri</div>';
      for (const x of reasons) {
        html += '<div class="rj-item">' + escapeHtml(x.reason) + ' (' + escapeHtml(x.count) + ')</div>';
      }
    }
    const ideas = j.improvement_ideas || [];
    if (ideas.length) {
      html += '<div class="rj-h">İyileştirme fikirleri (backlog)</div>';
      for (const idea of ideas) html += '<div class="fb-idea">' + escapeHtml(idea) + '</div>';
    }
    return html;
  }

  // EM-063: gorunum standardizasyonu panelini (saat dilimi + koordinat formati) ac/kapa.
  var _locCfg = null;
  function toggleLocalization() {
    const box = document.getElementById("display-loc");
    if (!box) return;
    if (!box.hidden) { box.hidden = true; return; }
    box.hidden = false;
    loadLocalization();
  }

  async function loadLocalization() {
    const box = document.getElementById("display-loc");
    if (!box) return;
    if (!_locCfg) {
      box.innerHTML = '<div class="empty">Yukleniyor…</div>';
      try {
        const res = await fetch("/api/v1/display/config");
        _locCfg = await res.json();
      } catch (err) {
        box.innerHTML = '<div class="empty">Yapilandirma alinamadi.</div>';
        return;
      }
    }
    renderLocalization();
  }

  function renderLocalization() {
    const box = document.getElementById("display-loc");
    if (!box || !_locCfg) return;
    const u = _locCfg.units || {};
    const defTz = window._locTz || (_locCfg.defaults && _locCfg.defaults.timezone) || "Europe/Istanbul";
    const defCf = window._locCf || (_locCfg.defaults && _locCfg.defaults.coordinate_format) || "decimal";
    let tzOpts = "";
    for (const z of (_locCfg.supported_timezones || [])) {
      tzOpts += '<option value="' + escapeHtml(z) + '"' + (z === defTz ? " selected" : "") + '>' + escapeHtml(z) + '</option>';
    }
    let cfOpts = "";
    for (const f of (_locCfg.coordinate_formats || [])) {
      cfOpts += '<option value="' + escapeHtml(f) + '"' + (f === defCf ? " selected" : "") + '>' + escapeHtml(f) + '</option>';
    }
    box.innerHTML =
      '<div class="as-h">Saat dilimi · birim · koordinat (EM-063)</div>'
      + '<div class="loc-row"><label>Saat dilimi <select id="loc-tz" onchange="applyLocalization()">' + tzOpts + '</select></label>'
      + '<label>Koordinat <select id="loc-cf" onchange="applyLocalization()">' + cfOpts + '</select></label></div>'
      + '<div class="loc-row"><span>Birimler: <b>' + escapeHtml(u.system || "metric") + '</b> — mesafe '
      + escapeHtml(u.distance || "km") + ', alan ' + escapeHtml(u.area || "ha") + ', hiz ' + escapeHtml(u.speed || "km/h") + '</span></div>'
      + '<div id="loc-out" class="loc-out"></div>';
    applyLocalization();
  }

  async function applyLocalization() {
    const out = document.getElementById("loc-out");
    if (!out) return;
    const tzEl = document.getElementById("loc-tz");
    const cfEl = document.getElementById("loc-cf");
    if (tzEl) window._locTz = tzEl.value;
    if (cfEl) window._locCf = cfEl.value;
    const center = map.getCenter();
    const payload = {
      time: new Date().toISOString(),
      timezone: window._locTz,
      coordinate_format: window._locCf,
      latitude: center.lat,
      longitude: center.lng,
    };
    try {
      const res = await fetch("/api/v1/display/standardize", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const j = await res.json();
      if (!res.ok) {
        out.innerHTML = '<div class="empty">'
          + escapeHtml((j && j.detail && j.detail.error) || "Hata") + '</div>';
        return;
      }
      const tm = j.time || {};
      const co = j.coordinate || {};
      out.innerHTML =
        '<div class="loc-item">Yerel saat: <b>' + escapeHtml(tm.local_display || "—") + '</b>'
        + ' (' + escapeHtml(tm.timezone || "") + ')</div>'
        + '<div class="loc-item">Merkez koordinat: <b>' + escapeHtml(co.display || "—") + '</b>'
        + ' [' + escapeHtml(co.format || "") + ']</div>';
    } catch (err) {
      out.innerHTML = '<div class="empty">Standartlastirma hatasi.</div>';
    }
  }

  // EM-046: bir oneri satiri icin "neden?" panelini ac/kapa (gerekce + reddedilenler).
  async function explainProposal(p, box) {
    if (!box) return;
    if (!box.hidden) { box.hidden = true; return; }  // tekrar tiklama kapatir
    const ev = p.event_key || exposureEventKey || "";
    if (!ev) { box.textContent = "Gerekce icin bir olay secili olmali."; box.hidden = false; return; }
    box.innerHTML = "gerekceler yukleniyor…";
    box.hidden = false;
    try {
      const res = await fetch(`/api/v1/recommendations/explain?event_key=${encodeURIComponent(ev)}`);
      const j = await res.json();
      if (!res.ok) { box.textContent = "Gerekce alinamadi: " + (j.detail && j.detail.error ? j.detail.error : res.status); return; }
      const rec = (j.proposals || []).find(x => x.proposal_id === p.proposal_id);
      const ctx = j.context || {};
      let html = "";
      if (rec) {
        html += `<div class="why-h">Neden onerildi (sira ${escapeHtml(rec.rank)})</div>`;
        html += `<ul>` + (rec.why || []).map(w => `<li>${escapeHtml(w)}</li>`).join("") + `</ul>`;
      }
      const thr = ctx.threshold_eta_minutes != null ? ("T+" + escapeHtml(ctx.threshold_eta_minutes) + " dk") : "—";
      html += `<div class="why-c">${escapeHtml(ctx.ranking_metric || "")} · ${escapeHtml(ctx.alternatives_evaluated || 0)} alternatif degerlendirildi · esik ${thr}</div>`;
      const rej = j.rejected_alternatives || [];
      if (rej.length) {
        html += `<div class="why-h">Degerlendirilen reddedilen alternatifler</div><ul>`
          + rej.map(r => `<li><b>${escapeHtml(r.name || r.resource_key)}</b>: ${escapeHtml(r.reason)}</li>`).join("")
          + `</ul>`;
      } else {
        html += `<div class="why-c">Reddedilen alternatif yok; tum adaylar onerilenlerde.</div>`;
      }
      box.innerHTML = html;
    } catch (err) {
      box.textContent = "Gerekce hatasi: " + err;
    }
  }

  function renderHorizons() {
    if (!forecastAll || !forecastAll.features) return;
    const selected = HORIZONS[sliderIndex];
    const cumulative = document.getElementById("horizon-cumulative").checked;
    Object.values(forecastByHorizon).forEach(g => map.removeLayer(g));
    forecastByHorizon = {};
    for (const h of HORIZONS) {
      if (cumulative ? h <= selected : h !== selected) continue;
      const group = L.geoJSON(
        { ...forecastAll,
          features: forecastAll.features.filter(
            f => f.properties && f.properties.horizon_minutes === h)},
        { style: f => styleFor("forecasts", f, true),
          onEachFeature: (f, layer) => layer.bindPopup(popupHtml(f)) }
      );
      group.addTo(map);
      forecastByHorizon[h] = group;
    }
    // EM-020: güven bandı yalnızca seçili ufkun iyimser/kötümser zarflarıyla.
    if (uncertaintyAll && layers.uncertainty && map.hasLayer(layers.uncertainty)) {
      layers.uncertainty.clearLayers();
      layers.uncertainty.addData({ ...uncertaintyAll,
        features: uncertaintyAll.features.filter(
          f => f.properties && f.properties.horizon_minutes === selected)});
    }
    renderWhatifScenario();  // EM-055: senaryo poligonları seçili ufkla üst üste
    renderTicks();
  }

  function renderTicks() {
    const box = document.getElementById("horizon-ticks");
    box.innerHTML = "";
    HORIZONS.forEach((h, i) => {
      // Buttons (not spans): keyboard-focusable and operable, with pressed
      // state exposed to assistive technology.
      const el = document.createElement("button");
      el.type = "button";
      el.textContent = `${h} dk`;
      el.className = i === sliderIndex ? "active" : "";
      el.setAttribute("aria-pressed", i === sliderIndex ? "true" : "false");
      el.addEventListener("click", () => {
        sliderIndex = i;
        document.getElementById("horizon-slider").value = String(i);
        renderHorizons();
      });
      box.appendChild(el);
    });
  }

  // --- EM-055: what-if rüzgar senaryosu (kaydırıcı + canlı yeniden hesaplama) ---
  const WHATIF_SCENARIO_STYLE = () => ({
    color: "#1565c0", weight: 2, dashArray: "8 4",
    fillColor: "#1565c0", fillOpacity: 0.12, opacity: 0.95,
  });
  function setWhatifChip(cls, text) {
    const chip = document.getElementById("whatif-chip");
    if (!chip) return;
    chip.className = cls;
    chip.textContent = text;
  }
  function whatifIgnition() {
    if (exposureEventKey) {
      const ev = fireEvents.find(e => e.event_key === exposureEventKey);
      if (ev && ev.latitude != null && ev.longitude != null) {
        return { latitude: ev.latitude, longitude: ev.longitude,
          event_key: ev.event_key, label: ev.name || ev.event_key };
      }
    }
    if (mapClickPoint) {
      return { latitude: mapClickPoint.lat, longitude: mapClickPoint.lng,
        event_key: null, label: "harita tıklaması" };
    }
    return null;
  }
  function updateWhatifIgnitionHint() {
    const el = document.getElementById("whatif-ignition");
    const ign = whatifIgnition();
    if (!el) return;
    el.textContent = ign
      ? `İgnisyon: ${ign.label} (${ign.latitude.toFixed(3)}, ${ign.longitude.toFixed(3)})`
      : "İgnisyon noktası: bir olay seçin veya haritaya tıklayın.";
  }
  function scheduleWhatif() {
    if (!whatifEnabled) return;
    clearTimeout(whatifTimer);
    whatifTimer = setTimeout(runWhatif, 400);
  }
  async function runWhatif() {
    const ign = whatifIgnition();
    if (!ign) { setWhatifChip("", "What-If: nokta seçin"); return; }
    const dir = Number(document.getElementById("whatif-dir").value);
    const speedPct = Number(document.getElementById("whatif-speed").value);
    const tempDelta = Number(document.getElementById("whatif-temp").value);
    const humidDelta = Number(document.getElementById("whatif-humidity").value);
    document.getElementById("whatif-dir-val").textContent = `${dir > 0 ? "+" : ""}${dir}°`;
    document.getElementById("whatif-speed-val").textContent = `%${speedPct}`;
    document.getElementById("whatif-temp-val").textContent = `${tempDelta > 0 ? "+" : ""}${tempDelta}°C`;
    document.getElementById("whatif-humidity-val").textContent = `${humidDelta > 0 ? "+" : ""}${humidDelta}%`;
    if (whatifAbort) whatifAbort.abort();
    whatifAbort = new AbortController();
    setWhatifChip("slow", "What-If: hesaplanıyor…");
    const body = {
      latitude: ign.latitude, longitude: ign.longitude, event_key: ign.event_key,
      wind_rotation_delta_deg: dir, wind_speed_factor: speedPct / 100,
      temperature_delta_c: tempDelta, humidity_delta_pct: humidDelta,
    };
    try {
      const res = await fetch("/api/v1/whatif/wind", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body), signal: whatifAbort.signal,
      });
      if (!res.ok) {
        let msg = `HTTP ${res.status}`;
        try { const j = await res.json(); msg = (j.detail && j.detail.error) || msg; }
        catch (err) { /* biçimsiz hata gövdesi */ }
        setWhatifChip("", `What-If: hata — ${msg}`);
        return;
      }
      whatifResult = await res.json();
      renderHorizons();  // senaryo katmanını seçili ufkla yeniden çiz
      renderWhatifSummary();
      recordWhatifHistory(body, ign.event_key);  // EM-062: bu koşuyu geçmişe ekle
      const chipCls = whatifResult.within_target ? "on" : "slow";
      setWhatifChip(chipCls, `What-If: ${(whatifResult.compute_ms / 1000).toFixed(1)} sn`);
    } catch (err) {
      if (err && err.name === "AbortError") return;
      setWhatifChip("", `What-If: hata — ${err.message}`);
    }
  }
  function renderWhatifScenario() {
    if (whatifScenarioLayer) { map.removeLayer(whatifScenarioLayer); whatifScenarioLayer = null; }
    if (!whatifEnabled || !whatifResult || !whatifResult.scenario) return;
    const selected = HORIZONS[sliderIndex];
    const cumulative = document.getElementById("horizon-cumulative").checked;
    const feats = (whatifResult.scenario.forecasts || []).filter(f => {
      const h = f.horizon_minutes;
      return cumulative ? h <= selected : h === selected;
    }).map(f => ({
      type: "Feature",
      properties: { horizon_minutes: f.horizon_minutes, area_ha: f.area_ha,
        head_distance_m: f.head_distance_m, spread_direction_deg: f.spread_direction_deg },
      geometry: f.polygon_geojson,
    })).filter(f => f.geometry && f.geometry.coordinates && f.geometry.coordinates.length);
    whatifScenarioLayer = L.geoJSON({ type: "FeatureCollection", features: feats }, {
      style: WHATIF_SCENARIO_STYLE,
      onEachFeature: (f, layer) => layer.bindPopup(popupHtml(f)),
    }).addTo(map);
  }
  function gapCell(cls, text) { return `<span class="${cls}">${text}</span>`; }
  function renderWhatifSummary() {
    const box = document.getElementById("whatif-summary");
    const news = document.getElementById("whatif-newlist");
    if (!whatifResult) { box.innerHTML = ""; news.innerHTML = ""; return; }
    const o = whatifResult.original, s = whatifResult.scenario;
    const cap = whatifResult.capacity, rec = whatifResult.recommendations;
    const fmt = v => (v === null || v === undefined ? "—" : v);
    const scenGap = cap.scenario.gap_ha_h;
    const gapCls = scenGap <= 0 ? "ok" : "bad";
    const gapLabel = scenGap <= 0 ? "yeterli" : `${scenGap} ha/saat açık`;
    box.innerHTML =
      `<div class="metric"><span>Alan (${s.max_horizon_minutes} dk)</span><b>${fmt(o.area_ha)} → ${fmt(s.area_ha)} ha</b></div>`
      + `<div class="metric"><span>Talep</span><b>${fmt(o.demand_ha_h)} → ${fmt(s.demand_ha_h)} ha/saat</b></div>`
      + `<div class="metric"><span>Etkin kapasite</span><b>${fmt(cap.effective_ha_h)} ha/saat</b></div>`
      + `<div class="metric"><span>Kapasite açığı</span><b>${gapCell(gapCls, `${fmt(cap.original.gap_ha_h)} → ${gapLabel}`)}</b></div>`
      + `<div class="metric"><span>Tehdit altındaki yapı</span><b>${rec.original.count} → ${rec.scenario.count}</b></div>`
      + `<div class="metric"><span>En erken etki</span><b>T+${fmt(rec.original.earliest_impact_minutes)} → T+${fmt(rec.scenario.earliest_impact_minutes)} dk</b></div>`
      + `<div class="metric"><span>Rüzgar</span><b>${whatifResult.wind.original.from_deg}/${whatifResult.wind.original.speed_kmh} → ${whatifResult.wind.scenario.from_deg}/${whatifResult.wind.scenario.speed_kmh} km/s</b></div>`
      + `<div class="metric"><span>Sıcaklık / Nem</span><b>${whatifResult.weather.original.air_temp_c}°C / %${whatifResult.weather.original.relative_humidity_pct} → ${whatifResult.weather.scenario.air_temp_c}°C / %${whatifResult.weather.scenario.relative_humidity_pct}</b></div>`
      + `<div class="metric"><span>Hesap</span><b>${whatifResult.compute_ms} ms (hedef ≤${whatifResult.target_seconds} sn)</b></div>`;
    const added = (rec.delta && rec.delta.newly_threatened) || [];
    news.innerHTML = added.length
      ? `<b>Yeni tehdit (${added.length}):</b>` + added.map(a =>
        `<div class="item"><span class="tag">YENİ</span> ${escapeHtml(a.name || a.asset_key)} <i>T+${escapeHtml(a.first_impact_minutes)} dk</i></div>`
      ).join("")
      : "";
  }
  function openWhatif() {
    whatifEnabled = true;
    document.getElementById("whatif-panel").style.display = "block";
    setWhatifChip("", "What-If: hazır");
    updateWhatifIgnitionHint();
    refreshScenarioList();
    refreshHistoryList();
    runWhatif();
  }
  function closeWhatif() {
    whatifEnabled = false;
    whatifResult = null;
    clearTimeout(whatifTimer);
    if (whatifAbort) { whatifAbort.abort(); whatifAbort = null; }
    if (whatifScenarioLayer) { map.removeLayer(whatifScenarioLayer); whatifScenarioLayer = null; }
    document.getElementById("whatif-panel").style.display = "none";
    document.getElementById("whatif-summary").innerHTML = "";
    document.getElementById("whatif-newlist").innerHTML = "";
    setWhatifChip("", "What-If: kapalı");
  }

  // --- EM-059: kaydedilmiş/paylaşılmış what-if senaryoları -----------------
  function scenLink(msg, isErr) {
    const box = document.getElementById("whatif-scen-link");
    if (!box) return;
    box.className = isErr ? "err" : "";
    box.textContent = msg || "";
  }
  function currentWhatifScenarioParams() {
    // A wind scenario stores its ignition point + the four slider knobs so it
    // can be replayed through /whatif/wind exactly as the live run does.
    const ign = whatifIgnition();
    if (!ign) return null;
    return {
      params: {
        latitude: ign.latitude, longitude: ign.longitude,
        wind_rotation_delta_deg: Number(document.getElementById("whatif-dir").value),
        wind_speed_factor: Number(document.getElementById("whatif-speed").value) / 100,
        temperature_delta_c: Number(document.getElementById("whatif-temp").value),
        humidity_delta_pct: Number(document.getElementById("whatif-humidity").value),
      },
      event_key: ign.event_key,
    };
  }
  async function refreshScenarioList() {
    const sel = document.getElementById("whatif-scen-list");
    if (!sel) return;
    const prev = sel.value;
    try {
      const res = await fetch("/api/v1/whatif/scenarios?kind=wind&limit=50");
      if (!res.ok) return;
      const data = await res.json();
      sel.innerHTML = "";
      for (const s of (data.scenarios || [])) {
        const opt = document.createElement("option");
        opt.value = s.scenario_key;
        opt.textContent = s.shared ? `${s.name} \u2794` : s.name;
        sel.appendChild(opt);
      }
      if (prev) sel.value = prev;
    } catch (err) { /* listeme hatası sessiz — panel zaten çalışıyor */ }
  }
  async function saveScenario() {
    const nameEl = document.getElementById("whatif-scen-name");
    const name = (nameEl && nameEl.value || "").trim();
    if (!name) { scenLink("Senaryo adı gerekli", true); return; }
    const built = currentWhatifScenarioParams();
    if (!built) { scenLink("Önce bir olay seçin veya haritaya tıklayın", true); return; }
    try {
      const res = await fetch("/api/v1/whatif/scenarios", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, kind: "wind", params: built.params, event_key: built.event_key }),
      });
      const j = await res.json();
      if (!res.ok) { scenLink(`Kaydedilemedi: ${(j.detail && j.detail.error) || res.status}`, true); return; }
      if (nameEl) nameEl.value = "";
      scenLink(`Kaydedildi: ${j.scenario.name}`);
      await refreshScenarioList();
      const sel = document.getElementById("whatif-scen-list");
      if (sel) sel.value = j.scenario.scenario_key;
    } catch (err) { scenLink(`Kaydedilemedi: ${err.message}`, true); }
  }
  async function loadScenario() {
    const sel = document.getElementById("whatif-scen-list");
    const key = sel && sel.value;
    if (!key) { scenLink("Yüklenecek senaryo seçin", true); return; }
    try {
      const res = await fetch(`/api/v1/whatif/scenarios/${encodeURIComponent(key)}`);
      const j = await res.json();
      if (!res.ok) { scenLink(`Yüklenemedi: ${(j.detail && j.detail.error) || res.status}`, true); return; }
      const p = j.scenario.params || {};
      if (p.latitude == null || p.longitude == null) { scenLink("Senaryo ignisyon noktası eksik", true); return; }
      // Önce ignisyonu senaryo konumuna sabitle (harita tıklaması gibi).
      mapClickPoint = { lat: p.latitude, lng: p.longitude };
      exposureEventKey = j.scenario.event_key || exposureEventKey;
      if (document.getElementById("whatif-dir")) document.getElementById("whatif-dir").value = String(p.wind_rotation_delta_deg || 0);
      if (document.getElementById("whatif-speed")) document.getElementById("whatif-speed").value = String(Math.round((p.wind_speed_factor || 1) * 100));
      if (document.getElementById("whatif-temp")) document.getElementById("whatif-temp").value = String(p.temperature_delta_c || 0);
      if (document.getElementById("whatif-humidity")) document.getElementById("whatif-humidity").value = String(p.humidity_delta_pct || 0);
      scenLink(`Yüklendi: ${j.scenario.name}`);
      updateWhatifIgnitionHint();
      if (!whatifEnabled) { openWhatif(); } else { runWhatif(); }
    } catch (err) { scenLink(`Yüklenemedi: ${err.message}`, true); }
  }
  async function shareScenario() {
    const sel = document.getElementById("whatif-scen-list");
    const key = sel && sel.value;
    if (!key) { scenLink("Paylaşılacak senaryo seçin", true); return; }
    try {
      const res = await fetch(`/api/v1/whatif/scenarios/${encodeURIComponent(key)}/share`, { method: "POST" });
      const j = await res.json();
      if (!res.ok) { scenLink(`Paylaşılamadı: ${(j.detail && j.detail.error) || res.status}`, true); return; }
      const url = `${window.location.origin}${j.scenario.share_path}`;
      scenLink(url);
      if (navigator.clipboard) { try { await navigator.clipboard.writeText(url); } catch (e) { /* pano izni yok */ } }
      await refreshScenarioList();
    } catch (err) { scenLink(`Paylaşılamadı: ${err.message}`, true); }
  }

  // --- EM-062: yuvarlanan koşu geçmişi + tek tık geri alma -----------------
  function histLabel(p) {
    const dir = p.wind_rotation_delta_deg || 0;
    const spd = Math.round((p.wind_speed_factor || 1) * 100);
    const t = p.temperature_delta_c || 0;
    const h = p.humidity_delta_pct || 0;
    return `${dir > 0 ? "+" : ""}${dir}° · %${spd} · ${t > 0 ? "+" : ""}${t}°C · ${h > 0 ? "+" : ""}${h}%`;
  }
  async function recordWhatifHistory(params, eventKey) {
    const sig = JSON.stringify(params);
    if (sig === recordWhatifHistory._last) return;  // istemci tarafı debounce
    recordWhatifHistory._last = sig;
    try {
      await fetch("/api/v1/whatif/history", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          kind: "wind", event_key: eventKey || null,
          label: histLabel(params), params,
        }),
      });
      await refreshHistoryList();
    } catch (err) { /* geçmiş kaydı sessiz — ana işlev etkilenmez */ }
  }
  async function refreshHistoryList() {
    const sel = document.getElementById("whatif-hist-list");
    if (!sel) return;
    const prev = sel.value;
    try {
      const res = await fetch("/api/v1/whatif/history?kind=wind&limit=10");
      if (!res.ok) return;
      const data = await res.json();
      sel.innerHTML = "";
      for (const h of (data.history || [])) {
        const opt = document.createElement("option");
        opt.value = String(h.id);
        const when = (h.created_at || "").slice(11, 16);
        opt.textContent = `${when} · ${h.label || histLabel(h.params)}`;
        sel.appendChild(opt);
      }
      if (prev) sel.value = prev;
    } catch (err) { /* listeme hatası sessiz */ }
  }
  function applyWhatifParams(p, eventKey) {
    if (p.latitude == null || p.longitude == null) return false;
    mapClickPoint = { lat: p.latitude, lng: p.longitude };
    if (eventKey) exposureEventKey = eventKey;
    document.getElementById("whatif-dir").value = String(p.wind_rotation_delta_deg || 0);
    document.getElementById("whatif-speed").value = String(Math.round((p.wind_speed_factor || 1) * 100));
    document.getElementById("whatif-temp").value = String(p.temperature_delta_c || 0);
    document.getElementById("whatif-humidity").value = String(p.humidity_delta_pct || 0);
    updateWhatifIgnitionHint();
    return true;
  }
  async function revertHistory() {
    const sel = document.getElementById("whatif-hist-list");
    const id = sel && sel.value;
    if (!id) { scenLink("Gerı donelecek kosu secin", true); return; }
    try {
      const res = await fetch(`/api/v1/whatif/history/${encodeURIComponent(id)}`);
      const j = await res.json();
      if (!res.ok) { scenLink(`Geri alınamadı: ${(j.detail && j.detail.error) || res.status}`, true); return; }
      const p = j.entry.params || {};
      if (!applyWhatifParams(p, j.entry.event_key)) { scenLink("Koşu ignisyon noktası eksik", true); return; }
      scenLink(`Geri dönüldü: ${j.entry.label || histLabel(p)}`);
      if (!whatifEnabled) { openWhatif(); } else { runWhatif(); }
    } catch (err) { scenLink(`Geri alınamadı: ${err.message}`, true); }
  }
  async function clearHistory() {
    try {
      await fetch("/api/v1/whatif/history", { method: "DELETE" });
      recordWhatifHistory._last = null;
      scenLink("Geçmiş temizlendi");
      await refreshHistoryList();
    } catch (err) { scenLink(`Temizlenemedi: ${err.message}`, true); }
  }

  // --- EM-090: canlı güncelleme (WebSocket + REST yedeği) ------------------
  const LIVE_KIND_LABELS = { fire_event: "Olay", forecast: "Tahmin", alert: "UYARI" };
  function setLive(cls, text, title) {
    const chip = document.getElementById("live-chip");
    if (!chip) return;
    chip.className = cls;
    chip.textContent = text;
    if (title) chip.title = title;
  }
  function flashLive(updates) {
    const box = document.getElementById("live-flash");
    if (!box || !updates || !updates.length) return;
    const lines = updates.slice(-4).map(u => {
      const label = LIVE_KIND_LABELS[u.kind] || u.kind;
      const msg = u.message || u.title || "";
      // EM-057: "plan güncellendi, ne değişti?" özetini başlık + faktör etiketiyle göster.
      const pl = u.payload || {};
      if (pl.plan_update) {
        const chips = (pl.changed_labels || [])
          .map(c => `<b>${escapeHtml(c)}</b>`).join(" · ");
        const head = escapeHtml(u.title || "Plan güncellendi");
        const band = (pl.headline && pl.headline.peak_level)
          ? ` \u2192 ${escapeHtml(pl.headline.peak_level)}` : "";
        return `<div><b>\u00f6zet \u00b7 ${head}</b>${band}`
          + (chips ? ` <span>(${chips})</span>` : "")
          + `<div>${escapeHtml(msg)}</div></div>`;
      }
      return `<div><b>${escapeHtml(label)}</b>: ${escapeHtml(msg)}</div>`;
    });
    box.innerHTML = `<b>Canlı güncelleme</b>${lines.join("")}`;
    box.classList.add("show");
    clearTimeout(flashLive._t);
    flashLive._t = setTimeout(() => box.classList.remove("show"), 6000);
  }
