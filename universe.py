from __future__ import annotations
"""股票宇宙 — S&P 500 成分股清單。"""

import logging

import pandas as pd
import requests

from notifier import send_message

log = logging.getLogger(__name__)

SP500_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
NASDAQ100_URL = "https://en.wikipedia.org/wiki/Nasdaq-100"


def _normalize_ticker(t: str) -> str:
    return t.replace(".", "-")


def _validate_ticker_list(tickers: list[str], source_name: str, expected_min: int = 450) -> list[str]:
    tickers = sorted(set(_normalize_ticker(t) for t in tickers if t.strip()))
    if len(tickers) < expected_min:
        log.warning(f"{source_name}: got {len(tickers)} tickers (expected ≥{expected_min}) — list may be invalid!")
        from notifier import send_message
        send_message(f"⚠️ {source_name} 回傳資料異常：{len(tickers)} 檔（預期 ≥{expected_min}）")
    log.info(f"{source_name}: {len(tickers)} tickers loaded.")
    return tickers


_USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36",
]


def _fetch_tables(url: str, retries: int = 3) -> list:
    """用 requests + pandas 抓取 HTML table（带 retry + User-Agent rotation）。"""
    last_error = None
    for attempt in range(retries):
        try:
            headers = {"User-Agent": _USER_AGENTS[attempt % len(_USER_AGENTS)]}
            resp = requests.get(url, headers=headers, timeout=15)
            resp.raise_for_status()
            return pd.read_html(resp.text)
        except Exception as e:
            last_error = e
            if attempt < retries - 1:
                log.warning(f"Wikipedia fetch attempt {attempt + 1} failed: {e}, retrying...")
                continue
    raise last_error


def _fmp_sp500() -> list[str] | None:
    try:
        from fmp_client import get_sp500 as fmp_sp500, available as fmp_avail
        if fmp_avail():
            tickers = fmp_sp500()
            if tickers and len(tickers) >= 450:
                log.info(f"S&P 500: {len(tickers)} tickers (via FMP)")
                return tickers
    except Exception as e:
        log.debug(f"FMP S&P 500 failed: {e}")
    return None


def _fmp_nasdaq100() -> list[str] | None:
    try:
        from fmp_client import get_nasdaq100 as fmp_nasdaq, available as fmp_avail
        if fmp_avail():
            tickers = fmp_nasdaq()
            if tickers and len(tickers) >= 90:
                log.info(f"NASDAQ-100: {len(tickers)} tickers (via FMP)")
                return tickers
    except Exception as e:
        log.debug(f"FMP NASDAQ-100 failed: {e}")
    return None


def get_sp500() -> list[str]:
    fmp_tickers = _fmp_sp500()
    if fmp_tickers is not None:
        return _validate_ticker_list(fmp_tickers, "S&P 500")
    try:
        tables = _fetch_tables(SP500_URL)
        df = tables[0]
        tickers = sorted(df["Symbol"].tolist())
        return _validate_ticker_list(tickers, "S&P 500")
    except Exception as e:
        log.warning(f"Failed to fetch S&P 500: {e}")
        log.warning("*** USING STATIC FALLBACK LIST — tickers may be stale! ***")
        send_message(f"⚠️ S&P 500 fetch failed: {e} — using static fallback list")
        return _fallback()


def get_nasdaq100() -> list[str]:
    fmp_tickers = _fmp_nasdaq100()
    if fmp_tickers is not None:
        return _validate_ticker_list(fmp_tickers, "NASDAQ-100", expected_min=90)
    try:
        tables = _fetch_tables(NASDAQ100_URL)
        for table in tables:
            col = "Ticker" if "Ticker" in table.columns else "Symbol"
            if col in table.columns:
                tickers = sorted(table[col].tolist())
                return _validate_ticker_list(tickers, "NASDAQ-100", expected_min=90)
    except Exception as e:
        log.warning(f"Failed to fetch NASDAQ-100: {e}")
        log.warning("*** USING STATIC FALLBACK LIST — tickers may be stale! ***")
        send_message(f"⚠️ NASDAQ-100 fetch failed: {e} — using static fallback list")
    return _fallback()


