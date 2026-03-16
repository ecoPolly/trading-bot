import requests
import pandas as pd
import time
import os
from datetime import datetime

# --- CONFIGURAZIONE ---
API_KEY        = os.getenv("ALPHA_VANTAGE_KEY", "demo")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID        = os.getenv("CHAT_ID")

SLEEP_BETWEEN_CALLS = 15
SLEEP_AFTER_FUND    = 15

TITOLI = {
    "NVO": (38, "S"), "LLY": (38, "S"), "PANW": (35, "S"), "RTX": (40, "S"), "FCX": (38, "S"),
    "AVGO": (35, "M"), "MSFT": (33, "M"), "CCJ": (38, "M"), "GD": (38, "M"), "VST": (35, "M"),
    "MP": (33, "M"), "AMZN": (35, "M"), "NVDA": (30, "L"), "ASML": (30, "L"), "LMT": (40, "L"),
    "XLK": (30, "L"), "VOO": (30, "L"), "SMR": (30, "L"), "VRT": (33, "L")
}

VIX_SOGLIA_ALERT = 25
VIX_SOGLIA_BLOCCO = 35
SCORE_MINIMO_BUY = 3

def send_telegram(text: str):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print(text)
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        requests.get(url, params={"chat_id": CHAT_ID, "text": text, "parse_mode": "Markdown"}, timeout=10)
    except Exception as e:
        print(f"Errore invio: {e}")

def get_vix() -> float:
    url = "https://www.alphavantage.co/query"
    params = {"function": "TIME_SERIES_DAILY", "symbol": "VIX", "apikey": API_KEY}
    try:
        r = requests.get(url, params=params, timeout=15)
        data = r.json()
        if "Time Series (Daily)" in data:
            last_date = sorted(data["Time Series (Daily)"].keys())[-1]
            return float(data["Time Series (Daily)"][last_date]["4. close"])
        return 20.0
    except:
        return 20.0

def get_price_data(symbol: str):
    url = "https://www.alphavantage.co/query"
    params = {"function": "TIME_SERIES_DAILY", "symbol": symbol, "apikey": API_KEY, "outputsize": "full"}
    try:
        r = requests.get(url, params=params, timeout=15)
        data = r.json()
        if "Time Series (Daily)" not in data: return None
        df = pd.DataFrame.from_dict(data["Time Series (Daily)"], orient="index")
        df = df.rename(columns={"1. open":"Open","2. high":"High","3. low":"Low","4. close":"Close","5. volume":"Volume"}).apply(pd.to_numeric)
        df = df.sort_index()
        delta = df["Close"].diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)
        avg_gain = gain.ewm(alpha=1/14, min_periods=14, adjust=False).mean()
        avg_loss = loss.ewm(alpha=1/14, min_periods=14, adjust=False).mean()
        df["RSI"] = 100 - (100 / (1 + avg_gain / avg_loss))
        df["MA50"] = df["Close"].rolling(50).mean()
        df["MA200"] = df["Close"].rolling(200).mean()
        ema12 = df["Close"].ewm(span=12, adjust=False).mean()
        ema26 = df["Close"].ewm(span=26, adjust=False).mean()
        df["MACD"] = ema12 - ema26
        df["Signal"] = df["MACD"].ewm(span=9, adjust=False).mean()
        df["MACD_hist"] = df["MACD"] - df["Signal"]
        df["SMA20"] = df["Close"].rolling(20).mean()
        df["STD20"] = df["Close"].rolling(20).std()
        df["BB_low"] = df["SMA20"] - 2 * df["STD20"]
        df["BB_up"] = df["SMA20"] + 2 * df["STD20"]
        df["Vol_avg"] = df["Volume"].rolling(20).mean()
        return df
    except: return None

def get_fundamentals(symbol: str):
    url = "https://www.alphavantage.co/query"
    params = {"function": "OVERVIEW", "symbol": symbol, "apikey": API_KEY}
    try:
        r = requests.get(url, params=params, timeout=15); data = r.json()
        return {"name": data.get("Name", symbol), "sector": data.get("Sector", "N/A"), "eps": float(data.get("EPS", 0)), "pe": float(data.get("PERatio", 0)), "peg": float(data.get("PEGRatio", 0))}
    except: return {"name": symbol, "sector": "N/A", "eps": 0, "pe": 0, "peg": 0}

def calcola_score(row, rsi_threshold, fund, macd_hist_prev):
    score = 0; motivi = []
    if row["RSI"] < rsi_threshold:
        score += 1; motivi.append(f"RSI {row['RSI']:.1f} < {rsi_threshold}")
    if row["MACD"] > row["Signal"]:
        score += 1; motivi.append("MACD Bullish Crossover")
    elif macd_hist_prev is not None and row["MACD_hist"] > macd_hist_prev:
        score += 1; motivi.append("MACD Momentum in risalita")
    if row["Close"] > row["MA200"]:
        score += 1; motivi.append("Sopra MA200")
    if fund["eps"] > 0:
        score += 1; motivi.append("EPS Positivo")
    return score, motivi

if __name__ == "__main__":
    vix = get_vix()
    if vix >= VIX_SOGLIA_BLOCCO:
        send_telegram(f"🚨 VIX Alto ({vix}): Analisi Sospesa"); exit()
    
    segnali = []
    for sym, (soglia, oriz) in TITOLI.items():
        df = get_price_data(sym)
        if df is None: continue
        row = df.iloc[-1]
        hist_prev = df["MACD_hist"].iloc[-2] if len(df)>1 else None
        
        if row["RSI"] < soglia + 10:
            fund = get_fundamentals(sym)
            score, motivi = calcola_score(row, soglia, fund, hist_prev)
            if score >= SCORE_MINIMO_BUY:
                msg = f"🟢 *{sym}* - Score {score}/6\nPrezzo: ${row['Close']:.2f}\nMotivi: {', '.join(motivi)}"
                segnali.append(msg); send_telegram(msg)
        time.sleep(15)
    
    send_telegram(f"📊 Analisi completata. Segnali: {len(segnali)}")
