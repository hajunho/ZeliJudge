import sys
import json
import copy

if sys.platform == "win32":
    try:
        sys.stdin.reconfigure(encoding="utf-8")
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

class MPTCPSubflow:
    def __init__(self, subflow_id: str, srtt_ms: float, cwnd: int, is_backup: bool = False):
        self.subflow_id = subflow_id
        self.srtt_ms = float(srtt_ms)
        self.cwnd = int(cwnd)
        self.in_flight = 0
        self.is_backup = bool(is_backup)
        self.status = "ACTIVE" if not self.is_backup else "BACKUP"
        self.tx_ssn = 1000
        self.rx_ssn = 1000
        self.tx_bytes = 0
        self.tx_packets = 0
        self.rx_bytes = 0
        self.retransmissions = 0

    @property
    def available_window(self) -> int:
        if self.status == "FAILED":
            return 0
        return max(0, self.cwnd - self.in_flight)

    def to_dict(self):
        return {
            "subflow_id": self.subflow_id,
            "status": self.status,
            "is_backup": self.is_backup,
            "srtt_ms": round(self.srtt_ms, 2),
            "cwnd": self.cwnd,
            "in_flight": self.in_flight,
            "available_window": self.available_window,
            "tx_ssn": self.tx_ssn,
            "rx_ssn": self.rx_ssn,
            "tx_bytes": self.tx_bytes,
            "tx_packets": self.tx_packets,
            "rx_bytes": self.rx_bytes,
            "retransmissions": self.retransmissions
        }

