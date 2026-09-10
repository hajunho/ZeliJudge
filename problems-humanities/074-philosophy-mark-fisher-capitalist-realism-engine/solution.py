import sys
import json
import copy

if sys.platform == "win32":
    try:
        sys.stdin.reconfigure(encoding="utf-8")
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

class CulturalItem:
    def __init__(self, item_id: str, title: str, category: str, revolt_energy: float, commercial_exposure: float):
        self.item_id = item_id
        self.title = title
        self.category = category
        self.initial_revolt_energy = float(revolt_energy)
        self.active_revolt_energy = float(revolt_energy)
        self.commercial_exposure = float(commercial_exposure)
        self.is_incorporated = False
        self.commodity_revenue = 0.0

    def to_dict(self):
        return {
            "item_id": self.item_id,
            "title": self.title,
            "category": self.category,
            "initial_revolt_energy": round(self.initial_revolt_energy, 4),
            "active_revolt_energy": round(self.active_revolt_energy, 4),
            "commercial_exposure": round(self.commercial_exposure, 4),
            "is_incorporated": self.is_incorporated,
            "commodity_revenue": round(self.commodity_revenue, 2)
        }

class SubjectGroup:
    def __init__(self, group_id: str, name: str, size: int,
                 system_awareness: float, collective_agency: float, dopamine_reliance: float,
                 audit_burden: float, productive_work: float):
        self.group_id = group_id
        self.name = name
        self.size = size
        self.system_awareness = float(system_awareness)
        self.collective_agency = float(collective_agency)
        self.dopamine_reliance = float(dopamine_reliance)
        self.audit_burden = float(audit_burden)
        self.productive_work = float(productive_work)
        self.privatized_stress = 0.0

    @property
    def reflexive_impotence(self) -> float:
        return self.system_awareness * (1.0 - self.collective_agency) * self.dopamine_reliance

    @property
    def audit_ratio(self) -> float:
        total = self.audit_burden + self.productive_work
        if total <= 0:
            return 0.0
        return self.audit_burden / total

    def to_dict(self):
        return {
            "group_id": self.group_id,
            "name": self.name,
            "reflexive_impotence": round(self.reflexive_impotence, 4),
            "audit_ratio": round(self.audit_ratio, 4),
            "collective_agency": round(self.collective_agency, 4),
            "dopamine_reliance": round(self.dopamine_reliance, 4),
            "privatized_stress": round(self.privatized_stress, 4)
        }

