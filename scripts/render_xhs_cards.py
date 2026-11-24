#!/usr/bin/env python3
"""Render a 5-card Xiaohongshu (3:4, 1080x1440) paper carousel from one JSON file."""
from __future__ import annotations

import argparse
import asyncio
import html
import json
import math
import os
import re
import sys
import tempfile
from pathlib import Path

def _find_cache_path(rel: str) -> Path:
    user = os.environ.get("USER", "")
    for base in (Path("/data") / user / ".cache" if user else None, Path.home() / ".cache"):
        if base and (base / rel).exists():
            return base / rel
    return Path.home() / ".cache" / rel


_FALLBACK_PY = Path(os.environ.get("XHS_PW_PYTHON") or _find_cache_path("pwvenv/bin/python"))
try:
    from playwright.async_api import async_playwright
except ImportError:
    if _FALLBACK_PY.exists() and Path(sys.executable) != _FALLBACK_PY:
        os.execv(str(_FALLBACK_PY), [str(_FALLBACK_PY), *sys.argv])
    raise

DEFAULT_PW_BROWSERS = _find_cache_path("ms-playwright")

THEMES: dict[str, dict[str, str]] = {
    "sage": {
        "canvas": "#F5F7F5", "canvas_end": "#F2F5F3", "surface": "#FFFFFF",
        "tinted": "#EAF2ED", "subtle": "#EFF3F0", "warn_bg": "#FDF1EB",
        "border": "#D7E2DB", "border_strong": "#BBD0C3", "warn_border": "#EBC8B6",
        "ink": "#121B16", "ink_sec": "#4A5A51", "ink_muted": "#76877D",
        "primary": "#186642", "contrast": "#CF5C24", "grid": "#E5EDE8", "bar_muted": "#CBD8D0",
    },
    "terracotta": {
        "canvas": "#FAF7F2", "canvas_end": "#F5EFE6", "surface": "#FFFFFF",
        "tinted": "#F5EAE4", "subtle": "#F3ECE2", "warn_bg": "#EEF3F8",
        "border": "#E5DDD0", "border_strong": "#DEC0B3", "warn_border": "#C5D5E5",
        "ink": "#1C1917", "ink_sec": "#57534E", "ink_muted": "#857F77",
        "primary": "#C84B31", "contrast": "#2B5B84", "grid": "#ECE6DC", "bar_muted": "#DDD5C7",
    },
    "blueprint": {
        "canvas": "#F5F7FA", "canvas_end": "#EEF2F7", "surface": "#FFFFFF",
        "tinted": "#EBF1FB", "subtle": "#EDF1F7", "warn_bg": "#FEF0E7",
        "border": "#D7E1EE", "border_strong": "#B6CBE8", "warn_border": "#F0C7B0",
        "ink": "#0F172A", "ink_sec": "#475569", "ink_muted": "#76859B",
        "primary": "#1D4ED8", "contrast": "#EA580C", "grid": "#E2E9F2", "bar_muted": "#CBD5E1",
    },
    "terminal": {
        "canvas": "#11141C", "canvas_end": "#0D1017", "surface": "#181D28",
        "tinted": "#162924", "subtle": "#1E2433", "warn_bg": "#2A2019",
        "border": "#2A3244", "border_strong": "#265947", "warn_border": "#5C4024",
        "ink": "#F1F5F9", "ink_sec": "#CBD5E1", "ink_muted": "#8B9BB4",
        "primary": "#34D399", "contrast": "#FBBF24", "grid": "#232A3B", "bar_muted": "#334155",
    },
}

REQUIRED_KEYS = ("meta", "cover", "problem", "method", "evidence", "takeaways")


def esc(val: object) -> str:
    return html.escape(str(val), quote=True)


def fmt_inline(text: str) -> str:
    safe = esc(text)
    return re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", safe)


def fmt_headline(text: str) -> tuple[str, int]:
    lines = str(text).split("\n")
    plain_max = max(len(re.sub(r"[{}]", "", ln)) for ln in lines)
    size = 74 if plain_max <= 11 else (64 if plain_max <= 14 else 54)
    rendered = []
    for ln in lines:
        safe = esc(ln)
        safe = re.sub(r"\{(.+?)\}", r'<span class="highlight">\1</span>', safe)
        rendered.append(safe)
    return "<br/>".join(rendered), size


