import sys

class PhysicalConnection:
    def __init__(self, conn_id):
        self.conn_id = conn_id
        self.active_cursors = 0


class JDBCPoolSimulator:
    def __init__(self):
        self.reset()

    def reset(self):
        self.max_cursors = 50
        self.pool_size = 5
        self.mode = "AUTO_CLOSE"  # AUTO_CLOSE | LEAK_ALL | LEAK_RESULTSET

        self.pool = [PhysicalConnection(i) for i in range(self.pool_size)]
        self.total_queries = 0
        self.cursor_errors = 0
        self.leaked_result_sets = 0

    def config(self, max_cursors, pool_size, mode):
        self.max_cursors = int(max_cursors)
        self.pool_size = int(pool_size)
        self.mode = mode.upper()
        self.pool = [PhysicalConnection(i) for i in range(self.pool_size)]
        return f"CONFIG_OK max_cursors={self.max_cursors} pool_size={self.pool_size} mode={self.mode}"

    def execute_query(self, count):
        count = int(count)
        executed = 0

        for i in range(count):
            total_active = sum(c.active_cursors for c in self.pool)
            if total_active >= self.max_cursors:
                self.cursor_errors += 1
                failed = count - executed
                return f"EXECUTE_FAIL executed={executed} failed={failed} reason=ORA-01000_MAX_CURSORS_EXCEEDED active_cursors={total_active}"

            conn_idx = executed % self.pool_size
            conn = self.pool[conn_idx]

            # Query opens cursor on DB
            conn.active_cursors += 1
            executed += 1
            self.total_queries += 1

            # Connection close handling according to mode
            if self.mode == "AUTO_CLOSE":
                # Clean close: Statement and ResultSet closed immediately
                conn.active_cursors -= 1
            elif self.mode == "LEAK_RESULTSET":
                # Stmt closed on DB, but client row buffer leaked
                conn.active_cursors -= 1
                self.leaked_result_sets += 1
            elif self.mode == "LEAK_ALL":
                # Connection returned to pool, but Statement/Cursor leaked on DB
                pass

        total_active = sum(c.active_cursors for c in self.pool)
        return f"EXECUTE_OK executed={executed} active_cursors={total_active}"

    def evict_idle_connections(self):
        freed = sum(c.active_cursors for c in self.pool)
        self.pool = [PhysicalConnection(i) for i in range(self.pool_size)]
        return f"EVICT_OK freed_cursors={freed} remaining_cursors=0"

    def status(self):
        total_active = sum(c.active_cursors for c in self.pool)
        if self.cursor_errors > 0:
            st = "EXHAUSTED"
        elif total_active > 0:
            st = "LEAKING"
        else:
            st = "HEALTHY"

        lines = [
            "--- JDBC_POOL_STATUS ---",
            f"MODE: {self.mode}",
            f"POOL_SIZE: {self.pool_size}",
            f"MAX_CURSORS: {self.max_cursors}",
            f"ACTIVE_CURSORS: {total_active}",
            f"TOTAL_QUERIES: {self.total_queries}",
            f"CURSOR_ERRORS: {self.cursor_errors}",
            f"STATUS: {st}",
            "--- END_STATUS ---"
        ]
        return "\n".join(lines)


def parse_tokens(tokens):
    kv = {}
    pos = []
    for t in tokens:
        if "=" in t:
            k, v = t.split("=", 1)
            kv[k.strip().lower()] = v.strip()
        else:
            pos.append(t.strip())
    return kv, pos


def main():
    sim = JDBCPoolSimulator()
    for line in sys.stdin:
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        parts = line.split()
        cmd = parts[0].upper()
        kv, pos = parse_tokens(parts[1:])

        if cmd == "CONFIG":
            m = kv.get("max_cursors", pos[0] if len(pos) > 0 else 50)
            p = kv.get("pool_size", pos[1] if len(pos) > 1 else 5)
            mode = kv.get("mode", pos[2] if len(pos) > 2 else "AUTO_CLOSE")
            print(sim.config(m, p, mode))
        elif cmd == "EXECUTE_QUERY":
            cnt = kv.get("count", pos[0] if len(pos) > 0 else 1)
            print(sim.execute_query(cnt))
        elif cmd == "EVICT_IDLE_CONNECTIONS":
            print(sim.evict_idle_connections())
        elif cmd == "STATUS":
            print(sim.status())
        elif cmd == "RESET":
            sim.reset()
            print("RESET_OK")


if __name__ == "__main__":
    main()
