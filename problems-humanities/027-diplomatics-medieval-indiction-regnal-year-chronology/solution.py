import sys
import json

# Ensure UTF-8 IO
sys.stdin.reconfigure(encoding="utf-8")
sys.stdout.reconfigure(encoding="utf-8")

def is_julian_leap(y):
    return y % 4 == 0

def days_in_julian_month(y, m):
    if m < 1 or m > 12:
        return 0
    if m in (1, 3, 5, 7, 8, 10, 12):
        return 31
    if m in (4, 6, 9, 11):
        return 30
    if m == 2:
        return 29 if is_julian_leap(y) else 28
    return 0

def is_valid_julian_date(y, m, d):
    if y <= 0 or m < 1 or m > 12 or d < 1:
        return False
    return d <= days_in_julian_month(y, m)

def julian_jdn(year, month, day):
    a = (14 - month) // 12
    y = year + 4800 - a
    m = month + 12 * a - 3
    return day + (153 * m + 2) // 5 + 365 * y + y // 4 - 32083

DOW_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

def get_day_of_week(year, month, day):
    jdn = julian_jdn(year, month, day)
    return DOW_NAMES[jdn % 7]

def julian_easter(year):
    # Meeus/Jones Julian Easter algorithm
    a = year % 4
    b = year % 7
    c = year % 19
    d = (19 * c + 15) % 30
    e = (2 * a + 4 * b - d + 34) % 7
    month = (d + e + 114) // 31
    day = ((d + e + 114) % 31) + 1
    return (year, month, day)

def get_golden_number(year):
    return (year % 19) + 1

def calculate_indiction(year, month, day, style="roman"):
    style = (style or "roman").lower()
    if style == "byzantine":  # Sept 1
        eff_year = year + 1 if (month > 9 or (month == 9 and day >= 1)) else year
    elif style == "bedan":    # Sept 24
        eff_year = year + 1 if (month > 9 or (month == 9 and day >= 24)) else year
    elif style == "roman":    # Dec 25
        eff_year = year + 1 if (month == 12 and day >= 25) else year
    elif style == "circumcision": # Jan 1
        eff_year = year
    else:
        eff_year = year
    return ((eff_year + 2) % 15) + 1

def resolve_style_to_julian_year(stated_year, month, day, style="circumcision"):
    style = (style or "circumcision").lower()
    if style == "circumcision":
        return stated_year
    elif style == "nativity":
        if month == 12 and day >= 25:
            return stated_year - 1
        return stated_year
    elif style == "florentine":
        if month < 3 or (month == 3 and day < 25):
            return stated_year + 1
        return stated_year
    elif style == "pisan":
        if month > 3 or (month == 3 and day >= 25):
            return stated_year - 1
        return stated_year
    elif style == "easter":
        ey, em, ed = julian_easter(stated_year + 1)
        if (month < em) or (month == em and day < ed):
            return stated_year + 1
        return stated_year
    return stated_year

def parse_iso_date(date_str):
    parts = [int(p) for p in date_str.split("-")]
    return parts[0], parts[1], parts[2]

