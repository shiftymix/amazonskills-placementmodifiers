"""
HTML report renderer — produces the interactive diff review page.
"""

from typing import Optional
from .optimizer import Recommendation, AccountConfig

PLACEMENT_LABELS = {
    "TOP_OF_SEARCH":        "Top of Search",
    "PRODUCT_PAGE":         "Product Page",
    "REST_OF_SEARCH":       "Rest of Search",
    "HOME_PAGE":            "Home Page",
    "SITE_AMAZON_BUSINESS": "Amazon Business",
}


def _acos(v: Optional[float]) -> str:
    return f"{v*100:.1f}%" if v is not None else "—"


def render_review_page(recs: list[Recommendation], config: AccountConfig) -> str:
    actionable  = [r for r in recs if not r.skip and r.delta_pp != 0.0]
    on_target   = [r for r in recs if not r.skip and r.delta_pp == 0.0]
    skipped     = [r for r in recs if r.skip and r.skip_reason != "in_range"]
    in_range    = [r for r in recs if r.skip and r.skip_reason == "in_range"]

    flagged_count = sum(1 for r in actionable if r.flagged)
    safe_count    = sum(1 for r in actionable if not r.flagged)

    rows_html = ""
    for r in sorted(actionable, key=lambda x: x.campaign_name):
        flag_cls = ' class="flagged"' if r.flagged else ''
        flag_icon = " ⚑" if r.flagged else ""
        delta_cls = "pos" if r.delta_pp > 0 else "neg"
        rows_html += f"""
        <tr{flag_cls}>
          <td><input type="checkbox" class="sel" data-id="{r.campaign_id}" data-flagged="{'1' if r.flagged else '0'}" {'checked' if not r.flagged else ''}></td>
          <td title="{r.campaign_name}">{r.campaign_name[:55]}{flag_icon}</td>
          <td>{PLACEMENT_LABELS.get(r.placement, r.placement)}</td>
          <td>{r.segment.upper()}</td>
          <td>{r.ad_type}</td>
          <td>{_acos(r.cur_acos)}</td>
          <td>{r.target_pct}</td>
          <td>{r.cur_modifier:.1f}%</td>
          <td>{r.new_modifier:.1f}%</td>
          <td class="{delta_cls}">{r.delta_pp:+.1f}pp</td>
        </tr>"""

    skip_rows = ""
    for r in skipped:
        skip_rows += f"<tr><td>{r.campaign_name[:55]}</td><td>{PLACEMENT_LABELS.get(r.placement, r.placement)}</td><td>{r.skip_reason}</td></tr>"

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Placement Optimizer — Review</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; margin: 0; padding: 20px; background: #f5f5f5; color: #333; }}
  h1 {{ font-size: 1.4em; margin-bottom: 4px; }}
  .meta {{ color: #666; font-size: 0.85em; margin-bottom: 20px; }}
  .stats {{ display: flex; gap: 16px; margin-bottom: 20px; }}
  .stat {{ background: white; border-radius: 8px; padding: 12px 20px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
  .stat .n {{ font-size: 1.8em; font-weight: bold; }}
  .stat .l {{ font-size: 0.8em; color: #888; }}
  table {{ border-collapse: collapse; width: 100%; background: white; border-radius: 8px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.1); font-size: 0.88em; }}
  th {{ background: #2c3e50; color: white; padding: 10px 12px; text-align: left; }}
  td {{ padding: 8px 12px; border-bottom: 1px solid #eee; }}
  tr:hover td {{ background: #f9f9f9; }}
  tr.flagged td {{ background: #fff8e1; }}
  .pos {{ color: #27ae60; font-weight: 600; }}
  .neg {{ color: #e74c3c; font-weight: 600; }}
  .actions {{ margin: 20px 0; display: flex; gap: 12px; align-items: center; }}
  button {{ padding: 10px 24px; border-radius: 6px; border: none; cursor: pointer; font-size: 1em; font-weight: 600; }}
  #btn-apply {{ background: #2ecc71; color: white; }}
  #btn-apply:hover {{ background: #27ae60; }}
  #btn-apply-flagged {{ background: #e67e22; color: white; }}
  #btn-apply-flagged:hover {{ background: #d35400; }}
  #btn-apply-flagged {{ display: {'block' if flagged_count > 0 else 'none'}; }}
  .flagged-note {{ color: #e67e22; font-size: 0.85em; }}
  details {{ margin-top: 20px; }}
  summary {{ cursor: pointer; color: #666; font-size: 0.9em; }}
  #result {{ margin-top: 16px; padding: 12px; background: #d4edda; border-radius: 6px; display: none; }}
</style>
</head>
<body>
<h1>Placement Optimizer — Review Changes</h1>
<div class="meta">Account: {config.name} &nbsp;|&nbsp; Profile: {config.profile_id}</div>

<div class="stats">
  <div class="stat"><div class="n">{len(actionable)}</div><div class="l">Adjustments</div></div>
  <div class="stat"><div class="n">{safe_count}</div><div class="l">Safe to apply</div></div>
  <div class="stat"><div class="n" style="color:#e67e22">{flagged_count}</div><div class="l">Flagged (high modifier)</div></div>
  <div class="stat"><div class="n">{len(in_range)}</div><div class="l">In range (no change)</div></div>
  <div class="stat"><div class="n">{len(skipped)}</div><div class="l">Skipped (low data)</div></div>
</div>

<table>
  <thead>
    <tr>
      <th style="width:30px"></th>
      <th>Campaign</th><th>Placement</th><th>Seg</th><th>Type</th>
      <th>ACOS</th><th>Target</th><th>Old %</th><th>New %</th><th>Δ</th>
    </tr>
  </thead>
  <tbody>{rows_html}</tbody>
</table>

<div class="actions">
  <button id="btn-apply" onclick="applySelected(false)">Apply Selected ({safe_count} safe)</button>
  <button id="btn-apply-flagged" onclick="applySelected(true)">Apply Including Flagged ({flagged_count} ⚑)</button>
  <span class="flagged-note">{"⚑ = modifier ≥ " + str(int(config.flag_threshold_pct)) + "% — review before applying" if flagged_count > 0 else ""}</span>
</div>
<div id="result"></div>

{f'''<details><summary>Skipped placements ({len(skipped)})</summary>
<table style="margin-top:8px">
  <thead><tr><th>Campaign</th><th>Placement</th><th>Reason</th></tr></thead>
  <tbody>{skip_rows}</tbody>
</table></details>''' if skipped else ''}

<script>
function getSelected(includeFlagged) {{
  const boxes = document.querySelectorAll('.sel:checked');
  const ids = [];
  boxes.forEach(b => {{
    if (includeFlagged || b.dataset.flagged !== '1') ids.push(b.dataset.id);
  }});
  return ids;
}}

function applySelected(includeFlagged) {{
  const ids = getSelected(includeFlagged);
  if (!ids.length) {{ alert('No campaigns selected.'); return; }}
  if (!confirm(`Apply changes to ${{ids.length}} campaigns?`)) return;

  fetch('/apply', {{
    method: 'POST',
    headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{campaign_ids: ids, include_flagged: includeFlagged}})
  }})
  .then(r => r.json())
  .then(d => {{
    if (d.redirect) window.location = d.redirect;
    else document.getElementById('result').style.display = 'block',
         document.getElementById('result').textContent = `Applied ${{d.applied}} changes.`;
  }});
}}
</script>
</body></html>"""


def render_applied_page(results: list[dict]) -> str:
    rows = ""
    for r in results:
        status = r.get("status", "unknown")
        cls = "pos" if status == "ok" else "neg"
        rows += f"<tr><td>{r.get('campaign_name', '')[:60]}</td><td>{r.get('placement', '')}</td><td>{r.get('old_modifier', '')}%</td><td>{r.get('new_modifier', '')}%</td><td class='{cls}'>{status}</td></tr>"

    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>Applied</title>
<style>
  body {{ font-family: -apple-system, sans-serif; margin: 20px; }}
  table {{ border-collapse: collapse; width: 100%; }}
  th, td {{ padding: 8px 12px; border-bottom: 1px solid #eee; text-align: left; }}
  th {{ background: #2c3e50; color: white; }}
  .pos {{ color: #27ae60; font-weight: 600; }}
  .neg {{ color: #e74c3c; font-weight: 600; }}
</style>
</head>
<body>
<h1>Changes Applied</h1>
<p>{len(results)} placement modifiers updated.</p>
<table>
  <thead><tr><th>Campaign</th><th>Placement</th><th>Old %</th><th>New %</th><th>Status</th></tr></thead>
  <tbody>{rows}</tbody>
</table>
</body></html>"""
