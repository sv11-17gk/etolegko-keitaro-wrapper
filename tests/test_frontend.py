"""Повторная отрисовка карточки должна сохранять один обработчик клика."""
from pathlib import Path
import shutil
import subprocess

import pytest


def test_one_click_sends_one_mutation_after_rerenders():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Для проверки JavaScript нужен Node.js")
    source = Path(__file__).resolve().parents[1] / "frontend/js/app.js"
    script = r"""
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const requests = [];
const stream = {
  kt_stream_id: 42, name: 'Flow 2', position: 2,
  is_offer_stream: true, dirty: false, offers: [], filter_summary: null
};
function element() {
  return {
    dataset: {}, classList: {toggle() {}, remove() {}, add() {}},
    querySelector() { return null; },
    listeners: [],
    addEventListener(event, callback) {
      if (event === 'click') this.listeners.push(callback);
    },
    async clickAction(act, pinned) {
      const button = {dataset: {act, id: '7', pinned}, disabled: false};
      const event = {target: {closest() {return button;}}};
      const handlers = [...this.listeners];
      if (this.onclick) handlers.push(this.onclick);
      for (const handler of handlers) await handler(event);
    }
  };
}
const context = vm.createContext({
  document: {createElement: element, querySelector: element},
  setTimeout() {return 1;}, clearTimeout() {},
  fetch: async (url, options) => {
    requests.push({url, method: options.method});
    return {ok: true, json: async () => stream};
  }
});
const code = fs.readFileSync(process.argv[2], 'utf8');
vm.runInContext(code.split('/* ---------- старт ---------- */')[0], context);
context.stream = stream;
(async () => {
  await vm.runInContext(`(async () => {
    const card = buildStreamCard(stream);
    await card.clickAction('pin', '1');
    await card.clickAction('pin', '0');
    await card.clickAction('remove');
    await card.clickAction('cancel');
  })()`, context);
  assert.deepEqual(requests.map(r => r.method), ['POST', 'POST', 'DELETE', 'POST']);
  assert.equal(requests[3].url, '/api/streams/42/cancel');
})().catch(error => {console.error(error); process.exitCode = 1;});
"""
    result = subprocess.run([node, "-", str(source)], input=script, text=True,
                            capture_output=True, timeout=10)
    assert result.returncode == 0, result.stdout + result.stderr


def test_filter_headers_and_statistics_markup():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Для проверки JavaScript нужен Node.js")
    source = Path(__file__).resolve().parents[1] / "frontend/js/app.js"
    script = r"""
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const context = vm.createContext({});
const code = fs.readFileSync(process.argv[2], 'utf8');
vm.runInContext(code.split('/* ---------- старт ---------- */')[0], context);
vm.runInContext(`
  const fake = () => ({dataset: {}, querySelector() {return null;}});
  const flow = {kt_stream_id: 1, name: 'Flow 1', position: 1,
    is_offer_stream: false, offers: [], filter_summary: 'country accept [MX,AU]'};
  let card = fake(); renderStreamInto(card, flow);
  if (!card.innerHTML.includes('filter by country accept [MX,AU]')) throw Error('missing filter');
  card = fake(); renderStreamInto(card, {...flow, filter_summary: null});
  if (card.innerHTML.includes('filter by')) throw Error('null filter shown');
  const offer = {offer_id: 3749, binding_id: 1, name: 'Offer', share: 100, state: 'active'};
  const valid = offerRowHtml(offer, {clicks_today: 12, week: [6,9,7,11,10,14,12]});
  if (!valid.includes('>12</span>') || !valid.includes('<svg') || !valid.includes('6, 9, 7, 11, 10, 14, 12')) throw Error('missing stats');
  const missing = offerRowHtml(offer, null);
  const invalid = offerRowHtml(offer, {clicks_today: 'bad', week: [undefined, NaN, -5]});
  const removed = offerRowHtml({...offer, state:'removed'}, {clicks_today:12,week:[1,2,3,4,5,6,12]});
  if (removed.includes('<svg') || !removed.includes('stats-cell">—')) throw Error('archive stats shown');
  if (!missing.includes('stats-cell">—')) throw Error('unknown stats fabricated');
  for (const html of [valid, missing, invalid, removed]) {
    if (['NaN', 'undefined', '[object Object]'].some(value => html.includes(value))) throw Error('invalid markup: '+html);
  }
`, context);
"""
    result = subprocess.run([node, "-", str(source)], input=script, text=True,
                            capture_output=True, timeout=10)
    assert result.returncode == 0, result.stdout + result.stderr
