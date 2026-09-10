import sys
import json
import copy

if hasattr(sys.stdin, "reconfigure"):
    sys.stdin.reconfigure(encoding="utf-8")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

class ARMSMMUv3Engine:
    def __init__(self, config):
        self.cmdq_size = config.get("cmdq_size", 32)
        self.evtq_size = config.get("evtq_size", 32)
        
        self.stes = {}
        
        self.cmdq = []
        self.evtq = []
        
        self.total_dma_requests = 0
        self.successful_dma = 0
        self.faulted_dma = 0
        self.cmdq_commands_processed = 0
        self.sync_completions = 0
        self.evtq_events_logged = 0
        
        self.translations_by_mode = {
            "BYPASS": 0,
            "STAGE1": 0,
            "STAGE2": 0,
            "NESTED": 0
        }
        
        self.dma_logs = []
        self.event_logs = []

    def config_ste(self, current_time, stream_id, ste_config, s1_mappings=None, s2_mappings=None, s1_ro=False, s2_ro=False):
        self.stes[stream_id] = {
            "stream_id": stream_id,
            "config": ste_config,
            "s1_mappings": s1_mappings or {},
            "s2_mappings": s2_mappings or {},
            "s1_ro": s1_ro,
            "s2_ro": s2_ro
        }
        self.event_logs.append({
            "time": current_time,
            "event": "CONFIG_STE",
            "stream_id": stream_id,
            "config": ste_config,
            "s1_entries": len(s1_mappings or {}),
            "s2_entries": len(s2_mappings or {})
        })

    def submit_cmd(self, current_time, op, args=None):
        self.cmdq_commands_processed += 1
        if op == "CMD_SYNC":
            self.sync_completions += 1
            status = "SYNCED"
        elif op in ("CFGI_STE", "CFGI_CD", "TLBI_NH_VA"):
            status = "INVALIDATED"
        else:
            status = "EXECUTED"
            
        self.event_logs.append({
            "time": current_time,
            "event": "SUBMIT_CMD",
            "op": op,
            "status": status,
            "args": args
        })

    def dma_request(self, current_time, stream_id, iova, size=4096, access_type="READ"):
        self.total_dma_requests += 1
        
        if stream_id not in self.stes:
            self._record_fault(current_time, stream_id, iova, access_type, "F_STREAM_DISABLED", "STREAM_NOT_CONFIGURED")
            return
            
        ste = self.stes[stream_id]
        mode = ste["config"]
        
        if mode == "ABORT":
            self._record_fault(current_time, stream_id, iova, access_type, "F_STREAM_DISABLED", "STE_CONFIG_ABORT")
            return
            
        final_pa = None
        
        if mode == "BYPASS":
            final_pa = iova
            self.translations_by_mode["BYPASS"] += 1
            
        elif mode == "STAGE1":
            s1_map = ste["s1_mappings"]
            if iova not in s1_map:
                self._record_fault(current_time, stream_id, iova, access_type, "F_TRANSLATION", "STAGE1_IOVA_UNMAPPED")
                return
            if access_type == "WRITE" and ste.get("s1_ro", False):
                self._record_fault(current_time, stream_id, iova, access_type, "F_PERMISSION", "STAGE1_WRITE_TO_RO")
                return
            final_pa = s1_map[iova]
            self.translations_by_mode["STAGE1"] += 1
            
        elif mode == "STAGE2":
            s2_map = ste["s2_mappings"]
            if iova not in s2_map:
                self._record_fault(current_time, stream_id, iova, access_type, "F_TRANSLATION", "STAGE2_GPA_UNMAPPED")
                return
            if access_type == "WRITE" and ste.get("s2_ro", False):
                self._record_fault(current_time, stream_id, iova, access_type, "F_PERMISSION", "STAGE2_WRITE_TO_RO")
                return
            final_pa = s2_map[iova]
            self.translations_by_mode["STAGE2"] += 1
            
        elif mode == "NESTED":
            s1_map = ste["s1_mappings"]
            if iova not in s1_map:
                self._record_fault(current_time, stream_id, iova, access_type, "F_TRANSLATION", "NESTED_STAGE1_IOVA_UNMAPPED")
                return
            if access_type == "WRITE" and ste.get("s1_ro", False):
                self._record_fault(current_time, stream_id, iova, access_type, "F_PERMISSION", "NESTED_STAGE1_WRITE_TO_RO")
                return
            ipa = s1_map[iova]
            
            s2_map = ste["s2_mappings"]
            if ipa not in s2_map:
                self._record_fault(current_time, stream_id, iova, access_type, "F_TRANSLATION", f"NESTED_STAGE2_IPA_UNMAPPED (IPA: {ipa})")
                return
            if access_type == "WRITE" and ste.get("s2_ro", False):
                self._record_fault(current_time, stream_id, iova, access_type, "F_PERMISSION", "NESTED_STAGE2_WRITE_TO_RO")
                return
            final_pa = s2_map[ipa]
            self.translations_by_mode["NESTED"] += 1
            
        else:
            self._record_fault(current_time, stream_id, iova, access_type, "F_BAD_STE", f"UNKNOWN_STE_CONFIG_{mode}")
            return
            
        self.successful_dma += 1
        self.dma_logs.append({
            "time": current_time,
            "stream_id": stream_id,
            "mode": mode,
            "iova": hex(iova),
            "pa": hex(final_pa),
            "access_type": access_type,
            "status": "SUCCESS"
        })

    def _record_fault(self, current_time, stream_id, iova, access_type, fault_type, detail):
        self.faulted_dma += 1
        self.evtq_events_logged += 1
        evt = {
            "time": current_time,
            "stream_id": stream_id,
            "iova": hex(iova),
            "access_type": access_type,
            "fault_type": fault_type,
            "detail": detail
        }
        self.evtq.append(evt)
        self.dma_logs.append({
            "time": current_time,
            "stream_id": stream_id,
            "iova": hex(iova),
            "access_type": access_type,
            "status": "FAULT",
            "fault_type": fault_type,
            "detail": detail
        })

    def run_trace(self, trace):
        for ev in trace:
            t = ev.get("time", 0)
            ev_type = ev.get("type")
            if ev_type == "CONFIG_STE":
                s1 = {int(k): int(v) for k, v in ev.get("s1_mappings", {}).items()}
                s2 = {int(k): int(v) for k, v in ev.get("s2_mappings", {}).items()}
                self.config_ste(t, ev["stream_id"], ev["config"], s1, s2, ev.get("s1_ro", False), ev.get("s2_ro", False))
            elif ev_type == "SUBMIT_CMD":
                self.submit_cmd(t, ev["op"], ev.get("args"))
            elif ev_type == "DMA_REQUEST":
                self.dma_request(t, ev["stream_id"], ev["iova"], ev.get("size", 4096), ev.get("access_type", "READ"))

    def get_result(self):
        return {
            "summary": {
                "total_dma_requests": self.total_dma_requests,
                "successful_dma": self.successful_dma,
                "faulted_dma": self.faulted_dma,
                "cmdq_commands_processed": self.cmdq_commands_processed,
                "sync_completions": self.sync_completions,
                "evtq_events_logged": self.evtq_events_logged,
                "translations_by_mode": self.translations_by_mode
            },
            "evtq": self.evtq,
            "dma_logs": self.dma_logs,
            "event_logs": self.event_logs
        }

def main():
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return
    data = json.loads(raw_input)
    config = data.get("config", {})
    trace = data.get("trace", [])
    
    engine = ARMSMMUv3Engine(config)
    engine.run_trace(trace)
    result = engine.get_result()
    print(json.dumps(result, separators=(',', ':'), ensure_ascii=False))

if __name__ == "__main__":
    main()
