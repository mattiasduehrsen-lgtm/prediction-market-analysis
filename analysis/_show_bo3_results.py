from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
t = (ROOT/"bo3_pipeline.log").read_text(encoding="utf-8",errors="ignore")
i = t.rfind("usable CS2 games")
print(t[i:] if i>=0 else t[-3000:])
