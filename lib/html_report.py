"""
HTML report renderer — produces the interactive editable diff review page.

Features:
- Inline editable modifier inputs (type your own value before applying)
- Per-row note/reason text field (saved with overrides)
- Skip toggle per row (excluded from apply)
- Overrides auto-loaded from output/overrides.json on page open
- One-click save → one-click apply flow
- Flagged rows (high modifier) highlighted separately
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

def _currency(v: Optional[float]) -> str:
    return f"${v:,.0f}" if v else "—"

def _cpc(spend: float, clicks: int) -> str:
    return f"${spend/clicks:.2f}" if clicks else "—"


def render_review_page(
    recs: list[Recommendation],
    config: AccountConfig,
    overrides: dict = None,
) -> str:
    """
    Full interactive review page. overrides = {campaign_id|placement: {modifier_pct, skip, note}}
    loaded from output/overrides.json so user edits persist across sessions.
    """
    overrides = overrides or {}

    actionable  = [r for r in recs if not r.skip and r.delta_pp != 0.0]
    on_target   = [r for r in recs if not r.skip and r.delta_pp == 0.0]
    skipped     = [r for r in recs if r.skip and r.skip_reason != "in_range"]

    flagged_ct  = sum(1 for r in actionable if r.flagged)
    change_ct   = len(actionable)
    insuf_ct    = len(skipped)

    nb_mid   = (config.nb_acos_low + config.nb_acos_high) / 2 * 100
    br_mid   = (config.brand_acos_low + config.brand_acos_high) / 2 * 100

    # Build rows — all_rows includes actionable + on_target + skipped
    all_recs = sorted(recs, key=lambda r: r.campaign_name)

    rows_html = ""
    for r in all_recs:
        key = f"{r.campaign_id}|{r.placement}"
        ov  = overrides.get(key, {})

        # Override values from saved session
        ov_mod  = ov.get("modifier_pct")
        ov_skip = ov.get("skip", False)
        ov_note = ov.get("note", "")

        display_mod = ov_mod if ov_mod is not None else r.new_modifier
        is_skipped  = ov_skip

        if r.skip and r.skip_reason != "in_range":
            row_cls = "row-insuf"
        elif r.skip or r.delta_pp == 0.0:
            row_cls = "row-within-range"
        else:
            row_cls = "row-change"

        if r.flagged:
            row_cls += " row-flagged"
        if is_skipped:
            row_cls += " skipped-row"

        flag_icon  = '<span class="flag-icon" title="High modifier — review before applying">⚠</span>' if r.flagged else ""
        seg_cls    = "seg-brand" if r.segment == "brand" else "seg-nb"
        seg_label  = "Brand" if r.segment == "brand" else "NB"
        at_cls     = f"adtype-{r.ad_type.lower()}"
        acos_pct   = r.cur_acos * 100 if r.cur_acos is not None else None
        tgt_low    = config.brand_acos_low * 100 if r.segment == "brand" else config.nb_acos_low * 100
        tgt_high   = config.brand_acos_high * 100 if r.segment == "brand" else config.nb_acos_high * 100
        acos_cls   = ""
        if acos_pct is not None:
            if acos_pct > tgt_high:
                acos_cls = "acos-high"
            elif acos_pct < tgt_low:
                acos_cls = "acos-low"
            else:
                acos_cls = "acos-ok"

        reason_html = ""
        if r.skip and r.skip_reason == "low_data":
            reason_html = f'<span class="reason-insuf">{r.clicks} clicks (low data)</span>'
        elif r.skip and r.skip_reason == "in_range":
            reason_html = '<span class="reason-ok">✓ in range</span>'
        elif r.skip_reason == "zero_out":
            reason_html = '<span class="reason-badge reason-zeroout">zero-out</span>'
        elif not r.skip and r.delta_pp != 0.0:
            reason_html = '<span class="reason-badge reason-adj">adj</span>'

        full_name_escaped = r.campaign_name.replace('"', "&quot;")
        pl_label = PLACEMENT_LABELS.get(r.placement, r.placement)

        rows_html += f"""
        <tr class="{row_cls}" data-id="{r.campaign_id}" data-placement="{r.placement}">
          <td class="col-skip">
            <input type="checkbox" class="skip-chk" title="Skip this row" {'checked' if is_skipped else ''}>
          </td>
          <td class="campaign-name" title="{full_name_escaped}">{flag_icon}{r.campaign_name}</td>
          <td>{pl_label}</td>
          <td><span class="{at_cls}">{r.ad_type}</span></td>
          <td class="{seg_cls}">{seg_label}</td>
          <td class="num">{_currency(getattr(r,'spend',None))}</td>
          <td class="num">{_currency(getattr(r,'sales',None))}</td>
          <td class="num">{r.clicks:,}</td>
          <td class="num {acos_cls}">{_acos(r.cur_acos)}</td>
          <td class="num tgt-val">{tgt_low:.0f}–{tgt_high:.0f}%</td>
          <td class="num">{r.cur_modifier:.0f}%</td>
          <td class="num new-mod-cell">
            <input type="number" class="mod-input" min="0" max="999" step="1"
                   value="{display_mod:.0f}" data-original="{r.new_modifier:.0f}">
          </td>
          <td class="reason-cell">{reason_html}
            <input type="text" class="reason-input" placeholder="note…" value="{ov_note}">
          </td>
        </tr>"""

    flagged_alert = ""
    if flagged_ct:
        flagged_alert = f"""
        <div class="alert">
          <strong>⚠ {flagged_ct} row(s) suggest a modifier ≥ {int(config.flag_threshold_pct)}%.</strong>
          These are highlighted amber. Reduce the value, skip the row, or apply as-is — your call.
        </div>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Placement Review — {config.name}</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
         font-size: 13px; background: #0f1117; color: #e2e8f0; padding: 24px; }}
  h1   {{ font-size: 20px; font-weight: 600; margin-bottom: 4px; color: #f8fafc; }}
  h2   {{ font-size: 14px; font-weight: 600; margin: 24px 0 8px; color: #94a3b8;
          text-transform: uppercase; letter-spacing: .05em; }}
  .meta {{ display: flex; gap: 20px; flex-wrap: wrap; margin: 12px 0 20px;
           padding: 12px 16px; background: #1e293b; border-radius: 8px; }}
  .meta-item {{ display: flex; flex-direction: column; gap: 2px; }}
  .meta-item .label {{ font-size: 11px; color: #64748b; text-transform: uppercase; letter-spacing: .05em; }}
  .meta-item .value {{ font-size: 13px; font-weight: 600; color: #f1f5f9; }}
  .pill {{ display: inline-block; padding: 2px 8px; border-radius: 999px; font-size: 11px; font-weight: 600; }}
  .pill-change  {{ background: #1d4ed8; color: #bfdbfe; }}
  .pill-flagged {{ background: #92400e; color: #fde68a; }}
  .pill-insuf   {{ background: #1e293b; color: #64748b; }}

  .alert {{ background: #422006; border: 1px solid #92400e; border-radius: 8px;
            padding: 12px 16px; margin-bottom: 20px; color: #fde68a; line-height: 1.6; }}

  /* Toolbar */
  .toolbar {{ display: flex; align-items: center; gap: 12px; margin-bottom: 16px; flex-wrap: wrap; }}
  .btn {{ border: none; border-radius: 6px; padding: 9px 20px; font-size: 13px;
          font-weight: 600; cursor: pointer; transition: background .15s; }}
  .btn-save  {{ background: #1d4ed8; color: #fff; }}
  .btn-save:hover {{ background: #1e40af; }}
  .btn-apply {{ background: #16a34a; color: #fff; }}
  .btn-apply:hover {{ background: #15803d; }}
  .btn-reset {{ background: transparent; color: #94a3b8; border: 1px solid #334155; }}
  .btn-reset:hover {{ color: #f1f5f9; }}
  .btn-dismiss {{ background: transparent; color: #64748b; border: 1px solid #334155;
                  padding: 6px 14px; font-size: 12px; }}
  .btn-dismiss:hover {{ color: #f1f5f9; border-color: #64748b; }}
  .btn:disabled {{ background: #374151 !important; color: #6b7280 !important; cursor: default; }}
  #save-status {{ font-size: 13px; }}
  #save-status.ok    {{ color: #4ade80; }}
  #save-status.error {{ color: #f87171; }}

  /* Apply panel */
  #apply-panel {{ display: none; margin: 16px 0; padding: 16px; background: #0f1e3d;
                  border: 1px solid #1d4ed8; border-radius: 8px; }}
  .apply-panel-header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; }}
  .apply-panel-header h3 {{ font-size: 13px; font-weight: 600; color: #93c5fd; }}
  #apply-results {{ font-size: 12px; line-height: 1.8; font-family: monospace; white-space: pre-wrap; }}
  .apply-ok  {{ color: #4ade80; }}
  .apply-err {{ color: #f87171; }}

  /* Table */
  .table-wrap {{ overflow-x: auto; border-radius: 8px; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 12px; }}
  thead th {{ background: #1e293b; color: #94a3b8; font-weight: 600; padding: 8px 10px;
              text-align: left; white-space: nowrap; border-bottom: 1px solid #334155; }}
  thead th.num {{ text-align: right; }}
  thead th.new-mod-hdr {{ background: #172554; color: #93c5fd; }}

  tbody tr {{ border-bottom: 1px solid #1a2235; transition: background .1s; }}
  tbody tr.row-change {{ background: #0f1117; }}
  tbody tr.row-change:hover {{ background: #1a2235; }}
  tbody tr.row-within-range td {{ color: #4b5563; }}
  tbody tr.row-within-range td.campaign-name {{ color: #64748b; }}
  tbody tr.row-insuf td {{ color: #374151; }}
  tbody tr.row-insuf td.campaign-name {{ color: #4b5563; }}
  tbody tr.row-insuf .mod-input {{ background: #0d1520; color: #4b5563; border-color: #1e293b; }}
  tbody tr.row-flagged {{ background: #1c1107 !important; }}
  tbody tr.row-flagged:hover {{ background: #2d1a0a !important; }}
  tr.skipped-row {{ opacity: .4; }}
  tr.skipped-row td.campaign-name {{ text-decoration: line-through; color: #475569; }}

  td {{ padding: 6px 10px; vertical-align: middle; }}
  td.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
  td.campaign-name {{ max-width: 280px; white-space: nowrap; overflow: hidden;
                      text-overflow: ellipsis; color: #cbd5e1; cursor: default; }}
  td.col-skip {{ width: 28px; text-align: center; }}
  .skip-chk {{ width: 14px; height: 14px; cursor: pointer; accent-color: #f87171; }}
  .acos-high {{ color: #f87171; font-weight: 600; }}
  .acos-low  {{ color: #4ade80; font-weight: 600; }}
  .acos-ok   {{ color: #94a3b8; }}
  td.tgt-val  {{ color: #64748b; font-size: 11px; }}
  .seg-brand {{ color: #a78bfa; font-weight: 600; }}
  .seg-nb    {{ color: #34d399; font-weight: 600; }}
  .adtype-sp {{ display: inline-block; font-size: 10px; font-weight: 700; padding: 1px 5px;
               border-radius: 3px; background: #1d4ed8; color: #bfdbfe; }}
  .adtype-sb {{ display: inline-block; font-size: 10px; font-weight: 700; padding: 1px 5px;
               border-radius: 3px; background: #7c3aed; color: #ede9fe; }}
  .flag-icon {{ color: #f59e0b; margin-right: 4px; }}
  td.new-mod-cell {{ background: #0f1e3d; }}
  .mod-input {{ width: 60px; background: #1e3a5f; border: 1px solid #334155; border-radius: 4px;
               color: #f1f5f9; font-size: 13px; font-weight: 700; padding: 4px 6px;
               text-align: right; -moz-appearance: textfield; }}
  .mod-input:focus {{ outline: none; border-color: #3b82f6; box-shadow: 0 0 0 2px rgba(59,130,246,.3); }}
  .mod-input::-webkit-outer-spin-button, .mod-input::-webkit-inner-spin-button {{ -webkit-appearance: none; }}
  .mod-input.modified {{ border-color: #f59e0b; color: #fbbf24; background: #1c1107; }}
  td.reason-cell {{ min-width: 160px; }}
  .reason-input {{ width: 100%; background: #1e293b; border: 1px solid #1e293b; border-radius: 4px;
                   color: #94a3b8; font-size: 12px; padding: 3px 6px; margin-top: 3px; }}
  .reason-input:focus {{ outline: none; border-color: #334155; color: #e2e8f0; background: #0f1117; }}
  .reason-input.has-value {{ border-color: #334155; color: #cbd5e1; }}
  .reason-insuf {{ color: #374151; font-size: 11px; font-style: italic; }}
  .reason-ok    {{ color: #166534; font-size: 11px; }}
  .reason-badge {{ display: inline-block; font-size: 10px; font-weight: 700; padding: 1px 5px;
                   border-radius: 3px; margin-right: 4px; color: #fff; }}
  .reason-adj     {{ background: #2563eb; }}
  .reason-zeroout {{ background: #dc2626; }}

  .legend {{ display: flex; gap: 16px; margin-bottom: 12px; font-size: 11px; color: #64748b; flex-wrap: wrap; }}
  .legend-item {{ display: flex; align-items: center; gap: 6px; }}
  .legend-swatch {{ width: 12px; height: 12px; border-radius: 2px; }}
  .swatch-change {{ background: #1d4ed8; }}
  .swatch-range  {{ background: #166534; }}
  .swatch-insuf  {{ background: #1e293b; }}

  .footer {{ margin-top: 32px; font-size: 11px; color: #475569;
             border-top: 1px solid #1e293b; padding-top: 12px; }}
</style>
</head>
<body>

<h1>Placement Review — {config.name}</h1>

<div class="meta">
  <div class="meta-item">
    <span class="label">Profile</span>
    <span class="value">{config.profile_id}</span>
  </div>
  <div class="meta-item">
    <span class="label">NB Target</span>
    <span class="value">{config.nb_acos_low*100:.0f}–{config.nb_acos_high*100:.0f}%
      <span style="color:#64748b;font-size:11px">mid {nb_mid:.0f}%</span></span>
  </div>
  <div class="meta-item">
    <span class="label">Brand Target</span>
    <span class="value">{config.brand_acos_low*100:.0f}–{config.brand_acos_high*100:.0f}%
      <span style="color:#64748b;font-size:11px">mid {br_mid:.0f}%</span></span>
  </div>
  <div class="meta-item">
    <span class="label">Rows</span>
    <span class="value">
      <span class="pill pill-change">{change_ct} changes</span>
      {"<span class='pill pill-flagged'>" + str(flagged_ct) + " flagged</span>" if flagged_ct else ""}
      <span class="pill pill-insuf">{insuf_ct} low-data</span>
    </span>
  </div>
</div>

{flagged_alert}

<div class="toolbar">
  <button class="btn btn-save" id="save-btn">1 — Save Edits</button>
  <button class="btn btn-apply" id="apply-btn">2 — Apply to Amazon</button>
  <button class="btn btn-reset" id="reset-btn">Reset</button>
  <span id="save-status"></span>
</div>

<div id="apply-panel">
  <div class="apply-panel-header">
    <h3>Apply Results</h3>
    <button class="btn btn-dismiss" id="dismiss-btn">✕ Dismiss</button>
  </div>
  <div id="apply-results"></div>
</div>

<div class="legend">
  <span class="legend-item"><span class="legend-swatch swatch-change"></span> Change recommended</span>
  <span class="legend-item"><span class="legend-swatch swatch-range"></span> Within ACOS range</span>
  <span class="legend-item"><span class="legend-swatch swatch-insuf"></span> Low data (skipped)</span>
  <span class="legend-item" style="color:#94a3b8">✏ New Mod% column is editable — type your own value before applying</span>
</div>

<div class="table-wrap">
<table id="review-table">
  <thead>
    <tr>
      <th class="col-skip" title="Skip row">✕</th>
      <th>Campaign</th>
      <th>Placement</th>
      <th>Type</th>
      <th>Seg</th>
      <th class="num">Spend</th>
      <th class="num">Sales</th>
      <th class="num">Clicks</th>
      <th class="num">ACOS%</th>
      <th class="num">Target</th>
      <th class="num">Cur Mod%</th>
      <th class="num new-mod-hdr">New Mod% ✏</th>
      <th>Note</th>
    </tr>
  </thead>
  <tbody>
    {rows_html}
  </tbody>
</table>
</div>

<div class="footer">
  {config.name} &nbsp;|&nbsp; {len(recs)} total rows ({change_ct} changes, {insuf_ct} low-data)
  &nbsp;|&nbsp; Notes and edits saved to <code>output/overrides.json</code>
</div>

<script>
(function() {{
  // --- Change tracking ---
  document.querySelectorAll('.mod-input').forEach(input => {{
    const orig = parseFloat(input.dataset.original);
    input.addEventListener('input', () => {{
      input.classList.toggle('modified', parseFloat(input.value) !== orig);
    }});
  }});
  document.querySelectorAll('.reason-input').forEach(input => {{
    input.addEventListener('input', () => {{
      input.classList.toggle('has-value', input.value.trim().length > 0);
    }});
  }});
  document.querySelectorAll('.skip-chk').forEach(chk => {{
    chk.addEventListener('change', () => {{
      chk.closest('tr').classList.toggle('skipped-row', chk.checked);
    }});
  }});

  // --- Collect overrides ---
  function collectOverrides() {{
    const overrides = {{}};
    document.querySelectorAll('#review-table tbody tr').forEach(row => {{
      const skip     = row.querySelector('.skip-chk').checked;
      const modInput = row.querySelector('.mod-input');
      const note     = row.querySelector('.reason-input').value.trim();
      const orig     = parseFloat(modInput.dataset.original);
      const val      = parseFloat(modInput.value);
      const key      = row.dataset.id + '|' + row.dataset.placement;
      if (skip || val !== orig || note) {{
        overrides[key] = {{
          modifier_pct: val,
          skip:         skip,
          note:         note || null,
        }};
      }}
    }});
    return overrides;
  }}

  // --- Collect selected campaign IDs for apply ---
  function collectSelected() {{
    const ids = [];
    document.querySelectorAll('#review-table tbody tr').forEach(row => {{
      if (!row.querySelector('.skip-chk').checked) {{
        ids.push(row.dataset.id);
      }}
    }});
    return ids;
  }}

  // --- Reset ---
  document.getElementById('reset-btn').addEventListener('click', () => {{
    document.querySelectorAll('.mod-input').forEach(i => {{
      i.value = i.dataset.original;
      i.classList.remove('modified');
    }});
    document.querySelectorAll('.reason-input').forEach(i => {{
      i.value = ''; i.classList.remove('has-value');
    }});
    document.querySelectorAll('.skip-chk').forEach(c => {{
      c.checked = false; c.closest('tr').classList.remove('skipped-row');
    }});
    document.getElementById('save-status').textContent = '';
    document.getElementById('save-status').className = '';
  }});

  // --- Save overrides ---
  document.getElementById('save-btn').addEventListener('click', async () => {{
    const btn    = document.getElementById('save-btn');
    const status = document.getElementById('save-status');
    btn.disabled = true; btn.textContent = 'Saving…';
    status.textContent = ''; status.className = '';
    try {{
      const resp = await fetch('/api/save', {{
        method: 'POST',
        headers: {{'Content-Type': 'application/json'}},
        body: JSON.stringify({{ overrides: collectOverrides() }})
      }});
      const result = await resp.json();
      if (result.ok) {{
        const parts = [];
        if (result.noted)   parts.push(result.noted + ' noted');
        if (result.skipped) parts.push(result.skipped + ' skipped');
        status.textContent = '✓ Saved' + (parts.length ? ' — ' + parts.join(' · ') : '');
        status.className = 'ok';
      }} else {{
        status.textContent = '✗ Save failed';
        status.className = 'error';
      }}
    }} catch(e) {{
      status.textContent = '✗ ' + e.message;
      status.className = 'error';
    }}
    btn.disabled = false; btn.textContent = '1 — Save Edits';
  }});

  // --- Apply to Amazon ---
  document.getElementById('apply-btn').addEventListener('click', async () => {{
    const btn    = document.getElementById('apply-btn');
    const panel  = document.getElementById('apply-panel');
    const output = document.getElementById('apply-results');
    if (!confirm('Push changes to Amazon Ads API?')) return;
    btn.disabled = true; btn.textContent = 'Applying…';
    panel.style.display = 'block';
    output.innerHTML = '<span style="color:#94a3b8">Pushing to Amazon Ads API…</span>';
    try {{
      const resp = await fetch('/apply', {{
        method: 'POST',
        headers: {{'Content-Type': 'application/json'}},
        body: JSON.stringify({{ campaign_ids: collectSelected(), include_flagged: false }})
      }});
      const result = await resp.json();
      if (result.redirect) {{
        window.location = result.redirect;
      }} else {{
        output.innerHTML = '<span class="apply-ok">✓ Done</span>';
      }}
    }} catch(e) {{
      output.innerHTML = '<span class="apply-err">✗ ' + e.message + '</span>';
    }}
    btn.disabled = false; btn.textContent = '2 — Apply to Amazon';
  }});

  // --- Dismiss apply panel ---
  document.getElementById('dismiss-btn').addEventListener('click', () => {{
    document.getElementById('apply-panel').style.display = 'none';
  }});
}})();
</script>
</body></html>"""


def render_applied_page(results: list[dict]) -> str:
    rows = ""
    ok = err = 0
    for r in results:
        status = r.get("status", "unknown")
        cls = "apply-ok" if status in ("ok", "dry_run") else "apply-err"
        if status == "ok":
            ok += 1
        elif status != "dry_run":
            err += 1
        rows += f"<tr><td>{r.get('campaign_id','')}</td><td class='{cls}'>{status}</td></tr>"

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Applied</title>
<style>
  body {{ font-family:-apple-system,sans-serif; background:#0f1117; color:#e2e8f0;
          margin: 0; padding: 24px; }}
  h1 {{ font-size: 18px; margin-bottom: 8px; }}
  table {{ border-collapse: collapse; font-size: 13px; }}
  td {{ padding: 6px 14px; border-bottom: 1px solid #1a2235; }}
  .apply-ok  {{ color: #4ade80; font-weight: 600; }}
  .apply-err {{ color: #f87171; font-weight: 600; }}
  a {{ color: #60a5fa; }}
</style></head>
<body>
<h1>Changes Applied</h1>
<p style="color:#94a3b8;margin-bottom:16px">{ok} succeeded &nbsp;·&nbsp; {err} errors</p>
<table><tbody>{rows}</tbody></table>
<p style="margin-top:20px"><a href="/">← Back to review</a></p>
</body></html>"""
