import sys
import json
import copy

# Ensure UTF-8 I/O for Windows environments
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stdin, "reconfigure"):
    sys.stdin.reconfigure(encoding="utf-8")

# Access flags definitions (Linux Kernel security/landlock/fs.c)
ACCESS_FS_EXECUTE     = 1 << 0
ACCESS_FS_WRITE_FILE  = 1 << 1
ACCESS_FS_READ_FILE   = 1 << 2
ACCESS_FS_READ_DIR    = 1 << 3
ACCESS_FS_REMOVE_DIR  = 1 << 4
ACCESS_FS_REMOVE_FILE = 1 << 5
ACCESS_FS_MAKE_CHAR   = 1 << 6
ACCESS_FS_MAKE_DIR    = 1 << 7
ACCESS_FS_MAKE_REG    = 1 << 8
ACCESS_FS_MAKE_SOCK   = 1 << 9
ACCESS_FS_MAKE_FIFO   = 1 << 10
ACCESS_FS_MAKE_BLOCK  = 1 << 11
ACCESS_FS_MAKE_SYM    = 1 << 12
ACCESS_FS_REFER       = 1 << 13
ACCESS_FS_TRUNCATE    = 1 << 14

ACCESS_FLAGS_MAP = {
    "EXECUTE": ACCESS_FS_EXECUTE,
    "WRITE_FILE": ACCESS_FS_WRITE_FILE,
    "READ_FILE": ACCESS_FS_READ_FILE,
    "READ_DIR": ACCESS_FS_READ_DIR,
    "REMOVE_DIR": ACCESS_FS_REMOVE_DIR,
    "REMOVE_FILE": ACCESS_FS_REMOVE_FILE,
    "MAKE_CHAR": ACCESS_FS_MAKE_CHAR,
    "MAKE_DIR": ACCESS_FS_MAKE_DIR,
    "MAKE_REG": ACCESS_FS_MAKE_REG,
    "MAKE_SOCK": ACCESS_FS_MAKE_SOCK,
    "MAKE_FIFO": ACCESS_FS_MAKE_FIFO,
    "MAKE_BLOCK": ACCESS_FS_MAKE_BLOCK,
    "MAKE_SYM": ACCESS_FS_MAKE_SYM,
    "REFER": ACCESS_FS_REFER,
    "TRUNCATE": ACCESS_FS_TRUNCATE
}

def parse_access_mask(access_list: list) -> int:
    mask = 0
    for a in access_list:
        if isinstance(a, int):
            mask |= a
        elif isinstance(a, str) and a in ACCESS_FLAGS_MAP:
            mask |= ACCESS_FLAGS_MAP[a]
    return mask

def mask_to_names(mask: int) -> list:
    return [name for name, val in ACCESS_FLAGS_MAP.items() if (mask & val)]

def normalize_path(p: str) -> str:
    p = p.replace("\\", "/").strip()
    parts = [part for part in p.split("/") if part]
    return "/" + "/".join(parts)

class LandlockRuleset:
    def __init__(self, ruleset_id: str, handled_access_fs: int):
        self.ruleset_id = ruleset_id
        self.handled_access_fs = handled_access_fs
        self.rules = {}

    def add_rule(self, path: str, allowed_access_fs: int):
        norm = normalize_path(path)
        self.rules[norm] = allowed_access_fs & self.handled_access_fs

    def check_access(self, target_path: str, req_mask: int) -> bool:
        active_req = req_mask & self.handled_access_fs
        if active_req == 0:
            return True

        norm = normalize_path(target_path)
        cur = norm
        while True:
            if cur in self.rules:
                granted = self.rules[cur]
                if (granted & active_req) == active_req:
                    return True
                else:
                    return False
            if cur == "/":
                break
            parent = "/".join(cur.split("/")[:-1])
            cur = parent if parent else "/"

        return False

class LandlockProcess:
    def __init__(self, pid: int, name: str):
        self.pid = pid
        self.name = name
        self.domain_layers = []
        self.access_logs = []

    def restrict_self(self, ruleset: LandlockRuleset):
        self.domain_layers.append(ruleset)

    def check_access(self, path: str, access_mask: int) -> dict:
        norm_path = normalize_path(path)
        layer_checks = []
        allowed = True
        denied_layer_id = None

        for layer in self.domain_layers:
            granted = layer.check_access(norm_path, access_mask)
            layer_checks.append({
                "ruleset_id": layer.ruleset_id,
                "handled": mask_to_names(layer.handled_access_fs),
                "granted": granted
            })
            if not granted and allowed:
                allowed = False
                denied_layer_id = layer.ruleset_id

        res = {
            "path": norm_path,
            "requested_mask": access_mask,
            "requested_rights": mask_to_names(access_mask),
            "allowed": allowed,
            "errno": 0 if allowed else "EACCES",
            "denied_layer_id": denied_layer_id,
            "layer_checks": layer_checks
        }
        self.access_logs.append(res)
        return res

