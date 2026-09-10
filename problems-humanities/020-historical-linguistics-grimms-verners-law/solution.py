import sys
import json

if sys.platform == "win32":
    try:
        sys.stdin.reconfigure(encoding="utf-8")
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

VOWELS = set(["a", "e", "i", "o", "u", "ā", "ē", "ī", "ō", "ū", "ǝ", "y", "m̥", "n̥", "l̥", "r̥"])
SONORANTS = set(["r", "l", "m", "n", "w", "j"])
VOICED_ENV = VOWELS.union(SONORANTS)

GRIMM_ACT1 = {
    "p": "f",
    "t": "th",
    "k": "h",
    "kw": "hw"
}

GRIMM_ACT2 = {
    "b": "p",
    "d": "t",
    "g": "k",
    "gw": "kw"
}

GRIMM_ACT3 = {
    "bh": "b",
    "dh": "d",
    "gh": "g",
    "gwh": "gw"
}

VERNER_VOICING = {
    "f": "b",
    "th": "d",
    "h": "g",
    "hw": "gw",
    "s": "z"
}

def solve(data):
    config = data.get("config", {})
    enable_verner = config.get("enable_verners_law", True)
    apply_rhotacism = config.get("apply_rhotacism", True)
    
    words = data.get("words", [])
    results = []

    for item in words:
        w_id = item["id"]
        tokens = item["tokens"]
        accent_idx = item["accent_token_index"]

        n = len(tokens)
        shifted = list(tokens)
        transformations = []

        # Step 1: Grimm's Law
        i = 0
        while i < n:
            tok = tokens[i]
            is_after_s = (i > 0 and tokens[i - 1] == "s")
            is_after_spirant = (i > 0 and tokens[i - 1] in ["p", "k"] and tok == "t")

            if tok in GRIMM_ACT1:
                if is_after_s:
                    transformations.append({
                        "token_index": i,
                        "original": tok,
                        "stage": "GRIMM_EXCEPTION_PROTECTED_BY_S",
                        "result": tok
                    })
                elif is_after_spirant:
                    transformations.append({
                        "token_index": i,
                        "original": tok,
                        "stage": "GRIMM_SPIRANT_LAW_PROTECTED_T",
                        "result": tok
                    })
                else:
                    new_tok = GRIMM_ACT1[tok]
                    shifted[i] = new_tok
                    transformations.append({
                        "token_index": i,
                        "original": tok,
                        "stage": "GRIMM_ACT_1_VOICELESS_TO_FRICATIVE",
                        "result": new_tok
                    })
            elif tok in GRIMM_ACT2:
                new_tok = GRIMM_ACT2[tok]
                shifted[i] = new_tok
                transformations.append({
                    "token_index": i,
                    "original": tok,
                    "stage": "GRIMM_ACT_2_VOICED_TO_VOICELESS",
                    "result": new_tok
                })
            elif tok in GRIMM_ACT3:
                new_tok = GRIMM_ACT3[tok]
                shifted[i] = new_tok
                transformations.append({
                    "token_index": i,
                    "original": tok,
                    "stage": "GRIMM_ACT_3_ASPIRATED_TO_VOICED",
                    "result": new_tok
                })
            i += 1

        # Step 2: Verner's Law
        if enable_verner:
            for j in range(len(shifted)):
                curr_tok = shifted[j]
                if curr_tok in VERNER_VOICING:
                    if j > 0 and j < len(shifted) - 1:
                        prev_tok = tokens[j - 1]
                        next_tok = tokens[j + 1]
                        
                        in_voiced_env = (prev_tok in VOICED_ENV and next_tok in VOICED_ENV)
                        if in_voiced_env:
                            prec_vowel_idx = None
                            for p in range(j - 1, -1, -1):
                                if tokens[p] in VOWELS:
                                    prec_vowel_idx = p
                                    break
                            
                            if prec_vowel_idx is not None and prec_vowel_idx != accent_idx:
                                voiced_tok = VERNER_VOICING[curr_tok]
                                if voiced_tok == "z" and apply_rhotacism:
                                    voiced_tok = "r"
                                    rule_name = "VERNER_LAW_VOICING_AND_RHOTACISM"
                                else:
                                    rule_name = "VERNER_LAW_VOICING"
                                
                                shifted[j] = voiced_tok
                                transformations.append({
                                    "token_index": j,
                                    "original": curr_tok,
                                    "stage": rule_name,
                                    "result": voiced_tok,
                                    "preceding_vowel_index": prec_vowel_idx,
                                    "accent_index": accent_idx
                                })

        results.append({
            "id": w_id,
            "pie_tokens": tokens,
            "pgmc_tokens": shifted,
            "reconstructed_word": "".join(shifted),
            "transformations": transformations
        })

    return {
        "total_words_analyzed": len(results),
        "results": results
    }

def main():
    try:
        raw_data = sys.stdin.read().strip()
        if not raw_data:
            return
        data = json.loads(raw_data)
        res = solve(data)
        print(json.dumps(res, ensure_ascii=False))
    except Exception as e:
        sys.stderr.write(f"Error: {e}\n")
        sys.exit(1)

if __name__ == "__main__":
    main()
