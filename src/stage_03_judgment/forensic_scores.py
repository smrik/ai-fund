"""
Deterministic forensic accounting scores — no LLM involved.

Provides:
    compute_beneish_m_score   — Beneish (1999) M-Score
    compute_altman_z_score    — Altman non-manufacturing Z'-Score
    compute_forensic_signals  — Combined wrapper with forensic_flag
"""
from __future__ import annotations

from typing import Optional


# ---------------------------------------------------------------------------
# Beneish M-Score
# ---------------------------------------------------------------------------

# Coefficients from Beneish (1999)
_M_COEF = {
    "DSRI":  0.920,
    "GMI":   0.528,
    "AQI":   0.404,
    "SGI":   0.892,
    "DEPI":  0.115,
    "SGAI": -0.172,
    "TATA":  4.679,
    "LVGI": -0.327,
}
_M_INTERCEPT = -4.84
_M_THRESHOLD = -1.78   # > -1.78 → likely manipulator
_M_GREY_LOW  = -2.50   # [-2.50, -1.78] → grey zone


def compute_beneish_m_score(hist: dict) -> dict:
    """
    Compute the Beneish M-Score from get_historical_financials() output.

    Parameters
    ----------
    hist : dict
        Keys: revenue, gross_profit, net_income, total_assets, capex, da, cffo
        Each is a list ordered newest-first (in millions).

    Returns
    -------
    dict with keys: m_score, zone, components, available_components,
                    total_components, interpretation, available, error
    """
    try:
        rev    = hist.get("revenue", [])
        gp     = hist.get("gross_profit", [])
        ni     = hist.get("net_income", [])
        ta     = hist.get("total_assets", [])
        capex  = hist.get("capex", [])   # absolute value
        da     = hist.get("da", [])
        cffo   = hist.get("cffo", [])

        # Need at least 2 years for most ratios
        if len(rev) < 2 or len(ta) < 2:
            return {
                "m_score": None,
                "zone": "unavailable",
                "components": {},
                "available_components": 0,
                "total_components": 8,
                "interpretation": "Insufficient history (need ≥2 years)",
                "available": False,
                "error": "Insufficient history",
            }

        def _safe(lst, idx):
            """Return lst[idx] if it exists and is non-zero, else None."""
            if lst and len(lst) > idx:
                v = lst[idx]
                if v is not None:
                    try:
                        return float(v)
                    except (TypeError, ValueError):
                        pass
            return None

        # Current (t=0) and prior (t=1) year values
        rev_t   = _safe(rev, 0);    rev_p   = _safe(rev, 1)
        gp_t    = _safe(gp, 0);     gp_p    = _safe(gp, 1)
        ni_t    = _safe(ni, 0)
        ta_t    = _safe(ta, 0);     ta_p    = _safe(ta, 1)
        capex_t = _safe(capex, 0);  capex_p = _safe(capex, 1)
        da_t    = _safe(da, 0);     da_p    = _safe(da, 1)
        cffo_t  = _safe(cffo, 0)

        components: dict[str, Optional[float]] = {}

        # DSRI — Days Sales Receivables Index
        # AR not in hist; mark unavailable
        components["DSRI"] = None

        # GMI — Gross Margin Index
        # GMI = ((Rev_p - COGS_p)/Rev_p) / ((Rev_t - COGS_t)/Rev_t)
        # COGS = Revenue - GrossProfit  →  GM = GP / Rev
        gmi: Optional[float] = None
        if (rev_t and rev_t != 0 and gp_t is not None
                and rev_p and rev_p != 0 and gp_p is not None):
            gm_t = gp_t / rev_t
            gm_p = gp_p / rev_p
            if gm_t != 0:
                gmi = gm_p / gm_t
        components["GMI"] = gmi

        # AQI — Asset Quality Index — requires CA and PPE; not in hist → None
        components["AQI"] = None

        # SGI — Sales Growth Index
        sgi: Optional[float] = None
        if rev_t is not None and rev_p and rev_p != 0:
            sgi = rev_t / rev_p
        components["SGI"] = sgi

        # DEPI — Depreciation Index
        # DEPI = (DA_p/(DA_p + capex_p)) / (DA_t/(DA_t + capex_t))
        depi: Optional[float] = None
        if (da_t is not None and capex_t is not None
                and da_p is not None and capex_p is not None):
            denom_t = da_t + capex_t
            denom_p = da_p + capex_p
            if denom_t != 0 and denom_p != 0:
                dep_t = da_t / denom_t
                dep_p = da_p / denom_p
                if dep_t != 0:
                    depi = dep_p / dep_t
        components["DEPI"] = depi

        # SGAI — SGA Index — SGA not in hist → None
        components["SGAI"] = None

        # LVGI — Leverage Index — balance sheet items not in hist → None
        components["LVGI"] = None

        # TATA — Total Accruals to Total Assets
        # TATA = (NetIncome - CFFO) / TotalAssets
        tata: Optional[float] = None
        if ni_t is not None and cffo_t is not None and ta_t and ta_t != 0:
            tata = (ni_t - cffo_t) / ta_t
        components["TATA"] = tata

        # Build M-Score using available components (missing → coefficient × 0)
        available_count = sum(1 for v in components.values() if v is not None)

        m_score: Optional[float] = None
        if available_count >= 2:  # Need at least GMI, SGI, TATA to be meaningful
            score = _M_INTERCEPT
            for name, coef in _M_COEF.items():
                value = components.get(name)
                if value is not None:
                    score += coef * value
                # If None, contribution is 0 (component excluded)
            m_score = round(score, 4)

        # Determine zone
        if m_score is None:
            zone = "unavailable"
            interpretation = "Insufficient data to compute M-Score"
        elif m_score > _M_THRESHOLD:
            zone = "manipulator"
            interpretation = (
                f"M-Score {m_score:.2f} > {_M_THRESHOLD} — elevated earnings manipulation risk"
            )
        elif m_score > _M_GREY_LOW:
            zone = "grey"
            interpretation = (
                f"M-Score {m_score:.2f} in grey zone [{_M_GREY_LOW}, {_M_THRESHOLD}] — inconclusive"
            )
        else:
            zone = "non_manipulator"
            interpretation = (
                f"M-Score {m_score:.2f} ≤ {_M_GREY_LOW} — low earnings manipulation signal"
            )

        return {
            "m_score":             m_score,
            "zone":                zone,
            "components":          components,
            "available_components": available_count,
            "total_components":    8,
            "interpretation":      interpretation,
            "available":           m_score is not None,
            "error":               None,
        }

    except Exception as exc:
        return {
            "m_score":             None,
            "zone":                "unavailable",
            "components":          {},
            "available_components": 0,
            "total_components":    8,
            "interpretation":      f"Error: {exc}",
            "available":           False,
            "error":               str(exc),
        }


