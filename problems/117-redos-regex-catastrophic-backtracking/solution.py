import sys

class RegexNode:
    pass

class Lit(RegexNode):
    def __init__(self, char):
        self.char = char

class AnyChar(RegexNode):
    pass

class CharClass(RegexNode):
    def __init__(self, chars):
        self.chars = set(chars)

class Concat(RegexNode):
    def __init__(self, nodes):
        self.nodes = nodes

class Alt(RegexNode):
    def __init__(self, branches):
        self.branches = branches

class Repeat(RegexNode):
    def __init__(self, child, min_cnt, max_cnt):
        self.child = child
        self.min_cnt = min_cnt
        self.max_cnt = max_cnt

class AnchorStart(RegexNode):
    pass

class AnchorEnd(RegexNode):
    pass

def parse_regex(pat: str) -> RegexNode:
    i = 0
    n = len(pat)

    def parse_expr():
        branches = [parse_seq()]
        nonlocal i
        while i < n and pat[i] == '|':
            i += 1
            branches.append(parse_seq())
        if len(branches) == 1:
            return branches[0]
        return Alt(branches)

    def parse_seq():
        nodes = []
        nonlocal i
        while i < n and pat[i] not in ')|':
            nodes.append(parse_repeat())
        if len(nodes) == 1:
            return nodes[0]
        return Concat(nodes)

    def parse_repeat():
        atom = parse_atom()
        nonlocal i
        if i < n:
            if pat[i] == '+':
                i += 1
                return Repeat(atom, 1, None)
            elif pat[i] == '*':
                i += 1
                return Repeat(atom, 0, None)
            elif pat[i] == '?':
                i += 1
                return Repeat(atom, 0, 1)
        return atom

    def parse_atom():
        nonlocal i
        if i >= n:
            return Concat([])
        c = pat[i]
        if c == '^':
            i += 1
            return AnchorStart()
        elif c == '$':
            i += 1
            return AnchorEnd()
        elif c == '.':
            i += 1
            return AnyChar()
        elif c == '(':
            i += 1
            inner = parse_expr()
            if i < n and pat[i] == ')':
                i += 1
            return inner
        elif c == '[':
            i += 1
            chars = []
            while i < n and pat[i] != ']':
                if i + 2 < n and pat[i+1] == '-':
                    start = pat[i]
                    end = pat[i+2]
                    for code in range(ord(start), ord(end) + 1):
                        chars.append(chr(code))
                    i += 3
                else:
                    chars.append(pat[i])
                    i += 1
            if i < n and pat[i] == ']':
                i += 1
            return CharClass(chars)
        elif c == '\\':
            i += 1
            if i < n:
                esc = pat[i]
                i += 1
                if esc == 'd':
                    return CharClass([str(d) for d in range(10)])
                elif esc == 'w':
                    return CharClass([chr(code) for code in range(ord('a'), ord('z')+1)] +
                                     [chr(code) for code in range(ord('A'), ord('Z')+1)] +
                                     [str(d) for d in range(10)] + ['_'])
                else:
                    return Lit(esc)
            return Lit('\\')
        else:
            i += 1
            return Lit(c)

    return parse_expr()

def analyze_vulnerability(pattern: str):
    ast = parse_regex(pattern)

    has_nested_quant = False
    has_ambig_alt = False

    def check_nested(node, inside_repeat=False):
        nonlocal has_nested_quant, has_ambig_alt
        if isinstance(node, Repeat):
            if inside_repeat:
                has_nested_quant = True
            check_nested(node.child, inside_repeat=True)
        elif isinstance(node, Alt):
            if inside_repeat:
                has_ambig_alt = True
            for b in node.branches:
                check_nested(b, inside_repeat=inside_repeat)
        elif isinstance(node, Concat):
            for ch in node.nodes:
                check_nested(ch, inside_repeat=inside_repeat)

    check_nested(ast, False)

    if has_nested_quant:
        return "HIGH_VULNERABILITY", "NESTED_QUANTIFIER"
    if has_ambig_alt:
        return "HIGH_VULNERABILITY", "AMBIGUOUS_ALTERNATION"
    return "SAFE", "NONE"

class CatastrophicBacktrackingError(Exception):
    def __init__(self, steps):
        self.steps = steps

