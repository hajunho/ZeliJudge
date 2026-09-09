import sys
import json

class MySQLReplicationEngine:
    def __init__(self, data):
        conf = data.get("config", {})
        self.router_mode = conf.get("router_mode", "RYOW_GTID")
        self.sticky_window_ms = int(conf.get("sticky_window_ms", 2000))
        self.primary_read_capacity = int(conf.get("primary_read_capacity", 5))

        self.primary_gtid = 0
        self.primary_storage = dict(data.get("initial_data", {}))

        self.replica_ids = list(data.get("replicas", ["replica-1", "replica-2"]))
        self.replicas = {
            r: {
                "storage": dict(self.primary_storage),
                "executed_gtid": 0,
                "read_count": 0
            }
            for r in self.replica_ids
        }

        self.replica_rr_idx = 0
        # user_id -> {"last_write_time": int, "last_write_gtid": int, "written_keys": set}
        self.user_sessions = {}
        # Binlog: list of {"gtid": int, "time": int, "key": str, "val": any}
        self.binlog = []
        self.events = data.get("events", [])

    def _pick_replica_least_loaded(self, candidate_rids):
        return min(candidate_rids, key=lambda r: (self.replicas[r]["read_count"], r))

    def _pick_replica_round_robin(self):
        rid = self.replica_ids[self.replica_rr_idx % len(self.replica_ids)]
        self.replica_rr_idx += 1
        return rid

    def run(self):
        results = []
        stale_reads = 0
        primary_reads = 0
        replica_reads = 0
        primary_overloads = 0

        for ev in self.events:
            ev_type = ev.get("type")
            t = ev.get("timestamp", 0)

            if ev_type == "WRITE":
                uid = ev.get("user_id")
                k = ev.get("key")
                v = ev.get("val")

                self.primary_gtid += 1
                gtid = self.primary_gtid
                self.primary_storage[k] = v

                self.binlog.append({
                    "gtid": gtid,
                    "time": t,
                    "key": k,
                    "val": v
                })

                if uid not in self.user_sessions:
                    self.user_sessions[uid] = {
                        "last_write_time": t,
                        "last_write_gtid": gtid,
                        "written_keys": {k}
                    }
                else:
                    self.user_sessions[uid]["last_write_time"] = t
                    self.user_sessions[uid]["last_write_gtid"] = gtid
                    self.user_sessions[uid]["written_keys"].add(k)

                results.append({
                    "type": "WRITE",
                    "timestamp": t,
                    "user_id": uid,
                    "key": k,
                    "gtid": gtid,
                    "status": "COMMITTED"
                })

            elif ev_type == "REPLICATION_APPLY":
                rid = ev.get("replica_id")
                target_gtid = int(ev.get("gtid"))

                applied_count = 0
                r = self.replicas[rid]
                for b in self.binlog:
                    if b["gtid"] > r["executed_gtid"] and b["gtid"] <= target_gtid:
                        r["storage"][b["key"]] = b["val"]
                        r["executed_gtid"] = b["gtid"]
                        applied_count += 1

                results.append({
                    "type": "REPLICATION_APPLY",
                    "timestamp": t,
                    "replica_id": rid,
                    "current_gtid": r["executed_gtid"],
                    "applied_events": applied_count
                })

            elif ev_type == "READ":
                uid = ev.get("user_id")
                k = ev.get("key")

                sess = self.user_sessions.get(uid)
                has_user_written_this_key = (sess is not None and k in sess["written_keys"])
                has_session_write = (sess is not None and sess["last_write_gtid"] > 0)

                in_sticky_window = False
                if has_session_write:
                    time_diff = t - sess["last_write_time"]
                    if time_diff <= self.sticky_window_ms:
                        in_sticky_window = True

                target_node = None
                routing_reason = "DEFAULT_REPLICA"

                if self.router_mode == "PRIMARY_ONLY":
                    target_node = "primary"
                    routing_reason = "POLICY_PRIMARY_ONLY"

                elif self.router_mode == "NAIVE_REPLICA":
                    target_node = self._pick_replica_round_robin()
                    routing_reason = "BLIND_REPLICA_ROUND_ROBIN"

                elif self.router_mode == "RYOW_STICKY":
                    if in_sticky_window:
                        target_node = "primary"
                        routing_reason = "STICKY_WINDOW_PRIMARY"
                    else:
                        target_node = self._pick_replica_round_robin()
                        routing_reason = "REPLICA_WINDOW_EXPIRED"

                elif self.router_mode == "RYOW_GTID":
                    if has_session_write:
                        req_gtid = sess["last_write_gtid"]
                        capable_reps = [
                            rid for rid in self.replica_ids
                            if self.replicas[rid]["executed_gtid"] >= req_gtid
                        ]
                        if capable_reps:
                            target_node = self._pick_replica_least_loaded(capable_reps)
                            routing_reason = f"GTID_SATISFIED_REPLICA ({target_node})"
                        else:
                            target_node = "primary"
                            routing_reason = f"GTID_LAG_FALLBACK_PRIMARY (required gtid {req_gtid})"
                    else:
                        target_node = self._pick_replica_least_loaded(self.replica_ids)
                        routing_reason = "NORMAL_REPLICA_READ"

                if target_node == "primary":
                    primary_reads += 1
                    read_val = self.primary_storage.get(k)
                    served_gtid = self.primary_gtid
                    if primary_reads > self.primary_read_capacity:
                        primary_overloads += 1
                else:
                    replica_reads += 1
                    rep = self.replicas[target_node]
                    rep["read_count"] += 1
                    read_val = rep["storage"].get(k)
                    served_gtid = rep["executed_gtid"]

                is_stale = False
                expected_val = self.primary_storage.get(k)
                if has_user_written_this_key and read_val != expected_val:
                    is_stale = True
                    stale_reads += 1

                results.append({
                    "type": "READ",
                    "timestamp": t,
                    "user_id": uid,
                    "key": k,
                    "routed_to": target_node,
                    "routing_reason": routing_reason,
                    "served_gtid": served_gtid,
                    "val": read_val,
                    "is_stale": is_stale
                })

        return {
            "summary": {
                "router_mode": self.router_mode,
                "total_writes": self.primary_gtid,
                "total_reads": primary_reads + replica_reads,
                "primary_reads": primary_reads,
                "replica_reads": replica_reads,
                "stale_reads": stale_reads,
                "primary_overload_count": primary_overloads,
                "consistency_guaranteed": (stale_reads == 0)
            },
            "replica_status": {
                rid: {
                    "executed_gtid": rinfo["executed_gtid"],
                    "read_count": rinfo["read_count"]
                }
                for rid, rinfo in self.replicas.items()
            },
            "results": results
        }

def main():
    raw = sys.stdin.read().strip()
    if not raw:
        return
    data = json.loads(raw)
    engine = MySQLReplicationEngine(data)
    result = engine.run()
    print(json.dumps(result, indent=2, ensure_ascii=False))

if __name__ == "__main__":
    main()
