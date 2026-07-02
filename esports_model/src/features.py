"""
Walk-forward feature engineering for CS2 / LoL win-probability modelling. v2.

For every finished 2-team match we emit a feature row using ONLY information
available strictly before begin_at (no leakage). Ratings, form, rest, H2H are
all updated AFTER the row is emitted.

v2 additions:
  - Tournament tier (CS2: bo3.gg join via build_bo3_join.py; LoL: league-name
    mapping). Event tier is pre-match metadata (bo3 publishes it on upcoming
    matches), so joining it is leakage-safe.
  - CS2 map-level Elo aggregates (build_map_features.py), incl. Bo3 veto-sim.
  - Roster-staleness proxies: time-inflated Glicko phi (deviation grows with
    inactivity, Glicko-2-style), 90-day activity counts, long-gap flags, and
    a post-gap "rust" counter (matches since returning from a 45d+ break).
    These proxy roster changes: long-dormant teams usually return different.

Outputs artifacts/{game}_features.parquet
Run build_bo3_join.py and build_map_features.py first (cs2).
"""
import json, math, sys
from collections import deque
from pathlib import Path
import numpy as np, pandas as pd
import pyarrow.parquet as pq

_REPO = Path(__file__).resolve().parents[2]   # esports_model/src/ -> repo root
SNAP = _REPO / "cowork_snapshot"
PS = SNAP / "gamedata" / "pandascore"
OUT = _REPO / "esports_model" / "artifacts"
OUT.mkdir(parents=True, exist_ok=True)

PHI_MAX = 350 / 173.7178
GAP_DAYS = 45.0


def load_matches(game):
    df = pq.read_table(PS / f"{game}_matches.parquet").to_pandas()
    df["begin_at"] = pd.to_datetime(df["begin_at"], utc=True)
    df = df.dropna(subset=["winner_id", "teamA_id", "teamB_id"]).copy()
    df = df[df["teamA_id"] != df["teamB_id"]]
    df["begin_at"] = df["begin_at"].ffill()
    df = df.sort_values("begin_at").reset_index(drop=True)
    df["actualA"] = (df["winner_id"] == df["teamA_id"]).astype(int)
    df["scoreA"] = pd.to_numeric(df["scoreA"], errors="coerce").fillna(0)
    df["scoreB"] = pd.to_numeric(df["scoreB"], errors="coerce").fillna(0)
    df["num_games"] = pd.to_numeric(df["num_games"], errors="coerce").fillna(1)
    return df


def team_region(game):
    t = pq.read_table(PS / f"{game}_teams.parquet").to_pandas()
    return dict(zip(t["id"], t["location"].fillna("??")))


def lol_patch(match_ids):
    out = {}
    want = set(match_ids)
    with open(PS / "lol_matches_raw.jsonl") as f:
        for ln in f:
            x = json.loads(ln)
            mid = x.get("id")
            if mid not in want:
                continue
            v = x.get("videogame_version")
            if v:
                try:
                    a, b = v.split(".")[:2]
                    out[mid] = float(a) + float(b) / 100.0
                except Exception:
                    pass
    return out


def lol_league_tier(league):
    """Ordinal event tier for LoL from league name (0..4, like bo3 d..s)."""
    if not isinstance(league, str):
        return np.nan
    l = league.lower()
    if any(k in l for k in ("worlds", "mid-season invitational", "msi", "first stand")):
        return 4.0
    if any(k in l for k in ("challengers", "academy", "2nd division", "division 2",
                            "div 2", "ldl", "hesports", "second division")):
        return 1.0
    if l in ("lck", "lpl", "lec", "lcs") or l.startswith("lta") or l == "lcp":
        return 3.0
    return 2.0