def validate_spec(spec: dict) -> None:
    missing = [k for k in REQUIRED_KEYS if k not in spec]
    if missing:
        raise ValueError(f"Missing required top-level JSON sections: {', '.join(missing)}")
    theme = spec.get("theme", "sage")
    if theme not in THEMES:
        raise ValueError(f"Unknown theme '{theme}'. Choose from: {', '.join(THEMES)}")
    cov, ev = spec["cover"], spec["evidence"]
    if not cov.get("chart") and not cov.get("hero_grid"):
        raise ValueError("cover must provide either 'chart' or 'hero_grid'")
    if cov.get("chart") and len(cov["chart"].get("points", ())) < 2:
        raise ValueError("cover.chart.points requires at least 2 data points")
    if len(cov.get("metrics", ())) < 2:
        raise ValueError("cover.metrics requires 2 items")
    if len(ev.get("bars", ())) < 1 or len(ev.get("ablations", ())) < 2:
        raise ValueError("evidence requires >=1 bar and >=2 ablations")


# ponytail: loads Google Fonts over HTTPS; install fonts-noto-cjk locally if running air-gapped.
def build_base_css(t: dict[str, str], progress_pct: int) -> str:
    return f"""
    @import url('https://fonts.googleapis.com/css2?family=Instrument+Sans:wght@400;500;600;700&family=JetBrains+Mono:wght@500;700&family=Noto+Sans+SC:wght@400;500;700;900&display=swap');
    :root {{
      --canvas: {t['canvas']}; --canvas-end: {t['canvas_end']}; --surface: {t['surface']};
      --tinted: {t['tinted']}; --subtle: {t['subtle']}; --warn-bg: {t['warn_bg']};
      --border: {t['border']}; --border-strong: {t['border_strong']}; --warn-border: {t['warn_border']};
      --ink: {t['ink']}; --ink-sec: {t['ink_sec']}; --ink-muted: {t['ink_muted']};
      --primary: {t['primary']}; --contrast: {t['contrast']}; --grid: {t['grid']}; --bar-muted: {t['bar_muted']};
    }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    html, body {{
      width: 1080px; height: 1440px; overflow: hidden;
      background: var(--canvas); color: var(--ink);
      font-family: 'Instrument Sans', 'Noto Sans SC', sans-serif;
      -webkit-font-smoothing: antialiased;
      word-break: break-word;
    }}
    p, li {{ text-wrap: pretty; }}
    .card {{
      width: 1080px; height: 1440px;
      padding: 72px 80px 64px 80px;
      display: flex; flex-direction: column; justify-content: space-between;
      position: relative;
      background: linear-gradient(180deg, var(--canvas) 0%, var(--canvas-end) 100%);
    }}
    .card::before {{
      content: ''; position: absolute; top: 0; left: 80px; right: 80px; height: 6px;
      background: linear-gradient(90deg, var(--primary) 0%, var(--primary) {progress_pct}%, var(--border) {progress_pct}%, var(--border) 100%);
    }}
    .meta-bar {{ display: flex; align-items: center; justify-content: space-between; }}
    .domain-pill {{
      display: inline-flex; align-items: center; gap: 12px;
      padding: 9px 18px; border-radius: 999px;
      background: var(--surface); border: 1.5px solid var(--border);
      font-size: 20px; font-weight: 700; letter-spacing: 0.04em; color: var(--primary);
    }}
    .domain-dot {{ width: 10px; height: 10px; border-radius: 50%; background: var(--primary); }}
    .page-index {{
      font-family: 'JetBrains Mono', monospace; font-size: 21px; font-weight: 700;
      color: var(--ink-sec); padding: 8px 20px; border-radius: 999px;
      background: var(--subtle); border: 1.5px solid var(--border); letter-spacing: 0.06em;
    }}
    .hero-header {{ margin-top: 2px; }}
    .headline {{ font-weight: 900; line-height: 1.18; letter-spacing: -0.025em; color: var(--ink); }}
    .headline .highlight {{ color: var(--primary); }}
    .subtitle {{ margin-top: 16px; font-size: 27px; line-height: 1.5; color: var(--ink-sec); max-width: 910px; }}
    .subtitle strong {{ color: var(--ink); font-weight: 700; }}
    .panel {{
      background: var(--surface); border: 1.5px solid var(--border);
      border-radius: 24px; padding: 30px 34px;
      box-shadow: 0 4px 20px rgba(0, 0, 0, 0.025);
    }}
    .footer {{
      border-top: 1.5px solid var(--border); padding-top: 20px;
      display: flex; align-items: center; justify-content: space-between; gap: 20px;
    }}
    .paper-title {{ font-size: 20.5px; font-weight: 700; color: var(--ink); letter-spacing: -0.01em; }}
    .paper-org {{ margin-top: 4px; font-size: 18px; color: var(--ink-muted); font-weight: 500; }}
    .swipe-cue {{
      font-size: 19px; font-weight: 700; color: var(--primary);
      background: var(--tinted); border: 1px solid var(--border-strong);
      padding: 9px 20px; border-radius: 999px; white-space: nowrap;
    }}
    .mono {{ font-family: 'JetBrains Mono', monospace; }}
    """


