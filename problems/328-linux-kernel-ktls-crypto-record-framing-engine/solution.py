import sys
import json
import hashlib
import hmac

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

def xor_bytes(a: bytes, b: bytes) -> bytes:
    return bytes(x ^ y for x, y in zip(a, b))

def derive_keystream(key: bytes, nonce: bytes, length: int) -> bytes:
    stream = b""
    counter = 0
    while len(stream) < length:
        block = hmac.new(key, nonce + counter.to_bytes(4, "big"), hashlib.sha256).digest()
        stream += block
        counter += 1
    return stream[:length]

def compute_tag(key: bytes, aad: bytes, ciphertext: bytes) -> bytes:
    return hmac.new(key, aad + ciphertext, hashlib.sha256).digest()[:16]

class KTLSEngine:
    CONTENT_TYPES = {
        "APPLICATION_DATA": 23,
        "ALERT": 21,
        "HANDSHAKE": 22
    }
    REV_CONTENT_TYPES = {v: k for k, v in CONTENT_TYPES.items()}

    def __init__(self, config: dict):
        self.tls_version = config.get("tls_version", "TLS_1_3")
        self.cipher_suite = config.get("cipher_suite", "AES_128_GCM")
        self.offload_mode = config.get("offload_mode", "SW")
        self.max_record_size = config.get("max_record_size", 16384)
        self.coalesce_enabled = config.get("coalesce_enabled", True)

        self.tx_key = bytes.fromhex(config.get("tx_key_hex", "01" * 16))
        self.tx_iv = bytes.fromhex(config.get("tx_iv_hex", "a0" * (12 if self.tls_version == "TLS_1_3" else 4)))
        self.rx_key = bytes.fromhex(config.get("rx_key_hex", config.get("tx_key_hex", "01" * 16)))
        self.rx_iv = bytes.fromhex(config.get("rx_iv_hex", config.get("tx_iv_hex", "a0" * (12 if self.tls_version == "TLS_1_3" else 4))))

        self.tx_seq = 0
        self.rx_seq = 0
        self.socket_state = "ACTIVE"

        self.tx_pending_data = b""
        self.tx_pending_type = 23
        self.tx_pending_zero_copy = False

        self.rx_wire_buffer = b""
        self.rx_delivered_data = b""

        self.tx_records_count = 0
        self.tx_payload_bytes = 0
        self.tx_wire_bytes = 0
        self.tx_zero_copy_bytes = 0

        self.rx_records_count = 0
        self.rx_payload_bytes = 0
        self.rx_wire_bytes = 0
        self.rx_mac_errors = 0

        self.tx_records_log = []
        self.wire_output = []
        self.last_loopback_tx_idx = 0

    def _derive_nonce(self, base_iv: bytes, seq: int) -> bytes:
        if self.tls_version == "TLS_1_3":
            seq_bytes = b"\x00" * 4 + seq.to_bytes(8, "big")
            return xor_bytes(base_iv, seq_bytes)
        else:
            salt = base_iv[:4]
            explicit_nonce = seq.to_bytes(8, "big")
            return salt + explicit_nonce

    def _frame_record(self, data: bytes, content_type: int, is_zero_copy: bool) -> bytes:
        seq = self.tx_seq
        self.tx_seq += 1
        nonce = self._derive_nonce(self.tx_iv, seq)

        if self.tls_version == "TLS_1_3":
            inner_plaintext = data + bytes([content_type])
            keystream = derive_keystream(self.tx_key, nonce, len(inner_plaintext))
            ciphertext = xor_bytes(inner_plaintext, keystream)

            legacy_version = b"\x03\x03"
            length = len(ciphertext) + 16
            header = bytes([23]) + legacy_version + length.to_bytes(2, "big")

            aad = header
            tag = compute_tag(self.tx_key, aad, ciphertext)
            record = header + ciphertext + tag
        else:
            keystream = derive_keystream(self.tx_key, nonce, len(data))
            ciphertext = xor_bytes(data, keystream)

            explicit_nonce = seq.to_bytes(8, "big")
            length = len(explicit_nonce) + len(ciphertext) + 16
            header = bytes([content_type]) + b"\x03\x03" + length.to_bytes(2, "big")

            aad = seq.to_bytes(8, "big") + header[:3] + len(ciphertext).to_bytes(2, "big")
            tag = compute_tag(self.tx_key, aad, ciphertext)
            record = header + explicit_nonce + ciphertext + tag

        self.tx_records_count += 1
        self.tx_payload_bytes += len(data)
        self.tx_wire_bytes += len(record)
        if is_zero_copy:
            self.tx_zero_copy_bytes += len(data)

        self.tx_records_log.append({
            "seq": seq,
            "content_type": self.REV_CONTENT_TYPES.get(content_type, "UNKNOWN"),
            "payload_len": len(data),
            "wire_len": len(record),
            "tag_hex": tag.hex(),
            "zero_copy": is_zero_copy
        })
        self.wire_output.append(record.hex())
        return record

    def send(self, data_hex: str, flags: list = None, content_type_str: str = "APPLICATION_DATA"):
        if self.socket_state != "ACTIVE":
            return {"status": "ERROR", "reason": f"Socket in {self.socket_state} state"}

        flags = flags or []
        data = bytes.fromhex(data_hex)
        c_type = self.CONTENT_TYPES.get(content_type_str, 23)
        msg_more = "MSG_MORE" in flags
        zero_copy = "ZERO_COPY" in flags

        emitted_count = 0

        if msg_more and self.coalesce_enabled:
            if len(self.tx_pending_data) + len(data) <= self.max_record_size:
                self.tx_pending_data += data
                self.tx_pending_type = c_type
                if zero_copy:
                    self.tx_pending_zero_copy = True
                return {"status": "BUFFERED", "pending_bytes": len(self.tx_pending_data)}
            else:
                if self.tx_pending_data:
                    self._frame_record(self.tx_pending_data, self.tx_pending_type, self.tx_pending_zero_copy)
                    emitted_count += 1
                    self.tx_pending_data = b""

        combined_data = self.tx_pending_data + data
        self.tx_pending_data = b""
        combined_zc = self.tx_pending_zero_copy or zero_copy
        self.tx_pending_zero_copy = False

        offset = 0
        while offset < len(combined_data):
            chunk = combined_data[offset:offset + self.max_record_size]
            if msg_more and offset + self.max_record_size >= len(combined_data) and self.coalesce_enabled:
                self.tx_pending_data = chunk
                self.tx_pending_type = c_type
                self.tx_pending_zero_copy = combined_zc
                break
            self._frame_record(chunk, c_type, combined_zc)
            emitted_count += 1
            offset += len(chunk)

        return {"status": "SENT", "records_emitted": emitted_count}

    def flush(self):
        if self.tx_pending_data:
            rec = self._frame_record(self.tx_pending_data, self.tx_pending_type, self.tx_pending_zero_copy)
            self.tx_pending_data = b""
            self.tx_pending_zero_copy = False
            return {"status": "FLUSHED", "record_len": len(rec)}
        return {"status": "IDLE", "pending_bytes": 0}

    def receive_wire(self, wire_hex: str):
        if self.socket_state != "ACTIVE":
            return {"status": "ERROR", "reason": f"Socket in {self.socket_state} state"}

        self.rx_wire_buffer += bytes.fromhex(wire_hex)
        delivered_chunks = []

        while len(self.rx_wire_buffer) >= 5:
            header = self.rx_wire_buffer[:5]
            content_type = header[0]
            version = header[1:3]
            rec_length = int.from_bytes(header[3:5], "big")

            if len(self.rx_wire_buffer) < 5 + rec_length:
                break

            record = self.rx_wire_buffer[:5 + rec_length]
            self.rx_wire_buffer = self.rx_wire_buffer[5 + rec_length:]
            self.rx_wire_bytes += len(record)

            seq = self.rx_seq
            nonce = self._derive_nonce(self.rx_iv, seq)

            if self.tls_version == "TLS_1_3":
                ciphertext_with_tag = record[5:]
                if len(ciphertext_with_tag) < 16:
                    self.socket_state = "TLS_ERROR_BAD_RECORD_MAC"
                    self.rx_mac_errors += 1
                    return {"status": "ERROR", "error": "EBADMSG_SHORT_RECORD"}

                ciphertext = ciphertext_with_tag[:-16]
                received_tag = ciphertext_with_tag[-16:]

                aad = header
                computed_tag = compute_tag(self.rx_key, aad, ciphertext)
                if not hmac.compare_digest(received_tag, computed_tag):
                    self.socket_state = "TLS_ERROR_BAD_RECORD_MAC"
                    self.rx_mac_errors += 1
                    return {"status": "ERROR", "error": "EBADMSG_MAC_MISMATCH", "seq": seq}

                keystream = derive_keystream(self.rx_key, nonce, len(ciphertext))
                inner_plaintext = xor_bytes(ciphertext, keystream)
                if not inner_plaintext:
                    self.socket_state = "TLS_ERROR_BAD_RECORD_MAC"
                    self.rx_mac_errors += 1
                    return {"status": "ERROR", "error": "EBADMSG_EMPTY_INNER"}

                actual_content_type = inner_plaintext[-1]
                payload = inner_plaintext[:-1]
            else:
                if rec_length < 8 + 16:
                    self.socket_state = "TLS_ERROR_BAD_RECORD_MAC"
                    self.rx_mac_errors += 1
                    return {"status": "ERROR", "error": "EBADMSG_SHORT_RECORD"}

                explicit_nonce = record[5:13]
                ciphertext = record[13:-16]
                received_tag = record[-16:]

                aad = seq.to_bytes(8, "big") + header[:3] + len(ciphertext).to_bytes(2, "big")
                computed_tag = compute_tag(self.rx_key, aad, ciphertext)
                if not hmac.compare_digest(received_tag, computed_tag):
                    self.socket_state = "TLS_ERROR_BAD_RECORD_MAC"
                    self.rx_mac_errors += 1
                    return {"status": "ERROR", "error": "EBADMSG_MAC_MISMATCH", "seq": seq}

                keystream = derive_keystream(self.rx_key, nonce, len(ciphertext))
                payload = xor_bytes(ciphertext, keystream)
                actual_content_type = content_type

            self.rx_seq += 1
            self.rx_records_count += 1
            self.rx_payload_bytes += len(payload)
            self.rx_delivered_data += payload
            delivered_chunks.append({
                "seq": seq,
                "content_type": self.REV_CONTENT_TYPES.get(actual_content_type, "UNKNOWN"),
                "payload_len": len(payload)
            })

        return {
            "status": "PROCESSED",
            "delivered_records": len(delivered_chunks),
            "pending_rx_bytes": len(self.rx_wire_buffer)
        }

    def loopback(self, corrupt_offset: int = -1):
        new_records = self.wire_output[self.last_loopback_tx_idx:]
        self.last_loopback_tx_idx = len(self.wire_output)

        combined_wire = b"".join(bytes.fromhex(r) for r in new_records)
        if corrupt_offset >= 0 and corrupt_offset < len(combined_wire):
            corrupt_byte = combined_wire[corrupt_offset] ^ 0x01
            combined_wire = combined_wire[:corrupt_offset] + bytes([corrupt_byte]) + combined_wire[corrupt_offset+1:]

        return self.receive_wire(combined_wire.hex())

    def get_status(self):
        total_tx_bytes = self.tx_payload_bytes
        total_rx_bytes = self.rx_payload_bytes
        total_bytes = total_tx_bytes + total_rx_bytes

        if self.offload_mode == "DEVICE":
            cpu_cycles = int(total_bytes * 0.5)
            savings_pct = 88.5
        elif self.offload_mode == "ASYNC":
            cpu_cycles = int(total_bytes * 3.2)
            savings_pct = 62.0
        else:
            non_zc_bytes = total_tx_bytes - self.tx_zero_copy_bytes
            cpu_cycles = int(total_bytes * 12 + non_zc_bytes * 2)
            savings_pct = 0.0

        overhead_ratio = round(self.tx_wire_bytes / self.tx_payload_bytes, 4) if self.tx_payload_bytes > 0 else 1.0

        return {
            "socket_state": self.socket_state,
            "tls_version": self.tls_version,
            "cipher_suite": self.cipher_suite,
            "offload_mode": self.offload_mode,
            "tx_stats": {
                "records_sent": self.tx_records_count,
                "payload_bytes": self.tx_payload_bytes,
                "wire_bytes": self.tx_wire_bytes,
                "zero_copy_bytes": self.tx_zero_copy_bytes,
                "overhead_ratio": overhead_ratio
            },
            "rx_stats": {
                "records_received": self.rx_records_count,
                "payload_bytes": self.rx_payload_bytes,
                "wire_bytes": self.rx_wire_bytes,
                "mac_errors": self.rx_mac_errors,
                "pending_buffer_bytes": len(self.rx_wire_buffer)
            },
            "performance": {
                "estimated_cpu_cycles": cpu_cycles,
                "hardware_offload_savings_pct": savings_pct
            },
            "rx_delivered_plaintext_hex": self.rx_delivered_data.hex(),
            "tx_records_summary": self.tx_records_log
        }

def main():
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return
    input_data = json.loads(raw_input)
    config = input_data.get("config", {})
    operations = input_data.get("operations", [])

    engine = KTLSEngine(config)
    execution_log = []

    for op in operations:
        op_type = op.get("op")
        if op_type == "SEND":
            res = engine.send(op.get("data_hex", ""), op.get("flags"), op.get("content_type", "APPLICATION_DATA"))
            execution_log.append({"op": op_type, "result": res})
        elif op_type == "FLUSH":
            res = engine.flush()
            execution_log.append({"op": op_type, "result": res})
        elif op_type == "RECEIVE":
            res = engine.receive_wire(op.get("wire_hex", ""))
            execution_log.append({"op": op_type, "result": res})
        elif op_type == "INJECT_LOOPBACK":
            res = engine.loopback(op.get("corrupt_offset", -1))
            execution_log.append({"op": op_type, "result": res})

    output_data = {
        "execution_log": execution_log,
        "final_status": engine.get_status()
    }
    print(json.dumps(output_data, separators=(',', ':')))

if __name__ == "__main__":
    main()
