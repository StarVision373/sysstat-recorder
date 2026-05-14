#!/usr/bin/env python3
"""
sysstat-recorder web dashboard — view system metrics in-browser.
"""

import os
import json
import sqlite3
import time
from datetime import datetime, date, timedelta, timezone

from flask import Flask, jsonify, render_template_string, request

DB_PATH = os.environ.get("SYSSTAT_DB",
    "/vol1/@apphome/trim.openclaw/data/workspace/sysstat-recorder/data/sysstat.db")
HOST = os.environ.get("SYSSTAT_HOST", "0.0.0.0")
PORT = int(os.environ.get("SYSSTAT_PORT", "8080"))

app = Flask(__name__)


def get_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def latest_row(conn):
    cur = conn.execute("SELECT * FROM snapshots ORDER BY ts DESC LIMIT 1")
    return cur.fetchone()


# ── API ──────────────────────────────────────────────────────────────────────

@app.route("/api/latest")
def api_latest():
    conn = get_db()
    row = latest_row(conn)
    if not row:
        return jsonify({"error": "no data yet"}), 404
    d = dict(row)
    if d.get("extra"):
        d["extra"] = json.loads(d["extra"])
    conn.close()
    return jsonify(d)


@app.route("/api/range")
def api_range():
    """Query by date or date range.
    ?from=YYYY-MM-DD&to=YYYY-MM-DD  —  both sides inclusive
    ?date=YYYY-MM-DD                —  single day"""
    conn = get_db()

    from_str = request.args.get("from", "").strip()
    to_str = request.args.get("to", "").strip()
    day_str = request.args.get("date", "").strip()

    tz = timezone(timedelta(hours=8))
    if day_str:
        d = datetime.strptime(day_str, "%Y-%m-%d")
        start = d.replace(tzinfo=tz).timestamp()
        end = (d + timedelta(days=1)).replace(tzinfo=tz).timestamp()
    elif from_str and to_str:
        start = datetime.strptime(from_str, "%Y-%m-%d").replace(tzinfo=tz).timestamp()
        end = (datetime.strptime(to_str, "%Y-%m-%d") + timedelta(days=1)).replace(tzinfo=tz).timestamp()
    else:
        # default: last 24h
        start = time.time() - 86400
        end = time.time() + 1

    cur = conn.execute(
        "SELECT * FROM snapshots WHERE ts >= ? AND ts < ? ORDER BY ts ASC",
        (start, end),
    )
    rows = cur.fetchall()

    data = []
    for r in rows:
        d = dict(r)
        if d.get("extra"):
            d["extra"] = json.loads(d["extra"])
        # human-readable time
        dt = datetime.fromtimestamp(d["ts"]).astimezone()
        d["time_label"] = dt.strftime("%H:%M")
        d["date_label"] = dt.strftime("%Y-%m-%d")
        data.append(d)

    conn.close()

    # compute summary for the range
    if data:
        cpus = [x["cpu_percent"] for x in data if x["cpu_percent"] is not None]
        mems = [x["mem_percent"] for x in data if x["mem_percent"] is not None]
        disks = [x["disk_percent"] for x in data if x["disk_percent"] is not None]
        # find min/max load
        loads = [x["load_1m"] for x in data if x["load_1m"] is not None]
        summary = {
            "samples": len(data),
            "cpu_avg": round(sum(cpus) / len(cpus), 1) if cpus else None,
            "cpu_max": round(max(cpus), 1) if cpus else None,
            "mem_avg": round(sum(mems) / len(mems), 1) if mems else None,
            "mem_max": round(max(mems), 1) if mems else None,
            "disk_avg": round(sum(disks) / len(disks), 1) if disks else None,
            "disk_max": round(max(disks), 1) if disks else None,
            "load_avg": round(sum(loads) / len(loads), 2) if loads else None,
            "load_max": round(max(loads), 2) if loads else None,
        }
    else:
        summary = {"samples": 0}

    return jsonify({"data": data, "summary": summary})


