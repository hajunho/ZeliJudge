# -*- coding: utf-8 -*-
"""
ZeliJudge Pro Track Problem #383: Linux Kernel Confidential Computing: AMD SEV-SNP & Intel TDX Remote Attestation Engine
Canonical Solution Implementation
"""
import sys
import json
import copy
import hashlib

if hasattr(sys.stdin, "reconfigure"):
    sys.stdin.reconfigure(encoding="utf-8")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

class SevSnpEngine:
    def __init__(self, config):
        self.golden_measurements = set(config.get("trusted_golden_measurements", []))
        self.root_ca_keys = set(config.get("trusted_root_ca_keys", ["amd_ark_root_2026"]))
        self.min_tcb_version = config.get("min_tcb_version", 10)
        self.vms = {}
        self.rmp_table = {}
        self.history = []
        self.stats = {
            "vms_launched": 0,
            "rmp_violations_blocked": 0,
            "attestation_requests": 0,
            "attestations_verified": 0,
            "attestations_rejected": 0
        }

    def _hash384(self, text):
        h = hashlib.sha384()
        h.update(text.encode("utf-8") if isinstance(text, str) else text)
        return h.hexdigest()

    def launch_confidential_vm(self, op):
        vm_id = op["vm_id"]
        asid = op["asid"]
        fw = op.get("firmware", "OVMF_SECURE_BOOT_v2")
        kernel = op.get("kernel", "vmlinuz_6.8_signed")
        initrd = op.get("initrd", "initrd_sealed")
        cmdline = op.get("cmdline", "console=ttyS0 quiet")
        policy = dict(op.get("policy", {"debug_allowed": False, "smt_allowed": True, "min_tcb": 10}))
        tcb_ver = op.get("host_tcb_version", 15)

        raw_image = f"{fw}::{kernel}::{initrd}::{cmdline}"
        measurement = self._hash384(raw_image)

        self.vms[vm_id] = {
            "vm_id": vm_id,
            "asid": asid,
            "measurement": measurement,
            "policy": policy,
            "tcb_version": tcb_ver,
            "chip_id": f"epyc_gen4_chip_{asid}",
            "allocated_pages": set()
        }
        self.stats["vms_launched"] += 1
        self.history.append({
            "op": "LAUNCH_VM", "vm_id": vm_id, "asid": asid, "status": "SUCCESS",
            "measurement": measurement, "debug_allowed": policy.get("debug_allowed", False),
            "detail": f"SEV-SNP confidential VM {vm_id} launched with measurement={measurement[:16]}..."
        })

    def rmp_update(self, op):
        vm_id = op["vm_id"]
        spa = op["spa"]
        gpa = op["gpa"]
        ptype = op.get("page_type", "PAGE_TYPE_NORMAL")
        vm = self.vms.get(vm_id)
        if not vm:
            self.history.append({"op": "RMPUPDATE", "vm_id": vm_id, "status": "ERR_VM_NOT_FOUND", "detail": "vm not found"})
            return

        asid = vm["asid"]
        entry = self.rmp_table.get(spa)
        if entry and entry["asid"] != asid and entry["page_type"] != "PAGE_TYPE_SHARED":
            self.stats["rmp_violations_blocked"] += 1
            self.history.append({
                "op": "RMPUPDATE", "vm_id": vm_id, "spa": spa, "status": "ERR_RMP_VIOLATION",
                "detail": f"#NPF RMP violation: SPA {spa} is already assigned to ASID {entry['asid']}"
            })
            return

        self.rmp_table[spa] = {
            "asid": asid,
            "gpa": gpa,
            "page_type": ptype,
            "validated": False
        }
        vm["allocated_pages"].add(spa)
        self.history.append({
            "op": "RMPUPDATE", "vm_id": vm_id, "spa": spa, "gpa": gpa, "page_type": ptype, "status": "SUCCESS",
            "detail": f"RMP entry mapped: SPA {spa} -> GPA {gpa} (type={ptype}, ASID={asid})"
        })

    def pvalidate(self, op):
        vm_id = op["vm_id"]
        spa = op["spa"]
        gpa = op["gpa"]
        vm = self.vms.get(vm_id)
        entry = self.rmp_table.get(spa)
        if not entry or entry["asid"] != vm["asid"] or entry["gpa"] != gpa:
            self.stats["rmp_violations_blocked"] += 1
            self.history.append({
                "op": "PVALIDATE", "vm_id": vm_id, "spa": spa, "status": "ERR_PVALIDATE_FAIL",
                "detail": f"PVALIDATE failed: RMP mapping mismatch for SPA {spa}"
            })
            return

        entry["validated"] = True
        self.history.append({
            "op": "PVALIDATE", "vm_id": vm_id, "spa": spa, "status": "SUCCESS",
            "detail": f"guest executed PVALIDATE on SPA {spa} (status=VALIDATED)"
        })

    def get_attestation_report(self, op):
        vm_id = op["vm_id"]
        user_data = op.get("user_data", "0" * 64)
        vm = self.vms.get(vm_id)
        if not vm:
            self.history.append({"op": "SNP_GET_REPORT", "vm_id": vm_id, "status": "ERR_VM_NOT_FOUND", "detail": "vm not found"})
            return None

        report_body = f"{vm['measurement']}::{vm['chip_id']}::{vm['tcb_version']}::{user_data}::{vm['policy']['debug_allowed']}"
        signature = self._hash384("VCEK_PRIVATE_KEY::" + report_body)

        report = {
            "vm_id": vm_id,
            "measurement": vm["measurement"],
            "policy": dict(vm["policy"]),
            "tcb_version": vm["tcb_version"],
            "chip_id": vm["chip_id"],
            "user_data": user_data,
            "signature": signature,
            "vcek_signer": "amd_vcek_cert_01",
            "root_ca": "amd_ark_root_2026"
        }
        self.history.append({
            "op": "SNP_GET_REPORT", "vm_id": vm_id, "status": "SUCCESS",
            "measurement": vm["measurement"][:16] + "...",
            "user_data": user_data[:16] + "...",
            "detail": "PSP generated hardware-signed attestation report"
        })
        return report

    def verify_attestation(self, op):
        report = op["report"]
        expected_user_data = op["expected_user_data"]
        self.stats["attestation_requests"] += 1

        if report.get("root_ca") not in self.root_ca_keys:
            self.stats["attestations_rejected"] += 1
            self.history.append({
                "op": "VERIFY_ATTESTATION", "vm_id": report["vm_id"], "status": "REJECTED_UNTRUSTED_CA",
                "detail": f"Attestation rejected: root CA {report.get('root_ca')} not in trusted keyring"
            })
            return

        report_body = f"{report['measurement']}::{report['chip_id']}::{report['tcb_version']}::{report['user_data']}::{report['policy']['debug_allowed']}"
        expected_sig = self._hash384("VCEK_PRIVATE_KEY::" + report_body)
        if report.get("signature") != expected_sig:
            self.stats["attestations_rejected"] += 1
            self.history.append({
                "op": "VERIFY_ATTESTATION", "vm_id": report["vm_id"], "status": "REJECTED_INVALID_SIGNATURE",
                "detail": "Attestation rejected: ECDSA signature over report body does not match VCEK"
            })
            return

        if report.get("user_data") != expected_user_data:
            self.stats["attestations_rejected"] += 1
            self.history.append({
                "op": "VERIFY_ATTESTATION", "vm_id": report["vm_id"], "status": "REJECTED_NONCE_MISMATCH",
                "detail": f"Attestation rejected: user_data nonce mismatch (expected {expected_user_data}, got {report.get('user_data')})"
            })
            return

        if report.get("measurement") not in self.golden_measurements:
            self.stats["attestations_rejected"] += 1
            self.history.append({
                "op": "VERIFY_ATTESTATION", "vm_id": report["vm_id"], "status": "REJECTED_UNKNOWN_MEASUREMENT",
                "detail": f"Attestation rejected: measurement {report.get('measurement')[:16]}... does not match golden image"
            })
            return

        if report.get("policy", {}).get("debug_allowed", False):
            self.stats["attestations_rejected"] += 1
            self.history.append({
                "op": "VERIFY_ATTESTATION", "vm_id": report["vm_id"], "status": "REJECTED_DEBUG_POLICY",
                "detail": "Attestation rejected: confidential VM has debug_allowed enabled"
            })
            return

        if report.get("tcb_version", 0) < self.min_tcb_version:
            self.stats["attestations_rejected"] += 1
            self.history.append({
                "op": "VERIFY_ATTESTATION", "vm_id": report["vm_id"], "status": "REJECTED_OUTDATED_TCB",
                "detail": f"Attestation rejected: hardware TCB version {report.get('tcb_version')} below required minimum {self.min_tcb_version}"
            })
            return

        self.stats["attestations_verified"] += 1
        self.history.append({
            "op": "VERIFY_ATTESTATION", "vm_id": report["vm_id"], "status": "TRUSTED_VERIFIED",
            "detail": "Attestation report fully verified; relying party established hardware root of trust"
        })

    def get_summary(self):
        return {
            "vms_running": len(self.vms),
            "rmp_entries_active": len(self.rmp_table),
            "rmp_violations_blocked": self.stats["rmp_violations_blocked"],
            "attestation_summary": {
                "requests": self.stats["attestation_requests"],
                "verified": self.stats["attestations_verified"],
                "rejected": self.stats["attestations_rejected"]
            }
        }

def main():
    raw = sys.stdin.read().strip()
    if not raw:
        return
    data = json.loads(raw)
    eng = SevSnpEngine(data["config"])
    last_report = None
    for op in data["operations"]:
        cmd = op["op"]
        if cmd == "LAUNCH_VM":
            eng.launch_confidential_vm(op)
        elif cmd == "RMPUPDATE":
            eng.rmp_update(op)
        elif cmd == "PVALIDATE":
            eng.pvalidate(op)
        elif cmd == "SNP_GET_REPORT":
            last_report = eng.get_attestation_report(op)
        elif cmd == "VERIFY_ATTESTATION":
            if "report" not in op and last_report:
                op_copy = dict(op)
                op_copy["report"] = last_report
                eng.verify_attestation(op_copy)
            else:
                eng.verify_attestation(op)
    result = {
        "history": eng.history,
        "summary": eng.get_summary()
    }
    print(json.dumps(result, separators=(',', ':'), ensure_ascii=False))

if __name__ == "__main__":
    main()
