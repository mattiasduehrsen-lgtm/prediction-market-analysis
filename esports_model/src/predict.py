"""Production win-probability predictor for CS2 / LoL.

    from predict import Predictor
    p = Predictor("cs2")
    p.predict("Vitality", "NRG")  -> {ok, model_prob_a, elo_prob_a, ...}

Loads only parquet/joblib artifacts produced by features.py / train.py /
build_state.py. No raw data needed at inference time.
"""
import re, json, math
from pathlib import Path
import numpy as np, pandas as pd, joblib

ART = Path(__file__).resolve().parent.parent / "artifacts"
BASE, DECAY_HALF, S = 1500.0, 180.0, 173.7178
FEATS = ["elo_diff", "elo_prob", "delo_diff", "glicko_mu_diff", "glicko_phi_a",
         "glicko_phi_b", "glicko_prob", "loggames_diff", "form10_diff",
         "form10_a", "form10_b", "streak_diff", "rest_a", "rest_b", "rest_diff",
         "h2h_a", "h2h_n", "num_games", "same_region", "patch", "new_a", "new_b",
         "games_a", "games_b"]


def _norm(s):
    if not isinstance(s, str): return ""
    s = s.split(" (")[0].split(" - ")[0].lower().strip()
    s = re.sub(r"\b(esports|esport|gaming|team|club|gg|e-sports)\b", "", s)
    return re.sub(r"[^a-z0-9]", "", s)


# Curated acronym/short-name -> canonical aliases. Markets often use the acronym
# (e.g. LoL "JDG") while the model state holds the full name ("JD Gaming"). Extend
# per game via artifacts/{game}_aliases.json (same {alias: canonical} shape).
SEED_ALIASES = {
    "lol": {
        "JDG": "JD Gaming", "BLG": "Bilibili Gaming", "TES": "Top Esports",
        "LNG": "LNG Esports", "WBG": "Weibo Gaming", "HLE": "Hanwha Life Esports",
        "GEN": "Gen.G", "GENG": "Gen.G", "DK": "Dplus KIA", "DWG": "Dplus KIA",
        "KT": "KT Rolster", "FNC": "Fnatic", "G2": "G2 Esports", "C9": "Cloud9",
        "TL": "Team Liquid", "FLY": "FlyQuest", "100T": "100 Thieves",
        "KC": "Karmine Corp", "MKOI": "Movistar KOI", "GX": "GiantX",
        "SK": "SK Gaming", "VIT": "Team Vitality", "AL": "Anyone's Legends",
        "CTBC": "CTBC Flying Oyster", "CFO": "CTBC Flying Oyster",
        "NIP": "Ninjas in Pyjamas", "Dplus": "Dplus KIA", "DRX": "DRX",
        "NS": "Nongshim RedForce", "Nongshim": "Nongshim RedForce",
        "BRO": "OKSavingsBank BRION", "BRION": "OKSavingsBank BRION",
        "PSG": "PSG Talon", "PNG": "Paris Saint-Germain Talon",
    },
    "cs2": {
        "NAVI": "Natus Vincere", "G2": "G2 Esports", "FAZE": "FaZe Clan",
        "VIT": "Team Vitality", "SPIRIT": "Team Spirit", "TL": "Team Liquid",
        "ENCE": "ENCE", "BIG": "BIG", "FUR": "FURIA",
    },
}


