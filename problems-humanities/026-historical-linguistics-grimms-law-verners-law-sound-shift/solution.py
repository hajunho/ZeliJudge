import sys
import json

if hasattr(sys.stdin, "reconfigure"):
    sys.stdin.reconfigure(encoding="utf-8")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

VOICED_SOUNDS = {
    'a', 'e', 'i', 'o', 'u', 'ā', 'ē', 'ī', 'ō', 'ū',
    'm', 'n', 'l', 'r', 'w', 'y', 'j'
}

VOWELS = {'a', 'e', 'i', 'o', 'u', 'ā', 'ē', 'ī', 'ō', 'ū'}
OBSTRUENTS = {'s', 'f', 'th', 'θ', 'x', 'h'}

def is_vowel(s):
    base = s.rstrip("'").rstrip("*")
    return base in VOWELS

def is_voiced(s):
    base = s.rstrip("'").rstrip("*")
    return base in VOICED_SOUNDS

def simulate_sound_shift(word_entry):
    word_id = word_entry.get("word_id", "")
    pie_tokens = list(word_entry.get("pie_tokens", []))
    accent_idx = word_entry.get("accent_token_index", -1)
    
    n = len(pie_tokens)
    
    grimm_tokens = list(pie_tokens)
    grimm_log = []
    verner_candidates = []
    
    for i in range(n):
        tok = pie_tokens[i]
        prev_tok = grimm_tokens[i - 1] if i > 0 else ""
        
        if prev_tok in OBSTRUENTS and tok in ('p', 't', 'k', 'kw'):
            grimm_log.append({
                "index": i, "from": tok, "to": tok, "phase": "SPIRANT_LAW_BLOCKED",
                "reason": f"Preceded by obstruent {prev_tok}"
            })
            continue
            
        if tok == 'p':
            grimm_tokens[i] = 'f'
            grimm_log.append({"index": i, "from": "p", "to": "f", "phase": "GRIMM_PHASE_1"})
            verner_candidates.append(i)
        elif tok == 't':
            grimm_tokens[i] = 'th'
            grimm_log.append({"index": i, "from": "t", "to": "th", "phase": "GRIMM_PHASE_1"})
            verner_candidates.append(i)
        elif tok == 'k':
            grimm_tokens[i] = 'h'
            grimm_log.append({"index": i, "from": "k", "to": "h", "phase": "GRIMM_PHASE_1"})
            verner_candidates.append(i)
        elif tok == 'kw':
            grimm_tokens[i] = 'hw'
            grimm_log.append({"index": i, "from": "kw", "to": "hw", "phase": "GRIMM_PHASE_1"})
            verner_candidates.append(i)
        elif tok == 'b':
            grimm_tokens[i] = 'p'
            grimm_log.append({"index": i, "from": "b", "to": "p", "phase": "GRIMM_PHASE_2"})
        elif tok == 'd':
            grimm_tokens[i] = 't'
            grimm_log.append({"index": i, "from": "d", "to": "t", "phase": "GRIMM_PHASE_2"})
        elif tok == 'g':
            grimm_tokens[i] = 'k'
            grimm_log.append({"index": i, "from": "g", "to": "k", "phase": "GRIMM_PHASE_2"})
        elif tok == 'gw':
            grimm_tokens[i] = 'kw'
            grimm_log.append({"index": i, "from": "gw", "to": "kw", "phase": "GRIMM_PHASE_2"})
        elif tok == 'bh':
            grimm_tokens[i] = 'b'
            grimm_log.append({"index": i, "from": "bh", "to": "b", "phase": "GRIMM_PHASE_3"})
        elif tok == 'dh':
            grimm_tokens[i] = 'd'
            grimm_log.append({"index": i, "from": "dh", "to": "d", "phase": "GRIMM_PHASE_3"})
        elif tok == 'gh':
            grimm_tokens[i] = 'g'
            grimm_log.append({"index": i, "from": "gh", "to": "g", "phase": "GRIMM_PHASE_3"})
        elif tok == 'gwh':
            grimm_tokens[i] = 'w'
            grimm_log.append({"index": i, "from": "gwh", "to": "w", "phase": "GRIMM_PHASE_3"})
            
    for i in range(n):
        if pie_tokens[i] == 's':
            verner_candidates.append(i)
            
    verner_tokens = list(grimm_tokens)
    verner_log = []
    
    for idx in sorted(set(verner_candidates)):
        target = grimm_tokens[idx]
        prev_idx = idx - 1
        next_idx = idx + 1
        
        prev_voiced = (prev_idx >= 0 and is_voiced(grimm_tokens[prev_idx]))
        next_voiced = (next_idx < n and is_voiced(grimm_tokens[next_idx]))
        in_voiced_env = prev_voiced and next_voiced
        
        prec_vowel_idx = -1
        for k in range(idx - 1, -1, -1):
            if is_vowel(pie_tokens[k]):
                prec_vowel_idx = k
                break
                
        prec_vowel_had_accent = (prec_vowel_idx == accent_idx)
        
        if in_voiced_env and not prec_vowel_had_accent:
            new_sound = target
            if target == 'f': new_sound = 'b'
            elif target == 'th': new_sound = 'd'
            elif target == 'h': new_sound = 'g'
            elif target == 'hw': new_sound = 'gw'
            elif target == 's': new_sound = 'z'
            
            verner_tokens[idx] = new_sound
            verner_log.append({
                "index": idx,
                "from": target,
                "to": new_sound,
                "reason": "Voiced environment & preceding vowel unaccented in PIE",
                "preceding_vowel_index": prec_vowel_idx,
                "pie_accent_index": accent_idx
            })
            
    pgmc_accent_idx = -1
    for i in range(n):
        if is_vowel(verner_tokens[i]):
            pgmc_accent_idx = i
            break
            
    return {
        "word_id": word_id,
        "pie_form": "".join(pie_tokens),
        "pie_accent_token_index": accent_idx,
        "grimm_stage": {
            "tokens": grimm_tokens,
            "form": "".join(grimm_tokens),
            "changes": grimm_log
        },
        "verner_stage": {
            "tokens": verner_tokens,
            "form": "".join(verner_tokens),
            "changes": verner_log
        },
        "proto_germanic": {
            "tokens": verner_tokens,
            "form": "".join(verner_tokens),
            "fixed_initial_accent_token_index": pgmc_accent_idx
        }
    }

def solve(data):
    words = data.get("words", [])
    results = [simulate_sound_shift(w) for w in words]
    total_words = len(results)
    grimm_changes_count = sum(len(r["grimm_stage"]["changes"]) for r in results)
    verner_changes_count = sum(len(r["verner_stage"]["changes"]) for r in results)
    
    return {
        "corpus_summary": {
            "total_words_analyzed": total_words,
            "total_grimm_shifts": grimm_changes_count,
            "total_verner_voicings": verner_changes_count
        },
        "words": results
    }

def main():
    raw = sys.stdin.read()
    if not raw.strip():
        return
    data = json.loads(raw)
    res = solve(data)
    print(json.dumps(res, ensure_ascii=False))

if __name__ == "__main__":
    main()
