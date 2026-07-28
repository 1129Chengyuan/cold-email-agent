#!/usr/bin/env python3
# ============================================================
#  jobs_site.py
#  Generate a single self-contained static webpage listing all
#  current board roles (Workday + Greenhouse/Lever/Ashby) with
#  client-side search, source filters, new-grad toggle, and sort.
#
#  Design: dark glassmorphism — frosted translucent cards over a
#  soft gradient "void", typography-driven hierarchy (Space
#  Grotesk display + Inter body), purposeful hover motion.
#
#  No server, no dependencies — the data is embedded as JSON and
#  the page runs on vanilla JS. Open the output file in a browser.
#
#  Usage:
#    python -m src.digest.jobs_site                 # -> docs/index.html (GitHub Pages)
#    python -m src.digest.jobs_site --out foo.html  # custom path
#    python -m src.digest.jobs_site --open          # build + open in browser
# ============================================================

from __future__ import annotations

import argparse
import datetime as dt
import json
import webbrowser
from pathlib import Path

from src.jobs import h1b_greenhouse as hg
from src.ranking import fit_ranker
from src.core import config

# docs/ because GitHub Pages can only serve a branch's root or /docs folder.
OUT_DEFAULT = Path(config.PROJECT_ROOT) / "docs" / "index.html"

# Big-name employers surfaced as "browse yourself" links (site hero + email):
# their boards are huge (Amazon) or block scraping (Google/Apple/Tesla/
# Bloomberg). Single source of truth — daily_job_email imports this.
# (name, url, brand color for the pill dot)
BROWSE_LINKS = [
    ("Amazon",    "https://www.amazon.jobs/en/search?base_query=software+engineer&loc_query=United+States", "#ff9900"),
    ("Google",    "https://www.google.com/about/careers/applications/jobs/results/?q=software%20engineer&hl=en&target_level=EARLY&location=United%20States", "#4285f4"),
    ("Microsoft", "https://jobs.careers.microsoft.com/global/en/search?q=software%20engineer&lc=United%20States", "#00a4ef"),
    ("Apple",     "https://jobs.apple.com/en-us/search?search=software%20engineer&location=united-states-USA", "#b8bfc6"),
    ("Tesla",     "https://www.tesla.com/careers/search/?query=software%20engineer&region=5", "#e82127"),
    ("Bloomberg", "https://bloomberg.avature.net/careers/SearchJobs/Software%20engineer?1686=%5B55478%5D&1686_format=2312&listFilterMode=1&jobRecordsPerPage=12&", "#9d7bff"),
    ("LinkedIn",  "https://www.linkedin.com/jobs/search/?f_C=1337&f_E=2%2C3&keywords=software%20engineer&location=United%20States&origin=JOB_SEARCH_PAGE_JOB_FILTER", "#0a66c2"),
]


def collect() -> list[dict]:
    """Current roles from the original board sources."""
    jobs = hg.daily_fresh_swe(us_only=True, include_aggregator=False,
                              include_custom=False)
    out = []
    for j in jobs:
        item = {
            "company": (j.get("company") or "").split("|")[0],  # clean Workday token
            "title": j.get("title", ""),
            "location": j.get("location", "") or "Location N/A",
            "url": j.get("url", ""),
            "source": j.get("ats", ""),
            "new_grad": bool(j.get("new_grad")),
            "is_new": bool(j.get("is_new")),
            "first_seen": j.get("first_seen", "") or j.get("updated_at", ""),
        }
        # every role gets a fit score: an LLM score if the ranker produced one,
        # else a free keyword score so "Best fit" is fully populated
        if isinstance(j.get("fit_score"), int) and j["fit_score"] >= 0:
            item["fit_score"], item["fit_reason"] = j["fit_score"], j.get("fit_reason", "")
        else:
            item["fit_score"], item["fit_reason"] = fit_ranker.keyword_fit(
                item["title"], item["company"])
        out.append(item)
    return out


def _browse_pills() -> str:
    return "".join(
        f'<a class="pill" href="{url}" target="_blank" rel="noopener">'
        f'<span class="dot" style="background:{color}"></span>{name}'
        f'<span class="arrow">&#8599;</span></a>'
        for name, url, color in BROWSE_LINKS)


