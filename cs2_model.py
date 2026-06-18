"""Shared CS2 Elo model logic for the paper betting bot.

Loads current team Elo ratings (built by analysis/build_elo.py from PandaScore
match history) and provides team-name matching + win-probability.
"""
from __future__ import annotations
import re
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parent
GD = ROOT / "cowork_snapshot" / "gamedata"
MIN_GAMES = 10   # don't trust Elo for teams with fewer prior matches


def norm(s):
    if not isinstance(s, str): return ""
    s = s.lower()
    s = re.sub(r"\(.*?\)", " ", s)
    s = s.replace("ex-", " ")
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    s = re.sub(r"\bbo\d\b", " ", s)
    # strip org-suffix words as WHOLE WORDS anywhere (not just space-delimited),
    # so "9z Team"->"9z", "Team Spirit"->"spirit" both normalize to match the
    # PandaScore key. (Keeps academy/fe/junior suffixes — those ARE distinct teams.)
    s = re.sub(r"\b(esports|e sports|gaming|team|clan)\b", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def is_handicap(a, b):
    blob = f"{a} {b}".lower()
    return ("handicap" in blob or "rounds" in blob
            or re.search(r"[+-]\d+\.?\d*\)?$", a or "") is not None
            or re.search(r"[+-]\d+\.?\d*\)?$", b or "") is not None)


def teq(x, y):
    return bool(x) and bool(y) and (x == y or (len(x) >= 4 and len(y) >= 4 and (x in y or y in x)))


class CS2Model:
    def __init__(self):
        self.elo_by_id: dict[int, tuple[float, int]] = {}
        self.name_to_id: dict[str, int] = {}
        self.id_to_name: dict[int, str] = {}
        self._mtime = 0.0
        self.load()

    def _register(self, n, tid):
        """Map normalized name -> team id, resolving collisions by PREFERRING THE
        TEAM WITH MORE PRIOR GAMES. Multiple teams can normalize to the same name
        (e.g. 'Team Falcons' [308 games] and a minor 'Falcons' [7 games] both ->
        'falcons'). First-writer-wins used to hand the name to whichever was loaded
        first — often the low-games minor team — which then false-rejected every
        real matchup as low_games. The established roster (more games) is the
        intended team for a CS2 market, so it wins the name."""
        if not n:
            return
        cur = self.name_to_id.get(n)
        if cur is None:
            self.name_to_id[n] = tid
        elif cur != tid and self.elo_by_id.get(tid, (0, 0))[1] > self.elo_by_id.get(cur, (0, 0))[1]:
            self.name_to_id[n] = tid

    def load(self):
        elo_path = GD / "pandascore" / "cs2_elo_final.parquet"
        teams_path = GD / "pandascore" / "cs2_teams.parquet"
        if not elo_path.exists():
            return
        try:
            self._mtime = elo_path.stat().st_mtime
            elo = pd.read_parquet(elo_path)
            self.elo_by_id = {int(r.team_id): (float(r.elo), int(r.games))
                              for r in elo.itertuples(index=False)}
            # name/acronym -> id from teams table; also from elo history names.
            # Collisions resolve to the higher-games team (see _register).
            self.name_to_id.clear(); self.id_to_name.clear()
            if teams_path.exists():
                t = pd.read_parquet(teams_path)
                for r in t.itertuples(index=False):
                    if r.id is None: continue
                    self.id_to_name[int(r.id)] = r.name
                    for nm in (r.name, r.acronym, r.slug):
                        self._register(norm(nm), int(r.id))
            # also pull names from elo history (covers teams not in teams table)
            hist = GD / "pandascore" / "cs2_elo_history.parquet"
            if hist.exists():
                h = pd.read_parquet(hist, columns=["teamA_id", "teamA_name", "teamB_id", "teamB_name"])
                for r in h.itertuples(index=False):
                    for tid, nm in [(r.teamA_id, r.teamA_name), (r.teamB_id, r.teamB_name)]:
                        if tid is None: continue
                        self.id_to_name.setdefault(int(tid), nm)
                        self._register(norm(nm), int(tid))
        except Exception as e:
            print(f"[cs2-model] load failed: {e}")

    def maybe_reload(self):
        try:
            m = (GD / "pandascore" / "cs2_elo_final.parquet").stat().st_mtime
        except OSError:
            return
        if m > self._mtime:
            print("[cs2-model] reloading Elo (refreshed)")
            self.load()

    def match_team(self, name):
        """Return (team_id, elo, games) for a Polymarket team name, or None."""
        n = norm(name)
        if not n:
            return None
        tid = self.name_to_id.get(n)
        if tid is None:
            # fuzzy: substring match against known names
            for kn, kid in self.name_to_id.items():
                if teq(n, kn):
                    tid = kid; break
        if tid is None:
            return None
        eg = self.elo_by_id.get(tid)
        if not eg:
            return None
        return tid, eg[0], eg[1]

    def predict(self, teamA_name, teamB_name):
        """Return dict with model_pA and team info, or None if unmatchable/unreliable."""
        if is_handicap(teamA_name, teamB_name):
            return None
        a = self.match_team(teamA_name)
        b = self.match_team(teamB_name)
        if not a or not b:
            return {"ok": False, "reason": "unmatched",
                    "a": a is not None, "b": b is not None}
        if a[2] < MIN_GAMES or b[2] < MIN_GAMES:
            return {"ok": False, "reason": "low_games", "gamesA": a[2], "gamesB": b[2]}
        eloA, eloB = a[1], b[1]
        pA = 1.0 / (1.0 + 10 ** ((eloB - eloA) / 400.0))
        return {"ok": True, "model_pA": round(pA, 4),
                "eloA": round(eloA, 1), "eloB": round(eloB, 1),
                "gamesA": a[2], "gamesB": b[2]}
