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

class AdornoCultureIndustryEngine:
    def __init__(self, config: dict):
        self.config = copy.deepcopy(config)
        self.critical_consciousness = float(self.config.get("initial_critical_consciousness", 0.5))
        self.standardization_level = float(self.config.get("initial_standardization", 0.4))
        self.pseudo_individualization = float(self.config.get("initial_pseudo_individualization", 0.3))
        self.instrumental_rationality = float(self.config.get("initial_instrumental_rationality", 0.4))

        self.event_log = []
        self.history = []
        self.stats = {
            "commodities_produced": 0,
            "avant_garde_interventions": 0,
            "retro_repackagings": 0,
            "critical_critiques": 0,
            "max_mass_deception_index": 0.0,
            "total_deception_epochs": 0
        }

    def log(self, msg: str):
        self.event_log.append(msg)

    def calc_mass_deception_index(self) -> float:
        num = (self.standardization_level * 0.45 +
               self.pseudo_individualization * 0.35 +
               self.instrumental_rationality * 0.20)
        denom = 1.0 + 0.5 * self.critical_consciousness
        m_raw = num / denom
        m_idx = round(min(1.0, max(0.0, m_raw)), 4)
        if m_idx > self.stats["max_mass_deception_index"]:
            self.stats["max_mass_deception_index"] = m_idx
        return m_idx

    def calc_regime(self, m_idx: float) -> str:
        if m_idx >= 0.70:
            return "TOTAL_MASS_DECEPTION"
        elif m_idx >= 0.40:
            return "COMMODIFIED_CONFORMISM"
        else:
            return "AUTONOMOUS_CRITICAL_SPHERE"

    def produce_commodity(self, title: str, genre: str, formulaic_score: float, surface_novelty: float, marketing_budget: float) -> dict:
        self.stats["commodities_produced"] += 1

        self.standardization_level = round(min(1.0, self.standardization_level + formulaic_score * 0.12), 4)

        novelty_effect = surface_novelty * 0.15 * (1.0 - abs(formulaic_score - 0.5))
        self.pseudo_individualization = round(min(1.0, self.pseudo_individualization + novelty_effect), 4)

        self.instrumental_rationality = round(min(1.0, self.instrumental_rationality + min(0.20, marketing_budget * 0.02)), 4)

        consciousness_decay = formulaic_score * 0.08 + self.pseudo_individualization * 0.05
        self.critical_consciousness = round(max(0.0, self.critical_consciousness - consciousness_decay), 4)

        m_idx = self.calc_mass_deception_index()
        regime = self.calc_regime(m_idx)
        if regime == "TOTAL_MASS_DECEPTION":
            self.stats["total_deception_epochs"] += 1

        self.log(f"PRODUCE_COMMODITY: '{title}' [{genre}] f={formulaic_score} n={surface_novelty} -> M={m_idx} ({regime})")
        res = {
            "op": "PRODUCE_CULTURAL_COMMODITY",
            "title": title,
            "genre": genre,
            "standardization": self.standardization_level,
            "pseudo_individualization": self.pseudo_individualization,
            "instrumental_rationality": self.instrumental_rationality,
            "critical_consciousness": self.critical_consciousness,
            "mass_deception_index": m_idx,
            "regime": regime
        }
        self.history.append(res)
        return res

    def inject_avant_garde(self, work_name: str, dissonance_factor: float, intellectual_challenge: float) -> dict:
        self.stats["avant_garde_interventions"] += 1

        self.standardization_level = round(max(0.0, self.standardization_level - dissonance_factor * 0.20), 4)
        self.pseudo_individualization = round(max(0.0, self.pseudo_individualization - intellectual_challenge * 0.18), 4)

        boost = dissonance_factor * 0.15 + intellectual_challenge * 0.15
        self.critical_consciousness = round(min(1.0, self.critical_consciousness + boost), 4)

        m_idx = self.calc_mass_deception_index()
        regime = self.calc_regime(m_idx)

        self.log(f"AVANT_GARDE_INJECTED: '{work_name}' dissonance={dissonance_factor} challenge={intellectual_challenge} -> M={m_idx} ({regime})")
        res = {
            "op": "INJECT_AVANT_GARDE_ART",
            "work_name": work_name,
            "standardization": self.standardization_level,
            "pseudo_individualization": self.pseudo_individualization,
            "critical_consciousness": self.critical_consciousness,
            "mass_deception_index": m_idx,
            "regime": regime
        }
        self.history.append(res)
        return res

    def apply_retro_repackaging(self, target_trend: str, nostalgia_intensity: float) -> dict:
        self.stats["retro_repackagings"] += 1

        self.pseudo_individualization = round(min(1.0, self.pseudo_individualization + nostalgia_intensity * 0.25), 4)
        self.standardization_level = round(min(1.0, self.standardization_level + nostalgia_intensity * 0.08), 4)

        m_idx = self.calc_mass_deception_index()
        regime = self.calc_regime(m_idx)
        if regime == "TOTAL_MASS_DECEPTION":
            self.stats["total_deception_epochs"] += 1

        self.log(f"RETRO_REPACKAGING: '{target_trend}' nostalgia={nostalgia_intensity} -> M={m_idx} ({regime})")
        res = {
            "op": "APPLY_RETRO_REPACKAGING",
            "target_trend": target_trend,
            "standardization": self.standardization_level,
            "pseudo_individualization": self.pseudo_individualization,
            "mass_deception_index": m_idx,
            "regime": regime
        }
        self.history.append(res)
        return res

    def conduct_critique(self, critique_depth: float) -> dict:
        self.stats["critical_critiques"] += 1

        self.critical_consciousness = round(min(1.0, self.critical_consciousness + critique_depth * 0.20), 4)
        self.instrumental_rationality = round(max(0.0, self.instrumental_rationality - critique_depth * 0.10), 4)

        m_idx = self.calc_mass_deception_index()
        regime = self.calc_regime(m_idx)

        self.log(f"CONDUCT_CRITIQUE: depth={critique_depth} -> C={self.critical_consciousness} M={m_idx} ({regime})")
        res = {
            "op": "CONDUCT_CRITICAL_ANALYSIS",
            "critique_depth": critique_depth,
            "critical_consciousness": self.critical_consciousness,
            "instrumental_rationality": self.instrumental_rationality,
            "mass_deception_index": m_idx,
            "regime": regime
        }
        self.history.append(res)
        return res

    def get_state(self) -> dict:
        m_idx = self.calc_mass_deception_index()
        regime = self.calc_regime(m_idx)
        return {
            "op": "GET_STATE",
            "standardization": self.standardization_level,
            "pseudo_individualization": self.pseudo_individualization,
            "instrumental_rationality": self.instrumental_rationality,
            "critical_consciousness": self.critical_consciousness,
            "mass_deception_index": m_idx,
            "regime": regime
        }

    def get_final_summary(self) -> dict:
        m_idx = self.calc_mass_deception_index()
        regime = self.calc_regime(m_idx)
        return {
            "standardization": self.standardization_level,
            "pseudo_individualization": self.pseudo_individualization,
            "instrumental_rationality": self.instrumental_rationality,
            "critical_consciousness": self.critical_consciousness,
            "mass_deception_index": m_idx,
            "regime": regime,
            "stats": self.stats,
            "event_count": len(self.event_log)
        }

