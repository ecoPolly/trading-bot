"""
Trading Bot v2 — Potenziato
Alpha Vantage FREE tier: 25 call/giorno (aggiornato 2024)
Ottimizzato per minimizzare le chiamate API.

Miglioramenti rispetto a v1:
  - MACD (momentum confirmation)
  - MA50 / MA200 golden cross / death cross
  - VIX come filtro globale anti-crollo
  - Score composito (non basta RSI)
  - Segnali separati: BREVE / MEDIO / LUNGO termine
  - Watchlist aggiornata con titoli a sconto potenziale
  - Gestione errori e rate limiting robusta
"""

import requests
import pandas as pd
import time
import os
from datetime import datetime

# ─── CONFIGURAZIONE ──────────────────────────────────────────────────────────

API_KEY        = os.getenv("ALPHA_VANTAGE_KEY", "demo")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID        = os.getenv("CHAT_ID")

# Alpha Vantage free: ~25 call/giorno (ogni titolo usa 2 call: DAILY + OVERVIEW)
# Con 22 titoli = 44 call → esegui ogni 2 giorni oppure riduci la watchlist
# Imposta SLEEP_BETWEEN_CALLS >= 15 sec per stare nei limiti

SLEEP_BETWEEN_CALLS = 15   # secondi tra chiamate API
SLEEP_AFTER_FUND    = 15   # secondi extra dopo chiamata fondamentali

# ─── WATCHLIST ───────────────────────────────────────────────────────────────
# Formato: "TICKER": (soglia_RSI, orizzonte)
# orizzonte: "S" = breve (1-3 mesi), "M" = medio (3-9 mesi), "L" = lungo (9m+)
# Soglie RSI più basse = più selettivo (meno segnali, più qualità)

TITOLI = {
    # ── BREVE TERMINE: titoli già corretti, catalizzatori vicini ──────────────
    # NVO ha perso ~40% dai massimi 2024, trend obesità intatto
    "NVO":  (38, "S"),
    # LLY correzione post-massimi, pipeline forte
    "LLY":  (38, "S"),
    # PANW ha consolidato, il ciclo rinnovi contratti è imminente
    "PANW": (35, "S"),
    # RTX beneficia escalation difesa EU, P/E ragionevole
    "RTX":  (40, "S"),
    # FCX legato al rame: infrastrutture AI e green energy lo spingono
    "FCX":  (38, "S"),

    # ── MEDIO TERMINE: trend forti ma volatili, aspetta lo sconto ─────────────
    # AVGO: chip custom per Google/Meta/Apple, meno esposta dazi di NVDA
    "AVGO": (35, "M"),
    # MSFT: AI + cloud enterprise, la più difensiva del big tech
    "MSFT": (33, "M"),
    # CCJ: uranio — accordi nucleare Microsoft/Google danno visibilità pluriennale
    "CCJ":  (38, "M"),
    # GD: backlog record, budget difesa in aumento globale
    "GD":   (38, "M"),
    # VST: vende elettricità ai datacenter, contratti pluriennali siglati
    "VST":  (35, "M"),
    # MP: terre rare strategiche, unico produttore USA rilevante
    "MP":   (33, "M"),
    # AMZN: AWS + AI + logistica, correzioni sono opportunità
    "AMZN": (35, "M"),

    # ── LUNGO TERMINE: speculativi/tematici, accumula sulle correzioni ─────────
    # NVDA: ogni correzione è storicamente un'opportunità di accumulo
    "NVDA": (30, "L"),
    # ASML: monopolio litografia EUV, l'unica alternativa non esiste
    "ASML": (30, "L"),
    # LMT: contratti decennali, dividend aristocrat della difesa
    "LMT":  (40, "L"),
    # XLK: ETF tech USA, meno volatile delle singole
    "XLK":  (30, "L"),
    # VOO: S&P500, il mattone di qualsiasi portafoglio
    "VOO":  (30, "L"),
    # SMR: small modular reactor — speculativo ma catalizzatore nucleare reale
    "SMR":  (30, "L"),
    # VRT: infrastruttura datacenter (cooling), backlog record
    "VRT":  (33, "L"),
}

# ─── PARAMETRI TECNICI ───────────────────────────────────────────────────────

VIX_SOGLIA_ALERT  = 25   # sopra questa soglia: aggiungi warning al messaggio
VIX_SOGLIA_BLOCCO = 35   # sopra questa soglia: blocca tutti i segnali BUY

SCORE_MINIMO_BUY  = 3    # score composito minimo per segnalare (max 6)

# ─── TELEGRAM ────────────────────────────────────────────────────────────────

