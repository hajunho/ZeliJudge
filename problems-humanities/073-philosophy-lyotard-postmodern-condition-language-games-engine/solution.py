import sys
import os
import json
import copy

if sys.platform == "win32":
    try:
        sys.stdin.reconfigure(encoding="utf-8")
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

class LyotardPostmodernEngine:
    def __init__(self, config: dict):
        self.config = copy.deepcopy(config)
        self.metanarrative_legitimacy = float(self.config.get("initial_metanarrative_legitimacy", 0.6))
        self.performativity_pressure = float(self.config.get("initial_performativity_pressure", 0.4))
        self.language_games_plurality = float(self.config.get("initial_language_games_plurality", 0.3))
        self.paralogy_index = float(self.config.get("initial_paralogy_index", 0.2))

        self.event_log = []
        self.history = []
        self.stats = {
            "metanarrative_assertions": 0,
            "incredulity_deconstructions": 0,
            "language_games_created": 0,
            "paralogy_moves": 0,
            "performativity_enforcements": 0,
            "max_postmodern_dispersion": 0.0,
            "postmodern_paralogy_epochs": 0
        }

    def log(self, msg: str):
        self.event_log.append(msg)

    def calc_dispersion_index(self) -> float:
        num = ((1.0 - self.metanarrative_legitimacy) * 0.40 +
               self.language_games_plurality * 0.35 +
               self.paralogy_index * 0.25)
        denom = 1.0 + 0.5 * self.performativity_pressure
        d_raw = num / denom
        d_idx = round(min(1.0, max(0.0, d_raw)), 4)
        if d_idx > self.stats["max_postmodern_dispersion"]:
            self.stats["max_postmodern_dispersion"] = d_idx
        return d_idx

    def calc_epoch(self, d_idx: float) -> str:
        if d_idx >= 0.70:
            return "POSTMODERN_PARALOGY"
        elif d_idx >= 0.40:
            return "PERFORMATIVE_TECHNOCRACY"
        else:
            return "MODERN_TOTALITARIAN_CONSENSUS"

    def assert_metanarrative(self, narrative_name: str, dogma_intensity: float, hegemony_force: float) -> dict:
        self.stats["metanarrative_assertions"] += 1

        self.metanarrative_legitimacy = round(min(1.0, self.metanarrative_legitimacy + dogma_intensity * 0.18 + hegemony_force * 0.10), 4)
        self.language_games_plurality = round(max(0.0, self.language_games_plurality - hegemony_force * 0.15), 4)
        self.paralogy_index = round(max(0.0, self.paralogy_index - dogma_intensity * 0.12), 4)

        d_idx = self.calc_dispersion_index()
        epoch = self.calc_epoch(d_idx)
        if epoch == "POSTMODERN_PARALOGY":
            self.stats["postmodern_paralogy_epochs"] += 1

        self.log(f"ASSERT_METANARRATIVE: '{narrative_name}' dogma={dogma_intensity} hegemony={hegemony_force} -> D={d_idx} ({epoch})")
        res = {
            "op": "ASSERT_METANARRATIVE",
            "narrative_name": narrative_name,
            "metanarrative_legitimacy": self.metanarrative_legitimacy,
            "language_games_plurality": self.language_games_plurality,
            "paralogy_index": self.paralogy_index,
            "postmodern_dispersion": d_idx,
            "epoch": epoch
        }
        self.history.append(res)
        return res

    def deconstruct_grand_recits(self, critique_target: str, incredulity_level: float) -> dict:
        self.stats["incredulity_deconstructions"] += 1

        self.metanarrative_legitimacy = round(max(0.0, self.metanarrative_legitimacy - incredulity_level * 0.25), 4)
        self.language_games_plurality = round(min(1.0, self.language_games_plurality + incredulity_level * 0.12), 4)

        d_idx = self.calc_dispersion_index()
        epoch = self.calc_epoch(d_idx)
        if epoch == "POSTMODERN_PARALOGY":
            self.stats["postmodern_paralogy_epochs"] += 1

        self.log(f"DECONSTRUCT_GRAND_RECITS: target='{critique_target}' incredulity={incredulity_level} -> D={d_idx} ({epoch})")
        res = {
            "op": "DECONSTRUCT_GRAND_RECITS",
            "critique_target": critique_target,
            "metanarrative_legitimacy": self.metanarrative_legitimacy,
            "language_games_plurality": self.language_games_plurality,
            "postmodern_dispersion": d_idx,
            "epoch": epoch
        }
        self.history.append(res)
        return res

    def introduce_language_game(self, game_type: str, player_count: int, rule_agility: float) -> dict:
        self.stats["language_games_created"] += 1

        boost = rule_agility * 0.15 + min(0.15, player_count * 0.02)
        self.language_games_plurality = round(min(1.0, self.language_games_plurality + boost), 4)
        self.performativity_pressure = round(max(0.0, self.performativity_pressure - rule_agility * 0.05), 4)

        d_idx = self.calc_dispersion_index()
        epoch = self.calc_epoch(d_idx)
        if epoch == "POSTMODERN_PARALOGY":
            self.stats["postmodern_paralogy_epochs"] += 1

        self.log(f"INTRODUCE_LANGUAGE_GAME: type={game_type} players={player_count} agility={rule_agility} -> D={d_idx} ({epoch})")
        res = {
            "op": "INTRODUCE_LANGUAGE_GAME",
            "game_type": game_type,
            "player_count": player_count,
            "language_games_plurality": self.language_games_plurality,
            "performativity_pressure": self.performativity_pressure,
            "postmodern_dispersion": d_idx,
            "epoch": epoch
        }
        self.history.append(res)
        return res

    def generate_paralogy(self, innovation_move: str, dissensus_power: float) -> dict:
        self.stats["paralogy_moves"] += 1

        self.paralogy_index = round(min(1.0, self.paralogy_index + dissensus_power * 0.25), 4)
        self.metanarrative_legitimacy = round(max(0.0, self.metanarrative_legitimacy - dissensus_power * 0.15), 4)
        self.performativity_pressure = round(max(0.0, self.performativity_pressure - dissensus_power * 0.10), 4)

        d_idx = self.calc_dispersion_index()
        epoch = self.calc_epoch(d_idx)
        if epoch == "POSTMODERN_PARALOGY":
            self.stats["postmodern_paralogy_epochs"] += 1

        self.log(f"GENERATE_PARALOGY: move='{innovation_move}' dissensus={dissensus_power} -> D={d_idx} ({epoch})")
        res = {
            "op": "GENERATE_PARALOGY",
            "innovation_move": innovation_move,
            "paralogy_index": self.paralogy_index,
            "metanarrative_legitimacy": self.metanarrative_legitimacy,
            "performativity_pressure": self.performativity_pressure,
            "postmodern_dispersion": d_idx,
            "epoch": epoch
        }
        self.history.append(res)
        return res

    def enforce_performativity(self, efficiency_metric: str, market_optimization: float) -> dict:
        self.stats["performativity_enforcements"] += 1

        self.performativity_pressure = round(min(1.0, self.performativity_pressure + market_optimization * 0.20), 4)
        self.paralogy_index = round(max(0.0, self.paralogy_index - market_optimization * 0.08), 4)

        d_idx = self.calc_dispersion_index()
        epoch = self.calc_epoch(d_idx)

        self.log(f"ENFORCE_PERFORMATIVITY: metric='{efficiency_metric}' opt={market_optimization} -> D={d_idx} ({epoch})")
        res = {
            "op": "ENFORCE_PERFORMATIVITY",
            "efficiency_metric": efficiency_metric,
            "performativity_pressure": self.performativity_pressure,
            "paralogy_index": self.paralogy_index,
            "postmodern_dispersion": d_idx,
            "epoch": epoch
        }
        self.history.append(res)
        return res

    def get_state(self) -> dict:
        d_idx = self.calc_dispersion_index()
        epoch = self.calc_epoch(d_idx)
        return {
            "op": "GET_STATE",
            "metanarrative_legitimacy": self.metanarrative_legitimacy,
            "performativity_pressure": self.performativity_pressure,
            "language_games_plurality": self.language_games_plurality,
            "paralogy_index": self.paralogy_index,
            "postmodern_dispersion": d_idx,
            "epoch": epoch
        }

    def get_final_summary(self) -> dict:
        d_idx = self.calc_dispersion_index()
        epoch = self.calc_epoch(d_idx)
        return {
            "metanarrative_legitimacy": self.metanarrative_legitimacy,
            "performativity_pressure": self.performativity_pressure,
            "language_games_plurality": self.language_games_plurality,
            "paralogy_index": self.paralogy_index,
            "postmodern_dispersion": d_idx,
            "epoch": epoch,
            "stats": self.stats,
            "event_count": len(self.event_log)
        }

