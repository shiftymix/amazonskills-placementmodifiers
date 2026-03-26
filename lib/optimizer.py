"""
Placement optimizer — pure computation, no API calls, no account config.

Formula:
  new_modifier = [(1 + cur/100) * (target_acos / cur_acos) - 1] * 100 * dampening
  clamped to [0, 900]

Zero-out rule:
  If cur_acos > zero_out_threshold AND cur_modifier <= zero_out_max:
    new_modifier = 0
"""

from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class PlacementPerf:
    """Performance data for a single campaign × placement."""
    campaign_id:   str
    campaign_name: str
    placement:     str          # v1 key: TOP_OF_SEARCH, PRODUCT_PAGE, etc.
    ad_type:       str          # "SP" or "SB"
    clicks:        int
    spend:         float
    sales:         float
    cur_modifier:  float        # current modifier %

    @property
    def acos(self) -> Optional[float]:
        if self.sales > 0:
            return self.spend / self.sales
        return None


@dataclass
class AccountConfig:
    """User-supplied per-account configuration."""
    profile_id:   str
    name:         str = "My Account"

    # ACOS target ranges (as decimals, e.g. 0.25 = 25%)
    nb_acos_low:   float = 0.20
    nb_acos_high:  float = 0.28
    brand_acos_low:  float = 0.10
    brand_acos_high: float = 0.15

    # Brand detection
    brand_patterns: list = field(default_factory=lambda: ["Branded", "Brand"])

    # Adjustment rules
    min_clicks:        int   = 20
    max_increase_pp:   float = 20.0
    dampening:         float = 0.50
    brand_dampening:   float = 0.65
    dampening_high_modifier: float = 0.80
    high_modifier_threshold: float = 20.0

    # Zero-out rule
    zero_out_acos_threshold: float = 0.50
    zero_out_max_modifier:   float = 20.0

    # Safety
    flag_threshold_pct: float = 50.0

    def is_brand(self, campaign_name: str) -> bool:
        n = campaign_name.lower()
        return any(p.lower() in n for p in self.brand_patterns)

    def acos_target(self, campaign_name: str) -> tuple[float, float]:
        """Return (low, high) ACOS target range for a campaign."""
        if self.is_brand(campaign_name):
            return self.brand_acos_low, self.brand_acos_high
        return self.nb_acos_low, self.nb_acos_high

    def calc_target_acos(self, campaign_name: str) -> float:
        """Return midpoint of the target ACOS range."""
        low, high = self.acos_target(campaign_name)
        return (low + high) / 2

    def get_dampening(self, campaign_name: str, cur_modifier: float, going_up: bool) -> float:
        is_brand = self.is_brand(campaign_name)
        base = self.brand_dampening if is_brand else self.dampening
        if going_up and cur_modifier >= self.high_modifier_threshold:
            return self.dampening_high_modifier
        return base


@dataclass
class Recommendation:
    """A single placement modifier recommendation."""
    campaign_id:   str
    campaign_name: str
    placement:     str
    ad_type:       str
    segment:       str          # "brand" or "nonbrand"
    cur_acos:      Optional[float]
    target_acos:   float
    cur_modifier:  float
    new_modifier:  float
    delta_pp:      float
    skip:          bool = False
    skip_reason:   str  = ""
    flagged:       bool = False
    # Performance data (passed through from PlacementPerf for UI display)
    clicks:        int   = 0
    spend:         float = 0.0
    sales:         float = 0.0

    @property
    def acos_pct(self) -> str:
        return f"{self.cur_acos*100:.1f}%" if self.cur_acos is not None else "n/a"

    @property
    def target_pct(self) -> str:
        return f"{self.target_acos*100:.1f}%"

    @property
    def in_range(self) -> bool:
        return self.skip and self.skip_reason == "in_range"


# ---------------------------------------------------------------------------
# Core formula
# ---------------------------------------------------------------------------

def compute_new_modifier(
    cur_modifier: float,
    cur_acos: float,
    target_acos: float,
    dampening: float,
    max_increase_pp: float,
) -> float:
    """
    Compute new modifier %.

    new = [(1 + cur/100) * (target / cur_acos) - 1] * 100 * dampening
    clamped to [0, 900]
    increase capped at max_increase_pp
    """
    raw = ((1 + cur_modifier / 100) * (target_acos / cur_acos) - 1) * 100
    delta = (raw - cur_modifier) * dampening

    # Cap increase
    if delta > max_increase_pp:
        delta = max_increase_pp

    new_mod = cur_modifier + delta
    return max(0.0, min(900.0, new_mod))


# ---------------------------------------------------------------------------
# Recommendation builder
# ---------------------------------------------------------------------------

