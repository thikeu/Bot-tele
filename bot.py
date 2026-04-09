import pandas as pd
import numpy as np
import requests
import os
import sys
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv

# Tự động đọc file .env (nếu có) — dùng cho local dev
load_dotenv()

# Múi giờ Việt Nam UTC+7
VN_TZ = timezone(timedelta(hours=7))
def now_vn():
    return datetime.now(VN_TZ).strftime('%Y-%m-%d %H:%M:%S')

# Fix encoding emoji trên Windows PowerShell
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')


# ==========================================
# 1. CẤU HÌNH CƠ BẢN
# ==========================================
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN', 'ĐIỀN_BOT_TOKEN_CỦA_BẠN_VÀO_ĐÂY')
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID', 'ĐIỀN_CHAT_ID_CỦA_BẠN_VÀO_ĐÂY')

# Các cặp coin muốn theo dõi (thêm/bớt tùy ý)
SYMBOLS = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT']

ACCOUNT_BALANCE = float(os.environ.get('ACCOUNT_BALANCE', '1000'))
RISK_PERCENT = 0.01   # Rủi ro 1% tài khoản
RR_RATIO = 2.0        # Tỷ lệ TP:SL = 1:2

# OKX public API — không cần API key, không block GitHub Actions cloud IPs
# interval mapping: '1h' -> '1H', '15m' -> '15m'
OKX_BASE = 'https://www.okx.com'

def _interval_to_okx(interval: str) -> str:
    """Chuyển interval sang format OKX: '1h' -> '1H', '15m' -> '15m'"""
    return interval.upper() if interval.endswith('h') else interval

def fetch_ohlcv_direct(symbol: str, interval: str, limit: int = 100):
    """
    Fetch OHLCV từ OKX public API.
    Trả về list [[timestamp_ms, open, high, low, close, volume], ...]
    OKX trả về newest-first nên cần reverse lại.
    """
    okx_symbol = symbol.replace('/', '-')   # BTC/USDT -> BTC-USDT
    okx_bar = _interval_to_okx(interval)    # 1h -> 1H, 15m -> 15m
    headers = {'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36'}

    # Thử OKX trước
    try:
        resp = requests.get(
            f"{OKX_BASE}/api/v5/market/candles",
            params={'instId': okx_symbol, 'bar': okx_bar, 'limit': str(limit)},
            headers=headers, timeout=20
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get('code') == '0' and data.get('data'):
            raw = data['data']
            # OKX format: [ts, open, high, low, close, vol, volCcy, ...]
            # newest first → reverse
            result = [[int(k[0]), float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5])] for k in raw]
            result.reverse()
            return result
    except Exception as e:
        print(f"   ⚠️  OKX lỗi: {e}, thử Binance...")

    # Fallback: Binance direct REST
    bin_symbol = symbol.replace('/', '')    # BTC/USDT -> BTCUSDT
    for host in ['https://api.binance.com', 'https://api1.binance.com', 'https://api2.binance.com']:
        try:
            resp = requests.get(
                f"{host}/api/v3/klines",
                params={'symbol': bin_symbol, 'interval': interval, 'limit': limit},
                headers=headers, timeout=20
            )
            resp.raise_for_status()
            raw = resp.json()
            return [[int(k[0]), float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5])] for k in raw]
        except Exception as e2:
            print(f"   ⚠️  {host} lỗi: {e2}")

    raise Exception(f"OKX và Binance đều không kết nối được")


# Biến lưu tóm tắt chỉ báo của coin vừa phân tích xong
_last_summary = ""


# ==========================================
# 2. TÍNH TOÁN CHỈ BÁO (Thuần Pandas/NumPy)
# ==========================================
def calc_ema(series: pd.Series, period: int) -> pd.Series:
    """Tính EMA (Exponential Moving Average)."""
    return series.ewm(span=period, adjust=False).mean()


def calc_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """Tính RSI (Relative Strength Index)."""
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(span=period, adjust=False).mean()
    avg_loss = loss.ewm(span=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def calc_atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    """Tính ATR (Average True Range)."""
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs()
    ], axis=1).max(axis=1)
    return tr.ewm(span=period, adjust=False).mean()


