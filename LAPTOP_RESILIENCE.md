# Laptop Resilience — why the bots stay running 24/7

> Created 2026-06-17 after the user found the laptop **locked with no bots running**.
> This is the canonical reference for what keeps the bots alive and how to re-verify it.

## Root cause of the recurring "locked laptop, bot not running" outages

The AC **hibernate timeout was 15 minutes** (`HIBERNATEIDLE` AC = `0x384` = 900s).
Lock the screen (or just walk away) on AC power → 15 min later the laptop
**hibernates** → full power-off to disk → every bot process dies **and no
scheduled task runs, not even the health guard**, until someone physically wakes
the machine. The guard could never help because the guard was powered off too.

Sleep timeout was already `0` (never), which is why this hid for so long — it
wasn't sleeping, it was *hibernating*.

## The fix (applied + verified 2026-06-17)

All applied via committed, re-runnable scripts (so it survives a re-image / is documented):

| Setting | Before | After | Script |
|---|---|---|---|
| `standby-timeout` AC/DC | 0 / 0 | 0 / 0 (never) | `analysis/_harden_power.ps1` |
| `hibernate-timeout` AC/DC | **0x384 (15m)** / 0 | 0 / 0 (never) | `analysis/_harden_power.ps1` |
| Hibernation feature | enabled | **`powercfg /hibernate off`** (unavailable) | `analysis/_harden_power.ps1` |
| Lid-close action AC/DC | (hidden) | **0 = Do Nothing** | `analysis/_finish_resilience.ps1` |
| Wake timers AC/DC | important-only / off | enabled / enabled | `analysis/_harden_power.ps1` |
| `PolyBotHealthGuard` WakeToRun | False | **True** | `analysis/_harden_power.ps1` |

## Defense layers (what recovers the bots, in order)

1. **Can't go down on idle** — sleep & hibernate are off; closing the lid does nothing.
   This removes the actual root cause.
2. **Survives reboot** — `PolyBotEsports, PolyBotSports, CS2ModelBot, CS2InplayBot,
   PolyBotTelegram` all have **AtStartup (Boot)** triggers → restart on power-up.
   (`PolyDashboard` is Logon-triggered, but the guard force-starts it — see #4.)
3. **Wakes itself** — `PolyBotHealthGuard` runs as SYSTEM on a **Time trigger every
   5 min indefinitely** with **WakeToRun=True**, so if anything ever does sleep the
   box, the guard's trigger wakes it.
4. **Revives dead/hung bots** — the guard (`ensure_bots.ps1`) checks all 6 bots each
   run: proc-count 0 = DEAD, stale heartbeat log = HUNG. It kills the hung process,
   does `schtasks /end` then `/run` (handles stuck-"running" tasks), and self-heals
   stale lockfiles. `schtasks /run` force-starts even Logon-triggered tasks, so the
   dashboard recovers on an unattended reboot without editing its triggers.

## How to re-verify (anytime)

```powershell
ssh matti@192.168.2.212
cd C:\Users\matti\Desktop\prediction-market-analysis
powershell -ExecutionPolicy Bypass -File analysis\_verify_resilience.ps1
```

Expect: sleep/hibernate/lid all `0x00000000`, "Hibernation is not available",
all trading tasks `triggers=Boot`, guard `wake=True state=Ready`, all 6 bots `OK`.

## Not covered (physical / out of scope)

- **Battery fully drains while unplugged** → laptop off until re-plugged & powered on.
  Whether it auto-boots on AC restore is a BIOS setting, not a Windows one.
- A `git pull` blocked by a locally-modified file (the separate June 2026 3-day
  outage) — always confirm pulls actually land; not a power issue.
