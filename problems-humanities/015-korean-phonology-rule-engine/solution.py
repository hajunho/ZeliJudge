import sys
import json

if sys.platform == "win32":
    try:
        sys.stdin.reconfigure(encoding="utf-8")
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

CHOSUNG = ['ㄱ', 'ㄲ', 'ㄴ', 'ㄷ', 'ㄸ', 'ㄹ', 'ㅁ', 'ㅂ', 'ㅃ', 'ㅅ', 'ㅆ', 'ㅇ', 'ㅈ', 'ㅉ', 'ㅊ', 'ㅋ', 'ㅌ', 'ㅍ', 'ㅎ']
JUNGSUNG = ['ㅏ', 'ㅐ', 'ㅑ', 'ㅒ', 'ㅓ', 'ㅔ', 'ㅕ', 'ㅖ', 'ㅗ', 'ㅘ', 'ㅙ', 'ㅚ', 'ㅛ', 'ㅜ', 'ㅝ', 'ㅞ', 'ㅟ', 'ㅠ', 'ㅡ', 'ㅢ', 'ㅣ']
JONGSUNG = ['', 'ㄱ', 'ㄲ', 'ㄳ', 'ㄴ', 'ㄵ', 'ㄶ', 'ㄷ', 'ㄹ', 'ㄺ', 'ㄻ', 'ㄼ', 'ㄽ', 'ㄾ', 'ㄿ', 'ㅀ', 'ㅁ', 'ㅂ', 'ㅄ', 'ㅅ', 'ㅆ', 'ㅇ', 'ㅈ', 'ㅊ', 'ㅋ', 'ㅌ', 'ㅍ', 'ㅎ']

CLUSTER_SPLIT = {
    'ㄳ': ('ㄱ', 'ㅅ'),
    'ㄵ': ('ㄴ', 'ㅈ'),
    'ㄶ': ('ㄴ', 'ㅎ'),
    'ㄼ': ('ㄹ', 'ㅂ'),
    'ㄽ': ('ㄹ', 'ㅅ'),
    'ㄾ': ('ㄹ', 'ㅌ'),
    'ㄿ': ('ㄹ', 'ㅍ'),
    'ㅀ': ('ㄹ', 'ㅎ'),
    'ㅄ': ('ㅂ', 'ㅅ'),
    'ㄺ': ('ㄹ', 'ㄱ'),
    'ㄻ': ('ㄹ', 'ㅁ'),
    'ㄲ': ('ㄲ', ''),
    'ㅆ': ('ㅆ', '')
}