class BacktrackingMatcher:
    def __init__(self, max_steps=100000):
        self.max_steps = max_steps
        self.steps = 0

    def match(self, pattern: str, text: str):
        self.steps = 0
        ast = parse_regex(pattern)

        nodes = ast.nodes if isinstance(ast, Concat) else [ast]
        start_anchored = False
        if nodes and isinstance(nodes[0], AnchorStart):
            start_anchored = True
            nodes = nodes[1:]

        end_anchored = False
        if nodes and isinstance(nodes[-1], AnchorEnd):
            end_anchored = True
            nodes = nodes[:-1]

        def step():
            self.steps += 1
            if self.steps > self.max_steps:
                raise CatastrophicBacktrackingError(self.steps)

        def match_nodes(seq, pos):
            step()
            if not seq:
                yield pos
                return

            head, tail = seq[0], seq[1:]

            if isinstance(head, Lit):
                if pos < len(text) and text[pos] == head.char:
                    yield from match_nodes(tail, pos + 1)

            elif isinstance(head, AnyChar):
                if pos < len(text) and text[pos] != '\n':
                    yield from match_nodes(tail, pos + 1)

            elif isinstance(head, CharClass):
                if pos < len(text) and text[pos] in head.chars:
                    yield from match_nodes(tail, pos + 1)

            elif isinstance(head, Alt):
                for branch in head.branches:
                    b_nodes = branch.nodes if isinstance(branch, Concat) else [branch]
                    yield from match_nodes(b_nodes + tail, pos)

            elif isinstance(head, Repeat):
                yield from match_repeat(head, tail, pos, 0)

            elif isinstance(head, Concat):
                yield from match_nodes(head.nodes + tail, pos)

        def match_repeat(repeat_node, tail, pos, count):
            step()
            min_cnt = repeat_node.min_cnt
            max_cnt = repeat_node.max_cnt
            child_nodes = repeat_node.child.nodes if isinstance(repeat_node.child, Concat) else [repeat_node.child]

            if max_cnt is None or count < max_cnt:
                for child_end in match_nodes(child_nodes, pos):
                    if child_end > pos:
                        yield from match_repeat(repeat_node, tail, child_end, count + 1)

            if count >= min_cnt:
                yield from match_nodes(tail, pos)

        if start_anchored:
            for end_pos in match_nodes(nodes, 0):
                if not end_anchored or end_pos == len(text):
                    return True, self.steps
            return False, self.steps
        else:
            for start_pos in range(len(text) + 1):
                for end_pos in match_nodes(nodes, start_pos):
                    if not end_anchored or end_pos == len(text):
                        return True, self.steps
            return False, self.steps

class State:
    def __init__(self, kind, c=None, chars=None, out=None, out1=None):
        self.kind = kind
        self.c = c
        self.chars = chars
        self.out = out
        self.out1 = out1

class Frag:
    def __init__(self, start, outs):
        self.start = start
        self.outs = outs

def patch(outs, state):
    for s, attr in outs:
        setattr(s, attr, state)

def compile_nfa(ast):
    def comp(node):
        if isinstance(node, Lit):
            s = State('char', c=node.char)
            return Frag(s, [(s, 'out')])
        elif isinstance(node, AnyChar):
            s = State('any')
            return Frag(s, [(s, 'out')])
        elif isinstance(node, CharClass):
            s = State('class', chars=node.chars)
            return Frag(s, [(s, 'out')])
        elif isinstance(node, Concat):
            if not node.nodes:
                s = State('split')
                return Frag(s, [(s, 'out')])
            f = comp(node.nodes[0])
            for next_node in node.nodes[1:]:
                f_next = comp(next_node)
                patch(f.outs, f_next.start)
                f = Frag(f.start, f_next.outs)
            return f
        elif isinstance(node, Alt):
            f1 = comp(node.branches[0])
            if len(node.branches) == 1:
                return f1
            for b in node.branches[1:]:
                f2 = comp(b)
                s = State('split', out=f1.start, out1=f2.start)
                f1 = Frag(s, f1.outs + f2.outs)
            return f1
        elif isinstance(node, Repeat):
            f = comp(node.child)
            if node.min_cnt == 1 and node.max_cnt is None:
                s = State('split', out=f.start, out1=None)
                patch(f.outs, s)
                return Frag(f.start, [(s, 'out1')])
            elif node.min_cnt == 0 and node.max_cnt is None:
                s = State('split', out=f.start, out1=None)
                patch(f.outs, s)
                return Frag(s, [(s, 'out1')])
            elif node.min_cnt == 0 and node.max_cnt == 1:
                s = State('split', out=f.start, out1=None)
                return Frag(s, f.outs + [(s, 'out1')])
            return f
        return Frag(State('split'), [])

    match_state = State('match')
    frag = comp(ast)
    patch(frag.outs, match_state)
    return frag.start, match_state

