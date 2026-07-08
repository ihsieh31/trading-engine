#!/bin/bash
set -e
cd "$(dirname "$0")"

RED='\033[0;31m'; GREEN='\033[0;32m'; CYAN='\033[0;36m'; YELLOW='\033[1;33m'; NC='\033[0m'
ok()   { echo -e "${GREEN}✅${NC} $1"; }
err()  { echo -e "${RED}❌${NC} $1"; }
info() { echo -e "${CYAN}$1${NC}"; }
warn() { echo -e "${YELLOW}$1${NC}"; }

LANG_ZH="zh"; LANG_EN="en"; L=""

t() { local en="$1" zh="$2"; [ "$L" = "$LANG_ZH" ] && echo "$zh" || echo "$en"; }

ask() {
    local prompt="$1" default="$2"
    read -p "$prompt " val
    echo "${val:-$default}"
}

ask_secret() {
    read -s -p "$1" val; echo; printf '%s\n' "$val"
}

# ── virtualenv ──
if [ ! -d ".venv" ]; then
    python3 -m venv .venv
fi
source .venv/bin/activate

# ── menu ──
menu() {
    while true; do
        echo ""
        info "$(t "========================================" "========================================")"
        info "$(t "         Trading Engine Menu" "         Trading Engine 選單")"
        info "$(t "========================================" "========================================")"
        echo "  1) $(t "Backtest" "歷史回測")"
        echo "  2) $(t "Deep Analysis" "單次深度分析")"
        echo "  3) $(t "Start Monitor (Full Auto)" "啟動全自動交易")"
        echo "  4) $(t "Dashboard (Web UI)" "Web 監控面板")"
        echo "  5) $(t "Setup / Reconfigure" "重新設定")"
        echo "  6) $(t "Exit" "離開")"
        read -p "$(t "  Choice [1-6]: " "  選擇 [1-6]: ")" ch
        case $ch in
            1) python backtest.py;;
            2) python deep_analyzer.py;;
            3) info "$(t "Starting scheduler (Ctrl+C to stop)..." "啟動排程器 (Ctrl+C 停止)...")"; exec python scheduler.py;;
            4) info "$(t "Starting dashboard..." "啟動儀表板...")"; python dashboard.py;;
            5) read -p "$(t "  Confirm delete .env and reconfigure? (y/N): " "  確定刪除 .env 重新設定？(y/N): ")" confirm; [ "$confirm" = "y" ] || [ "$confirm" = "Y" ] && rm -f .env && exec bash "$0";;
            *) exit 0;;
        esac
    done
}

# ── 已有設定 → 選單 ──
if [ -f ".env" ]; then
    menu
    exit 0
fi

# ══════════════════════════════════════════════
#  首次設定
# ══════════════════════════════════════════════
echo ""
info "$(t "========================================" "========================================")"
info "$(t "   Trading Engine — First-Time Setup" "   Trading Engine — 首次設定")"
info "$(t "========================================" "========================================")"
echo ""

# ── 1. 語言 ──
echo "$(t "Select language:" "選擇語言：")"
echo "  1) English"
echo "  2) 中文"
read -p "$(t "  Choice [1/2]: " "  選擇 [1/2]: ")" lc
[ "$lc" = "2" ] && L="$LANG_ZH" || L="$LANG_EN"
echo ""

# ── 2. LLM ──
info "$(t "── Step 1/5: LLM (Required) ──" "── 步驟 1/5：LLM（必要）──")"
echo "$(t "  Any OpenAI-compatible API will work (OpenAI, Anthropic, Groq, DeepSeek, etc.)" "  任何相容 OpenAI 格式的 API 都可使用（OpenAI、Anthropic、Groq、DeepSeek 等）")"
echo ""
LLM_KEY=""; LLM_URL=""; DEEP_MODEL=""; QUICK_MODEL=""
while [ -z "$LLM_KEY" ]; do
    LLM_KEY=$(ask_secret "  API Key: ")
    [ -z "$LLM_KEY" ] && err "$(t "Required" "必填")"
