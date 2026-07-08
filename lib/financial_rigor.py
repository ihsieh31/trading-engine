"""Financial Rigor — 精確十進位計算、市值驗證、估值指標、多源交叉驗證、Benford 檢測。

所有財務計算使用 Decimal 避免浮點誤差。零外部依賴。
"""

import math
import logging
from decimal import Decimal, Context, ROUND_HALF_EVEN
from typing import Any

log = logging.getLogger(__name__)

_CTX = Context(prec=28, rounding=ROUND_HALF_EVEN)


def exact(value: Any) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):
        return Decimal(str(value))
    return Decimal(str(value))


def fmt_number(d: Decimal) -> str:
    v = float(d)
    abs_v = abs(v)
    if abs_v >= 1e12:
        return f"{v/1e12:.2f}T"
    if abs_v >= 1e9:
        return f"{v/1e9:.2f}B"
    if abs_v >= 1e6:
        return f"{v/1e6:.2f}M"
    return f"{v:,.2f}"


def verify_market_cap(price: float, shares: float, reported_cap: float) -> dict:
    p = exact(price)
    s = exact(shares)
    r = exact(reported_cap)
    calculated = _CTX.multiply(p, s)
    deviation = abs(float(calculated - r) / float(r)) * 100 if r != 0 else 0
    return {
        "calculated_cap": float(calculated),
        "reported_cap": float(r),
        "deviation_pct": round(deviation, 2),
        "pass": deviation <= 5,
        "warning_unit_mismatch": deviation > 5,
    }


def verify_valuation(price: float, eps: float = None, bvps: float = None,
                     fcf_per_share: float = None, dividend: float = None,
                     revenue_per_share: float = None) -> dict:
    p = exact(price)
    results = {}
    if eps is not None and float(eps) != 0:
        e = exact(eps)
        pe = float(_CTX.divide(p, e))
        ey = float(_CTX.divide(e, p) * 100)
        results["PE"] = round(pe, 2)
        results["earnings_yield_pct"] = round(ey, 2)
    if bvps is not None and float(bvps) != 0:
        b = exact(bvps)
        pb = float(_CTX.divide(p, b))
        results["PB"] = round(pb, 2)
        if eps is not None and float(eps) != 0:
            roe = float(_CTX.divide(exact(eps), b) * 100)
            results["ROE_pct"] = round(roe, 2)
    if fcf_per_share is not None and float(fcf_per_share) != 0:
        f = exact(fcf_per_share)
        results["P_FCF"] = round(float(_CTX.divide(p, f)), 2)
        results["FCF_yield_pct"] = round(float(_CTX.divide(f, p) * 100), 2)
    if dividend is not None and float(p) != 0:
        d = exact(dividend)
        results["dividend_yield_pct"] = round(float(_CTX.divide(d, p) * 100), 2)
    if revenue_per_share is not None and float(revenue_per_share) != 0:
        r = exact(revenue_per_share)
        results["PS"] = round(float(_CTX.divide(p, r)), 2)
    return results


def cross_validate(source_values: dict, tolerance_pct: float = 2.0) -> dict:
    values = {k: exact(v) for k, v in source_values.items()}
    nums = [float(v) for v in values.values()]
    sorted_vals = sorted(nums)
    n = len(sorted_vals)
    median = sorted_vals[n // 2] if n % 2 == 1 else (sorted_vals[n//2-1] + sorted_vals[n//2]) / 2
    results = {}
    all_ok = True
    for src, val in values.items():
        dev = abs(float(val) - median) / median * 100 if median != 0 else 0
        ok = dev <= tolerance_pct
        if not ok:
            all_ok = False
        results[src] = {"value": float(val), "deviation_pct": round(dev, 2), "pass": ok}
    return {"consensus": round(median, 4), "all_consistent": all_ok, "sources": results}


_BENFORD = {d: math.log10(1 + 1/d) for d in range(1, 10)}


def benford_check(values: list) -> dict:
    digits = []
    for v in values:
        v = abs(float(v))
        if v > 0:
            sig = 10 ** (math.log10(v) - math.floor(math.log10(v)))
            d = int(sig)
            if 1 <= d <= 9:
                digits.append(d)
    n = len(digits)
    if n < 50:
        return {"sample_size": n, "is_conforming": None, "reason": "insufficient_sample"}
    counts = {}
    for d in digits:
        counts[d] = counts.get(d, 0) + 1
    observed = {d: counts.get(d, 0) / n for d in range(1, 10)}
    mad = sum(abs(observed.get(d, 0) - _BENFORD[d]) for d in range(1, 10)) / 9
    if mad < 0.006:
        conformity = "close"
    elif mad < 0.012:
        conformity = "acceptable"
    elif mad < 0.015:
        conformity = "marginal"
    else:
        conformity = "nonconforming"
    return {
        "sample_size": n,
        "mad": round(mad, 6),
        "conformity": conformity,
        "is_conforming": mad < 0.015,
    }


def exact_calc(expr: str) -> float:
    allowed = set("0123456789.+-*/() eE")
    if not all(c in allowed for c in expr.replace(" ", "")):
        raise ValueError("Unsafe expression")
    result = eval(expr, {"__builtins__": {}}, {})
    return float(exact(result))