def solve():
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return
    data = json.loads(raw_input)
    eng = AdornoCultureIndustryEngine(data["config"])
    results = []
    for op in data.get("operations", []):
        cmd = op["op"]
        if cmd == "PRODUCE_CULTURAL_COMMODITY":
            res = eng.produce_commodity(
                title=op["title"],
                genre=op.get("genre", "GENERAL"),
                formulaic_score=float(op.get("formulaic_score", 0.5)),
                surface_novelty=float(op.get("surface_novelty", 0.5)),
                marketing_budget=float(op.get("marketing_budget", 1.0))
            )
            results.append(res)
        elif cmd == "INJECT_AVANT_GARDE_ART":
            res = eng.inject_avant_garde(
                work_name=op["work_name"],
                dissonance_factor=float(op.get("dissonance_factor", 0.8)),
                intellectual_challenge=float(op.get("intellectual_challenge", 0.8))
            )
            results.append(res)
        elif cmd == "APPLY_RETRO_REPACKAGING":
            res = eng.apply_retro_repackaging(
                target_trend=op["target_trend"],
                nostalgia_intensity=float(op.get("nostalgia_intensity", 0.5))
            )
            results.append(res)
        elif cmd == "CONDUCT_CRITICAL_ANALYSIS":
            res = eng.conduct_critique(
                critique_depth=float(op.get("critique_depth", 0.5))
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