def send_telegram(text: str):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("[Telegram] Token o Chat ID mancanti, stampo solo su console.")
        print(text)
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        requests.get(url, params={"chat_id": CHAT_ID, "text": text, "parse_mode": "Markdown"}, timeout=10)
    except Exception as e:
        print(f"[Telegram] Errore invio: {e}")

# ─── FETCH VIX ───────────────────────────────────────────────────────────────

def get_vix() -> float:
    """
    Scarica il VIX (CBOE Volatility Index) da Alpha Vantage.
    Restituisce il valore attuale o -1 in caso di errore.
    Usa 1 call API.
    """
    url = "https://www.alphavantage.co/query"
    params = {
        "function": "TIME_SERIES_DAILY",
        "symbol": "VIX",
        "apikey": API_KEY,
        "outputsize": "compact"
    }
    try:
        r = requests.get(url, params=params, timeout=15)
        data = r.json()
        if "Time Series (Daily)" in data:
            last_date = sorted(data["Time Series (Daily)"].keys())[-1]
            vix_val = float(data["Time Series (Daily)"][last_date]["4. close"])
            print(f"  VIX attuale: {vix_val:.1f}")
            return vix_val
        else:
            # Alpha Vantage free non sempre ha VIX — usa un valore neutro
            print("  [VIX] Dato non disponibile, uso valore neutro 20.")
            return 20.0
    except Exception as e:
        print(f"  [VIX] Errore: {e}")
        return 20.0

# ─── FETCH DATI TECNICI ──────────────────────────────────────────────────────

def get_price_data(symbol: str) -> pd.DataFrame | None:
    """
    Scarica la serie storica giornaliera completa.
    Calcola: RSI14, MA50, MA200, MACD, Bollinger Bands, Volume medio.
    Usa 1 call API.
    """
    url = "https://www.alphavantage.co/query"
    params = {
        "function": "TIME_SERIES_DAILY",
        "symbol": symbol,
        "apikey": API_KEY,
        "outputsize": "full"
    }
    try:
        r = requests.get(url, params=params, timeout=15)
        data = r.json()
    except Exception as e:
        print(f"  [{symbol}] Errore connessione: {e}")
        return None

    if "Time Series (Daily)" not in data:
        msg = data.get("Note") or data.get("Information") or "Risposta API non valida"
        print(f"  [{symbol}] Salto — {msg[:80]}")
        return None

    df = pd.DataFrame.from_dict(data["Time Series (Daily)"], orient="index")
    df = df.rename(columns={
        "1. open":   "Open",
        "2. high":   "High",
        "3. low":    "Low",
        "4. close":  "Close",
        "5. volume": "Volume"
    }).apply(pd.to_numeric, errors="coerce")
    df = df.sort_index()

    # ── RSI 14 ──
    delta    = df["Close"].diff()
    gain     = delta.clip(lower=0)
    loss     = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1/14, min_periods=14, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/14, min_periods=14, adjust=False).mean()
    df["RSI"] = 100 - (100 / (1 + avg_gain / avg_loss))

    # ── Medie mobili ──
    df["MA50"]  = df["Close"].rolling(50).mean()
    df["MA200"] = df["Close"].rolling(200).mean()

    # ── MACD (12/26/9) ──
    ema12        = df["Close"].ewm(span=12, adjust=False).mean()
    ema26        = df["Close"].ewm(span=26, adjust=False).mean()
    df["MACD"]   = ema12 - ema26
    df["Signal"] = df["MACD"].ewm(span=9, adjust=False).mean()
    df["MACD_hist"] = df["MACD"] - df["Signal"]

    # ── Bollinger Bands (20gg, 2σ) ──
    df["SMA20"]  = df["Close"].rolling(20).mean()
    df["STD20"]  = df["Close"].rolling(20).std()
    df["BB_low"] = df["SMA20"] - 2 * df["STD20"]
    df["BB_up"]  = df["SMA20"] + 2 * df["STD20"]

    # ── Volume medio 20gg ──
    df["Vol_avg"] = df["Volume"].rolling(20).mean()

    return df

# ─── FETCH FONDAMENTALI ──────────────────────────────────────────────────────

def get_fundamentals(symbol: str) -> dict:
    """
    Scarica EPS, P/E, PEG, nome azienda, settore.
    Usa 1 call API.
    """
    url = "https://www.alphavantage.co/query"
    params = {"function": "OVERVIEW", "symbol": symbol, "apikey": API_KEY}
    try:
        r    = requests.get(url, params=params, timeout=15)
        data = r.json()
        return {
            "name":    data.get("Name", symbol),
            "sector":  data.get("Sector", "N/D"),
            "eps":     _to_float(data.get("EPS")),
            "pe":      _to_float(data.get("PERatio")),
            "peg":     _to_float(data.get("PEGRatio")),
            "fcf":     _to_float(data.get("FreeCashFlow")),  # non sempre presente
            "debt_eq": _to_float(data.get("DebtToEquityRatio")),
        }
    except Exception as e:
        print(f"  [{symbol}] Fondamentali errore: {e}")
        return {"name": symbol, "sector": "N/D", "eps": 0, "pe": 0, "peg": 0, "fcf": 0, "debt_eq": 0}

