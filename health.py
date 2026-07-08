"""外部監控 ping — 整合 healthchecks.io 免費方案。

用法：
    HEALTHCHECK_URL=https://hc-ping.com/your-uuid python scheduler.py

設定的話每個 cycle 會打一次 ping，掛掉時 healthchecks.io 發通知。
沒設定就略過。
"""

import logging
import requests

log = logging.getLogger(__name__)


def ping(state: str = ""):
    from config import Config
    url = Config().HEALTHCHECK_URL
    if not url:
        return
    full = f"{url}/{state}" if state else url
    try:
        requests.get(full, timeout=10)
    except requests.RequestException as e:
        log.debug(f"Healthcheck ping failed: {e}")