def build_recommendations(
    placements: list[PlacementPerf],
    config: AccountConfig,
) -> list[Recommendation]:
    recs = []

    for p in placements:
        segment = "brand" if config.is_brand(p.campaign_name) else "nonbrand"
        acos_low, acos_high = config.acos_target(p.campaign_name)
        target_acos = config.calc_target_acos(p.campaign_name)

        perf_kwargs = dict(clicks=p.clicks, spend=p.spend, sales=p.sales)

        # Skip: not enough clicks
        if p.clicks < config.min_clicks:
            recs.append(Recommendation(
                campaign_id=p.campaign_id, campaign_name=p.campaign_name,
                placement=p.placement, ad_type=p.ad_type, segment=segment,
                cur_acos=p.acos, target_acos=target_acos,
                cur_modifier=p.cur_modifier, new_modifier=p.cur_modifier,
                delta_pp=0.0, skip=True, skip_reason=f"low_clicks ({p.clicks})",
                **perf_kwargs,
            ))
            continue

        # Skip: no sales data
        if p.acos is None:
            recs.append(Recommendation(
                campaign_id=p.campaign_id, campaign_name=p.campaign_name,
                placement=p.placement, ad_type=p.ad_type, segment=segment,
                cur_acos=None, target_acos=target_acos,
                cur_modifier=p.cur_modifier, new_modifier=p.cur_modifier,
                delta_pp=0.0, skip=True, skip_reason="no_sales",
                **perf_kwargs,
            ))
            continue

        cur_acos = p.acos

        # Zero-out rule
        if (cur_acos > config.zero_out_acos_threshold
                and p.cur_modifier <= config.zero_out_max_modifier):
            recs.append(Recommendation(
                campaign_id=p.campaign_id, campaign_name=p.campaign_name,
                placement=p.placement, ad_type=p.ad_type, segment=segment,
                cur_acos=cur_acos, target_acos=target_acos,
                cur_modifier=p.cur_modifier, new_modifier=0.0,
                delta_pp=-p.cur_modifier,
                flagged=p.cur_modifier >= config.flag_threshold_pct,
                **perf_kwargs,
            ))
            continue

        # In range — no change needed
        if acos_low <= cur_acos <= acos_high:
            recs.append(Recommendation(
                campaign_id=p.campaign_id, campaign_name=p.campaign_name,
                placement=p.placement, ad_type=p.ad_type, segment=segment,
                cur_acos=cur_acos, target_acos=target_acos,
                cur_modifier=p.cur_modifier, new_modifier=p.cur_modifier,
                delta_pp=0.0, skip=True, skip_reason="in_range",
                **perf_kwargs,
            ))
            continue

        # Compute recommendation
        going_up = cur_acos < target_acos
        damp = config.get_dampening(p.campaign_name, p.cur_modifier, going_up)

        new_mod = compute_new_modifier(
            cur_modifier=p.cur_modifier,
            cur_acos=cur_acos,
            target_acos=target_acos,
            dampening=damp,
            max_increase_pp=config.max_increase_pp,
        )
        new_mod = round(new_mod, 1)
        delta = round(new_mod - p.cur_modifier, 1)

        flagged = new_mod >= config.flag_threshold_pct

        recs.append(Recommendation(
            campaign_id=p.campaign_id, campaign_name=p.campaign_name,
            placement=p.placement, ad_type=p.ad_type, segment=segment,
            cur_acos=cur_acos, target_acos=target_acos,
            cur_modifier=p.cur_modifier, new_modifier=new_mod,
            delta_pp=delta, flagged=flagged,
            **perf_kwargs,
        ))

    return recs


# ---------------------------------------------------------------------------
# Diff table formatter (terminal)
# ---------------------------------------------------------------------------

def format_diff_table(recs: list[Recommendation], include_skipped: bool = False) -> str:
    """Format recommendations as a plain-text table for terminal output."""
    PLACEMENT_SHORT = {
        "TOP_OF_SEARCH":        "TOS",
        "PRODUCT_PAGE":         "PP",
        "REST_OF_SEARCH":       "ROS",
        "HOME_PAGE":            "HP",
        "SITE_AMAZON_BUSINESS": "B2B",
    }

    actionable = [r for r in recs if not r.skip and r.delta_pp != 0.0]
    skipped    = [r for r in recs if r.skip]
    on_target  = [r for r in recs if not r.skip and r.delta_pp == 0.0]

    lines = []
    lines.append(f"\n{'Campaign':<45} {'Plcmt':<6} {'Seg':<4} {'Type':<4} {'ACOS':>6} {'Tgt':>5} {'Old%':>5} {'New%':>5} {'Δ':>5}  {'Flag'}")
    lines.append("-" * 100)

    for r in sorted(actionable, key=lambda x: x.campaign_name):
        flag = "⚑" if r.flagged else ""
        name = r.campaign_name[:44]
        lines.append(
            f"{name:<45} {PLACEMENT_SHORT.get(r.placement, r.placement[:5]):<6} "
            f"{r.segment[:2].upper():<4} {r.ad_type:<4} "
            f"{r.acos_pct:>6} {r.target_pct:>5} "
            f"{r.cur_modifier:>5.1f} {r.new_modifier:>5.1f} "
            f"{r.delta_pp:>+5.1f}  {flag}"
        )

    lines.append(f"\n  {len(actionable)} adjustments  |  {len(on_target)} on target  |  {len(skipped)} skipped")

    if include_skipped and skipped:
        lines.append("\nSkipped:")
        for r in skipped:
            lines.append(f"  {r.campaign_name[:50]:<50} {r.placement:<20} {r.skip_reason}")

    return "\n".join(lines)
