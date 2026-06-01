# app/viz/radar_html.py
from __future__ import annotations
import math
from typing import Dict, List, Tuple


def _clamp01(x: float) -> float:
    try:
        x = float(x)
    except Exception:
        return 0.0
    return max(0.0, min(1.0, x))


def _short(s: str, n: int = 28) -> str:
    s = (s or "").strip()
    return (s[: n - 1] + "…") if len(s) > n else s


def _radar_card_inner(labels: List[str], values: List[float], max_axes: int = 12) -> str:
    pairs: List[Tuple[str, float]] = [
        (labels[i], _clamp01(values[i]))
        for i in range(min(len(labels), len(values), max_axes))
    ]
    if not pairs:
        pairs = [("No data", 0.0)]

    labels2 = [_short(p[0]) for p in pairs]
    values2 = [p[1] for p in pairs]
    N = len(values2)

    cx, cy = 160, 160
    R = 120
    labelR = 145

    def pt(rmul: float, i: int) -> Tuple[float, float]:
        ang = math.radians(-90 + i * (360.0 / N))
        return (cx + R * rmul * math.cos(ang), cy + R * rmul * math.sin(ang))

    def pts_str(rmul: float) -> str:
        return " ".join([f"{pt(rmul, i)[0]:.1f},{pt(rmul, i)[1]:.1f}" for i in range(N)])

    grid = []
    for lvl in [0.2, 0.4, 0.6, 0.8, 1.0]:
        grid.append(
            f'<polygon points="{pts_str(lvl)}" fill="none" stroke="#e5e7eb" stroke-width="1" />'
        )

    axes = []
    for i in range(N):
        x0, y0 = cx, cy
        x1, y1 = pt(1.0, i)
        axes.append(
            f'<line x1="{x0}" y1="{y0}" x2="{x1:.1f}" y2="{y1:.1f}" stroke="#e5e7eb" stroke-width="1" />'
        )

        ang = math.radians(-90 + i * (360.0 / N))
        lx = cx + labelR * math.cos(ang)
        ly = cy + labelR * math.sin(ang)

        ca = math.cos(ang)
        anchor = "middle"
        if ca > 0.35:
            anchor = "start"
        elif ca < -0.35:
            anchor = "end"

        axes.append(
            f'<text x="{lx:.1f}" y="{ly:.1f}" font-size="10" fill="#111827" '
            f'text-anchor="{anchor}" dominant-baseline="middle">{labels2[i]}</text>'
        )

    value_points = []
    for i, v in enumerate(values2):
        x, y = pt(v, i)
        value_points.append(f"{x:.1f},{y:.1f}")
    value_poly = " ".join(value_points)

    # full table (not truncated), but labels shortened
    rows = "\n".join(
        [f"<tr><td>{labels2[i]}</td><td style='text-align:right'>{int(values2[i]*100)}%</td></tr>" for i in range(N)]
    )

    svg = f"""
<svg viewBox="0 0 320 340" width="100%" style="display:block;margin:auto;max-width:700px">
  <rect x="0" y="0" width="320" height="340" fill="white"/>
  {''.join(grid)}
  {''.join(axes)}
  <polygon points="{value_poly}" fill="rgba(59,130,246,0.18)" stroke="#3b82f6" stroke-width="2" />
  <circle cx="{cx}" cy="{cy}" r="2.5" fill="#111827" />
</svg>
"""
    return f"""
<div class="card">
  {svg}
  <table><tbody>{rows}</tbody></table>
</div>
"""


def build_radar_html(title: str, labels: List[str], values: List[float], max_axes: int = 12) -> str:
    """Your original single-radar HTML document."""
    inner = _radar_card_inner(labels, values, max_axes=max_axes)
    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<style>
  html, body {{ margin:0; padding:0; height:100%; font-family:system-ui,Segoe UI,Arial; background:#fff; }}
  .wrap {{ padding:12px; }}
  .title {{ font-weight:700; font-size:16px; margin-bottom:6px; }}
  .sub {{ font-size:12px; opacity:.75; margin-bottom:10px; }}
  .card {{ border:1px solid #e5e7eb; border-radius:12px; padding:12px; background:#fff; }}
  table {{ width:100%; border-collapse:collapse; font-size:12px; margin-top:10px; }}
  td {{ padding:6px 4px; border-top:1px solid #f1f5f9; }}
</style>
</head>
<body>
  <div class="wrap">
    <div class="title">{title}</div>
    <div class="sub">Scores normalisés (0 → 1)</div>
    {inner}
  </div>
</body>
</html>
"""


def build_radar_dashboard_html(
    title: str,
    views: Dict[str, Dict[str, object]],
    default_view: str = "modules",
    max_axes: int = 12,
) -> str:
    """
    views example:
    {
      "modules": {"label": "Modules", "labels": [...], "values": [...]},
      "MOD_1":    {"label": "KCs: Module 1", "labels": [...], "values": [...]},
      ...
    }
    """
    # render each view as a hidden block
    blocks = []
    options = []
    for vid, v in views.items():
        vlabel = str(v.get("label") or vid)
        labels = list(v.get("labels") or [])
        values = list(v.get("values") or [])
        inner = _radar_card_inner(labels, values, max_axes=max_axes)
        blocks.append(f'<div class="view" id="view-{vid}" style="display:none">{inner}</div>')
        options.append(f'<option value="{vid}">{vlabel}</option>')

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<style>
  html, body {{ margin:0; padding:0; height:100%; font-family:system-ui,Segoe UI,Arial; background:#fff; }}
  .wrap {{ padding:12px; }}
  .top {{ display:flex; gap:10px; align-items:center; justify-content:space-between; flex-wrap:wrap; }}
  .title {{ font-weight:700; font-size:16px; }}
  .sub {{ font-size:12px; opacity:.75; margin-top:2px; }}
  select {{ padding:8px 10px; border:1px solid #e5e7eb; border-radius:10px; font-size:12px; }}
  .card {{ border:1px solid #e5e7eb; border-radius:12px; padding:12px; background:#fff; }}
  table {{ width:100%; border-collapse:collapse; font-size:12px; margin-top:10px; }}
  td {{ padding:6px 4px; border-top:1px solid #f1f5f9; }}
</style>
</head>
<body>
  <div class="wrap">
    <div class="top">
      <div>
        <div class="title">{title}</div>
        <div class="sub">Choisir une vue : Modules ou KCs par module</div>
      </div>
      <select id="sel">
        {''.join(options)}
      </select>
    </div>

    <div style="height:10px"></div>

    {''.join(blocks)}
  </div>

<script>
(function() {{
  const sel = document.getElementById("sel");
  const views = Array.from(document.querySelectorAll(".view"));
  function show(id) {{
    views.forEach(v => v.style.display = (v.id === "view-" + id) ? "block" : "none");
  }}
  sel.value = {default_view!r};
  show(sel.value);
  sel.addEventListener("change", () => show(sel.value));
}})();
</script>
</body>
</html>
"""
