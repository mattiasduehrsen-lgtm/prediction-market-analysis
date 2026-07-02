"""Research probe: what CONTEXT data does bo3.gg expose per match?
Target signals: (1) lineups/players ("donk isn't playing"), (2) map picks/vetos
("they're strong on Mirage"), (3) tournament tier. Read-only, free API."""
import json
import requests

S = requests.Session()
S.headers.update({"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
B = "https://api.bo3.gg/api/v1"

def g(path, params=None):
    r = S.get(f"{B}/{path}", params=params, timeout=15)
    try:
        return r.status_code, r.json()
    except Exception:
        return r.status_code, {}

# 1) recent finished matches (production pattern uses status filter on /matches loosely;
#    fall back to plain sort which the downloader used)
sc, j = g("matches", {"sort": "-start_date", "page[limit]": 8})
rows = j.get("data") or j.get("matches") or []
print(f"matches list: {sc}, rows={len(rows)}")
m = None
for r_ in rows:
    if r_.get("status") == "finished" or r_.get("winner_team_id") or r_.get("loser_team_id"):
        m = r_; break
m = m or (rows[0] if rows else None)
if not m:
    print("no match rows; abort"); raise SystemExit
print(f"sample: id={m.get('id')} slug={m.get('slug')} tier={m.get('tier')} "
      f"status={m.get('status')} bo={m.get('bo_type')}")

# 2) match DETAIL — what related objects exist?
for ident in (m.get("slug"), m.get("id")):
    if not ident: continue
    sc, det = g(f"matches/{ident}")
    base = det.get("data", det) if isinstance(det, dict) else {}
    if sc == 200 and base:
        print(f"\nmatch detail [{ident}]: keys = {sorted(base.keys())}")
        for k in ("games", "teams", "players", "lineups", "streams", "stage", "tournament"):
            v = base.get(k)
            if isinstance(v, list) and v and isinstance(v[0], dict):
                print(f"  {k}[0] keys: {sorted(v[0].keys())[:16]}")
            elif isinstance(v, dict):
                print(f"  {k} keys: {sorted(v.keys())[:16]}")
        break

# 3) games for this match — per-map info incl map name + player stats?
sc, gj = g("games", {"filter[games.match_id][eq]": m.get("id"), "page[limit]": 5})
grows = gj.get("data") or gj.get("games") or []
print(f"\ngames for match: {sc}, rows={len(grows)}")
if grows:
    g0 = grows[0]
    print("game keys:", sorted(g0.keys()))

# 4) per-game player stats endpoint? (several aggregators expose game_players)
gid = grows[0].get("id") if grows else None
for ep, params in [("players", {"page[limit]": 2}),
                   ("games/" + str(gid) + "/players" if gid else "players", None),
                   ("player_game_stats", {"filter[player_game_stats.game_id][eq]": gid, "page[limit]": 3}),
                   ("game_player_stats", {"page[limit]": 2})]:
    sc, pj = g(ep, params)
    n = len(pj.get("data", [])) if isinstance(pj, dict) else 0
    keys = sorted(pj.get("data")[0].keys())[:14] if isinstance(pj, dict) and pj.get("data") else []
    print(f"probe {ep}: {sc} rows={n} keys={keys}")
