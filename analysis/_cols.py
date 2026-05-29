import pandas as pd
from pathlib import Path
p=Path("cowork_snapshot")/"esports"/"clob_esports_markets.parquet"
df=pd.read_parquet(p)
print(list(df.columns))
