from __future__ import annotations
"""產業分類對應表 — 用於 MAX_SECTOR_PCT 產業曝險控管。

未知 ticker 回傳 "Unknown"，套用 UNKNOWN_SECTOR_CAP（預設 5%）保守上限。
"""

import logging

log = logging.getLogger(__name__)

# 未知產業分類的保守上限（取代完全放行）
UNKNOWN_SECTOR_CAP = 0.05

SECTOR_MAP = {
    # Technology
    "AAPL": "Technology", "MSFT": "Technology", "NVDA": "Technology",
    "AVGO": "Technology", "AMD": "Technology", "INTC": "Technology",
    "QCOM": "Technology", "TXN": "Technology", "ADBE": "Technology",
    "CRM": "Technology", "CSCO": "Technology", "ORCL": "Technology",
    "ACN": "Technology", "ADP": "Technology", "IT": "Technology",
    "FICO": "Technology", "ANET": "Technology", "CDNS": "Technology",
    "SNPS": "Technology", "INTU": "Technology", "NOW": "Technology",
    "PANW": "Technology", "FTNT": "Technology", "CRWD": "Technology",
    "MRVL": "Technology", "KLAC": "Technology", "LRCX": "Technology",
    "AMAT": "Technology", "MU": "Technology", "WDC": "Technology",
    "STX": "Technology", "ENPH": "Technology", "FSLR": "Technology",
    "APH": "Technology", "GLW": "Technology", "KEYS": "Technology",
    "MCHP": "Technology", "MSI": "Technology", "NTAP": "Technology",
    "NXPI": "Technology", "SWKS": "Technology", "TER": "Technology",
    "TEL": "Technology", "JBL": "Technology",

    # Healthcare
    "JNJ": "Healthcare", "PFE": "Healthcare", "MRK": "Healthcare",
    "UNH": "Healthcare", "ABBV": "Healthcare", "ABT": "Healthcare",
    "TMO": "Healthcare", "DHR": "Healthcare", "LLY": "Healthcare",
    "AMGN": "Healthcare", "GILD": "Healthcare", "VRTX": "Healthcare",
    "SYK": "Healthcare", "BSX": "Healthcare", "MDT": "Healthcare",
    "ISRG": "Healthcare", "REGN": "Healthcare", "MRNA": "Healthcare",
    "BIIB": "Healthcare", "ILMN": "Healthcare", "DXCM": "Healthcare",
    "PODD": "Healthcare", "ALGN": "Healthcare", "ZBH": "Healthcare",
    "A": "Healthcare", "ALNY": "Healthcare", "ARGX": "Healthcare",
    "BAX": "Healthcare", "BDX": "Healthcare", "BIO": "Healthcare",
    "CERN": "Healthcare", "CI": "Healthcare", "CNC": "Healthcare",
    "COR": "Healthcare", "COO": "Healthcare", "CRL": "Healthcare",
    "DVA": "Healthcare", "ELV": "Healthcare", "EW": "Healthcare",
    "GEHC": "Healthcare", "HCA": "Healthcare", "HOLX": "Healthcare",
    "HUM": "Healthcare", "IDXX": "Healthcare", "INCY": "Healthcare",
    "IQV": "Healthcare", "LH": "Healthcare",

    # Financial
    "JPM": "Financial", "BAC": "Financial", "WFC": "Financial",
    "C": "Financial", "GS": "Financial", "MS": "Financial",
    "BLK": "Financial", "AXP": "Financial", "V": "Financial",
    "MA": "Financial", "PYPL": "Financial", "SQ": "Financial",
    "COF": "Financial", "USB": "Financial", "PNC": "Financial",
    "TFC": "Financial", "SCHW": "Financial", "SPGI": "Financial",
    "MCO": "Financial", "MMC": "Financial", "AON": "Financial",
    "AJG": "Financial", "MET": "Financial", "PRU": "Financial",
    "AIG": "Financial", "ALL": "Financial", "CB": "Financial",
    "PGR": "Financial", "TRV": "Financial", "BK": "Financial",
    "STT": "Financial", "NTRS": "Financial", "MTB": "Financial",
    "FITB": "Financial", "RF": "Financial", "HBAN": "Financial",
    "KEY": "Financial", "CFG": "Financial", "SYF": "Financial",
    "DFS": "Financial", "CMA": "Financial", "ZION": "Financial",
    "SIVB": "Financial", "FIS": "Financial", "JKHY": "Financial",
    "NDAQ": "Financial", "CBOE": "Financial", "MKTX": "Financial",
    "L": "Financial", "UNM": "Financial", "GL": "Financial",
    "PFG": "Financial", "AFL": "Financial",

    # Consumer Cyclical
    "TSLA": "Consumer Cyclical", "AMZN": "Consumer Cyclical",
    "NKE": "Consumer Cyclical", "HD": "Consumer Cyclical",
    "LOW": "Consumer Cyclical", "SBUX": "Consumer Cyclical",
    "MCD": "Consumer Cyclical", "BKNG": "Consumer Cyclical",
    "TGT": "Consumer Cyclical",
    "TJX": "Consumer Cyclical", "ROST": "Consumer Cyclical",
    "GM": "Consumer Cyclical", "F": "Consumer Cyclical",
    "UBER": "Consumer Cyclical", "LYFT": "Consumer Cyclical",
    "DHI": "Consumer Cyclical", "LEN": "Consumer Cyclical",
    "NVR": "Consumer Cyclical", "PHM": "Consumer Cyclical",
    "TSCO": "Consumer Cyclical", "ORLY": "Consumer Cyclical",
    "AZO": "Consumer Cyclical", "AAP": "Consumer Cyclical",
    "BBY": "Consumer Cyclical", "DG": "Consumer Cyclical",
    "DLTR": "Consumer Cyclical", "ULTA": "Consumer Cyclical",
    "EBAY": "Consumer Cyclical", "ETSY": "Consumer Cyclical",
    "MAR": "Consumer Cyclical", "HLT": "Consumer Cyclical",
    "CCL": "Consumer Cyclical", "RCL": "Consumer Cyclical",
    "NCLH": "Consumer Cyclical", "WYNN": "Consumer Cyclical",
    "LVS": "Consumer Cyclical", "MGM": "Consumer Cyclical",
    "DPZ": "Consumer Cyclical", "YUM": "Consumer Cyclical",
    "CMG": "Consumer Cyclical", "DRI": "Consumer Cyclical",
    "LULU": "Consumer Cyclical", "DECK": "Consumer Cyclical",
    "RL": "Consumer Cyclical", "TPR": "Consumer Cyclical",

    # Communication Services
    "META": "Communication Services", "GOOGL": "Communication Services",
    "GOOG": "Communication Services", "NFLX": "Communication Services",
    "DIS": "Communication Services", "CMCSA": "Communication Services",
    "T": "Communication Services", "TMUS": "Communication Services",
    "VZ": "Communication Services", "CHTR": "Communication Services",
    "WBD": "Communication Services", "PARA": "Communication Services",
    "FOXA": "Communication Services", "FOX": "Communication Services",
    "NWSA": "Communication Services", "NWS": "Communication Services",
    "TTWO": "Communication Services", "EA": "Communication Services",
    "OMC": "Communication Services", "IPG": "Communication Services",
    "PUBM": "Communication Services", "RDDT": "Communication Services",
    "SNAP": "Communication Services", "PINS": "Communication Services",

    # Consumer Defensive
    "WMT": "Consumer Defensive", "COST": "Consumer Defensive",
    "PG": "Consumer Defensive", "KO": "Consumer Defensive",
    "PEP": "Consumer Defensive", "PM": "Consumer Defensive",
    "MO": "Consumer Defensive", "MDLZ": "Consumer Defensive",
    "KHC": "Consumer Defensive", "KDP": "Consumer Defensive",
    "KR": "Consumer Defensive", "CL": "Consumer Defensive",
    "CLX": "Consumer Defensive", "CHD": "Consumer Defensive",
    "KMB": "Consumer Defensive", "SJM": "Consumer Defensive",
    "GIS": "Consumer Defensive", "CPB": "Consumer Defensive",
    "HRL": "Consumer Defensive", "TSN": "Consumer Defensive",
    "CAG": "Consumer Defensive", "K": "Consumer Defensive",
    "HSY": "Consumer Defensive", "SYY": "Consumer Defensive",
    "STZ": "Consumer Defensive", "MNST": "Consumer Defensive",
    "COTY": "Consumer Defensive", "EL": "Consumer Defensive",
    "LW": "Consumer Defensive", "MKC": "Consumer Defensive",
    "FLO": "Consumer Defensive", "INGR": "Consumer Defensive",
    "DAR": "Consumer Defensive", "TAP": "Consumer Defensive",
    "BF-B": "Consumer Defensive", "BWA": "Consumer Defensive",

    # Energy
    "XOM": "Energy", "CVX": "Energy", "COP": "Energy",
    "EOG": "Energy", "PXD": "Energy", "OXY": "Energy",
    "HES": "Energy", "PSX": "Energy", "VLO": "Energy",
    "MPC": "Energy", "KMI": "Energy", "WMB": "Energy",
    "OKE": "Energy", "TRGP": "Energy", "DVN": "Energy",
    "MRO": "Energy", "FANG": "Energy", "CTRA": "Energy",
    "HAL": "Energy", "SLB": "Energy", "BKR": "Energy",
    "CHK": "Energy", "SWN": "Energy", "RRC": "Energy",
    "AR": "Energy", "EQT": "Energy", "APA": "Energy",
    "MUR": "Energy", "OVV": "Energy", "PR": "Energy",

    # Industrials
    "BA": "Industrials", "CAT": "Industrials", "GE": "Industrials",
    "HON": "Industrials", "UPS": "Industrials", "FDX": "Industrials",
    "RTX": "Industrials", "LMT": "Industrials", "NOC": "Industrials",
    "GD": "Industrials", "LHX": "Industrials",
    "MMM": "Industrials", "EMR": "Industrials", "ETN": "Industrials",
    "ITW": "Industrials", "CARR": "Industrials", "OTIS": "Industrials",
    "DE": "Industrials", "CMI": "Industrials", "PCAR": "Industrials",
    "CSX": "Industrials", "NSC": "Industrials", "UNP": "Industrials",
    "RSG": "Industrials", "WM": "Industrials", "WAB": "Industrials",
    "TT": "Industrials", "IR": "Industrials", "DOV": "Industrials",
    "PH": "Industrials", "ROK": "Industrials", "AME": "Industrials",
    "PWR": "Industrials", "JCI": "Industrials", "GPN": "Industrials",
    "EFX": "Industrials", "TRU": "Industrials", "VRSK": "Industrials",
    "DAY": "Industrials", "EXPD": "Industrials", "CHRW": "Industrials",
    "JBHT": "Industrials", "ODFL": "Industrials", "XPO": "Industrials",
    "SAIA": "Industrials", "LUV": "Industrials", "DAL": "Industrials",
    "UAL": "Industrials", "AAL": "Industrials",

    # Basic Materials
    "LIN": "Basic Materials", "APD": "Basic Materials", "SHW": "Basic Materials",
    "ECL": "Basic Materials", "DD": "Basic Materials", "DOW": "Basic Materials",
    "PPG": "Basic Materials", "LYB": "Basic Materials", "NEM": "Basic Materials",
    "FCX": "Basic Materials", "SCCO": "Basic Materials", "CTVA": "Basic Materials",
    "FMC": "Basic Materials", "CF": "Basic Materials", "MOS": "Basic Materials",
    "EMN": "Basic Materials", "IFF": "Basic Materials", "ALB": "Basic Materials",
    "CE": "Basic Materials", "PX": "Basic Materials", "AVY": "Basic Materials",
    "BALL": "Basic Materials", "CCK": "Basic Materials", "IP": "Basic Materials",
    "WRK": "Basic Materials", "PKG": "Basic Materials", "AMCR": "Basic Materials",
    "SEE": "Basic Materials", "SMG": "Basic Materials",

    # Real Estate
    "PLD": "Real Estate", "EQIX": "Real Estate", "DLR": "Real Estate",
    "SPG": "Real Estate", "PSA": "Real Estate", "O": "Real Estate",
    "WELL": "Real Estate", "AVB": "Real Estate", "EQR": "Real Estate",
    "ESS": "Real Estate", "MAA": "Real Estate", "UDR": "Real Estate",
    "INVH": "Real Estate", "SUI": "Real Estate", "HST": "Real Estate",
    "VICI": "Real Estate", "CCI": "Real Estate", "SBAC": "Real Estate",
    "AMT": "Real Estate", "WY": "Real Estate", "IRM": "Real Estate",
    "CBRE": "Real Estate", "EXR": "Real Estate", "FRT": "Real Estate",
    "KIM": "Real Estate", "REG": "Real Estate", "BXP": "Real Estate",

    # Utilities
    "NEE": "Utilities", "DUK": "Utilities", "SO": "Utilities",
    "D": "Utilities", "AEP": "Utilities", "EXC": "Utilities",
    "SRE": "Utilities", "PEG": "Utilities", "ED": "Utilities",
    "EIX": "Utilities", "XEL": "Utilities", "WEC": "Utilities",
    "ES": "Utilities", "ETR": "Utilities", "DTE": "Utilities",
    "PPL": "Utilities", "FE": "Utilities", "AEE": "Utilities",
    "CMS": "Utilities", "CNP": "Utilities", "LNT": "Utilities",
    "NI": "Utilities", "ATO": "Utilities", "AWK": "Utilities",
    "PNW": "Utilities", "CWT": "Utilities", "AGR": "Utilities",
    "EVRG": "Utilities", "OGE": "Utilities",
    "POR": "Utilities", "IDA": "Utilities", "NWE": "Utilities",
}

