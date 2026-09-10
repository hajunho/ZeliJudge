import sys
import json
import math

class SaussureLinguisticEngine:
    def __init__(self):
        self.lexicon = {}
        self.valid_syntagms = []

    def add_word(self, signifier, signified, pos, epa, language="en"):
        self.lexicon[signifier] = {
            "signifier": signifier,
            "signified": signified,
            "pos": pos,
            "epa": [round(float(x), 2) for x in epa],
            "language": language
        }

    def add_syntagm_rule(self, rule_name, pos_sequence):
        self.valid_syntagms.append({"name": rule_name, "pattern": pos_sequence})

    def semantic_distance(self, w1, w2):
        if w1 not in self.lexicon or w2 not in self.lexicon:
            return None
        v1 = self.lexicon[w1]["epa"]
        v2 = self.lexicon[w2]["epa"]
        dist = math.sqrt(sum((a - b) ** 2 for a, b in zip(v1, v2)))
        return round(dist, 2)

    def analyze_syntagm(self, word_sequence):
        tokens = []
        pos_seq = []
        missing = []
        
        for w in word_sequence:
            if w in self.lexicon:
                info = self.lexicon[w]
                tokens.append(info)
                pos_seq.append(info["pos"])
            else:
                missing.append(w)
                
        if missing:
            return {
                "valid": False,
                "matched_rule": None,
                "pos_sequence": pos_seq,
                "error": f"Unknown words in lexicon: {missing}",
                "composite_epa": [0.0, 0.0, 0.0]
            }
            
        matched_rule = None
        for r in self.valid_syntagms:
            if r["pattern"] == pos_seq:
                matched_rule = r["name"]
                break
                
        avg_epa = [
            round(sum(t["epa"][i] for t in tokens) / len(tokens), 2)
            for i in range(3)
        ]
        
        return {
            "valid": matched_rule is not None,
            "matched_rule": matched_rule,
            "pos_sequence": pos_seq,
            "tokens": [t["signifier"] for t in tokens],
            "composite_epa": avg_epa
        }

    def query_paradigmatic_substitutes(self, target_word, top_k=3):
        if target_word not in self.lexicon:
            return None
            
        target_info = self.lexicon[target_word]
        target_pos = target_info["pos"]
        
        candidates = []
        for w, info in self.lexicon.items():
            if w == target_word:
                continue
            if info["pos"] == target_pos:
                d = self.semantic_distance(target_word, w)
                candidates.append({
                    "word": w,
                    "signified": info["signified"],
                    "semantic_distance": d,
                    "epa": info["epa"]
                })
                
        candidates.sort(key=lambda c: (c["semantic_distance"], c["word"]))
        synonyms = candidates[:top_k]
        furthest = sorted(candidates, key=lambda c: (-c["semantic_distance"], c["word"]))[:top_k]
        
        return {
            "target_word": target_word,
            "pos": target_pos,
            "closest_substitutes": synonyms,
            "furthest_opposites": furthest
        }

    def check_arbitrariness(self, signified_concept):
        matching = []
        for w, info in self.lexicon.items():
            if info["signified"].lower() == signified_concept.lower():
                matching.append({
                    "signifier": info["signifier"],
                    "language": info["language"],
                    "epa": info["epa"]
                })
        return {
            "signified": signified_concept,
            "distinct_signifiers_count": len(matching),
            "signifiers": matching,
            "is_arbitrary": len(matching) > 1
        }

def run_simulation(req):
    engine = SaussureLinguisticEngine()
    
    for w_item in req.get("lexicon", []):
        engine.add_word(
            signifier=w_item["signifier"],
            signified=w_item["signified"],
            pos=w_item["pos"],
            epa=w_item["epa"],
            language=w_item.get("language", "en")
        )
        
    for r_item in req.get("syntagm_rules", []):
        engine.add_syntagm_rule(r_item["name"], r_item["pattern"])
        
    logs = []
    for op_item in req.get("operations", []):
        step = op_item["step"]
        op = op_item["op"]
        
        if op == "CHECK_ARBITRARINESS":
            concept = op_item["signified"]
            res = engine.check_arbitrariness(concept)
            logs.append({"step": step, "op": op, **res})
            
        elif op == "SEMANTIC_DISTANCE":
            w1 = op_item["word1"]
            w2 = op_item["word2"]
            dist = engine.semantic_distance(w1, w2)
            logs.append({"step": step, "op": op, "word1": w1, "word2": w2, "distance": dist})
            
        elif op == "ANALYZE_SYNTAGM":
            words = op_item["words"]
            res = engine.analyze_syntagm(words)
            logs.append({"step": step, "op": op, **res})
            
        elif op == "QUERY_PARADIGM":
            target = op_item["target_word"]
            k = op_item.get("top_k", 3)
            res = engine.query_paradigmatic_substitutes(target, k)
            logs.append({"step": step, "op": op, **res})
            
    return {
        "operations_log": logs,
        "lexicon_size": len(engine.lexicon)
    }

def main():
    if hasattr(sys.stdin, "reconfigure"):
        sys.stdin.reconfigure(encoding="utf-8")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        
    raw_in = sys.stdin.read().strip()
    if not raw_in:
        return
        
    req = json.loads(raw_in)
    res = run_simulation(req)
    print(json.dumps(res, ensure_ascii=False))

if __name__ == "__main__":
    main()
