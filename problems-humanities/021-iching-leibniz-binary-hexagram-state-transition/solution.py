import sys
import json

if sys.platform == "win32":
    try:
        sys.stdin.reconfigure(encoding="utf-8")
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

TRIGRAM_NAMES = {
    0: {"name_ko": "곤", "hanja": "坤", "element": "지(地)", "symbol": "☷"},
    1: {"name_ko": "간", "hanja": "艮", "element": "산(山)", "symbol": "☶"},
    2: {"name_ko": "감", "hanja": "坎", "element": "수(水)", "symbol": "☵"},
    3: {"name_ko": "손", "hanja": "巽", "element": "풍(風)", "symbol": "☴"},
    4: {"name_ko": "진", "hanja": "震", "element": "뢰(雷)", "symbol": "☳"},
    5: {"name_ko": "리", "hanja": "離", "element": "화(火)", "symbol": "☲"},
    6: {"name_ko": "태", "hanja": "兌", "element": "택(澤)", "symbol": "☱"},
    7: {"name_ko": "건", "hanja": "乾", "element": "천(天)", "symbol": "☰"}
}

HEXAGRAM_TABLE = {
    (7, 7): (1, "중천건", "乾爲天"),
    (0, 0): (2, "중지곤", "坤爲地"),
    (2, 4): (3, "수뢰둔", "水雷屯"),
    (1, 2): (4, "산수몽", "山水蒙"),
    (2, 7): (5, "수천수", "水天需"),
    (7, 2): (6, "천수송", "天水訟"),
    (0, 2): (7, "지수사", "地水師"),
    (2, 0): (8, "수지비", "水地比"),
    (3, 7): (9, "풍천소축", "風天小畜"),
    (7, 6): (10, "천택리", "天澤履"),
    (0, 7): (11, "지천태", "地天泰"),
    (7, 0): (12, "천지비", "天地否"),
    (7, 5): (13, "천화동인", "天火同人"),
    (5, 7): (14, "화천대유", "火天大有"),
    (0, 1): (15, "지산겸", "地山謙"),
    (4, 0): (16, "뇌지예", "雷地豫"),
    (6, 4): (17, "택뢰수", "澤雷隨"),
    (1, 3): (18, "산풍고", "山風蠱"),
    (0, 6): (19, "지택임", "地澤臨"),
    (3, 0): (20, "풍지관", "風地觀"),
    (5, 4): (21, "화뢰서합", "火雷噬嗑"),
    (1, 5): (22, "산화비", "山火賁"),
    (1, 0): (23, "산지박", "山地剝"),
    (0, 4): (24, "지뢰복", "地雷復"),
    (7, 4): (25, "천뢰무망", "天雷無妄"),
    (1, 7): (26, "산천대축", "山天大畜"),
    (1, 4): (27, "산뢰이", "山雷頤"),
    (6, 3): (28, "택풍대과", "澤風大過"),
    (2, 2): (29, "중수감", "坎爲水"),
    (5, 5): (30, "중화리", "離爲火"),
    (6, 1): (31, "택산함", "澤山咸"),
    (4, 3): (32, "뇌풍항", "雷風恒"),
    (7, 1): (33, "천산돈", "天山遯"),
    (4, 7): (34, "뇌천대장", "雷天大壯"),
    (5, 0): (35, "화지진", "火地晉"),
    (0, 5): (36, "지화명이", "地火明夷"),
    (3, 5): (37, "풍화가인", "風火家人"),
    (5, 6): (38, "화택규", "火澤睽"),
    (2, 1): (39, "수산건", "水山蹇"),
    (4, 2): (40, "뇌수해", "雷水解"),
    (1, 6): (41, "산택손", "山澤損"),
    (3, 4): (42, "풍뢰익", "風雷益"),
    (6, 7): (43, "택천쾌", "澤天夬"),
    (7, 3): (44, "천풍구", "天風姤"),
    (6, 0): (45, "택지췌", "澤地萃"),
    (0, 3): (46, "지풍승", "地風升"),
    (6, 2): (47, "택수곤", "澤水困"),
    (2, 3): (48, "수풍정", "水風井"),
    (6, 5): (49, "택화혁", "澤火革"),
    (5, 3): (50, "화풍정", "火風鼎"),
    (4, 4): (51, "중뢰진", "震爲雷"),
    (1, 1): (52, "중산간", "艮爲山"),
    (3, 1): (53, "풍산점", "風山漸"),
    (4, 6): (54, "뇌택귀매", "雷澤歸妹"),
    (4, 5): (55, "뇌화풍", "雷火豐"),
    (5, 1): (56, "화산려", "火山旅"),
    (3, 3): (57, "중풍손", "巽爲風"),
    (6, 6): (58, "중택태", "兌爲澤"),
    (3, 2): (59, "풍수환", "風水渙"),
    (2, 6): (60, "수택절", "水澤節"),
    (3, 6): (61, "풍택중부", "風澤中孚"),
    (4, 1): (62, "뇌산소과", "雷山小過"),
    (2, 5): (63, "수화기제", "水火旣濟"),
    (5, 2): (64, "화수미제", "火水未濟")
}

