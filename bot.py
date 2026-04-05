import ccxt
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

# Dùng Binance làm primary, Bybit làm fallback
# (Binance hay block Azure IPs của GitHub Actions)
exchange_binance = ccxt.binance({
    'timeout': 30000,
    'enableRateLimit': True,
})
exchange_bybit = ccxt.bybit({
    'timeout': 30000,
    'enableRateLimit': True,
})

def fetch_ohlcv_with_fallback(symbol: str, timeframe: str, limit: int):
    """Thử Binance trước, nếu lỗi thì dùng Bybit."""
    # Bybit dùng format BTCUSDT thay BTUSDT/USDT
    bybit_symbol = symbol.replace('/', '')
    try:
        data = exchange_binance.fetch_ohlcv(symbol, timeframe, limit=limit)
        if data:
            return data
    except Exception as e:
        print(f"   ⚠️  Binance lỗi ({e}), thử Bybit...")
    try:
        data = exchange_bybit.fetch_ohlcv(bybit_symbol, timeframe, limit=limit)
        return data
    except Exception as e2:
        raise Exception(f"Binance và Bybit đều lỗi: {e2}")

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


def calc_supertrend(high: pd.Series, low: pd.Series, close: pd.Series,
                    period: int = 10, multiplier: float = 3.0):
    """
    Tính SuperTrend.
    Trả về Series direction: 1 = uptrend (giá trên ST), -1 = downtrend.
    """
    atr = calc_atr(high, low, close, period)
    hl_avg = (high + low) / 2

    upper_band = hl_avg + multiplier * atr
    lower_band = hl_avg - multiplier * atr

    # Tính supertrend iteratively
    direction = pd.Series(index=close.index, dtype=float)
    supertrend = pd.Series(index=close.index, dtype=float)

    for i in range(1, len(close)):
        # Lower band (support khi uptrend)
        if lower_band.iloc[i] > lower_band.iloc[i - 1] or close.iloc[i - 1] < lower_band.iloc[i - 1]:
            lb = lower_band.iloc[i]
        else:
            lb = lower_band.iloc[i - 1]

        # Upper band (resistance khi downtrend)
        if upper_band.iloc[i] < upper_band.iloc[i - 1] or close.iloc[i - 1] > upper_band.iloc[i - 1]:
            ub = upper_band.iloc[i]
        else:
            ub = upper_band.iloc[i - 1]

        lower_band.iloc[i] = lb
        upper_band.iloc[i] = ub

        # Xác định hướng
        prev_st = supertrend.iloc[i - 1] if i > 1 else ub
        if prev_st == upper_band.iloc[i - 1]:
            # Đang downtrend
            if close.iloc[i] > ub:
                direction.iloc[i] = 1
                supertrend.iloc[i] = lb
            else:
                direction.iloc[i] = -1
                supertrend.iloc[i] = ub
        else:
            # Đang uptrend
            if close.iloc[i] < lb:
                direction.iloc[i] = -1
                supertrend.iloc[i] = ub
            else:
                direction.iloc[i] = 1
                supertrend.iloc[i] = lb

    return direction


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
    print(f"📊 Đang phân tích {symbol}...")
    print(f"⏰ {now_vn()} (UTC+7)")

    global _last_summary
    _last_summary = f"⚠️ <b>{symbol}</b>: lỗi kết nối"

    try:
        ohlcv_1h = fetch_ohlcv_with_fallback(symbol, '1h', limit=100)
        ohlcv_15m = fetch_ohlcv_with_fallback(symbol, '15m', limit=100)
    except Exception as e:
        print(f"❌ Lỗi lấy dữ liệu: {e}")
        _last_summary = f"⚠️ <b>{symbol}</b>: lỗi lấy data"
        return None


    if len(ohlcv_1h) < 60 or len(ohlcv_15m) < 20:
        print("⚠️  Không đủ dữ liệu.")
        _last_summary = f"⚠️ <b>{symbol}</b>: không đủ dữ liệu"
        return None

    cols = ['timestamp', 'open', 'high', 'low', 'close', 'volume']
    df_1h = pd.DataFrame(ohlcv_1h, columns=cols).astype({'open': float, 'high': float, 'low': float, 'close': float})
    df_15m = pd.DataFrame(ohlcv_15m, columns=cols).astype({'open': float, 'high': float, 'low': float, 'close': float})

    # Tính chỉ báo
    df_1h['ema_50'] = calc_ema(df_1h['close'], 50)
    df_15m['rsi'] = calc_rsi(df_15m['close'], 14)
    df_15m['atr'] = calc_atr(df_15m['high'], df_15m['low'], df_15m['close'], 14)
    df_15m['st_dir'] = calc_supertrend(df_15m['high'], df_15m['low'], df_15m['close'], 10, 3.0)

    # Nến đã đóng gần nhất (iloc[-2]) và trước đó (iloc[-3])
    last_1h  = df_1h.iloc[-2]
    last_15m = df_15m.iloc[-2]
    prev_15m = df_15m.iloc[-3]

    current_price = float(last_15m['close'])
    ema50   = float(last_1h['ema_50'])
    rsi_val = float(last_15m['rsi'])
    atr_val = float(last_15m['atr'])

    if any(np.isnan(v) for v in [ema50, rsi_val, atr_val]):
        print("⚠️  Dữ liệu chỉ báo bị NaN. Bỏ qua.")
        _last_summary = f"⚠️ <b>{symbol}</b>: NaN indicators"
        return None

    is_uptrend   = last_1h['close'] > ema50
    is_downtrend = last_1h['close'] < ema50
    st_buy  = (prev_15m['st_dir'] == -1) and (last_15m['st_dir'] == 1)
    st_sell = (prev_15m['st_dir'] == 1)  and (last_15m['st_dir'] == -1)

    trend_icon = "📈" if is_uptrend else "📉"
    st_icon = "🔺" if float(last_15m['st_dir']) == 1 else "🔻"
    # Luôn lưu summary ngay sau khi tính xong chỉ báo
    _last_summary = (
        f"{trend_icon} <b>{symbol}</b>: {current_price:.2f} | EMA50:{ema50:.2f}\n"
        f"   RSI:{rsi_val:.1f} | ATR:{atr_val:.4f} | ST:{st_icon}"
    )

    trend_txt = "📈 UPTREND" if is_uptrend else "📉 DOWNTREND"
    print(f"   💰 Giá: {current_price:.4f}  |  EMA50(1H): {ema50:.4f}")
    print(f"   ⚡ RSI: {rsi_val:.2f}  |  ATR: {atr_val:.4f}")
    print(f"   🔍 Xu hướng 1H: {trend_txt}  |  ST↑:{st_buy}  ST↓:{st_sell}")

    risk_amount = ACCOUNT_BALANCE * RISK_PERCENT

    # ---- LONG ----
    if st_buy and is_uptrend and rsi_val < 70:
        sl_price = df_15m['low'].tail(10).min() - atr_val * 0.5
        dist = current_price - sl_price
        if dist > 0:
            tp_price = current_price + dist * RR_RATIO
            volume   = risk_amount / dist
            msg = (
                f"🟢 <b>TÍN HIỆU LONG: {symbol}</b>\n"
                f"{'='*30}\n"
                f"📌 Entry: <b>{current_price:.4f}</b>\n"
                f"🛑 SL:    <b>{sl_price:.4f}</b> (-{dist/current_price*100:.2f}%)\n"
                f"🎯 TP 1:{RR_RATIO}: <b>{tp_price:.4f}</b> (+{(tp_price-current_price)/current_price*100:.2f}%)\n"
                f"⚖️ Khối lượng: <b>{volume:.4f} {symbol.split('/')[0]}</b>\n"
                f"{'='*30}\n"
                f"RSI: {rsi_val:.1f} | ATR: {atr_val:.4f} | EMA50: {ema50:.4f}\n"
                f"<i>⚠️ Rủi ro: {risk_amount:.2f}$ ({RISK_PERCENT*100:.0f}%)</i>\n"
                f"<i>⏰ {now_vn()} (ICT)</i>"
            )
            send_telegram(msg)
            return "LONG"

    # ---- SHORT ----
    elif st_sell and is_downtrend and rsi_val > 30:
        sl_price = df_15m['high'].tail(10).max() + atr_val * 0.5
        dist = sl_price - current_price
        if dist > 0:
            tp_price = current_price - dist * RR_RATIO
            volume   = risk_amount / dist
            msg = (
                f"🔴 <b>TÍN HIỆU SHORT: {symbol}</b>\n"
                f"{'='*30}\n"
                f"📌 Entry: <b>{current_price:.4f}</b>\n"
                f"🛑 SL:    <b>{sl_price:.4f}</b> (+{dist/current_price*100:.2f}%)\n"
                f"🎯 TP 1:{RR_RATIO}: <b>{tp_price:.4f}</b> (-{(current_price-tp_price)/current_price*100:.2f}%)\n"
                f"⚖️ Khối lượng: <b>{volume:.4f} {symbol.split('/')[0]}</b>\n"
                f"{'='*30}\n"
                f"RSI: {rsi_val:.1f} | ATR: {atr_val:.4f} | EMA50: {ema50:.4f}\n"
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
        # Gửi tóm tắt thị trường định kỳ dù không có tín hiệu
        summary_lines = "\n".join(summaries)
        msg = (
            f"📊 <b>Tóm tắt thị trường</b>\n"
            f"{'='*28}\n"
            f"{summary_lines}\n"
            f"{'='*28}\n"
            f"<i>⏰ {now_vn()} (ICT) | Không có tín hiệu</i>"
        )
        send_telegram(msg)
        print("ℹ️  Không có tín hiệu. Đã gửi tóm tắt Telegram.")
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