# ---------------------------------------------------------------------------
# Altman Z'-Score (non-manufacturing variant)
# ---------------------------------------------------------------------------

_Z_COEFFICIENTS = {"X1": 6.56, "X2": 3.26, "X3": 6.72, "X4": 1.05}
_Z_SAFE     = 2.6
_Z_DISTRESS = 1.1


def compute_altman_z_score(hist: dict, market_cap_mm: Optional[float]) -> dict:
    """
    Compute the Altman non-manufacturing Z'-Score.

    Parameters
    ----------
    hist          : dict from get_historical_financials()
    market_cap_mm : float | None — current market cap in millions

    Returns
    -------
    dict with keys: z_score, zone, components, interpretation, available, error
    """
    try:
        rev   = hist.get("revenue", [])
        gp    = hist.get("gross_profit", [])
        ni    = hist.get("net_income", [])
        ta    = hist.get("total_assets", [])
        cffo  = hist.get("cffo", [])

        def _safe(lst, idx):
            if lst and len(lst) > idx:
                v = lst[idx]
                if v is not None:
                    try:
                        return float(v)
                    except (TypeError, ValueError):
                        pass
            return None

        ta_t  = _safe(ta, 0)
        ni_t  = _safe(ni, 0)
        ni_1  = _safe(ni, 1)
        ni_2  = _safe(ni, 2)
        gp_t  = _safe(gp, 0)
        rev_t = _safe(rev, 0)

        if ta_t is None or ta_t == 0:
            return {
                "z_score":       None,
                "zone":          "unavailable",
                "components":    {},
                "interpretation": "No total assets data",
                "available":     False,
                "error":         "No total assets data",
            }

        components: dict[str, Optional[float]] = {}

        # X1 = Working Capital / Total Assets
        # Proxy: NWC ≈ net_income * 0.5 (rough)
        x1: Optional[float] = None
        if ni_t is not None:
            nwc_proxy = ni_t * 0.5
            x1 = nwc_proxy / ta_t
        components["X1"] = x1

        # X2 = Retained Earnings / Total Assets
        # Proxy: cumulative 3-year net income / total assets
        x2: Optional[float] = None
        retained = sum(
            v for v in [ni_t, ni_1, ni_2] if v is not None
        )
        if retained is not None:
            x2 = retained / ta_t
        components["X2"] = x2

        # X3 = EBIT / Total Assets
        # EBIT ≈ net_income * 1.35 (tax gross-up)
        x3: Optional[float] = None
        if ni_t is not None:
            ebit_proxy = ni_t * 1.35
            x3 = ebit_proxy / ta_t
        components["X3"] = x3

        # X4 = Market Cap / Total Liabilities
        # Total Liabilities ≈ Total Assets × 0.5 (rough proxy)
        x4: Optional[float] = None
        if market_cap_mm is not None and ta_t != 0:
            total_liab_proxy = ta_t * 0.5
            if total_liab_proxy != 0:
                x4 = market_cap_mm / total_liab_proxy
        components["X4"] = x4

        # Require at least X2, X3 to compute a meaningful score
        available_components = [x1, x2, x3, x4]
        n_available = sum(1 for v in available_components if v is not None)

        z_score: Optional[float] = None
        if n_available >= 2:
            score = 0.0
            for key, coef in _Z_COEFFICIENTS.items():
                val = components.get(key)
                if val is not None:
                    score += coef * val
            z_score = round(score, 4)

        # Determine zone
        if z_score is None:
            zone = "unavailable"
            interpretation = "Insufficient data to compute Z-Score"
        elif z_score > _Z_SAFE:
            zone = "safe"
            interpretation = f"Z-Score {z_score:.2f} > {_Z_SAFE} — financially healthy"
        elif z_score > _Z_DISTRESS:
            zone = "grey"
            interpretation = (
                f"Z-Score {z_score:.2f} in grey zone [{_Z_DISTRESS}, {_Z_SAFE}] — monitor leverage"
            )
        else:
            zone = "distress"
            interpretation = (
                f"Z-Score {z_score:.2f} ≤ {_Z_DISTRESS} — financial distress signal"
            )

        return {
            "z_score":        z_score,
            "zone":           zone,
            "components":     components,
            "interpretation": interpretation,
            "available":      z_score is not None,
            "error":          None,
        }

    except Exception as exc:
        return {
            "z_score":        None,
            "zone":           "unavailable",
            "components":     {},
            "interpretation": f"Error: {exc}",
            "available":      False,
            "error":          str(exc),
        }


