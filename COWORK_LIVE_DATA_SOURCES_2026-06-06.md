# CS2 live-data sourcing: every method, ranked for the in-play bot (2026-06-06)

**The single most important framing:** your edge window is **0–10 minutes** after a map completes (measured: ROI is flat-to-rising through +5 min, ~+24% at +10 min, gone by +30). So you do **not** need sub-second data, and you should not spend money chasing it. The bottleneck that's actually killing you is not latency — it's that the paper bot has logged **zero** bets (a matching/pipeline problem). With that said, here is every way to watch CS2 live, ranked, plus what I'd actually wire in.

Two latency facts to anchor everything below:
- A pro broadcast (GOTV/CSTV) runs on a **1:45 competitive delay**. Anything derived from the broadcast inherits that.
- **bo3.gg — what you already use — runs ~30 seconds *ahead* of the broadcast**, i.e. it's pulling from a faster source. So bo3 sees a map end roughly **60–90s after it actually happens** — comfortably inside a 10-minute window.

---

## The methods, fastest → slowest detection of "map just ended + who won"

### 1. GRID.gg — official, server-sourced (the best free upgrade)
GRID ingests data **straight from the game server**, so it's the lowest-latency source that exists (faster than broadcast, sub-second to a few seconds), delivered over **WebSocket push** (no polling). It's now the **exclusive data partner for ESL / IEM / ESL Pro League** (EFG events).

- **Cost / access:** **GRID Open Access is FREE** for "pre-revenue startups, academic institutions, independent developers, and fans" — you qualify. CS2 + Dota2, real-time match stats and in-game events, with docs and a sample Node WebSocket script.
- **The catch:** GRID's productized **"Series Events" feed (the clean map-ended / series-score betting stream) is a PAID product, not in Open Access.** Open Access gives you live in-game *telemetry/events* (rounds, kills, etc.), from which you can *infer* map completion (e.g. a team's round count hits 13), but the turnkey "map N finished, score is X" signal is behind the paid wall.
- **Coverage caveat that matters for you:** GRID's rights are concentrated in **top-tier** events (ESL/IEM) — which is exactly the **tier-S segment where your edge was weak/negative (−5.7%)**. Less useful for the tier-B / unclassified matches where your edge actually lives.
- **Verdict:** Apply for Open Access (free, ~minutes of effort). Best latency, official, and a great redundancy/cross-check feed — but it covers the wrong tier for your edge and the cleanest signal is paywalled. Worth having, not a silver bullet.

### 2. Valve Game State Integration (GSI) — free, native, but operationally heavy
GSI is Valve's official real-time **push** of game state to an external listener. Full match state ("allplayers", round/map events) is **only exposed to HLTV/observers/GOTV spectators** — when you merely play, you only see your own data.

- **To use it on pro matches you must run a CS2 client spectating the match's GOTV**, then read GSI locally. That inherits the **GOTV delay (~1:45 competitive)** and requires the tournament's GOTV to be publicly joinable (frequently restricted or relay-gated for big events).
- **FACEIT path:** FACEIT exposes spectating for **tournament** matches — either a whitelisted in-game **SPEC slot (near real-time)** or a **CSTV Playcast (CSTV delay + ~24s)**. Good for FACEIT-hosted qualifiers/lower tiers, but whitelist/tournament-gated and fiddly.
- **Cost:** free. **Ops cost:** high — you'd run one (or many) CS2 clients, manage GOTV connections per match, mature libraries exist (e.g. `CounterStrike2GSI`, `go-cs2-gsi`).
- **Verdict:** Powerful and free, genuinely real-time *if* you can spectate, but the operational burden (a live CS2 client per concurrent match) is disproportionate to a $10–100/month strategy. Keep in your back pocket; don't build it first.

### 3. bo3.gg API — what you already use (and it's good enough)
Free JSON API, no key, no Cloudflare wall. **~30s ahead of broadcast**, strong **lower-tier coverage** — i.e. it covers the exact matches where your edge is concentrated.

