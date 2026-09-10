import sys
import json

if sys.platform == "win32":
    try:
        sys.stdin.reconfigure(encoding="utf-8")
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

STEMS = ["갑", "을", "병", "정", "무", "기", "경", "신", "임", "계"]
STEMS_HANJA = ["甲", "乙", "丙", "丁", "戊", "己", "庚", "辛", "壬", "癸"]

BRANCHES = ["자", "축", "인", "묘", "진", "사", "오", "미", "신", "유", "술", "해"]
BRANCHES_HANJA = ["子", "丑", "寅", "卯", "辰", "巳", "午", "未", "申", "酉", "戌", "亥"]

ZODIAC = ["쥐", "소", "호랑이", "토끼", "용", "뱀", "말", "양", "원숭이", "닭", "개", "돼지"]

ZHONGQI_MONTH_MAP = {
    "우수": 1, "雨水": 1,
    "춘분": 2, "春分": 2,
    "곡우": 3, "穀雨": 3,
    "소만": 4, "小滿": 4,
    "하지": 5, "夏至": 5,
    "대서": 6, "大暑": 6,
    "처서": 7, "處暑": 7,
    "추분": 8, "秋分": 8,
    "상강": 9, "霜降": 9,
    "소설": 10, "小雪": 10,
    "동지": 11, "冬至": 11,
    "대한": 12, "大寒": 12
}

def get_ganzi(idx):
    idx = idx % 60
    stem_idx = idx % 10
    branch_idx = idx % 12
    return {
        "index": idx,
        "name_ko": STEMS[stem_idx] + BRANCHES[branch_idx],
        "name_hanja": STEMS_HANJA[stem_idx] + BRANCHES_HANJA[branch_idx],
        "stem_ko": STEMS[stem_idx],
        "stem_hanja": STEMS_HANJA[stem_idx],
        "branch_ko": BRANCHES[branch_idx],
        "branch_hanja": BRANCHES_HANJA[branch_idx],
        "zodiac": ZODIAC[branch_idx]
    }

def gregorian_to_jdn(year, month, day):
    a = (14 - month) // 12
    y = year + 4800 - a
    m = month + 12 * a - 3
    jdn = day + (153 * m + 2) // 5 + 365 * y + y // 4 - y // 100 + y // 400 - 32045
    return jdn

def jdn_to_gregorian(jdn):
    l = jdn + 68569
    n = (4 * l) // 146097
    l = l - (146097 * n + 3) // 4
    i = (4000 * (l + 1)) // 1461001
    l = l - (1461 * i) // 4 + 31
    j = (80 * l) // 2447
    day = l - (2447 * j) // 80
    l = j // 11
    month = j + 2 - 12 * l
    year = 100 * (n - 49) + i + l
    return year, month, day

def get_day_ganzi(jdn):
    # Anchor: 2000-01-01 (JDN 2451545) is 54 (무오 戊午)
    idx = (jdn + 49) % 60
    return get_ganzi(idx)

def get_year_ganzi(year):
    # Year 4 CE was Gap-Ja (0, 갑자)
    idx = (year - 4) % 60
    return get_ganzi(idx)

def get_month_ganzi(year, lunar_month):
    # Five Tigers (오호돈월법):
    # Year stem (year - 4) % 10
    year_stem = (year - 4) % 10
    start_stem = (year_stem * 2 + 2) % 10
    stem_idx = (start_stem + (lunar_month - 1)) % 10
    branch_idx = (lunar_month + 1) % 12
    for g in range(60):
        if g % 10 == stem_idx and g % 12 == branch_idx:
            return get_ganzi(g)
    return get_ganzi(0)

def parse_date_str(d_str):
    parts = list(map(int, d_str.split("-")))
    return parts[0], parts[1], parts[2]

