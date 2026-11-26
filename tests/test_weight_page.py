"""
The weight page runs its own script in the browser. These tests run that script in Node.js against a
stub page, so a script that stops early shows up here as an empty history.
"""

import json
import os
import re
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


needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="runs the page script with Node.js")


def table_dates(history_html: str) -> list:
    return re.findall(r"<td>(\d{4}-\d{2}-\d{2})</td>", history_html)


# ---------- order: newest first in the table, oldest first in the chart ----------

@needs_node
@pytest.mark.parametrize("arrival", ["oldest_first", "newest_first", "shuffled"])
def test_history_is_newest_first_whatever_order_the_entries_arrive_in(arrival):
    today = date.today()
    oldest = {"id": 1, "weight_kg": 66.2, "logged_date": (today - timedelta(days=20)).isoformat()}
    middle = {"id": 2, "weight_kg": 65.4, "logged_date": (today - timedelta(days=10)).isoformat()}
    newest = {"id": 3, "weight_kg": 64.8, "logged_date": (today - timedelta(days=2)).isoformat()}
    order = {
        "oldest_first": [oldest, middle, newest],
        "newest_first": [newest, middle, oldest],
        "shuffled": [middle, newest, oldest],
    }[arrival]

    page = run_weight_page(order)

    assert page["error"] is None, page["error"]
    assert table_dates(page["history"]) == [newest["logged_date"], middle["logged_date"], oldest["logged_date"]]
    assert page["chartLabels"] == [oldest["logged_date"], middle["logged_date"], newest["logged_date"]]
    assert "64.8 kg" in page["current"] and newest["logged_date"] in page["current"]


# ---------- saving: the checks the page makes before it posts ----------

# Fills in the form, presses Save and reports what the page showed and what it sent to the server.
NODE_SAVE_RUNNER = r"""
const fs = require('fs');
const vm = require('vm');

const html = fs.readFileSync(__PAGE__, 'utf8');
const settings = __SETTINGS__;
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];

const elements = {};
function element(id) {
  if (!elements[id]) elements[id] = { value: '', max: '', innerHTML: '', classList: { toggle() {} } };
  return elements[id];
}
const requests = [];
const sandbox = {
  document: { getElementById: element },
  fetch: async (url, options) => {
    if (!options || options.method !== 'POST') return { ok: true, json: async () => [] };
    requests.push(JSON.parse(options.body));
    if (settings.offline) throw new TypeError('Failed to fetch');
    if (settings.nonJson) return { ok: false, status: 500, json: async () => { throw new SyntaxError('Unexpected token <'); } };
    return { ok: settings.status < 400, status: settings.status, json: async () => settings.reply };
  },
  Chart: class { destroy() {} },
};
if (settings.now) {
  const RealDate = Date;
  sandbox.Date = class extends RealDate {
    constructor(...args) { if (args.length === 0) super(settings.now); else super(...args); }
  };
}
vm.createContext(sandbox);
vm.runInContext(script, sandbox);
const defaults = { date: element('dateInput').value, max: element('dateInput').max };

setTimeout(async () => {
  element('weightInput').value = settings.weight;
  if (settings.date !== null) element('dateInput').value = settings.date;
  await vm.runInContext('logWeight()', sandbox);
  setTimeout(() => {
    console.log(JSON.stringify({ defaults, box: element('logError').innerHTML, weightField: element('weightInput').value, requests }));
  }, 20);
}, 20);
"""


def press_save(weight, logged_date=None, status=201, reply=None, non_json=False, offline=False, now=None, tz=None) -> dict:
    """logged_date=None leaves the date the page filled in by itself."""
    settings = {
        "weight": weight, "date": logged_date, "status": status, "reply": reply or {},
        "nonJson": non_json, "offline": offline, "now": now,
    }
    code = NODE_SAVE_RUNNER.replace("__PAGE__", json.dumps(str(WEIGHT_PAGE))).replace("__SETTINGS__", json.dumps(settings))
    env = {**os.environ, "TZ": tz} if tz else None
    result = subprocess.run(["node", "-e", code], capture_output=True, text=True, timeout=60, env=env)
    if result.returncode != 0:
        raise RuntimeError(result.stderr)
    return json.loads(result.stdout)


@needs_node
@pytest.mark.parametrize("weight, logged_date, message", [
    pytest.param("", None, "Enter both a weight and a date.", id="no-weight"),
    pytest.param("70", "", "Enter both a weight and a date.", id="no-date"),
    pytest.param("abc", None, "Weight must be a number.", id="not-a-number"),
    pytest.param("19.9", None, "Weight must be between 20 and 500 kg.", id="too-light"),
    pytest.param("500.1", None, "Weight must be between 20 and 500 kg.", id="too-heavy"),
    pytest.param("70", "1899-12-31", "Date must be 1900-01-01 or later.", id="before-1900"),
    pytest.param("70", (date.today() + timedelta(days=3)).isoformat(), "Date cannot be in the future.", id="future-date"),
])
def test_page_refuses_a_bad_entry_without_sending_it(weight, logged_date, message):
    page = press_save(weight, logged_date)

    assert message in page["box"]
    assert page["requests"] == []


@needs_node
@pytest.mark.parametrize("weight", ["20", "70.5", "500"])
def test_page_sends_a_good_entry_and_clears_the_weight_box(weight):
    page = press_save(weight)

    assert page["requests"] == [{"weight_kg": weight, "logged_date": page["defaults"]["date"]}]
    assert page["box"] == ""
    assert page["weightField"] == ""


@needs_node
def test_message_from_the_server_is_shown_as_text_not_as_markup():
    page = press_save("70", status=400, reply={"error": "<img src=x onerror=alert(1)>"})

    assert "&lt;img" in page["box"]
    assert "<img" not in page["box"]
    assert page["weightField"] == "70"


@needs_node
def test_page_shows_a_message_when_the_server_answers_with_something_that_is_not_json():
    page = press_save("70", status=500, non_json=True)

    assert "Could not save this entry." in page["box"]


@needs_node
def test_page_shows_a_message_when_the_server_cannot_be_reached():
    page = press_save("70", offline=True)

    assert "Could not reach the server." in page["box"]


@needs_node
@pytest.mark.parametrize("now, tz, expected", [
    pytest.param("2026-11-27T01:30:00Z", "America/New_York", "2026-11-26", id="evening-in-new-york"),
    pytest.param("2026-11-26T23:30:00Z", "Africa/Lagos", "2026-11-27", id="just-after-midnight-in-lagos"),
])
def test_date_starts_as_the_local_day_and_can_be_saved_straight_away(now, tz, expected):
    page = press_save("70", now=now, tz=tz)

    assert page["defaults"] == {"date": expected, "max": expected}
    assert page["requests"] == [{"weight_kg": "70", "logged_date": expected}]
    assert page["box"] == ""
