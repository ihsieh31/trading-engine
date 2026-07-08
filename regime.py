from __future__ import annotations
"""市場情境感知 — 判斷目前市場處於何種 regime，影響部位規模與進場意願。"""

import json
import logging
import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime, timedelta, timezone
from pathlib import Path
from event_bus import EventBus

log = logging.getLogger(__name__)


class RegimeDetector:
    """市場情境偵測器。

    使用 SPY 判斷目前 regime：
    - bull:  價格 > MA50 > MA200，趨勢向上
    - bear:  價格 < MA50 < MA200，趨勢向下
    - ranging:  價格在 MA50 附近來回，無明確方向
    - high_vol: 波動率偏高（ATR 百分位 > 80）

    影響：
    - position_size_mult: 多頭市場 1.0，空頭 0.5，盤整 0.75
    - 空頭時只允許 Overweight 評級進場
    """

    def __init__(self):
        self._cache = {}

    @staticmethod
    def _fmp_spy_data():
        try:
            from fmp_client import get_historical, available as fmp_avail
            if not fmp_avail():
                return None
            hist = get_historical("SPY", days=365)
            if not hist or len(hist) < 60:
                return None
            df = pd.DataFrame(hist)
            df.rename(columns={"close": "Close", "high": "High", "low": "Low", "open": "Open", "volume": "Volume"}, inplace=True)
            for c in ["Close", "High", "Low"]:
                df[c] = pd.to_numeric(df[c], errors="coerce")
            df.sort_values("date", inplace=True)
            df.set_index(pd.DatetimeIndex(pd.to_datetime(df["date"])), inplace=True)
            return df[["Close", "High", "Low"]]
        except Exception as e:
            log.debug(f"FMP SPY data failed: {e}")
        return None

    def detect(self, force_refresh: bool = False, market_open: bool | None = None) -> dict:
        if not force_refresh and self._cache:
            age = (datetime.now(timezone.utc) - self._cache.get("_cached_at", datetime.min.replace(tzinfo=timezone.utc))).total_seconds()
            if age < 3600:
                cached_phase = self._cache.get("_cached_phase", "")
                if market_open is not True or cached_phase == "open":
                    return self._cache

        spy = self._fmp_spy_data()
        if spy is None:
            try:
                spy = yf.download("SPY", period="1y", interval="1d", auto_adjust=True, progress=False)
            except Exception:
                spy = None
        if spy is None or (hasattr(spy, "empty") and spy.empty) or "Close" not in spy.columns:
            log.warning("RegimeDetector: no SPY data")
            return self._fallback()

        try:
            result = self._compute_regime(spy)
        except Exception as e:
            log.warning(f"RegimeDetector compute failed: {e}")
            return self._fallback()

        result["_cached_at"] = datetime.now(timezone.utc)
        result["_cached_phase"] = "open" if market_open else "closed"
        old_regime = self._cache.get("regime") if self._cache else None
        self._cache = result
        if old_regime and old_regime != result["regime"]:
            EventBus.get_instance().emit("regime_changed", {
                "from": old_regime, "to": result["regime"],
                "spy_price": result["spy_price"],
                "position_size_mult": result["position_size_mult"],
            })
        log.info(f"Regime: {result['regime']} | SPY={result['spy_price']} | mult={result['position_size_mult']}")
        return result

    def _compute_regime(self, spy_df):
        close = spy_df["Close"].squeeze()
        if isinstance(close, np.ndarray):
            close = pd.Series(close)
        high = spy_df["High"].squeeze()
        low = spy_df["Low"].squeeze()

        ma50 = close.rolling(50).mean()
        ma200 = close.rolling(200).mean()
        latest = close.iloc[-1]
        ma50_val = ma50.iloc[-1]
        ma200_val = ma200.iloc[-1]

        prev_close = close.shift(1)
        tr = pd.concat([
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ], axis=1).max(axis=1)
        atr_series = tr.rolling(14).mean()
        atr = float(atr_series.iloc[-1]) if not atr_series.empty else 0.0
        atr_pct = (atr / latest * 100) if latest > 0 else 0
        hist_atr_pct = (atr_series.dropna() / close.reindex(atr_series.dropna().index) * 100).values
        atr_percentile = float(np.mean(hist_atr_pct <= atr_pct) * 100) if len(hist_atr_pct) > 5 else 50.0

        price_vs_ma50 = (latest - ma50_val) / ma50_val * 100
        price_vs_ma200 = (latest - ma200_val) / ma200_val * 100

        if latest > ma50_val > ma200_val and price_vs_ma50 > -1:
            regime = "bull"
            size_mult = 1.0
        elif latest < ma50_val < ma200_val and price_vs_ma50 < 1:
            regime = "bear"
            size_mult = 0.5
        elif abs(price_vs_ma50) < 3:
            regime = "ranging"
            size_mult = 0.75
        elif price_vs_ma50 >= 3:
            regime = "bull"
            size_mult = 1.0
        else:
            regime = "ranging"
            size_mult = 0.75

        if atr_percentile > 80:
            regime = f"{regime}_high_vol"
            size_mult *= 0.75

        macro_context = ""
        try:
            from economics_kb import get_economics_kb
            ekb = get_economics_kb()
            macro_context = ekb.get_macro_context(regime=regime)
        except Exception:
            pass

        return {
            "regime": regime,
            "position_size_mult": size_mult,
            "spy_price": float(round(latest, 2)),
            "ma50": float(round(ma50_val, 2)),
            "ma200": float(round(ma200_val, 2)),
            "price_vs_ma50_pct": float(round(price_vs_ma50, 2)),
            "price_vs_ma200_pct": float(round(price_vs_ma200, 2)),
            "atr_pct": float(round(atr_pct, 2)),
            "atr_percentile": float(round(atr_percentile, 1)),
            "macro_context": macro_context,
            "detected_at": datetime.now(timezone.utc).isoformat(),
        }

    def _fallback(self) -> dict:
        return {
            "regime": "unknown",
            "position_size_mult": 0.5,
            "spy_price": 0,
            "ma50": 0,
            "ma200": 0,
            "price_vs_ma50_pct": 0,
            "price_vs_ma200_pct": 0,
            "atr_pct": 0,
            "atr_percentile": 0,
            "detected_at": datetime.now(timezone.utc).isoformat(),
        }
