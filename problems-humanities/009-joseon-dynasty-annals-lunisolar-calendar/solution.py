import sys
import json
import datetime

if sys.platform == "win32":
    try:
        sys.stdin.reconfigure(encoding="utf-8")
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

STEMS = ["갑", "을", "병", "정", "무", "기", "경", "신", "임", "계"]
BRANCHES = ["자", "축", "인", "묘", "진", "사", "오", "미", "신", "유", "술", "해"]
GANJI_60 = [STEMS[i % 10] + BRANCHES[i % 12] for i in range(60)]
WEEKDAYS = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]

DEFAULT_KINGS = {
    "태조": {"start_year": 1392, "max_year": 7},
    "정종": {"start_year": 1399, "max_year": 2},
    "태종": {"start_year": 1401, "max_year": 18},
    "세종": {"start_year": 1419, "max_year": 32},
    "문종": {"start_year": 1451, "max_year": 2},
    "단종": {"start_year": 1453, "max_year": 3},
    "세조": {"start_year": 1455, "max_year": 14},
    "예종": {"start_year": 1469, "max_year": 1},
    "성종": {"start_year": 1470, "max_year": 25},
    "연산군": {"start_year": 1495, "max_year": 12},
    "중종": {"start_year": 1506, "max_year": 39},
    "인종": {"start_year": 1545, "max_year": 1},
    "명종": {"start_year": 1546, "max_year": 22},
    "선조": {"start_year": 1568, "max_year": 41},
    "광해군": {"start_year": 1609, "max_year": 15},
    "인조": {"start_year": 1623, "max_year": 27},
    "효종": {"start_year": 1650, "max_year": 10},
    "현종": {"start_year": 1660, "max_year": 15},
    "숙종": {"start_year": 1675, "max_year": 46},
    "경종": {"start_year": 1721, "max_year": 4},
    "영조": {"start_year": 1725, "max_year": 52},
    "정조": {"start_year": 1777, "max_year": 24},
    "순조": {"start_year": 1801, "max_year": 34},
    "헌종": {"start_year": 1835, "max_year": 15},
    "철종": {"start_year": 1850, "max_year": 14},
    "고종": {"start_year": 1864, "max_year": 44},
    "순종": {"start_year": 1907, "max_year": 4}
}

def get_year_ganji(year: int) -> str:
    stem_idx = (year - 4) % 10
    branch_idx = (year - 4) % 12
    return STEMS[stem_idx] + BRANCHES[branch_idx]

def get_day_ganji(dt: datetime.date) -> str:
    # Continuous ordinal where 2024-01-01 (ordinal 738886) + 14 = 0 mod 60 (갑자)
    idx = (dt.toordinal() + 14) % 60
    return GANJI_60[idx]

def get_ganji_diff(recorded: str, calculated: str) -> int:
    rec_idx = GANJI_60.index(recorded)
    calc_idx = GANJI_60.index(calculated)
    diff = (rec_idx - calc_idx) % 60
    if diff > 30:
        diff -= 60
    return diff

