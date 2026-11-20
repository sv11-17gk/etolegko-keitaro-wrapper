/* Редактор кампаний: кампании -> потоки -> офферы (веса, пины, removed, push/cancel).
   Vanilla JS, без сборки. */
"use strict";

/* ---------- утилиты ---------- */
const $ = (sel, root) => (root || document).querySelector(sel);

function esc(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

let toastTimer = null;
function toast(msg, isError) {
  const el = $("#toast");
  el.textContent = msg;
  el.classList.toggle("error", Boolean(isError));
  el.classList.remove("hidden");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.add("hidden"), 4000);
}

async function api(path, opts = {}) {
  const resp = await fetch(path, {
    cache: "no-store",
    headers: opts.body ? { "Content-Type": "application/json" } : undefined,
    ...opts,
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  let data = null;
  try { data = await resp.json(); } catch { /* пустой ответ — ок */ }
  if (!resp.ok) {
    const detail = data && data.detail ? data.detail : `HTTP ${resp.status}`;
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return data;
}

/* ---------- состояние ---------- */
let campaigns = [];
let currentCampaignId = null;
let streamDtos = [];
const streamCards = new Map(); // kt_stream_id -> <section>
const offerStatistics = new Map(); // kt_stream_id -> Map(offer_id -> stats)

/* ---------- кампании ---------- */
async function loadCampaigns(preferredId) {
  campaigns = await api("/api/campaigns");
  const select = $("#campaignSelect");
  select.innerHTML = "";
  for (const c of campaigns) {
    const opt = document.createElement("option");
    opt.value = c.kt_campaign_id;
    const dirty = c.dirty_count ? ` — есть изменения (${c.dirty_count})` : "";
    opt.textContent = `${c.name} [${c.kt_campaign_id}]${dirty}`;
    select.appendChild(opt);
  }
  const wanted = preferredId ?? new URLSearchParams(location.search).get("campaign");
  currentCampaignId = Number(
    wanted && campaigns.some(c => c.kt_campaign_id === Number(wanted))
      ? wanted : (campaigns[0] ? campaigns[0].kt_campaign_id : 0),
  ) || null;
  if (currentCampaignId) select.value = String(currentCampaignId);
  updateViewInKt();
}

function updateViewInKt() {
  const c = campaigns.find(x => x.kt_campaign_id === currentCampaignId);
  $("#viewInKt").href = c && c.admin_url ? c.admin_url : "#";
  $("#viewInKt").classList.toggle("hidden", !c || !c.admin_url);
  $("#campaignName").textContent = c ? c.name : "Нет кампаний";
  $("#campaignName").href = c && c.admin_url ? c.admin_url : "/campaigns.html";
  $("#campaignName").target = "_blank";
  $("#campaignName").rel = "noopener";
  $("#demoNote").classList.toggle("hidden", !campaigns.some(x => x.demo_mode));
}

async function loadStreams() {
  const box = $("#streams");
  streamCards.clear();
  offerStatistics.clear();
  streamDtos = [];
  box.innerHTML = `<p class="empty">Загружаем потоки…</p>`;
  if (!currentCampaignId) {
    box.innerHTML = `<p class="empty">Кампаний в Keitaro пока нет — создайте первую.</p>`;
    return;
  }
  const streams = await api(`/api/campaigns/${currentCampaignId}/streams`);
  box.innerHTML = "";
  streamDtos = [...streams].sort((a, b) => Number(b.is_offer_stream) - Number(a.is_offer_stream) || a.position - b.position);
  for (const s of streamDtos) {
    const card = buildStreamCard(s);
    box.appendChild(card);
    if (s.is_offer_stream) loadOfferStatistics(s.kt_stream_id, card);
  }
  if (!streams.length) box.innerHTML = `<p class="empty">В этой кампании пока нет потоков.</p>`;
}

async function refetchCampaignsAndStreams() {
  await loadCampaigns(currentCampaignId);
  await loadStreams();
}

/* ---------- карточка потока ---------- */
function offerName(o) {
  const name = String(o.name || "");
  const id = String(o.offer_id);
  return name === id || name.startsWith(id + " ") || name.startsWith("[" + id + "]")
    ? esc(name) : `<span class="offer-id">${id}</span> ${esc(name)}`;
}

function statisticsHtml(o, stats) {
  if (o.state === "removed" || !stats) {
    return {stats: "—", trends: "—"};
  }
  const safeCount = value => Number.isFinite(Number(value)) ? Math.max(0, Math.trunc(Number(value))) : 0;
  const week = Array.from({length: 7}, (_, index) => safeCount((stats.week || [])[index]));
  const clicks = safeCount(stats.clicks_today);
  const low = Math.min(...week), high = Math.max(...week);
  const points = week.map((value, index) => {
    const x = 2 + index * 136 / 6;
    const y = high === low ? 14 : 26 - (value - low) * 24 / (high - low);
    return `${x.toFixed(2)},${y.toFixed(2)}`;
  }).join(" ");
  const label = `Клики за последние 7 дней: ${week.join(", ")}`;
  return {
    stats: `<span title="Клики оффера за сегодня">${clicks}</span>`,
    trends: `<svg class="sparkline" viewBox="0 0 140 28" role="img" aria-label="${label}"><title>${label}</title><polyline points="${points}" fill="none" stroke="currentColor" stroke-width="1.5"/></svg>`,
  };
}

async function loadOfferStatistics(sid, card) {
  try {
    const data = await api(`/api/streams/${sid}/stats`);
    if (streamCards.get(sid) !== card) return;
    const stats = new Map((data.offers || []).map(o => [o.offer_id, o]));
    offerStatistics.set(sid, stats);
    const current = streamDtos.find(s => s.kt_stream_id === sid);
    for (const offer of current ? current.offers : []) {
      const row = card.querySelector(`[data-binding="${offer.binding_id}"]`);
      if (!row) continue;
      const html = statisticsHtml(offer, stats.get(offer.offer_id) || {clicks_today: 0, week: []});
      $(".stats-cell", row).innerHTML = html.stats;
      $(".trends-cell", row).innerHTML = html.trends;
    }
  } catch (e) {
    if (streamCards.get(sid) !== card) return;
    // Ошибка отчёта не превращается в вымышленные нули и не блокирует редактирование.
    for (const cell of card.querySelectorAll(".stats-cell, .trends-cell")) {
      cell.textContent = "—";
      cell.title = `Статистика недоступна: ${e.message}`;
    }
  }
}

function offerRowHtml(o, stats) {
  const removed = o.state === "removed";
  const actionBtn = removed
    ? `<button class="btn small" data-act="bringback" data-id="${o.binding_id}">BRING BACK</button>`
    : `<button class="btn small danger" data-act="remove" data-id="${o.binding_id}">REMOVE</button>`;
  const pinBtn = removed
    ? ``
    : `<button class="btn small pin-btn${o.pinned ? " pinned" : ""}" data-act="pin" data-id="${o.binding_id}"
         title="${o.pinned ? "Открепить вес" : "Закрепить вес"}" aria-pressed="${Boolean(o.pinned)}" data-pinned="${o.pinned ? "0" : "1"}">${o.pinned ? "UNPIN" : "PIN"}</button>`;
  const statistics = statisticsHtml(o, stats);
  return `<tr class="${removed ? "removed" : ""}" data-binding="${o.binding_id}">
    <td class="name-cell">${offerName(o)}
      ${removed ? `<span class="removed-tag">(removed)</span>` : ""}
      <a class="offer-preview" href="${esc(o.preview_url || `/api/offers/${o.offer_id}/preview`)}" target="_blank" rel="noopener">(preview)</a></td>
    <td class="share"><div class="share-control"><span>${o.share}%</span>${pinBtn}</div></td>
    <td class="stats-cell">${statistics.stats}</td><td class="trends-cell">${statistics.trends}</td>
    <td class="offer-actions">${actionBtn}</td>
  </tr>`;
}

function streamBodyHtml(s) {
  if (!s.is_offer_stream) {
    return "";
  }
  const rows = [...s.offers]
    .sort((a, b) => Number(a.state === "removed") - Number(b.state === "removed") || b.share - a.share)
    .map(o => {
      const report = offerStatistics.get(s.kt_stream_id);
      return offerRowHtml(o, report ? report.get(o.offer_id) || {clicks_today: 0, week: []} : null);
    }).join("");
  return `
    ${s.warning ? `<div class="stream-warning">${esc(s.warning)}</div>` : ""}
    <table class="offers" aria-label="Офферы потока ${esc(s.name)}">
      <colgroup><col class="col-offer"><col class="col-share"><col class="col-stats"><col class="col-trends"><col class="col-actions"></colgroup>
      <thead class="sr-only"><tr><th>Offer</th><th>Share</th><th>Stats</th><th>Trends</th><th>Actions</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>
    <div class="add-row">
      <input class="input add-input" aria-label="Добавить оффер: ID или название" placeholder="Offer ID или название" autocomplete="off">
      <button class="btn small primary" data-act="add">ADD</button>
      <div class="suggest hidden"></div>
    </div>`;
}

function buildStreamCard(s) {
  const card = document.createElement("section");
  card.className = "card stream" + (s.dirty ? " dirty" : "");
  card.dataset.streamId = s.kt_stream_id;
  renderStreamInto(card, s);
  streamCards.set(s.kt_stream_id, card);
  return card;
}

function renderStreamInto(card, s) {
  card.className = "card stream" + (s.dirty ? " dirty" : "");
  card.dataset.streamId = s.kt_stream_id;
  const clicks = s.clicks_today == null ? "" : `, clicks today: ${s.clicks_today}`;
  const filter = typeof s.filter_summary === "string" && s.filter_summary.trim()
    ? `filter by ${esc(s.filter_summary)}, ` : "";
  const details = `${filter}stream_id ${s.kt_stream_id}${clicks}`;
  const draftActions = s.dirty && s.is_offer_stream ? `
    <div class="draft-actions">
      <button class="btn small primary" data-act="push">PUSH TO KT</button>
      <button class="btn small" data-act="cancel">CANCEL</button>
    </div>` : "";
  card.innerHTML = `
    <div class="stream-head">
      <div class="stream-title">Stream: ${esc(s.name)} (#${s.position})
        <span class="muted">${details}</span>
      </div>
    </div>
    ${draftActions}
    ${streamBodyHtml(s)}`;
  bindStreamEvents(card, s);
}

function replaceCard(streamDto) {
  const previous = streamDtos.find(s => s.kt_stream_id === streamDto.kt_stream_id);
  if (streamDto.clicks_today == null && previous && previous.clicks_today != null) {
    streamDto = {...streamDto, clicks_today: previous.clicks_today};
  }
  streamDtos = streamDtos.map(s => s.kt_stream_id === streamDto.kt_stream_id ? streamDto : s);
  const card = streamCards.get(streamDto.kt_stream_id);
  if (card) {
    renderStreamInto(card, streamDto);
    const report = offerStatistics.get(streamDto.kt_stream_id);
    if (report && streamDto.offers.some(o => o.state !== "removed" && !report.has(o.offer_id))) {
      loadOfferStatistics(streamDto.kt_stream_id, card);
    }
  }
}

/* ---------- обработчики потока ---------- */
function bindStreamEvents(card, s) {
  const sid = s.kt_stream_id;

  card.onclick = async (ev) => {
    const btn = ev.target.closest("button");
    if (!btn) return;
    const act = btn.dataset.act;
    try {
      btn.disabled = true;
      if (act === "push") {
        replaceCard(await api(`/api/streams/${sid}/push`, { method: "POST" }));
        toast("Изменения запушены в Keitaro");
      } else if (act === "cancel") {
        replaceCard(await api(`/api/streams/${sid}/cancel`, { method: "POST" }));
        toast("Изменения отменены");
      } else if (act === "remove") {
        replaceCard(await api(`/api/bindings/${btn.dataset.id}`, { method: "DELETE" }));
        toast("Оффер удалён из потока (не пушено)");
      } else if (act === "bringback") {
        replaceCard(await api(`/api/bindings/${btn.dataset.id}/bring-back`, { method: "POST" }));
        toast("Оффер возвращён (не пушено)");
      } else if (act === "pin") {
        const pinned = btn.dataset.pinned === "1";
        replaceCard(await api(`/api/bindings/${btn.dataset.id}/pin`,
          { method: "POST", body: { pinned } }));
        toast(pinned ? "Вес закреплён" : "Вес откреплён");
      } else if (act === "showall") {
        openModal(sid);
      } else if (act === "add") {
        const input = $(".add-input", card);
        const picked = pickedOffers.get(input);
        if (!picked) { toast("Сначала выберите оффер из подсказок", true); return; }
        replaceCard(await api(`/api/streams/${sid}/offers`,
          { method: "POST", body: { offer_id: picked.offer_id } }));
        input.value = "";
        pickedOffers.delete(input);
        toast(`Оффер ${picked.offer_id} добавлен (не пушено)`);
      }
    } catch (e) {
      toast(e.message, true);
    } finally {
      btn.disabled = false;
    }
  };

  const input = $(".add-input", card);
  if (input) attachOfferAutocomplete(input, $(".suggest", card));
}

/* ---------- автокомплит офферов ---------- */
const pickedOffers = new WeakMap(); // input -> {offer_id, name}

function attachOfferAutocomplete(input, suggestBox, onPicked) {
  let timer = null;
  const render = (items) => {
    if (!items.length) { suggestBox.classList.add("hidden"); return; }
    suggestBox.innerHTML = items.map(o =>
      `<div class="suggest-item" data-id="${o.offer_id}">${offerName(o)}</div>`).join("");
    suggestBox.classList.remove("hidden");
    [...suggestBox.children].forEach(item => {
      item.addEventListener("mousedown", (ev) => {
        ev.preventDefault();
        const id = Number(item.dataset.id);
        const o = items.find(x => x.offer_id === id);
        input.value = (o.name === String(id) || String(o.name || "").startsWith(id + " ") || String(o.name || "").startsWith("[" + id + "]")) ? o.name : `${id} ${o.name}`;
        pickedOffers.set(input, o);
        if (onPicked) onPicked(o);
        suggestBox.classList.add("hidden");
      });
    });
  };
  const search = async () => {
    const q = input.value.trim();
    if (q.length < 1) { suggestBox.classList.add("hidden"); return; }
    try { render(await api(`/api/offers/search?q=${encodeURIComponent(q)}`)); }
    catch (e) { suggestBox.classList.add("hidden"); }
  };
  input.addEventListener("input", () => {
    pickedOffers.delete(input);
    clearTimeout(timer);
    timer = setTimeout(search, 250);
  });
  input.addEventListener("blur", () => setTimeout(() => suggestBox.classList.add("hidden"), 150));
}

/* ---------- глобальный каталог офферов ---------- */
let modalStreamId = null;
let modalOffset = 0;
let modalHasMore = false;
let modalRequest = 0;
let catalogAdding = false;
const modalLimit = 50;

function closeModal() {
  $("#modal").classList.add("hidden");
  $("#showAllBtn").focus();
}

function openModal() {
  const offerStreams = streamDtos.filter(s => s.is_offer_stream);
  const select = $("#modalStreamSelect");
  select.innerHTML = offerStreams.map(s => `<option value="${s.kt_stream_id}">${esc(s.name)} (#${s.position})</option>`).join("");
  if (offerStreams.some(s => s.kt_stream_id === modalStreamId)) select.value = String(modalStreamId);
  modalStreamId = Number(select.value) || null;
  $("#modalTarget").classList.toggle("hidden", !offerStreams.length);
  $("#modalReadonly").classList.toggle("hidden", Boolean(offerStreams.length));
  $("#modalSearch").value = "";
  modalOffset = 0;
  $("#modal").classList.remove("hidden");
  $("#modalSearch").focus();
  modalSearch();
}

async function modalSearch() {
  const request = ++modalRequest;
  const q = $("#modalSearch").value.trim();
  $("#modalList").innerHTML = `<p class="muted">Загружаем офферы…</p>`;
  $("#modalPrev").disabled = true;
  $("#modalNext").disabled = true;
  try {
    const data = await api(q ? `/api/offers/search?q=${encodeURIComponent(q)}` : `/api/offers?offset=${modalOffset}&limit=${modalLimit}`);
    if (request !== modalRequest) return;
    const items = q ? data : data.items;
    modalHasMore = !q && data.has_more;
    $("#modalPagination").classList.toggle("hidden", Boolean(q));
    $("#modalPrev").disabled = modalOffset === 0;
    $("#modalNext").disabled = !modalHasMore;
    $("#modalPage").textContent = items.length ? `${modalOffset + 1}–${modalOffset + items.length}` : "Нет офферов";
    $("#modalList").innerHTML = items.length ? items.map(o => `
      <div class="modal-row">
        <div class="name">${offerName(o)} <a href="/api/offers/${o.offer_id}/preview" target="_blank" rel="noopener">(preview)</a></div>
        ${modalStreamId ? `<button class="btn small primary" data-offer-id="${o.offer_id}">ADD</button>` : ""}
      </div>`).join("") : `<p class="muted">Ничего не найдено</p>`;
  } catch (e) {
    if (request !== modalRequest) return;
    $("#modalList").innerHTML = `<p class="error-text">${esc(e.message)}</p>`;
  }
}

/* ---------- старт ---------- */
$("#fetchBtn").addEventListener("click", async () => {
  if (!currentCampaignId) return;
  try {
    $("#fetchBtn").disabled = true;
    await api(`/api/campaigns/${currentCampaignId}/fetch`, { method: "POST" });
    await loadStreams();
    toast("Потоки синхронизированы с Keitaro");
  } catch (e) { toast(e.message, true); }
  finally { $("#fetchBtn").disabled = false; }
});

$("#campaignSelect").addEventListener("change", (ev) => {
  currentCampaignId = Number(ev.target.value) || null;
  updateViewInKt();
  history.replaceState(null, "", `?campaign=${currentCampaignId}`);
  loadStreams().catch(e => toast(e.message, true));
});

$("#showAllBtn").addEventListener("click", openModal);
$("#modalClose").addEventListener("click", closeModal);
$("#modal").addEventListener("click", (ev) => {
  if (ev.target.id === "modal") closeModal();
});
document.addEventListener("keydown", ev => {
  if (ev.key === "Escape" && !$("#modal").classList.contains("hidden")) closeModal();
});
$("#modalStreamSelect").addEventListener("change", ev => { modalStreamId = Number(ev.target.value) || null; });
$("#modalPrev").addEventListener("click", () => { if (modalOffset > 0) { modalOffset = Math.max(0, modalOffset - modalLimit); modalSearch(); } });
$("#modalNext").addEventListener("click", () => { if (modalHasMore) { modalOffset += modalLimit; modalSearch(); } });
$("#modalList").onclick = async ev => {
  const btn = ev.target.closest("button[data-offer-id]");
  if (!btn || !modalStreamId || catalogAdding) return;
  const streamId = modalStreamId;
  catalogAdding = true;
  btn.disabled = true;
  try {
    replaceCard(await api(`/api/streams/${streamId}/offers`, {method: "POST", body: {offer_id: Number(btn.dataset.offerId)}}));
    closeModal();
    toast(`Оффер ${btn.dataset.offerId} добавлен (не пушено)`);
  } catch (e) { toast(e.message, true); }
  finally { catalogAdding = false; btn.disabled = false; }
};
let modalTimer = null;
$("#modalSearch").addEventListener("input", () => {
  clearTimeout(modalTimer);
  modalOffset = 0;
  modalTimer = setTimeout(modalSearch, 250);
});

loadCampaigns().then(loadStreams).catch(e => {
  $("#streams").innerHTML = `<p class="empty error-text">Не удалось загрузить кампанию. Повторите FETCH STREAMS FROM KT или обновите страницу.</p>`;
  toast(e.message, true);
});
