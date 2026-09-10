import sys
import math
import json

if sys.platform == "win32":
    try:
        sys.stdin.reconfigure(encoding="utf-8")
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

def allocate_seats(input_data):
    election_name = input_data.get("election_name", "General Election")
    total_seats = int(input_data.get("total_seats", 47))
    threshold_pct = float(input_data.get("threshold_percent", 3.0))
    min_dist_seats = int(input_data.get("min_district_seats_threshold", 5))
    parties = input_data.get("parties", [])

    total_votes = sum(p.get("votes", 0) for p in parties)
    if total_votes == 0:
        return {"error": "Total votes must be greater than zero."}

    # Step 1: Check eligibility
    eligible_parties = []
    ineligible_parties = []

    for idx, p in enumerate(parties):
        p_name = p.get("party_name")
        votes = p.get("votes", 0)
        dist_seats = p.get("district_seats", 0)
        v_pct = (votes / total_votes) * 100.0

        p_info = {
            "idx": idx,
            "party_name": p_name,
            "votes": votes,
            "district_seats": dist_seats,
            "vote_percent": round(v_pct, 2),
            "raw_vote_percent": v_pct
        }

        if v_pct >= threshold_pct or dist_seats >= min_dist_seats:
            eligible_parties.append(p_info)
        else:
            ineligible_parties.append(p_info)

    total_elig_votes = sum(p["votes"] for p in eligible_parties)

    # Step 2: Hare-Niemeyer Allocation helper
    def compute_hare(seats):
        if not eligible_parties or total_elig_votes == 0:
            return {}
        quota = total_elig_votes / seats
        alloc = {}
        remainders = []
        allocated_base = 0

        for p in eligible_parties:
            exact = p["votes"] / quota
            base = math.floor(exact)
            rem = exact - base
            alloc[p["party_name"]] = {
                "base": base,
                "rem": rem,
                "votes": p["votes"],
                "idx": p["idx"],
                "final": base
            }
            allocated_base += base
            remainders.append((rem, p["votes"], -p["idx"], p["party_name"]))

        rem_seats = seats - allocated_base
        remainders.sort(reverse=True)
        for i in range(rem_seats):
            p_name = remainders[i][3]
            alloc[p_name]["final"] += 1

        return {k: v["final"] for k, v in alloc.items()}

    # Compute Hare for total_seats
    quota = total_elig_votes / total_seats if total_seats > 0 else 1
    hare_res = []
    hare_alloc_dict = {}
    remainders = []
    allocated_base = 0

    for p in eligible_parties:
        exact = p["votes"] / quota
        base = math.floor(exact)
        rem = exact - base
        remainders.append((rem, p["votes"], -p["idx"], p["party_name"], base))
        allocated_base += base

    rem_seats = total_seats - allocated_base
    remainders.sort(reverse=True)
    extra_seats_set = set(remainders[i][3] for i in range(rem_seats))

    for p in eligible_parties:
        p_name = p["party_name"]
        exact = p["votes"] / quota
        base = math.floor(exact)
        rem = round(exact - base, 4)
        final = base + (1 if p_name in extra_seats_set else 0)
        hare_alloc_dict[p_name] = final
        hare_res.append({
            "party_name": p_name,
            "votes": p["votes"],
            "vote_percent": p["vote_percent"],
            "base_seats": base,
            "remainder": rem,
            "final_seats": final,
            "seat_percent": round((final / total_seats) * 100.0, 2)
        })

    # Step 3: d'Hondt Allocation
    dhondt_quotients = []
    for p in eligible_parties:
        for s in range(1, total_seats + 1):
            q = p["votes"] / s
            dhondt_quotients.append((q, p["votes"], -p["idx"], p["party_name"]))

    dhondt_quotients.sort(reverse=True)
    top_quotients = dhondt_quotients[:total_seats]

    dhondt_seat_counts = {p["party_name"]: 0 for p in eligible_parties}
    for item in top_quotients:
        dhondt_seat_counts[item[3]] += 1

    dhondt_res = []
    for p in eligible_parties:
        p_name = p["party_name"]
        seats = dhondt_seat_counts[p_name]
        dhondt_res.append({
            "party_name": p_name,
            "votes": p["votes"],
            "vote_percent": p["vote_percent"],
            "final_seats": seats,
            "seat_percent": round((seats / total_seats) * 100.0, 2)
        })

    # Step 4: Gallagher Index
    def compute_gallagher(seat_dict):
        diff_sq_sum = 0.0
        for p in parties:
            v_pct = (p.get("votes", 0) / total_votes) * 100.0
            p_seats = seat_dict.get(p.get("party_name"), 0)
            s_pct = (p_seats / total_seats) * 100.0
            diff_sq_sum += (v_pct - s_pct) ** 2
        return round(math.sqrt(0.5 * diff_sq_sum), 2)

    hare_g = compute_gallagher(hare_alloc_dict)
    dhondt_g = compute_gallagher(dhondt_seat_counts)
    more_prop = "HARE_NIEMEYER" if hare_g < dhondt_g else ("DHONDT" if dhondt_g < hare_g else "TIED")

    # Step 5: Alabama Paradox Check in Hare Method
    hare_plus_one = compute_hare(total_seats + 1)
    paradox_parties = []
    for p_name, curr_s in hare_alloc_dict.items():
        next_s = hare_plus_one.get(p_name, 0)
        if next_s < curr_s:
            paradox_parties.append(f"{p_name} ({curr_s}석 -> {next_s}석)")

    if paradox_parties:
        alabama_detected = True
        alabama_details = f"알라바마 패러독스 발생! 총 의석을 {total_seats}석에서 {total_seats+1}석으로 1석 증원 시 {', '.join(paradox_parties)}의 의석이 오히려 감소합니다."
    else:
        alabama_detected = False
        alabama_details = f"총 의석 1석 증원({total_seats+1}석) 시뮬레이션에서 의석 감소 역설(알라바마 패러독스)이 발생하지 않았습니다."

    diagnostics = [
        f"유효 투표수 {total_votes:,}표 중 {len(eligible_parties)}개 정당이 봉쇄조항(득표율 {threshold_pct}% 또는 지역구 {min_dist_seats}석)을 충족하여 의석 배분 자격을 획득했습니다.",
        f"갤러거 불비례성 지수: 헤어-니마이어 {hare_g} vs 동트 {dhondt_g}. {more_prop} 방식이 유권자의 표심을 더 충실하게 반영합니다."
    ]

    return {
        "election_name": election_name,
        "total_seats": total_seats,
        "total_votes": total_votes,
        "eligible_parties_count": len(eligible_parties),
        "ineligible_parties_count": len(ineligible_parties),
        "hare_niemeyer_allocation": hare_res,
        "dhondt_allocation": dhondt_res,
        "disproportionality": {
            "hare_gallagher_index": hare_g,
            "dhondt_gallagher_index": dhondt_g,
            "more_proportional_method": more_prop
        },
        "alabama_paradox": {
            "detected": alabama_detected,
            "details": alabama_details
        },
        "diagnostics": diagnostics
    }

def main():
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return
    data = json.loads(raw_input)
    result = allocate_seats(data)
    print(json.dumps(result, ensure_ascii=False))

if __name__ == "__main__":
    main()