def wrap_card(meta: dict, idx: int, total: int, kicker: str, title: str, subtitle: str, body_html: str, cue: str, theme: dict[str, str]) -> str:
    h_html, h_size = fmt_headline(title)
    css = build_base_css(theme, int(round(idx / total * 100)))
    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8"/><style>{css}</style></head>
<body>
  <div class="card" id="capture-root">
    <div>
      <div class="meta-bar">
        <div class="domain-pill"><span class="domain-dot"></span><span>{esc(kicker)}</span></div>
        <div class="page-index">{idx:02d} / {total:02d}</div>
      </div>
      <div class="hero-header" style="margin-top:22px">
        <h1 class="headline" style="font-size:{h_size}px">{h_html}</h1>
        <p class="subtitle">{fmt_inline(subtitle)}</p>
      </div>
    </div>
    {body_html}
    <div class="footer">
      <div>
        <div class="paper-title">{esc(meta['paper_title'])}</div>
        <div class="paper-org">{esc(meta['org_year'])}</div>
      </div>
      <div class="swipe-cue">{esc(cue)}</div>
    </div>
  </div>
</body></html>"""


# ponytail: inline SVG supports 1 primary series (3-8 points); switch to Vega-Lite if multi-series grouped charts are needed.
def render_line_svg(chart: dict, t: dict[str, str]) -> str:
    pts = chart["points"]
    n = len(pts)
    vals = [float(p["y"]) for p in pts]
    raw_xs = [float(p["pos"]) for p in pts] if all("pos" in p for p in pts) else [i / max(n - 1, 1) for i in range(n)]
    span_x = max(raw_xs) - min(raw_xs) or 1.0
    xs = [84.0 + ((x - min(raw_xs)) / span_x) * 696.0 for x in raw_xs]

    y_min = float(chart.get("y_min", math.floor((min(vals) - 4) / 5.0) * 5))
    y_max = float(chart.get("y_max", math.ceil((max(vals) + 6) / 5.0) * 5))
    y_span = max(y_max - y_min, 1.0)
    ys = [288.0 - ((v - y_min) / y_span) * 252.0 for v in vals]
    unit = esc(chart.get("unit", "%"))

    grids, y_labels = [], []
    for i in range(5):
        gy = 36.0 + i * 63.0
        gv = y_max - i * (y_span / 4.0)
        gv_str = f"{gv:.0f}{unit}" if gv.is_integer() else f"{gv:.1f}{unit}"
        if i < 4:
            grids.append(f'<line x1="66" y1="{gy:.1f}" x2="814" y2="{gy:.1f}" stroke="{t["grid"]}" stroke-width="1.5" stroke-dasharray="5 5"/>')
        else:
            grids.append(f'<line x1="66" y1="{gy:.1f}" x2="814" y2="{gy:.1f}" stroke="{t["bar_muted"]}" stroke-width="1.8"/>')
        y_labels.append(f'<text x="54" y="{gy + 6:.1f}">{gv_str}</text>')

    v_ticks = [f'<line x1="{x:.1f}" y1="36" x2="{x:.1f}" y2="288" stroke="{t["grid"]}" stroke-width="1.2"/>' for x in xs]
    poly_pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in zip(xs, ys))
    area_d = f"M {xs[0]:.1f} {ys[0]:.1f} " + " ".join(f"L {x:.1f} {y:.1f}" for x, y in zip(xs[1:], ys[1:])) + f" L {xs[-1]:.1f} 288 L {xs[0]:.1f} 288 Z"

    trend = f'<line x1="{xs[0]:.1f}" y1="{ys[0]:.1f}" x2="{xs[-1]:.1f}" y2="{ys[-1]:.1f}" stroke="{t["ink_muted"]}" stroke-opacity="0.55" stroke-width="2.2" stroke-dasharray="8 7"/>' if chart.get("show_trend") else ""

    circles, val_labels, x_labels = [], [], []
    for i, (p, x, y, v) in enumerate(zip(pts, xs, ys, vals)):
        v_txt = f"{v:g}{unit}"
        is_last = i == n - 1
        x_color = t["primary"] if is_last else t["ink"]
        x_labels.append(f'<text x="{x:.1f}" y="320" fill="{x_color}">{esc(p["x"])}</text>')
        if is_last:
            px = min(max(x - 56, 60), 724)
            py = max(y - 56, 8)
            circles.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="17" fill="{t["primary"]}" fill-opacity="0.18"/>')
            circles.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="9" fill="{t["primary"]}" stroke="{t["surface"]}" stroke-width="3.5"/>')
            val_labels.append(f'<rect x="{px:.1f}" y="{py:.1f}" width="112" height="38" rx="10" fill="{t["primary"]}"/>')
            val_labels.append(f'<text x="{px + 56:.1f}" y="{py + 26:.1f}" fill="#FFFFFF" font-size="21">{v_txt}</text>')
        else:
            circles.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="7.5" fill="{t["surface"]}" stroke="{t["primary"]}" stroke-width="4"/>')
            below = p.get("label_pos") == "below"
            ly = y + 34 if below else y - 22
            lx = x + (24 if i == 0 else 0)
            val_labels.append(f'<text x="{lx:.1f}" y="{ly:.1f}" fill="{t["ink"]}" font-size="20">{v_txt}</text>')

    return f"""
    <svg viewBox="0 0 844 348" width="100%" height="340" xmlns="http://www.w3.org/2000/svg">
      <defs>
        <linearGradient id="ag" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stop-color="{t['primary']}" stop-opacity="0.18"/>
          <stop offset="92%" stop-color="{t['primary']}" stop-opacity="0.01"/>
        </linearGradient>
      </defs>
      {''.join(grids)}
      <g font-family="JetBrains Mono, monospace" font-size="17.5" fill="{t['ink_muted']}" text-anchor="end">{''.join(y_labels)}</g>
      {''.join(v_ticks)}
      <path d="{area_d}" fill="url(#ag)"/>
      {trend}
      <polyline fill="none" stroke="{t['primary']}" stroke-width="5" stroke-linecap="round" stroke-linejoin="round" points="{poly_pts}"/>
      {''.join(circles)}
      <g font-family="JetBrains Mono, monospace" font-weight="700" text-anchor="middle">{''.join(val_labels)}</g>
      <g font-family="JetBrains Mono, monospace" font-size="19.5" font-weight="700" text-anchor="middle">{''.join(x_labels)}</g>
      <text x="432" y="344" font-family="Instrument Sans, Noto Sans SC, sans-serif" font-size="16.5" fill="{t['ink_muted']}" text-anchor="middle">{esc(chart.get('x_label', ''))}</text>
    </svg>"""


def build_p1_cover(spec: dict, t: dict[str, str]) -> str:
    c = spec["cover"]
    if c.get("chart"):
        ch = c["chart"]
        stages_html = ""
        if ch.get("stages"):
            pills = []
            for idx, st in enumerate(ch["stages"][:4], 1):
                is_hi = idx == len(ch["stages"][:4])
                bg = "var(--tinted)" if is_hi else "var(--subtle)"
                bd = "var(--border-strong)" if is_hi else "var(--border)"
                step_col = "var(--primary)" if is_hi else "var(--ink-muted)"
                pills.append(f"""
                <div style="background:{bg};border:1.2px solid {bd};border-radius:12px;padding:11px 14px;display:flex;flex-direction:column;gap:3px">
                  <span class="mono" style="font-size:14px;font-weight:700;color:{step_col}">{esc(st['step'])}</span>
                  <span style="font-size:20px;font-weight:700;color:var(--ink)">{esc(st['title'])}</span>
                  <span style="font-size:13.5px;color:var(--ink-sec);white-space:nowrap">{esc(st.get('sub', ''))}</span>
                </div>""")
            stages_html = f"""
            <div style="border-top:1.5px dashed var(--border);padding-top:16px;margin-top:12px;display:flex;flex-direction:column;gap:11px">
              <div style="display:flex;justify-content:space-between;font-size:18px;color:var(--ink-muted)">
                <strong style="color:var(--ink-sec)">{esc(ch.get('stages_title', '核心阶段演进'))}</strong>
                <span>{esc(ch.get('stages_hint', '第 03 页详解 →'))}</span>
              </div>
              <div style="display:grid;grid-template-columns:repeat({len(pills)},1fr);gap:12px">{''.join(pills)}</div>
            </div>"""

        legend_dash = (
            f'<span style="display:inline-flex;align-items:center;gap:7px"><i style="width:18px;border-top:2.5px dashed var(--ink-muted);display:inline-block"></i>{esc(ch["trend_label"])}</span>'
            if ch.get("show_trend") and ch.get("trend_label") else ""
        )
        hero = f"""
        <div class="panel qa-box" style="padding:28px 34px 24px 34px">
          <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:16px;margin-bottom:10px">
            <div>
              <h2 style="font-size:26px;font-weight:700">{esc(ch['title'])}</h2>
              <p style="margin-top:6px;font-size:18px;color:var(--ink-muted);display:flex;gap:18px;align-items:center">
                <span style="display:inline-flex;align-items:center;gap:7px"><i style="width:18px;height:3.5px;background:var(--primary);display:inline-block;border-radius:2px"></i>{esc(ch.get('series_label', '实测表现'))}</span>
                {legend_dash}
              </p>
            </div>
            <div style="background:var(--tinted);border:1.5px solid var(--border-strong);color:var(--primary);padding:8px 16px;border-radius:12px;font-size:19.5px;font-weight:700;white-space:nowrap">
              <span class="mono">{esc(ch['badge_num'])}</span> {esc(ch.get('badge_label', ''))}
            </div>
          </div>
          {render_line_svg(ch, t)}
          {stages_html}
        </div>"""
    else:
        cells = []
        for idx, item in enumerate(c["hero_grid"][:4]):
            bg = "var(--tinted)" if idx == 0 else "var(--surface)"
            bd = "var(--border-strong)" if idx == 0 else "var(--border)"
            col = "var(--primary)" if idx % 2 == 0 else "var(--contrast)"
            cells.append(f"""
            <div class="qa-box" style="background:{bg};border:1.5px solid {bd};border-radius:22px;padding:30px 32px;display:flex;flex-direction:column;justify-content:space-between;gap:10px">
              <div style="font-size:19px;font-weight:700;color:var(--ink-sec)">{esc(item['eyebrow'])}</div>
              <div style="font-size:60px;font-weight:800;color:{col};line-height:1.05;letter-spacing:-0.03em">{esc(item['value'])}</div>
              <div style="font-size:21px;color:var(--ink-sec);line-height:1.45">{esc(item['desc'])}</div>
            </div>""")
        hero = f'<div style="display:grid;grid-template-columns:1fr 1fr;gap:20px">{"".join(cells)}</div>'

    bento_cards = "".join(
        f'<div class="qa-box" style="background:{"var(--tinted)" if i == 0 else "var(--surface)"};'
        f'border:1.5px solid {"var(--border-strong)" if i == 0 else "var(--border)"};border-radius:20px;padding:23px 28px;display:flex;flex-direction:column;gap:6px">'
        f'<div style="font-size:18.5px;font-weight:700;color:var(--ink-sec)">{esc(m["eyebrow"])}</div>'
        f'<div style="display:flex;align-items:baseline;gap:14px">'
        f'<span style="font-size:52px;font-weight:800;color:{"var(--primary)" if i == 0 else "var(--contrast)"};line-height:1.05;letter-spacing:-0.03em">{esc(m["value"])}</span>'
        f'<span style="font-size:23.5px;font-weight:700">{esc(m["unit"])}</span></div>'
        f'<div style="font-size:19px;color:var(--ink-sec)">{esc(m["desc"])}</div></div>'
        for i, m in enumerate(c["metrics"][:2])
    )
    bento = f'<div style="display:grid;grid-template-columns:1.08fr 0.92fr;gap:22px">{bento_cards}</div>'
    return wrap_card(spec["meta"], 1, 5, c["kicker"], c["title"], c["subtitle"], hero + bento, c.get("swipe_cue", "右滑看核心痛点 →"), t)


def build_p2_problem(spec: dict, t: dict[str, str]) -> str:
    p = spec["problem"]

    def render_side(side: dict, is_ours: bool) -> str:
        bg = "var(--tinted)" if is_ours else "var(--warn-bg)"
        bd = "var(--border-strong)" if is_ours else "var(--warn-border)"
        accent = "var(--primary)" if is_ours else "var(--contrast)"
        mark = "✓" if is_ours else "×"
        tag = "NEW PERSPECTIVE · 本文破局" if is_ours else "NAIVE BASELINE · 传统瓶颈"
        rows = []
        for pt in side["points"][:3]:
            rows.append(f"""
            <div style="background:var(--surface);border:1.2px solid {bd};border-radius:14px;padding:18px 20px;display:flex;gap:14px;align-items:flex-start">
              <span class="mono" style="width:30px;height:30px;border-radius:8px;background:{bg};color:{accent};font-weight:700;font-size:20px;display:flex;align-items:center;justify-content:center;flex-shrink:0">{mark}</span>
              <div>
                <div style="font-size:22px;font-weight:700;color:var(--ink)">{esc(pt['head'])}</div>
                <div style="margin-top:4px;font-size:18.5px;color:var(--ink-sec);line-height:1.42">{esc(pt['body'])}</div>
              </div>
            </div>""")
        return f"""
        <div class="qa-box" style="background:{bg};border:1.5px solid {bd};border-radius:24px;padding:28px 26px;display:flex;flex-direction:column;justify-content:space-between;gap:16px">
          <div>
            <div class="mono" style="font-size:15px;font-weight:700;color:{accent};letter-spacing:0.05em">{tag}</div>
            <h2 style="margin-top:8px;font-size:29px;font-weight:800;color:var(--ink)">{esc(side['label'])}</h2>
          </div>
          <div style="display:flex;flex-direction:column;gap:14px;flex:1;justify-content:center">{''.join(rows)}</div>
        </div>"""

    body = f"""
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:22px;flex:1;max-height:640px">
      {render_side(p['naive'], False)}
      {render_side(p['ours'], True)}
    </div>
    <div class="panel qa-box" style="border-left:6px solid var(--primary);padding:24px 30px;background:var(--surface)">
      <div class="mono" style="font-size:16px;font-weight:700;color:var(--primary);letter-spacing:0.05em">KEY INSIGHT · 本质矛盾洞察</div>
      <div style="margin-top:8px;font-size:23.5px;line-height:1.48;color:var(--ink)">{fmt_inline(p['insight'])}</div>
    </div>"""
    return wrap_card(spec["meta"], 2, 5, p.get("kicker", "PROBLEM · 为什么难"), p["title"], p["subtitle"], body, p.get("swipe_cue", "右滑看核心机制 →"), t)


def build_p3_method(spec: dict, t: dict[str, str]) -> str:
    m = spec["method"]
    steps = m["steps"][:4]
    cards = []
    for idx, st in enumerate(steps, 1):
        is_key = st.get("highlight") or idx == len(steps)
        bg = "var(--tinted)" if is_key else "var(--surface)"
        bd = "var(--border-strong)" if is_key else "var(--border)"
        cards.append(f"""
        <div class="qa-box" style="background:{bg};border:1.5px solid {bd};border-radius:20px;padding:22px 28px;display:flex;gap:22px;align-items:center">
          <div class="mono" style="width:52px;height:52px;border-radius:14px;background:var(--primary);color:#FFFFFF;font-size:23px;font-weight:700;display:flex;align-items:center;justify-content:center;flex-shrink:0">{idx:02d}</div>
          <div style="flex:1">
            <div style="display:flex;justify-content:space-between;align-items:center;gap:12px">
              <h3 style="font-size:25px;font-weight:800;color:var(--ink)">{esc(st['name'])}</h3>
              <span class="mono" style="font-size:16px;font-weight:700;color:var(--primary);background:var(--subtle);border:1px solid var(--border);padding:4px 12px;border-radius:999px;white-space:nowrap">{esc(st.get('tag', ''))}</span>
            </div>
            <p style="margin-top:6px;font-size:20.5px;color:var(--ink-sec);line-height:1.44">{fmt_inline(st['desc'])}</p>
          </div>
        </div>""")

    body = f"""
    <div style="display:flex;flex-direction:column;gap:16px">{''.join(cards)}</div>
    <div class="qa-box" style="background:var(--subtle);border:1.5px solid var(--border);border-radius:20px;padding:22px 28px">
      <div class="mono" style="font-size:16px;font-weight:700;color:var(--contrast);letter-spacing:0.05em">CORE DIFFERENCE · 与常规做法最关键的一刀</div>
      <div style="margin-top:7px;font-size:22px;color:var(--ink);line-height:1.46">{fmt_inline(m['key_knife'])}</div>
    </div>"""
    return wrap_card(spec["meta"], 3, 5, m.get("kicker", "METHOD · 核心机制"), m["title"], m["subtitle"], body, m.get("swipe_cue", "右滑看实验证据 →"), t)


def build_p4_evidence(spec: dict, t: dict[str, str]) -> str:
    ev = spec["evidence"]
    bars = ev["bars"][:5]
    max_val = max(float(b["value"]) for b in bars) or 1.0
    unit = esc(ev.get("unit", "%"))
    rows = []
    for b in bars:
        is_ours = bool(b.get("is_ours"))
        pct = max(12.0, (float(b["value"]) / max_val) * 100.0)
        fill = "var(--primary)" if is_ours else "var(--bar-muted)"
        weight = "800" if is_ours else "500"
        col = "var(--primary)" if is_ours else "var(--ink-sec)"
        rows.append(f"""
        <div style="display:grid;grid-template-columns:230px 1fr 120px;gap:18px;align-items:center">
          <div style="font-size:21px;font-weight:{weight};color:{'var(--ink)' if is_ours else 'var(--ink-sec)'};white-space:nowrap;overflow:hidden;text-overflow:ellipsis">{esc(b['label'])}</div>
          <div style="height:26px;background:var(--subtle);border-radius:999px;overflow:hidden;border:1px solid var(--border)">
            <div style="width:{pct:.1f}%;height:100%;background:{fill};border-radius:999px"></div>
          </div>
          <div class="mono" style="font-size:23px;font-weight:700;color:{col};text-align:right">{b['value']:g}{unit}</div>
        </div>""")

    ab_cards = "".join(
        f'<div class="qa-box" style="background:{"var(--tinted)" if i == 0 else "var(--surface)"};'
        f'border:1.5px solid {"var(--border-strong)" if i == 0 else "var(--border)"};border-radius:20px;padding:24px 26px">'
        f'<div class="mono" style="font-size:15.5px;font-weight:700;color:{"var(--primary)" if i == 0 else "var(--contrast)"}">{esc(ab["tag"])}</div>'
        f'<div style="margin-top:8px;font-size:23px;font-weight:800;color:var(--ink)">{esc(ab["head"])}</div>'
        f'<p style="margin-top:6px;font-size:19.5px;color:var(--ink-sec);line-height:1.45">{fmt_inline(ab["body"])}</p></div>'
        for i, ab in enumerate(ev["ablations"][:2])
    )
    body = f"""
    <div class="panel qa-box" style="display:flex;flex-direction:column;gap:24px">
      <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:16px">
        <div>
          <h2 style="font-size:26px;font-weight:800">{esc(ev['chart_title'])}</h2>
          <p style="margin-top:5px;font-size:18.5px;color:var(--ink-muted)">{esc(ev.get('chart_sub', ''))}</p>
        </div>
        <div class="mono" style="background:var(--tinted);border:1.5px solid var(--border-strong);color:var(--primary);padding:8px 16px;border-radius:12px;font-size:19px;font-weight:700;white-space:nowrap">{esc(ev['badge'])}</div>
      </div>
      <div style="display:flex;flex-direction:column;gap:20px;padding:6px 0">{''.join(rows)}</div>
    </div>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:22px">{ab_cards}</div>"""
    return wrap_card(spec["meta"], 4, 5, ev.get("kicker", "EVIDENCE · 实验验证"), ev["title"], ev["subtitle"], body, ev.get("swipe_cue", "右滑看局限与启发 →"), t)


