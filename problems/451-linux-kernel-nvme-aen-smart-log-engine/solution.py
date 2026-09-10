import sys
import json

class NvmeController:
    def __init__(self, config):
        self.ctrl_id = config.get("ctrl_id", "nvme0")
        self.aer_limit = config.get("aer_limit", 4)
        self.inflight_aer = config.get("initial_inflight_aer", self.aer_limit)
        
        self.namespaces = {}
        for ns in config.get("namespaces", []):
            nsid = ns["nsid"]
            self.namespaces[nsid] = {
                "nsid": nsid,
                "size_lba": ns.get("size_lba", 209715200),
                "block_size": ns.get("block_size", 4096),
                "ro": ns.get("ro", False)
            }
            
        self.total_events_handled = 0
        self.smart_warnings_logged = 0
        self.reset_count = 0
        self.event_queue = []

    def submit_aer(self):
        if self.inflight_aer < self.aer_limit:
            self.inflight_aer += 1
            if self.event_queue:
                queued_ev = self.event_queue.pop(0)
                return self.trigger_event(queued_ev)
            return {"status": "AER_SUBMITTED", "inflight_aer": self.inflight_aer}
        return {"status": "AER_QUEUE_FULL", "inflight_aer": self.inflight_aer}

    def trigger_event(self, ev):
        event_type = ev.get("event_type")
        log_page = ev.get("log_page", 0)
        payload = ev.get("payload", {})

        if self.inflight_aer == 0:
            self.event_queue.append(ev)
            return {"status": "EVENT_QUEUED_NO_AER", "event_type": event_type}

        self.total_events_handled += 1
        
        if event_type == "SMART_HEALTH" or log_page == 2:
            critical_warn = payload.get("critical_warning_bits", 0)
            warn_list = []
            ro_enforced = False
            
            if critical_warn & (1 << 0):
                warn_list.append("SPARE_BELOW_THRESHOLD")
                self.smart_warnings_logged += 1
            if critical_warn & (1 << 1):
                warn_list.append("TEMPERATURE_EXCEEDED")
                self.smart_warnings_logged += 1
            if critical_warn & (1 << 2):
                warn_list.append("RELIABILITY_DEGRADED")
                self.smart_warnings_logged += 1
            if critical_warn & (1 << 3):
                warn_list.append("MEDIA_READ_ONLY")
                self.smart_warnings_logged += 1
                ro_enforced = True
                for ns in self.namespaces.values():
                    ns["ro"] = True
            if critical_warn & (1 << 4):
                warn_list.append("VOLATILE_BACKUP_FAILED")
                self.smart_warnings_logged += 1

            return {
                "status": "EVENT_PROCESSED",
                "type": "SMART_HEALTH",
                "warnings": warn_list,
                "ro_enforced": ro_enforced
            }

        elif event_type == "NOTICE" or log_page == 4:
            changed_nsids = payload.get("changed_nsids", [])
            ns_updates = payload.get("ns_updates", {})
            scanned = []

            for nsid in changed_nsids:
                scanned.append(nsid)
                if str(nsid) in ns_updates or nsid in ns_updates:
                    info = ns_updates.get(str(nsid), ns_updates.get(nsid))
                    action = info.get("action", "UPDATE")
                    if action == "REMOVE":
                        self.namespaces.pop(nsid, None)
                    elif action in ["UPDATE", "ATTACH"]:
                        self.namespaces[nsid] = {
                            "nsid": nsid,
                            "size_lba": info.get("size_lba", 0),
                            "block_size": info.get("block_size", 4096),
                            "ro": info.get("ro", False)
                        }

            return {
                "status": "EVENT_PROCESSED",
                "type": "NOTICE_CHANGED_NS",
                "scanned_nsids": sorted(scanned)
            }

        elif log_page == 7 or event_type == "TELEMETRY":
            dump_id = payload.get("dump_id", "telemetry_dump_0")
            return {
                "status": "EVENT_PROCESSED",
                "type": "TELEMETRY_CAPTURED",
                "dump_id": dump_id
            }

        return {
            "status": "EVENT_PROCESSED",
            "type": event_type,
            "raw_log_page": log_page
        }

    def reset_controller(self):
        self.reset_count += 1
        self.inflight_aer = self.aer_limit
        self.event_queue.clear()
        return {
            "status": "CTRL_RESET_COMPLETE",
            "ctrl_id": self.ctrl_id,
            "inflight_aer": self.inflight_aer
        }

    def query_stats(self):
        ns_list = []
        for nsid in sorted(self.namespaces.keys()):
            ns_list.append(self.namespaces[nsid])
            
        return {
            "ctrl_id": self.ctrl_id,
            "inflight_aer": self.inflight_aer,
            "total_events_handled": self.total_events_handled,
            "smart_warnings_logged": self.smart_warnings_logged,
            "reset_count": self.reset_count,
            "namespaces": ns_list
        }

def solve():
    if hasattr(sys.stdin, "reconfigure"):
        sys.stdin.reconfigure(encoding="utf-8")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    raw = sys.stdin.read().strip()
    if not raw:
        return

    input_data = json.loads(raw)
    ctrl = NvmeController(input_data.get("config", {}))
    results = []

    for op in input_data.get("operations", []):
        cmd = op.get("op")
        if cmd == "SUBMIT_AER":
            res = ctrl.submit_aer()
            results.append(res)
        elif cmd == "TRIGGER_EVENT":
            res = ctrl.trigger_event(op.get("event", {}))
            results.append(res)
        elif cmd == "RESET_CONTROLLER":
            res = ctrl.reset_controller()
            results.append(res)
        elif cmd == "QUERY_STATS":
            res = ctrl.query_stats()
            results.append(res)

    out_obj = {"results": results}
    print(json.dumps(out_obj, separators=(',', ':'), ensure_ascii=False))

if __name__ == "__main__":
    solve()