class CapitalistRealismEngine:
    def __init__(self, raw_config: dict):
        config = copy.deepcopy(raw_config)
        self.base_inevitability = float(config.get("base_inevitability", 0.80))
        self.incorporation_rate = float(config.get("incorporation_rate", 0.85))
        self.weights = config.get("weights", {
            "inevitability": 0.30,
            "pre_incorporation": 0.25,
            "market_stalinism": 0.25,
            "reflexive_impotence": 0.20
        })

        self.cultural_items = {}
        for it in config.get("cultural_items", []):
            item = CulturalItem(
                item_id=it["item_id"],
                title=it["title"],
                category=it.get("category", "art"),
                revolt_energy=float(it.get("revolt_energy", 0.5)),
                commercial_exposure=float(it.get("commercial_exposure", 0.5))
            )
            self.cultural_items[item.item_id] = item

        self.groups = {}
        for g in config.get("subject_groups", []):
            grp = SubjectGroup(
                group_id=g["group_id"],
                name=g["name"],
                size=int(g.get("size", 100)),
                system_awareness=float(g.get("system_awareness", 0.7)),
                collective_agency=float(g.get("collective_agency", 0.2)),
                dopamine_reliance=float(g.get("dopamine_reliance", 0.8)),
                audit_burden=float(g.get("audit_burden", 40.0)),
                productive_work=float(g.get("productive_work", 40.0))
            )
            self.groups[grp.group_id] = grp

        self.current_step = 0
        self.total_incorporated_items = 0
        self.total_commodity_revenue = 0.0
        self.cr_index = 0.0
        self.horizon_status = "CLOSED"
        self.metrics_breakdown = {}
        self.query_logs = []
        self._calculate_cr()

    def _calculate_cr(self):
        # 1. Inevitability
        avg_agency = sum(g.collective_agency for g in self.groups.values()) / max(1, len(self.groups))
        inevitability = min(1.0, max(0.0, self.base_inevitability * (1.0 - 0.5 * avg_agency)))

        # 2. Pre-incorporation
        total_initial_energy = sum(it.initial_revolt_energy for it in self.cultural_items.values())
        if total_initial_energy > 0:
            incorporated_initial = sum(it.initial_revolt_energy for it in self.cultural_items.values() if it.is_incorporated)
            pre_inc = incorporated_initial / total_initial_energy
        else:
            pre_inc = 0.5

        # 3. Market Stalinism
        market_stalinism = sum(g.audit_ratio for g in self.groups.values()) / max(1, len(self.groups))

        # 4. Reflexive Impotence
        avg_ri = sum(g.reflexive_impotence for g in self.groups.values()) / max(1, len(self.groups))

        self.metrics_breakdown = {
            "inevitability": round(inevitability, 4),
            "pre_incorporation": round(pre_inc, 4),
            "market_stalinism": round(market_stalinism, 4),
            "reflexive_impotence": round(avg_ri, 4)
        }

        self.cr_index = (
            self.weights["inevitability"] * inevitability +
            self.weights["pre_incorporation"] * pre_inc +
            self.weights["market_stalinism"] * market_stalinism +
            self.weights["reflexive_impotence"] * avg_ri
        )
        self.cr_index = round(min(1.0, max(0.0, self.cr_index)), 4)

        if self.cr_index >= 0.70:
            self.horizon_status = "CLOSED_TOTALIZING_HEGEMONY"
        elif self.cr_index >= 0.40:
            self.horizon_status = "CRACKED_CONTRADICTIONS"
        else:
            self.horizon_status = "OPENED_POST_CAPITALIST_RUPTURE"

    def pre_incorporate(self, item_id: str, market_budget: float):
        if item_id not in self.cultural_items:
            return
        item = self.cultural_items[item_id]
        if item.is_incorporated:
            return

        inc_factor = min(1.0, self.incorporation_rate * (1.0 + item.commercial_exposure * 0.2))
        revenue = market_budget * item.active_revolt_energy * 2.5
        item.active_revolt_energy = max(0.0, item.active_revolt_energy * (1.0 - inc_factor))
        item.is_incorporated = True
        item.commodity_revenue = revenue

        self.total_incorporated_items += 1
        self.total_commodity_revenue += revenue
        self._calculate_cr()

    def impose_audit(self, group_id: str, extra_kpi_hours: float):
        if group_id not in self.groups:
            return
        g = self.groups[group_id]
        g.audit_burden += extra_kpi_hours
        g.productive_work = max(5.0, g.productive_work - extra_kpi_hours * 0.3)
        self._calculate_cr()

    def privatize_stress(self, group_id: str, medicalization_level: float):
        if group_id not in self.groups:
            return
        g = self.groups[group_id]
        g.privatized_stress = min(1.0, g.privatized_stress + medicalization_level)
        g.collective_agency = max(0.0, g.collective_agency - medicalization_level * 0.4)
        g.dopamine_reliance = min(1.0, g.dopamine_reliance + medicalization_level * 0.2)
        self._calculate_cr()

    def repoliticize_mental_health(self, group_id: str, solidarity_effort: float):
        if group_id not in self.groups:
            return
        g = self.groups[group_id]
        g.privatized_stress = max(0.0, g.privatized_stress - solidarity_effort)
        g.collective_agency = min(1.0, g.collective_agency + solidarity_effort * 0.6)
        g.dopamine_reliance = max(0.0, g.dopamine_reliance - solidarity_effort * 0.4)
        g.audit_burden = max(0.0, g.audit_burden - solidarity_effort * 15.0)
        self.base_inevitability = max(0.0, self.base_inevitability - solidarity_effort * 0.2)
        self._calculate_cr()

    def step(self):
        self.current_step += 1
        self._calculate_cr()

    def run_commands(self, commands: list):
        for cmd in commands:
            ctype = cmd["type"]
            if ctype == "PRE_INCORPORATE":
                self.pre_incorporate(cmd["item_id"], float(cmd.get("market_budget", 1000.0)))
            elif ctype == "IMPOSE_AUDIT":
                self.impose_audit(cmd["group_id"], float(cmd.get("extra_kpi_hours", 10.0)))
            elif ctype == "PRIVATIZE_STRESS":
                self.privatize_stress(cmd["group_id"], float(cmd.get("medicalization_level", 0.2)))
            elif ctype == "REPOLITICIZE":
                self.repoliticize_mental_health(cmd["group_id"], float(cmd.get("solidarity_effort", 0.3)))
            elif ctype == "STEP":
                self.step()
            elif ctype == "QUERY_STATUS":
                self.query_logs.append({
                    "step": self.current_step,
                    "cr_index": self.cr_index,
                    "horizon_status": self.horizon_status,
                    "metrics": copy.deepcopy(self.metrics_breakdown)
                })

    def get_final_result(self) -> dict:
        return {
            "total_steps": self.current_step,
            "capitalist_realism_index": self.cr_index,
            "horizon_status": self.horizon_status,
            "metrics_breakdown": self.metrics_breakdown,
            "total_incorporated_items": self.total_incorporated_items,
            "total_commodity_revenue": round(self.total_commodity_revenue, 2),
            "subject_groups": {gid: g.to_dict() for gid, g in sorted(self.groups.items())},
            "cultural_items": {iid: it.to_dict() for iid, it in sorted(self.cultural_items.items())},
            "query_logs": self.query_logs
        }

def main():
    raw = sys.stdin.read().strip()
    if not raw:
        return
    data = json.loads(raw)
    engine = CapitalistRealismEngine(data["config"])
    engine.run_commands(data.get("commands", []))
    result = engine.get_final_result()
    print(json.dumps(result, ensure_ascii=False))

if __name__ == "__main__":
    main()
