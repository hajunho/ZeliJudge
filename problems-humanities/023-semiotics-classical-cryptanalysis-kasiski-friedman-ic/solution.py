import sys
import json
from collections import Counter

if sys.platform == "win32":
    try:
        sys.stdin.reconfigure(encoding="utf-8")
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

ENGLISH_FREQ = {
    'A': 0.08167, 'B': 0.01492, 'C': 0.02782, 'D': 0.04253, 'E': 0.12702,
    'F': 0.02228, 'G': 0.02015, 'H': 0.06094, 'I': 0.06966, 'J': 0.00153,
    'K': 0.00772, 'L': 0.04025, 'M': 0.02406, 'N': 0.06749, 'O': 0.07507,
    'P': 0.01929, 'Q': 0.00095, 'R': 0.05987, 'S': 0.06327, 'T': 0.09056,
    'U': 0.02758, 'V': 0.00978, 'W': 0.02360, 'X': 0.00150, 'Y': 0.01974,
    'Z': 0.00074
}

def clean_text(text):
    return "".join([c.upper() for c in text if c.isalpha()])

def calculate_ic(text):
    n = len(text)
    if n <= 1:
        return 0.0
    counts = Counter(text)
    sum_fi = sum(f * (f - 1) for f in counts.values())
    return sum_fi / (n * (n - 1))

def find_repeated_substrings(text, min_len=3, max_len=5):
    repeats = {}
    n = len(text)
    for length in range(min_len, max_len + 1):
        seen = {}
        for i in range(n - length + 1):
            sub = text[i:i+length]
            if sub not in seen:
                seen[sub] = [i]
            else:
                seen[sub].append(i)
        for sub, positions in seen.items():
            if len(positions) >= 2:
                repeats[sub] = positions
    return repeats

def kasiski_examination(text, max_key_len=12):
    repeats = find_repeated_substrings(text, min_len=3, max_len=5)
    factor_counts = Counter()
    intervals = []

    for sub, positions in repeats.items():
        for i in range(len(positions)):
            for j in range(i + 1, len(positions)):
                dist = positions[j] - positions[i]
                intervals.append(dist)
                for f in range(2, max_key_len + 1):
                    if dist % f == 0:
                        factor_counts[f] += 1

    return factor_counts, repeats

def find_best_key_length(text, max_key_len=12):
    best_len = 1
    best_ic = 0.0
    ic_scores = {}

    for l in range(1, max_key_len + 1):
        slices = [[] for _ in range(l)]
        for idx, char in enumerate(text):
            slices[idx % l].append(char)
        avg_ic = sum(calculate_ic("".join(s)) for s in slices) / l
        ic_scores[l] = round(avg_ic, 4)
        if avg_ic > best_ic:
            best_ic = avg_ic
            best_len = l

    return best_len, ic_scores

def recover_key(text, key_len):
    recovered = []
    for slice_idx in range(key_len):
        slice_text = [text[i] for i in range(slice_idx, len(text), key_len)]
        n = len(slice_text)

        best_shift = 0
        min_chi2 = float("inf")

        for shift in range(26):
            decrypted = [chr((ord(c) - ord('A') - shift) % 26 + ord('A')) for c in slice_text]
            counts = Counter(decrypted)

            chi2 = 0.0
            for char, prob in ENGLISH_FREQ.items():
                expected = n * prob
                observed = counts.get(char, 0)
                chi2 += ((observed - expected) ** 2) / expected

            if chi2 < min_chi2:
                min_chi2 = chi2
                best_shift = shift

        recovered.append(chr(ord('A') + best_shift))

    return "".join(recovered)

def decrypt(ciphertext, key):
    res = []
    k_len = len(key)
    for i, c in enumerate(ciphertext):
        k_char = key[i % k_len]
        shift = ord(k_char) - ord('A')
        plain_c = chr((ord(c) - ord('A') - shift) % 26 + ord('A'))
        res.append(plain_c)
    return "".join(res)

def get_alberti_rotations(key):
    # Relative shift of inner disk for each character in key period
    return [ord(c) - ord('A') for c in key]

def analyze_cipher(ciphertext, max_key_len=12):
    cleaned = clean_text(ciphertext)
    overall_ic = round(calculate_ic(cleaned), 4)

    # Estimate key length using Friedman formula
    # L_hat = (0.0667 - 0.0385) / (IC - 0.0385)
    if overall_ic > 0.0385:
        friedman_est = round((0.0667 - 0.0385) / (overall_ic - 0.0385), 2)
    else:
        friedman_est = float(max_key_len)

    factor_counts, repeats = kasiski_examination(cleaned, max_key_len=max_key_len)
    top_kasiski_factors = [f for f, _ in factor_counts.most_common(3)]

    best_l, ic_map = find_best_key_length(cleaned, max_key_len=max_key_len)
    recovered_key = recover_key(cleaned, best_l)
    decrypted_plain = decrypt(cleaned, recovered_key)
    rotations = get_alberti_rotations(recovered_key)

    is_monoalphabetic = (best_l == 1) or (overall_ic >= 0.060)

    return {
        "text_length": len(cleaned),
        "overall_index_of_coincidence": overall_ic,
        "friedman_estimated_key_length": friedman_est,
        "kasiski_top_factors": top_kasiski_factors,
        "ic_by_key_length": ic_map,
        "detected_key_length": best_l,
        "recovered_key": recovered_key,
        "is_monoalphabetic": is_monoalphabetic,
        "alberti_disk_rotations": rotations,
        "decrypted_plaintext": decrypted_plain
    }

def solve(data):
    messages = data.get("messages", [])
    max_k = data.get("max_key_length", 12)
    results = []

    for msg in messages:
        mid = msg["id"]
        c_text = msg["ciphertext"]
        analysis = analyze_cipher(c_text, max_key_len=max_k)
        analysis["id"] = mid
        results.append(analysis)

    return {
        "total_messages_analyzed": len(results),
        "results": results
    }

def main():
    try:
        raw = sys.stdin.read().strip()
        if not raw:
            return
        data = json.loads(raw)
        res = solve(data)
        print(json.dumps(res, ensure_ascii=False))
    except Exception as e:
        sys.stderr.write(f"Error: {e}\\n")

if __name__ == "__main__":
    main()
