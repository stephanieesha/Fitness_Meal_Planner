"""
The weight page runs its own script in the browser. These tests run that script in Node.js against a
stub page, so a script that stops early shows up here as an empty history.
"""

import json
import shutil
import subprocess
from datetime import date, timedelta
from pathlib import Path

import pytest

WEIGHT_PAGE = Path(__file__).parent.parent / "templates" / "weight.html"

# The page's <script> with a stub document, fetch and Chart. Prints what the page rendered as JSON.
NODE_RUNNER = r"""
const fs = require('fs');
const vm = require('vm');

const html = fs.readFileSync(__PAGE__, 'utf8');
const entries = __ENTRIES__;
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];

const elements = {};
function element(id) {
  if (!elements[id]) elements[id] = { value: '', innerHTML: '', classList: { toggle() {} } };
  return elements[id];
}
const charts = [];
class StubChart {
  constructor(canvas, config) { charts.push(config); }
  destroy() {}
}
const sandbox = {
  document: { getElementById: element },
  fetch: async () => ({ ok: true, json: async () => entries }),
  Chart: StubChart,
};
vm.createContext(sandbox);

let error = null;
try {
  vm.runInContext(script, sandbox);
} catch (e) {
  error = String(e && e.message ? e.message : e);
}
setTimeout(() => {
  console.log(JSON.stringify({
    error,
    current: element('currentWeightBox').innerHTML,
    history: element('historyTable').innerHTML,
    chartLabels: charts.length ? charts[charts.length - 1].data.labels : [],
  }));
}, 20);
"""


def run_weight_page(entries: list) -> dict:
    code = NODE_RUNNER.replace("__PAGE__", json.dumps(str(WEIGHT_PAGE))).replace("__ENTRIES__", json.dumps(entries))
    result = subprocess.run(["node", "-e", code], capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        raise RuntimeError(result.stderr)
    return json.loads(result.stdout)


@pytest.mark.skipif(shutil.which("node") is None, reason="runs the page script with Node.js")
def test_weight_history_shows_the_logged_entries():
    today = date.today()
    entries = [
        {"id": 1, "weight_kg": 65.5, "logged_date": (today - timedelta(days=10)).isoformat()},
        {"id": 2, "weight_kg": 64.8, "logged_date": (today - timedelta(days=2)).isoformat()},
    ]

    page = run_weight_page(entries)

    assert page["error"] is None, page["error"]
    assert "64.8 kg" in page["current"]
    assert "65.5 kg" in page["history"] and "64.8 kg" in page["history"]
    assert page["chartLabels"] == [entry["logged_date"] for entry in entries]