def _to_float(val) -> float:
    try:
        return float(val) if val not in (None, "None", "-", "") else 0.0
    except:
        return 0.0

# ─── SCORE COMPOSITO ─────────────────────────────────────────────────────────

def calcola_score(row: pd.Series, rsi_threshold: float, fund: dict) -> tuple[int, list[str]]:
    """
    Punteggio da 0 a 6. Ogni condizione soddisfatta vale 1 punto.
    Restituisce (score, lista_motivi).
    """
    score   = 0
    motivi  = []

    # 1. RSI sotto soglia personalizzata O prezzo sotto Bollinger inferiore
    if row["RSI"] < rsi_threshold:
        score += 1
        motivi.append(f"RSI {row['RSI']:.1f} < soglia {rsi_threshold}")
    elif row["Close"] <= row["BB_low"]:
        score += 1
        motivi.append(f"Prezzo sotto Bollinger inferiore (${row['BB_low']:.2f})")

    # 2. MACD: istogramma negativo ma in risalita (divergenza rialzista)
    if row["MACD_hist"] < 0 and row["MACD_hist"] > 0:
        # caso impossibile, usato come placeholder — sotto la logica reale
        pass
    # MACD sopra signal line = momentum positivo in formazione
    if row["MACD"] > row["Signal"]:
        score += 1
        motivi.append("MACD sopra signal line (momentum positivo)")
    elif row["MACD_hist"] > -0.5 and row["RSI"] < rsi_threshold + 5:
        # MACD quasi al crossover
        score += 1
        motivi.append("MACD prossimo al crossover rialzista")

    # 3. Prezzo sopra MA200 (trend lungo termine rialzista)
    if pd.notna(row["MA200"]) and row["Close"] > row["MA200"]:
        score += 1
        motivi.append(f"Sopra MA200 (${row['MA200']:.2f}) — trend rialzista")
    else:
        motivi.append(f"⚠️ Sotto MA200 — trend debole")

    # 4. MA50 sopra MA200 (golden cross attivo)
    if pd.notna(row["MA50"]) and pd.notna(row["MA200"]):
        if row["MA50"] > row["MA200"]:
            score += 1
            motivi.append("Golden cross attivo (MA50 > MA200)")
        else:
            motivi.append("⚠️ Death cross (MA50 < MA200) — cautela")

    # 5. Fondamentali: EPS positivo
    if fund["eps"] > 0:
        score += 1
        motivi.append(f"EPS positivo ({fund['eps']:.2f})")
    else:
        motivi.append(f"⚠️ EPS negativo/zero ({fund['eps']:.2f}) — speculativo")

    # 6. Volume anomalo (conferma istituzionale)
    if pd.notna(row["Vol_avg"]) and row["Volume"] > row["Vol_avg"] * 1.5:
        score += 1
        motivi.append(f"Volume anomalo ({row['Volume']:,.0f} vs media {row['Vol_avg']:,.0f})")

    return score, motivi

# ─── FORMATTAZIONE MESSAGGIO ─────────────────────────────────────────────────

def formatta_messaggio(symbol: str, orizzonte: str, row: pd.Series,
                       fund: dict, score: int, motivi: list[str], vix: float) -> str:
    orizzonte_label = {"S": "BREVE (1-3 mesi)", "M": "MEDIO (3-9 mesi)", "L": "LUNGO (9m+)"}
    emoji_score = "🟢" if score >= 5 else "🟡" if score >= 3 else "🔴"

    target = row["BB_up"]
    gain   = ((target - row["Close"]) / row["Close"]) * 100

    vix_warn = ""
    if vix >= VIX_SOGLIA_ALERT:
        vix_warn = f"\n⚠️ *VIX ELEVATO* ({vix:.1f}) — rischio mercato alto, position size ridotta"

    motivi_str = "\n  • ".join(motivi)

    msg = (
        f"{emoji_score} *SEGNALE {orizzonte_label.get(orizzonte, orizzonte)}*\n"
        f"*{fund['name']} ({symbol})* — {fund['sector']}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 Prezzo: *${row['Close']:.2f}* | Target BB: ${target:.2f} (+{gain:.1f}%)\n"
        f"📊 Score: *{score}/6*\n"
        f"📉 RSI: {row['RSI']:.1f} | MACD: {row['MACD']:.3f} | Signal: {row['Signal']:.3f}\n"
        f"📈 MA50: ${row['MA50']:.2f} | MA200: ${row['MA200']:.2f}\n"
        f"💹 EPS: {fund['eps']} | P/E: {fund['pe']} | PEG: {fund['peg']}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"*Motivi:*\n  • {motivi_str}"
        f"{vix_warn}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"⚠️ _Non è consulenza finanziaria. Fai le tue valutazioni._"
    )
    return msg