def decompose(ch: str):
    code = ord(ch)
    if 0xAC00 <= code <= 0xD7A3:
        off = code - 0xAC00
        return [CHOSUNG[off // (21 * 28)], JUNGSUNG[(off % (21 * 28)) // 28], JONGSUNG[off % 28]]
    return [ch, '', '']

def compose(cho: str, jung: str, jong: str = '') -> str:
    if cho in CHOSUNG and jung in JUNGSUNG and jong in JONGSUNG:
        code = 0xAC00 + (CHOSUNG.index(cho) * 21 * 28) + (JUNGSUNG.index(jung) * 28) + JONGSUNG.index(jong)
        return chr(code)
    return cho

def run_phonology_engine(item: dict) -> dict:
    word = item["word"]
    is_compound = item.get("is_compound", False)
    comp_boundaries = set(item.get("compound_boundaries", []))
    is_predicate = item.get("is_predicate", False)
    has_hi_suffix = item.get("has_hi_suffix", False)
    special_lb_b = item.get("special_lb_b", False)

    syllables = [decompose(c) for c in word]
    trace = []
    applied_rules = []

    def current_word():
        return "".join(compose(s[0], s[1], s[2]) for s in syllables)

    # 1. N_INSERTION (ㄴ 첨가)
    if is_compound and comp_boundaries:
        for b in sorted(comp_boundaries):
            if 0 <= b < len(syllables) - 1:
                c1, c2 = syllables[b], syllables[b+1]
                if c1[2] != '' and c2[0] == 'ㅇ' and c2[1] in ('ㅣ', 'ㅑ', 'ㅕ', 'ㅛ', 'ㅠ'):
                    c2[0] = 'ㄴ'
                    applied_rules.append("N_INSERTION")
                    trace.append({"rule": "N_INSERTION", "form": current_word()})

    # 2. ASPIRATION (자음 축약 / 거센소리되기)
    aspiration_map = {'ㄱ': 'ㅋ', 'ㄷ': 'ㅌ', 'ㅂ': 'ㅍ', 'ㅈ': 'ㅊ'}
    for i in range(len(syllables) - 1):
        c1, c2 = syllables[i], syllables[i+1]
        # Coda has ㅎ or cluster ending in ㅎ
        if c1[2] == 'ㅎ' and c2[0] in aspiration_map:
            c1[2] = ''
            c2[0] = aspiration_map[c2[0]]
            applied_rules.append("ASPIRATION")
            trace.append({"rule": "ASPIRATION", "form": current_word()})
        elif c1[2] == 'ㄶ' and c2[0] in aspiration_map:
            c1[2] = 'ㄴ'
            c2[0] = aspiration_map[c2[0]]
            applied_rules.append("ASPIRATION")
            trace.append({"rule": "ASPIRATION", "form": current_word()})
        elif c1[2] == 'ㅀ' and c2[0] in aspiration_map:
            c1[2] = 'ㄹ'
            c2[0] = aspiration_map[c2[0]]
            applied_rules.append("ASPIRATION")
            trace.append({"rule": "ASPIRATION", "form": current_word()})
        # Onset is ㅎ and coda has plain stop
        elif c2[0] == 'ㅎ':
            if c1[2] in aspiration_map:
                c2[0] = aspiration_map[c1[2]]
                c1[2] = ''
                applied_rules.append("ASPIRATION")
                trace.append({"rule": "ASPIRATION", "form": current_word()})
            elif c1[2] == 'ㄺ':
                c1[2] = 'ㄹ'
                c2[0] = 'ㅋ'
                applied_rules.append("ASPIRATION")
                trace.append({"rule": "ASPIRATION", "form": current_word()})
            elif c1[2] == 'ㄼ':
                c1[2] = 'ㄹ'
                c2[0] = 'ㅍ'
                applied_rules.append("ASPIRATION")
                trace.append({"rule": "ASPIRATION", "form": current_word()})
            elif c1[2] == 'ㄵ':
                c1[2] = 'ㄴ'
                c2[0] = 'ㅊ'
                applied_rules.append("ASPIRATION")
                trace.append({"rule": "ASPIRATION", "form": current_word()})

    # 3. PALATALIZATION (구개음화)
    # Case 3A: Coda ㄷ, ㅌ followed by grammatical /i, j/
    for i in range(len(syllables) - 1):
        c1, c2 = syllables[i], syllables[i+1]
        is_boundary = (i in comp_boundaries) if is_compound else False
        if not is_boundary and c2[0] == 'ㅇ' and c2[1] in ('ㅣ', 'ㅑ', 'ㅕ', 'ㅛ', 'ㅠ'):
            if c1[2] == 'ㄷ':
                c1[2] = ''
                c2[0] = 'ㅈ'
                applied_rules.append("PALATALIZATION")
                trace.append({"rule": "PALATALIZATION", "form": current_word()})
            elif c1[2] == 'ㅌ':
                c1[2] = ''
                c2[0] = 'ㅊ'
                applied_rules.append("PALATALIZATION")
                trace.append({"rule": "PALATALIZATION", "form": current_word()})
            elif c1[2] == 'ㄾ':
                c1[2] = 'ㄹ'
                c2[0] = 'ㅊ'
                applied_rules.append("PALATALIZATION")
                trace.append({"rule": "PALATALIZATION", "form": current_word()})

    # Case 3B: Onset ㅌ + /i, j/ formed by aspiration with suffix -히- (표준 발음법 제17항 붙임)
    if has_hi_suffix:
        for i in range(len(syllables)):
            c = syllables[i]
            if c[0] == 'ㅌ' and c[1] in ('ㅣ', 'ㅑ', 'ㅕ', 'ㅛ', 'ㅠ'):
                c[0] = 'ㅊ'
                applied_rules.append("PALATALIZATION")
                trace.append({"rule": "PALATALIZATION", "form": current_word()})

    # 4. TENSIFICATION (된소리되기 / 경음화)
    OBSTRUENT_CODAS = {
        'ㄱ', 'ㄲ', 'ㅋ', 'ㄳ', 'ㄺ',
        'ㄷ', 'ㅌ', 'ㅅ', 'ㅆ', 'ㅈ', 'ㅊ',
        'ㅂ', 'ㅍ', 'ㄼ', 'ㄿ', 'ㅄ', 'ㄾ'
    }
    TENSE_MAP = {'ㄱ': 'ㄲ', 'ㄷ': 'ㄸ', 'ㅂ': 'ㅃ', 'ㅅ': 'ㅆ', 'ㅈ': 'ㅉ'}
    for i in range(len(syllables) - 1):
        c1, c2 = syllables[i], syllables[i+1]
        is_boundary = (i in comp_boundaries) if is_compound else False
        pred_nasal = is_predicate and (c1[2] in ('ㄴ', 'ㄵ', 'ㅁ', 'ㄻ'))
        post_obstruent = c1[2] in OBSTRUENT_CODAS
        if (post_obstruent or pred_nasal) and c2[0] in TENSE_MAP:
            c2[0] = TENSE_MAP[c2[0]]
            applied_rules.append("TENSIFICATION")
            trace.append({"rule": "TENSIFICATION", "form": current_word()})

    # 5. CLUSTER_SIMPLIFICATION (자음군 단순화)
    cluster_front = {'ㄳ': 'ㄱ', 'ㄵ': 'ㄴ', 'ㄼ': 'ㄹ', 'ㄽ': 'ㄹ', 'ㄾ': 'ㄹ', 'ㅄ': 'ㅂ'}
    cluster_back = {'ㄺ': 'ㄱ', 'ㄻ': 'ㅁ', 'ㄿ': 'ㅂ'}
    for i in range(len(syllables)):
        c = syllables[i]
        is_boundary = (i in comp_boundaries) if is_compound else False
        is_last = (i == len(syllables) - 1)
        next_is_consonant = False if is_last else (syllables[i+1][0] != 'ㅇ')
        applies = is_last or next_is_consonant or is_boundary

        if applies:
            if c[2] == 'ㄼ' and is_predicate and c[0] == 'ㅂ' and c[1] == 'ㅏ':
                c[2] = 'ㅂ'
                applied_rules.append("CLUSTER_SIMPLIFICATION")
                trace.append({"rule": "CLUSTER_SIMPLIFICATION", "form": current_word()})
            elif c[2] == 'ㄼ' and special_lb_b:
                c[2] = 'ㅂ'
                applied_rules.append("CLUSTER_SIMPLIFICATION")
                trace.append({"rule": "CLUSTER_SIMPLIFICATION", "form": current_word()})
            elif c[2] == 'ㄺ' and is_predicate and not is_last and syllables[i+1][0] in ('ㄱ', 'ㄲ'):
                c[2] = 'ㄹ'
                applied_rules.append("CLUSTER_SIMPLIFICATION")
                trace.append({"rule": "CLUSTER_SIMPLIFICATION", "form": current_word()})
            elif c[2] in cluster_front:
                c[2] = cluster_front[c[2]]
                applied_rules.append("CLUSTER_SIMPLIFICATION")
                trace.append({"rule": "CLUSTER_SIMPLIFICATION", "form": current_word()})
            elif c[2] in cluster_back:
                c[2] = cluster_back[c[2]]
                applied_rules.append("CLUSTER_SIMPLIFICATION")
                trace.append({"rule": "CLUSTER_SIMPLIFICATION", "form": current_word()})
            elif c[2] == 'ㄶ':
                c[2] = 'ㄴ'
                applied_rules.append("CLUSTER_SIMPLIFICATION")
                trace.append({"rule": "CLUSTER_SIMPLIFICATION", "form": current_word()})
            elif c[2] == 'ㅀ':
                c[2] = 'ㄹ'
                applied_rules.append("CLUSTER_SIMPLIFICATION")
                trace.append({"rule": "CLUSTER_SIMPLIFICATION", "form": current_word()})

    # 6. CODA_NEUTRALIZATION (음절의 끝소리 규칙)
    neutral_map = {
        'ㅋ': 'ㄱ', 'ㄲ': 'ㄱ',
        'ㅅ': 'ㄷ', 'ㅆ': 'ㄷ', 'ㅈ': 'ㄷ', 'ㅊ': 'ㄷ', 'ㅌ': 'ㄷ', 'ㅎ': 'ㄷ',
        'ㅍ': 'ㅂ'
    }
    for i in range(len(syllables)):
        c = syllables[i]
        is_boundary = (i in comp_boundaries) if is_compound else False
        is_last = (i == len(syllables) - 1)
        next_is_consonant = False if is_last else (syllables[i+1][0] != 'ㅇ')
        applies = is_last or next_is_consonant or is_boundary

        if applies and c[2] in neutral_map:
            c[2] = neutral_map[c[2]]
            applied_rules.append("CODA_NEUTRALIZATION")
            trace.append({"rule": "CODA_NEUTRALIZATION", "form": current_word()})

    # 7. NASALIZATION (비음화)
    # Phase 7A: /ㄹ/-nasalization
    for i in range(len(syllables) - 1):
        c1, c2 = syllables[i], syllables[i+1]
        if c1[2] in ('ㅁ', 'ㅇ', 'ㄱ', 'ㅂ', 'ㄷ') and c2[0] == 'ㄹ':
            c2[0] = 'ㄴ'
            applied_rules.append("NASALIZATION")
            trace.append({"rule": "NASALIZATION", "form": current_word()})

    # Phase 7B: Plain stop nasalization
    nasal_map = {'ㄱ': 'ㅇ', 'ㄷ': 'ㄴ', 'ㅂ': 'ㅁ'}
    for i in range(len(syllables) - 1):
        c1, c2 = syllables[i], syllables[i+1]
        if c1[2] in nasal_map and c2[0] in ('ㄴ', 'ㅁ'):
            c1[2] = nasal_map[c1[2]]
            applied_rules.append("NASALIZATION")
            trace.append({"rule": "NASALIZATION", "form": current_word()})

    # 8. LATERALIZATION (유음화: ㄴ+ㄹ -> ㄹ+ㄹ, ㄹ+ㄴ -> ㄹ+ㄹ)
    for i in range(len(syllables) - 1):
        c1, c2 = syllables[i], syllables[i+1]
        if c1[2] == 'ㄴ' and c2[0] == 'ㄹ':
            c1[2] = 'ㄹ'
            applied_rules.append("LATERALIZATION")
            trace.append({"rule": "LATERALIZATION", "form": current_word()})
        elif c1[2] == 'ㄹ' and c2[0] == 'ㄴ':
            c2[0] = 'ㄹ'
            applied_rules.append("LATERALIZATION")
            trace.append({"rule": "LATERALIZATION", "form": current_word()})

    # 9. RESYLLABIFICATION (연음 법칙)
    for i in range(len(syllables) - 1):
        c1, c2 = syllables[i], syllables[i+1]
        is_boundary = (i in comp_boundaries) if is_compound else False
        if c1[2] != '' and c2[0] == 'ㅇ' and not is_boundary:
            if c1[2] in CLUSTER_SPLIT:
                first, second = CLUSTER_SPLIT[c1[2]]
                c1[2] = first
                c2[0] = 'ㅆ' if second == 'ㅅ' else second
            else:
                c2[0] = c1[2]
                c1[2] = ''
            applied_rules.append("RESYLLABIFICATION")
            trace.append({"rule": "RESYLLABIFICATION", "form": current_word()})

    final_phonetic = current_word()

    # IPA Mapping
    IPA_CHO = {
        'ㄱ': 'k', 'ㄲ': 'k͈', 'ㄴ': 'n', 'ㄷ': 't', 'ㄸ': 't͈',
        'ㄹ': 'ɾ', 'ㅁ': 'm', 'ㅂ': 'p', 'ㅃ': 'p͈', 'ㅅ': 's',
        'ㅆ': 's͈', 'ㅇ': '', 'ㅈ': 'tɕ', 'ㅉ': 'tɕ͈', 'ㅊ': 'tɕʰ',
        'ㅋ': 'kʰ', 'ㅌ': 'tʰ', 'ㅍ': 'pʰ', 'ㅎ': 'h'
    }
    IPA_JUNG = {
        'ㅏ': 'a', 'ㅐ': 'ɛ', 'ㅑ': 'ja', 'ㅒ': 'jɛ', 'ㅓ': 'ʌ',
        'ㅔ': 'e', 'ㅕ': 'jʌ', 'ㅖ': 'je', 'ㅗ': 'o', 'ㅘ': 'wa',
        'ㅙ': 'wɛ', 'ㅚ': 'ø', 'ㅛ': 'jo', 'ㅜ': 'u', 'ㅝ': 'wʌ',
        'ㅞ': 'we', 'ㅟ': 'y', 'ㅠ': 'ju', 'ㅡ': 'ɯ', 'ㅢ': 'ɰi', 'ㅣ': 'i'
    }
    IPA_JONG = {
        '': '', 'ㄱ': 'k̚', 'ㄴ': 'n', 'ㄷ': 't̚', 'ㄹ': 'l',
        'ㅁ': 'm', 'ㅂ': 'p̚', 'ㅇ': 'ŋ'
    }

    ipa_syllables = []
    for idx, s in enumerate(syllables):
        cho = s[0]
        if cho == 'ㄹ' and idx > 0 and syllables[idx-1][2] == 'ㄹ':
            cho_ipa = 'l'
        else:
            cho_ipa = IPA_CHO.get(cho, cho)
        jung_ipa = IPA_JUNG.get(s[1], s[1])
        jong_ipa = IPA_JONG.get(s[2], s[2])
        ipa_syllables.append(cho_ipa + jung_ipa + jong_ipa)
    ipa_str = f"[{'.'.join(ipa_syllables)}]"

    substitutions = [r for r in applied_rules if r in ('CODA_NEUTRALIZATION', 'PALATALIZATION', 'NASALIZATION', 'LATERALIZATION', 'TENSIFICATION')]
    deletions = [r for r in applied_rules if r in ('CLUSTER_SIMPLIFICATION',)]
    additions = [r for r in applied_rules if r in ('N_INSERTION',)]
    contractions = [r for r in applied_rules if r in ('ASPIRATION',)]

    return {
        "word": word,
        "phonetic": final_phonetic,
        "ipa": ipa_str,
        "rules_applied": applied_rules,
        "derivation_steps": trace,
        "classification": {
            "substitutions": substitutions,
            "deletions": deletions,
            "additions": additions,
            "contractions": contractions
        }
    }

def main():
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return
    data = json.loads(raw_input)
    queries = data.get("queries", [])
    results = [run_phonology_engine(q) for q in queries]
    res = {"results": results}
    print(json.dumps(res, ensure_ascii=False))

if __name__ == "__main__":
    main()