class LandlockEngine:
    def __init__(self, raw_config: dict):
        config = copy.deepcopy(raw_config)
        self.rulesets = {}
        for r_cfg in config.get("rulesets", []):
            handled = parse_access_mask(r_cfg.get("handled_access_fs", []))
            r = LandlockRuleset(r_cfg["ruleset_id"], handled)
            for rule in r_cfg.get("rules", []):
                allowed = parse_access_mask(rule.get("allowed_access_fs", []))
                r.add_rule(rule["path"], allowed)
            self.rulesets[r.ruleset_id] = r

        self.processes = {}
        for p_cfg in config.get("processes", []):
            p = LandlockProcess(p_cfg["pid"], p_cfg.get("name", f"proc_{p_cfg['pid']}"))
            for rs_id in p_cfg.get("domain_ruleset_ids", []):
                if rs_id in self.rulesets:
                    p.restrict_self(self.rulesets[rs_id])
            self.processes[p.pid] = p

        self.stats = {
            "total_access_requests": 0,
            "access_granted": 0,
            "access_denied": 0
        }
        self.current_step = 0
        self.snapshots = []

    def run_commands(self, commands: list):
        for cmd in commands:
            ctype = cmd["type"]
            if ctype == "CREATE_RULESET":
                handled = parse_access_mask(cmd.get("handled_access_fs", []))
                r = LandlockRuleset(cmd["ruleset_id"], handled)
                self.rulesets[r.ruleset_id] = r

            elif ctype == "ADD_RULE":
                rs_id = cmd["ruleset_id"]
                if rs_id in self.rulesets:
                    allowed = parse_access_mask(cmd.get("allowed_access_fs", []))
                    self.rulesets[rs_id].add_rule(cmd["path"], allowed)

            elif ctype == "RESTRICT_SELF":
                pid = cmd["pid"]
                rs_id = cmd["ruleset_id"]
                if pid in self.processes and rs_id in self.rulesets:
                    self.processes[pid].restrict_self(self.rulesets[rs_id])

            elif ctype == "FORK":
                parent_pid = cmd["parent_pid"]
                child_pid = cmd["child_pid"]
                child_name = cmd.get("child_name", f"proc_{child_pid}")
                if parent_pid in self.processes:
                    parent = self.processes[parent_pid]
                    child = LandlockProcess(child_pid, child_name)
                    child.domain_layers = list(parent.domain_layers)
                    self.processes[child_pid] = child

            elif ctype == "CHECK_ACCESS":
                pid = cmd["pid"]
                path = cmd["path"]
                mask = parse_access_mask(cmd.get("access_rights", []))
                if pid in self.processes:
                    self.stats["total_access_requests"] += 1
                    res = self.processes[pid].check_access(path, mask)
                    if res["allowed"]:
                        self.stats["access_granted"] += 1
                    else:
                        self.stats["access_denied"] += 1

            elif ctype == "STEP":
                self.current_step += 1

            elif ctype == "QUERY_SNAPSHOT":
                self.snapshots.append({
                    "step": self.current_step,
                    "stats": copy.deepcopy(self.stats),
                    "processes": {pid: {
                        "pid": p.pid,
                        "name": p.name,
                        "domain_layers": [l.ruleset_id for l in p.domain_layers],
                        "logs_count": len(p.access_logs)
                    } for pid, p in sorted(self.processes.items())}
                })

    def get_final_result(self) -> dict:
        return {
            "total_steps": self.current_step,
            "stats": self.stats,
            "processes": {pid: {
                "pid": p.pid,
                "name": p.name,
                "domain_layers": [l.ruleset_id for l in p.domain_layers],
                "access_logs": p.access_logs
            } for pid, p in sorted(self.processes.items())},
            "rulesets": {rid: {
                "ruleset_id": r.ruleset_id,
                "handled_access": mask_to_names(r.handled_access_fs),
                "rules": {p: mask_to_names(mask) for p, mask in sorted(r.rules.items())}
            } for rid, r in sorted(self.rulesets.items())},
            "snapshots": self.snapshots
        }

def main():
    raw = sys.stdin.read().strip()
    if not raw:
        return
    data = json.loads(raw)
    engine = LandlockEngine(data.get("config", {}))
    engine.run_commands(data.get("commands", []))
    print(json.dumps(engine.get_final_result(), separators=(",", ":"), ensure_ascii=False))

if __name__ == "__main__":
    main()