done
echo ""
LLM_URL=$(ask "$(t "  API Endpoint" "  API 端點網址"):" "")
DEEP_MODEL=$(ask "$(t "  Model for deep analysis" "  深度分析模型"):" "")
QUICK_MODEL=$(ask "$(t "  Model for quick tasks" "  快速任務模型"):" "")
echo ""

# ── 3. Alpaca ──
info "$(t "── Step 2/5: Alpaca Broker API (Required) ──" "── 步驟 2/5：Alpaca 券商 API（必要）──")"
echo ""
echo "$(t "  Alpaca provides free paper trading accounts." "  Alpaca 提供免費紙上交易（Paper Trading）帳戶。")"
echo "$(t "  You get \$100,000 virtual money to test the system." "  內含 $100,000 虛擬資金，可完整測試系統。")"
echo "$(t "  No real money required, no credit card needed." "  不需真實資金，不需綁信用卡。")"
echo ""
echo "  $(t "Steps:" "申請步驟：")"
echo "    1. $(t "Go to https://alpaca.markets and sign up" "前往 https://alpaca.markets 註冊")"
echo "    2. $(t "Verify your email" "驗證 Email")"
echo "    3. $(t "Go to Paper Trading → API Keys" "進入 Paper Trading → API Keys")"
echo "    4. $(t "Click \"Generate Key\"" "點「Generate Key」產生金鑰")"
echo "    5. $(t "Copy both Key and Secret Key below" "將 Key 和 Secret Key 貼到下方")"
echo ""
ALPACA_KEY=""; ALPACA_SECRET=""
while [ -z "$ALPACA_KEY" ]; do
    ALPACA_KEY=$(ask "$(t "  API Key" "  API Key"):" "")
    [ -z "$ALPACA_KEY" ] && err "$(t "  Required" "  必填")"
done
while [ -z "$ALPACA_SECRET" ]; do
    ALPACA_SECRET=$(ask_secret "$(t "  Secret Key: " "  Secret Key: ")")
    echo
    [ -z "$ALPACA_SECRET" ] && err "$(t "  Required" "  必填")"
done
echo ""

# ── 4. 新聞 ──
info "$(t "── Step 3/5: News API (Optional, but recommended) ──" "── 步驟 3/5：新聞 API（建議至少申請一個）──")"
echo ""
echo "$(t "  Used to fetch latest news for stocks being analyzed." "  用於取得個股最新新聞，幫助 LLM 分析。")"
echo ""

warn "$(t "  [Tavily]" "  [Tavily]")"
echo "    $(t "URL: https://tavily.com" "網址：https://tavily.com")"
echo "    $(t "Free: 1,000 requests/month, no credit card needed" "免費：每月 1000 次，不需信用卡")"
TAVILY=$(ask "  Tavily$(t " API Keys (comma-separated for multiple)" " API Keys（多 Key 用逗號分隔）"):" "")
echo ""

warn "$(t "  [Brave Search]" "  [Brave Search]")"
echo "    $(t "URL: https://brave.com/search/api/" "網址：https://brave.com/search/api/")"
echo "    $(t "Free: 2,000 requests/month, no credit card needed" "免費：每月 2000 次，不需信用卡")"
BRAVE=$(ask "  Brave$(t " API Key" " API Key"):" "")
echo ""

warn "$(t "  [SerpAPI]" "  [SerpAPI]")"
echo "    $(t "URL: https://serpapi.com" "網址：https://serpapi.com")"
echo "    $(t "Free: 100 searches/month" "免費：每月 100 次")"
SERPAPI=$(ask "  SerpAPI$(t " API Key" " API Key"):" "")
echo ""

