import sys
import json

SENSE_KEY_NO_SENSE = 0x00
SENSE_KEY_RECOVERED_ERROR = 0x01
SENSE_KEY_NOT_READY = 0x02
SENSE_KEY_MEDIUM_ERROR = 0x03
SENSE_KEY_HARDWARE_ERROR = 0x04
SENSE_KEY_ILLEGAL_REQUEST = 0x05
SENSE_KEY_UNIT_ATTENTION = 0x06
SENSE_KEY_DATA_PROTECT = 0x07
SENSE_KEY_BLANK_CHECK = 0x08
SENSE_KEY_ABORTED_COMMAND = 0x0B

def simulate_scsi_eh(input_data):
    config = input_data.get("config", {})
    max_retries = config.get("max_retries", 3)
    
    devices = {}
    for dev in input_data.get("devices", []):
        key = f"{dev['target']}:{dev['lun']}"
        devices[key] = {
            "target": dev["target"],
            "lun": dev["lun"],
            "state": "RUNNING",
            "active_cmds": 0,
            "failed_cmds": 0,
            "recovered_cmds": 0
        }
        
    commands = input_data.get("commands", [])
    cmd_results = []
    
    metrics = {
        "commands_total": len(commands),
        "commands_completed_success": 0,
        "commands_failed_permanently": 0,
        "eh_aborts_attempted": 0,
        "eh_aborts_succeeded": 0,
        "eh_device_resets": 0,
        "eh_target_resets": 0,
        "eh_bus_host_resets": 0,
        "devices_offlined": 0
    }
    
    for cmd in commands:
        cmd_id = cmd.get("id")
        target = cmd.get("target", 0)
        lun = cmd.get("lun", 0)
        dev_key = f"{target}:{lun}"
        
        dev = devices.get(dev_key)
        if not dev or dev["state"] == "OFFLINE":
            metrics["commands_failed_permanently"] += 1
            cmd_results.append({
                "cmd_id": cmd_id,
                "target": target,
                "lun": lun,
                "completed": False,
                "final_stage": "DEVICE_OFFLINE_OR_NOT_FOUND",
                "retries_used": 0
            })
            continue
            
        dev["active_cmds"] += 1
        error_type = cmd.get("error_type", "NONE")
        sense_key = cmd.get("sense_key", SENSE_KEY_NO_SENSE)
        
        lldd_abort_ok = cmd.get("lldd_abort_ok", False)
        lldd_dev_reset_ok = cmd.get("lldd_dev_reset_ok", False)
        lldd_target_reset_ok = cmd.get("lldd_target_reset_ok", False)
        lldd_host_reset_ok = cmd.get("lldd_host_reset_ok", True)
        
        completed = False
        retries_used = 0
        final_stage = "NORMAL"
        
        if error_type == "NONE":
            completed = True
            final_stage = "NORMAL"
            metrics["commands_completed_success"] += 1
            dev["recovered_cmds"] += 1
            
        elif error_type == "CHECK_CONDITION":
            if sense_key in (SENSE_KEY_NO_SENSE, SENSE_KEY_RECOVERED_ERROR):
                completed = True
                final_stage = "SENSE_RECOVERED"
                metrics["commands_completed_success"] += 1
                dev["recovered_cmds"] += 1
            elif sense_key in (SENSE_KEY_MEDIUM_ERROR, SENSE_KEY_ILLEGAL_REQUEST):
                completed = False
                final_stage = "SENSE_UNRECOVERABLE_FAIL"
                metrics["commands_failed_permanently"] += 1
                dev["failed_cmds"] += 1
            elif sense_key in (SENSE_KEY_NOT_READY, SENSE_KEY_UNIT_ATTENTION, SENSE_KEY_ABORTED_COMMAND):
                retries_available = cmd.get("retries_available", max_retries)
                if retries_available > 0:
                    completed = True
                    retries_used = 1
                    final_stage = "SENSE_RETRY_SUCCESS"
                    metrics["commands_completed_success"] += 1
                    dev["recovered_cmds"] += 1
                else:
                    completed = False
                    final_stage = "SENSE_RETRIES_EXHAUSTED"
                    metrics["commands_failed_permanently"] += 1
                    dev["failed_cmds"] += 1
            elif sense_key == SENSE_KEY_HARDWARE_ERROR:
                error_type = "TIMEOUT"
                
        if error_type == "TIMEOUT":
            metrics["eh_aborts_attempted"] += 1
            if lldd_abort_ok:
                metrics["eh_aborts_succeeded"] += 1
                final_stage = "EH_ABORT_SUCCESS"
                completed = True
                metrics["commands_completed_success"] += 1
                dev["recovered_cmds"] += 1
            else:
                metrics["eh_device_resets"] += 1
                if lldd_dev_reset_ok:
                    final_stage = "EH_DEVICE_RESET_SUCCESS"
                    completed = True
                    metrics["commands_completed_success"] += 1
                    dev["recovered_cmds"] += 1
                else:
                    metrics["eh_target_resets"] += 1
                    if lldd_target_reset_ok:
                        final_stage = "EH_TARGET_RESET_SUCCESS"
                        completed = True
                        metrics["commands_completed_success"] += 1
                        for d_k, d_v in devices.items():
                            if d_v["target"] == target:
                                d_v["recovered_cmds"] += 1
                    else:
                        metrics["eh_bus_host_resets"] += 1
                        if lldd_host_reset_ok:
                            final_stage = "EH_HOST_RESET_SUCCESS"
                            completed = True
                            metrics["commands_completed_success"] += 1
                        else:
                            final_stage = "EH_ESCALATION_FAILED_OFFLINE"
                            completed = False
                            dev["state"] = "OFFLINE"
                            metrics["devices_offlined"] += 1
                            metrics["commands_failed_permanently"] += 1
                            dev["failed_cmds"] += 1

        dev["active_cmds"] -= 1
        cmd_results.append({
            "cmd_id": cmd_id,
            "target": target,
            "lun": lun,
            "completed": completed,
            "final_stage": final_stage,
            "retries_used": retries_used
        })

    return {
        "metrics": metrics,
        "devices": devices,
        "cmd_results": cmd_results
    }

def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raw = sys.stdin.read().strip()
    if not raw:
        return
    data = json.loads(raw)
    result = simulate_scsi_eh(data)
    sys.stdout.write(json.dumps(result, separators=(',', ':'), ensure_ascii=False))

if __name__ == "__main__":
    main()
