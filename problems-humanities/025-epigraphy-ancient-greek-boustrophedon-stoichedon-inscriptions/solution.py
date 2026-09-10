import sys
import json
from collections import Counter

if hasattr(sys.stdin, "reconfigure"):
    sys.stdin.reconfigure(encoding="utf-8")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

def match_word(pattern, word):
    if len(pattern) != len(word):
        return False
    for p, w in zip(pattern, word):
        if p not in ('?', '_') and p != w:
            return False
    return True

def find_segmentations(stream, lexicon):
    n = len(stream)
    memo = {}
    
    def dfs(idx):
        if idx == n:
            return [[]]
        if idx in memo:
            return memo[idx]
        
        res = []
        for word in lexicon:
            wlen = len(word)
            if idx + wlen <= n:
                seg = stream[idx:idx + wlen]
                if match_word(seg, word):
                    sub = dfs(idx + wlen)
                    for s in sub:
                        res.append([word] + s)
        memo[idx] = res
        return res

    return dfs(0)

def solve(data):
    raw_rows = data.get("grid_rows", [])
    is_boustrophedon = data.get("is_boustrophedon", True)
    lexicon = data.get("lexicon", [])
    target_formula = data.get("target_formula", None)
    
    R = len(raw_rows)
    C = len(raw_rows[0]) if R > 0 else 0
    total_cells = R * C
    
    intact_count = 0
    damaged_count = 0
    letter_counts = Counter()
    
    for r in range(R):
        for c in range(C):
            ch = raw_rows[r][c]
            if ch in ('?', '_'):
                damaged_count += 1
            else:
                intact_count += 1
                letter_counts[ch] += 1
                
    lacuna_rate = round((damaged_count / total_cells) * 100, 2) if total_cells > 0 else 0.0
    sorted_freq = dict(sorted(letter_counts.items(), key=lambda item: (-item[1], item[0])))
    
    reading_stream_chars = []
    cell_coords = []
    
    for r in range(R):
        if is_boustrophedon and (r % 2 == 1):
            for c in range(C - 1, -1, -1):
                reading_stream_chars.append(raw_rows[r][c])
                cell_coords.append((r, c))
        else:
            for c in range(C):
                reading_stream_chars.append(raw_rows[r][c])
                cell_coords.append((r, c))
                
    raw_reading_text = "".join(reading_stream_chars)
    
    restored_stream = list(reading_stream_chars)
    restoration_log = []
    chosen_words = None
    status = "UNRESOLVED"
    candidates_count = 0
    
    if target_formula is not None:
        target_concat = "".join(target_formula)
        if len(target_concat) == total_cells and match_word(raw_reading_text, target_concat):
            chosen_words = target_formula
            status = "SUCCESS_FORMULA"
            candidates_count = 1
    elif lexicon:
        segs = find_segmentations(raw_reading_text, lexicon)
        candidates_count = len(segs)
        if len(segs) == 1:
            chosen_words = segs[0]
            status = "SUCCESS_UNIQUE"
        elif len(segs) > 1:
            chosen_words = segs[0]
            status = "AMBIGUOUS"
            
    if chosen_words:
        curr_pos = 0
        for word in chosen_words:
            wlen = len(word)
            for char_idx in range(wlen):
                stream_idx = curr_pos + char_idx
                if stream_idx < total_cells:
                    orig_char = restored_stream[stream_idx]
                    target_char = word[char_idx]
                    if orig_char in ('?', '_'):
                        restored_stream[stream_idx] = target_char
                        r, c = cell_coords[stream_idx]
                        restoration_log.append({
                            "pos": stream_idx,
                            "row": r,
                            "col": c,
                            "original": orig_char,
                            "restored": target_char,
                            "source_word": word
                        })
            curr_pos += wlen

    restored_reading_text = "".join(restored_stream)
    restorations_count = len(restoration_log)
    remaining_lacunae = sum(1 for ch in restored_stream if ch in ('?', '_'))
    
    restored_grid = [["" for _ in range(C)] for _ in range(R)]
    for stream_idx in range(total_cells):
        r, c = cell_coords[stream_idx]
        restored_grid[r][c] = restored_stream[stream_idx]
        
    restored_grid_rows = ["".join(row) for row in restored_grid]
    
    return {
        "grid_dimensions": {
            "rows": R,
            "cols": C,
            "total_cells": total_cells
        },
        "lacuna_analysis": {
            "intact_characters": intact_count,
            "damaged_characters": damaged_count,
            "lacuna_rate_pct": lacuna_rate,
            "letter_frequencies": sorted_freq
        },
        "reading_stream": {
            "unfolded_raw_text": raw_reading_text
        },
        "restoration": {
            "status": status,
            "restorations_count": restorations_count,
            "remaining_lacunae": remaining_lacunae,
            "candidates_count": candidates_count,
            "restored_reading_text": restored_reading_text,
            "restored_grid_rows": restored_grid_rows,
            "restoration_log": restoration_log
        }
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
