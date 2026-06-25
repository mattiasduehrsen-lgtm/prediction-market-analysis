"""Full system health check. Run on the laptop. Prints PASS/WARN/FAIL per item."""
from __future__ import annotations
import json, os, subprocess, time, re
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(r"C:\Users\matti\Desktop\prediction-market-analysis")
now = time.time()
P, W, F = [], [], []
def ok(m): P.append(m)
def warn(m): W.append(m)
def fail(m): F.append(m)

def ps(cmd):
    try:
        return subprocess.run(["powershell","-NoProfile","-Command",cmd],
                              capture_output=True,text=True,timeout=40).stdout
    except Exception as e:
        return f"ERR {e}"

# 1) PROCESSES
cmds = ps("Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | ForEach-Object { $_.CommandLine }")
bots = {"esports_fade_bot":"LIVE fade","sports_fade_bot":"sports","cs2_model_bot":"model paper",
        "cs2_inplay_bot":"inplay paper","telegram_bot":"telegram","main.py dashboard":"dashboard"}
print("="*70); print(" 1. PROCESSES")
for key,label in bots.items():
    # 'sports_fade_bot' is a substring of 'esports_fade_bot' -> boundary match
    _pat=re.compile(r"(?<![A-Za-z])"+re.escape(key))
    n = len([l for l in cmds.splitlines() if _pat.search(l)])
    line=f"   {label:<12} ({key}): {n} proc"
    if n==0: print(line+"  <<< DOWN"); fail(f"{label} DOWN")
    elif n>2: print(line+"  <<< DUPLICATE"); warn(f"{label} {n} procs (dup)")
    else: print(line+"  OK"); ok(f"{label} up")

# 2) HEARTBEAT FRESHNESS
print("="*70); print(" 2. LOG FRESHNESS (stale = stuck/dead)")
# heartbeat bots (must be fresh). telegram/dashboard are event-driven -> not here.
logs={"watchdog_esports.log":"esports","watchdog_sports.log":"sports",
      "watchdog_cs2model.log":"model","watchdog_cs2inplay.log":"inplay"}
for fn,label in logs.items():
    p=ROOT/fn
    if not p.exists(): print(f"   {label}: NO LOG"); warn(f"{label} no log"); continue
    age=(now-p.stat().st_mtime)/60
    s=f"   {label:<10}: last write {age:.1f} min ago"
    if age>30: print(s+"  <<< STALE/HUNG"); fail(f"{label} log stale {age:.0f}m")
    else: print(s+"  OK"); ok(f"{label} fresh")
print("   (telegram/dashboard are event-driven — liveness checked in section 1)")

# 3) LIVE ESPORTS BOT INTERNALS (onchain + pnl)
print("="*70); print(" 3. LIVE ESPORTS BOT")
try:
    tail=ps(f"Get-Content '{ROOT}\\watchdog_esports.log' -Tail 40")
    hbs=[l for l in tail.splitlines() if "heartbeat" in l]
    if hbs:
        h=hbs[-1]; print("   "+h.strip()[:140])
        if "conn=True" in h: ok("onchain connected")
        else: fail("onchain NOT connected"); print("   <<< onchain not connected")
        m=re.search(r"last_lag=(\d+)s",h)
        if m:
            lag=int(m.group(1))
            ok(f"onchain lag {lag}s") if lag<30 else warn(f"onchain lag {lag}s high")
    else: warn("no esports heartbeat in tail")
except Exception as e: warn(f"esports parse {e}")

# 4) WALLET / PNL
print("="*70); print(" 4. WALLET / PNL")
try:
    d=json.loads((ROOT/"output"/"esports_fade"/"live_daily_pnl.json").read_text())
    eq=d.get("wallet_total_equity_usd"); roi=d.get("lifetime_equity_roi_pct")
    print(f"   equity ${eq} | lifetime ROI {roi}% | today realized ${d.get('realized_pnl_usd')}")
    age=(now-d.get('generated_at',0))/60
    print(f"   pnl file age: {age:.0f} min")
    ok("wallet readable") if eq else warn("equity missing")
except Exception as e: warn(f"pnl read {e}")

# 5) SCHEDULED TASKS
print("="*70); print(" 5. SCHEDULED TASKS")
tasks=["PolyBotEsports","PolyBotSports","PolyBotTelegram","PolyDashboard","CS2ModelBot",
       "CS2InplayBot","PolyBotHealthGuard","CS2EloRefresh","CS2ModelEval","CS2InplayEval",
       "PolyBotEsportsRefresh","EsportsMarketMonitor","LoLEloRefresh","EsportsModelState"]