# ---------------------------------------------------------------------------
# Combined wrapper
# ---------------------------------------------------------------------------

def compute_forensic_signals(
    hist: dict,
    market_cap_mm: Optional[float],
    sector: Optional[str] = None,
) -> dict:
    """
    Run both M-Score and Z-Score and combine into a single forensic signal dict.

    forensic_flag logic
    -------------------
    red   : M-Score > -1.78 (manipulator zone) OR Z-Score zone == "distress"
    amber : M-Score in grey zone [-2.50, -1.78] OR Z-Score zone == "grey"
    green : everything else (both non-manipulator and safe/unavailable)

    Parameters
    ----------
    hist          : dict from get_historical_financials()
    market_cap_mm : float | None
    sector        : str | None (reserved for future sector-specific thresholds)

    Returns
    -------
    dict with keys: beneish, altman, forensic_flag, available, error
    """
    try:
        beneish = compute_beneish_m_score(hist)
        altman  = compute_altman_z_score(hist, market_cap_mm)

        m_score   = beneish.get("m_score")
        m_zone    = beneish.get("zone", "unavailable")
        z_zone    = altman.get("zone", "unavailable")

        # Determine overall forensic flag
        if m_zone == "manipulator" or z_zone == "distress":
            forensic_flag = "red"
        elif m_zone == "grey" or z_zone == "grey":
            forensic_flag = "amber"
        else:
            forensic_flag = "green"

        return {
            "beneish":       beneish,
            "altman":        altman,
            "forensic_flag": forensic_flag,
            "available":     beneish.get("available", False) or altman.get("available", False),
            "error":         None,
            # Flat keys for easy access in qoe_signals and dashboard
            "m_score":       m_score,
            "m_score_zone":  m_zone,
            "z_score":       altman.get("z_score"),
            "z_score_zone":  z_zone,
        }

    except Exception as exc:
        return {
            "beneish":       {"available": False, "error": str(exc)},
            "altman":        {"available": False, "error": str(exc)},
            "forensic_flag": "amber",
            "available":     False,
            "error":         str(exc),
        }