- **Cost:** free. **Access:** trivial (you're already on it). **ToS:** unofficial aggregator — tolerable for personal use, but no SLA; it can change or rate-limit.
- **Latency vs your window:** ~60–90s behind real game → you still have **~8+ minutes** of usable window. **Latency is not your problem here.**
- **Verdict:** Correct primary source. The fix you need is operational (why is the bot logging zero bets?), not a faster feed.

### 4. Bookmaker odds feeds as a proxy signal (OddsPapi / Pinnacle)
Instead of detecting the *game* event, detect a **sharp book repricing** after a map and front-run Polymarket. **OddsPapi** has a **free REST tier** (all ~348 bookmakers incl. Pinnacle, GG.BET, Thunderpick, Betway; CS2 majors covered) and a **Pro WebSocket** (sub-second).

- **Use:** Pinnacle is sharp and fast; when its CS2 series price jumps, a map almost certainly just resolved. A great **independent confirmation / redundancy** signal, and cheap.
- **Catch:** the free tier is REST (poll every few seconds); the sub-second push is paid. And a book's reprice isn't necessarily faster than bo3. It tells you *the market moved*, not the raw score.
- **Verdict:** Worth adding on the free tier as a **cross-check** ("did a sharp book also just move?") and as a sanity input to your `model_live` vs market comparison. Not a primary detector.

### 5. Commercial enterprise feeds — PandaScore Live, Sportradar, Abios (priced out)
- **PandaScore Live:** **€1,000 per game per month** (Live Basic = WebSocket, 2-second frames); the **Events feed** (timeline as it happens) is the more expensive **Pro Live** tier. CS2 lives under the `/csgo/` prefix.
- **Sportradar / Abios:** **$2,000–$10,000/month**, annual contracts, enterprise-only. No meaningful free tier.
- **Verdict:** **Rule out.** €1,000+/month against a $10–100/month edge is absurd. (PandaScore's *free historical* tier remains useful for your Elo model inputs — just not for live.)

### 6. HLTV / stream OCR / Liquipedia — don't bother for live
- **HLTV:** gold-standard stats but **Cloudflare-gated**; scraping live is fragile and ToS-hostile.
- **Stream scoreboard OCR (Twitch/YouTube):** inherits the full **~1:45+ broadcast delay** plus OCR lag and brittleness. Worst latency, highest maintenance.
- **Liquipedia:** wiki, not a live feed.
- **Verdict:** No.

---

## Comparison at a glance

| Method | Detect-map-end latency | Cost | Access barrier | Tier coverage | Fit for your edge |
|---|---|---|---|---|---|
| **GRID Open Access** | seconds (server) | Free* | Application + Series Events paywalled | **Top tier (ESL/IEM)** | Redundancy / cross-check; wrong tier |
| **GSI via GOTV/FACEIT** | ~30s–105s | Free | High ops (run CS2 client) | Depends on spectate access | Backup; heavy |
| **bo3.gg (current)** | ~60–90s | Free | None | **Lower tier (your edge zone)** | **Primary — keep** |
| **OddsPapi (Pinnacle)** | seconds (REST free) | Free / paid WS | API key | Major tournaments | Confirmation signal |
| PandaScore Live | ~2s | €1,000/game/mo | Paid | Broad | Priced out |
| Sportradar / Abios | ~1–2s | $2–10k/mo | Enterprise | Broad | Priced out |
| HLTV / OCR / Liquipedia | 105s+ | Free | Cloudflare / brittle | Mixed | No |

\* GRID Open Access is free; the clean live "Series Events" stream is paid.

---

## What I'd actually do (in order)

1. **Fix the pipeline before touching the data source.** The bot logging zero bets is the real blocker, and it is not a latency issue — bo3 already gives you ~8 minutes of usable window. Diagnose the matching/gating (team-name aliases, the `status`/`done`+live-map filter) so signals actually get recorded.
2. **Keep bo3.gg as the primary detector.** It covers your edge's tier and is fast enough. Add a freshness guard: if a live map's timestamp is stale beyond ~5 min, skip (you already have the data for this).
3. **Apply for GRID Open Access (free).** Use it as a **redundant, lowest-latency cross-check** and to harden detection on top-tier matches — but remember your edge is weak in tier-S, so this is reliability, not new profit.
4. **Add OddsPapi free tier as a confirmation signal** — "did a sharp book also just reprice?" — cheap insurance against acting on a bad bo3 read.
5. **Hold GSI/GOTV and any paid feed in reserve.** Only justified if you later prove the edge live *and* dramatically raise frequency/bankroll. At today's $10–100/month ceiling, neither pays for itself.

**Bottom line:** there is a whole ladder of live CS2 data, from server-direct (GRID) to native push (GSI) to your current aggregator (bo3) to proxy odds feeds — but for *this* strategy the latency question is already answered in your favor. The win is operational: get the bot recording, run bo3 as primary with GRID Open Access + an odds feed as free redundancy, and don't pay for speed you don't need.

---

## Sources
- [Valve CS2 Game State Integration (developer wiki)](https://developer.valvesoftware.com/wiki/Counter-Strike:_Global_Offensive_Game_State_Integration)
- [CounterStrike2GSI library (GitHub)](https://github.com/antonpup/CounterStrike2GSI) · [go-cs2-gsi (GitHub)](https://github.com/Nescabir/go-cs2-gsi)
- [GRID Open Access](https://grid.gg/open-access/) · [GRID Live Esports Data](https://grid.gg/live-esports-data/) · [GRID exclusive data partner for ESL/IEM (esports.gg)](https://esports.gg/news/esports/grid-exclusive-data-partner-efg/)
- [PandaScore pricing](https://www.pandascore.co/pricing) · [PandaScore WebSockets overview](https://developers.pandascore.co/docs/websockets-overview)
- [bo3.gg live matches](https://bo3.gg/matches/current) · [CS2API — bo3 wrapper (GitHub)](https://github.com/tommhe14/CS2API)
- [FACEIT — spectating CS2 matches](https://support.faceit.com/hc/en-us/articles/17050697184668-Setup-Running-Spectating-CS2-Matches) · [CS:GO GOTV guide (ZAP-Hosting)](https://zap-hosting.com/guides/docs/csgo-gotv/)
- [OddsPapi — free esports odds (Pinnacle CS2)](https://oddspapi.io/blog/esports-odds-api-guide-how-to-get-pinnacle-cs2-lol-data-for-free/) · [OddsPapi WebSocket overview](https://docs.oddspapi.io/websocket/overview)
- [Abios Esports Data API](https://abiosgaming.com/esports-data-api) · [Sportradar Dev Portal](https://developer.sportradar.com/)
