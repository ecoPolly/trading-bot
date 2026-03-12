import requests
import pandas as pd
import time
import os

# ─── CONFIGURAZIONE ──────────────────────────────────────────────────────────
API_KEY = os.getenv("ALPHA_VANTAGE_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

# Watchlist Strategica con soglie RSI personalizzate
TITOLI = {
    "NVDA": 30, "VRT": 35, "ASML": 30,            # AI & Tech
    "LMT": 40, "RTX": 40, "PLTR": 35, "GD": 38,   # Difesa & Guerra
    "CCJ": 40, "SMR": 35,                         # Uranio & Nucleare
    "FCX": 40, "LAC": 35,                         # Metalli (LAC è alternativa a ALB)
    "TSLA": 30, "BTC": 30,                        # Volatili
    "XLK": 30, "VOO": 30,                           # Indici Tech e S&P500 (Alternative a QQQ/SPY)
}

# ─── FUNZIONI DI SUPPORTO ────────────────────────────────────────────────────

def send_telegram_msg(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    params = {"chat_id": CHAT_ID, "text": text}
    try:
        requests.get(url, params=params)
    except Exception as e:
        print(f"Errore invio Telegram: {e}")

def get_fundamentals(symbol):
    """Secondo stadio: controlla se l'azienda produce utili"""
    url = "https://www.alphavantage.co/query"
    params = {"function": "OVERVIEW", "symbol": symbol, "apikey": API_KEY}
    try:
        r = requests.get(url, params=params)
        data = r.json()
        eps = float(data.get("EPS", 0))
        pe = float(data.get("PERatio", 0))
        name = data.get("Name", symbol)
        return eps, pe, name
    except:
        return 0, 0, symbol

def get_data_and_analyze(symbol, rsi_threshold):
    """Primo stadio: analisi tecnica del grafico"""
    url = "https://www.alphavantage.co/query"
    params = {"function": "TIME_SERIES_DAILY", "symbol": symbol, "apikey": API_KEY, "outputsize": "full"}
    
    r = requests.get(url, params=params)
    data = r.json()
    
    if "Time Series (Daily)" not in data:
        print(f"⚠️ Salto {symbol}: Limite API o dato non disponibile.")
        return None

    # Prezzi e volumi
    df = pd.DataFrame.from_dict(data["Time Series (Daily)"], orient="index")
    df = df.rename(columns={"4. close": "Close", "5. volume": "Volume"}).apply(pd.to_numeric)
    df = df.sort_index()

    # 1. RSI
    delta = df['Close'].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1/14, min_periods=14, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/14, min_periods=14, adjust=False).mean()
    df['RSI'] = 100 - (100 / (1 + (avg_gain / avg_loss)))

    # 2. SMA200 (Trend Lungo Termine)
    df['SMA200'] = df['Close'].rolling(window=200).mean()

    # 3. Media Volumi (20gg)
    df['Avg_Vol'] = df['Volume'].rolling(window=20).mean()

    # 4. Bollinger Bands (20gg)
    df['SMA20'] = df['Close'].rolling(window=20).mean()
    df['STD'] = df['Close'].rolling(window=20).std()
    df['Lower'] = df['SMA20'] - (df['STD'] * 2)
    df['Upper'] = df['SMA20'] + (df['STD'] * 2)

    last = df.iloc[-1]
    
    # --- LOGICA DI FILTRAGGIO ---
    
    # Controllo Tecnico (Prezzo basso?)
    if last['RSI'] < rsi_threshold or last['Close'] <= last['Lower']:
        
        # Se il prezzo è basso, controlliamo se l'azienda è sana (EPS > 0)
        time.sleep(15) # Pausa obbligatoria per API Alpha Vantage
        eps, pe, company_name = get_fundamentals(symbol)
        
        if eps > 0:
            target_price = last['Upper']
            potential_gain = ((target_price - last['Close']) / last['Close']) * 100
            
            trend = "Trend Rialzista ✅" if last['Close'] > last['SMA200'] else "Trend Debole ⚠️"
            vol_status = "ALTI 📈" if last['Volume'] > last['Avg_Vol'] else "Normali"

            msg = (f"🟢 SEGNALE ACQUISTO: {company_name} ({symbol})\n"
                   f"💰 Prezzo Attuale: ${last['Close']:.2f}\n"
                   f"🎯 TARGET PRICE: ${target_price:.2f} (+{potential_gain:.1f}%)\n"
                   f"📊 FONDAMENTALI: EPS {eps} | P/E {pe}\n"
                   f"📉 TECNICO: RSI {last['RSI']:.2f} | {trend}\n"
                   f"🔊 VOLUMI: {vol_status}\n"
                   f"💡 Nota: Azienda in profitto con prezzo a sconto.")
            return msg
        else:
            print(f"Sconto trovato su {symbol}, ma ignorato: EPS negativo ({eps}).")
            
    return None

# ─── ESECUZIONE ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("🤖 Bot in esecuzione... Analisi della watchlist in corso.")
    
    for s, soglia in TITOLI.items():
        print(f"Controllo {s}...")
        segnali = get_data_and_analyze(s, soglia)
        
        if segnali:
            send_telegram_msg(segnali)
            print(f"✅ Messaggio inviato per {s}")
        
        # Attesa per rispettare le 5 chiamate/minuto della versione Free
        time.sleep(15)
        
    print(" Analisi completata.")