# Tickers that appear in multiple sectors — resolve by known ticker list if needed
# For now, most specific mapping wins (hand above)


_unknown_warned: set[str] = set()
_sector_cache: dict[str, str] = {}


def get_sector(ticker: str) -> str:
    ticker = ticker.upper()
    sector = SECTOR_MAP.get(ticker)
    if sector is not None:
        return sector
    if ticker in _sector_cache:
        return _sector_cache[ticker]

    sector = _fmp_sector_fallback(ticker)
    if sector is None:
        sector = _yfinance_sector_fallback(ticker)
    if sector is None:
        sector = "Unknown"

    _sector_cache[ticker] = sector
    if sector == "Unknown" and ticker not in _unknown_warned:
        _unknown_warned.add(ticker)
        log.warning(f"[{ticker}] Not in SECTOR_MAP and all fallbacks failed — "
                     "sector exposure control will be bypassed for this ticker")
    return sector


def _fmp_sector_fallback(ticker: str) -> str | None:
    try:
        from fmp_client import get_sector as fmp_sector, available as fmp_avail
        if fmp_avail():
            s = fmp_sector(ticker)
            if s:
                log.info(f"[{ticker}] Resolved sector via FMP: {s}")
                return s
    except Exception as e:
        log.debug(f"[{ticker}] FMP sector fallback failed: {e}")
    return None


