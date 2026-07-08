"""技術指標快速篩選器 — 用 yfinance 掃描大量股票，找出有潛力的標的。
不下 LLM，純 pandas 計算，每檔約 1-2 秒。
"""

import logging
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Optional

import pandas as pd
import yfinance as yf

log = logging.getLogger(__name__)


@dataclass
class ScreenResult:
    ticker: str
    score: float = 0.0
    price: Optional[float] = None
    ma20: Optional[float] = None
    ma50: Optional[float] = None
    rsi: Optional[float] = None
    macd: Optional[float] = None
    macd_signal: Optional[float] = None
    volume_ratio: Optional[float] = None
    signals: list[str] = field(default_factory=list)
    error: Optional[str] = None


class Screener:
    def __init__(self, max_workers: int = 10, lookback_days: int = 90, rate_limit_delay: float = 0.1):
        self.max_workers = max_workers
        self.lookback_days = lookback_days
        self._rate_limit_delay = rate_limit_delay
        self._last_request_time = 0.0
        self._rate_lock = threading.Lock()

    def screen(self, tickers: list[str], top_n: int = 20, min_score: float = 0) -> list[ScreenResult]:
        """掃描 tickers，回傳排名前 top_n 的結果。"""
        log.info(f"Screening {len(tickers)} tickers (top_n={top_n}, workers={self.max_workers})...")
        start = time.time()
        results = []

        with ThreadPoolExecutor(max_workers=self.max_workers) as ex:
            fut_map = {ex.submit(self._analyze_one, t): t for t in tickers}
            for fut in as_completed(fut_map):
                try:
                    results.append(fut.result())
                except Exception as e:
                    t = fut_map[fut]
                    results.append(ScreenResult(ticker=t, error=str(e)))

        scored = [r for r in results if r.score > min_score and r.error is None]
        scored.sort(key=lambda r: r.score, reverse=True)

        elapsed = time.time() - start
        log.info(f"Screen complete: {len(scored)} passed (of {len(tickers)}) in {elapsed:.0f}s")
        return scored[:top_n]

    def _analyze_one(self, ticker: str) -> ScreenResult:
        """對單一股票計算技術評分。"""
        with self._rate_lock:
            elapsed = time.time() - self._last_request_time
            if elapsed < self._rate_limit_delay:
                time.sleep(self._rate_limit_delay - elapsed)
            self._last_request_time = time.time()

        try:
            data = yf.download(ticker, period=f"{self.lookback_days}d", auto_adjust=True, progress=False)
            if data.empty or len(data) < 60:
                return ScreenResult(ticker=ticker, error="Insufficient data")

            close = data["Close"]
            if isinstance(close, pd.DataFrame) and ticker in close.columns:
                close = close[ticker]
            close = close.squeeze()

            volume = data["Volume"]
            if isinstance(volume, pd.DataFrame) and ticker in volume.columns:
                volume = volume[ticker]
            volume = volume.squeeze()

            price = float(close.iloc[-1])
            ma20 = float(close.tail(20).mean())
            ma50 = float(close.tail(50).mean())

            result = ScreenResult(ticker=ticker, price=round(price, 2))
            signals = []
            score = 0.0

            # 1. 價格 > MA20（短線上漲趨勢）
            if price > ma20:
                signals.append("above_ma20")
                score += 2.0
            else:
                score -= 1.0

            result.ma20 = round(ma20, 2)

            # 2. MA20 > MA50（黃金交叉趨勢）
            if ma20 > ma50:
                signals.append("golden_cross")
                score += 2.0
            else:
                score -= 1.0

            result.ma50 = round(ma50, 2)

            # 3. RSI (14)
            rsi = self._calc_rsi(close, 14)
            rsi_val = float(rsi.iloc[-1])
            result.rsi = round(rsi_val, 1)
            if 30 <= rsi_val <= 70:
                signals.append("rsi_normal")
                score += 1.0
            elif rsi_val > 70:
                signals.append("rsi_overbought")
                score -= 0.5
            elif rsi_val < 30:
                signals.append("rsi_oversold")
                score += 1.5

            # 4. MACD
            macd_line, signal_line, _ = self._calc_macd(close)
            macd_val = float(macd_line.iloc[-1])
            signal_val = float(signal_line.iloc[-1])
            result.macd = round(macd_val, 2)
            result.macd_signal = round(signal_val, 2)
            if macd_val > signal_val:
                signals.append("macd_bullish")
                score += 1.5
            else:
                score -= 0.5

            # 5. 成交量 ratio（最近 5 日 / 過去 50 日均量）
            avg_vol_5 = float(volume.tail(5).mean())
            avg_vol_45_before = float(volume.iloc[-50:-5].mean()) if len(volume) >= 50 else avg_vol_5
            vol_ratio = avg_vol_5 / avg_vol_45_before if avg_vol_45_before > 0 else 1.0
            result.volume_ratio = round(vol_ratio, 2)
            if vol_ratio > 1.5:
                signals.append("volume_surge")
                score += 1.0
            elif vol_ratio > 1.0:
                signals.append("volume_normal")
                score += 0.5

            result.score = round(score, 1)
            result.signals = signals
            return result

        except Exception as e:
            return ScreenResult(ticker=ticker, error=str(e))

    def _calc_rsi(self, series: pd.Series, period: int = 14) -> pd.Series:
        delta = series.diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)
        avg_gain = gain.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
        avg_loss = loss.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
        rs = avg_gain / avg_loss.replace(0, 1e-10)
        return 100 - (100 / (1 + rs))

    def _calc_macd(self, series: pd.Series) -> tuple[pd.Series, pd.Series, pd.Series]:
        ema12 = series.ewm(span=12, adjust=False).mean()
        ema26 = series.ewm(span=26, adjust=False).mean()
        macd_line = ema12 - ema26
        signal_line = macd_line.ewm(span=9, adjust=False).mean()
        histogram = macd_line - signal_line
        return macd_line, signal_line, histogram

    def print_summary(self, results: list[ScreenResult]):
        """印出篩選結果表格。"""
        if not results:
            log.info("No stocks passed screening.")
            return
        lines = [f"{'Ticker':>8} {'Score':>6} {'Price':>8} {'MA20':>8} {'RSI':>6} {'Vol':>6} {'Signals':<40}"]
        lines.append("-" * 85)
        for r in results:
            vol_str = f"{r.volume_ratio:.1f}x" if r.volume_ratio else "N/A"
            sig_str = ", ".join(r.signals) if r.signals else "-"
            lines.append(f"{r.ticker:>8} {r.score:>6.1f} {r.price:>8} {r.ma20 or 0:>8.1f} {r.rsi or 0:>6.1f} {vol_str:>6} {sig_str:<40}")
        log.info("\n".join(lines))
