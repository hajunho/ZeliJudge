#!/usr/bin/env python3
"""
[ZeliJudge #022] 로컬에선 되는데 왜 배포하니까 빨간 줄이 떠요?: CORS와 브라우저 Preflight
해답 코드: W3C / WHATWG 브라우저 CORS 및 Preflight 판정 엔진 O(Q)
"""
import sys

SAFE_HEADERS = {"accept", "accept-language", "content-language", "-"}
SAFE_METHODS = {"GET", "HEAD", "POST"}

def solve():
    input_data = sys.stdin.read().splitlines()
    if not input_data:
        return

    # 1. CONFIG 파싱
    config_line = input_data[0].strip()
    config_tokens = config_line.split()
    
    cfg = {}
    for tok in config_tokens[1:]:
        k, v = tok.split(":", 1)
        cfg[k] = v

    origin_raw = cfg.get("ORIGIN", "")
    is_origin_wildcard = (origin_raw == "*")
    allowed_origins = set(origin_raw.split(",")) if not is_origin_wildcard else set()

    method_raw = cfg.get("METHODS", "")
    is_method_wildcard = (method_raw == "*")
    allowed_methods = set(method_raw.split(",")) if not is_method_wildcard else set()

    headers_raw = cfg.get("HEADERS", "").lower()
    is_header_wildcard = (headers_raw == "*")
    if headers_raw == "-" or is_header_wildcard:
        allowed_headers = set()
    else:
        allowed_headers = set(headers_raw.split(","))

    # 2. 요청 개수
    q_count = int(input_data[1].strip())
    output = []

    for line in input_data[2:q_count + 2]:
        line = line.strip()
        if not line:
            continue

        parts = line.split()
        # REQ <origin> <method> <headers> <with_credentials>
        req_origin = parts[1]
        req_method = parts[2].upper()
        raw_headers = parts[3].lower()
        with_credentials = (parts[4].upper() == "TRUE")

        req_headers = [h for h in raw_headers.split(",") if h and h != "-"]

        # 1단계: Preflight 여부 판정
        is_preflight = False
        if req_method not in SAFE_METHODS:
            is_preflight = True
        else:
            for h in req_headers:
                if h not in SAFE_HEADERS:
                    is_preflight = True
                    break

        req_type = "PREFLIGHT_REQUIRED" if is_preflight else "SIMPLE_REQUEST"

        # 2단계: 브라우저 보안 심사
        res = None

        # (1) 와일드카드 크레덴셜 금지 위반
        if with_credentials and is_origin_wildcard:
            res = "BLOCKED_CREDENTIALS_WILDCARD"

        # (2) 오리진 미승인 위반
        elif not is_origin_wildcard and (req_origin not in allowed_origins):
            res = "BLOCKED_ORIGIN_NOT_ALLOWED"

        # (3) 메서드 미승인 위반
        elif not is_method_wildcard and (req_method not in allowed_methods):
            res = "BLOCKED_METHOD_NOT_ALLOWED"

        # (4) 헤더 미승인 위반
        elif not is_header_wildcard:
            custom_headers = [h for h in req_headers if h not in SAFE_HEADERS]
            for ch in custom_headers:
                if ch not in allowed_headers:
                    res = "BLOCKED_HEADER_NOT_ALLOWED"
                    break

        # (5) 승인 통과
        if res is None:
            res = "ALLOWED"

        output.append(f"CORS {req_type} {res}")

    if output:
        sys.stdout.write("\n".join(output) + "\n")

if __name__ == "__main__":
    solve()