def process_joseon_chronology(input_data: dict) -> dict:
    kings = input_data.get("kings", DEFAULT_KINGS)
    calendar_db = input_data.get("calendar_db", {})
    records = input_data.get("records", [])

    results = []
    freq = {}

    def add_anomaly_freq(cat: str):
        freq[cat] = freq.get(cat, 0) + 1

    valid_count = 0
    anomaly_count = 0
    error_count = 0

    for rec in records:
        rec_id = rec.get("record_id")
        king = rec.get("king")
        regnal_year = rec.get("regnal_year")
        lunar_month = rec.get("lunar_month")
        is_leap = rec.get("is_leap", False)
        lunar_day = rec.get("lunar_day")
        rec_year_ganji = rec.get("recorded_year_ganji")
        rec_day_ganji = rec.get("recorded_day_ganji")
        event = rec.get("event")

        res = {
            "record_id": rec_id,
            "king": king,
            "regnal_year": regnal_year,
            "solar_year": None,
            "dangi_year": None,
            "calculated_year_ganji": None,
            "solar_date": None,
            "day_of_week": None,
            "calculated_day_ganji": None,
            "status": None,
            "anomalies": []
        }

        # Validate King
        if king not in kings:
            res["status"] = "ERROR"
            res["anomalies"].append(f"INVALID_KING_NAME: {king}")
            add_anomaly_freq("INVALID_KING_NAME")
            error_count += 1
            results.append(res)
            continue

        king_info = kings[king]
        start_year = king_info["start_year"]
        max_year = king_info["max_year"]

        if not isinstance(regnal_year, int) or regnal_year < 1 or regnal_year > max_year:
            res["status"] = "ERROR"
            res["anomalies"].append(f"INVALID_REGNAL_YEAR: {regnal_year} (max: {max_year})")
            add_anomaly_freq("INVALID_REGNAL_YEAR")
            error_count += 1
            results.append(res)
            continue

        solar_year = start_year + (regnal_year - 1)
        dangi_year = solar_year + 2333
        calc_year_ganji = get_year_ganji(solar_year)

        res["solar_year"] = solar_year
        res["dangi_year"] = dangi_year
        res["calculated_year_ganji"] = calc_year_ganji

        # Check calendar_db
        year_str = str(solar_year)
        if year_str not in calendar_db:
            res["status"] = "ERROR"
            res["anomalies"].append(f"CALENDAR_DATA_MISSING: {solar_year}")
            add_anomaly_freq("CALENDAR_DATA_MISSING")
            error_count += 1
            results.append(res)
            continue

        year_cal = calendar_db[year_str]
        lunar_new_year_str = year_cal.get("lunar_new_year")
        months = year_cal.get("months", [])

        # Find target month
        target_month_info = None
        cum_days = 0
        found = False
        for m in months:
            if m["month"] == lunar_month and m["is_leap"] == is_leap:
                target_month_info = m
                found = True
                break
            cum_days += m["days"]

        if not found:
            res["status"] = "ERROR"
            res["anomalies"].append(f"INVALID_LUNAR_MONTH: month={lunar_month}, is_leap={is_leap}")
            add_anomaly_freq("INVALID_LUNAR_MONTH")
            error_count += 1
            results.append(res)
            continue

        max_days = target_month_info["days"]
        if not isinstance(lunar_day, int) or lunar_day < 1 or lunar_day > max_days:
            res["status"] = "ERROR"
            res["anomalies"].append(f"INVALID_LUNAR_DAY: day={lunar_day}, max_days={max_days}")
            add_anomaly_freq("INVALID_LUNAR_DAY")
            error_count += 1
            results.append(res)
            continue

        # Calculate Solar Date
        total_delta = cum_days + (lunar_day - 1)
        base_date = datetime.date.fromisoformat(lunar_new_year_str)
        solar_dt = base_date + datetime.timedelta(days=total_delta)
        solar_date_str = solar_dt.isoformat()
        day_of_week = WEEKDAYS[solar_dt.weekday()]
        calc_day_ganji = get_day_ganji(solar_dt)

        res["solar_date"] = solar_date_str
        res["day_of_week"] = day_of_week
        res["calculated_day_ganji"] = calc_day_ganji

        # Check Anomalies
        anomalies = []

        # 1. Year Ganji Mismatch
        if rec_year_ganji and rec_year_ganji != calc_year_ganji:
            anomalies.append(f"YEAR_GANJI_MISMATCH: recorded={rec_year_ganji}, calculated={calc_year_ganji}")
            add_anomaly_freq("YEAR_GANJI_MISMATCH")

        # 2. Day Ganji Mismatch
        if rec_day_ganji and rec_day_ganji != calc_day_ganji:
            if rec_day_ganji in GANJI_60:
                diff = get_ganji_diff(rec_day_ganji, calc_day_ganji)
                anomalies.append(f"DAY_GANJI_MISMATCH: recorded={rec_day_ganji}, calculated={calc_day_ganji}, diff={diff:+d}")
            else:
                anomalies.append(f"DAY_GANJI_MISMATCH: recorded={rec_day_ganji}, calculated={calc_day_ganji}, diff=UNKNOWN")
            add_anomaly_freq("DAY_GANJI_MISMATCH")

        # 3. Astronomical Phenomenon
        if event == "SOLAR_ECLIPSE":
            if lunar_day != 1:
                anomalies.append(f"ASTRONOMICAL_ANOMALY: SOLAR_ECLIPSE_NOT_ON_NEW_MOON (recorded_day={lunar_day})")
                add_anomaly_freq("SOLAR_ECLIPSE_NOT_ON_NEW_MOON")
        elif event == "LUNAR_ECLIPSE":
            if lunar_day not in (15, 16):
                anomalies.append(f"ASTRONOMICAL_ANOMALY: LUNAR_ECLIPSE_NOT_ON_FULL_MOON (recorded_day={lunar_day})")
                add_anomaly_freq("LUNAR_ECLIPSE_NOT_ON_FULL_MOON")

        anomalies.sort()
        res["anomalies"] = anomalies

        if anomalies:
            res["status"] = "ANOMALY_DETECTED"
            anomaly_count += 1
        else:
            res["status"] = "VALID"
            valid_count += 1

        results.append(res)

    sorted_freq = dict(sorted(freq.items()))

    return {
        "records": results,
        "summary": {
            "total_records": len(records),
            "valid_records": valid_count,
            "anomaly_records": anomaly_count,
            "error_records": error_count,
            "anomaly_frequency": sorted_freq
        }
    }

def main():
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return
    input_data = json.loads(raw_input)
    result = process_joseon_chronology(input_data)
    print(json.dumps(result, ensure_ascii=False))

if __name__ == "__main__":
    main()
