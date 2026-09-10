import sys
import os
import json

class OrientalismEngine:
    def __init__(self, config: dict):
        self.canonical_texts = set(config.get("canonical_texts", [
            "Dante", "Renan", "Lane", "Chateaubriand", "Balfour", "Cromer", "Volney", "Jones"
        ]))
        self.binary_polarities = {
            # Rationality
            "rational": {"pole": "Occident", "axis": "rationality", "weight": 1.0},
            "scientific": {"pole": "Occident", "axis": "rationality", "weight": 1.0},
            "logical": {"pole": "Occident", "axis": "rationality", "weight": 1.0},
            "mystical": {"pole": "Orient", "axis": "rationality", "weight": 1.0},
            "sensual": {"pole": "Orient", "axis": "rationality", "weight": 1.0},
            "irrational": {"pole": "Orient", "axis": "rationality", "weight": 1.0},
            # Temporality
            "progressive": {"pole": "Occident", "axis": "temporality", "weight": 1.0},
            "dynamic": {"pole": "Occident", "axis": "temporality", "weight": 1.0},
            "modern": {"pole": "Occident", "axis": "temporality", "weight": 1.0},
            "static": {"pole": "Orient", "axis": "temporality", "weight": 1.0},
            "ahistorical": {"pole": "Orient", "axis": "temporality", "weight": 1.0},
            "timeless": {"pole": "Orient", "axis": "temporality", "weight": 1.0},
            # Agency
            "agentic": {"pole": "Occident", "axis": "agency", "weight": 1.0},
            "active": {"pole": "Occident", "axis": "agency", "weight": 1.0},
            "autonomous": {"pole": "Occident", "axis": "agency", "weight": 1.0},
            "passive": {"pole": "Orient", "axis": "agency", "weight": 1.0},
            "submissive": {"pole": "Orient", "axis": "agency", "weight": 1.0},
            "fatalistic": {"pole": "Orient", "axis": "agency", "weight": 1.0},
            # Governance / Morality
            "democratic": {"pole": "Occident", "axis": "governance", "weight": 1.0},
            "lawful": {"pole": "Occident", "axis": "governance", "weight": 1.0},
            "civilized": {"pole": "Occident", "axis": "governance", "weight": 1.0},
            "despotic": {"pole": "Orient", "axis": "governance", "weight": 1.0},
            "fanatical": {"pole": "Orient", "axis": "governance", "weight": 1.0},
            "barbaric": {"pole": "Orient", "axis": "governance", "weight": 1.0}
        }
        if "binary_polarities" in config:
            self.binary_polarities.update(config["binary_polarities"])

        self.latent_bias = float(config.get("initial_latent_bias", 0.0))
        self.statements = []
        self.event_log = []
        self.stats = {
            "total_statements": 0,
            "manifest_orientalist_count": 0,
            "counter_hegemonic_count": 0,
            "neutral_count": 0,
            "textual_attitude_sum": 0.0,
            "max_othering_score": 0.0
        }

    def log(self, msg: str):
        self.event_log.append(msg)

    def analyze_statement(self, stmt: dict) -> dict:
        stmt_id = stmt.get("statement_id", len(self.statements) + 1)
        speaker = stmt.get("speaker_origin", "Occident")
        target = stmt.get("subject_target", "Orient")
        attrs = stmt.get("attributes", [])
        refs = stmt.get("references", [])
        empirical_facts = stmt.get("empirical_facts", 0)

        canon_count = sum(1 for r in refs if r in self.canonical_texts)
        total_evidence = empirical_facts + canon_count
        if total_evidence > 0:
            textual_attitude = round(canon_count / total_evidence, 4)
        else:
            textual_attitude = 0.0

        orient_attr_score = 0.0
        occident_attr_score = 0.0
        active_axes = set()

        for a in attrs:
            a_lower = a.lower()
            if a_lower in self.binary_polarities:
                pol = self.binary_polarities[a_lower]
                active_axes.add(pol["axis"])
                if pol["pole"] == "Orient":
                    orient_attr_score += pol["weight"]
                elif pol["pole"] == "Occident":
                    occident_attr_score += pol["weight"]

        discourse_type = "NEUTRAL"
        othering_score = 0.0

        if speaker == "Occident" and target == "Orient":
            axis_diversity = len(active_axes) / 4.0 if active_axes else 0.0
            raw_othering = (orient_attr_score * 0.35) + (textual_attitude * 0.35) + (self.latent_bias * 0.2) + (axis_diversity * 0.1)
            othering_score = round(min(1.0, max(0.0, raw_othering)), 4)

            if othering_score >= 0.35:
                discourse_type = "MANIFEST_ORIENTALISM"
                self.stats["manifest_orientalist_count"] += 1
                bias_gain = round(othering_score * 0.15, 4)
                self.latent_bias = round(min(1.0, self.latent_bias + bias_gain), 4)
                self.log(f"MANIFEST_ORIENTALISM id={stmt_id} othering={othering_score} textual_attitude={textual_attitude} latent_bias={self.latent_bias}")
            else:
                discourse_type = "NEUTRAL"
                self.stats["neutral_count"] += 1

        elif speaker == "Orient" or stmt.get("is_counter_discourse", False):
            discourse_type = "COUNTER_HEGEMONIC"
            self.stats["counter_hegemonic_count"] += 1
            bias_reduction = round(0.12 + (empirical_facts * 0.04), 4)
            self.latent_bias = round(max(0.0, self.latent_bias - bias_reduction), 4)
            self.log(f"COUNTER_HEGEMONIC id={stmt_id} reduced_by={bias_reduction} latent_bias={self.latent_bias}")

        else:
            discourse_type = "NEUTRAL"
            self.stats["neutral_count"] += 1

        self.stats["total_statements"] += 1
        self.stats["textual_attitude_sum"] += textual_attitude
        if othering_score > self.stats["max_othering_score"]:
            self.stats["max_othering_score"] = othering_score

        analyzed = {
            "statement_id": stmt_id,
            "speaker_origin": speaker,
            "subject_target": target,
            "discourse_type": discourse_type,
            "textual_attitude": textual_attitude,
            "othering_score": othering_score,
            "latent_bias_after": self.latent_bias
        }
        self.statements.append(analyzed)
        return analyzed

    def evaluate_discourse(self) -> dict:
        total = self.stats["total_statements"]
        avg_textual_attitude = round(self.stats["textual_attitude_sum"] / total, 4) if total > 0 else 0.0

        if self.latent_bias >= 0.70:
            positional_superiority = "HEGEMONIC_DOMINANCE"
        elif self.latent_bias >= 0.40:
            positional_superiority = "PATERNALISTIC_SURVEILLANCE"
        else:
            positional_superiority = "DECONSTRUCTED_EGALITARIAN"

        return {
            "total_statements": total,
            "manifest_orientalist_count": self.stats["manifest_orientalist_count"],
            "counter_hegemonic_count": self.stats["counter_hegemonic_count"],
            "neutral_count": self.stats["neutral_count"],
            "average_textual_attitude": avg_textual_attitude,
            "final_latent_bias": self.latent_bias,
            "max_othering_score": self.stats["max_othering_score"],
            "positional_superiority": positional_superiority
        }

def run_simulation(input_data: dict) -> dict:
    config = input_data.get("config", {})
    operations = input_data.get("operations", [])

    engine = OrientalismEngine(config)
    results = []

    for op_info in operations:
        op = op_info.get("op")
        if op == "ANALYZE_STATEMENT":
            stmt = op_info.get("statement", {})
            res = engine.analyze_statement(stmt)
            results.append(res)
        elif op == "RESET_BIAS":
            new_bias = op_info.get("latent_bias", 0.0)
            engine.latent_bias = round(float(new_bias), 4)
            engine.log(f"RESET_BIAS latent_bias={engine.latent_bias}")

    evaluation = engine.evaluate_discourse()
    return {
        "evaluation": evaluation,
        "statements": results,
        "event_log": engine.event_log
    }

if __name__ == "__main__":
    if sys.platform == "win32":
        try:
            sys.stdin.reconfigure(encoding="utf-8")
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    input_text = sys.stdin.read().strip()
    if not input_text:
        sys.exit(0)

    data = json.loads(input_text)
    result = run_simulation(data)
    print(json.dumps(result, ensure_ascii=False))