# ----------------------------- Glicko-2 (lightweight) -----------------------
class Glicko:
    """Sequential Glicko-2; per-match update (rating period = 1 match)."""
    Q = math.log(10) / 400.0
    def __init__(self, tau=0.5):
        self.tau = tau
        self.mu = {}      # rating (Glicko-2 scale, 0 == 1500)
        self.phi = {}     # deviation
        self.sigma = {}   # volatility
    def _get(self, t):
        if t not in self.mu:
            self.mu[t] = 0.0; self.phi[t] = PHI_MAX; self.sigma[t] = 0.06
        return self.mu[t], self.phi[t], self.sigma[t]
    def rating(self, t):
        mu, phi, _ = self._get(t)
        return 1500 + 173.7178*mu, 173.7178*phi
    def phi_inflated(self, t, days_idle):
        """Glicko-2 style: deviation grows with inactivity (1 period ~ 7 days)."""
        _, phi, sigma = self._get(t)
        periods = max(days_idle, 0.0) / 7.0
        return 173.7178 * min(math.sqrt(phi*phi + sigma*sigma*periods), PHI_MAX)
    def expect(self, ta, tb):
        mua, phia, _ = self._get(ta); mub, phib, _ = self._get(tb)
        g = 1/math.sqrt(1 + 3*(phib**2)/(math.pi**2))
        return 1/(1+math.exp(-g*(mua-mub)))
    def update(self, ta, tb, sa):
        mua, phia, siga = self._get(ta); mub, phib, sigb = self._get(tb)
        self._one(ta, mua, phia, siga, mub, phib, sa)
        self._one(tb, mub, phib, sigb, mua, phia, 1-sa)
    def _one(self, t, mu, phi, sigma, mu_o, phi_o, s):
        g = 1/math.sqrt(1 + 3*(phi_o**2)/(math.pi**2))
        E = 1/(1+math.exp(-g*(mu-mu_o)))
        v = 1.0/(g*g*E*(1-E) + 1e-12)
        delta = v*g*(s-E)
        a = math.log(sigma**2); tau = self.tau
        def f(x):
            ex = math.exp(x)
            return (ex*(delta**2 - phi**2 - v - ex))/(2*(phi**2+v+ex)**2) - (x-a)/(tau**2)
        A = a; B = (math.log(delta**2 - phi**2 - v) if delta**2 > phi**2+v else a - tau)
        if delta**2 <= phi**2+v:
            k = 1
            while f(a-k*tau) < 0: k += 1
            B = a-k*tau
        fa, fb = f(A), f(B)
        for _ in range(60):
            C = A + (A-B)*fa/(fb-fa); fc = f(C)
            if fc*fb < 0: A, fa = B, fb
            else: fa /= 2
            B, fb = C, fc
            if abs(B-A) < 1e-6: break
        sigma_n = math.exp(A/2)
        phi_star = math.sqrt(phi**2 + sigma_n**2)
        phi_n = 1/math.sqrt(1/phi_star**2 + 1/v)
        mu_n = mu + phi_n**2 * g*(s-E)
        self.mu[t], self.phi[t], self.sigma[t] = mu_n, phi_n, sigma_n


