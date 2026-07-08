"""美股交易日曆 — 使用 exchange_calendars 精確判斷 NYSE 交易日及時段。"""

import logging
from datetime import datetime, date, timezone, timedelta

import pytz
import pandas as pd
import exchange_calendars as xcals

log = logging.getLogger(__name__)

_NY_TZ = pytz.timezone("America/New_York")
_CAL = None


def today_et() -> date:
    """公開 wrapper：取美東時區的『今天』，取代 date.today()。"""
    return _ny_today()


def _ny_today() -> date:
    """統一取美東時區的『今天』，取代 date.today()。"""
    return datetime.now(timezone.utc).astimezone(_NY_TZ).date()


def _get_cal():
    global _CAL
    if _CAL is None:
        try:
            _CAL = xcals.get_calendar("XNYS")
        except Exception as e:
            log.warning(f"Failed to load NYSE calendar: {e}")
            _CAL = None
    return _CAL


def is_trading_day(check_date: date = None) -> bool:
    cal = _get_cal()
    if cal is None:
        log.error("Trading calendar unavailable — conservatively assuming non-trading day. Check exchange_calendars installation.")
        from notifier import send_message
        send_message("🚨 交易日曆載入失敗，系統保守視為非交易日以避免誤判")
        return False
    if check_date is None:
        check_date = _ny_today()
    return cal.is_session(check_date)


def is_market_open_now(dt: datetime = None) -> bool:
    if dt is None:
        dt = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    et_dt = dt.astimezone(_NY_TZ)
    cal = _get_cal()
    if cal is None:
        return _fallback_is_open(et_dt)
    return cal.is_open_on_minute(et_dt)


def get_market_phase(dt: datetime = None) -> str:
    if dt is None:
        dt = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    et_dt = dt.astimezone(_NY_TZ)

    cal = _get_cal()
    if cal is None:
        return "open" if _fallback_is_open(et_dt) else "closed"

    if cal.is_open_on_minute(et_dt):
        return "open"

    today_date = et_dt.date()
    if not cal.is_session(today_date):
        return "closed"

    today_sec = et_dt.hour * 3600 + et_dt.minute * 60 + et_dt.second
    row = cal.schedule.loc[pd.Timestamp(today_date)]
    open_sec = row["open"].hour * 3600 + row["open"].minute * 60
    close_sec = row["close"].hour * 3600 + row["close"].minute * 60

    if today_sec < open_sec:
        return "premarket"
    if today_sec >= close_sec:
        return "afterhours"
    return "closed"


def get_trading_hours_et() -> dict:
    cal = _get_cal()
    today = _ny_today()
    result = {"date": str(today), "is_trading_day": False, "open_et": None, "close_et": None}

    if cal is None:
        result["is_trading_day"] = _fallback_is_open(datetime.now(timezone.utc).astimezone(_NY_TZ))
        if result["is_trading_day"]:
            result["open_et"] = "09:30"
            result["close_et"] = "16:00"
        return result

    result["is_trading_day"] = cal.is_session(today)
    if result["is_trading_day"] and today in cal.schedule.index:
        row = cal.schedule.loc[pd.Timestamp(today)]
        result["open_et"] = row["open"].strftime("%H:%M")
        result["close_et"] = row["close"].strftime("%H:%M")
    return result


def minutes_until_open(dt: datetime = None) -> int:
    if dt is None:
        dt = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    et_dt = dt.astimezone(_NY_TZ)

    cal = _get_cal()
    if cal is None:
        return 0

    if cal.is_open_on_minute(et_dt):
        return -1

    today_date = et_dt.date()
    if cal.is_session(today_date):
        row = cal.schedule.loc[pd.Timestamp(today_date)]
        open_dt = row["open"]
        diff = (open_dt - et_dt).total_seconds() / 60
        if diff > 0:
            return int(diff)

    next_day = today_date
    for _ in range(7):
        next_day += timedelta(days=1)
        if cal.is_session(next_day):
            row = cal.schedule.loc[pd.Timestamp(next_day)]
            open_dt = row["open"]
            diff = (open_dt - et_dt).total_seconds() / 60
            return int(diff)
    return 0


def last_trading_day() -> date:
    """回傳最近一個交易日（往回找最多 7 天）。"""
    cal = _get_cal()
    today = _ny_today()
    if cal is not None:
        for i in range(7):
            check = today - timedelta(days=i)
            if cal.is_session(check):
                return check
    for i in range(7):
        check = today - timedelta(days=i)
        if check.weekday() < 5:
            return check
    return today


def _fallback_is_open(et_dt: datetime) -> bool:
    if et_dt.weekday() > 4:
        return False
    hour = et_dt.hour
    minute = et_dt.minute
    if hour == 9:
        return minute >= 30
    if 10 <= hour < 16:
        return True
    return False
