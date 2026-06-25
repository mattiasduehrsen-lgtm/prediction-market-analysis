"""
Walk-forward feature engineering for CS2 / LoL win-probability modelling.

For every finished 2-team match we emit a feature row using ONLY information
available strictly before begin_at (no leakage). Ratings, form, rest, H2H are
all updated AFTER the row is emitted.

Outputs artifacts/{game}_features.parquet
"""
import json, math, sys
from pathlib import Path
import numpy as np, pandas as pd
import pyarrow.parquet as pq

_REPO = Path(__file__).resolve().parents[2]   # esports_model/src/ -> repo root
SNAP = _REPO / "cowork_snapshot"
PS = SNAP / "gamedata" / "pandascore"
OUT = _REPO / "esports_model" / "artifacts"
OUT.mkdir(parents=True, exist_ok=True)


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
    """match_id -> major.minor patch float (LoL only)."""
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
            self.mu[t] = 0.0; self.phi[t] = 350/173.7178; self.sigma[t] = 0.06
        return self.mu[t], self.phi[t], self.sigma[t]
    def rating(self, t):
        mu, phi, _ = self._get(t)
        return 1500 + 173.7178*mu, 173.7178*phi
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

    # state
    elo = {}                 # standard Elo (baseline-style)
    delo = {}                # time-decayed Elo
    last_played = {}         # team -> begin_at
    last_elo_t = {}          # team -> begin_at for decay
    hist = {}                # team -> list of recent (result) for form
    h2h = {}                 # (min,max) -> [A_wins_by_lower, n]
    games_ct = {}
    gl = Glicko()

    BASE = 1500.0; K = 32.0; DK = 40.0; DECAY_HALF = 180.0  # days

    rows = []
    for r in df.itertuples(index=False):
        a, b = r.teamA_id, r.teamB_id
        t = r.begin_at
        ea = elo.get(a, BASE); eb = elo.get(b, BASE)
        # decayed elo: pull toward base by inactivity half-life
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
        # form: last-10 win rate
        def form(team):
            h = hist.get(team, [])
            return (np.mean(h[-10:]) if h else 0.5), (sum(1 for _ in h[-10:]) and _streak(h))
        fa, sa_ = form(a); fb, sb_ = form(b)
        # rest days
        def rest(team):
            lp = last_played.get(team)
            return min((t-lp).total_seconds()/86400.0, 60.0) if lp is not None else 30.0
        ra = rest(a); rb = rest(b)
        # h2h
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
        })

        # ---- updates (after emitting) ----
        res = r.actualA
        # standard elo
        pa = 1/(1+10**(-(ea-eb)/400))
        elo[a] = ea + K*(res-pa); elo[b] = eb + K*((1-res)-(1-pa))
        # decayed elo (use decayed values as base, bigger K)
        pda = 1/(1+10**(-(da-db)/400))
        # margin multiplier from map score
        margin = abs(r.scoreA-r.scoreB); mult = math.log1p(margin) if margin > 0 else 0.5
        delo[a] = da + DK*mult*(res-pda); delo[b] = db + DK*mult*((1-res)-(1-pda))
        last_elo_t[a] = t; last_elo_t[b] = t
        # glicko
        gl.update(a, b, res)
        # bookkeeping
        hist.setdefault(a, []).append(res); hist.setdefault(b, []).append(1-res)
        last_played[a] = t; last_played[b] = t
        games_ct[a] = ga+1; games_ct[b] = gb+1
        if a < b: hh = [hh[0]+res, hh[1]+1]
        else: hh = [hh[0]+(1-res), hh[1]+1]
        h2h[key] = hh

    out = pd.DataFrame(rows)
    out.to_parquet(OUT / f"{game}_features.parquet", index=False)
    print(f"{game}: wrote {len(out):,} feature rows -> {game}_features.parquet")
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
