import sys
import json
import math

if sys.platform == "win32":
    try:
        sys.stdin.reconfigure(encoding="utf-8")
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

CHROMATIC_LUS = [
    ("황종", "黃鍾"), ("대려", "大呂"), ("태주", "太簇"), ("협종", "夾鍾"),
    ("고선", "姑洗"), ("중려", "仲呂"), ("유빈", "蕤賓"), ("임종", "林鍾"),
    ("이칙", "夷則"), ("남려", "南呂"), ("무역", "無射"), ("응종", "應鍾")
]

GENERATION_SEQUENCE = [
    ("황종", "黃鍾", "ORIGIN"),
    ("임종", "林鍾", "SUN_IL"),
    ("태주", "太簇", "IK_IL"),
    ("남려", "南呂", "SUN_IL"),
    ("고선", "姑洗", "IK_IL"),
    ("응종", "應鍾", "SUN_IL"),
    ("유빈", "蕤賓", "IK_IL"),
    ("대려", "大呂", "IK_IL"),
    ("이칙", "夷則", "SUN_IL"),
    ("협종", "夾鍾", "IK_IL"),
    ("무역", "無射", "SUN_IL"),
    ("중려", "仲呂", "IK_IL")
]

PENTATONIC_ROLES = ["궁", "상", "각", "치", "우"]
PENTATONIC_ROLES_HANJA = ["宮", "商", "角", "徵", "羽"]
PENTATONIC_INTERVALS = [0, 2, 4, 7, 9]

def generate_tuning(base_length, base_freq):
    curr_len = base_length
    lus_by_name = {}
    gen_list = []

    for step_idx, (name_ko, name_hanja, op) in enumerate(GENERATION_SEQUENCE):
        if op == "ORIGIN":
            pass
        elif op == "SUN_IL":
            curr_len = curr_len * 2.0 / 3.0
        elif op == "IK_IL":
            curr_len = curr_len * 4.0 / 3.0

        freq = base_freq * (base_length / curr_len)
        cents = 1200.0 * math.log2(freq / base_freq)

        info = {
            "step": step_idx + 1,
            "name_ko": name_ko,
            "name_hanja": name_hanja,
            "operation": op,
            "pipe_length": round(curr_len, 4),
            "frequency_hz": round(freq, 2),
            "cent": round(cents, 2)
        }
        lus_by_name[name_ko] = info
        gen_list.append(info)

    pythagorean_comma_ratio = (3.0 ** 12) / (2.0 ** 19)
    pythagorean_comma_cent = round(1200.0 * math.log2(pythagorean_comma_ratio), 2)

    # Chromatic order table
    chromatic_list = []
    for idx, (n_ko, n_hanja) in enumerate(CHROMATIC_LUS):
        info = dict(lus_by_name[n_ko])
        info["semitone_index"] = idx
        chromatic_list.append(info)

    return lus_by_name, gen_list, chromatic_list, pythagorean_comma_cent

def get_pentatonic_scale(lus_by_name, tonic_name):
    chromatic_names = [n[0] for n in CHROMATIC_LUS]
    if tonic_name not in chromatic_names:
        tonic_name = "황종"
    t_idx = chromatic_names.index(tonic_name)

    scale = []
    for role_idx, interval in enumerate(PENTATONIC_INTERVALS):
        lu_idx = (t_idx + interval) % 12
        lu_ko, lu_hanja = CHROMATIC_LUS[lu_idx]
        lu_info = lus_by_name[lu_ko]
        scale.append({
            "role_ko": PENTATONIC_ROLES[role_idx],
            "role_hanja": PENTATONIC_ROLES_HANJA[role_idx],
            "name_ko": lu_ko,
            "name_hanja": lu_hanja,
            "pipe_length": lu_info["pipe_length"],
            "frequency_hz": lu_info["frequency_hz"],
            "cent": lu_info["cent"]
        })
    return scale

def solve(data):
    base_length = float(data.get("base_length", 81.0))
    base_freq = float(data.get("base_frequency_hz", 261.625565))
    queries = data.get("queries", [])

    lus_by_name, gen_list, chromatic_list, comma_cent = generate_tuning(base_length, base_freq)

    query_results = []
    for q in queries:
        qid = q["id"]
        tonic = q.get("tonic", "황종")
        scale = get_pentatonic_scale(lus_by_name, tonic)
        query_results.append({
            "id": qid,
            "tonic": tonic,
            "pentatonic_scale": scale
        })

    return {
        "base_tuning": {
            "hwangjong_length": base_length,
            "hwangjong_frequency_hz": round(base_freq, 2),
            "pythagorean_comma_cent": comma_cent
        },
        "generation_sequence": gen_list,
        "chromatic_lus": chromatic_list,
        "query_results": query_results
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
