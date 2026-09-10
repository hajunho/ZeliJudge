import sys
import json

RETURN_TO_HANDLER_ADDR = 0xffffffff81000000

class FtraceFunctionGraphEngine:
    def __init__(self, max_depth=16, return_to_handler_addr=RETURN_TO_HANDLER_ADDR):
        self.max_depth = max_depth
        self.return_to_handler = return_to_handler_addr
        self.ret_stack = []
        self.hw_stack = []
        self.enabled = False
        self.graph_funcs = set()
        self.active_root_depth = None
        self.trace_events = []
        self.stats = {
            "entries_intercepted": 0,
            "exits_intercepted": 0,
            "stack_hijacks": 0,
            "depth_overflows": 0
        }

    def configure(self, enabled=True, graph_funcs=None, max_depth=None):
        self.enabled = enabled
        if graph_funcs is not None:
            self.graph_funcs = set(graph_funcs)
        if max_depth is not None:
            self.max_depth = max_depth
        return {
            "status": "CONFIGURED",
            "enabled": self.enabled,
            "graph_funcs": sorted(list(self.graph_funcs)),
            "max_depth": self.max_depth
        }

    def fentry_call(self, func_name, caller_ret_addr, timestamp):
        self.hw_stack.append(caller_ret_addr)
        stack_slot_idx = len(self.hw_stack) - 1

        if not self.enabled:
            return {"status": "TRACING_DISABLED", "func": func_name}

        should_trace = True
        if self.graph_funcs:
            if func_name in self.graph_funcs:
                if self.active_root_depth is None:
                    self.active_root_depth = len(self.ret_stack)
            elif self.active_root_depth is None:
                should_trace = False

        if not should_trace:
            return {"status": "FILTERED_OUT", "func": func_name}

        current_depth = len(self.ret_stack)
        if current_depth >= self.max_depth:
            self.stats["depth_overflows"] += 1
            return {"status": "DEPTH_OVERFLOW", "func": func_name, "depth": current_depth}

        frame = {
            "func": func_name,
            "orig_ret": caller_ret_addr,
            "calltime": timestamp,
            "depth": current_depth
        }
        self.ret_stack.append(frame)

        self.hw_stack[stack_slot_idx] = self.return_to_handler
        self.stats["stack_hijacks"] += 1
        self.stats["entries_intercepted"] += 1

        entry_event = {
            "type": "GRAPH_ENTRY",
            "func": func_name,
            "depth": current_depth,
            "calltime": timestamp,
            "hijacked_ret": self.return_to_handler
        }
        self.trace_events.append(entry_event)

        return entry_event

    def fexit_return(self, timestamp):
        if not self.hw_stack:
            return {"status": "EMPTY_HW_STACK"}

        ret_addr = self.hw_stack.pop()

        if ret_addr != self.return_to_handler:
            return {"status": "NORMAL_RETURN", "target_rip": ret_addr}

        if not self.ret_stack:
            return {"status": "SHADOW_STACK_UNDERFLOW"}

        frame = self.ret_stack.pop()
        duration = timestamp - frame["calltime"]
        self.stats["exits_intercepted"] += 1

        exit_event = {
            "type": "GRAPH_EXIT",
            "func": frame["func"],
            "depth": frame["depth"],
            "duration_ns": duration,
            "restored_ret": frame["orig_ret"]
        }
        self.trace_events.append(exit_event)

        if self.active_root_depth is not None and len(self.ret_stack) <= self.active_root_depth:
            self.active_root_depth = None

        return exit_event

    def query_tracer_state(self):
        return {
            "enabled": self.enabled,
            "current_depth": len(self.ret_stack),
            "hw_stack_len": len(self.hw_stack),
            "trace_events_count": len(self.trace_events),
            "trace_events": list(self.trace_events),
            "stats": self.stats
        }

def main():
    if hasattr(sys.stdin, "reconfigure"):
        sys.stdin.reconfigure(encoding="utf-8")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    raw = sys.stdin.read()
    if not raw.strip():
        return
    input_data = json.loads(raw)

    cfg = input_data.get("config", {})
    max_d = cfg.get("max_depth", 16)
    ret_addr = cfg.get("return_to_handler_addr", RETURN_TO_HANDLER_ADDR)

    engine = FtraceFunctionGraphEngine(max_depth=max_d, return_to_handler_addr=ret_addr)
    results = []

    for op in input_data.get("operations", []):
        cmd = op.get("op")
        if cmd == "CONFIGURE":
            res = engine.configure(op.get("enabled", True), op.get("graph_funcs"), op.get("max_depth"))
            results.append(res)
        elif cmd == "FENTRY_CALL":
            res = engine.fentry_call(op["func"], op["caller_ret_addr"], op["timestamp"])
            results.append(res)
        elif cmd == "FEXIT_RETURN":
            res = engine.fexit_return(op["timestamp"])
            results.append(res)
        elif cmd == "QUERY_TRACER_STATE":
            res = engine.query_tracer_state()
            results.append(res)

    out = {"results": results}
    print(json.dumps(out, separators=(',', ':'), ensure_ascii=False))

if __name__ == "__main__":
    main()
