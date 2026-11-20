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
const streamCards = new Map(); // kt_stream_id -> <section>

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
}

async function loadStreams() {
  const box = $("#streams");
  streamCards.clear();
  box.innerHTML = "";
  if (!currentCampaignId) {
    box.innerHTML = `<p class="empty">Кампаний в Keitaro пока нет — создайте первую.</p>`;
    return;
  }
  const streams = await api(`/api/campaigns/${currentCampaignId}/streams`);
  for (const s of streams) box.appendChild(buildStreamCard(s));
}

async function refetchCampaignsAndStreams() {
  await loadCampaigns(currentCampaignId);
  await loadStreams();
}

/* ---------- карточка потока ---------- */
function offerRowHtml(o) {
  const removed = o.state === "removed";
  const actionBtn = removed
    ? `<button class="btn small" data-act="bringback" data-id="${o.binding_id}">BRING BACK</button>`
    : `<button class="btn small danger" data-act="remove" data-id="${o.binding_id}">REMOVE</button>`;
  const pinBtn = removed
    ? ``
    : `<button class="btn small ghost" data-act="pin" data-id="${o.binding_id}"
         data-pinned="${o.pinned ? "0" : "1"}">${o.pinned ? "UNPIN" : "PIN"}</button>`;
  return `<tr class="${removed ? "removed" : ""}" data-binding="${o.binding_id}">
    <td>${o.offer_id}</td>
    <td class="name-cell">${esc(o.name)} ${removed ? `<span class="removed-tag">(removed)</span>` : ""}
      ${o.pinned && !removed ? `<span class="muted" title="Вес закреплён">— pinned</span>` : ""}</td>
    <td class="share">${o.share}%</td>
    <td>${pinBtn}</td>
    <td>${actionBtn}</td>
  </tr>`;
}

function streamBodyHtml(s) {
  if (!s.is_offer_stream) {
    return `<p class="muted">Поток без офферов (redirect/action) — содержимое не парсим,
      как в оригинальной обёртке.</p>`;
  }
  const rows = s.offers.map(offerRowHtml).join("");
  return `
    ${s.warning ? `<div class="stream-warning">${esc(s.warning)}</div>` : ""}
    <div class="table-wrap"><table class="offers">
      <thead><tr><th>ID</th><th>Offer</th><th>Share</th><th></th><th></th></tr></thead>
      <tbody>${rows}</tbody>
    </table></div>
    <div class="add-row">
      <input class="input add-input" placeholder="Offer ID или название — поиск по Keitaro" autocomplete="off">
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
  const headActions = `
    ${s.is_offer_stream ? `<button class="btn small" data-act="showall">SHOW ALL OFFERS</button>` : ""}
    ${s.dirty && s.is_offer_stream ? `
      <button class="btn small primary" data-act="push">PUSH TO KT</button>
      <button class="btn small" data-act="cancel">CANCEL</button>` : ""}`;
  card.innerHTML = `
    <div class="stream-head">
      <div class="stream-title">Stream: ${esc(s.name)} (#${s.position})
        <span class="muted">filter by ${esc(s.filter_summary)}, stream_id ${s.kt_stream_id}${clicks}</span>
      </div>
      <div class="stream-actions">${headActions}</div>
    </div>
    ${streamBodyHtml(s)}`;
  bindStreamEvents(card, s);
}

function replaceCard(streamDto) {
  const card = streamCards.get(streamDto.kt_stream_id);
  if (card) renderStreamInto(card, streamDto);
}

/* ---------- обработчики потока ---------- */
function bindStreamEvents(card, s) {
  const sid = s.kt_stream_id;

  card.addEventListener("click", async (ev) => {
    const btn = ev.target.closest("button");
    if (!btn) return;
    const act = btn.dataset.act;
    try {
      btn.disabled = true;
      if (act === "push") {
        replaceCard(await api(`/api/streams/${sid}/push`, { method: "POST" }));
        toast("Изменения запушены в Keitaro");
      } else if (act === "cancel") {
        if (confirm("Откатить непушенные изменения потока?")) {
          replaceCard(await api(`/api/streams/${sid}/cancel`, { method: "POST" }));
          toast("Изменения отменены");
        }
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
  });

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
      `<div class="suggest-item" data-id="${o.offer_id}">${o.offer_id}
         <span class="muted">${esc(o.name)}</span></div>`).join("");
    suggestBox.classList.remove("hidden");
    [...suggestBox.children].forEach(item => {
      item.addEventListener("mousedown", (ev) => {
        ev.preventDefault();
        const id = Number(item.dataset.id);
        const o = items.find(x => x.offer_id === id);
        input.value = `${id} ${o.name}`;
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

/* ---------- модалка «все офферы» ---------- */
let modalStreamId = null;

function openModal(streamId) {
  modalStreamId = streamId;
  $("#modalSearch").value = "";
  $("#modalList").innerHTML = `<p class="muted">Начните вводить ID или название оффера…</p>`;
  $("#modal").classList.remove("hidden");
  $("#modalSearch").focus();
}

async function modalSearch() {
  const q = $("#modalSearch").value.trim();
  if (!q) return;
  try {
    const items = await api(`/api/offers/search?q=${encodeURIComponent(q)}`);
    $("#modalList").innerHTML = items.length ? items.map(o => `
      <div class="modal-row">
        <div class="name">${o.offer_id} <span class="muted">${esc(o.name)}</span></div>
        <button class="btn small primary" data-offer-id="${o.offer_id}">ADD</button>
      </div>`).join("")
      : `<p class="muted">Ничего не найдено</p>`;
    [...$("#modalList").querySelectorAll("button")].forEach(btn => {
      btn.addEventListener("click", async () => {
        try {
          btn.disabled = true;
          replaceCard(await api(`/api/streams/${modalStreamId}/offers`,
            { method: "POST", body: { offer_id: Number(btn.dataset.offerId) } }));
          $("#modal").classList.add("hidden");
          toast(`Оффер ${btn.dataset.offerId} добавлен (не пушено)`);
        } catch (e) { toast(e.message, true); btn.disabled = false; }
      });
    });
  } catch (e) { toast(e.message, true); }
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

$("#modalClose").addEventListener("click", () => $("#modal").classList.add("hidden"));
$("#modal").addEventListener("click", (ev) => {
  if (ev.target.id === "modal") $("#modal").classList.add("hidden");
});
let modalTimer = null;
$("#modalSearch").addEventListener("input", () => {
  clearTimeout(modalTimer);
  modalTimer = setTimeout(modalSearch, 250);
});

loadCampaigns().then(loadStreams).catch(e => toast(e.message, true));
