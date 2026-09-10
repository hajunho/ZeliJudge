import sys
import json
import hashlib

class ARMCCARMEEngine:
    def __init__(self, config=None):
        self.granules = {}
        self.realms = {}
        
        self.delegated_granules_count = 0
        self.undelegated_granules_count = 0
        self.gpc_faults_blocked = 0
        self.realms_created = 0
        self.realms_active = 0
        
        self.security_logs = []
        self.event_logs = []

    def _get_granule(self, pa):
        if pa not in self.granules:
            self.granules[pa] = {
                "pa": pa,
                "state": "NON_SECURE",
                "realm_id": None,
                "scrubbed": True
            }
        return self.granules[pa]

    def rmi_granule_delegate(self, current_time, pa):
        g = self._get_granule(pa)
        if g["state"] != "NON_SECURE":
            self.event_logs.append({
                "time": current_time,
                "event": "RMI_ERROR",
                "error": "RMI_ERROR_INPUT_NOT_NON_SECURE",
                "pa": pa
            })
            return False
            
        g["state"] = "REALM"
        g["scrubbed"] = False
        self.delegated_granules_count += 1
        self.event_logs.append({
            "time": current_time,
            "event": "RMI_GRANULE_DELEGATE_SUCCESS",
            "pa": pa,
            "new_state": "REALM"
        })
        return True

    def rmi_realm_create(self, current_time, realm_id, params=None):
        if realm_id in self.realms:
            self.event_logs.append({
                "time": current_time,
                "event": "RMI_ERROR",
                "error": "REALM_ALREADY_EXISTS",
                "realm_id": realm_id
            })
            return False
            
        self.realms[realm_id] = {
            "realm_id": realm_id,
            "state": "NEW",
            "measurement": hashlib.sha256(b"RME_INITIAL_SEED").hexdigest()[:16],
            "ipa_map": {},
            "params": params or {}
        }
        self.realms_created += 1
        self.event_logs.append({
            "time": current_time,
            "event": "RMI_REALM_CREATE_SUCCESS",
            "realm_id": realm_id,
            "initial_measurement": self.realms[realm_id]["measurement"]
        })
        return True

    def rmi_rtt_map(self, current_time, realm_id, ipa, pa, data_hash=""):
        if realm_id not in self.realms:
            return False
        r = self.realms[realm_id]
        if r["state"] != "NEW":
            self.event_logs.append({
                "time": current_time,
                "event": "RMI_ERROR",
                "error": "REALM_NOT_IN_NEW_STATE",
                "realm_id": realm_id
            })
            return False
            
        g = self._get_granule(pa)
        if g["state"] != "REALM" or g["realm_id"] is not None:
            self.event_logs.append({
                "time": current_time,
                "event": "RMI_ERROR",
                "error": "GRANULE_INVALID_OR_ALREADY_MAPPED",
                "pa": pa
            })
            return False
            
        g["realm_id"] = realm_id
        r["ipa_map"][ipa] = {
            "pa": pa,
            "ripas": "RAM",
            "data_hash": data_hash
        }
        combined = (r["measurement"] + ipa + pa + data_hash).encode("utf-8")
        r["measurement"] = hashlib.sha256(combined).hexdigest()[:16]
        
        self.event_logs.append({
            "time": current_time,
            "event": "RMI_RTT_MAP_SUCCESS",
            "realm_id": realm_id,
            "ipa": ipa,
            "pa": pa,
            "new_measurement": r["measurement"]
        })
        return True

    def rmi_realm_activate(self, current_time, realm_id):
        if realm_id not in self.realms:
            return False
        r = self.realms[realm_id]
        if r["state"] != "NEW":
            return False
            
        r["state"] = "ACTIVE"
        self.realms_active += 1
        self.security_logs.append({
            "time": current_time,
            "action": "REALM_SEALED_AND_ACTIVATED",
            "realm_id": realm_id,
            "final_measurement": r["measurement"]
        })
        self.event_logs.append({
            "time": current_time,
            "event": "RMI_REALM_ACTIVATE_SUCCESS",
            "realm_id": realm_id,
            "final_measurement": r["measurement"]
        })
        return True

    def host_access_attempt(self, current_time, pa, access_type="READ"):
        g = self._get_granule(pa)
        if g["state"] == "REALM":
            self.gpc_faults_blocked += 1
            self.security_logs.append({
                "time": current_time,
                "action": "GPC_FAULT_BLOCKED",
                "pa": pa,
                "access_type": access_type,
                "granule_state": "REALM",
                "realm_id": g["realm_id"]
            })
            self.event_logs.append({
                "time": current_time,
                "event": "HARDWARE_GPC_FAULT",
                "pa": pa,
                "status": "TERMINATED_BY_GPC"
            })
            return False
        else:
            self.event_logs.append({
                "time": current_time,
                "event": "HOST_ACCESS_ALLOWED",
                "pa": pa,
                "access_type": access_type
            })
            return True

    def rsi_attestation_token(self, current_time, realm_id, challenge=""):
        if realm_id not in self.realms:
            return None
        r = self.realms[realm_id]
        token_hash = hashlib.sha256((r["measurement"] + challenge).encode("utf-8")).hexdigest()[:24]
        
        token = {
            "realm_id": realm_id,
            "state": r["state"],
            "measurement": r["measurement"],
            "challenge": challenge,
            "token_signature": token_hash
        }
        self.security_logs.append({
            "time": current_time,
            "action": "RSI_ATTESTATION_ISSUED",
            "realm_id": realm_id,
            "token": token
        })
        self.event_logs.append({
            "time": current_time,
            "event": "RSI_ATTESTATION_TOKEN_SUCCESS",
            "realm_id": realm_id
        })
        return token

    def rmi_realm_destroy(self, current_time, realm_id):
        if realm_id not in self.realms:
            return False
        r = self.realms[realm_id]
        if r["state"] == "ACTIVE":
            self.realms_active -= 1
        r["state"] = "DESTROYED"
        
        for ipa, mapping in r["ipa_map"].items():
            pa = mapping["pa"]
            g = self._get_granule(pa)
            g["realm_id"] = None
            mapping["ripas"] = "DESTROYED"
            
        self.event_logs.append({
            "time": current_time,
            "event": "RMI_REALM_DESTROY_SUCCESS",
            "realm_id": realm_id
        })
        return True

    def rmi_granule_undelegate(self, current_time, pa):
        g = self._get_granule(pa)
        if g["state"] != "REALM":
            self.event_logs.append({
                "time": current_time,
                "event": "RMI_ERROR",
                "error": "GRANULE_NOT_REALM",
                "pa": pa
            })
            return False
            
        if g["realm_id"] is not None:
            self.event_logs.append({
                "time": current_time,
                "event": "RMI_ERROR",
                "error": "GRANULE_STILL_ASSIGNED_TO_REALM",
                "pa": pa,
                "realm_id": g["realm_id"]
            })
            return False
            
        g["state"] = "NON_SECURE"
        g["scrubbed"] = True
        self.undelegated_granules_count += 1
        self.event_logs.append({
            "time": current_time,
            "event": "RMI_GRANULE_UNDELEGATE_SUCCESS",
            "pa": pa,
            "new_state": "NON_SECURE",
            "scrubbed": True
        })
        return True

    def run_trace(self, trace):
        for ev in trace:
            t = ev.get("time", 0)
            ev_type = ev.get("type")
            if ev_type == "RMI_GRANULE_DELEGATE":
                self.rmi_granule_delegate(t, ev["pa"])
            elif ev_type == "RMI_REALM_CREATE":
                self.rmi_realm_create(t, ev["realm_id"], ev.get("params"))
            elif ev_type == "RMI_RTT_MAP":
                self.rmi_rtt_map(t, ev["realm_id"], ev["ipa"], ev["pa"], ev.get("data_hash", ""))
            elif ev_type == "RMI_REALM_ACTIVATE":
                self.rmi_realm_activate(t, ev["realm_id"])
            elif ev_type == "HOST_ACCESS_ATTEMPT":
                self.host_access_attempt(t, ev["pa"], ev.get("access_type", "READ"))
            elif ev_type == "RSI_ATTESTATION_TOKEN":
                self.rsi_attestation_token(t, ev["realm_id"], ev.get("challenge", ""))
            elif ev_type == "RMI_REALM_DESTROY":
                self.rmi_realm_destroy(t, ev["realm_id"])
            elif ev_type == "RMI_GRANULE_UNDELEGATE":
                self.rmi_granule_undelegate(t, ev["pa"])

    def get_result(self):
        realms_out = {}
        for rid, r in sorted(self.realms.items()):
            realms_out[rid] = {
                "state": r["state"],
                "measurement": r["measurement"],
                "mapped_pages_count": len(r["ipa_map"])
            }
            
        granules_out = {}
        for pa, g in sorted(self.granules.items()):
            granules_out[pa] = {
                "state": g["state"],
                "realm_id": g["realm_id"],
                "scrubbed": g["scrubbed"]
            }
            
        return {
            "summary": {
                "delegated_granules_count": self.delegated_granules_count,
                "undelegated_granules_count": self.undelegated_granules_count,
                "gpc_faults_blocked": self.gpc_faults_blocked,
                "realms_created": self.realms_created,
                "realms_active": self.realms_active
            },
            "realms": realms_out,
            "granules": granules_out,
            "security_logs": self.security_logs,
            "event_logs": self.event_logs
        }

def main():
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    
    raw = sys.stdin.read().strip()
    if not raw:
        return
    data = json.loads(raw)
    
    engine = ARMCCARMEEngine(data.get("config", {}))
    engine.run_trace(data.get("trace", []))
    res = engine.get_result()
    print(json.dumps(res, separators=(',', ':'), ensure_ascii=False))

if __name__ == "__main__":
    main()
