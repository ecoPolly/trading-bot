import requests
import pandas as pd
import time
import os

# ─── CONFIGURAZIONE ──────────────────────────────────────────────────────────
API_KEY = os.getenv("ALPHA_VANTAGE_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

# Usiamo un dizionario: "TICKER": SOGLIA_RSI_PERSONALIZZATA
TITOLI = {
    "NVDA": 30, "VRT": 35,   # AI & Cooling
    "CCJ": 40, "SMR": 35,    # Uranio & Nucleare (Soglia più alta perché "caldi")
    "FCX": 40, "ALB": 35,    # Metalli (Rame e Litio)
    "TSLA": 30, "BTC": 30,   # Volatili
    "ASML": 30, "QQQ": 30,   # Semiconduttori e Indice Tech
    "SPY": 30, "SRUUF": 40   # S&P500 e Uranio Fisico
}
# ──────────────────────────────────────────────────────────────────────────────

def send_telegram_msg(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    params = {"chat_id": CHAT_ID, "text": text}
    try:
        requests.get(url, params=params)
    except Exception as e:
        print(f"Errore invio Telegram: {e}")

def get_data_and_analyze(symbol, rsi_threshold):
    url = "https://www.alphavantage.co/query"
    params = {"function": "TIME_SERIES_DAILY", "symbol": symbol, "apikey": API_KEY, "outputsize": "full"} # "full" serve per la SMA200
    
    r = requests.get(url, params=params)
    data = r.json()
    
    if "Time Series (Daily)" not in data:
        print(f"⚠️ Errore dati per {symbol}: {data.get('Note', 'Limite API o simbolo errato')}")
        return None

    # Trasformazione dati
    df = pd.DataFrame.from_dict(data["Time Series (Daily)"], orient="index")
    df = df.rename(columns={
        "4. close": "Close",
        "5. volume": "Volume"
    }).apply(pd.to_numeric)
    df = df.sort_index()

    # 1. Calcolo RSI (Standard 14 periodi)
    delta = df['Close'].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1/14, min_periods=14, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/14, min_periods=14, adjust=False).mean()
    df['RSI'] = 100 - (100 / (1 + (avg_gain / avg_loss)))

    # 2. Media Mobile 200 (SMA200) - Indica il trend di lungo periodo
    df['SMA200'] = df['Close'].rolling(window=200).mean()

    # 3. Media Volumi 20 giorni - Per capire se l'interesse aumenta
    df['Avg_Vol'] = df['Volume'].rolling(window=20).mean()

    # 4. Bollinger Bands (20 periodi)
    df['SMA20'] = df['Close'].rolling(window=20).mean()
    df['STD'] = df['Close'].rolling(window=20).std()
    df['Lower'] = df['SMA20'] - (df['STD'] * 2)

    last = df.iloc[-1]
    
    # --- LOGICA DI CONFLUENZA MIGLIORATA ---
    # Cerchiamo: RSI basso + Prezzo vicino/sotto Banda Inferiore
    if last['RSI'] < rsi_threshold or last['Close'] <= last['Lower']:
        status = "🟢 SEGNALE DI ACQUISTO"
        trend = "SOPRA la SMA200 (Trend Rialzista ✅)" if last['Close'] > last['SMA200'] else "SOTTO la SMA200 (Trend Debole ⚠️)"
        volume_status = "ALTI 📈" if last['Volume'] > last['Avg_Vol'] else "Normali"

        msg = (f"{status} per {symbol}\n"
               f"💰 Prezzo: ${last['Close']:.2f}\n"
               f"📉 RSI: {last['RSI']:.2f} (Soglia: {rsi_threshold})\n"
               f"🏟️ Trend: {trend}\n"
               f"📊 Volumi: {volume_status}\n"
               f"💡 Nota: Prezzo vicino alla banda di Bollinger inferiore.")
        return msg
    
    return None

if __name__ == "__main__":
    print("🤖 Bot avviato... Controllo Watchlist Strategica.")
    
    for s, soglia in TITOLI.items():
        print(f"Analizzando {s} (Soglia RSI: {soglia})...")
        segnali = get_data_and_analyze(s, soglia)
        if segnali:
            send_telegram_msg(segnali)
            print(f"!!! Segnale inviato per {s}")
        
        # Fondamentale per la versione Free di Alpha Vantage (5 req/min)
        # Attendiamo 15 secondi tra un titolo e l'altro
        time.sleep(15) 
        
    print("✅ Analisi completata.")
