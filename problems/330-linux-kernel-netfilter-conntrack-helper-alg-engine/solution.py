import sys
import json
import re

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

class ConntrackHelperEngine:
    def __init__(self, config: dict):
        self.nat_public_ip = config.get("nat_public_ip", "203.0.113.195")
        self.nat_port_range = list(config.get("nat_port_range", [40000, 50000]))
        self.current_nat_port = self.nat_port_range[0]
        self.expect_timeout_default = config.get("expect_timeout_ticks", 30)

        self.connections = {}
        self.expectations = {}
        self.next_ct_id = 1
        self.next_expect_id = 1
        self.current_tick = 0

        self.stats = {
            "packets_processed": 0,
            "packets_mangled": 0,
            "expectations_created": 0,
            "expectations_fulfilled": 0,
            "expectations_expired": 0,
            "bytes_payload_delta": 0,
            "related_connections_created": 0
        }

    def _allocate_nat_port(self) -> int:
        port = self.current_nat_port
        self.current_nat_port += 1
        if self.current_nat_port > self.nat_port_range[1]:
            self.current_nat_port = self.nat_port_range[0]
        return port

    def create_master_connection(self, proto: str, src_ip: str, src_port: int, dst_ip: str, dst_port: int, helper_name: str = "ftp") -> dict:
        ct_id = self.next_ct_id
        self.next_ct_id += 1

        ct = {
            "ct_id": ct_id,
            "proto": proto,
            "helper_name": helper_name,
            "src_ip": src_ip,
            "src_port": src_port,
            "dst_ip": dst_ip,
            "dst_port": dst_port,
            "nat_ip": self.nat_public_ip,
            "nat_port": self._allocate_nat_port(),
            "state": "ESTABLISHED",
            "seq_offset_outbound": 0,
            "seq_offset_inbound": 0,
            "packets_count": 0
        }
        self.connections[ct_id] = ct
        return {"status": "CREATED", "ct_id": ct_id}

    def process_packet(self, ct_id: int, direction: str, seq: int, ack: int, payload: str = "") -> dict:
        self.stats["packets_processed"] += 1
        ct = self.connections.get(ct_id)
        if ct is None:
            return {"status": "ERROR", "reason": "CONN_NOT_FOUND"}

        ct["packets_count"] += 1
        mangled = False
        expect_created = None
        new_payload = payload

        if direction == "OUTBOUND":
            adj_seq = seq + ct["seq_offset_outbound"]
            adj_ack = ack - ct["seq_offset_inbound"]

            if ct["helper_name"] == "ftp":
                match = re.search(r"PORT\s+(\d+),(\d+),(\d+),(\d+),(\d+),(\d+)", payload)
                if match:
                    cli_ip = f"{match.group(1)}.{match.group(2)}.{match.group(3)}.{match.group(4)}"
                    cli_port = int(match.group(5)) * 256 + int(match.group(6))

                    nat_data_port = self._allocate_nat_port()
                    p1, p2 = nat_data_port // 256, nat_data_port % 256
                    nat_octets = self.nat_public_ip.split(".")
                    replacement = f"PORT {nat_octets[0]},{nat_octets[1]},{nat_octets[2]},{nat_octets[3]},{p1},{p2}"

                    new_payload = payload[:match.start()] + replacement + payload[match.end():]
                    delta = len(new_payload) - len(payload)
                    ct["seq_offset_outbound"] += delta
                    self.stats["bytes_payload_delta"] += delta
                    self.stats["packets_mangled"] += 1
                    mangled = True

                    expect_id = self.next_expect_id
                    self.next_expect_id += 1
                    exp = {
                        "expect_id": expect_id,
                        "master_ct_id": ct_id,
                        "proto": "TCP",
                        "dst_ip": self.nat_public_ip,
                        "dst_port": nat_data_port,
                        "target_cli_ip": cli_ip,
                        "target_cli_port": cli_port,
                        "expires_tick": self.current_tick + self.expect_timeout_default
                    }
                    self.expectations[expect_id] = exp
                    expect_created = exp
                    self.stats["expectations_created"] += 1

            elif ct["helper_name"] == "sip":
                match_c = re.search(r"c=IN IP4\s+([0-9.]+)", payload)
                match_m = re.search(r"m=audio\s+(\d+)\s+RTP/AVP", payload)
                if match_c and match_m:
                    cli_rtp_ip = match_c.group(1)
                    cli_rtp_port = int(match_m.group(1))

                    nat_rtp_port = self._allocate_nat_port()
                    repl_c = f"c=IN IP4 {self.nat_public_ip}"
                    repl_m = f"m=audio {nat_rtp_port} RTP/AVP"

                    new_payload = re.sub(r"c=IN IP4\s+[0-9.]+", repl_c, payload)
                    new_payload = re.sub(r"m=audio\s+\d+\s+RTP/AVP", repl_m, new_payload)

                    delta = len(new_payload) - len(payload)
                    ct["seq_offset_outbound"] += delta
                    self.stats["bytes_payload_delta"] += delta
                    self.stats["packets_mangled"] += 1
                    mangled = True

                    expect_id = self.next_expect_id
                    self.next_expect_id += 1
                    exp = {
                        "expect_id": expect_id,
                        "master_ct_id": ct_id,
                        "proto": "UDP",
                        "dst_ip": self.nat_public_ip,
                        "dst_port": nat_rtp_port,
                        "target_cli_ip": cli_rtp_ip,
                        "target_cli_port": cli_rtp_port,
                        "expires_tick": self.current_tick + self.expect_timeout_default
                    }
                    self.expectations[expect_id] = exp
                    expect_created = exp
                    self.stats["expectations_created"] += 1

        else:
            adj_seq = seq + ct["seq_offset_inbound"]
            adj_ack = ack - ct["seq_offset_outbound"]

            if ct["helper_name"] == "ftp":
                match = re.search(r"227\s+Entering Passive Mode\s*\(([0-9,]+)\)", payload)
                if match:
                    parts = match.group(1).split(",")
                    if len(parts) == 6:
                        srv_data_ip = ".".join(parts[:4])
                        srv_data_port = int(parts[4]) * 256 + int(parts[5])

                        expect_id = self.next_expect_id
                        self.next_expect_id += 1
                        exp = {
                            "expect_id": expect_id,
                            "master_ct_id": ct_id,
                            "proto": "TCP",
                            "dst_ip": srv_data_ip,
                            "dst_port": srv_data_port,
                            "target_cli_ip": ct["src_ip"],
                            "target_cli_port": None,
                            "expires_tick": self.current_tick + self.expect_timeout_default
                        }
                        self.expectations[expect_id] = exp
                        expect_created = exp
                        self.stats["expectations_created"] += 1

        res = {
            "status": "PROCESSED",
            "direction": direction,
            "orig_seq": seq,
            "orig_ack": ack,
            "adj_seq": adj_seq,
            "adj_ack": adj_ack,
            "mangled": mangled,
            "payload": new_payload
        }
        if expect_created:
            res["expectation_created_id"] = expect_created["expect_id"]
        return res

    def match_incoming_data_conn(self, proto: str, src_ip: str, src_port: int, dst_ip: str, dst_port: int) -> dict:
        self.stats["packets_processed"] += 1
        matched_exp = None
        for exp_id, exp in list(self.expectations.items()):
            if exp["proto"] == proto and exp["dst_ip"] == dst_ip and exp["dst_port"] == dst_port:
                matched_exp = exp
                break

        if matched_exp:
            self.stats["expectations_fulfilled"] += 1
            self.stats["related_connections_created"] += 1
            del self.expectations[matched_exp["expect_id"]]

            rel_id = self.next_ct_id
            self.next_ct_id += 1
            rel_ct = {
                "ct_id": rel_id,
                "master_ct_id": matched_exp["master_ct_id"],
                "proto": proto,
                "src_ip": src_ip,
                "src_port": src_port,
                "dst_ip": dst_ip,
                "dst_port": dst_port,
                "state": "RELATED",
                "seq_offset_outbound": 0,
                "seq_offset_inbound": 0,
                "packets_count": 1
            }
            self.connections[rel_id] = rel_ct
            return {
                "status": "ACCEPTED_RELATED",
                "related_ct_id": rel_id,
                "matched_expect_id": matched_exp["expect_id"],
                "translated_dst": f"{matched_exp['target_cli_ip']}:{matched_exp['target_cli_port']}" if matched_exp.get('target_cli_port') else f"{dst_ip}:{dst_port}"
            }
        else:
            return {"status": "DROPPED_BY_FIREWALL", "reason": "NO_MATCHING_EXPECTATION"}

    def tick(self, ticks: int = 1) -> dict:
        self.current_tick += ticks
        expired = []
        for exp_id, exp in list(self.expectations.items()):
            if exp["expires_tick"] <= self.current_tick:
                expired.append(exp_id)
                del self.expectations[exp_id]
                self.stats["expectations_expired"] += 1
        return {"current_tick": self.current_tick, "expired_count": len(expired), "expired_ids": expired}

    def get_summary(self) -> dict:
        return {
            "stats": self.stats,
            "active_connections_count": len(self.connections),
            "active_expectations_count": len(self.expectations),
            "current_tick": self.current_tick,
            "connections": [
                {
                    "ct_id": ct["ct_id"],
                    "state": ct["state"],
                    "src": f"{ct['src_ip']}:{ct['src_port']}",
                    "dst": f"{ct['dst_ip']}:{ct['dst_port']}",
                    "seq_offset_outbound": ct["seq_offset_outbound"],
                    "seq_offset_inbound": ct["seq_offset_inbound"]
                }
                for ct in sorted(self.connections.values(), key=lambda x: x["ct_id"])
            ],
            "expectations": [
                {
                    "expect_id": exp["expect_id"],
                    "master_ct_id": exp["master_ct_id"],
                    "proto": exp["proto"],
                    "expected_target": f"{exp['dst_ip']}:{exp['dst_port']}",
                    "expires_tick": exp["expires_tick"]
                }
                for exp in sorted(self.expectations.values(), key=lambda x: x["expect_id"])
            ]
        }