def solve():
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return
    data = json.loads(raw_input)
    eng = LyotardPostmodernEngine(data["config"])
    results = []
    for op in data.get("operations", []):
        cmd = op["op"]
        if cmd == "ASSERT_METANARRATIVE":
            res = eng.assert_metanarrative(
                narrative_name=op["narrative_name"],
                dogma_intensity=float(op.get("dogma_intensity", 0.5)),
                hegemony_force=float(op.get("hegemony_force", 0.5))
            )
            results.append(res)
        elif cmd == "DECONSTRUCT_GRAND_RECITS":
            res = eng.deconstruct_grand_recits(
                critique_target=op["critique_target"],
                incredulity_level=float(op.get("incredulity_level", 0.5))
            )
            results.append(res)
        elif cmd == "INTRODUCE_LANGUAGE_GAME":
            res = eng.introduce_language_game(
                game_type=op.get("game_type", "DENOTATIVE"),
                player_count=int(op.get("player_count", 4)),
                rule_agility=float(op.get("rule_agility", 0.5))
            )
            results.append(res)
        elif cmd == "GENERATE_PARALOGY":
            res = eng.generate_paralogy(
                innovation_move=op["innovation_move"],
                dissensus_power=float(op.get("dissensus_power", 0.5))
            )
            results.append(res)
        elif cmd == "ENFORCE_PERFORMATIVITY":
            res = eng.enforce_performativity(
                efficiency_metric=op["efficiency_metric"],
                market_optimization=float(op.get("market_optimization", 0.5))
            )
            results.append(res)
        elif cmd == "GET_STATE":
            res = eng.get_state()
            results.append(res)

    output = {
        "results": results,
        "final_summary": eng.get_final_summary()
    }
    print(json.dumps(output, ensure_ascii=False))

if __name__ == "__main__":
    solve()