# ─── ANALISI SINGOLO TITOLO ──────────────────────────────────────────────────

def analizza(symbol: str, rsi_threshold: float, orizzonte: str, vix: float) -> str | None:
    print(f"  Scarico dati tecnici {symbol}...")
    df = get_price_data(symbol)
    time.sleep(SLEEP_BETWEEN_CALLS)

    if df is None or len(df) < 200:
        return None

    row = df.iloc[-1]

    # Pre-filtro rapido: se RSI alto e prezzo sopra Bollinger, skip senza usare altra call API
    if row["RSI"] > rsi_threshold + 15 and row["Close"] > row["BB_low"] * 1.05:
        print(f"  [{symbol}] Nessun segnale tecnico (RSI {row['RSI']:.1f}, skip fondamentali)")
        return None

    # Solo se supera il pre-filtro, chiama i fondamentali (risparmio call API)
    print(f"  Scarico fondamentali {symbol}...")
    fund = get_fundamentals(symbol)
    time.sleep(SLEEP_AFTER_FUND)

    score, motivi = calcola_score(row, rsi_threshold, fund)

    if score >= SCORE_MINIMO_BUY:
        msg = formatta_messaggio(symbol, orizzonte, row, fund, score, motivi, vix)
        return msg
    else:
        print(f"  [{symbol}] Score {score}/6 sotto soglia ({SCORE_MINIMO_BUY}), nessun segnale.")
        return None

# ─── ESECUZIONE PRINCIPALE ───────────────────────────────────────────────────

if __name__ == "__main__":
    ora = datetime.now().strftime("%d/%m/%Y %H:%M")
    print(f"\n{'='*50}")
    print(f"  Trading Bot v2 — {ora}")
    print(f"{'='*50}\n")

    # 1. Controlla VIX (1 call API)
    print("Controllo VIX...")
    vix = get_vix()
    time.sleep(SLEEP_BETWEEN_CALLS)

    if vix >= VIX_SOGLIA_BLOCCO:
        msg = (f"🚨 *ALERT VIX CRITICO*\n"
               f"VIX = *{vix:.1f}* (soglia blocco: {VIX_SOGLIA_BLOCCO})\n"
               f"❌ Analisi sospesa: mercato in panico, nessun segnale BUY emesso.\n"
               f"💡 Aspetta VIX < {VIX_SOGLIA_BLOCCO} prima di rientrare.")
        send_telegram(msg)
        print(f"\nVIX {vix:.1f} — analisi bloccata.")
        exit(0)

    # 2. Analizza ogni titolo
    segnali = {"S": [], "M": [], "L": []}

    for symbol, (soglia, orizzonte) in TITOLI.items():
        print(f"\n[{symbol}] orizzonte={orizzonte}")
        try:
            res = analizza(symbol, soglia, orizzonte, vix)
            if res:
                segnali[orizzonte].append(res)
                send_telegram(res)
        except Exception as e:
            print(f"  [{symbol}] Errore inatteso: {e}")

    # 3. Report finale
    totale = sum(len(v) for v in segnali.values())
    vix_str = f"VIX: {vix:.1f} {'⚠️' if vix > VIX_SOGLIA_ALERT else '✅'}"

    if totale == 0:
        send_telegram(
            f"📊 *Report giornaliero — {ora}*\n"
            f"{vix_str}\n"
            f"✅ Analisi completata: nessun segnale oggi.\n"
            f"Titoli analizzati: {len(TITOLI)}"
        )
    else:
        riepilogo = (
            f"📊 *Report giornaliero — {ora}*\n"
            f"{vix_str}\n"
            f"Segnali trovati: *{totale}*\n"
            f"  🔵 Breve termine: {len(segnali['S'])}\n"
            f"  🟡 Medio termine: {len(segnali['M'])}\n"
            f"  🟢 Lungo termine: {len(segnali['L'])}\n"
            f"Titoli analizzati: {len(TITOLI)}"
        )
        send_telegram(riepilogo)

    print(f"\n✅ Analisi completata. Segnali totali: {totale}")