def get_unicode_hexagram(king_wen_num):
    return chr(0x4DC0 + king_wen_num - 1) if king_wen_num > 0 else ""

def make_hex_val(lines_bits):
    # lines_bits: line 1 (idx 0) to line 6 (idx 5)
    # lower trigram: line 1 (idx 0), line 2 (idx 1), line 3 (idx 2)
    # trigram value: (bottom << 2) | (mid << 1) | top
    lo = (lines_bits[0] << 2) | (lines_bits[1] << 1) | lines_bits[2]
    up = (lines_bits[3] << 2) | (lines_bits[4] << 1) | lines_bits[5]
    return (up << 3) | lo

def get_hexagram_info(val):
    lower_val = val & 7
    upper_val = (val >> 3) & 7
    kw_num, name_ko, name_hanja = HEXAGRAM_TABLE.get((upper_val, lower_val), (0, "미상", "未知"))
    unicode_sym = get_unicode_hexagram(kw_num)
    return {
        "fuxi_binary_value": val,
        "binary_string": f"{val:06b}",
        "king_wen_number": kw_num,
        "name_korean": name_ko,
        "name_hanja": name_hanja,
        "unicode_symbol": unicode_sym,
        "upper_trigram": TRIGRAM_NAMES[upper_val],
        "lower_trigram": TRIGRAM_NAMES[lower_val]
    }

def analyze_cast(cast_lines):
    base_bits = []
    resulting_bits = []
    changing_lines = []
    line_details = []
    cast_probability = 1.0

    prob_map = {
        6: 1 / 16,
        7: 5 / 16,
        8: 7 / 16,
        9: 3 / 16
    }

    for idx, num in enumerate(cast_lines, 1):
        p = prob_map.get(num, 0.0)
        cast_probability *= p

        if num == 6:
            base_bits.append(0)
            resulting_bits.append(1)
            changing_lines.append(idx)
            detail = {"line_number": idx, "cast_number": 6, "emblem": "노음(老陰)", "base_bit": 0, "resulting_bit": 1, "is_changing": True}
        elif num == 7:
            base_bits.append(1)
            resulting_bits.append(1)
            detail = {"line_number": idx, "cast_number": 7, "emblem": "소양(少陽)", "base_bit": 1, "resulting_bit": 1, "is_changing": False}
        elif num == 8:
            base_bits.append(0)
            resulting_bits.append(0)
            detail = {"line_number": idx, "cast_number": 8, "emblem": "소음(少陰)", "base_bit": 0, "resulting_bit": 0, "is_changing": False}
        elif num == 9:
            base_bits.append(1)
            resulting_bits.append(0)
            changing_lines.append(idx)
            detail = {"line_number": idx, "cast_number": 9, "emblem": "노양(老陽)", "base_bit": 1, "resulting_bit": 0, "is_changing": True}
        line_details.append(detail)

    base_val = make_hex_val(base_bits)
    res_val = make_hex_val(resulting_bits)

    # Nuclear Hexagram (호괘, lines 2,3,4 as lower, lines 3,4,5 as upper)
    # lines_bits indices: line 1 = idx 0, line 2 = idx 1, line 3 = idx 2, line 4 = idx 3, line 5 = idx 4, line 6 = idx 5
    nuc_lower = (base_bits[1] << 2) | (base_bits[2] << 1) | base_bits[3]
    nuc_upper = (base_bits[2] << 2) | (base_bits[3] << 1) | base_bits[4]
    nuclear_val = (nuc_upper << 3) | nuc_lower

    # Inverse Hexagram (착괘, bitwise NOT of 6 bits)
    inverse_val = (~base_val) & 0x3F

    # Reverse Hexagram (종괘, upside down)
    reverse_bits = list(reversed(base_bits))
    rev_lower = (reverse_bits[0] << 2) | (reverse_bits[1] << 1) | reverse_bits[2]
    rev_upper = (reverse_bits[3] << 2) | (reverse_bits[4] << 1) | reverse_bits[5]
    reverse_val = (rev_upper << 3) | rev_lower

    return {
        "base_hexagram": get_hexagram_info(base_val),
        "resulting_hexagram": get_hexagram_info(res_val),
        "nuclear_hexagram": get_hexagram_info(nuclear_val),
        "inverse_hexagram": get_hexagram_info(inverse_val),
        "reverse_hexagram": get_hexagram_info(reverse_val),
        "changing_lines": changing_lines,
        "line_details": line_details,
        "cast_probability": round(cast_probability, 8)
    }

def solve(data):
    divinations = data.get("divinations", [])
    results = []
    for d in divinations:
        d_id = d["id"]
        cast_lines = d["lines"]
        analysis = analyze_cast(cast_lines)
        analysis["id"] = d_id
        results.append(analysis)

    return {
        "total_divinations_analyzed": len(results),
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
        sys.stderr.write(f"Error: {e}\n")

if __name__ == "__main__":
    main()