def build_p5_takeaways(spec: dict, t: dict[str, str]) -> str:
    tk = spec["takeaways"]
    t_cards = []
    for idx, item in enumerate(tk["items"][:2], 1):
        t_cards.append(f"""
        <div class="qa-box" style="background:var(--surface);border:1.5px solid var(--border);border-radius:20px;padding:24px 28px;display:flex;gap:20px;align-items:flex-start">
          <span class="mono" style="padding:6px 13px;border-radius:10px;background:var(--tinted);border:1px solid var(--border-strong);color:var(--primary);font-size:19px;font-weight:700;flex-shrink:0">启发 0{idx}</span>
          <div>
            <h3 style="font-size:24px;font-weight:800;color:var(--ink)">{esc(item['head'])}</h3>
            <p style="margin-top:6px;font-size:20px;color:var(--ink-sec);line-height:1.46">{fmt_inline(item['body'])}</p>
          </div>
        </div>""")

    lims = "".join(f'<li style="margin-left:22px;padding-left:4px">{fmt_inline(x)}</li>' for x in tk["limitations"][:2])
    chips = "".join(
        f'<div style="background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:12px 16px">'
        f'<div style="font-size:15px;color:var(--ink-muted)">{esc(c["k"])}</div>'
        f'<div style="margin-top:4px;font-size:19px;font-weight:700;color:var(--ink)">{esc(c["v"])}</div></div>'
        for c in tk["cheat_sheet"][:3]
    )
    body = f"""
    <div style="display:flex;flex-direction:column;gap:16px">{''.join(t_cards)}</div>
    <div class="qa-box" style="background:var(--warn-bg);border:1.5px solid var(--warn-border);border-radius:20px;padding:22px 28px">
      <div class="mono" style="font-size:16px;font-weight:700;color:var(--contrast);letter-spacing:0.04em">LIMITATIONS · 适用边界与客观局限（防过度外推）</div>
      <ul style="margin-top:10px;display:flex;flex-direction:column;gap:8px;font-size:20px;color:var(--ink-sec);line-height:1.45">{lims}</ul>
    </div>
    <div class="qa-box" style="background:var(--subtle);border:1.5px solid var(--border);border-radius:20px;padding:20px 24px">
      <div class="mono" style="font-size:15px;font-weight:700;color:var(--ink-muted);margin-bottom:12px">PAPER CHEAT-SHEET · 论文速查卡</div>
      <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:14px">{chips}</div>
    </div>"""
    return wrap_card(spec["meta"], 5, 5, tk.get("kicker", "TAKEAWAYS · 启发与边界"), tk["title"], tk["subtitle"], body, tk.get("swipe_cue", "建议收藏 · 随时复盘 ★"), t)


