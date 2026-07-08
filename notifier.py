"""Telegram 通知 — 重要事件送 bot 訊息。

需要 .env 設定：
    TELEGRAM_BOT_TOKEN=xxx
    TELEGRAM_CHAT_ID=xxx

沒設定就略過。
"""

import html
import logging

log = logging.getLogger(__name__)


MAX_MSG_LEN = 4000


def send_message(text: str):
    from config import Config
    cfg = Config()
    bot_token = cfg.TELEGRAM_BOT_TOKEN
    chat_id = cfg.TELEGRAM_CHAT_ID
    if not bot_token or not chat_id:
        return

    import requests
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    chunks = [text[i:i + MAX_MSG_LEN] for i in range(0, len(text), MAX_MSG_LEN)]
    for chunk in chunks:
        try:
            safe_text = html.escape(chunk)
            payload = {"chat_id": chat_id, "text": safe_text, "parse_mode": "HTML"}
            resp = requests.post(url, json=payload, timeout=10)
            if resp.status_code != 200:
                log.warning(f"Telegram send failed: {resp.status_code} {resp.text[:200]}")
        except Exception as e:
            log.warning(f"Telegram send error: {e}")