def solve():
    raw = sys.stdin.read().strip()
    if not raw:
        return
    req = json.loads(raw)
    mode = req.get("mode")

    if mode == "calculate_chronology":
        y, m, d = req["year"], req["month"], req["day"]
        if not is_valid_julian_date(y, m, d):
            print(json.dumps({"error": f"Invalid Julian date: {y:04d}-{m:02d}-{d:02d}"}, ensure_ascii=False))
            return
        
        ey, em, ed = julian_easter(y)
        easter_str = f"{ey:04d}-{em:02d}-{ed:02d}"
        dow = get_day_of_week(y, m, d)
        gn = get_golden_number(y)
        
        nat_y = y + 1 if (m == 12 and d >= 25) else y
        flor_y = y - 1 if (m < 3 or (m == 3 and d < 25)) else y
        pis_y = y + 1 if (m > 3 or (m == 3 and d >= 25)) else y
        east_y = y - 1 if ((m < em) or (m == em and d < ed)) else y
        
        res = {
            "mode": "calculate_chronology",
            "julian_date": f"{y:04d}-{m:02d}-{d:02d}",
            "day_of_week": dow,
            "golden_number": gn,
            "easter_sunday": easter_str,
            "indictions": {
                "byzantine": calculate_indiction(y, m, d, "byzantine"),
                "bedan": calculate_indiction(y, m, d, "bedan"),
                "roman": calculate_indiction(y, m, d, "roman"),
                "circumcision": calculate_indiction(y, m, d, "circumcision")
            },
            "calendar_years": {
                "circumcision": y,
                "nativity": nat_y,
                "florentine": flor_y,
                "pisan": pis_y,
                "easter": east_y
            }
        }
        print(json.dumps(res, ensure_ascii=False))
        return

    elif mode == "convert_regnal_to_julian":
        monarch = req["monarch"]
        acc_y, acc_m, acc_d = parse_iso_date(req["accession_date"])
        regnal_year = req["regnal_year"]
        m, d = req["month"], req["day"]
        
        if (m, d) >= (acc_m, acc_d):
            julian_year = acc_y + regnal_year - 1
        else:
            julian_year = acc_y + regnal_year
            
        if not is_valid_julian_date(julian_year, m, d):
            print(json.dumps({"error": f"Invalid date: {julian_year:04d}-{m:02d}-{d:02d}"}, ensure_ascii=False))
            return
            
        date_str = f"{julian_year:04d}-{m:02d}-{d:02d}"
        dow = get_day_of_week(julian_year, m, d)
        ind_roman = calculate_indiction(julian_year, m, d, "roman")
        
        res = {
            "mode": "convert_regnal_to_julian",
            "monarch": monarch,
            "regnal_year": regnal_year,
            "julian_date": date_str,
            "day_of_week": dow,
            "indiction_roman": ind_roman
        }
        print(json.dumps(res, ensure_ascii=False))
        return

    elif mode == "verify_charters":
        registry = req.get("monarch_registry", {})
        results = []
        for ch in req.get("charters", []):
            ch_id = ch["charter_id"]
            stated = ch["stated_date"]
            st_year = stated["anno_domini"]
            st_style = stated.get("calendar_style", "circumcision")
            m = stated["month"]
            d = stated["day"]
            
            resolved_year = resolve_style_to_julian_year(st_year, m, d, st_style)
            if not is_valid_julian_date(resolved_year, m, d):
                results.append({
                    "charter_id": ch_id,
                    "resolved_julian_date": f"{resolved_year:04d}-{m:02d}-{d:02d}",
                    "actual_day_of_week": None,
                    "calculated_indiction": None,
                    "calculated_regnal_year": None,
                    "status": "ANACHRONISTIC_FORGERY",
                    "discrepancies": [f"INVALID_CALENDAR_DATE: {resolved_year:04d}-{m:02d}-{d:02d} does not exist in Julian calendar"]
                })
                continue
                
            res_date_str = f"{resolved_year:04d}-{m:02d}-{d:02d}"
            actual_dow = get_day_of_week(resolved_year, m, d)
            ind_style = stated.get("indiction_style", "roman")
            calc_ind = calculate_indiction(resolved_year, m, d, ind_style)
            
            discrepancies = []
            
            if "day_of_week" in stated and stated["day_of_week"]:
                if stated["day_of_week"].strip().lower() != actual_dow.lower():
                    discrepancies.append(f"DAY_OF_WEEK_MISMATCH: stated {stated['day_of_week']}, calculated {actual_dow}")
            
            if "indiction" in stated and stated["indiction"] is not None:
                if stated["indiction"] != calc_ind:
                    discrepancies.append(f"INDICTION_MISMATCH: stated {stated['indiction']}, calculated {calc_ind} ({ind_style} style)")
                    
            calc_regnal = None
            monarch_name = stated.get("monarch")
            if monarch_name:
                if monarch_name not in registry:
                    discrepancies.append(f"UNKNOWN_MONARCH: '{monarch_name}' not found in monarch registry")
                else:
                    m_data = registry[monarch_name]
                    acc_y, acc_m, acc_d = parse_iso_date(m_data["accession_date"])
                    end_y, end_m, end_d = parse_iso_date(m_data["end_date"])
                    
                    if (resolved_year, m, d) < (acc_y, acc_m, acc_d):
                        discrepancies.append(f"PRE_REIGN_DATE: resolved date {res_date_str} is before accession {m_data['accession_date']}")
                    elif (resolved_year, m, d) > (end_y, end_m, end_d):
                        discrepancies.append(f"POST_REIGN_DATE: resolved date {res_date_str} is after reign end {m_data['end_date']}")
                    else:
                        if (m, d) >= (acc_m, acc_d):
                            calc_regnal = resolved_year - acc_y + 1
                        else:
                            calc_regnal = resolved_year - acc_y
                            
                    if "regnal_year" in stated and stated["regnal_year"] is not None:
                        if calc_regnal is not None and stated["regnal_year"] != calc_regnal:
                            discrepancies.append(f"REGNAL_YEAR_MISMATCH: stated {stated['regnal_year']}, calculated {calc_regnal}")
                            
            if len(discrepancies) == 0:
                status = "AUTHENTIC"
            elif len(discrepancies) == 1:
                status = "SUSPICIOUS"
            else:
                status = "ANACHRONISTIC_FORGERY"
                
            results.append({
                "charter_id": ch_id,
                "resolved_julian_date": res_date_str,
                "actual_day_of_week": actual_dow,
                "calculated_indiction": calc_ind,
                "calculated_regnal_year": calc_regnal,
                "status": status,
                "discrepancies": discrepancies
            })
            
        res = {
            "mode": "verify_charters",
            "results": results
        }
        print(json.dumps(res, ensure_ascii=False))
        return

if __name__ == "__main__":
    solve()