def solve(data):
    calendar_def = data.get("calendar_definition", {})
    new_moons = calendar_def.get("new_moons", [])
    solar_terms = calendar_def.get("solar_terms", [])

    nm_list = []
    for nm in new_moons:
        y, m, d = parse_date_str(nm["date"])
        nm_list.append({
            "date": nm["date"],
            "jdn": gregorian_to_jdn(y, m, d)
        })
    nm_list.sort(key=lambda x: x["jdn"])

    st_list = []
    for st in solar_terms:
        y, m, d = parse_date_str(st["date"])
        st_list.append({
            "name": st["name"],
            "date": st["date"],
            "jdn": gregorian_to_jdn(y, m, d),
            "is_zhongqi": st.get("is_zhongqi", False)
        })

    lunar_months = []
    prev_month_num = 0
    leap_assigned = False

    for i in range(len(nm_list) - 1):
        m_start = nm_list[i]["jdn"]
        m_end = nm_list[i+1]["jdn"] - 1
        days_in_month = m_end - m_start + 1

        terms_in_month = [t for t in st_list if m_start <= t["jdn"] <= m_end]
        zhongqi_terms = [t for t in terms_in_month if t["is_zhongqi"]]

        is_leap = False
        month_num = 0

        if len(zhongqi_terms) == 0:
            if not leap_assigned:
                is_leap = True
                month_num = prev_month_num
                leap_assigned = True
            else:
                month_num = prev_month_num + 1
        else:
            zq_name = zhongqi_terms[0]["name"]
            month_num = ZHONGQI_MONTH_MAP.get(zq_name, prev_month_num + 1)
            prev_month_num = month_num

        ey, em, ed = jdn_to_gregorian(m_end)
        lunar_months.append({
            "month_index": i + 1,
            "lunar_month": month_num,
            "is_leap": is_leap,
            "days_count": days_in_month,
            "start_date": nm_list[i]["date"],
            "end_date": f"{ey:04d}-{em:02d}-{ed:02d}",
            "start_jdn": m_start,
            "end_jdn": m_end,
            "solar_terms": [t["name"] for t in terms_in_month]
        })

    queries = data.get("queries", [])
    query_results = []

    for q in queries:
        qid = q["id"]
        q_date_str = q.get("date")
        y, m, d = parse_date_str(q_date_str)
        q_jdn = gregorian_to_jdn(y, m, d)

        matched_lm = None
        lunar_day = 1
        for lm in lunar_months:
            if lm["start_jdn"] <= q_jdn <= lm["end_jdn"]:
                matched_lm = lm
                lunar_day = q_jdn - lm["start_jdn"] + 1
                break

        l_month_num = matched_lm["lunar_month"] if matched_lm else m
        is_leap_month = matched_lm["is_leap"] if matched_lm else False

        year_ganzi = get_year_ganzi(y)
        month_ganzi = get_month_ganzi(y, l_month_num)
        day_ganzi = get_day_ganzi(q_jdn)

        query_results.append({
            "id": qid,
            "gregorian_date": q_date_str,
            "julian_day_number": q_jdn,
            "lunar_date": {
                "year": y,
                "month": l_month_num,
                "day": lunar_day,
                "is_leap": is_leap_month,
                "days_in_month": matched_lm["days_count"] if matched_lm else 30
            },
            "year_ganzi": year_ganzi,
            "month_ganzi": month_ganzi,
            "day_ganzi": day_ganzi
        })

    return {
        "calendar_summary": {
            "total_lunar_months": len(lunar_months),
            "leap_month_found": any(lm["is_leap"] for lm in lunar_months),
            "leap_month_number": next((lm["lunar_month"] for lm in lunar_months if lm["is_leap"]), None),
            "months": [
                {
                    "month_number": lm["lunar_month"],
                    "is_leap": lm["is_leap"],
                    "days": lm["days_count"],
                    "solar_terms": lm["solar_terms"]
                }
                for lm in lunar_months
            ]
        },
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
        sys.stderr.write(f"Error: {e}\n")

if __name__ == "__main__":
    main()
