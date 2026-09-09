#!/usr/bin/env python3
"""
ZeliJudge CLI Test Runner
내 컴퓨터에서 서버비 0원으로 ZeliJudge 문제를 채점하는 로컬 테스터
"""
import sys
import os
import json
import time
import subprocess
from pathlib import Path

# Windows 콘솔 유니코드 출력 호환성 보장
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

def run_problem_test(problem_dir: Path):
    problem_name = problem_dir.name
    solution_file = problem_dir / "solution.py"
    testcases_file = problem_dir / "testcases.json"

    print(f"\n{'='*60}")
    print(f"🎯 [ZeliJudge] 채점 시작: {problem_name}")
    print(f"{'='*60}")

    if not solution_file.exists():
        print(f"❌ Error: solution.py 가 존재하지 않습니다. ({solution_file})")
        return False

    if not testcases_file.exists():
        print(f"❌ Error: testcases.json 이 존재하지 않습니다. ({testcases_file})")
        return False

    with open(testcases_file, "r", encoding="utf-8") as f:
        testcases = json.load(f)

    total = len(testcases)
    passed = 0

    for idx, tc in enumerate(testcases, 1):
        tc_id = tc.get("id", idx)
        desc = tc.get("description", f"Testcase #{tc_id}")
        inp = tc.get("input", "")
        expected = tc.get("expected_output", tc.get("output", "")).strip()

        start_time = time.perf_counter()
        try:
            res = subprocess.run(
                [sys.executable, str(solution_file)],
                input=inp,
                text=True,
                capture_output=True,
                timeout=5.0  # 5초 타임아웃
            )
            elapsed = (time.perf_counter() - start_time) * 1000 # ms
            
            if res.returncode != 0:
                print(f"  [{tc_id}/{total}] 💥 RUNTIME ERROR ({elapsed:.1f}ms) - {desc}")
                print(f"      Stderr: {res.stderr[:200]}")
                continue

            actual = res.stdout.strip()

            if actual == expected:
                print(f"  [{tc_id}/{total}] ✅ PASS ({elapsed:6.1f}ms) - {desc}")
                passed += 1
            else:
                print(f"  [{tc_id}/{total}] ❌ WRONG ANSWER ({elapsed:6.1f}ms) - {desc}")
                print(f"      Expected: {repr(expected[:60])}")
                print(f"      Actual:   {repr(actual[:60])}")

        except subprocess.TimeoutExpired:
            print(f"  [{tc_id}/{total}] ⏱️ TIME LIMIT EXCEEDED (> 5000ms) - {desc}")

    print(f"{'-'*60}")
    print(f"결과: {passed}/{total} 통과 ({'성공' if passed == total else '실패'})")
    return passed == total

def main():
    root_dir = Path(__file__).resolve().parent.parent
    problems_dir = root_dir / "problems"

    target_problems = []
    if len(sys.argv) > 1:
        query = sys.argv[1]
        for p in sorted(problems_dir.iterdir()):
            if p.is_dir() and query in p.name:
                target_problems.append(p)
    else:
        target_problems = [p for p in sorted(problems_dir.iterdir()) if p.is_dir()]

    if not target_problems:
        print("채점할 문제 디렉토리를 찾을 수 없습니다.")
        sys.exit(1)

    all_ok = True
    for prob in target_problems:
        ok = run_problem_test(prob)
        if not ok:
            all_ok = False

    print("\n" + "="*60)
    if all_ok:
        print("🎉 [ALL PROBLEMS PASSED] 모든 문제가 정상 통과되었습니다!")
        sys.exit(0)
    else:
        print("⚠️ [FAILURES DETECTED] 실패한 테스트케이스가 있습니다.")
        sys.exit(1)

if __name__ == "__main__":
    main()
