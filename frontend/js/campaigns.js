"use strict";
const $ = s => document.querySelector(s);
function esc(s) { return String(s ?? "").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;"); }
let campaigns = [];
function renderCampaigns() {
  const q = $("#campaignSearch").value.trim().toLowerCase();
  const items = campaigns.filter(c => `${c.name} ${c.kt_campaign_id}`.toLowerCase().includes(q));
  $("#campaignList").innerHTML = items.length ? `<div class="table-wrap"><table class="campaign-list"><thead><tr><th>ID</th><th>Campaign</th><th>Actions</th></tr></thead><tbody>${items.map(c => `<tr><td>${c.kt_campaign_id}</td><td><a href="/index.html?campaign=${c.kt_campaign_id}">${esc(c.name)}</a>${c.dirty_count ? `<span class="draft-count">Есть изменения: ${c.dirty_count}</span>` : ""}</td><td><a class="btn small" href="/index.html?campaign=${c.kt_campaign_id}">OPEN EDITOR</a></td></tr>`).join("")}</tbody></table></div>` : `<p class="empty">${q ? "Кампании не найдены." : "Кампаний пока нет. Создайте первую."}</p>`;
}
$("#campaignSearch").addEventListener("input", renderCampaigns);
(async () => { try {
  const response = await fetch("/api/campaigns", {cache: "no-store"});
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  campaigns = await response.json();
  $("#demoNote").classList.toggle("hidden", !campaigns.some(c => c.demo_mode));
  renderCampaigns();
} catch (e) { $("#campaignList").innerHTML = `<p class="error-text">Не удалось загрузить кампании: ${esc(e.message)}. Обновите страницу.</p>`; } })();
