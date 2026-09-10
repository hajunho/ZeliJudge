import sys
import json

if sys.platform == 'win32':
    try:
        sys.stdin.reconfigure(encoding='utf-8')
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

def parse_sentence_cky(sentence_str, grammar_rules, start_symbol='S'):
    words = sentence_str.strip().split()
    n = len(words)
    if n == 0:
        return {
            'sentence': sentence_str,
            'token_count': 0,
            'tokens': [],
            'is_grammatical': False,
            'is_ambiguous': False,
            'parse_count': 0,
            'viterbi_parse': None,
            'all_parses': [],
            'chart_summary': []
        }

    binary_rules = []
    lexical_rules = []
    for r in grammar_rules:
        lhs = r['lhs']
        rhs = r['rhs']
        prob = float(r.get('prob', 1.0))
        if len(rhs) == 2:
            binary_rules.append((lhs, rhs[0], rhs[1], prob))
        elif len(rhs) == 1:
            lexical_rules.append((lhs, rhs[0], prob))

    chart = [[{} for _ in range(n + 1)] for _ in range(n)]

    for i in range(n):
        w = words[i]
        for lhs, terminal, prob in lexical_rules:
            if terminal.lower() == w.lower():
                tree_str = f'({lhs} {w})'
                if lhs not in chart[i][1]:
                    chart[i][1][lhs] = []
                chart[i][1][lhs].append({
                    'prob': prob,
                    'tree': tree_str,
                    'lhs': lhs
                })

    for l in range(2, n + 1):
        for i in range(n - l + 1):
            for k in range(1, l):
                left_cell = chart[i][k]
                right_cell = chart[i + k][l - k]
                if not left_cell or not right_cell:
                    continue
                for lhs, b, c, rule_prob in binary_rules:
                    if b in left_cell and c in right_cell:
                        for left_match in left_cell[b]:
                            for right_match in right_cell[c]:
                                prob = rule_prob * left_match['prob'] * right_match['prob']
                                tree_str = f'({lhs} {left_match["tree"]} {right_match["tree"]})'
                                if lhs not in chart[i][l]:
                                    chart[i][l][lhs] = []
                                chart[i][l][lhs].append({
                                    'prob': prob,
                                    'tree': tree_str,
                                    'lhs': lhs,
                                    'split': i + k
                                })

    s_parses = chart[0][n].get(start_symbol, [])
    unique_parses = {}
    for p in s_parses:
        t = p['tree']
        if t not in unique_parses or p['prob'] > unique_parses[t]['prob']:
            unique_parses[t] = p

    sorted_parses = sorted(unique_parses.values(), key=lambda x: (-x['prob'], x['tree']))

    chart_summary = []
    for l in range(1, n + 1):
        for i in range(n - l + 1):
            non_terminals = sorted(list(chart[i][l].keys()))
            if non_terminals:
                chart_summary.append({
                    'span': [i, i + l],
                    'length': l,
                    'tokens': words[i:i+l],
                    'constituents': non_terminals
                })

    is_grammatical = len(sorted_parses) > 0
    is_ambiguous = len(sorted_parses) > 1

    formatted_parses = []
    for idx, p in enumerate(sorted_parses):
        formatted_parses.append({
            'rank': idx + 1,
            'probability': round(p['prob'], 8),
            'parse_tree': p['tree']
        })

    viterbi_parse = formatted_parses[0] if formatted_parses else None

    return {
        'token_count': n,
        'tokens': words,
        'is_grammatical': is_grammatical,
        'is_ambiguous': is_ambiguous,
        'parse_count': len(sorted_parses),
        'viterbi_parse': viterbi_parse,
        'all_parses': formatted_parses,
        'chart_summary': chart_summary
    }

def main():
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return
    data = json.loads(raw_input)
    default_grammar = data.get('grammar', [])
    queries = data.get('queries', [])
    results = []
    for q in queries:
        qid = q.get('query_id', '')
        sentence = q.get('sentence', '')
        start_symbol = q.get('start_symbol', 'S')
        grammar = q.get('grammar', default_grammar)
        parsed = parse_sentence_cky(sentence, grammar, start_symbol)
        parsed['query_id'] = qid
        parsed['sentence'] = sentence
        res_entry = {
            'query_id': qid,
            'sentence': sentence,
            'token_count': parsed['token_count'],
            'tokens': parsed['tokens'],
            'is_grammatical': parsed['is_grammatical'],
            'is_ambiguous': parsed['is_ambiguous'],
            'parse_count': parsed['parse_count'],
            'viterbi_parse': parsed['viterbi_parse'],
            'all_parses': parsed['all_parses'],
            'chart_summary': parsed['chart_summary']
        }
        results.append(res_entry)
    res = {'results': results}
    print(json.dumps(res, ensure_ascii=False))

if __name__ == '__main__':
    main()
