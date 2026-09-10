import sys
import json

if hasattr(sys.stdin, "reconfigure"):
    sys.stdin.reconfigure(encoding="utf-8")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

class NVMeController:
    def __init__(self, config, initial_state):
        self.cap_timeout_ms = config.get("cap_timeout_ms", 2000)
        self.max_io_queues = config.get("max_io_queues", 4)
        self.max_retries = config.get("max_retries", 2)
        self.uncor_threshold = config.get("uncor_nonfatal_threshold", 3)
        
        self.state = initial_state.get("state", "NVME_CTRL_LIVE")
        self.csts_cfs = initial_state.get("csts_cfs", 0)
        self.csts_rdy = initial_state.get("csts_rdy", 1)
        self.cc_en = initial_state.get("cc_en", 1)
        
        self.aer_correctable_count = 0
        self.aer_uncor_nonfatal_count = 0
        self.aer_uncor_fatal_count = 0
        self.consecutive_uncor_nonfatal = 0
        
        self.resets_initiated = 0
        self.resets_successful = 0
        self.resets_failed = 0
        
        self.in_flight_cmds = {}
        self.completed_cmds = {}
        self.aborted_cmds = []
        self.requeued_cmds = []
        self.recovered_cmds = []
        
        self.state_history = [self.state]

    def log_state(self, new_state):
        if self.state != new_state:
            self.state = new_state
            self.state_history.append(new_state)

    def handle_io_submit(self, cmd_id, qid, op, lba, blocks):
        if self.state != "NVME_CTRL_LIVE":
            return False
        self.in_flight_cmds[cmd_id] = {
            "cmd_id": cmd_id,
            "qid": qid,
            "op": op,
            "lba": lba,
            "blocks": blocks,
            "retries": 0
        }
        return True

    def handle_io_complete(self, cmd_id, status):
        if cmd_id in self.in_flight_cmds:
            del self.in_flight_cmds[cmd_id]
            self.completed_cmds[cmd_id] = status
            return True
        return False

    def trigger_reset(self, reason, reset_params):
        self.resets_initiated += 1
        self.log_state("NVME_CTRL_RESETTING")
        
        in_flight_list = list(self.in_flight_cmds.values())
        self.in_flight_cmds.clear()
        
        to_requeue = []
        for cmd in in_flight_list:
            if cmd["retries"] < self.max_retries:
                cmd["retries"] += 1
                to_requeue.append(cmd)
                self.requeued_cmds.append(cmd["cmd_id"])
            else:
                self.aborted_cmds.append(cmd["cmd_id"])
                self.completed_cmds[cmd["cmd_id"]] = "ABORTED_EIO"
                
        self.cc_en = 0
        disable_success = reset_params.get("disable_success", True)
        disable_latency = reset_params.get("disable_latency_ms", 100)
        
        if not disable_success or disable_latency > self.cap_timeout_ms:
            self.csts_rdy = 1
            self.resets_failed += 1
            self.log_state("NVME_CTRL_DEAD")
            for cmd in to_requeue:
                self.aborted_cmds.append(cmd["cmd_id"])
                self.completed_cmds[cmd["cmd_id"]] = "ABORTED_EIO"
            return False
            
        self.csts_rdy = 0
        self.csts_cfs = 0
        self.log_state("NVME_CTRL_CONNECTING")
        
        self.cc_en = 1
        enable_success = reset_params.get("enable_success", True)
        enable_latency = reset_params.get("enable_latency_ms", 200)
        
        if not enable_success or enable_latency > self.cap_timeout_ms:
            self.resets_failed += 1
            self.log_state("NVME_CTRL_DEAD")
            for cmd in to_requeue:
                self.aborted_cmds.append(cmd["cmd_id"])
                self.completed_cmds[cmd["cmd_id"]] = "ABORTED_EIO"
            return False
            
        self.csts_rdy = 1
        
        identify_success = reset_params.get("identify_success", True)
        if not identify_success:
            self.resets_failed += 1
            self.log_state("NVME_CTRL_DEAD")
            for cmd in to_requeue:
                self.aborted_cmds.append(cmd["cmd_id"])
                self.completed_cmds[cmd["cmd_id"]] = "ABORTED_EIO"
            return False
            
        self.resets_successful += 1
        self.consecutive_uncor_nonfatal = 0
        self.log_state("NVME_CTRL_LIVE")
        
        for cmd in to_requeue:
            self.in_flight_cmds[cmd["cmd_id"]] = cmd
            self.recovered_cmds.append(cmd["cmd_id"])
            
        return True

    def process_event(self, ev):
        etype = ev.get("type")
        if etype == "IO_SUBMIT":
            self.handle_io_submit(ev["cmd_id"], ev.get("qid", 1), ev.get("op", "READ"), ev.get("lba", 0), ev.get("blocks", 8))
        elif etype == "IO_COMPLETE":
            self.handle_io_complete(ev["cmd_id"], ev.get("status", "SUCCESS"))
        elif etype == "PCI_AER_ERR":
            sev = ev.get("severity")
            code = ev.get("code")
            aff_cmd = ev.get("affected_cmd_id")
            
            if sev == "CORRECTABLE":
                self.aer_correctable_count += 1
            elif sev == "UNCOR_NONFATAL":
                self.aer_uncor_nonfatal_count += 1
                self.consecutive_uncor_nonfatal += 1
                if aff_cmd and aff_cmd in self.in_flight_cmds:
                    del self.in_flight_cmds[aff_cmd]
                    self.aborted_cmds.append(aff_cmd)
                    self.completed_cmds[aff_cmd] = f"ERROR_{code}"
                
                if self.consecutive_uncor_nonfatal >= self.uncor_threshold:
                    reset_params = ev.get("reset_params", {})
                    self.trigger_reset(f"Escalated from {self.consecutive_uncor_nonfatal} uncorrectable non-fatal errors", reset_params)
            elif sev == "UNCOR_FATAL":
                self.aer_uncor_fatal_count += 1
                reset_params = ev.get("reset_params", {})
                self.trigger_reset(f"PCIe AER Fatal Error ({code})", reset_params)
        elif etype == "CSTS_CFS_TRIGGER":
            self.csts_cfs = 1
            reset_params = ev.get("reset_params", {})
            self.trigger_reset("Controller Fatal Status (CSTS.CFS=1)", reset_params)
        elif etype == "KATO_TRIGGER":
            reset_params = ev.get("reset_params", {})
            self.trigger_reset("Keep Alive Timer Timeout (KATO)", reset_params)
        elif etype == "MANUAL_RESET":
            reset_params = ev.get("reset_params", {})
            self.trigger_reset("User Manual Reset", reset_params)

    def get_summary(self):
        return {
            "controller_status": {
                "state": self.state,
                "cc_en": self.cc_en,
                "csts_rdy": self.csts_rdy,
                "csts_cfs": self.csts_cfs,
                "is_operational": self.state == "NVME_CTRL_LIVE"
            },
            "aer_statistics": {
                "correctable_errors": self.aer_correctable_count,
                "uncorrectable_nonfatal_errors": self.aer_uncor_nonfatal_count,
                "uncorrectable_fatal_errors": self.aer_uncor_fatal_count,
                "total_aer_events": self.aer_correctable_count + self.aer_uncor_nonfatal_count + self.aer_uncor_fatal_count
            },
            "reset_metrics": {
                "resets_initiated": self.resets_initiated,
                "resets_successful": self.resets_successful,
                "resets_failed": self.resets_failed,
                "state_history": self.state_history
            },
            "command_metrics": {
                "in_flight_count": len(self.in_flight_cmds),
                "completed_count": len(self.completed_cmds),
                "aborted_commands": self.aborted_cmds,
                "requeued_commands": self.requeued_cmds,
                "recovered_commands": self.recovered_cmds
            }
        }

def main():
    raw = sys.stdin.read()
    if not raw.strip():
        return
    data = json.loads(raw)
    cfg = data.get("config", {})
    init = data.get("initial_state", {})
    events = data.get("events", [])
    ctrl = NVMeController(cfg, init)
    for ev in events:
        ctrl.process_event(ev)
    res = ctrl.get_summary()
    print(json.dumps(res, ensure_ascii=False))

if __name__ == "__main__":
    main()
