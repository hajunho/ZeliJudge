import sys
import json

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

def solve():
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return
        
    input_data = json.loads(raw_input)
    families = {f["family_id"]: f for f in input_data.get("families", [])}
    messages = input_data.get("messages", [])
    
    results = []
    
    for msg in messages:
        msg_id = msg.get("msg_id", "MSG")
        is_root = msg.get("is_sender_root", False)
        hdr = msg.get("nlmsghdr", {})
        nlmsg_len = hdr.get("nlmsg_len", 0)
        nlmsg_type = hdr.get("nlmsg_type", 0)
        flags = hdr.get("nlmsg_flags", [])
        seq = hdr.get("nlmsg_seq", 0)
        pid = hdr.get("nlmsg_pid", 0)
        
        # 1. Header validation
        if nlmsg_len < 16:
            results.append({
                "msg_id": msg_id,
                "status": "ERROR",
                "error": {
                    "errno": -22, # -EINVAL
                    "code": "EINVAL",
                    "reason": "NLMSG_LEN_TOO_SHORT",
                    "nlmsg_seq": seq
                }
            })
            continue
            
        if nlmsg_len % 4 != 0:
            results.append({
                "msg_id": msg_id,
                "status": "ERROR",
                "error": {
                    "errno": -22,
                    "code": "EINVAL",
                    "reason": "NLMSG_NOT_ALIGNED",
                    "nlmsg_seq": seq
                }
            })
            continue
            
        # 2. Netlink Control Messages (< 16)
        if nlmsg_type < 16:
            if nlmsg_type == 1: # NLMSG_NOOP
                results.append({
                    "msg_id": msg_id,
                    "status": "NOOP",
                    "nlmsg_seq": seq,
                    "details": "NLMSG_NOOP_IGNORED"
                })
            else:
                results.append({
                    "msg_id": msg_id,
                    "status": "ERROR",
                    "error": {
                        "errno": -95, # -EOPNOTSUPP
                        "code": "EOPNOTSUPP",
                        "reason": f"UNSUPPORTED_CONTROL_TYPE_{nlmsg_type}",
                        "nlmsg_seq": seq
                    }
                })
            continue
            
        # 3. Generic Netlink Dispatch (nlmsg_type >= 16)
        if nlmsg_type not in families:
            results.append({
                "msg_id": msg_id,
                "status": "ERROR",
                "error": {
                    "errno": -2, # -ENOENT
                    "code": "ENOENT",
                    "reason": "GENL_FAMILY_NOT_FOUND",
                    "nlmsg_seq": seq
                }
            })
            continue
            
        family = families[nlmsg_type]
        if nlmsg_len < 20: # 16 (nlmsghdr) + 4 (genlmsghdr)
            results.append({
                "msg_id": msg_id,
                "status": "ERROR",
                "error": {
                    "errno": -22,
                    "code": "EINVAL",
                    "reason": "GENL_HDR_TOO_SHORT",
                    "nlmsg_seq": seq
                }
            })
            continue
            
        genlhdr = msg.get("genlmsghdr", {})
        cmd_id = genlhdr.get("cmd", 0)
        version = genlhdr.get("version", 1)
        
        if version > family.get("version", 1):
            results.append({
                "msg_id": msg_id,
                "status": "ERROR",
                "error": {
                    "errno": -93, # -EPROTONOSUPPORT
                    "code": "EPROTONOSUPPORT",
                    "reason": "GENL_VERSION_MISMATCH",
                    "nlmsg_seq": seq
                }
            })
            continue
            
        cmd_map = {c["cmd_id"]: c for c in family.get("commands", [])}
        if cmd_id not in cmd_map:
            results.append({
                "msg_id": msg_id,
                "status": "ERROR",
                "error": {
                    "errno": -95,
                    "code": "EOPNOTSUPP",
                    "reason": "GENL_CMD_NOT_FOUND",
                    "nlmsg_seq": seq
                }
            })
            continue
            
        cmd_info = cmd_map[cmd_id]
        if cmd_info.get("requires_root", False) and not is_root:
            results.append({
                "msg_id": msg_id,
                "status": "ERROR",
                "error": {
                    "errno": -1, # -EPERM
                    "code": "EPERM",
                    "reason": "GENL_PERMISSION_DENIED",
                    "nlmsg_seq": seq
                }
            })
            continue

        # 4. TLV Attribute Parsing and Policy Validation
        raw_attrs = msg.get("raw_attrs", [])
        policies = family.get("policies", {})
        maxattr = family.get("maxattr", 32)
        
        parsed_attrs = {}
        attr_parse_error = None
        total_attr_wire_bytes = 0
        
        def validate_attribute(attr, policy_table, max_id):
            nonlocal total_attr_wire_bytes
            raw_type = attr.get("type", 0)
            is_nested = bool(raw_type & 0x8000)
            attr_id = raw_type & 0x3FFF
            val = attr.get("value")
            
            if attr_id == 0 or attr_id > max_id:
                return None, f"ATTR_ID_{attr_id}_OUT_OF_RANGE"
                
            pol_key = str(attr_id)
            if pol_key not in policy_table:
                return None, f"ATTR_{attr_id}_NO_POLICY"
                
            pol = policy_table[pol_key]
            pol_type = pol.get("type")
            
            payload_len = 0
            validated_val = val
            
            if pol_type == "U8":
                if not isinstance(val, int) or not (0 <= val <= 255):
                    return None, f"ATTR_{attr_id}_INVALID_U8"
                payload_len = 1
            elif pol_type == "U16":
                if not isinstance(val, int) or not (0 <= val <= 65535):
                    return None, f"ATTR_{attr_id}_INVALID_U16"
                payload_len = 2
            elif pol_type == "U32":
                if not isinstance(val, int) or not (0 <= val <= 4294967295):
                    return None, f"ATTR_{attr_id}_INVALID_U32"
                payload_len = 4
            elif pol_type == "STRING":
                if not isinstance(val, str):
                    return None, f"ATTR_{attr_id}_NOT_STRING"
                s_len = len(val.encode("utf-8")) + 1 # null-terminated
                min_l = pol.get("min_len", 0)
                max_l = pol.get("max_len", 256)
                if not (min_l <= len(val) <= max_l):
                    return None, f"ATTR_{attr_id}_STRING_LEN_OUT_OF_BOUNDS"
                payload_len = s_len
            elif pol_type == "FLAG":
                validated_val = bool(val)
                payload_len = 0
            elif pol_type == "NESTED":
                if not is_nested or not isinstance(val, list):
                    return None, f"ATTR_{attr_id}_EXPECTED_NESTED"
                child_pols = pol.get("child_policies", {})
                nested_dict = {}
                nested_payload_len = 0
                for c_attr in val:
                    c_res, c_err = validate_attribute(c_attr, child_pols, 32)
                    if c_err:
                        return None, f"NESTED_{c_err}"
                    nested_dict[c_res["attr_id"]] = c_res
                    nested_payload_len += c_res["aligned_wire_len"]
                payload_len = nested_payload_len
                validated_val = nested_dict
            else:
                return None, f"UNKNOWN_POLICY_TYPE_{pol_type}"
                
            nla_len = 4 + payload_len # header + payload
            aligned_wire_len = (nla_len + 3) & ~3
            total_attr_wire_bytes += aligned_wire_len
            
            return {
                "attr_id": attr_id,
                "type": pol_type,
                "is_nested": is_nested,
                "nla_len": nla_len,
                "aligned_wire_len": aligned_wire_len,
                "value": validated_val
            }, None

        for a in raw_attrs:
            res, err = validate_attribute(a, policies, maxattr)
            if err:
                attr_parse_error = err
                break
            parsed_attrs[res["attr_id"]] = res
            
        if attr_parse_error:
            results.append({
                "msg_id": msg_id,
                "status": "ERROR",
                "error": {
                    "errno": -22,
                    "code": "EINVAL",
                    "reason": attr_parse_error,
                    "nlmsg_seq": seq
                }
            })
            continue
            
        # 5. Execution & Response
        is_dump = "NLM_F_DUMP" in flags
        wants_ack = "NLM_F_ACK" in flags
        
        reply_msgs = []
        if is_dump:
            if not cmd_info.get("supports_dump", False):
                results.append({
                    "msg_id": msg_id,
                    "status": "ERROR",
                    "error": {
                        "errno": -95,
                        "code": "EOPNOTSUPP",
                        "reason": "CMD_DOES_NOT_SUPPORT_DUMP",
                        "nlmsg_seq": seq
                    }
                })
                continue
                
            # Multipart dump stream
            reply_msgs.append({
                "nlmsg_type": nlmsg_type,
                "nlmsg_flags": ["NLM_F_MULTI"],
                "nlmsg_seq": seq,
                "genl_cmd": cmd_info["name"],
                "dump_index": 1,
                "payload": f"DUMP_PART_1_FAMILY_{family['name']}"
            })
            reply_msgs.append({
                "nlmsg_type": nlmsg_type,
                "nlmsg_flags": ["NLM_F_MULTI"],
                "nlmsg_seq": seq,
                "genl_cmd": cmd_info["name"],
                "dump_index": 2,
                "payload": f"DUMP_PART_2_FAMILY_{family['name']}"
            })
            # NLMSG_DONE terminates dump
            reply_msgs.append({
                "nlmsg_type": 3, # NLMSG_DONE
                "nlmsg_flags": ["NLM_F_MULTI"],
                "nlmsg_seq": seq,
                "payload": "NLMSG_DONE"
            })
        else:
            # Unicast response
            reply_msgs.append({
                "nlmsg_type": nlmsg_type,
                "nlmsg_flags": [],
                "nlmsg_seq": seq,
                "genl_cmd": cmd_info["name"],
                "dispatched_family": family["name"],
                "parsed_attr_count": len(parsed_attrs),
                "total_attr_bytes": total_attr_wire_bytes
            })
            
        if wants_ack and not is_dump:
            reply_msgs.append({
                "nlmsg_type": 2, # NLMSG_ERROR with errno 0 acts as ACK
                "nlmsg_flags": [],
                "nlmsg_seq": seq,
                "error_code": 0,
                "status": "ACK_SUCCESS"
            })
            
        results.append({
            "msg_id": msg_id,
            "status": "SUCCESS",
            "dispatched_family": family["name"],
            "command": cmd_info["name"],
            "parsed_attrs": parsed_attrs,
            "total_attr_wire_bytes": total_attr_wire_bytes,
            "replies": reply_msgs
        })
        
    output = {
        "processed_count": len(results),
        "results": results
    }
    print(json.dumps(output, separators=(',', ':'), ensure_ascii=False))

if __name__ == "__main__":
    solve()