# Template uses __TOKEN__ placeholders (not str.format) so the CSS/JS braces
# don't need escaping.
_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Fresh SWE/DE/Infra Internships · __COUNT__</title>
<meta name="description" content="Software, data, and infrastructure internships at verified H-1B sponsors, refreshed daily.">
<meta name="color-scheme" content="dark light">
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'%3E%3Cdefs%3E%3ClinearGradient id='g' x1='0' y1='0' x2='1' y2='1'%3E%3Cstop offset='0' stop-color='%236366f1'/%3E%3Cstop offset='1' stop-color='%2338bdf8'/%3E%3C/linearGradient%3E%3C/defs%3E%3Crect width='64' height='64' rx='14' fill='url(%23g)'/%3E%3Ctext x='32' y='45' font-family='Arial,Helvetica,sans-serif' font-size='30' font-weight='800' fill='white' text-anchor='middle'%3EH1%3C/text%3E%3C/svg%3E">
<script>
  // set theme before first paint: saved choice, else system preference
  document.documentElement.dataset.theme =
    localStorage.getItem('theme') ||
    (matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark');
</script>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Space+Grotesk:wght@500;600;700&display=swap" rel="stylesheet">
<style>
  :root {
    --bg:#070b14; --ink:#e8edf6; --muted:#93a0b4; --faint:#5d6a80;
    --glass:rgba(255,255,255,.045); --glass-hi:rgba(255,255,255,.08);
    --card:rgba(255,255,255,.045);
    --line:rgba(255,255,255,.09); --line-hi:rgba(255,255,255,.22);
    --indigo:#6366f1; --sky:#38bdf8; --violet:#a78bfa;
    --grad:linear-gradient(135deg,#6366f1,#38bdf8);
    --toolbar-bg:rgba(11,16,28,.72); --menu-bg:#0d1322;
    --ok:#4ade80; --ok-bg:rgba(74,222,128,.14); --ok-line:rgba(74,222,128,.3);
    --vio:#c4b5fd; --vio-bg:rgba(167,139,250,.14); --vio-line:rgba(167,139,250,.3);
    --amb:#fbbf24; --amb-bg:rgba(251,191,36,.12); --amb-line:rgba(251,191,36,.3);
    --chip-on-bg:rgba(99,102,241,.16); --chip-on-line:rgba(99,102,241,.55); --chip-on-fg:#c7d2fe;
    --shadow:0 14px 34px rgba(0,0,0,.36);
    --glow1:rgba(99,102,241,.16); --glow2:rgba(56,189,248,.10); --glow3:rgba(167,139,250,.10);
    --r-lg:20px; --r-md:14px;
  }
  html[data-theme="light"] {
    --bg:#f7f8fb; --ink:#171c26; --muted:#4b5565; --faint:#8a93a3;
    --glass:rgba(15,23,42,.04); --glass-hi:rgba(15,23,42,.07);
    --card:#ffffff;
    --line:rgba(15,23,42,.10); --line-hi:rgba(15,23,42,.26);
    --toolbar-bg:rgba(247,248,251,.82); --menu-bg:#ffffff;
    --ok:#15803d; --ok-bg:rgba(22,163,74,.10); --ok-line:rgba(22,163,74,.28);
    --vio:#6d28d9; --vio-bg:rgba(124,58,237,.09); --vio-line:rgba(124,58,237,.25);
    --amb:#a16207; --amb-bg:rgba(202,138,4,.10); --amb-line:rgba(202,138,4,.28);
    --chip-on-bg:rgba(99,102,241,.10); --chip-on-line:rgba(99,102,241,.5); --chip-on-fg:#4338ca;
    --shadow:0 14px 30px rgba(15,23,42,.12);
    --glow1:rgba(99,102,241,.09); --glow2:rgba(56,189,248,.07); --glow3:rgba(167,139,250,.07);
  }
  * { box-sizing:border-box; }
  html { scroll-behavior:smooth; }
  body {
    margin:0; background:var(--bg); color:var(--ink);
    font-family:'Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
    font-size:15px; line-height:1.5;
    -webkit-font-smoothing:antialiased;
    transition:background .2s ease, color .2s ease;
  }
  /* soft gradient glows (subtle in both themes) */
  .glow { position:fixed; inset:0; z-index:-1; pointer-events:none;
    background:
      radial-gradient(52rem 30rem at 12% -8%, var(--glow1), transparent 60%),
      radial-gradient(44rem 26rem at 88% 4%, var(--glow2), transparent 60%),
      radial-gradient(60rem 34rem at 50% 115%, var(--glow3), transparent 60%); }
  .wrap { max-width:1320px; margin:0 auto; padding:44px 22px 80px; }
  a { color:inherit; }

  /* ── Hero ─────────────────────────────────────────── */
  .eyebrow { font-size:12px; font-weight:600; letter-spacing:.14em;
    text-transform:uppercase; color:var(--sky); margin-bottom:14px; }
  h1 { font-family:'Space Grotesk',sans-serif; font-size:clamp(34px,5vw,54px);
    font-weight:700; letter-spacing:-.02em; line-height:1.05; margin:0 0 12px; }
  h1 .accent { background:var(--grad); -webkit-background-clip:text;
    background-clip:text; color:transparent; }
  .sub { color:var(--muted); font-size:16px; max-width:640px; margin:0 0 22px; }
  .stats { display:flex; gap:10px; flex-wrap:wrap; margin-bottom:34px; }
  .stat { padding:7px 15px; border-radius:999px; font-size:13px; font-weight:600;
    background:var(--glass); border:1px solid var(--line); color:var(--muted); }
  .stat b { color:var(--ink); font-weight:700; }
  .stat.hot b { color:var(--ok); }

  /* ── Browse-direct pills (top of page) ────────────── */
  .browse { border:1px solid var(--line); border-radius:var(--r-lg);
    background:var(--card); backdrop-filter:blur(14px); -webkit-backdrop-filter:blur(14px);
    padding:20px 22px 16px; margin-bottom:30px; }
  .browse h2 { font-family:'Space Grotesk',sans-serif; font-size:17px;
    font-weight:600; margin:0 0 3px; }
  .browse p { color:var(--faint); font-size:13px; margin:0 0 14px; }
  .pills { display:flex; flex-wrap:wrap; gap:9px; }
  .pill { display:inline-flex; align-items:center; gap:8px; padding:9px 16px;
    border-radius:999px; background:var(--glass); border:1px solid var(--line);
    font-size:13.5px; font-weight:600; text-decoration:none;
    transition:border-color .18s, background .18s, transform .18s; }
  .pill:hover { border-color:var(--line-hi); background:var(--glass-hi);
    transform:translateY(-1px); }
  .pill .dot { width:8px; height:8px; border-radius:50%; flex:0 0 auto; }
  .pill .arrow { color:var(--faint); font-size:12px; transition:color .18s, transform .18s; }
  .pill:hover .arrow { color:var(--sky); transform:translate(1px,-1px); }

  /* ── Tracker bar (button + quick-add) ─────────────── */
  .tracker-bar { display:flex; flex-wrap:wrap; align-items:center; gap:12px;
    padding:15px 18px; margin-bottom:26px; border:1px solid var(--line);
    border-radius:var(--r-lg); background:var(--card);
    backdrop-filter:blur(14px); -webkit-backdrop-filter:blur(14px); }
  .btn-track { display:inline-flex; align-items:center; gap:8px; padding:10px 18px;
    border-radius:999px; background:var(--indigo); color:#fff; font-weight:650;
    font-size:14px; text-decoration:none; white-space:nowrap;
    transition:filter .16s, transform .16s; }
  .btn-track:hover { filter:brightness(1.08); transform:translateY(-1px); }
  .quick-add { display:flex; flex-wrap:wrap; align-items:center; gap:9px; flex:1; min-width:260px; }
  .quick-add input { flex:1; min-width:180px; padding:9px 14px; font:inherit; font-size:14px;
    color:var(--ink); background:var(--glass); border:1px solid var(--line);
    border-radius:var(--r-md); outline:none; transition:border-color .18s, box-shadow .18s; }
  .quick-add input::placeholder { color:var(--faint); }
  .quick-add input:focus { border-color:var(--indigo); box-shadow:0 0 0 3px rgba(99,102,241,.22); }
  .quick-add button { padding:9px 16px; font:inherit; font-size:14px; font-weight:600; cursor:pointer;
    border-radius:var(--r-md); background:var(--glass-hi); border:1px solid var(--line-hi); color:var(--ink);
    transition:border-color .16s; }
  .quick-add button:hover { border-color:var(--indigo); }
  .qa-msg { font-size:13px; color:var(--ok); font-weight:600; white-space:nowrap; }

  /* ── Sticky glass toolbar ─────────────────────────── */
  .toolbar { position:sticky; top:12px; z-index:20; display:flex; flex-wrap:wrap;
    gap:10px; align-items:center; padding:12px 14px; margin-bottom:14px;
    border:1px solid var(--line); border-radius:var(--r-lg);
    background:var(--toolbar-bg); backdrop-filter:blur(18px);
    -webkit-backdrop-filter:blur(18px); }
  input[type=search] { flex:1; min-width:200px; padding:10px 15px; font:inherit;
    font-size:14px; color:var(--ink); background:var(--glass);
    border:1px solid var(--line); border-radius:var(--r-md); outline:none;
    transition:border-color .18s, box-shadow .18s; }
  input[type=search]::placeholder { color:var(--faint); }
  input[type=search]:focus { border-color:var(--indigo);
    box-shadow:0 0 0 3px rgba(99,102,241,.22); }
  .chip { padding:8px 15px; border-radius:999px; font-size:13px; font-weight:600;
    text-transform:capitalize; cursor:pointer; user-select:none; font-family:inherit;
    background:transparent; border:1px solid var(--line); color:var(--muted);
    transition:all .18s; }
  .chip:hover { border-color:var(--line-hi); color:var(--ink); }
  .chip.on { background:var(--chip-on-bg); border-color:var(--chip-on-line);
    color:var(--chip-on-fg); }
  label.tog { display:flex; align-items:center; gap:7px; font-size:13px;
    font-weight:500; color:var(--muted); cursor:pointer; }
  label.tog input { accent-color:var(--indigo); width:15px; height:15px; }
  select { padding:9px 12px; font:inherit; font-size:13px; color:var(--ink);
    background:var(--glass); border:1px solid var(--line);
    border-radius:var(--r-md); outline:none; cursor:pointer; }
  select option { background:var(--menu-bg); }
  .count { font-size:13px; color:var(--faint); margin:0 4px 16px; }

  /* ── Job cards ────────────────────────────────────── */
  .grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(295px,1fr));
    gap:14px; }
  .card { display:flex; flex-direction:column; gap:9px; padding:18px;
    border-radius:var(--r-lg); text-decoration:none;
    background:var(--card); border:1px solid var(--line);
    backdrop-filter:blur(10px); -webkit-backdrop-filter:blur(10px);
    transition:transform .18s, border-color .18s, background .18s, box-shadow .18s; }
  .card:hover { transform:translateY(-3px); border-color:var(--line-hi);
    box-shadow:var(--shadow), 0 0 0 1px rgba(99,102,241,.14); }
  .co { display:flex; align-items:center; gap:10px; }
  .mono { width:36px; height:36px; border-radius:11px; flex:0 0 auto;
    display:flex; align-items:center; justify-content:center;
    font-family:'Space Grotesk',sans-serif; font-weight:700; font-size:15px;
    color:#fff; }
  .co-name { font-size:13px; font-weight:600; color:var(--muted);
    text-transform:capitalize; overflow:hidden; text-overflow:ellipsis;
    white-space:nowrap; }
  .title { font-size:15.5px; font-weight:600; line-height:1.34; color:var(--ink); }
  .card:hover .title { background:var(--grad); -webkit-background-clip:text;
    background-clip:text; color:transparent; }
  .loc { font-size:12.5px; color:var(--faint); overflow:hidden;
    text-overflow:ellipsis; white-space:nowrap; }
  .meta { display:flex; align-items:center; gap:7px; flex-wrap:wrap;
    margin-top:auto; padding-top:6px; }
  .badge { font-size:10px; font-weight:700; letter-spacing:.05em;
    text-transform:uppercase; padding:3px 9px; border-radius:999px; }
  .b-new { background:var(--ok-bg); color:var(--ok);
    border:1px solid var(--ok-line); }
  .b-grad { background:var(--vio-bg); color:var(--vio);
    border:1px solid var(--vio-line); }
  .b-fit-hi  { background:var(--ok-bg);  color:var(--ok);  border:1px solid var(--ok-line); }
  .b-fit-mid { background:var(--amb-bg); color:var(--amb); border:1px solid var(--amb-line); }
  .b-fit-lo  { background:var(--glass);  color:var(--muted); border:1px solid var(--line); }
  .b-src { background:var(--glass); border:1px solid var(--line); }
  .seen { font-size:11px; color:var(--faint); margin-left:auto; }
  .empty { grid-column:1/-1; text-align:center; color:var(--faint);
    padding:70px 0; border:1px dashed var(--line); border-radius:var(--r-lg); }

  footer { margin-top:44px; padding-top:22px; border-top:1px solid var(--line);
    color:var(--faint); font-size:12.5px; line-height:1.7; }
  footer code { background:var(--glass); border:1px solid var(--line);
    border-radius:6px; padding:1px 7px; font-size:11.5px; }

  /* ── Company H-1B lookup ──────────────────────────── */
  .lookup { border:1px solid var(--line); border-radius:var(--r-lg);
    background:var(--card); backdrop-filter:blur(14px); -webkit-backdrop-filter:blur(14px);
    padding:20px 22px; margin-bottom:30px; }
  .lookup h2 { font-family:'Space Grotesk',sans-serif; font-size:17px;
    font-weight:600; margin:0 0 3px; }
  .lookup p { color:var(--faint); font-size:13px; margin:0 0 14px; }
  .lookup input[type=search] { width:100%; }
  .co-results { margin-top:14px; display:grid; gap:10px; }
  .co-row { display:flex; flex-wrap:wrap; align-items:baseline; gap:6px 16px;
    padding:13px 16px; border-radius:var(--r-md); background:var(--glass);
    border:1px solid var(--line); }
  .co-row .cn { font-size:15px; font-weight:650; color:var(--ink); margin-right:auto; }
  .co-row .cn small { color:var(--faint); font-weight:500; font-size:12px; margin-left:6px; }
  .co-stat { font-size:13px; color:var(--muted); white-space:nowrap; }
  .co-stat b { color:var(--ink); font-weight:700; }
  .co-stat.sal b { color:var(--ok); }
  .co-none { color:var(--faint); font-style:italic; }
  .co-hint { color:var(--faint); font-size:12.5px; padding:6px 2px; }

  @media (max-width:640px) {
    .wrap { padding:30px 14px 60px; }
    .toolbar { top:8px; }
  }
</style>
</head>
<body>
<div class="glow"></div>
<div class="wrap">

  <div class="eyebrow">H-1B sponsor job board · updated __DATE__</div>
  <h1>Fresh SWE/DE/Infra internships, <span class="accent">every day</span></h1>
  <p class="sub">Software, data engineering &amp; infrastructure internships pulled from the
    public boards of verified H-1B sponsors — Greenhouse, Lever, Ashby, SmartRecruiters, Workable &amp; Workday. US-only.</p>
  <div class="stats" id="stats"></div>

  <div class="tracker-bar">
    <a class="btn-track" href="tracker.html">My application tracker &rarr;</a>
    <div class="quick-add">
      <input type="text" id="qaCompany" placeholder="Quick-add a company you applied to…" autocomplete="off">
      <button id="qaBtn">Add to tracker</button>
      <span class="qa-msg" id="qaMsg"></span>
    </div>
  </div>

  <section class="browse">
    <h2>Browse these employers directly</h2>
    <p>Big or scrape-blocked boards — open each one&rsquo;s software-engineer search and filter yourself.</p>
    <div class="pills">__PILLS__</div>
  </section>

  <section class="lookup" id="lookup">
    <h2>H-1B company lookup</h2>
    <p>Type any company to see its H-1B approvals and typical certified H-1B salary.
       Partial names and small typos work — the closest matches show up.</p>
    <input type="search" id="coq" placeholder="e.g. Google, Stripe, Precisely…" autocomplete="off">
    <div class="co-results" id="coResults"></div>
  </section>

  <div class="toolbar">
    <input type="search" id="q" placeholder="Search title, company, or location…" autocomplete="off">
    <span id="chips" style="display:contents"></span>
    <label class="tog"><input type="checkbox" id="gradOnly"> Internships only</label>
    <select id="sort">
      <option value="seen">Newest first</option>
      <option value="fit">Best fit</option>
      <option value="company">Company A–Z</option>
      <option value="title">Title A–Z</option>
    </select>
    <button class="chip" id="themeBtn" title="Toggle light/dark theme">&#9788;</button>
  </div>

  <div class="count" id="count"></div>
  <div class="grid" id="grid"></div>

  <footer>
    __COUNT__ roles · sourced from the public ATS boards of top H-1B sponsors ·
    refreshed daily by GitHub Actions. Click a card to open the original posting.
    &ldquo;First seen&rdquo; is the date this board first spotted the posting.
    Rebuild locally with <code>python -m src.digest.jobs_site</code>.
    · <a href="tracker.html" style="color:var(--sky)">My application tracker</a>
    <span style="color:var(--faint)">(private — stored only in your browser)</span>
  </footer>
</div>

<script>
const JOBS = __DATA__;
const SOURCES = [...new Set(JOBS.map(j => j.source))].sort();
let active = new Set(SOURCES);

const el = id => document.getElementById(id);
const grid = el('grid'), q = el('q'), gradOnly = el('gradOnly'),
      sortSel = el('sort'), countEl = el('count'), chips = el('chips');

// header stats
(() => {
  const nNew = JOBS.filter(j => j.is_new).length;
  const nGrad = JOBS.filter(j => j.new_grad).length;
  el('stats').innerHTML =
    `<span class="stat"><b>${JOBS.length}</b> open roles</span>` +
    (nNew ? `<span class="stat hot"><b>${nNew}</b> new today</span>` : '') +
    `<span class="stat"><b>${nGrad}</b> explicit internship</span>` +
    `<span class="stat"><b>${SOURCES.length}</b> sources</span>`;
})();

// source filter chips
SOURCES.forEach(s => {
  const c = document.createElement('span');
  c.className = 'chip on'; c.textContent = s;
  c.onclick = () => { c.classList.toggle('on');
    c.classList.contains('on') ? active.add(s) : active.delete(s); render(); };
  chips.appendChild(c);
});

const esc = s => (s||'').replace(/[&<>"]/g, m => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[m]));
// deterministic gradient per company
function monoStyle(name) {
  let h = 0; for (const ch of name) h = (h * 31 + ch.charCodeAt(0)) % 360;
  return `background:linear-gradient(135deg,hsl(${h},62%,52%),hsl(${(h+45)%360},62%,40%))`;
}
// résumé-fit chip (only for roles scored in a recent digest run)
function fitChip(j) {
  if (j.fit_score == null) return '';
  const cls = j.fit_score >= 80 ? 'b-fit-hi' : j.fit_score >= 60 ? 'b-fit-mid' : 'b-fit-lo';
  return `<span class="badge ${cls}" title="${esc(j.fit_reason||'')}">${j.fit_score} fit</span>`;
}

function render() {
  const term = q.value.trim().toLowerCase();
  const grad = gradOnly.checked;
  let rows = JOBS.filter(j =>
    active.has(j.source) &&
    (!grad || j.new_grad) &&
    (!term || (j.title+' '+j.company+' '+j.location).toLowerCase().includes(term)));

  const s = sortSel.value;
  rows.sort((a,b) => s === 'company' ? a.company.localeCompare(b.company)
    : s === 'title' ? a.title.localeCompare(b.title)
    : s === 'fit' ? (((b.fit_score ?? -1) - (a.fit_score ?? -1)) ||
                     (b.first_seen||'').localeCompare(a.first_seen||''))
    : (b.first_seen||'').localeCompare(a.first_seen||''));

  countEl.textContent = rows.length + ' role' + (rows.length!==1?'s':'') +
    (rows.length!==JOBS.length ? ' of ' + JOBS.length : '') +
    (s === 'fit' ? ' · ranked by résumé fit (LLM-scored where available, else keyword match)' : '');

  grid.innerHTML = rows.length ? rows.map(j => `
    <a class="card" href="${esc(j.url)}" target="_blank" rel="noopener">
      <div class="co">
        <div class="mono" style="${monoStyle(j.company)}">${esc((j.company.trim()[0]||'?').toUpperCase())}</div>
        <div class="co-name">${esc(j.company)}</div>
      </div>
      <div class="title">${esc(j.title)}</div>
      <div class="loc">${esc(j.location)}</div>
      <div class="meta">
        ${fitChip(j)}
        <span class="badge b-src">${esc(j.source)}</span>
        ${j.new_grad ? '<span class="badge b-grad">Internship</span>' : ''}
        ${j.is_new ? '<span class="badge b-new">New</span>' : ''}
        <span class="seen">${esc(j.first_seen)}</span>
      </div>
    </a>`).join('')
    : '<div class="empty">No roles match your filters.</div>';
}

// light/dark toggle — persists; ☀ shown in dark (click for light), ☾ in light
const themeBtn = el('themeBtn');
function syncThemeBtn() {
  themeBtn.textContent = document.documentElement.dataset.theme === 'light' ? '☾' : '☀';
}
themeBtn.onclick = () => {
  const t = document.documentElement.dataset.theme === 'light' ? 'dark' : 'light';
  document.documentElement.dataset.theme = t;
  localStorage.setItem('theme', t);
  syncThemeBtn();
};
syncThemeBtn();

q.oninput = render; gradOnly.onchange = render; sortSel.onchange = render;
render();

// ── Quick-add a company to the tracker (shared localStorage with tracker.html) ──
(() => {
  const KEY = 'tracker_apps_v1';
  const inp = el('qaCompany'), btn = el('qaBtn'), msg = el('qaMsg');
  const today = () => { const d = new Date(); return `${d.getMonth()+1}/${d.getDate()}/${d.getFullYear()}`; };
  function add(){
    const c = inp.value.trim();
    if (!c){ inp.focus(); return; }
    let apps = []; try { apps = JSON.parse(localStorage.getItem(KEY)) || []; } catch(e){}
    apps.push({ company:c, role:'', location:'', link:'', date:today(), note:'',
                coldEmail:'', phoneScreen:'', oa:'', round1:'', round2:'' });
    localStorage.setItem(KEY, JSON.stringify(apps));
    inp.value = '';
    msg.textContent = `Added ${c} — ${apps.length} in your tracker`;
    setTimeout(() => { msg.textContent = ''; }, 2800);
  }
  btn.onclick = add;
  inp.addEventListener('keydown', e => { if (e.key === 'Enter') add(); });
})();

// ── Company H-1B lookup (lazy-loads employers.json on first use) ──
(() => {
  const box = el('coq'), out = el('coResults');
  let DATA = null, loading = false;
  const SUF = /\\b(INC|LLC|LLP|LP|LTD|CORP|CORPORATION|CO|COMPANY|PC|PLLC|THE|USA|US|NA|NORTH AMERICA)\\b/g;
  const norm = s => (s||'').toUpperCase().replace(/[^A-Z0-9& ]/g,' ').replace(SUF,' ').replace(/\\s+/g,' ').trim();
  const money = n => '$' + Math.round(n).toLocaleString();
  const kk = n => '$' + Math.round(n/1000) + 'k';
  const bigrams = s => { const g = new Set(); for (let i=0;i<s.length-1;i++) g.add(s.slice(i,i+2)); return g; };
  function dice(a,b){ const A=bigrams(a),B=bigrams(b); if(!A.size||!B.size) return 0;
    let n=0; for(const x of A) if(B.has(x)) n++; return 2*n/(A.size+B.size); }

  async function load(){
    if (DATA || loading) return; loading = true;
    out.innerHTML = '<div class="co-hint">Loading company data…</div>';
    try {
      const r = await fetch('employers.json'); const j = await r.json();
      DATA = j.rows; for (const row of DATA) row.push(norm(row[0]));  // idx 8 = normalized name
    } catch(e) { out.innerHTML = '<div class="co-hint">Could not load company data.</div>'; loading=false; return; }
    loading = false; run();
  }

  function search(qn){
    const hits = [];
    for (const r of DATA){
      const nm = r[8]; let sc = 0;
      if (nm === qn) sc = 1000;
      else if (nm.startsWith(qn)) sc = 600 - nm.length*0.3;
      else if (nm.includes(qn)) sc = 400 - nm.indexOf(qn)*2 - nm.length*0.2;
      if (sc){ sc += Math.min(45, Math.log10(1 + r[2] + r[7]) * 16); hits.push([r, sc]); }  // prominence boost
    }
    if (hits.length < 8){                              // typo fallback: closest by name
      for (const r of DATA){ const nm = r[8];
        if (nm === qn || nm.includes(qn)) continue;
        const s = dice(qn, nm); if (s > 0.5) hits.push([r, s*300]);
      }
    }
    hits.sort((a,b) => b[1]-a[1] || (b[0][2]+b[0][7])-(a[0][2]+a[0][7]));
    return hits.slice(0, 12).map(h => h[0]);
  }

  function fmtRow(r){
    const [name,state,tot,nw,med,p25,p75,n] = r;
    const cases = tot>0
      ? `<span class="co-stat"><b>${tot.toLocaleString()}</b> H-1B approvals${nw?` · ${nw.toLocaleString()} new`:''}</span>`
      : '<span class="co-stat co-none">no USCIS case data</span>';
    const sal = med>0
      ? `<span class="co-stat sal">median <b>${money(med)}</b>${(p25&&p75)?` · ${kk(p25)}–${kk(p75)}`:''}${n?` · ${n.toLocaleString()} LCAs`:''}</span>`
      : '<span class="co-stat co-none">no wage data</span>';
    return `<div class="co-row"><span class="cn">${esc(name)}${state?` <small>${esc(state)}</small>`:''}</span>${cases}${sal}</div>`;
  }

  function run(){
    if (!DATA) return;
    const qn = norm(box.value.trim());
    if (qn.length < 2){ out.innerHTML = '<div class="co-hint">Type at least 2 letters.</div>'; return; }
    const res = search(qn);
    out.innerHTML = res.length ? res.map(fmtRow).join('')
      : '<div class="co-hint">No close matches — try fewer letters or a parent company name.</div>';
  }

  let t;
  box.addEventListener('input', () => { clearTimeout(t); t = setTimeout(() => DATA ? run() : load(), 140); });
  box.addEventListener('focus', load, { once:true });
})();
</script>
</body>
</html>
"""


def build(jobs: list[dict], generated: str) -> str:
    data = json.dumps(jobs, ensure_ascii=False).replace("</", "<\\/")
    return (_PAGE
            .replace("__COUNT__", str(len(jobs)))
            .replace("__DATE__", generated)
            .replace("__PILLS__", _browse_pills())
            .replace("__DATA__", data))


def main():
    ap = argparse.ArgumentParser(description="Build a static webpage of all current roles")
    ap.add_argument("--out", default=str(OUT_DEFAULT), help="output HTML path")
    ap.add_argument("--open", action="store_true", help="open the page in a browser after building")
    args = ap.parse_args()

    jobs = collect()
    html = build(jobs, dt.date.today().strftime("%B %-d, %Y"))
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    print(f"✅ Wrote {len(jobs)} roles to {out}  ({out.stat().st_size//1024} KB)")
    if args.open:
        webbrowser.open(out.resolve().as_uri())


if __name__ == "__main__":
    main()