class Predictor:
    def __init__(self, game, default_num_games=3):
        self.game = game; self.default_num_games = default_num_games
        b = joblib.load(ART / f"{game}_model.joblib")
        self.clf, self.iso = b["clf"], b["iso"]
        st = pd.read_parquet(ART / f"{game}_team_state.parquet")
        st["nkey"] = st.name.map(_norm)
        # keep the most-played row per name key
        st = st.sort_values("games").drop_duplicates("nkey", keep="last")
        self.state = {r.nkey: r for r in st.itertuples(index=False)}
        h = pd.read_parquet(ART / f"{game}_h2h.parquet")
        self.h2h = {(int(r.a), int(r.b)): (r.wins_low, r.n) for r in h.itertuples(index=False)}
        self.meta = json.loads((ART / f"{game}_state_meta.json").read_text())
        # alias map: norm(alias) -> norm(canonical), from seed + optional JSON file
        self.aliases = {}
        for k, v in SEED_ALIASES.get(game, {}).items():
            self.aliases[_norm(k)] = _norm(v)
        ap = ART / f"{game}_aliases.json"
        if ap.exists():
            try:
                for k, v in json.loads(ap.read_text()).items():
                    self.aliases[_norm(k)] = _norm(v)
            except Exception:
                pass

    def _row(self, name):
        n = _norm(name)
        r = self.state.get(n)
        if r is not None:
            return r
        # 1) curated alias
        a = self.aliases.get(n)
        if a and a in self.state:
            return self.state[a]
        # 2) conservative fuzzy: substring match, but ONLY if it's unambiguous
        #    (exactly one state key contains/!is-contained-by n) to avoid mispicks.
        if len(n) >= 4:
            cands = [row for k, row in self.state.items()
                     if len(k) >= 4 and (n in k or k in n)]
            if len(cands) == 1:
                return cands[0]
        return None

    def predict(self, team_a, team_b, num_games=None, at_time=None):
        ra, rb = self._row(team_a), self._row(team_b)
        miss = [n for n, r in ((team_a, ra), (team_b, rb)) if r is None]
        if miss:
            return {"ok": False, "error": f"unknown team(s): {miss}"}
        now = pd.Timestamp(at_time, tz="UTC") if at_time else pd.Timestamp.utcnow().tz_localize("UTC") \
            if pd.Timestamp.utcnow().tz is None else pd.Timestamp.utcnow()
        now_ns = int(now.value)
        ng = num_games if num_games is not None else self.default_num_games

        def decay(r):
            days = max((now_ns - r.last_elo_ns) / 86400e9, 0)
            return BASE + (r.delo - BASE) * 0.5 ** (days / DECAY_HALF)
        def rest(r):
            return min(max((now_ns - r.last_played_ns) / 86400e9, 0), 60.0)
        da, db = decay(ra), decay(rb)
        mua, mub = (ra.glicko_mu - BASE) / S, (rb.glicko_mu - BASE) / S
        phia, phib = ra.glicko_phi / S, rb.glicko_phi / S
        g = 1 / math.sqrt(1 + 3 * phib ** 2 / math.pi ** 2)
        glicko_prob = 1 / (1 + math.exp(-g * (mua - mub)))
        key = (min(ra.team_id, rb.team_id), max(ra.team_id, rb.team_id))
        wl, hn = self.h2h.get(key, (0, 0))
        h2h_a = (wl / hn if hn else 0.5) if ra.team_id < rb.team_id else (1 - wl / hn if hn else 0.5)
        elo_prob = 1 / (1 + 10 ** (-(ra.elo - rb.elo) / 400))
        feat = {
            "elo_diff": ra.elo - rb.elo, "elo_prob": elo_prob, "delo_diff": da - db,
            "glicko_mu_diff": ra.glicko_mu - rb.glicko_mu,
            "glicko_phi_a": ra.glicko_phi, "glicko_phi_b": rb.glicko_phi,
            "glicko_prob": glicko_prob,
            "loggames_diff": math.log1p(ra.games) - math.log1p(rb.games),
            "form10_diff": ra.form10 - rb.form10, "form10_a": ra.form10, "form10_b": rb.form10,
            "streak_diff": ra.streak - rb.streak,
            "rest_a": rest(ra), "rest_b": rest(rb), "rest_diff": rest(ra) - rest(rb),
            "h2h_a": h2h_a, "h2h_n": hn, "num_games": ng,
            "same_region": int(ra.location == rb.location),
            "patch": self.meta.get("patch_default", np.nan),
            "new_a": int(ra.games < 5), "new_b": int(rb.games < 5),
            "games_a": ra.games, "games_b": rb.games,
        }
        X = pd.DataFrame([[feat[k] for k in FEATS]], columns=FEATS)
        raw = self.clf.predict_proba(X)[0, 1]
        prob = float(self.iso.transform([raw])[0])
        return {"ok": True, "game": self.game, "team_a": team_a, "team_b": team_b,
                "model_prob_a": round(prob, 4), "model_prob_b": round(1 - prob, 4),
                "elo_prob_a": round(float(elo_prob), 4), "glicko_prob_a": round(glicko_prob, 4),
                "games_a": int(ra.games), "games_b": int(rb.games)}


if __name__ == "__main__":
    import sys
    g = sys.argv[1] if len(sys.argv) > 1 else "cs2"
    p = Predictor(g)
    tests = ([("Vitality", "NRG"), ("Spirit", "FaZe"), ("MOUZ", "G2")] if g == "cs2"
             else [("T1", "Gen.G"), ("JDG", "BLG"), ("G2 Esports", "Fnatic")])
    for a, b in tests:
        print(p.predict(a, b))
