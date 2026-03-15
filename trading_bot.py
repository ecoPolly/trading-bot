import requests
import pandas as pd
import time
import os

# ─── CONFIGURAZIONE ──────────────────────────────────────────────────────────
API_KEY = os.getenv("ALPHA_VANTAGE_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

# Watchlist Strategica con soglie RSI personalizzate
# Watchlist Strategica Ampliata (Target: ~3 segnali/settimana)
TITOLI = {
    # --- AI, TECH & SEMICONDUCTORS ---
    "NVDA": 30, "VRT": 35, "ASML": 30, "AMD": 30, "AVGO": 35,
    # --- DIFESA, GUERRA & CYBERSECURITY ---
    "LMT": 40, "RTX": 40, "GD": 38, "PANW": 35,
    # --- ENERGIA, URANIO & NUCLEARE ---
    "CCJ": 40, "SMR": 35, "VST": 40, "OKLO": 30,
    # --- METALLI & MATERIE PRIME ---
    "FCX": 40, "LAC": 35, "MP": 35,
    # --- BIG PHARMA & BIOTECH (Trend Obesità/Longevità) ---
    "LLY": 35, "NVO": 35,
    # --- INDICI & CLOUD ---
    "XLK": 30, "VOO": 30, "AMZN": 35, "MSFT": 35
}

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
    print("🤖 Bot in esecuzione...")
    report_completo = "📊 REPORT GIORNALIERO\n"
    segnali_trovati = 0
    
    for s, soglia in TITOLI.items():
        print(f"Controllo {s}...")
        res = get_data_and_analyze(s, soglia)
        if res:
            send_telegram_msg(res)
            segnali_trovati += 1
        time.sleep(15)
    
    if segnali_trovati == 0:
        send_telegram_msg("✅ Analisi completata: Nessun segnale di acquisto oggi. Mercato stabile.")
    
    print("Analisi completata.")