def main():
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return
    input_data = json.loads(raw_input)
    config = input_data.get("config", {})
    operations = input_data.get("operations", [])

    engine = ConntrackHelperEngine(config)
    execution_log = []

    for op in operations:
        t = op.get("op")
        if t == "CREATE_MASTER":
            res = engine.create_master_connection(
                op.get("proto", "TCP"),
                op.get("src_ip", "10.0.0.2"),
                op.get("src_port", 50000),
                op.get("dst_ip", "198.51.100.1"),
                op.get("dst_port", 21),
                op.get("helper_name", "ftp")
            )
            execution_log.append({"op": t, "result": res})
        elif t == "PROCESS_PACKET":
            res = engine.process_packet(
                op.get("ct_id", 1),
                op.get("direction", "OUTBOUND"),
                op.get("seq", 1000),
                op.get("ack", 2000),
                op.get("payload", "")
            )
            execution_log.append({"op": t, "result": res})
        elif t == "MATCH_DATA":
            res = engine.match_incoming_data_conn(
                op.get("proto", "TCP"),
                op.get("src_ip", "198.51.100.1"),
                op.get("src_port", 20),
                op.get("dst_ip", "203.0.113.195"),
                op.get("dst_port", 40000)
            )
            execution_log.append({"op": t, "result": res})
        elif t == "TICK":
            res = engine.tick(op.get("ticks", 1))
            execution_log.append({"op": t, "result": res})

    output = {
        "execution_log": execution_log,
        "final_summary": engine.get_summary()
    }
    print(json.dumps(output, separators=(',', ':')))

if __name__ == "__main__":
    main()
