import requests
import pandas as pd
import time

# ─── CONFIGURAZIONE ──────────────────────────────────────────────────────────
API_KEY     = "FIX9HNM1D5XAI9Y0"
TELEGRAM_TOKEN = "8753761075:AAEZHhEScWDBVwXSc1jTqOqfX9f6IMAflXc"  # Incolla qui il token di BotFather
CHAT_ID        = "817439734"     # Incolla qui il tuo Chat ID
TITOLI         = ["TSLA", "AAPL", "NVDA", "BTCUSD"]
# ──────────────────────────────────────────────────────────────────────────────

def send_telegram_msg(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    params = {"chat_id": CHAT_ID, "text": text}
    try:
        requests.get(url, params=params)
    except Exception as e:
        print(f"Errore invio Telegram: {e}")

def get_data_and_analyze(symbol):
    url = "https://www.alphavantage.co/query"
    params = {"function": "TIME_SERIES_DAILY", "symbol": symbol, "apikey": API_KEY}
    
    r = requests.get(url, params=params)
    data = r.json()
    
    if "Time Series (Daily)" not in data:
        return None

    df = pd.DataFrame.from_dict(data["Time Series (Daily)"], orient="index")
    df = df.rename(columns={"4. close": "Close"}).apply(pd.to_numeric)
    df = df.sort_index()

    # 1. Calcolo RSI
    delta = df['Close'].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1/14, min_periods=14, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/14, min_periods=14, adjust=False).mean()
    df['RSI'] = 100 - (100 / (1 + (avg_gain / avg_loss)))

    # 2. Calcolo Bollinger Bands
    df['SMA20'] = df['Close'].rolling(window=20).mean()
    df['STD'] = df['Close'].rolling(window=20).std()
    df['Upper'] = df['SMA20'] + (df['STD'] * 2)
    df['Lower'] = df['SMA20'] - (df['STD'] * 2)

    last = df.iloc[-1]
    msg = None

    # LOGICA DI SEGNALE
    if last['Close'] < last['Lower'] and last['RSI'] < 30:
        msg = f"🟢 COMPRA {symbol}\nPrezzo: ${last['Close']:.2f}\nRSI: {last['RSI']:.2f}\nStatistica: Prezzo sotto banda inferiore."
    elif last['Close'] > last['Upper'] and last['RSI'] > 70:
        msg = f"🔴 VENDI {symbol}\nPrezzo: ${last['Close']:.2f}\nRSI: {last['RSI']:.2f}\nStatistica: Prezzo sopra banda superiore."
    
    return msg
if __name__ == "__main__":
    send_telegram_msg("🚀 Bot di Trading collegato correttamente!") # Aggiungi questa riga
    print("🤖 Bot avviato... Controllo in corso.")


    for s in TITOLI:
        print(f"Analizzando {s}...")
        segnali = get_data_and_analyze(s)
        if segnali:
            send_telegram_msg(segnali)
            print(f"!!! Segnale inviato per {s}")
        time.sleep(15) # Per non bloccare l'API gratuita
    print("✅ Analisi completata.")
