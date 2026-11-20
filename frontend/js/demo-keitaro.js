"use strict";
const $ = s => document.querySelector(s);
function esc(s) { return String(s ?? "").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;"); }
const campaignId = Number(new URLSearchParams(location.search).get("campaign"));
$("#backToEditor").href = campaignId ? `/index.html?campaign=${campaignId}` : "/";
let busy = false;
async function api(path, options) {
  const response = await fetch(path, {cache: "no-store", ...options});
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || `HTTP ${response.status}`);
  return data;
}
function refName(value) { return value && typeof value === "object" ? value.name || value.id || "—" : value || "—"; }
function streamHtml(stream) {
  const offers = stream.offers || [];
  const filters = Array.isArray(stream.filters) ? stream.filters : [];
  const filterText = filters.map(f => `${f.name} / ${f.mode}: ${Array.isArray(f.payload) ? f.payload.join(", ") : f.payload || "—"}`).join("; ");
  const redirect = typeof stream.action_payload === "string" ? stream.action_payload : "";
  return `<section class="card demo-stream"><div class="stream-head"><strong>${esc(stream.name)} <span class="muted">stream_id ${stream.id}</span></strong></div><div class="demo-stream-body">${filterText ? `<p>Фильтры: ${esc(filterText)}</p>` : ""}${redirect ? `<p>Редирект: ${esc(redirect)}</p>` : ""}${offers.length ? `<table class="demo-offers"><thead><tr><th>Offer</th><th>Share</th><th>Actions</th></tr></thead><tbody>${offers.map(o => `<tr><td>${esc(o.name || o.offer_id)} <span class="muted">[${o.offer_id}]</span></td><td>${o.share}%</td><td><button class="btn small" data-stream="${stream.id}" data-offer="${o.offer_id}">REMOVE IN KT</button></td></tr>`).join("")}</tbody></table>` : `<p class="muted">Офферов нет.</p>`}</div></section>`;
}
async function loadDemo() {
  $("#refreshDemo").disabled = true;
  try {
    if (!campaignId) throw new Error("Не указан ID кампании");
    const data = await api(`/api/demo/campaigns/${campaignId}`);
    const c = data.campaign;
    $("#demoCampaign").innerHTML = `<section class="demo-summary"><h2>${esc(c.name)} <span class="muted">[${c.id}]</span></h2><dl><dt>Домен</dt><dd>${esc(refName(c.domain))}</dd><dt>Группа</dt><dd>${esc(refName(c.group))}</dd><dt>Источник</dt><dd>${esc(refName(c.source))}</dd></dl></section><div class="streams">${data.streams.map(streamHtml).join("")}</div>`;
  } catch (e) { $("#demoCampaign").innerHTML = `<p class="error-text">${esc(e.message)}</p>`; }
  finally { $("#refreshDemo").disabled = false; }
}
$("#refreshDemo").addEventListener("click", loadDemo);
$("#demoCampaign").onclick = async ev => {
  const btn = ev.target.closest("button[data-offer]");
  if (!btn || busy) return;
  busy = true; btn.disabled = true;
  try {
    await api(`/api/demo/streams/${btn.dataset.stream}/offers/${btn.dataset.offer}`, {method: "DELETE"});
    await loadDemo();
  } catch (e) {
    const toast = $("#toast"); toast.textContent = e.message; toast.classList.remove("hidden"); toast.classList.add("error"); setTimeout(() => toast.classList.add("hidden"), 5000);
  } finally { busy = false; btn.disabled = false; }
};
loadDemo();
