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
  is_offer_stream: true, dirty: false, offers: [], filter_summary: 'None'
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