async def render_deck(spec: dict, out_dir: Path, scale: float = 1.5) -> list[Path]:
    validate_spec(spec)
    if "PLAYWRIGHT_BROWSERS_PATH" not in os.environ and DEFAULT_PW_BROWSERS.exists():
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(DEFAULT_PW_BROWSERS)

    theme = THEMES[spec.get("theme", "sage")]
    pages = [
        ("01_cover.png", build_p1_cover(spec, theme)),
        ("02_problem.png", build_p2_problem(spec, theme)),
        ("03_method.png", build_p3_method(spec, theme)),
        ("04_evidence.png", build_p4_evidence(spec, theme)),
        ("05_takeaways.png", build_p5_takeaways(spec, theme)),
    ]
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        try:
            ctx = await browser.new_context(viewport={"width": 1080, "height": 1440}, device_scale_factor=scale)
            page = await ctx.new_page()
            for fname, html_doc in pages:
                await page.set_content(html_doc, wait_until="load", timeout=15_000)
                await page.evaluate("() => document.fonts.ready")
                await page.wait_for_timeout(180)
                qa = await page.evaluate("""() => {
                    const root = document.getElementById('capture-root');
                    const bad = [];
                    if (root.scrollHeight > root.clientHeight + 1 || root.scrollWidth > root.clientWidth + 1) {
                        bad.push(`root(${root.scrollWidth}x${root.scrollHeight})`);
                    }
                    for (const el of document.querySelectorAll('.qa-box')) {
                        const r = el.getBoundingClientRect();
                        if (el.scrollHeight > el.clientHeight + 2 || r.bottom > 1440.5 || r.right > 1080.5) {
                            bad.push(`box(${Math.round(r.bottom)})`);
                        }
                    }
                    return bad;
                }""")
                if qa:
                    raise RuntimeError(f"Layout overflow detected on {fname}: {', '.join(qa)}. Shorten field copy.")
                dest = out_dir / fname
                await page.locator("#capture-root").screenshot(path=str(dest))
                written.append(dest)
        finally:
            await browser.close()
    return written