def _yfinance_sector_fallback(ticker: str) -> str | None:
    try:
        import yfinance as yf
        info = yf.Ticker(ticker).info
        sector = info.get("sector", "") or ""
        if sector:
            log.info(f"[{ticker}] Resolved sector via yfinance fallback: {sector}")
            return sector
    except Exception as e:
        log.debug(f"[{ticker}] yfinance sector fallback failed: {e}")
    return None


def get_sector_exposure(positions: dict, portfolio_value: float) -> dict:
    """計算各產業的曝險比例。

    Args:
        positions: get_positions_dict() 的回傳格式 {ticker: {market_value: ...}}
        portfolio_value: 總資產價值

    Returns:
        {sector: pct_of_portfolio, ...}
    """
    sector_values = {}
    for ticker, pos in positions.items():
        sector = get_sector(ticker)
        market_value = pos.get("market_value", 0)
        sector_values[sector] = sector_values.get(sector, 0) + market_value

    if portfolio_value <= 0:
        return {s: 0.0 for s in sector_values}

    return {s: v / portfolio_value for s, v in sector_values.items()}


def sector_allows(ticker: str, positions: dict, portfolio_value: float,
                   max_sector_pct: float, extra_committed: float = 0.0) -> bool:
    """檢查新增此 ticker 是否會超過產業上限。

    Args:
        extra_committed: 本次批次中已排入但尚未反映在 positions 裡的該產業美元金額

    Returns:
        True = 允許進場（未超限）
    """
    sector = get_sector(ticker)
    if sector == "Unknown":
        effective_cap = UNKNOWN_SECTOR_CAP
    else:
        effective_cap = max_sector_pct

    current = get_sector_exposure(positions, portfolio_value)
    current_pct = current.get(sector, 0.0) + (extra_committed / portfolio_value if portfolio_value > 0 else 0)
    if current_pct >= effective_cap:
        log.info(f"[{ticker}] Sector '{sector}' at {current_pct*100:.1f}% "
                 f"(incl. {extra_committed:.0f} committed this cycle) >= limit {max_sector_pct*100:.0f}%, skipping")
        return False
    return True