class MPTCPEngine:
    def __init__(self, raw_config: dict):
        config = copy.deepcopy(raw_config)
        self.token = config.get("token", "0x3f4a9b1c")
        self.scheduler = config.get("scheduler", "minrtt")
        self.mss = int(config.get("mss", 1400))
        self.initial_dsn = int(config.get("initial_dsn", 1000000000))
        
        self.next_tx_dsn = self.initial_dsn
        self.una_dsn = self.initial_dsn
        self.rx_next_dsn = int(config.get("initial_rx_dsn", 2000000000))
        
        self.subflows = {}
        for sf_cfg in config.get("subflows", []):
            sf = MPTCPSubflow(
                subflow_id=sf_cfg["subflow_id"],
                srtt_ms=sf_cfg.get("srtt_ms", 20.0),
                cwnd=sf_cfg.get("cwnd", 14000),
                is_backup=sf_cfg.get("is_backup", False)
            )
            self.subflows[sf.subflow_id] = sf

        self.rr_index = 0
        self.in_flight_mappings = []
        self.rx_reorder_queue = {}
        self.delivered_stream = ""
        self.total_tx_bytes = 0
        self.total_rx_bytes = 0
        self.total_retransmissions = 0
        self.event_logs = []

    def add_subflow(self, sf_cfg: dict):
        sf = MPTCPSubflow(
            subflow_id=sf_cfg["subflow_id"],
            srtt_ms=sf_cfg.get("srtt_ms", 20.0),
            cwnd=sf_cfg.get("cwnd", 14000),
            is_backup=sf_cfg.get("is_backup", False)
        )
        self.subflows[sf.subflow_id] = sf

    def set_subflow_status(self, subflow_id: str, params: dict):
        if subflow_id not in self.subflows:
            return
        sf = self.subflows[subflow_id]
        if "status" in params:
            sf.status = params["status"]
        if "srtt_ms" in params:
            sf.srtt_ms = float(params["srtt_ms"])
        if "cwnd" in params:
            sf.cwnd = int(params["cwnd"])
        if "is_backup" in params:
            sf.is_backup = bool(params["is_backup"])
            if sf.status != "FAILED":
                sf.status = "BACKUP" if sf.is_backup else "ACTIVE"

    def _select_subflow(self, segment_len: int) -> MPTCPSubflow:
        active_cands = [sf for sf in self.subflows.values() if sf.status == "ACTIVE" and sf.available_window >= segment_len]
        backup_cands = [sf for sf in self.subflows.values() if sf.status == "BACKUP" and sf.available_window >= segment_len]

        candidates = active_cands if active_cands else backup_cands
        if not candidates:
            return None

        if self.scheduler == "minrtt":
            candidates.sort(key=lambda sf: (sf.srtt_ms, sf.subflow_id))
            return candidates[0]
        elif self.scheduler == "round_robin":
            candidates.sort(key=lambda sf: sf.subflow_id)
            sf = candidates[self.rr_index % len(candidates)]
            self.rr_index += 1
            return sf
        elif self.scheduler == "redundant":
            candidates.sort(key=lambda sf: (sf.srtt_ms, sf.subflow_id))
            return candidates[0]

        return candidates[0]

    def send_data(self, payload: str):
        data_bytes = payload.encode("utf-8")
        offset = 0
        total_len = len(data_bytes)

        while offset < total_len:
            seg_len = min(self.mss, total_len - offset)
            seg_data = data_bytes[offset:offset + seg_len].decode("utf-8", errors="replace")

            if self.scheduler == "redundant":
                subflows_to_send = [sf for sf in self.subflows.values() if sf.status in ("ACTIVE", "BACKUP") and sf.available_window >= seg_len]
                if not subflows_to_send:
                    break
                for sf in subflows_to_send:
                    mapping = {
                        "dsn": self.next_tx_dsn,
                        "ssn": sf.tx_ssn,
                        "length": seg_len,
                        "subflow_id": sf.subflow_id,
                        "data": seg_data,
                        "acked": False
                    }
                    self.in_flight_mappings.append(mapping)
                    sf.in_flight += seg_len
                    sf.tx_ssn += seg_len
                    sf.tx_bytes += seg_len
                    sf.tx_packets += 1

                self.total_tx_bytes += seg_len
                self.next_tx_dsn += seg_len
                offset += seg_len
            else:
                target_sf = self._select_subflow(seg_len)
                if not target_sf:
                    break

                mapping = {
                    "dsn": self.next_tx_dsn,
                    "ssn": target_sf.tx_ssn,
                    "length": seg_len,
                    "subflow_id": target_sf.subflow_id,
                    "data": seg_data,
                    "acked": False
                }
                self.in_flight_mappings.append(mapping)
                target_sf.in_flight += seg_len
                target_sf.tx_ssn += seg_len
                target_sf.tx_bytes += seg_len
                target_sf.tx_packets += 1

                self.total_tx_bytes += seg_len
                self.next_tx_dsn += seg_len
                offset += seg_len

    def subflow_ack(self, subflow_id: str, bytes_acked: int):
        if subflow_id in self.subflows:
            sf = self.subflows[subflow_id]
            sf.in_flight = max(0, sf.in_flight - bytes_acked)

    def data_ack(self, ack_dsn: int):
        if ack_dsn <= self.una_dsn:
            return
        self.una_dsn = ack_dsn
        remaining = []
        for m in self.in_flight_mappings:
            if m["dsn"] + m["length"] <= ack_dsn:
                pass
            else:
                remaining.append(m)
        self.in_flight_mappings = remaining

    def receive_packet(self, subflow_id: str, ssn: int, dsn: int, payload: str):
        seg_len = len(payload.encode("utf-8"))
        if subflow_id in self.subflows:
            sf = self.subflows[subflow_id]
            sf.rx_ssn = max(sf.rx_ssn, ssn + seg_len)
            sf.rx_bytes += seg_len

        self.total_rx_bytes += seg_len

        if dsn >= self.rx_next_dsn:
            self.rx_reorder_queue[dsn] = {"length": seg_len, "data": payload}

        while self.rx_next_dsn in self.rx_reorder_queue:
            item = self.rx_reorder_queue.pop(self.rx_next_dsn)
            self.delivered_stream += item["data"]
            self.rx_next_dsn += item["length"]

    def failover_retransmit(self, failed_subflow_id: str):
        if failed_subflow_id in self.subflows:
            self.subflows[failed_subflow_id].status = "FAILED"
            self.subflows[failed_subflow_id].in_flight = 0

        retransmit_candidates = [m for m in self.in_flight_mappings if m["subflow_id"] == failed_subflow_id]
        
        for m in retransmit_candidates:
            new_sf = self._select_subflow(m["length"])
            if new_sf:
                m["subflow_id"] = new_sf.subflow_id
                m["ssn"] = new_sf.tx_ssn
                new_sf.in_flight += m["length"]
                new_sf.tx_ssn += m["length"]
                new_sf.tx_bytes += m["length"]
                new_sf.tx_packets += 1
                new_sf.retransmissions += 1
                self.total_retransmissions += 1

    def run_commands(self, commands: list):
        for cmd in commands:
            ctype = cmd["type"]
            if ctype == "ADD_SUBFLOW":
                self.add_subflow(cmd["subflow"])
            elif ctype == "SET_SUBFLOW_STATUS":
                self.set_subflow_status(cmd["subflow_id"], cmd["params"])
            elif ctype == "SEND_DATA":
                self.send_data(cmd["payload"])
            elif ctype == "SUBFLOW_ACK":
                self.subflow_ack(cmd["subflow_id"], int(cmd["bytes_acked"]))
            elif ctype == "DATA_ACK":
                self.data_ack(int(cmd["ack_dsn"]))
            elif ctype == "RECEIVE_PACKET":
                self.receive_packet(cmd["subflow_id"], int(cmd["ssn"]), int(cmd["dsn"]), cmd["payload"])
            elif ctype == "FAILOVER_RETRANSMIT":
                self.failover_retransmit(cmd["failed_subflow_id"])
            elif ctype == "QUERY_STATE":
                self.event_logs.append({
                    "una_dsn": self.una_dsn,
                    "next_tx_dsn": self.next_tx_dsn,
                    "rx_next_dsn": self.rx_next_dsn,
                    "in_flight_count": len(self.in_flight_mappings),
                    "delivered_length": len(self.delivered_stream)
                })

    def get_final_result(self) -> dict:
        return {
            "token": self.token,
            "scheduler": self.scheduler,
            "una_dsn": self.una_dsn,
            "next_tx_dsn": self.next_tx_dsn,
            "rx_next_dsn": self.rx_next_dsn,
            "delivered_stream": self.delivered_stream,
            "total_tx_bytes": self.total_tx_bytes,
            "total_rx_bytes": self.total_rx_bytes,
            "total_retransmissions": self.total_retransmissions,
            "in_flight_mappings_count": len(self.in_flight_mappings),
            "subflows": {sid: sf.to_dict() for sid, sf in sorted(self.subflows.items())},
            "event_logs": self.event_logs
        }

def main():
    raw = sys.stdin.read().strip()
    if not raw:
        return
    data = json.loads(raw)
    engine = MPTCPEngine(data["config"])
    engine.run_commands(data.get("commands", []))
    result = engine.get_final_result()
    print(json.dumps(result, ensure_ascii=False))

if __name__ == "__main__":
    main()