# ----------------------------- forward pass --------------------------------
def build(game):
    df = load_matches(game)
    region = team_region(game)
    patch = lol_patch(df["match_id"].tolist()) if game == "lol" else {}

    elo = {}; delo = {}; last_played = {}; last_elo_t = {}
    hist = {}; h2h = {}; games_ct = {}
    recent = {}              # team -> deque of begin_at (90d activity)
    postgap = {}             # team -> matches since last 45d+ gap (capped 20)
    gl = Glicko()

    BASE = 1500.0; K = 32.0; DK = 40.0; DECAY_HALF = 180.0  # days

    rows = []
    for r in df.itertuples(index=False):
        a, b = r.teamA_id, r.teamB_id
        t = r.begin_at
        ea = elo.get(a, BASE); eb = elo.get(b, BASE)
        def decayed(team):
            v = delo.get(team, BASE); lt = last_elo_t.get(team)
            if lt is not None:
                days = (t - lt).total_seconds()/86400.0
                w = 0.5 ** (days/DECAY_HALF)
                v = BASE + (v-BASE)*w
            return v
        da = decayed(a); db = decayed(b)
        gmu_a, gphi_a = gl.rating(a); gmu_b, gphi_b = gl.rating(b)

        ga = games_ct.get(a, 0); gb = games_ct.get(b, 0)
        def form(team):
            h = hist.get(team, [])
            return (np.mean(h[-10:]) if h else 0.5), (sum(1 for _ in h[-10:]) and _streak(h))
        fa, sa_ = form(a); fb, sb_ = form(b)
        def rest(team):
            lp = last_played.get(team)
            return min((t-lp).total_seconds()/86400.0, 60.0) if lp is not None else 30.0
        ra = rest(a); rb = rest(b)
        def idle(team):
            lp = last_played.get(team)
            return (t-lp).total_seconds()/86400.0 if lp is not None else 365.0
        ia = idle(a); ib = idle(b)
        def act90(team):
            q = recent.get(team)
            if q is None: return 0
            cut = t - pd.Timedelta(days=90)
            while q and q[0] < cut: q.popleft()
            return len(q)
        aa = act90(a); ab = act90(b)
        phi_ia = gl.phi_inflated(a, ia); phi_ib = gl.phi_inflated(b, ib)
        key = (min(a, b), max(a, b)); hh = h2h.get(key, [0, 0])
        if hh[1] > 0:
            lower_wr = hh[0]/hh[1]
            h2h_a = lower_wr if a < b else 1-lower_wr
        else:
            h2h_a = 0.5
        rows.append({
            "match_id": r.match_id, "begin_at": t, "actualA": r.actualA,
            "elo_diff": ea-eb,
            "elo_prob": 1/(1+10**(-(ea-eb)/400)),
            "delo_diff": da-db,
            "glicko_mu_diff": gmu_a-gmu_b,
            "glicko_phi_a": gphi_a, "glicko_phi_b": gphi_b,
            "glicko_prob": gl.expect(a, b),
            "games_a": ga, "games_b": gb,
            "loggames_diff": math.log1p(ga)-math.log1p(gb),
            "form10_diff": fa-fb, "form10_a": fa, "form10_b": fb,
            "streak_diff": (sa_ or 0)-(sb_ or 0),
            "rest_a": ra, "rest_b": rb, "rest_diff": ra-rb,
            "h2h_a": h2h_a, "h2h_n": hh[1],
            "num_games": r.num_games,
            "same_region": int(region.get(a, "?") == region.get(b, "?")),
            "patch": patch.get(r.match_id, np.nan),
            "new_a": int(ga < 5), "new_b": int(gb < 5),
            # --- v2 roster-staleness proxies ---
            "phi_infl_a": phi_ia, "phi_infl_b": phi_ib,
            "phi_infl_diff": phi_ia-phi_ib,
            "act90_a": aa, "act90_b": ab, "act90_diff": aa-ab,
            "longgap_a": int(ia >= GAP_DAYS), "longgap_b": int(ib >= GAP_DAYS),
            "postgap_a": min(postgap.get(a, 20), 20), "postgap_b": min(postgap.get(b, 20), 20),
        })

        # ---- updates (after emitting) ----
        res = r.actualA
        pa = 1/(1+10**(-(ea-eb)/400))
        elo[a] = ea + K*(res-pa); elo[b] = eb + K*((1-res)-(1-pa))
        pda = 1/(1+10**(-(da-db)/400))
        margin = abs(r.scoreA-r.scoreB); mult = math.log1p(margin) if margin > 0 else 0.5
        delo[a] = da + DK*mult*(res-pda); delo[b] = db + DK*mult*((1-res)-(1-pda))
        last_elo_t[a] = t; last_elo_t[b] = t
        gl.update(a, b, res)
        hist.setdefault(a, []).append(res); hist.setdefault(b, []).append(1-res)
        # post-gap rust counter: reset on 45d+ gap, else increment
        for team, gap in ((a, ia), (b, ib)):
            if gap >= GAP_DAYS: postgap[team] = 0
            else: postgap[team] = postgap.get(team, 20) + 1
        recent.setdefault(a, deque()).append(t); recent.setdefault(b, deque()).append(t)
        last_played[a] = t; last_played[b] = t
        games_ct[a] = ga+1; games_ct[b] = gb+1
        if a < b: hh = [hh[0]+res, hh[1]+1]
        else: hh = [hh[0]+(1-res), hh[1]+1]
        h2h[key] = hh

    out = pd.DataFrame(rows)

    # ---- v2 context merges (all pre-match event metadata) ----
    if game == "cs2":
        tier = pq.read_table(OUT / "cs2_bo3_join.parquet").to_pandas()
        tier = tier[["match_id", "tier_ord", "bo3_rating", "bo3_stars", "tier_source"]]
        out = out.merge(tier, on="match_id", how="left")
        out["tier_is_s"] = (out.tier_ord == 4).astype(float).where(out.tier_ord.notna())
        out["tier_known"] = out.tier_ord.notna().astype(int)
        out = out.drop(columns=["tier_source"])
        mf = pq.read_table(OUT / "cs2_map_feats.parquet").to_pandas()
        out = out.merge(mf, on="match_id", how="left")
    else:
        mm = pq.read_table(PS / f"{game}_matches.parquet").to_pandas()[["match_id", "league"]]
        out = out.merge(mm, on="match_id", how="left")
        out["tier_ord"] = out.league.map(lol_league_tier)
        out["tier_is_s"] = (out.tier_ord == 4).astype(float)
        out["tier_known"] = out.tier_ord.notna().astype(int)
        out = out.drop(columns=["league"])
        for c in ("bo3_rating", "bo3_stars", "mapelo_veto_prob", "mapelo_mean_diff",
                  "mapelo_best_diff", "mapelo_worst_diff", "mapelo_spread", "mapelo_ngames"):
            out[c] = np.nan

    out.to_parquet(OUT / f"{game}_features.parquet", index=False)
    print(f"{game}: wrote {len(out):,} feature rows -> {game}_features.parquet "
          f"(tier known {out.tier_known.mean():.1%}, mapelo {out.mapelo_veto_prob.notna().mean():.1%})")
    return out


def _streak(h):
    if not h: return 0
    s = 0; last = h[-1]
    for v in reversed(h):
        if v == last: s += 1
        else: break
    return s if last == 1 else -s


if __name__ == "__main__":
    for g in (sys.argv[1:] or ["cs2", "lol"]):
        build(g)
