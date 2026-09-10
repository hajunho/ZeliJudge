#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import sys
import json
import re

if sys.platform == "win32":
    try:
        sys.stdin.reconfigure(encoding="utf-8")
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

HANGUL_BASE = 0xAC00
HANGUL_END = 0xD7A3
JONGSEONG_LIST = [
    "", "ㄱ", "ㄲ", "ㄳ", "ㄴ", "ㄵ", "ㄶ", "ㄷ", "ㄹ", "ㄺ", "ㄻ", "ㄼ", "ㄽ", "ㄾ", "ㄿ", "ㅀ",
    "ㅁ", "ㅂ", "ㅄ", "ㅅ", "ㅆ", "ㅇ", "ㅈ", "ㅊ", "ㅋ", "ㅌ", "ㅍ", "ㅎ"
]

DIGIT_JONGSEONG = {
    "0": ("영", "ㅇ", True, False),
    "1": ("일", "ㄹ", True, True),
    "2": ("이", "", False, False),
    "3": ("삼", "ㅁ", True, False),
    "4": ("사", "", False, False),
    "5": ("오", "", False, False),
    "6": ("육", "ㄱ", True, False),
    "7": ("칠", "ㄹ", True, True),
    "8": ("팔", "ㄹ", True, True),
    "9": ("구", "", False, False)
}

ALPHA_JONGSEONG = {
    "L": ("엘", "ㄹ", True, True),
    "l": ("엘", "ㄹ", True, True),
    "M": ("엠", "ㅁ", True, False),
    "m": ("엠", "ㅁ", True, False),
    "N": ("엔", "ㄴ", True, False),
    "n": ("엔", "ㄴ", True, False),
    "R": ("알", "ㄹ", True, True),
    "r": ("알", "ㄹ", True, True)
}

def analyze_last_char(word):
    cleaned = str(word).strip()
    for ch in reversed(cleaned):
        if ch in ")\"'\u201d\u2019]}>":
            continue
        code = ord(ch)
        if HANGUL_BASE <= code <= HANGUL_END:
            jong_idx = (code - HANGUL_BASE) % 28
            has_jong = (jong_idx > 0)
            jong_char = JONGSEONG_LIST[jong_idx]
            is_rieul = (jong_idx == 8)
            return {
                "char": ch,
                "has_jongseong": has_jong,
                "jongseong_char": jong_char,
                "is_rieul": is_rieul
            }
        if ch in DIGIT_JONGSEONG:
            pron, jong_char, has_jong, is_rieul = DIGIT_JONGSEONG[ch]
            return {
                "char": ch,
                "has_jongseong": has_jong,
                "jongseong_char": jong_char,
                "is_rieul": is_rieul
            }
        if ch.isalpha():
            if ch in ALPHA_JONGSEONG:
                pron, jong_char, has_jong, is_rieul = ALPHA_JONGSEONG[ch]
                return {
                    "char": ch,
                    "has_jongseong": has_jong,
                    "jongseong_char": jong_char,
                    "is_rieul": is_rieul
                }
            else:
                return {
                    "char": ch,
                    "has_jongseong": False,
                    "jongseong_char": "",
                    "is_rieul": False
                }
    return {
        "char": "",
        "has_jongseong": False,
        "jongseong_char": "",
        "is_rieul": False
    }

def resolve_josa(josa_pattern, char_info):
    has_jong = char_info["has_jongseong"]
    is_rieul = char_info["is_rieul"]

    if josa_pattern in ["(을/를)", "을/를", "(을)를"]:
        return "을" if has_jong else "를"
    elif josa_pattern in ["(은/는)", "은/는", "(은)는"]:
        return "은" if has_jong else "는"
    elif josa_pattern in ["(이/가)", "이/가", "(이)가"]:
        return "이" if has_jong else "가"
    elif josa_pattern in ["(와/과)", "와/과", "(과/와)", "과/와"]:
        return "과" if has_jong else "와"
    elif josa_pattern in ["(으/로)", "으/로", "(으)로"]:
        if not has_jong or is_rieul:
            return "로"
        else:
            return "으로"
    elif josa_pattern in ["(이나/나)", "이나/나", "(이)나"]:
        return "이나" if has_jong else "나"
    elif josa_pattern in ["(이라/라)", "이라/라", "(이)라"]:
        return "이라" if has_jong else "라"
    elif josa_pattern in ["(아/야)", "아/야"]:
        return "아" if has_jong else "야"
    return josa_pattern

def render_template(input_data):
    template = input_data.get("template", "")
    variables = input_data.get("variables", {})
    resolved_details = []

    var_pattern = re.compile(r'\{([a-zA-Z0-9_]+)\}(\((?:을/를|은/는|이/가|와/과|과/와|으/로|이나/나|이라/라|아/야)\)|(?:\((?:을|은|이|으)\)(?:를|는|가|로|나|라)))?')

    def replace_var(match):
        var_name = match.group(1)
        josa_tag = match.group(2)
        val = str(variables.get(var_name, ""))
        if not josa_tag:
            return val

        char_info = analyze_last_char(val)
        selected = resolve_josa(josa_tag, char_info)
        resolved_details.append({
            "target": f"{{{var_name}}}",
            "word": val,
            "last_char": char_info["char"],
            "has_jongseong": char_info["has_jongseong"],
            "jongseong": char_info["jongseong_char"],
            "is_rieul_exception": char_info["is_rieul"],
            "josa_tag": josa_tag,
            "selected_josa": selected
        })
        return val + selected

    rendered = var_pattern.sub(replace_var, template)

    static_pattern = re.compile(r'([가-힣0-9a-zA-Z]+)(\((?:을/를|은/는|이/가|와/과|과/와|으/로|이나/나|이라/라|아/야)\)|(?:\((?:을|은|이|으)\)(?:를|는|가|로|나|라)))')

    def replace_static(match):
        word = match.group(1)
        josa_tag = match.group(2)
        char_info = analyze_last_char(word)
        selected = resolve_josa(josa_tag, char_info)
        resolved_details.append({
            "target": word,
            "word": word,
            "last_char": char_info["char"],
            "has_jongseong": char_info["has_jongseong"],
            "jongseong": char_info["jongseong_char"],
            "is_rieul_exception": char_info["is_rieul"],
            "josa_tag": josa_tag,
            "selected_josa": selected
        })
        return word + selected

    rendered = static_pattern.sub(replace_static, rendered)

    return {
        "rendered_text": rendered,
        "resolved_count": len(resolved_details),
        "details": resolved_details
    }

def solve():
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return
    input_data = json.loads(raw_input)
    res = render_template(input_data)
    print(json.dumps(res, ensure_ascii=False))

if __name__ == "__main__":
    solve()
