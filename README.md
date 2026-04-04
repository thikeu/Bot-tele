# 🤖 Bot Tín Hiệu Trading MEXC → Telegram

Bot tự động phân tích thị trường và gửi tín hiệu trading **LONG/SHORT** qua Telegram, chạy **miễn phí** trên GitHub Actions mỗi 15 phút.

## 📊 Chiến lược

| Chỉ báo | Khung | Vai trò |
|---|---|---|
| **EMA 50** | 1H | Bộ lọc xu hướng chính |
| **SuperTrend (10,3)** | 15M | Tín hiệu vào lệnh dứt khoát |
| **RSI (14)** | 15M | Lọc nhiễu, tránh đỉnh/đáy |

**Logic:**
- ✅ **LONG**: SuperTrend đảo chiều lên + Giá 1H trên EMA50 + RSI < 70
- ✅ **SHORT**: SuperTrend đảo chiều xuống + Giá 1H dưới EMA50 + RSI > 30

---

## 🚀 Hướng dẫn cài đặt

### Bước 1: Lấy thông tin Telegram

1. Tạo bot: Nhắn tin `/newbot` cho [@BotFather](https://t.me/BotFather) → Lấy **TELEGRAM_TOKEN**
2. Lấy Chat ID: Nhắn tin `/start` cho [@userinfobot](https://t.me/userinfobot) → Lấy **TELEGRAM_CHAT_ID**

### Bước 2: Chạy thử trên máy tính

```bash
# 1. Cài đặt thư viện
pip install -r requirements.txt

# 2. Tạo file .env từ mẫu
copy .env.example .env   # Windows
# cp .env.example .env   # Mac/Linux

# 3. Mở .env và điền token thật của bạn vào

# 4. Chạy bot
python bot.py
```

### Bước 3: Tự động hóa qua GitHub Actions (Miễn phí)

1. **Tạo repository mới** trên GitHub (có thể để Private)

2. **Đẩy code lên:**

```bash
git init
git add .
git commit -m "feat: initial trading bot setup"
git branch -M main
git remote add origin https://github.com/TEN_BAN/TEN_REPO.git
git push -u origin main
```

3. **Thêm Secrets trên GitHub:**
   - Vào repo → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**
   - Thêm 3 secrets:
     - `TELEGRAM_TOKEN` = token bot của bạn
     - `TELEGRAM_CHAT_ID` = chat ID của bạn
     - `ACCOUNT_BALANCE` = 1000 (vốn giả lập)

4. **Kích hoạt Actions:**
   - Vào tab **Actions** → Chọn workflow → **Enable workflow**
   - Bot sẽ tự động chạy mỗi 15 phút!

---

## 📱 Mẫu tin nhắn Telegram

```
🟢 TÍN HIỆU LONG (MUA): BTC/USDT
==============================
📌 Giá Entry: 65000.1234 USDT
🛑 Cắt lỗ (SL): 64200.0000 (-1.23%)
🎯 Chốt lời (TP 1:2): 66600.0000 (+2.46%)
⚖️ Khối lượng: 0.0125 BTC
==============================
📊 RSI: 55.3 | ATR: 350.1234
🕐 EMA50 (1H): 63500.0000
⚠️ Rủi ro lệnh này: 10.00$ (1%)
⏰ 2025-01-15 14:30:00
```

---

## ⚙️ Tùy chỉnh

Mở file `bot.py` và chỉnh các thông số đầu file:

```python
# Thêm/bớt các cặp coin muốn theo dõi
SYMBOLS = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT']

# Tỷ lệ rủi ro (1% = 0.01)
RISK_PERCENT = 0.01

# Tỷ lệ lợi nhuận/rủi ro
RR_RATIO = 2.0
```

---

## ⚠️ Tuyên bố miễn trách

> Bot này chỉ cung cấp **thông tin phân tích kỹ thuật** không phải lời khuyên tài chính. Hãy luôn tự nghiên cứu và quản lý rủi ro cẩn thận.