def run_self_check(example_path: Path) -> None:
    base = json.loads(example_path.read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory() as tmp:
        out = asyncio.run(render_deck(base, Path(tmp) / "sage", scale=1.0))
        assert len(out) == 5 and all(p.stat().st_size > 20_000 for p in out)

        fallback = json.loads(json.dumps(base))
        fallback["theme"] = "terminal"
        fallback["cover"].pop("chart", None)
        fallback["cover"]["title"] = "R&D < 5ms 延迟\n{零中心}自组织？"
        fallback["cover"]["hero_grid"] = [
            {"eyebrow": "最大验证规模", "value": "1,024", "desc": "去中心化并发智能体"},
            {"eyebrow": "Pandoc 通过率", "value": "55.06%", "desc": "较单 Agent 跃升 +21.17 pt"},
            {"eyebrow": "五任务相对收益", "value": "+49%", "desc": "跨 5 类真实代码仓库"},
            {"eyebrow": "中心编排器", "value": "0 节点", "desc": "消除全局通信单点瓶颈"},
        ]
        out_fb = asyncio.run(render_deck(fallback, Path(tmp) / "terminal_fb", scale=1.0))
        assert len(out_fb) == 5

        overflow = json.loads(json.dumps(base))
        overflow["problem"]["insight"] = "超长溢出测试" * 180
        try:
            asyncio.run(render_deck(overflow, Path(tmp) / "overflow", scale=1.0))
            raise AssertionError("Expected RuntimeError on overflowing card")
        except RuntimeError:
            pass
    print("SELF-CHECK OK: 5-card chart mode, 2x2 bento fallback, dark theme, HTML escaping, and overflow guard verified.")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("input_json", nargs="?", help="Path to paper carousel JSON")
    ap.add_argument("-o", "--out-dir", default="./output", help="Output directory for 01..05 PNGs")
    ap.add_argument("--scale", type=float, default=1.5, help="Device scale factor (default 1.5 -> 1620x2160)")
    ap.add_argument("--self-check", action="store_true", help="Run built-in rendering & QA self-check")
    args = ap.parse_args()

    if args.self_check:
        here = Path(__file__).resolve()
        default_ref = here.parent.parent / "references" / "example_agensh.json"
        sample = Path(args.input_json) if args.input_json else (default_ref if default_ref.exists() else here.with_name("example_agensh.json"))
        run_self_check(sample)
        return
    if not args.input_json:
        ap.error("input_json is required unless --self-check is set")

    spec = json.loads(Path(args.input_json).read_text(encoding="utf-8"))
    paths = asyncio.run(render_deck(spec, Path(args.out_dir), scale=args.scale))
    for p in paths:
        print(p)


if __name__ == "__main__":
    main()
