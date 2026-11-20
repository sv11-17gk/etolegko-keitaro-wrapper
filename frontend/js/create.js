/* Создаватор кампаний: Name + Geo (список через запятую) + Offer (автокомплит).
   Домен/группа/источник — опциональные дропдауны, по умолчанию KT подставит первые активные. */
"use strict";

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
  try { data = await resp.json(); } catch { /* ок */ }
  if (!resp.ok) {
    const detail = data && data.detail ? data.detail : `HTTP ${resp.status}`;
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return data;
}

/* ---------- автокомплит оффера ---------- */
let pickedOffer = null;

function attachOfferAutocomplete() {
  const input = $("#offerInput");
  const box = $("#offerSuggest");
  let timer = null;
  const render = (items) => {
    if (!items.length) { box.classList.add("hidden"); return; }
    box.innerHTML = items.map(o =>
      `<div class="suggest-item" data-id="${o.offer_id}">${o.offer_id}
         <span class="muted">${esc(o.name)}</span></div>`).join("");
    box.classList.remove("hidden");
    [...box.children].forEach(item => {
      item.addEventListener("mousedown", (ev) => {
        ev.preventDefault();
        const id = Number(item.dataset.id);
        const o = items.find(x => x.offer_id === id);
        input.value = `${id} ${o.name}`;
        $("#offerIdInput").value = id;
        pickedOffer = o;
        box.classList.add("hidden");
      });
    });
  };
  const search = async () => {
    const q = input.value.trim();
    if (!q) { box.classList.add("hidden"); return; }
    try { render(await api(`/api/offers/search?q=${encodeURIComponent(q)}`)); }
    catch { box.classList.add("hidden"); }
  };
  input.addEventListener("input", () => {
    pickedOffer = null;
    $("#offerIdInput").value = "";
    clearTimeout(timer);
    timer = setTimeout(search, 250);
  });
  input.addEventListener("blur", () => setTimeout(() => box.classList.add("hidden"), 150));
}

/* ---------- справочники ---------- */
function fillSelect(select, items, emptyLabel) {
  select.innerHTML = `<option value="">${esc(emptyLabel)}</option>`;
  for (const it of items || []) {
    const opt = document.createElement("option");
    opt.value = it.id;
    opt.textContent = `${it.name} [${it.id}]`;
    select.appendChild(opt);
  }
}

async function loadReference() {
  const ref = await api("/api/reference");
  fillSelect($("#domainSelect"), ref.domains, "авто — первый активный");
  fillSelect($("#groupSelect"), ref.groups, "авто — первая группа");
  fillSelect($("#sourceSelect"), ref.sources, "авто — первый источник");
}

/* ---------- отправка ---------- */
$("#createForm").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const form = ev.target;
  const geos = form.geos.value.split(",").map(s => s.trim()).filter(Boolean);
  const offerId = Number($("#offerIdInput").value);
  if (!geos.length) { toast("Укажите хотя бы один гео-код", true); return; }
  if (!offerId) { toast("Выберите оффер из подсказок", true); return; }
  const body = {
    name: form.name.value.trim(),
    geos,
    offer_id: offerId,
    domain_id: Number($("#domainSelect").value) || null,
    group_id: Number($("#groupSelect").value) || null,
    source_id: Number($("#sourceSelect").value) || null,
  };
  try {
    const btn = form.querySelector("button[type=submit]");
    btn.disabled = true;
    const created = await api("/api/campaigns", { method: "POST", body });
    const result = $("#result");
    result.classList.remove("hidden");
    result.innerHTML = `
      <b>Кампания создана:</b> ${esc(created.name)} (id ${created.kt_campaign_id}, alias ${esc(created.alias)})<br>
      Домен: ${esc(created.domain)} · Группа: ${esc(created.group)} · Источник: ${esc(created.source)}<br>
      Гео: ${created.geos.map(esc).join(", ")} · Оффер: ${offerId}<br>
      <a href="/index.html?campaign=${created.kt_campaign_id}">Открыть в редакторе</a>`;
    form.reset();
    $("#offerIdInput").value = "";
    toast("Кампания создана в Keitaro");
  } catch (e) {
    toast(e.message, true);
  } finally {
    const btn = form.querySelector("button[type=submit]");
    if (btn) btn.disabled = false;
  }
});

attachOfferAutocomplete();
loadReference().catch(e => toast(e.message, true));