class LinearRE2Matcher:
    def __init__(self):
        pass

    def match(self, pattern: str, text: str):
        steps = 0
        ast = parse_regex(pattern)

        nodes = ast.nodes if isinstance(ast, Concat) else [ast]
        start_anchored = False
        if nodes and isinstance(nodes[0], AnchorStart):
            start_anchored = True
            nodes = nodes[1:]

        end_anchored = False
        if nodes and isinstance(nodes[-1], AnchorEnd):
            end_anchored = True
            nodes = nodes[:-1]

        clean_ast = Concat(nodes) if len(nodes) != 1 else nodes[0]
        start, match_state = compile_nfa(clean_ast)

        def add_state(s, state_list, visited):
            nonlocal steps
            if s is None or id(s) in visited:
                return
            visited.add(id(s))
            steps += 1
            if s.kind == 'split':
                add_state(s.out, state_list, visited)
                add_state(s.out1, state_list, visited)
            else:
                state_list.append(s)

        current_states = []
        visited = set()
        add_state(start, current_states, visited)

        matched_anywhere = any(s == match_state for s in current_states)

        for ch in text:
            next_states = []
            visited = set()
            for s in current_states:
                steps += 1
                if s.kind == 'char' and s.c == ch:
                    add_state(s.out, next_states, visited)
                elif s.kind == 'any' and ch != '\n':
                    add_state(s.out, next_states, visited)
                elif s.kind == 'class' and ch in s.chars:
                    add_state(s.out, next_states, visited)
            current_states = next_states
            if not start_anchored:
                add_state(start, current_states, visited)
            if any(s == match_state for s in current_states):
                matched_anywhere = True

        if end_anchored:
            is_matched = any(s == match_state for s in current_states)
        else:
            is_matched = matched_anywhere

        return is_matched, steps

def main():
    engine = "BACKTRACKING"
    max_steps = 100000

    backtracking_matcher = BacktrackingMatcher(max_steps=max_steps)
    re2_matcher = LinearRE2Matcher()

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue

        parts = line.split()
        cmd = parts[0]

        if cmd == "CONFIG":
            params = {}
            for p in parts[1:]:
                if '=' in p:
                    k, v = p.split('=', 1)
                    params[k] = v
            if 'engine' in params:
                engine = params['engine']
            if 'max_steps' in params:
                max_steps = int(params['max_steps'])
                backtracking_matcher.max_steps = max_steps
            print(f"OK engine={engine} max_steps={max_steps}")

        elif cmd == "ANALYZE":
            pattern = ""
            for p in parts[1:]:
                if p.startswith("pattern="):
                    pattern = p[len("pattern="):]
            risk, reason = analyze_vulnerability(pattern)
            print(f"ANALYZE_RESULT pattern={pattern} risk={risk} reason={reason}")

        elif cmd == "MATCH":
            pattern = ""
            text = ""
            for p in parts[1:]:
                if p.startswith("pattern="):
                    pattern = p[len("pattern="):]
                elif p.startswith("text="):
                    text = p[len("text="):]

            if engine == "BACKTRACKING":
                try:
                    matched, steps = backtracking_matcher.match(pattern, text)
                    status = "MATCH_SUCCESS" if matched else "MATCH_FAILURE"
                    print(f"{status} pattern={pattern} text={text} matched={'true' if matched else 'false'} steps={steps} elapsed_us={steps}")
                except CatastrophicBacktrackingError as e:
                    print(f"MATCH_TIMEOUT pattern={pattern} text={text} steps={e.steps} error=REDOS_CATASTROPHIC_BACKTRACKING")
            elif engine == "LINEAR_RE2":
                matched, steps = re2_matcher.match(pattern, text)
                status = "MATCH_SUCCESS" if matched else "MATCH_FAILURE"
                print(f"{status} pattern={pattern} text={text} matched={'true' if matched else 'false'} steps={steps} elapsed_us={steps}")

        elif cmd == "RESET":
            engine = "BACKTRACKING"
            max_steps = 100000
            backtracking_matcher.max_steps = max_steps
            print(f"OK engine={engine} max_steps={max_steps}")

if __name__ == '__main__':
    main()
