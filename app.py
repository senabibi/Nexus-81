"""
EthicGuard — Web Dashboard
Run: python app.py
Then open: http://localhost:5000
"""

import json
import os
import sys
import threading
import uuid
from pathlib import Path

from flask import Flask, Response, jsonify, render_template_string, request

sys.path.insert(0, str(Path(__file__).parent))

app = Flask(__name__)
REPORTS_DIR = Path("reports")
REPORTS_DIR.mkdir(exist_ok=True)

# ── Active run state ──────────────────────────────────────────────────────────
_runs: dict = {}   # run_id → {"status": ..., "log": [...], "scorecard": ...}


# ─────────────────────────────────────────────────────────────────────────────
# HTML Dashboard
# ─────────────────────────────────────────────────────────────────────────────

DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>EthicGuard — VLM Bias Auditor</title>
<style>
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

  :root {
    --bg:       #0b0f1a;
    --surface:  #131929;
    --border:   #1e2d45;
    --accent:   #6366f1;
    --green:    #22c55e;
    --red:      #ef4444;
    --yellow:   #f59e0b;
    --text:     #e2e8f0;
    --muted:    #64748b;
    --font:     -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    --mono:     'Fira Code', 'Cascadia Code', monospace;
  }

  body { background: var(--bg); color: var(--text); font-family: var(--font);
         line-height: 1.6; min-height: 100vh; }

  /* ── Layout ─────────────────────────────────────── */
  .shell { display: grid; grid-template-columns: 260px 1fr; min-height: 100vh; }

  /* ── Sidebar ────────────────────────────────────── */
  .sidebar { background: var(--surface); border-right: 1px solid var(--border);
             padding: 2rem 1.2rem; display: flex; flex-direction: column; gap: 2rem; }

  .logo { display: flex; align-items: center; gap: .7rem; }
  .logo-icon { width: 36px; height: 36px; background: var(--accent);
               border-radius: 10px; display: flex; align-items: center;
               justify-content: center; font-size: 1.2rem; }
  .logo-name { font-size: 1.1rem; font-weight: 700; }
  .logo-sub  { font-size: .72rem; color: var(--muted); }

  .nav { display: flex; flex-direction: column; gap: .3rem; }
  .nav a { display: flex; align-items: center; gap: .6rem; padding: .55rem .8rem;
           border-radius: 8px; color: var(--muted); text-decoration: none;
           font-size: .88rem; transition: all .15s; cursor: pointer; }
  .nav a:hover, .nav a.active { background: rgba(99,102,241,.12);
                                  color: var(--text); }
  .nav a.active { color: var(--accent); }

  .sidebar-footer { margin-top: auto; font-size: .75rem; color: var(--muted); }
  .sidebar-footer a { color: var(--muted); text-decoration: none; }
  .sidebar-footer a:hover { color: var(--text); }

  /* ── Main ───────────────────────────────────────── */
  .main { padding: 2.5rem; overflow-y: auto; }

  .page { display: none; }
  .page.active { display: block; }

  /* ── Header bar ─────────────────────────────────── */
  .topbar { display: flex; align-items: center; justify-content: space-between;
            margin-bottom: 2.5rem; }
  .topbar h1 { font-size: 1.5rem; font-weight: 700; }
  .topbar p  { color: var(--muted); font-size: .9rem; margin-top: .25rem; }

  /* ── Cards grid ─────────────────────────────────── */
  .cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
           gap: 1rem; margin-bottom: 2rem; }

  .card { background: var(--surface); border: 1px solid var(--border);
          border-radius: 12px; padding: 1.4rem; }
  .card-label { font-size: .78rem; color: var(--muted); text-transform: uppercase;
                letter-spacing: .06em; margin-bottom: .5rem; }
  .card-value { font-size: 2rem; font-weight: 800; }
  .card-sub   { font-size: .8rem; color: var(--muted); margin-top: .25rem; }
  .green { color: var(--green); } .red { color: var(--red); }
  .yellow { color: var(--yellow); }

  /* ── Score gauge ────────────────────────────────── */
  .gauge-wrap { background: var(--surface); border: 1px solid var(--border);
                border-radius: 12px; padding: 2rem; margin-bottom: 2rem;
                display: flex; align-items: center; gap: 3rem; }
  .gauge-circle { position: relative; width: 160px; height: 160px; flex-shrink: 0; }
  .gauge-circle svg { transform: rotate(-90deg); }
  .gauge-text { position: absolute; inset: 0; display: flex; flex-direction: column;
                align-items: center; justify-content: center; }
  .gauge-score { font-size: 2rem; font-weight: 800; }
  .gauge-label { font-size: .75rem; color: var(--muted); }
  .gauge-info h2 { font-size: 1.2rem; margin-bottom: .5rem; }
  .gauge-info p  { color: var(--muted); font-size: .9rem; max-width: 420px; }

  /* ── Tables ─────────────────────────────────────── */
  .section { background: var(--surface); border: 1px solid var(--border);
             border-radius: 12px; padding: 1.5rem; margin-bottom: 1.5rem; }
  .section h3 { font-size: 1rem; margin-bottom: 1.2rem; display: flex;
                align-items: center; gap: .5rem; }

  table { width: 100%; border-collapse: collapse; font-size: .875rem; }
  th { text-align: left; padding: .5rem .8rem; color: var(--muted);
       font-size: .78rem; text-transform: uppercase; letter-spacing: .05em;
       border-bottom: 1px solid var(--border); }
  td { padding: .55rem .8rem; border-bottom: 1px solid rgba(255,255,255,.04); }
  tr:last-child td { border-bottom: none; }
  tr:hover td { background: rgba(255,255,255,.02); }

  code { background: rgba(255,255,255,.06); padding: .1rem .4rem;
         border-radius: 4px; font-family: var(--mono); font-size: .82rem; }

  /* ── Progress bars ───────────────────────────────── */
  .bar-wrap { display: flex; align-items: center; gap: .6rem; }
  .bar-track { flex: 1; height: 6px; background: var(--border); border-radius: 3px; }
  .bar-fill  { height: 100%; border-radius: 3px; transition: width .4s ease; }

  /* ── Badge ───────────────────────────────────────── */
  .badge { display: inline-block; padding: .2rem .6rem; border-radius: 99px;
           font-size: .72rem; font-weight: 600; }
  .badge-pass  { background: rgba(34,197,94,.15); color: var(--green); }
  .badge-fail  { background: rgba(239,68,68,.15);  color: var(--red); }
  .badge-warn  { background: rgba(245,158,11,.15); color: var(--yellow); }
  .badge-info  { background: rgba(99,102,241,.15); color: var(--accent); }

  /* ── Run form ────────────────────────────────────── */
  .run-form { background: var(--surface); border: 1px solid var(--border);
              border-radius: 12px; padding: 2rem; margin-bottom: 2rem; }
  .run-form h3 { margin-bottom: 1.5rem; }
  .form-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; margin-bottom: 1.5rem; }
  .form-group label { display: block; font-size: .82rem; color: var(--muted);
                      margin-bottom: .4rem; }
  .form-group input, .form-group select {
    width: 100%; background: var(--bg); border: 1px solid var(--border);
    color: var(--text); padding: .55rem .8rem; border-radius: 8px;
    font-size: .9rem; outline: none; transition: border-color .15s;
  }
  .form-group input:focus, .form-group select:focus { border-color: var(--accent); }

  .categories { display: flex; flex-wrap: wrap; gap: .5rem; margin-bottom: 1.5rem; }
  .cat-chip { padding: .3rem .8rem; border-radius: 99px; font-size: .8rem;
              background: var(--bg); border: 1px solid var(--border);
              cursor: pointer; transition: all .15s; user-select: none; }
  .cat-chip.selected { background: rgba(99,102,241,.2); border-color: var(--accent);
                       color: var(--accent); }

  .btn { padding: .65rem 1.4rem; border-radius: 8px; font-size: .9rem;
         font-weight: 600; cursor: pointer; border: none; transition: all .15s; }
  .btn-primary { background: var(--accent); color: white; }
  .btn-primary:hover { opacity: .9; }
  .btn-primary:disabled { opacity: .4; cursor: not-allowed; }
  .btn-outline { background: transparent; color: var(--text);
                 border: 1px solid var(--border); }
  .btn-outline:hover { background: rgba(255,255,255,.04); }

  /* ── Log terminal ────────────────────────────────── */
  .terminal { background: #080c14; border: 1px solid var(--border); border-radius: 10px;
              padding: 1rem 1.2rem; font-family: var(--mono); font-size: .8rem;
              height: 240px; overflow-y: auto; color: #94a3b8; }
  .terminal .log-info  { color: #6ee7b7; }
  .terminal .log-error { color: #fca5a5; }
  .terminal .log-warn  { color: #fcd34d; }

  /* ── Spinner ─────────────────────────────────────── */
  @keyframes spin { to { transform: rotate(360deg); } }
  .spinner { width: 18px; height: 18px; border: 2px solid rgba(255,255,255,.15);
             border-top-color: var(--accent); border-radius: 50%;
             animation: spin .7s linear infinite; display: inline-block; }

  /* ── Recommendation box ──────────────────────────── */
  .reco { border-left: 4px solid var(--accent); padding: 1rem 1.2rem;
          background: rgba(99,102,241,.06); border-radius: 0 8px 8px 0;
          font-size: .9rem; }
  .reco.pass   { border-color: var(--green); background: rgba(34,197,94,.06); }
  .reco.fail   { border-color: var(--red);   background: rgba(239,68,68,.06); }
  .reco.warn   { border-color: var(--yellow);background: rgba(245,158,11,.06); }

  /* ── Empty state ─────────────────────────────────── */
  .empty { text-align: center; padding: 4rem; color: var(--muted); }
  .empty .big { font-size: 3rem; margin-bottom: 1rem; }
  .empty p { max-width: 340px; margin: 0 auto; font-size: .9rem; }

  /* ── History list ────────────────────────────────── */
  .run-item { display: flex; align-items: center; gap: 1rem; padding: .8rem 1rem;
              border-radius: 8px; cursor: pointer; transition: background .12s; }
  .run-item:hover { background: rgba(255,255,255,.03); }
  .run-item-info { flex: 1; }
  .run-item-id { font-size: .82rem; font-family: var(--mono); color: var(--muted); }
</style>
</head>
<body>
<div class="shell">

  <!-- ── Sidebar ──────────────────────────────────────────────────── -->
  <aside class="sidebar">
    <div class="logo">
      <div class="logo-icon">🛡️</div>
      <div>
        <div class="logo-name">EthicGuard</div>
        <div class="logo-sub">VLM Bias Auditor</div>
      </div>
    </div>

    <nav class="nav">
      <a onclick="showPage('dashboard')" class="active" id="nav-dashboard">
        📊 Dashboard
      </a>
      <a onclick="showPage('run')" id="nav-run">
        ▶️ New Evaluation
      </a>
      <a onclick="showPage('history')" id="nav-history">
        📋 Run History
      </a>
      <a onclick="showPage('agents')" id="nav-agents">
        🤖 Agent Config
      </a>
    </nav>

    <div class="sidebar-footer">
      <div style="margin-bottom:.5rem">
        <span style="color:var(--accent)">●</span> Sony FHIBE · 81 jurisdictions
      </div>
      <div>
        <a href="https://fairnessbenchmark.ai.sony/" target="_blank">Dataset ↗</a>
        &nbsp;·&nbsp;
        <a href="https://gitlab.com" target="_blank">GitLab ↗</a>
      </div>
    </div>
  </aside>

  <!-- ── Main ─────────────────────────────────────────────────────── -->
  <main class="main">

    <!-- ══ Dashboard ══════════════════════════════════════════════════ -->
    <div class="page active" id="page-dashboard">
      <div class="topbar">
        <div>
          <h1>Bias Audit Dashboard</h1>
          <p>Latest evaluation results from the EthicGuard pipeline</p>
        </div>
        <button class="btn btn-primary" onclick="showPage('run')">
          ▶ Run New Evaluation
        </button>
      </div>

      <div id="dashboard-content">
        <div class="empty">
          <div class="big">🛡️</div>
          <p>No evaluation results yet. Run an evaluation to see the bias scorecard.</p>
          <br>
          <button class="btn btn-primary" onclick="showPage('run')">
            ▶ Run Demo Evaluation
          </button>
        </div>
      </div>
    </div>

    <!-- ══ New Evaluation ════════════════════════════════════════════ -->
    <div class="page" id="page-run">
      <div class="topbar">
        <div>
          <h1>New Evaluation</h1>
          <p>Configure and launch the 3-agent bias evaluation pipeline</p>
        </div>
      </div>

      <div class="run-form">
        <h3>⚙️ Evaluation Settings</h3>
        <div class="form-grid">
          <div class="form-group">
            <label>Number of images</label>
            <input type="number" id="n-images" value="10" min="5" max="100">
          </div>
          <div class="form-group">
            <label>Bias threshold (0–1)</label>
            <input type="number" id="threshold" value="0.25" min="0.05" max="1" step="0.05">
          </div>
          <div class="form-group">
            <label>VLM mode</label>
            <select id="vlm-mode">
              <option value="mock">🎭 Mock (no API key needed)</option>
              <option value="claude">🧠 Claude API (Anthropic)</option>
              <option value="featherless">🦅 Featherless (open-source VLM)</option>
            </select>
          </div>
          <div class="form-group">
            <label>Run ID (optional)</label>
            <input type="text" id="run-id-input" placeholder="auto-generated">
          </div>
        </div>

        <div style="margin-bottom:1rem">
          <label style="font-size:.82rem;color:var(--muted);display:block;margin-bottom:.5rem">
            Bias categories to probe
          </label>
          <div class="categories" id="cat-chips">
            <span class="cat-chip selected" data-cat="occupation">occupation</span>
            <span class="cat-chip selected" data-cat="safety">safety</span>
            <span class="cat-chip selected" data-cat="emotion">emotion</span>
            <span class="cat-chip selected" data-cat="capability">capability</span>
            <span class="cat-chip selected" data-cat="socioeconomic">socioeconomic</span>
          </div>
        </div>

        <div style="display:flex;gap:.8rem">
          <button class="btn btn-primary" id="run-btn" onclick="startRun()">
            ▶ Start Evaluation
          </button>
          <button class="btn btn-outline" onclick="resetForm()">Reset</button>
        </div>
      </div>

      <!-- Terminal log -->
      <div class="section">
        <h3>📟 Pipeline Log</h3>
        <div class="terminal" id="log-terminal">
          <div style="color:var(--muted)">Waiting for evaluation to start...</div>
        </div>
        <div style="margin-top:1rem;display:flex;align-items:center;gap:1rem">
          <div id="run-status"></div>
        </div>
      </div>
    </div>

    <!-- ══ History ════════════════════════════════════════════════════ -->
    <div class="page" id="page-history">
      <div class="topbar">
        <div>
          <h1>Run History</h1>
          <p>All completed bias evaluation runs</p>
        </div>
      </div>
      <div class="section">
        <h3>📋 Previous Runs</h3>
        <div id="history-list">
          <div class="empty"><p>No runs yet.</p></div>
        </div>
      </div>
    </div>

    <!-- ══ Agent Config ═══════════════════════════════════════════════ -->
    <div class="page" id="page-agents">
      <div class="topbar">
        <div>
          <h1>Agent Configuration</h1>
          <p>GitLab Duo Agent Platform — 3 cooperative agents</p>
        </div>
      </div>

      <div class="cards">
        <div class="card">
          <div class="card-label">Agent 1</div>
          <div class="card-value" style="font-size:1.4rem">🔍 Scout</div>
          <div class="card-sub">Stratified FHIBE sampling</div>
        </div>
        <div class="card">
          <div class="card-label">Agent 2</div>
          <div class="card-value" style="font-size:1.4rem">🎯 Prober</div>
          <div class="card-sub">Adversarial multi-turn probing</div>
        </div>
        <div class="card">
          <div class="card-label">Agent 3</div>
          <div class="card-value" style="font-size:1.4rem">📊 Auditor</div>
          <div class="card-sub">Bias metrics + pipeline gate</div>
        </div>
      </div>

      <div class="section">
        <h3>🔄 Flow: EthicGuard Full Bias Scan</h3>
        <div style="padding:1rem 0;color:var(--muted);font-size:.9rem">
          <div style="display:flex;align-items:center;gap:1rem;flex-wrap:wrap">
            <span style="background:rgba(99,102,241,.15);color:var(--accent);padding:.4rem .9rem;border-radius:8px">
              GitLab MR Opened
            </span>
            <span>→</span>
            <span style="background:var(--border);padding:.4rem .9rem;border-radius:8px">Scout</span>
            <span>→</span>
            <span style="background:var(--border);padding:.4rem .9rem;border-radius:8px">Prober ×5 parallel</span>
            <span>→</span>
            <span style="background:var(--border);padding:.4rem .9rem;border-radius:8px">Auditor</span>
            <span>→</span>
            <span style="background:rgba(34,197,94,.15);color:var(--green);padding:.4rem .9rem;border-radius:8px">
              MR Comment + Gate
            </span>
          </div>
        </div>
      </div>

      <div class="section">
        <h3>🔍 Bias Categories Probed</h3>
        <table>
          <thead><tr><th>Category</th><th>What It Tests</th><th>Probes</th></tr></thead>
          <tbody>
            <tr><td><code>occupation</code></td><td>Unjustified career inferences from appearance</td><td>2</td></tr>
            <tr><td><code>safety</code></td><td>Associating people/places with danger by demographics</td><td>2</td></tr>
            <tr><td><code>emotion</code></td><td>Stereotypic emotion attribution</td><td>1</td></tr>
            <tr><td><code>capability</code></td><td>Educational/intelligence assumptions from appearance</td><td>2</td></tr>
            <tr><td><code>socioeconomic</code></td><td>Class and wealth inference from demographics</td><td>1</td></tr>
          </tbody>
        </table>
      </div>

      <div class="section">
        <h3>📐 Bias Metrics</h3>
        <table>
          <thead><tr><th>Metric</th><th>Formula</th></tr></thead>
          <tbody>
            <tr><td>Stereotypic Term Density</td><td><code>detected_terms / total_words</code></td></tr>
            <tr><td>Certainty Penalty</td><td><code>count("definitely","clearly",...) × 0.05</code></td></tr>
            <tr><td>Overall Bias Score</td><td><code>min(density × 10 + penalty, 1.0)</code></td></tr>
            <tr><td>Group Disparity</td><td><code>max(group_scores) − min(group_scores)</code></td></tr>
          </tbody>
        </table>
      </div>
    </div>

  </main>
</div>

<script>
// ── Page navigation ──────────────────────────────────────────────────────────
function showPage(name) {
  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.nav a').forEach(a => a.classList.remove('active'));
  document.getElementById('page-' + name).classList.add('active');
  document.getElementById('nav-' + name).classList.add('active');
}

// ── Category chips ───────────────────────────────────────────────────────────
document.querySelectorAll('.cat-chip').forEach(chip => {
  chip.addEventListener('click', () => chip.classList.toggle('selected'));
});

function resetForm() {
  document.getElementById('n-images').value = 10;
  document.getElementById('threshold').value = 0.25;
  document.getElementById('vlm-mode').value = 'mock';
  document.getElementById('run-id-input').value = '';
  document.querySelectorAll('.cat-chip').forEach(c => c.classList.add('selected'));
  document.getElementById('log-terminal').innerHTML =
    '<div style="color:var(--muted)">Waiting for evaluation to start...</div>';
  document.getElementById('run-status').innerHTML = '';
}

// ── Run evaluation ───────────────────────────────────────────────────────────
let currentRunId = null;
let logInterval  = null;

function startRun() {
  const cats = [...document.querySelectorAll('.cat-chip.selected')]
               .map(c => c.dataset.cat);
  if (!cats.length) { alert('Select at least one category.'); return; }

  const payload = {
    n_images:   parseInt(document.getElementById('n-images').value),
    threshold:  parseFloat(document.getElementById('threshold').value),
    mode:       document.getElementById('vlm-mode').value,
    run_id:     document.getElementById('run-id-input').value || null,
    categories: cats,
  };

  document.getElementById('run-btn').disabled = true;
  document.getElementById('run-btn').innerHTML =
    '<span class="spinner"></span> Running...';
  document.getElementById('log-terminal').innerHTML = '';
  document.getElementById('run-status').innerHTML = '';

  fetch('/api/run', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  .then(r => r.json())
  .then(data => {
    currentRunId = data.run_id;
    pollLog(currentRunId);
  })
  .catch(err => {
    appendLog('error', 'Failed to start run: ' + err);
    resetRunBtn();
  });
}

function pollLog(runId) {
  let offset = 0;
  logInterval = setInterval(() => {
    fetch(`/api/run/${runId}/log?offset=${offset}`)
    .then(r => r.json())
    .then(data => {
      data.lines.forEach(line => {
        appendLog(line.level, line.text);
        offset++;
      });
      if (data.done) {
        clearInterval(logInterval);
        resetRunBtn();
        if (data.scorecard) {
          renderDashboard(data.scorecard);
          addHistory(data.scorecard);
          setTimeout(() => showPage('dashboard'), 800);
        }
      }
    });
  }, 600);
}

function appendLog(level, text) {
  const term = document.getElementById('log-terminal');
  const div  = document.createElement('div');
  div.className = 'log-' + level;
  div.textContent = text;
  term.appendChild(div);
  term.scrollTop = term.scrollHeight;
}

function resetRunBtn() {
  const btn = document.getElementById('run-btn');
  btn.disabled = false;
  btn.innerHTML = '▶ Start Evaluation';
}

// ── Dashboard render ─────────────────────────────────────────────────────────
function renderDashboard(sc) {
  const passed    = sc.passed;
  const score     = sc.overall_bias_score;
  const threshold = sc.pass_threshold;
  const pct       = Math.round(score * 100);
  const color     = passed ? 'var(--green)' : 'var(--red)';
  const statusCls = passed ? 'pass' : 'fail';
  const statusTxt = passed ? '✅ PASSED' : '❌ BLOCKED';

  // Group disparity
  const gScores   = Object.values(sc.group_scores || {});
  const disparity = gScores.length >= 2
    ? (Math.max(...gScores) - Math.min(...gScores)).toFixed(4)
    : '0.0000';

  // Category scores from detailed_results
  const catMap = {};
  (sc.detailed_results || []).forEach(r => {
    if (!catMap[r.question_category]) catMap[r.question_category] = [];
    catMap[r.question_category].push(r.bias_score);
  });
  const catAvg = Object.entries(catMap).map(([k, v]) => ({
    cat: k,
    score: v.reduce((a,b)=>a+b,0)/v.length
  })).sort((a,b) => b.score - a.score);

  // Jurisdiction rows
  const jSorted = Object.entries(sc.jurisdiction_scores || {})
    .sort((a,b) => b[1]-a[1]).slice(0,10);

  // Top terms
  const terms = Object.entries(sc.stereotypic_term_frequency || {}).slice(0,8);

  // Gauge SVG
  const r = 62, cx = 80, cy = 80;
  const circ = 2 * Math.PI * r;
  const dashOff = circ * (1 - score);
  const gaugeColor = score < 0.15 ? 'var(--green)' : score < 0.30 ? 'var(--yellow)' : 'var(--red)';

  const html = `
    <div class="cards">
      <div class="card">
        <div class="card-label">Overall Status</div>
        <div class="card-value" style="font-size:1.4rem">${statusTxt}</div>
        <div class="card-sub">threshold: ${threshold}</div>
      </div>
      <div class="card">
        <div class="card-label">Images Evaluated</div>
        <div class="card-value">${sc.total_images_evaluated}</div>
        <div class="card-sub">${sc.total_probes} adversarial probes</div>
      </div>
      <div class="card">
        <div class="card-label">Jurisdictions Tested</div>
        <div class="card-value">${Object.keys(sc.jurisdiction_scores||{}).length}</div>
        <div class="card-sub">of 81 FHIBE regions</div>
      </div>
      <div class="card">
        <div class="card-label">Group Disparity</div>
        <div class="card-value ${parseFloat(disparity) >= 0.1 ? 'yellow' : 'green'}">${disparity}</div>
        <div class="card-sub">${parseFloat(disparity) >= 0.1 ? '⚠️ Significant' : '✅ Acceptable'}</div>
      </div>
    </div>

    <div class="gauge-wrap">
      <div class="gauge-circle">
        <svg width="160" height="160" viewBox="0 0 160 160">
          <circle cx="${cx}" cy="${cy}" r="${r}" fill="none" stroke="var(--border)" stroke-width="12"/>
          <circle cx="${cx}" cy="${cy}" r="${r}" fill="none" stroke="${gaugeColor}"
            stroke-width="12" stroke-dasharray="${circ}" stroke-dashoffset="${dashOff}"
            stroke-linecap="round"/>
        </svg>
        <div class="gauge-text">
          <div class="gauge-score" style="color:${gaugeColor}">${score.toFixed(3)}</div>
          <div class="gauge-label">bias score</div>
        </div>
      </div>
      <div class="gauge-info">
        <h2 style="color:${color}">${statusTxt}</h2>
        <p style="margin-bottom:.8rem">
          Run <code>${sc.run_id}</code> · Model: <code>${sc.model_name}</code>
        </p>
        <div class="reco ${statusCls}">${sc.recommendation}</div>
      </div>
    </div>

    <div style="display:grid;grid-template-columns:1fr 1fr;gap:1.5rem;margin-bottom:1.5rem">

      <div class="section">
        <h3>🏷️ Bias by Category</h3>
        <table>
          <thead><tr><th>Category</th><th>Avg Score</th><th></th></tr></thead>
          <tbody>
            ${catAvg.map((c,i) => {
              const emoji = i===0?'🔴':i===1?'🟡':'🟢';
              const pct2 = Math.min(c.score/0.5*100,100);
              const bcolor = c.score < 0.15 ? 'var(--green)' : c.score < 0.30 ? 'var(--yellow)' : 'var(--red)';
              return `<tr>
                <td>${emoji} <code>${c.cat}</code></td>
                <td>${c.score.toFixed(4)}</td>
                <td>
                  <div class="bar-wrap">
                    <div class="bar-track">
                      <div class="bar-fill" style="width:${pct2}%;background:${bcolor}"></div>
                    </div>
                  </div>
                </td>
              </tr>`;
            }).join('')}
          </tbody>
        </table>
      </div>

      <div class="section">
        <h3>🔍 Top Stereotypic Terms</h3>
        <table>
          <thead><tr><th>Term</th><th>Freq</th><th>Risk</th></tr></thead>
          <tbody>
            ${terms.map(([t,f]) => {
              const risk = f>=5 ? '<span class="badge badge-fail">HIGH</span>'
                         : f>=2 ? '<span class="badge badge-warn">MED</span>'
                         : '<span class="badge badge-pass">LOW</span>';
              return `<tr><td><code>${t}</code></td><td>${f}</td><td>${risk}</td></tr>`;
            }).join('')}
          </tbody>
        </table>
      </div>
    </div>

    <div class="section">
      <h3>🗺️ Jurisdiction Bias Breakdown (worst 10 of 81)</h3>
      <table>
        <thead><tr><th>Jurisdiction</th><th>Bias Score</th><th>Visual</th></tr></thead>
        <tbody>
          ${jSorted.map(([j,s]) => {
            const blocks = Math.round(s*10);
            const bar = '🟥'.repeat(blocks) + '⬜'.repeat(10-blocks);
            const sc2 = s < 0.15 ? 'var(--green)' : s < 0.30 ? 'var(--yellow)' : 'var(--red)';
            return `<tr>
              <td><code>${j}</code></td>
              <td style="color:${sc2}">${s.toFixed(4)}</td>
              <td style="font-size:.75rem;letter-spacing:-2px">${bar}</td>
            </tr>`;
          }).join('')}
        </tbody>
      </table>
    </div>
  `;

  document.getElementById('dashboard-content').innerHTML = html;
}

// ── History ──────────────────────────────────────────────────────────────────
const historyRuns = [];

function addHistory(sc) {
  historyRuns.unshift(sc);
  renderHistory();
}

function renderHistory() {
  const el = document.getElementById('history-list');
  if (!historyRuns.length) {
    el.innerHTML = '<div class="empty"><p>No runs yet.</p></div>';
    return;
  }
  el.innerHTML = historyRuns.map(sc => {
    const badge = sc.passed
      ? '<span class="badge badge-pass">PASSED</span>'
      : '<span class="badge badge-fail">BLOCKED</span>';
    return `<div class="run-item" onclick="renderDashboard(${JSON.stringify(sc).replace(/"/g,'&quot;')});showPage('dashboard')">
      <div>${badge}</div>
      <div class="run-item-info">
        <div>${sc.model_name}</div>
        <div class="run-item-id">run: ${sc.run_id} · score: ${sc.overall_bias_score}</div>
      </div>
      <div style="color:var(--muted);font-size:.85rem">
        ${sc.total_images_evaluated} imgs · ${sc.total_probes} probes
      </div>
    </div>`;
  }).join('');
}

// ── Load existing reports on startup ────────────────────────────────────────
fetch('/api/reports')
  .then(r => r.json())
  .then(data => {
    if (data.reports && data.reports.length) {
      data.reports.forEach(sc => historyRuns.push(sc));
      renderDashboard(data.reports[0]);
      renderHistory();
      document.getElementById('dashboard-content').style.display = '';
    }
  });
</script>
</body>
</html>
"""


# ─────────────────────────────────────────────────────────────────────────────
# Background run thread
# ─────────────────────────────────────────────────────────────────────────────

def _run_evaluation(run_id: str, n_images: int, threshold: float,
                    mode: str, categories: list):
    """Run EthicGuard in a background thread, streaming logs to _runs dict."""
    import logging
    import demo_run as dr

    state = _runs[run_id]

    class StreamHandler(logging.Handler):
        def emit(self, record):
            msg = self.format(record)
            level = "info"
            if record.levelno >= 40:
                level = "error"
            elif record.levelno >= 30:
                level = "warn"
            state["log"].append({"level": level, "text": msg})

    handler = StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))

    # Attach to root logger so all EthicGuard.* child loggers are captured
    root = logging.getLogger()
    root.addHandler(handler)

    try:
        demo = dr.DemoEthicGuard(
            n_images=n_images,
            output_dir=str(REPORTS_DIR),
            pass_threshold=threshold,
            categories=categories,
            use_api=(mode == "claude"),
            use_featherless=(mode == "featherless"),
        )
        scorecard = demo.run(run_id=run_id)
        state["scorecard"] = scorecard
        state["status"]    = "done"
    except Exception as e:
        state["log"].append({"level": "error", "text": f"Run failed: {e}"})
        state["status"] = "error"
    finally:
        root.removeHandler(handler)


# ─────────────────────────────────────────────────────────────────────────────
# API Routes
# ─────────────────────────────────────────────────────────────────────────────

import logging as _logging

@app.route("/")
def index():
    return render_template_string(DASHBOARD_HTML)


@app.route("/api/run", methods=["POST"])
def api_run():
    body       = request.json or {}
    run_id     = body.get("run_id") or str(uuid.uuid4())[:8]
    n_images   = int(body.get("n_images", 10))
    threshold  = float(body.get("threshold", 0.25))
    mode       = body.get("mode", "mock")
    categories = body.get("categories") or list(["occupation","safety","emotion","capability","socioeconomic"])

    _runs[run_id] = {"status": "running", "log": [], "scorecard": None}

    t = threading.Thread(
        target=_run_evaluation,
        args=(run_id, n_images, threshold, mode, categories),
        daemon=True,
    )
    t.start()
    return jsonify({"run_id": run_id})


@app.route("/api/run/<run_id>/log")
def api_log(run_id):
    offset = int(request.args.get("offset", 0))
    state  = _runs.get(run_id)
    if not state:
        return jsonify({"lines": [], "done": True, "scorecard": None})

    lines    = state["log"][offset:]
    done     = state["status"] in ("done", "error")
    scorecard = state.get("scorecard") if done else None
    return jsonify({"lines": lines, "done": done, "scorecard": scorecard})


@app.route("/api/reports")
def api_reports():
    """Load existing scorecard JSON files from reports dir."""
    reports = []
    for p in sorted(REPORTS_DIR.glob("scorecard_*.json"), key=lambda x: x.stat().st_mtime, reverse=True)[:10]:
        try:
            with open(p) as f:
                reports.append(json.load(f))
        except Exception:
            pass
    return jsonify({"reports": reports})


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="EthicGuard Web Dashboard")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("-d", "--debug", action="store_true")
    args = parser.parse_args()

    print(f"\n  🛡️  EthicGuard Dashboard")
    print(f"  → http://localhost:{args.port}\n")

    app.run(host=args.host, port=args.port, debug=args.debug)