def get_universe(source: str = "sp500") -> list[str]:
    source = source.lower()
    if source == "sp500":
        return get_sp500()
    elif source == "nasdaq100":
        return get_nasdaq100()
    else:
        log.warning(f"Unknown universe '{source}', using SP500 fallback.")
        return _fallback()


def _fallback() -> list[str]:
    tickers = [
        "AAPL", "MSFT", "NVDA", "TSLA", "META", "AMZN", "GOOGL", "GOOG",
        "BRK.B", "JPM", "V", "JNJ", "WMT", "PG", "MA", "UNH", "HD", "DIS",
        "PYPL", "NFLX", "ADBE", "CRM", "INTC", "AMD", "QCOM", "TXN", "AVGO",
        "AMGN", "GILD", "SBUX", "NKE", "BA", "CAT", "GE", "XOM", "CVX",
        "PFE", "MRK", "ABBV", "KO", "PEP", "COST", "TMO", "DHR", "LIN",
        "NEE", "LOW", "AXP", "BLK", "C", "CMCSA", "CSCO", "F", "GM",
        "GS", "HON", "IBM", "LMT", "MMM", "MO", "MS", "ORCL", "PM",
        "RTX", "T", "UPS", "USB", "WFC", "ABT", "ACN", "ADP", "ALL",
        "AMAT", "AON", "APA", "APD", "APH", "ARE", "ATO", "AWK", "AXON",
        "AZO", "BAX", "BBY", "BDX", "BIIB", "BK", "BKNG", "BKR", "BLDR",
        "BMY", "BSX", "BWA", "BXP", "CAG", "CAH", "CARR", "CB", "CBOE",
        "CBRE", "CCI", "CCL", "CDNS", "CDW", "CE", "CEG", "CF", "CFG",
        "CHD", "CHRW", "CHTR", "CI", "CINF", "CL", "CLX", "CME", "CMG",
        "CMI", "CMS", "CNC", "CNP", "COF", "COO", "COP", "COR", "CPB",
        "CPRT", "CRL", "CRM", "CSGP", "CSX", "CTAS", "CTRA", "CTSH",
        "CTVA", "CVS", "CVX", "D", "DAL", "DD", "DE", "DECK", "DELL",
        "DFS", "DG", "DGX", "DHI", "DHR", "DIS", "DLR", "DLTR", "DOC",
        "DOCU", "DOV", "DOW", "DRE", "DRI", "DTE", "DUK", "DVA", "DVN",
        "DXCM", "EA", "EBAY", "ECL", "ED", "EFX", "EIX", "EL", "EMN",
        "EMR", "ENPH", "EOG", "EPAM", "EQIX", "EQR", "EQT", "ERIE",
        "ES", "ESS", "ETN", "ETR", "EVRG", "EW", "EXC", "EXPD", "EXPE",
        "EXR", "FANG", "FAST", "FCX", "FDS", "FDX", "FE", "FFIV", "FI",
        "FICO", "FIS", "FITB", "FMC", "FOX", "FOXA", "FRT", "FSLR",
        "FTNT", "FTV", "GD", "GDDY", "GE", "GEHC", "GEN", "GFS", "GGG",
        "GILD", "GIS", "GL", "GLW", "GM", "GNRC", "GPC", "GPN", "GRMN",
        "GS", "GWW", "HAL", "HAS", "HBAN", "HCA", "HD", "HES", "HIG",
        "HII", "HLT", "HOLX", "HON", "HPE", "HPQ", "HRL", "HSIC", "HST",
        "HSY", "HUBB", "HUM", "HWM", "IBM", "ICE", "IDXX", "IEX", "IFF",
        "INCY", "INTC", "INTU", "INVH", "IP", "IPG", "IQV", "IR", "IRM",
        "ISRG", "IT", "ITW", "IVZ", "J", "JBHT", "JCI", "JKHY", "JNJ",
        "JPM", "K", "KDP", "KEY", "KEYS", "KHC", "KIM", "KKR", "KMB",
        "KMI", "KMX", "KO", "KR", "KVUE", "L", "LDOS", "LEN", "LH",
        "LHX", "LIN", "LKQ", "LLY", "LMT", "LNC", "LNT", "LOW", "LRCX",
        "LULU", "LUV", "LVS", "LW", "LYB", "LYV", "MA", "MAA", "MAR",
        "MAS", "MCD", "MCHP", "MCK", "MCO", "MDLZ", "MDT", "MET", "META",
        "MGM", "MHK", "MKC", "MKTX", "MLM", "MMC", "MMM", "MNST", "MO",
        "MOH", "MOS", "MPC", "MPWR", "MRK", "MRNA", "MRO", "MS", "MSCI",
        "MSFT", "MSI", "MTB", "MTCH", "MTD", "MU", "NDAQ", "NEE", "NEM",
        "NFLX", "NI", "NKE", "NOC", "NOW", "NRG", "NSC", "NTAP", "NTRS",
        "NUE", "NVDA", "NVR", "NWL", "NWS", "NWSA", "NXPI", "O", "ODFL",
        "OGN", "OKE", "OMC", "ON", "ORCL", "ORLY", "OTIS", "OXY", "PANW",
        "PARA", "PAYC", "PAYX", "PCAR", "PCG", "PEG", "PEP", "PFE", "PFG",
        "PG", "PGR", "PH", "PHM", "PKG", "PLD", "PLTR", "PM", "PNC",
        "PNR", "PNW", "PODD", "POOL", "PPG", "PPL", "PRU", "PSA", "PSX",
        "PTC", "PWR", "PYPL", "QCOM", "RCL", "RDY", "REGN", "RF", "RHI",
        "RJF", "RL", "RMD", "ROK", "ROL", "ROP", "ROST", "RS", "RSG",
        "RTX", "RVTY", "SBAC", "SBUX", "SCHW", "SHW", "SJM", "SNA",
        "SNPS", "SO", "SOLV", "SPG", "SPGI", "SQ", "SRE", "STE", "STLD",
        "STT", "STX", "STZ", "SWK", "SWKS", "SYF", "SYK", "SYY", "T",
        "TAP", "TCOM", "TDG", "TDY", "TECH", "TEL", "TER", "TFC", "TFX",
        "TGT", "TJX", "TMO", "TMUS", "TPR", "TRGP", "TRMB", "TROW",
        "TRV", "TSCO", "TSLA", "TSN", "TT", "TTWO", "TXN", "TXT", "TYL",
        "UAL", "UBER", "UDR", "UHS", "ULTA", "UNH", "UNM", "UNP", "UPS",
        "URI", "USB", "V", "VICI", "VLO", "VLTO", "VMC", "VRSK", "VRSN",
        "VRTX", "VST", "VTR", "VTRS", "VZ", "WAB", "WAT", "WBA", "WBD",
        "WDC", "WEC", "WELL", "WFC", "WH", "WMB", "WMT", "WRB", "WST",
        "WSM", "WST", "WTW", "WY", "WYNN", "XEL", "XOM", "XYL", "YUM",
        "ZBRA", "ZBH", "ZTS",
    ]
    tickers = sorted(set(_normalize_ticker(t) for t in tickers if t.strip()))
    validated = [t for t in tickers if len(t) <= 5 and t.replace("-", "").isalpha()]
    if len(tickers) < 400:
        log.error(f"Fallback list only has {len(tickers)} valid-looking tickers — needs review!")
    log.info(f"Using fallback list: {len(tickers)} tickers.")
    return tickers
