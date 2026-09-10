import sys
import json

if sys.platform == "win32":
    try:
        sys.stdin.reconfigure(encoding="utf-8")
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

def time_to_mins(t_str):
    h, m = map(int, t_str.split(":"))
    return h * 60 + m

def is_night_minute(minute_of_day):
    # 22:00 is 1320 mins, 06:00 is 360 mins
    m = minute_of_day % 1440
    return m < 360 or m >= 1320

def process_labor_records(input_data):
    employee_id = input_data.get("employee_id", "EMP-UNKNOWN")
    employee_name = input_data.get("employee_name", "홍길동")
    hourly_rate = float(input_data.get("hourly_rate", 10000))
    records = input_data.get("records", [])

    total_actual_mins = 0
    total_night_mins = 0
    total_overtime_mins = 0
    total_holiday_regular_mins = 0
    total_holiday_overtime_mins = 0

    accumulated_weekday_regular_mins = 0
    has_rest_period_violation = False
    rest_violation_reasons = []

    daily_reports = []

    for rec in records:
        date_str = rec.get("date")
        day_of_week = rec.get("day_of_week")
        is_holiday = rec.get("is_holiday", False)
        start_m = time_to_mins(rec.get("start_time"))
        end_m = time_to_mins(rec.get("end_time"))

        if end_m <= start_m:
            # Past midnight into next morning
            end_m += 1440

        # Build break intervals
        break_intervals = []
        for b in rec.get("breaks", []):
            b_s = time_to_mins(b.get("start"))
            b_e = time_to_mins(b.get("end"))
            if b_e <= b_s:
                b_e += 1440
            if b_s < start_m and (b_s + 1440) < end_m:
                b_s += 1440
                b_e += 1440
            break_intervals.append((b_s, b_e))

        # Check minute by minute
        day_work_mins = []
        for m in range(start_m, end_m):
            in_break = False
            for bs, be in break_intervals:
                if bs <= m < be:
                    in_break = True
                    break
            if not in_break:
                day_work_mins.append(m)

        actual_mins = len(day_work_mins)
        total_break_mins = (end_m - start_m) - actual_mins

        # Labor Standards Act Article 54: 4h -> 30m, 8h -> 60m
        if actual_mins >= 480 and total_break_mins < 60:
            has_rest_period_violation = True
            rest_violation_reasons.append(f"{date_str}: 8시간 이상 근무({round(actual_mins/60, 1)}시간)이나 휴게시간({total_break_mins}분)이 1시간 미만임")
        elif actual_mins >= 240 and total_break_mins < 30:
            has_rest_period_violation = True
            rest_violation_reasons.append(f"{date_str}: 4시간 이상 근무({round(actual_mins/60, 1)}시간)이나 휴게시간({total_break_mins}분)이 30분 미만임")

        # Categorize night minutes
        day_night_mins = 0
        for m in day_work_mins:
            if is_night_minute(m):
                day_night_mins += 1

        total_actual_mins += actual_mins
        total_night_mins += day_night_mins

        day_overtime_mins = 0
        day_holiday_reg_mins = 0
        day_holiday_ot_mins = 0

        if is_holiday:
            if actual_mins <= 480:
                day_holiday_reg_mins = actual_mins
            else:
                day_holiday_reg_mins = 480
                day_holiday_ot_mins = actual_mins - 480
            total_holiday_regular_mins += day_holiday_reg_mins
            total_holiday_overtime_mins += day_holiday_ot_mins
        else:
            daily_reg = min(actual_mins, 480)
            daily_ot = max(0, actual_mins - 480)

            prev_acc = accumulated_weekday_regular_mins
            new_acc = prev_acc + daily_reg
            if new_acc <= 2400: # 40 hours
                weekly_ot = 0
            else:
                if prev_acc < 2400:
                    weekly_ot = new_acc - 2400
                else:
                    weekly_ot = daily_reg
            accumulated_weekday_regular_mins = new_acc

            day_overtime_mins = daily_ot + weekly_ot
            total_overtime_mins += day_overtime_mins

        daily_reports.append({
            "date": date_str,
            "day_of_week": day_of_week,
            "is_holiday": is_holiday,
            "actual_work_hours": round(actual_mins / 60.0, 2),
            "break_hours": round(total_break_mins / 60.0, 2),
            "night_hours": round(day_night_mins / 60.0, 2),
            "overtime_hours": round(day_overtime_mins / 60.0, 2),
            "holiday_hours": round((day_holiday_reg_mins + day_holiday_ot_mins) / 60.0, 2)
        })

    # Total hours summary
    total_hours = round(total_actual_mins / 60.0, 2)
    night_hours = round(total_night_mins / 60.0, 2)
    overtime_hours = round(total_overtime_mins / 60.0, 2)
    holiday_reg_hours = round(total_holiday_regular_mins / 60.0, 2)
    holiday_ot_hours = round(total_holiday_overtime_mins / 60.0, 2)
    regular_work_hours = round((total_actual_mins - total_overtime_mins - total_holiday_regular_mins - total_holiday_overtime_mins) / 60.0, 2)

    # Wage Calculations
    base_wage = round(total_hours * hourly_rate)
    overtime_premium = round(overtime_hours * hourly_rate * 0.5)
    night_premium = round(night_hours * hourly_rate * 0.5)
    holiday_reg_premium = round(holiday_reg_hours * hourly_rate * 0.5)
    holiday_ot_premium = round(holiday_ot_hours * hourly_rate * 1.0)
    total_premium = overtime_premium + night_premium + holiday_reg_premium + holiday_ot_premium
    gross_pay = base_wage + total_premium

    # Status Determination
    diagnostics = []
    if total_hours > 52.0:
        status = "VIOLATION_52_HOURS_EXCEEDED"
        diagnostics.append(f"주간 총 근로시간({total_hours}시간)이 근로기준법 제53조 상한선인 52시간을 초과했습니다.")
        recommendation = "근로기준법 위반(형사 처벌 대상). 즉시 초과 업무를 중단하고 특별연장근로 인가 여부 검토 또는 추가 인력을 배치하십시오."
    elif has_rest_period_violation:
        status = "VIOLATION_REST_PERIOD_MISSING"
        diagnostics.extend(rest_violation_reasons)
        recommendation = "근로기준법 제54조 휴게시간 미부여 위반. 4시간 이상 30분, 8시간 이상 1시간의 무급 휴게시간을 의무 부여하십시오."
    elif overtime_hours > 0 or (holiday_reg_hours + holiday_ot_hours) > 0:
        status = "COMPLIANT_OVERTIME"
        diagnostics.append(f"주 52시간 상한 이내(총 {total_hours}시간)로 적법하게 연장/휴일 근로가 수행되었습니다.")
        recommendation = "법정 가산수당(연장 50%, 야간 50%, 휴일 50%~100%)을 정상 지급 처리하십시오."
    else:
        status = "COMPLIANT_NORMAL"
        diagnostics.append(f"주 40시간 이내(총 {total_hours}시간) 표준 법정근로시간을 준수했습니다.")
        recommendation = "표준 급여 정상 지급."

    return {
        "status": status,
        "employee_id": employee_id,
        "employee_name": employee_name,
        "hourly_rate": int(hourly_rate),
        "work_summary": {
            "total_work_hours": total_hours,
            "regular_work_hours": regular_work_hours,
            "overtime_hours": overtime_hours,
            "night_hours": night_hours,
            "holiday_hours": round(holiday_reg_hours + holiday_ot_hours, 2)
        },
        "wage_breakdown": {
            "base_wage": base_wage,
            "overtime_premium": overtime_premium,
            "night_premium": night_premium,
            "holiday_premium": holiday_reg_premium + holiday_ot_premium,
            "gross_pay": gross_pay
        },
        "daily_reports": daily_reports,
        "diagnostics": diagnostics,
        "recommendation": recommendation
    }

def main():
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return
    data = json.loads(raw_input)
    result = process_labor_records(data)
    print(json.dumps(result, ensure_ascii=False))

if __name__ == "__main__":
    main()