out=ps("foreach($t in @('"+"','".join(tasks)+"')){ $i=Get-ScheduledTaskInfo -TaskName $t -ErrorAction SilentlyContinue; "
       "$s=(Get-ScheduledTask -TaskName $t -ErrorAction SilentlyContinue).State; "
       "if($i){ Write-Output ($t+'|'+$s+'|'+$i.LastTaskResult+'|'+$i.NextRunTime) } else { Write-Output ($t+'|MISSING') } }")
for l in out.splitlines():
    l=l.strip()
    if not l or "|" not in l: continue
    parts=l.split("|")
    name=parts[0]
    if parts[1]=="MISSING": print(f"   {name:<24} MISSING"); fail(f"{name} missing"); continue
    state,res,nxt=parts[1],parts[2],("|".join(parts[3:]) if len(parts)>3 else "")
    flag="" if state in ("Ready","Running") else " <<< "+state
    print(f"   {name:<24} {state:<8} result={res} next={nxt[:16]}{flag}")
    if state not in ("Ready","Running"): warn(f"{name} state {state}")

# 6) HEALTH GUARD
print("="*70); print(" 6. HEALTH GUARD")
lr=ROOT/"health_guard_lastrun.txt"
if lr.exists():
    age=(now-lr.stat().st_mtime)/60
    print("   "+lr.read_text().strip()[:90]+f"  ({age:.1f} min ago)")
    ok("guard ran") if age<10 else warn(f"guard lastrun {age:.0f}m ago")
else: print("   no lastrun file"); warn("guard never ran")

# 7) DATA FRESHNESS
print("="*70); print(" 7. DATA FRESHNESS (auto-refresh working?)")
data={"cowork_snapshot/esports/fade_targets.json":("fade targets",120),
      "cowork_snapshot/gamedata/pandascore/cs2_elo_final.parquet":("series Elo",120),
      "cowork_snapshot/esports/clob_esports_markets.parquet":("clob markets",120)}
for rel,(label,maxmin) in data.items():
    p=ROOT/rel
    if not p.exists(): print(f"   {label}: MISSING"); warn(f"{label} missing"); continue
    age=(now-p.stat().st_mtime)/60
    s=f"   {label:<14}: {age:.0f} min old"
    if age>maxmin: print(s+"  <<< STALE"); warn(f"{label} stale {age:.0f}m")
    else: print(s+"  OK"); ok(f"{label} fresh")

# 8) PAUSE FLAGS
print("="*70); print(" 8. PAUSE FLAGS (active bots only)")
rel="output/esports_fade/paused.flag"
if (ROOT/rel).exists(): print(f"   {rel}: PRESENT (LIVE bot paused!)"); warn("esports paused")
else: print(f"   {rel}: absent (live bot trading)"); ok("not paused")

# 9) IN-PLAY DATA
print("="*70); print(" 9. IN-PLAY PAPER DATA")
for rel,label in [("output/cs2_inplay/paper_bets.csv","bets"),("output/cs2_inplay/observations.csv","obs")]:
    p=ROOT/rel
    n=(len(p.read_text(encoding="utf-8",errors="ignore").splitlines())-1) if p.exists() else 0
    print(f"   {label}: {n} rows")

# 10) GIT
print("="*70); print(" 10. GIT SYNC")
g=subprocess.run(["git","-C",str(ROOT),"status","-sb"],capture_output=True,text=True).stdout.splitlines()
print("   "+(g[0] if g else "?"))
if g and ("behind" in g[0]): warn("laptop behind origin"); print("   <<< BEHIND origin")
elif g: ok("git in sync")

# 11) DISK
print("="*70); print(" 11. DISK")
free=ps("[math]::Round((Get-PSDrive C).Free/1GB,1)")
print(f"   C: free {free.strip()} GB")
try:
    if float(free.strip())<5: fail("low disk")
    else: ok("disk ok")
except: pass

# SUMMARY
print("\n"+"="*70)
print(f" SUMMARY: {len(P)} PASS, {len(W)} WARN, {len(F)} FAIL")
if F: print(" FAIL: "+"; ".join(F))
if W: print(" WARN: "+"; ".join(W))
if not F and not W: print(" ALL GREEN")