@app.route("/api/dates")
def api_dates():
    """Return all distinct dates that have data."""
    conn = get_db()
    rows = conn.execute(
        "SELECT DISTINCT strftime('%Y-%m-%d', ts_text) as day FROM snapshots ORDER BY day DESC"
    ).fetchall()
    conn.close()
    return jsonify([r["day"] for r in rows])


# ── Dashboard page ──────────────────────────────────────────────────────────

INDEX_HTML = r"""
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>sysstat-recorder</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
<style>
  * { box-sizing:border-box; margin:0; padding:0 }
  body { font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
         background:#0f172a; color:#e2e8f0; padding:20px }
  h1 { font-size:1.6rem; margin-bottom:4px }
  .sub { color:#94a3b8; font-size:0.85rem; margin-bottom:16px }
  .toolbar { display:flex; flex-wrap:wrap; gap:8px; align-items:center; margin-bottom:20px;
             background:#1e293b; border-radius:10px; padding:12px 16px }
  .toolbar label { font-size:0.85rem; color:#94a3b8 }
  .toolbar input[type=date] { background:#334155; border:1px solid #475569; color:#e2e8f0;
    border-radius:6px; padding:6px 10px; font-size:0.85rem; outline:none }
  .toolbar input[type=date]:focus { border-color:#38bdf8 }
  .toolbar button { background:#38bdf8; color:#0f172a; border:none; border-radius:6px;
    padding:6px 14px; font-size:0.85rem; font-weight:600; cursor:pointer }
  .toolbar button:hover { background:#7dd3fc }
  .toolbar button.sm { background:#334155; color:#e2e8f0; padding:4px 10px; font-size:0.75rem }
  .toolbar button.sm:hover { background:#475569 }
  .toolbar .sep { color:#475569; margin:0 2px }
  .summary { background:#1e293b; border-radius:10px; padding:12px 16px; margin-bottom:16px;
             display:flex; flex-wrap:wrap; gap:12px 24px; font-size:0.85rem }
  .summary span { color:#94a3b8 }
  .summary b { color:#e2e8f0 }
  .grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(300px,1fr)); gap:16px; margin-bottom:24px }
  .card { background:#1e293b; border-radius:10px; padding:16px }
  .card h2 { font-size:0.85rem; text-transform:uppercase; letter-spacing:.05em; color:#64748b; margin-bottom:8px }
  .val { font-size:1.8rem; font-weight:700 }
  .val small { font-size:0.75rem; font-weight:400; color:#94a3b8 }
  .chart-wrap { background:#1e293b; border-radius:10px; padding:16px; margin-bottom:16px }
  .chart-wrap h2 { font-size:0.9rem; color:#64748b; margin-bottom:4px }
  .chart-wrap .meta { font-size:0.75rem; color:#475569; margin-bottom:8px }
  canvas { width:100% !important; height:auto !important; max-height:220px }
  .badge { display:inline-block; padding:2px 10px; border-radius:999px; font-size:0.75rem; font-weight:600 }
  .badge-ok { background:#166534; color:#86efac }
  .badge-warn { background:#854d0e; color:#fde68a }
  .badge-err { background:#7f1d1d; color:#fca5a5 }
  .proc-table { width:100%; border-collapse:collapse; font-size:0.8rem }
  .proc-table th { text-align:left; color:#64748b; padding:4px 8px; border-bottom:1px solid #334155 }
  .proc-table td { padding:4px 8px; border-bottom:1px solid #1e293b }
</style>
</head>
<body>
<h1>&#x1f4ca; sysstat-recorder</h1>
<p class="sub" id="status">loading…</p>

<div class="toolbar">
  <label>查询日期：</label>
  <input type="date" id="date-from">
  <span class="sep">—</span>
  <input type="date" id="date-to">
  <button onclick="queryDate()">查询</button>
  <button class="sm" onclick="quickDate('today')">今天</button>
  <button class="sm" onclick="quickDate('yesterday')">昨天</button>
  <button class="sm" onclick="quickDate('week')">近7天</button>
</div>

<div class="summary" id="summary"></div>

<div class="grid" id="cards">
  <div class="card"><h2>CPU</h2><div class="val" id="cpu-val">—</div></div>
  <div class="card"><h2>Memory</h2><div class="val" id="mem-val">—</div></div>
  <div class="card"><h2>Disk</h2><div class="val" id="disk-val">—</div></div>
  <div class="card"><h2>Load</h2><div class="val" id="load-val">—</div></div>
  <div class="card"><h2>Network</h2><div class="val" id="net-val">—</div></div>
  <div class="card"><h2>Processes</h2><div class="val" id="proc-val">—</div></div>
</div>

<div class="chart-wrap"><h2>CPU %</h2><div class="meta" id="meta-cpu"></div><canvas id="chart-cpu"></canvas></div>
<div class="chart-wrap"><h2>Memory %</h2><div class="meta" id="meta-mem"></div><canvas id="chart-mem"></canvas></div>
<div class="chart-wrap"><h2>Disk %</h2><div class="meta" id="meta-disk"></div><canvas id="chart-disk"></canvas></div>
<div class="chart-wrap"><h2>Load (1m)</h2><div class="meta" id="meta-load"></div><canvas id="chart-load"></canvas></div>

<div class="chart-wrap"><h2>Top Processes (latest snapshot)</h2>
<table class="proc-table" id="proc-table"><tr><th>PID</th><th>Name</th><th>CPU%</th><th>MEM%</th></tr></table>
</div>

<div class="chart-wrap"><h2>Data Table</h2>
<div style="overflow-x:auto">
<table class="proc-table" id="data-table">
<thead><tr>
  <th>Time</th><th>CPU%</th><th>MEM%</th><th>Disk%</th><th>Load 1m</th><th>Procs</th>
</tr></thead>
<tbody></tbody>
</table>
</div>
</div>

<script>
const fmt = (n) => (n==null?'—':Number(n).toFixed(1));
const fmtBytes = (b) => {
  if (b==null) return '—';
  const u=['B','KB','MB','GB','TB']; let i=0; let v=b;
  while(v>=1024 && i<u.length-1){v/=1024;i++}
  return v.toFixed(1)+' '+u[i];
};

const chartOpts = (label,color,min,max) => ({
  type:'line', data:{ labels:[], datasets:[{ label, data:[], borderColor:color,
    backgroundColor:color+'33', fill:true, tension:0.3, pointRadius:1 }] },
  options:{ responsive:true, maintainAspectRatio:false,
    scales:{ x:{ grid:{ color:'#334155' }, ticks:{ maxTicksLimit:24, color:'#94a3b8', font:{size:10} } },
             y:{ min, max, grid:{ color:'#334155' }, ticks:{ color:'#94a3b8' } } },
    plugins:{ legend:{ display:false } } }
});

const charts={
  cpu: new Chart(document.getElementById('chart-cpu'),chartOpts('CPU%','#38bdf8',0,100)),
  mem: new Chart(document.getElementById('chart-mem'),chartOpts('MEM%','#a78bfa',0,100)),
  disk: new Chart(document.getElementById('chart-disk'),chartOpts('DISK%','#34d399',0,100)),
  load: new Chart(document.getElementById('chart-load'),chartOpts('Load','#fb923c',0,0)),
};

// init date pickers
const today = new Date().toISOString().slice(0,10);
document.getElementById('date-from').value = today;
document.getElementById('date-to').value = today;

function quickDate(opt) {
  if (opt==='today') {
    document.getElementById('date-from').value = today;
    document.getElementById('date-to').value = today;
  } else if (opt==='yesterday') {
    const yd = new Date(Date.now()-86400000).toISOString().slice(0,10);
    document.getElementById('date-from').value = yd;
    document.getElementById('date-to').value = yd;
  } else if (opt==='week') {
    const wk = new Date(Date.now()-6*86400000).toISOString().slice(0,10);
    document.getElementById('date-from').value = wk;
    document.getElementById('date-to').value = today;
  }
  queryDate();
}

function queryDate() {
  const from = document.getElementById('date-from').value;
  const to = document.getElementById('date-to').value;
  if (!from || !to) { fetchLive(); return; }

  fetch('/api/range?from='+from+'&to='+to).then(r=>r.json()).then(resp=>{
    const data = resp.data || [];
    const sum = resp.summary || {};
    const latest = data[data.length-1];
    renderCards(latest);
    renderCharts(data, sum);
    renderTable(data);
  }).catch(e=>{ document.getElementById('status').textContent='Error: '+e.message; });
}

function fetchLive() {
  fetch('/api/range').then(r=>r.json()).then(resp=>{
    const data = resp.data || [];
    const sum = resp.summary || {};
    const latest = data[data.length-1];
    renderCards(latest);
    renderCharts(data, sum);
    renderTable(data);
  }).catch(e=>{ document.getElementById('status').textContent='Error: '+e.message; });
}

function renderCards(latest) {
  const st = document.getElementById('status');
  const uptime = latest && latest.boot_ts ? Math.floor(Date.now()/1000 - latest.boot_ts) : 0;
  const uptimeStr = uptime>86400 ? Math.floor(uptime/86400)+'d '+Math.floor((uptime%86400)/3600)+'h' :
    uptime>3600 ? Math.floor(uptime/3600)+'h '+Math.floor((uptime%3600)/60)+'m' :
    uptime>60 ? Math.floor(uptime/60)+'m' : uptime+'s';
  st.textContent = 'Host: '+(latest?latest.hostname:'—')+' · Latest: '+(latest?latest.ts_text:'—')+' · Uptime: '+uptimeStr;

  if (!latest) {
    document.getElementById('cpu-val').innerHTML='—'; document.getElementById('mem-val').innerHTML='—';
    document.getElementById('disk-val').innerHTML='—'; document.getElementById('load-val').innerHTML='—';
    document.getElementById('net-val').innerHTML='—'; document.getElementById('proc-val').innerHTML='—';
    return;
  }
  const cpuBadge = latest.cpu_percent>80?'badge-err':latest.cpu_percent>60?'badge-warn':'badge-ok';
  document.getElementById('cpu-val').innerHTML='<span class="badge '+cpuBadge+'">'+fmt(latest.cpu_percent)+'%</span> <small>'+ (latest.cpu_count||'?')+' cores</small>';

  const memPct = latest.mem_percent||0;
  const memBadge = memPct>90?'badge-err':memPct>75?'badge-warn':'badge-ok';
  document.getElementById('mem-val').innerHTML='<span class="badge '+memBadge+'">'+fmt(memPct)+'%</span> <small>'+fmtBytes(latest.mem_used)+' / '+fmtBytes(latest.mem_total)+'</small>';

  const diskPct = latest.disk_percent||0;
  const diskBadge = diskPct>90?'badge-err':diskPct>80?'badge-warn':'badge-ok';
  document.getElementById('disk-val').innerHTML='<span class="badge '+diskBadge+'">'+fmt(diskPct)+'%</span> <small>'+fmtBytes(latest.disk_used)+' / '+fmtBytes(latest.disk_total)+'</small>';

  document.getElementById('load-val').innerHTML=fmt(latest.load_1m)+' / '+fmt(latest.load_5m)+' / '+fmt(latest.load_15m);
  document.getElementById('net-val').innerHTML='&#8595; '+fmtBytes(latest.net_recv)+'<br><small>&#8593; '+fmtBytes(latest.net_sent)+'</small>';
  document.getElementById('proc-val').innerHTML=(latest.procs||'—')+' procs';

  // top procs
  const extra = latest.extra||{};
  const top = extra.top_procs||[];
  const tbody = document.getElementById('proc-table');
  tbody.innerHTML = '<tr><th>PID</th><th>Name</th><th>CPU%</th><th>MEM%</th></tr>';
  top.forEach(p=>{
    const tr=tbody.insertRow();
    tr.insertCell().textContent=p.pid;
    tr.insertCell().textContent=p.name;
    tr.insertCell().textContent=fmt(p.cpu);
    tr.insertCell().textContent=fmt(p.mem);
  });
}

function renderCharts(data, sum) {
  const labels = data.map(d=>d.time_label+' '+d.date_label);
  charts.cpu.data.labels=labels; charts.cpu.data.datasets[0].data=data.map(d=>d.cpu_percent); charts.cpu.update();
  charts.mem.data.labels=labels; charts.mem.data.datasets[0].data=data.map(d=>d.mem_percent); charts.mem.update();
  charts.disk.data.labels=labels; charts.disk.data.datasets[0].data=data.map(d=>d.disk_percent); charts.disk.update();
  charts.load.data.labels=labels; charts.load.data.datasets[0].data=data.map(d=>d.load_1m); charts.load.update();

  const maxLoad = sum.load_max ? Math.ceil(sum.load_max*1.2) : 1;
  charts.load.options.scales.y.max = maxLoad;
  charts.load.update();

  document.getElementById('meta-cpu').textContent =
    'avg '+fmt(sum.cpu_avg)+'% | max '+fmt(sum.cpu_max)+'% | samples '+sum.samples;
  document.getElementById('meta-mem').textContent =
    'avg '+fmt(sum.mem_avg)+'% | max '+fmt(sum.mem_max)+'% | samples '+sum.samples;
  document.getElementById('meta-disk').textContent =
    'avg '+fmt(sum.disk_avg)+'% | max '+fmt(sum.disk_max)+'% | samples '+sum.samples;
  document.getElementById('meta-load').textContent =
    'avg '+fmt(sum.load_avg)+' | max '+fmt(sum.load_max)+' | samples '+sum.samples;

  // summary bar
  document.getElementById('summary').innerHTML =
    '<span>Samples: <b>'+sum.samples+'</b></span>'+
    '<span>CPU avg: <b>'+fmt(sum.cpu_avg)+'%</b> / max: <b>'+fmt(sum.cpu_max)+'%</b></span>'+
    '<span>MEM avg: <b>'+fmt(sum.mem_avg)+'%</b> / max: <b>'+fmt(sum.mem_max)+'%</b></span>'+
    '<span>Disk avg: <b>'+fmt(sum.disk_avg)+'%</b> / max: <b>'+fmt(sum.disk_max)+'%</b></span>'+
    '<span>Load avg: <b>'+fmt(sum.load_avg)+'</b> / max: <b>'+fmt(sum.load_max)+'</b></span>';
}

function renderTable(data) {
  const tbody = document.getElementById('data-table').querySelector('tbody');
  tbody.innerHTML = '';
  if (data.length > 500) {
    // downsample for table display: show every Nth row
    const step = Math.ceil(data.length / 200);
    for (let i=0; i<data.length; i+=step) {
      const d = data[i];
      appendRow(tbody, d);
    }
    tbody.insertRow().cells[0].textContent = '… (showing '+Math.ceil(data.length/step)+'/'+data.length+' rows)';
  } else {
    data.forEach(d=>appendRow(tbody, d));
  }
}

function appendRow(tbody, d) {
  const tr = tbody.insertRow();
  tr.insertCell().textContent = d.date_label + ' ' + d.time_label;
  tr.insertCell().textContent = fmt(d.cpu_percent);
  tr.insertCell().textContent = fmt(d.mem_percent);
  tr.insertCell().textContent = fmt(d.disk_percent);
  tr.insertCell().textContent = fmt(d.load_1m);
  tr.insertCell().textContent = d.procs||'—';
}

// init
queryDate();
</script>
</body>
</html>
"""


@app.route("/")
def index():
    return render_template_string(INDEX_HTML)


if __name__ == "__main__":
    app.run(host=HOST, port=PORT, debug=False)