def calc_bollinger_bands(close: pd.Series, period: int = 20, num_std: float = 2.0):
    """Tính Bollinger Bands."""
    sma = close.rolling(window=period).mean()
    std = close.rolling(window=period).std()
    upper_band = sma + (std * num_std)
    lower_band = sma - (std * num_std)
    return lower_band, upper_band


# ==========================================
# 3. HÀM GỬI TIN NHẮN TELEGRAM
# ==========================================
def send_telegram(message: str):
    if TELEGRAM_TOKEN == 'ĐIỀN_BOT_TOKEN_CỦA_BẠN_VÀO_ĐÂY':
        print("⚠️  Chưa cấu hình TELEGRAM_TOKEN.")
        print(f"--- NỘI DUNG ---\n{message}\n----------------")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"}
    try:
        resp = requests.post(url, json=payload, timeout=10)
        resp.raise_for_status()
        print("✅ Đã gửi Telegram!")
    except Exception as e:
        print(f"❌ Lỗi gửi Telegram: {e}")


# ==========================================
# 4. PHÂN TÍCH TÍN HIỆU
# ==========================================
def fetch_data_and_analyze(symbol: str):
    print(f"\n{'='*50}")
    print(f"📊 Đang phân tích {symbol} (Chiến lược BB/RSI 5m + Xu hướng 1H)...")
    print(f"⏰ {now_vn()} (UTC+7)")

    global _last_summary
    _last_summary = f"⚠️ <b>{symbol}</b>: lỗi kết nối"

    try:
        ohlcv_1h = fetch_ohlcv_direct(symbol, '1h', limit=100)
        ohlcv_15m = fetch_ohlcv_direct(symbol, '15m', limit=100)
        ohlcv_5m = fetch_ohlcv_direct(symbol, '5m', limit=100)
    except Exception as e:
        print(f"❌ Lỗi lấy dữ liệu: {e}")
        _last_summary = f"⚠️ <b>{symbol}</b>: lỗi lấy data"
        return None

    if len(ohlcv_1h) < 60 or len(ohlcv_15m) < 20 or len(ohlcv_5m) < 30:
        print("⚠️  Không đủ dữ liệu.")
        _last_summary = f"⚠️ <b>{symbol}</b>: không đủ dữ liệu"
        return None

    cols = ['timestamp', 'open', 'high', 'low', 'close', 'volume']
    df_1h = pd.DataFrame(ohlcv_1h, columns=cols).astype({'open': float, 'high': float, 'low': float, 'close': float})
    df_15m = pd.DataFrame(ohlcv_15m, columns=cols).astype({'open': float, 'high': float, 'low': float, 'close': float})
    df_5m = pd.DataFrame(ohlcv_5m, columns=cols).astype({'open': float, 'high': float, 'low': float, 'close': float})

    # Tính chỉ báo
    df_1h['ema_50'] = calc_ema(df_1h['close'], 50)
    df_15m['atr'] = calc_atr(df_15m['high'], df_15m['low'], df_15m['close'], 14)
    # 5m
    df_5m['rsi'] = calc_rsi(df_5m['close'], 14)
    df_5m['bb_lower'], df_5m['bb_upper'] = calc_bollinger_bands(df_5m['close'], 20, 2.0)

    # Nến đã đóng gần nhất
    last_1h  = df_1h.iloc[-2]
    last_15m = df_15m.iloc[-2]
    last_5m = df_5m.iloc[-2]

    current_price = float(last_5m['close'])
    ema50   = float(last_1h['ema_50'])
    atr_val = float(last_15m['atr'])
    rsi_val = float(last_5m['rsi'])
    bb_lower = float(last_5m['bb_lower'])
    bb_upper = float(last_5m['bb_upper'])

    if any(np.isnan(v) for v in [ema50, rsi_val, atr_val, bb_lower, bb_upper]):
        print("⚠️  Dữ liệu chỉ báo bị NaN. Bỏ qua.")
        _last_summary = f"⚠️ <b>{symbol}</b>: NaN indicators"
        return None

    is_uptrend   = last_1h['close'] > ema50
    is_downtrend = last_1h['close'] < ema50

    trend_icon = "📈" if is_uptrend else "📉"
    _last_summary = (
        f"{trend_icon} <b>{symbol}</b>: {current_price:.2f} | EMA50(1H):{ema50:.2f}\n"
        f"   RSI(5m):{rsi_val:.1f} | BB_L:{bb_lower:.2f} | BB_U:{bb_upper:.2f}"
    )

    trend_txt = "📈 UPTREND" if is_uptrend else "📉 DOWNTREND"
    print(f"   💰 Giá(5m): {current_price:.4f}  |  EMA50(1H): {ema50:.4f}")
    print(f"   ⚡ RSI(5m): {rsi_val:.2f} | BB lower: {bb_lower:.4f} | BB upper: {bb_upper:.4f}")
    print(f"   🔍 Xu hướng 1H: {trend_txt}")

    risk_amount = ACCOUNT_BALANCE * RISK_PERCENT

    # Xét giá trị nến 5m gần nhất
    touched_lower = float(last_5m['low']) <= bb_lower
    touched_upper = float(last_5m['high']) >= bb_upper

    # ---- LONG ----
    # Trend 1H Tăng + Nến 5m đâm xuống BB lower + RSI quá bán
    long_cond = is_uptrend and touched_lower and rsi_val < 35

    # ---- SHORT ----
    # Trend 1H Giảm + Nến 5m đâm lên BB upper + RSI quá mua
    short_cond = is_downtrend and touched_upper and rsi_val > 65

    if long_cond:
        # SL = 1.5 * ATR (15m) để tránh râu nến quét lãng xẹt
        sl_dist = atr_val * 1.5
        sl_price = current_price - sl_dist
        tp1_price = current_price + sl_dist * 1.0 # 1:1
        tp2_price = current_price + sl_dist * 2.0 # 1:2
        tp3_price = current_price + sl_dist * 3.0 # 1:3
        
        volume = risk_amount / sl_dist
        msg = (
            f"🟢 <b>TÍN HIỆU LONG (Buy the Dip): {symbol}</b>\n"
            f"{'='*30}\n"
            f"📌 Entry (5m): <b>{current_price:.4f}</b>\n"
            f"🛑 SL: <b>{sl_price:.4f}</b> (-{sl_dist/current_price*100:.2f}%)\n"
            f"⚖️ Khối lượng: <b>{volume:.4f} {symbol.split('/')[0]}</b>\n"
            f"{'='*30}\n"
            f"🎯 <b>CÁC MỐC CHỐT LỜI (Scaled TPs):</b>\n"
            f"✅ <b>TP1 (50% Volume): {tp1_price:.4f}</b> (RR 1:1 - dời SL về Hoà vốn)\n"
            f"✅ <b>TP2 (25% Volume): {tp2_price:.4f}</b> (RR 1:2)\n"
            f"✅ <b>TP3 (25% Volume): {tp3_price:.4f}</b> (RR 1:3)\n"
            f"{'='*30}\n"
            f"RSI(5m): {rsi_val:.1f} | ATR(15m): {atr_val:.4f} | EMA50(1H): {ema50:.4f}\n"
            f"<i>⚠️ Rủi ro: {risk_amount:.2f}$ ({RISK_PERCENT*100:.0f}%)</i>\n"
            f"<i>⏰ {now_vn()} (ICT)</i>"
        )
        send_telegram(msg)
        return "LONG"

    elif short_cond:
        sl_dist = atr_val * 1.5
        sl_price = current_price + sl_dist
        tp1_price = current_price - sl_dist * 1.0
        tp2_price = current_price - sl_dist * 2.0
        tp3_price = current_price - sl_dist * 3.0
        
        volume = risk_amount / sl_dist
        msg = (
            f"🔴 <b>TÍN HIỆU SHORT (Sell the Rally): {symbol}</b>\n"
            f"{'='*30}\n"
            f"📌 Entry (5m): <b>{current_price:.4f}</b>\n"
            f"🛑 SL: <b>{sl_price:.4f}</b> (+{sl_dist/current_price*100:.2f}%)\n"
            f"⚖️ Khối lượng: <b>{volume:.4f} {symbol.split('/')[0]}</b>\n"
            f"{'='*30}\n"
            f"🎯 <b>CÁC MỐC CHỐT LỜI (Scaled TPs):</b>\n"
            f"✅ <b>TP1 (50% Volume): {tp1_price:.4f}</b> (RR 1:1 - dời SL về Hoà vốn)\n"
            f"✅ <b>TP2 (25% Volume): {tp2_price:.4f}</b> (RR 1:2)\n"
            f"✅ <b>TP3 (25% Volume): {tp3_price:.4f}</b> (RR 1:3)\n"
            f"{'='*30}\n"
            f"RSI(5m): {rsi_val:.1f} | ATR(15m): {atr_val:.4f} | EMA50(1H): {ema50:.4f}\n"
            f"<i>⚠️ Rủi ro: {risk_amount:.2f}$ ({RISK_PERCENT*100:.0f}%)</i>\n"
            f"<i>⏰ {now_vn()} (ICT)</i>"
        )
        send_telegram(msg)
        return "SHORT"

    print(f"   ℹ️  Không có tín hiệu cho {symbol}.")
    return None




