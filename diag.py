import pandas as pd

df = pd.read_csv(r'C:\Users\matti\Desktop\prediction-market-analysis\output\paper_trading\polymarket\signals.csv')

buy = df[df['signal'] == 'buy']
print(f'Total markets evaluated: {len(df)}')
print(f'Buy signals: {len(buy)}')
print()
print('--- Filter breakdown (how many markets pass each) ---')
print(f'edge >= 0.01:                    {(df["edge"] >= 0.01).sum()}')
print(f'recent_trade_count >= 5:         {(df["recent_trade_count"] >= 5).sum()}')
print(f'recent_notional >= 100:          {(df["recent_notional"] >= 100).sum()}')
print(f'seconds_since_last_trade <= 900: {(df["seconds_since_last_trade"] <= 900).sum()}')
has_buy_share = 'buy_share' in df.columns
print(f'buy_share >= 0.60:               {(df["buy_share"] >= 0.60).sum() if has_buy_share else "N/A"}')
print(f'liquidity >= 5000:               {(df["liquidity"] >= 5000).sum()}')
print()
print('--- Edge distribution ---')
print(df['edge'].describe())
print()
print('--- Top 5 by edge ---')
print(df[['question','edge','recent_trade_count','recent_notional','seconds_since_last_trade']].nlargest(5, 'edge').to_string())