# ── 5. Telegram ──
info "$(t "── Step 4/5: Telegram Notifications (Optional) ──" "── 步驟 4/5：Telegram 通知（選填）──")"
echo ""
echo "$(t "  Receive trade alerts and daily reports on Telegram." "  可接收交易通知與每日報表。")"
echo ""
echo "  $(t "Steps:" "設定步驟：")"
echo "    1. $(t "Open Telegram, search for @BotFather" "開啟 Telegram，搜尋 @BotFather")"
echo "    2. $(t "Send /newbot and follow instructions" "輸入 /newbot 依指示建立 Bot")"
echo "    3. $(t "Copy the bot token (looks like: 123456:ABC-DEF...)" "複製 Bot Token（格式：123456:ABC-DEF...）")"
echo "    4. $(t "Message your bot something (anything)" "對你的 Bot 隨便發一則訊息")"
echo "    5. $(t "Visit this URL in browser (replace <token>):" "在瀏覽器打開以下網址（換成你的 token）：")"
echo "       https://api.telegram.org/bot<token>/getUpdates"
echo "    6. $(t "Find your Chat ID in the JSON response (\"chat\":{\"id\":123...})" "在 JSON 回應中找到 chat.id")"
echo ""
TELEGRAM_BOT=$(ask "  Telegram Bot Token:" "")
TELEGRAM_CHAT=$(ask "  Telegram Chat ID:" "")
echo ""

# ══════════════════════════════════════════════
#  產生 .env
# ══════════════════════════════════════════════
info "$(t "── Step 5/5: Generating config..." "── 步驟 5/5：產生設定檔...")"

cat > .env << EOF
# === LLM ===
OPENAI_COMPATIBLE_API_KEY=$LLM_KEY
LLM_BACKEND_URL=$LLM_URL
DEEP_THINK_MODEL=$DEEP_MODEL
QUICK_THINK_MODEL=$QUICK_MODEL

# === Alpaca ===
ALPACA_API_KEY=$ALPACA_KEY
ALPACA_API_SECRET=$ALPACA_SECRET
IS_PAPER=true

# === News ===
TAVILY_API_KEYS=$TAVILY
BRAVE_API_KEYS=$BRAVE
SERPAPI_API_KEYS=$SERPAPI

# === Screening ===
UNIVERSE_SOURCE=sp500
SCREENER_TOP_N=15
SCREENER_WORKERS=10

# === Risk Management ===
INITIAL_CAPITAL=100000
MAX_POSITION_PCT=0.10
MAX_TOTAL_EXPOSURE=0.50
MAX_SECTOR_PCT=0.25
STOP_LOSS_PCT=0.05
TAKE_PROFIT_PCT=0.15
KELLY_FRACTION=0.25
MIN_POSITION_PCT=0.02
MAX_DAILY_LOSS_PCT=0.03
MAX_DRAWDOWN_PCT=0.15

# === Order Management ===
ORDER_MAX_RETRIES=3
ORDER_RETRY_DELAY_SEC=10
ORDER_FILL_TIMEOUT_SEC=300

# === Monitoring ===
MONITOR_INTERVAL_SECONDS=30
BUY_COOLDOWN_SECONDS=3600
GAP_ALERT_PCT=0.08
POSITION_NEWS_CHECK_INTERVAL_SEC=1800

# === Dashboard ===
DASHBOARD_PORT=8899

# === Knowledge Base ===
OBSIDIAN_VAULT_PATH=./knowledge

# === Paths ===
DATA_DIR=./data
HEALTHCHECK_URL=
TELEGRAM_BOT_TOKEN=$TELEGRAM_BOT
TELEGRAM_CHAT_ID=$TELEGRAM_CHAT
EOF

ok "$(t "Configuration saved to .env" ".env 已產生")"
echo ""

# ── 安裝 ──
info "$(t "Installing dependencies..." "安裝依賴套件中...")"
pip install -q -r requirements.txt
ok "$(t "Dependencies installed" "依賴安裝完成")"
echo ""

# ── 健康檢查 ──
if [ -f "dry_run.py" ]; then
    info "$(t "Running health check..." "執行健康檢查...")"
    python dry_run.py || true
    echo ""
fi

ok "$(t "Setup complete!" "設定完成！")"

# ── 進入選單 ──
menu