# ==========================================
# 5. CHẠY CHƯƠNG TRÌNH
# ==========================================
def run_one_cycle():
    """Chạy 1 chu kỳ phân tích toàn bộ SYMBOLS."""
    signals = []
    summaries = []  # Tóm tắt chỉ báo để gửi Telegram

    for sym in SYMBOLS:
        try:
            result = fetch_data_and_analyze(sym)
            if result:
                signals.append(f"{sym}: {result}")
            # Thu thập tóm tắt chỉ báo từ lần phân tích vừa rồi
            summaries.append(_last_summary)
        except Exception as e:
            print(f"❌ Lỗi {sym}: {e}")
            summaries.append(f"❌ {sym}: lỗi")

    print(f"\n{'='*50}")
    if signals:
        print(f"🎯 {len(signals)} tín hiệu đã phát hiện:")
        for s in signals:
            print(f"   ✅ {s}")
    else:
        print("ℹ️  Không có tín hiệu lần này.")
    print("✅ Chu kỳ hoàn thành.\n")



if __name__ == "__main__":
    import time

    INTERVAL_MINUTES = 4
    IS_GITHUB_ACTIONS = os.environ.get('GITHUB_ACTIONS') == 'true'

    print("🤖 Bot Trading Binance Khởi Động!")
    print(f"   Vốn: {ACCOUNT_BALANCE}$ | Rủi ro: {RISK_PERCENT*100:.0f}%/lệnh | TP:SL = 1:{RR_RATIO}")
    print(f"   Theo dõi: {', '.join(SYMBOLS)}")

    # Chế độ test: py bot.py --test → gửi tin nhắn mẫu ngay lập tức
    if '--test' in sys.argv:
        print("\n🧪 Chế độ TEST — Đang gửi tin nhắn mẫu tới Telegram...")
        test_msg = (
            "✅ <b>TEST THÀNH CÔNG!</b>\n"
            "Bot Trading Binance đang hoạt động.\n"
            "========================\n"
            "🟢 TÍN HIỆU LONG MẪU: BTC/USDT\n"
            "📌 Entry: 67193.0000\n"
            "🛑 SL: 66500.0000 (-1.03%)\n"
            "🎯 TP: 68579.0000 (+2.06%)\n"
            "========================\n"
            f"<i>⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</i>"
        )
        send_telegram(test_msg)
        print("✅ Test hoàn thành. Kiểm tra Telegram của bạn!")
        sys.exit(0)


    if IS_GITHUB_ACTIONS:
        print("   ☁️  Chế độ: GitHub Actions (chạy 1 lần)")
        run_one_cycle()
        sys.exit(0)

    else:
        print(f"   🔄 Chế độ: Loop local — mỗi {INTERVAL_MINUTES} phút | Ctrl+C để dừng\n")
        while True:
            try:
                run_one_cycle()
                print(f"⏳ Nghỉ {INTERVAL_MINUTES} phút... (Ctrl+C để dừng)")
                time.sleep(INTERVAL_MINUTES * 60)
            except KeyboardInterrupt:
                print("\n🛑 Bot đã dừng theo yêu cầu.")
                sys.exit(0)

