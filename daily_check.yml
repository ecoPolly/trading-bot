name: Trading Bot Daily Check

on:
  schedule:
    - cron: '15 21 * * *' # Gira ogni giorno alle 21:15 UTC (22:15 in Italia)
  workflow_dispatch: # Ti permette di lanciarlo a mano se vuoi fare un test

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout code
        uses: actions/checkout@v2

      - name: Set up Python
        uses: actions/setup-python@v2
        with:
          python-version: '3.9'

      - name: Install dependencies
        run: pip install requests pandas

      - name: Run Bot
        run: python trading_bot.py
        env:
          # Inserisci qui le tue chiavi se non vuoi caricarle nel codice pubblico
          API_KEY: ${{ secrets.FIX9HNM1D5XAI9Y0}}
