import sys
import os
import json
import struct

# Castagnoli CRC32-C (Polynomial 0x1EDC6F41, reflected 0x82F63B78)
CRC32C_POLY = 0x82F63B78
CRC32C_TABLE = []
for i in range(256):
    c = i
    for _ in range(8):
        c = (c >> 1) ^ CRC32C_POLY if (c & 1) else (c >> 1)
    CRC32C_TABLE.append(c)

def crc32c(data: bytes) -> int:
    crc = 0xFFFFFFFF
    for b in data:
        crc = (crc >> 8) ^ CRC32C_TABLE[(crc ^ b) & 0xFF]
    return (crc ^ 0xFFFFFFFF) & 0xFFFFFFFF

# PDU Types
PDU_H2C_TERM_REQ = 0x00
PDU_C2H_TERM_REQ = 0x01
PDU_CAPSULE_CMD  = 0x04
PDU_CAPSULE_RESP = 0x05
PDU_H2C_DATA     = 0x06
PDU_C2H_DATA     = 0x07
PDU_R2T          = 0x08

PDU_NAMES = {
    0x00: "H2C_TERM_REQ",
    0x01: "C2H_TERM_REQ",
    0x04: "CAPSULE_CMD",
    0x05: "CAPSULE_RESP",
    0x06: "H2C_DATA",
    0x07: "C2H_DATA",
    0x08: "R2T",
}

# PDU Flags
HDGST_FLAG    = 0x01
DDGST_FLAG    = 0x02
DATA_LAST     = 0x04
DATA_SUCCESS  = 0x08

# NVMe Status Codes
NVME_SC_SUCCESS              = 0x0000
NVME_SC_INVALID_FIELD        = 0x0002
NVME_SC_CONNECT_INVALID_PARAM= 0x0180
NVME_SC_DATA_DIGEST_ERROR    = 0x0280
NVME_SC_HEADER_DIGEST_ERROR  = 0x0281
NVME_SC_INVALID_OFFSET       = 0x0282
NVME_SC_PDU_LENGTH_ERROR     = 0x0283

# NVMe Opcodes
NVME_OPC_CONNECT = 0x00
NVME_OPC_WRITE   = 0x01
NVME_OPC_READ    = 0x02
NVME_OPC_IDENTIFY= 0x06
NVME_OPC_FLUSH   = 0x08

class NVMeTCPTarget:
    def __init__(self, config, initial_storage=None):
        self.block_size = config.get("block_size", 512)
        self.ioccsz = config.get("ioccsz", 4096)
        self.max_r2t = config.get("max_r2t", 2048)
        self.hdgst_enable = config.get("hdgst_enable", False)
        self.ddgst_enable = config.get("ddgst_enable", False)
        self.c2h_success = config.get("c2h_success", False)

        self.storage = {} # lba (int) -> bytearray
        if initial_storage:
            for lba_str, hex_val in initial_storage.items():
                data = bytes.fromhex(hex_val)
                self.storage[int(lba_str)] = bytearray(data.ljust(self.block_size, b'\x00')[:self.block_size])

        self.socket_state = "ESTABLISHED"
        self.rx_stream = bytearray()
        self.tx_pdus = []
        self.tx_raw = bytearray()
        self.event_log = []

        self.active_commands = {} # cid -> info
        self.next_ttag = 1
        self.sq_head = 0

        self.stats = {
            "commands_processed": 0,
            "r2t_pdus_sent": 0,
            "h2c_data_pdus_received": 0,
            "c2h_data_pdus_sent": 0,
            "bytes_read": 0,
            "bytes_written": 0,
            "digest_errors": 0,
            "terminations": 0
        }

    def log(self, msg: str):
        self.event_log.append(msg)

    def send_pdu(self, pdu_type: int, flags: int, hlen: int, pdo: int, plen: int, header_payload: bytes, data_payload: bytes = b""):
        pdu_flags = 0
        if self.hdgst_enable:
            pdu_flags |= HDGST_FLAG
        if self.ddgst_enable and len(data_payload) > 0:
            pdu_flags |= DDGST_FLAG
        pdu_flags |= (flags & (DATA_LAST | DATA_SUCCESS))

        hdgst_len = 4 if (pdu_flags & HDGST_FLAG) else 0
        ddgst_len = 4 if (pdu_flags & DDGST_FLAG) else 0
        actual_pdo = (hlen + hdgst_len) if len(data_payload) > 0 else 0
        actual_plen = hlen + hdgst_len + len(data_payload) + ddgst_len

        header_bytes = bytearray(struct.pack("<BBBB I", pdu_type, pdu_flags, hlen, actual_pdo, actual_plen))
        header_bytes.extend(header_payload)
        header_bytes = header_bytes[:hlen]
        if len(header_bytes) < hlen:
            header_bytes.extend(b'\x00' * (hlen - len(header_bytes)))

        raw_packet = bytearray(header_bytes)
        if pdu_flags & HDGST_FLAG:
            h_crc = crc32c(bytes(header_bytes))
            raw_packet.extend(struct.pack("<I", h_crc))

        if len(data_payload) > 0:
            raw_packet.extend(data_payload)
            if pdu_flags & DDGST_FLAG:
                d_crc = crc32c(bytes(data_payload))
                raw_packet.extend(struct.pack("<I", d_crc))

        self.tx_raw.extend(raw_packet)
        return raw_packet

    def send_capsule_resp(self, cid: int, status: int, result: int = 0):
        cqe = struct.pack("<I HH HH I", result, self.sq_head, 0, cid, status, 0)
        self.sq_head = (self.sq_head + 1) & 0xFFFF
        self.send_pdu(PDU_CAPSULE_RESP, 0, 24, 0, 24, cqe)
        status_str = f"0x{status:04x}"
        self.tx_pdus.append({
            "pdu_type": "CAPSULE_RESP",
            "cid": cid,
            "status": status_str,
            "sq_head": self.sq_head
        })
        self.log(f"TX CAPSULE_RESP cid={cid} status={status_str} sq_head={self.sq_head}")

    def send_term_req(self, fes: int, error_offset: int = 0):
        self.stats["terminations"] += 1
        self.socket_state = "TERMINATED"
        payload = struct.pack("<H I 10s", fes, error_offset, b'\x00'*10)
        self.send_pdu(PDU_C2H_TERM_REQ, 0, 24, 0, 24, payload)
        fes_str = f"0x{fes:04x}"
        self.tx_pdus.append({
            "pdu_type": "C2H_TERM_REQ",
            "fes": fes_str,
            "error_offset": error_offset
        })
        self.log(f"TX C2H_TERM_REQ fes={fes_str} error_offset={error_offset}")

    def send_r2t(self, cid: int, ttag: int, r2t_offset: int, r2t_length: int):
        self.stats["r2t_pdus_sent"] += 1
        payload = struct.pack("<HH II 4s", cid, ttag, r2t_offset, r2t_length, b'\x00'*4)
        self.send_pdu(PDU_R2T, 0, 24, 0, 24, payload)
        self.tx_pdus.append({
            "pdu_type": "R2T",
            "cid": cid,
            "ttag": ttag,
            "r2t_offset": r2t_offset,
            "r2t_length": r2t_length
        })
        self.log(f"TX R2T cid={cid} ttag={ttag} offset={r2t_offset} length={r2t_length}")

    def send_c2h_data(self, cid: int, data_offset: int, data: bytes, is_last: bool, is_success: bool):
        self.stats["c2h_data_pdus_sent"] += 1
        flags = 0
        if is_last:
            flags |= DATA_LAST
        if is_success:
            flags |= DATA_SUCCESS

        payload_hdr = struct.pack("<HH II 4s", cid, 0, data_offset, len(data), b'\x00'*4)
        self.send_pdu(PDU_C2H_DATA, flags, 24, 24, 24 + len(data), payload_hdr, data)
        self.tx_pdus.append({
            "pdu_type": "C2H_DATA",
            "cid": cid,
            "data_offset": data_offset,
            "data_length": len(data),
            "last": is_last,
            "success": is_success
        })
        self.log(f"TX C2H_DATA cid={cid} offset={data_offset} len={len(data)} last={is_last} success={is_success}")

    def process_rx_stream(self):
        if self.socket_state == "TERMINATED":
            return

        while len(self.rx_stream) >= 8:
            pdu_type, pdu_flags, hlen, pdo, plen = struct.unpack("<BBBB I", self.rx_stream[:8])
            hdgst_len = 4 if (pdu_flags & HDGST_FLAG) else 0

            if hlen < 8 or plen < hlen + hdgst_len:
                self.send_term_req(NVME_SC_PDU_LENGTH_ERROR, 0)
                return

            if len(self.rx_stream) < plen:
                break

            pdu_bytes = self.rx_stream[:plen]
            del self.rx_stream[:plen]

            # 1. Header digest verification
            if pdu_flags & HDGST_FLAG:
                expected_crc = crc32c(bytes(pdu_bytes[:hlen]))
                actual_crc = struct.unpack("<I", pdu_bytes[hlen:hlen+4])[0]
                if expected_crc != actual_crc:
                    self.stats["digest_errors"] += 1
                    self.log(f"CRC32C ERROR: Header Digest mismatch exp=0x{expected_crc:08x} got=0x{actual_crc:08x}")
                    self.send_term_req(NVME_SC_HEADER_DIGEST_ERROR, hlen)
                    return

            # 2. Data digest verification
            ddgst_len = 4 if (pdu_flags & DDGST_FLAG) else 0
            if ddgst_len > 0:
                if pdo < hlen + hdgst_len or pdo > plen - ddgst_len:
                    self.send_term_req(NVME_SC_INVALID_OFFSET, pdo)
                    return
                data_bytes = bytes(pdu_bytes[pdo : plen - ddgst_len])
                expected_crc = crc32c(data_bytes)
                actual_crc = struct.unpack("<I", pdu_bytes[plen - ddgst_len : plen])[0]
                if expected_crc != actual_crc:
                    self.stats["digest_errors"] += 1
                    self.log(f"CRC32C ERROR: Data Digest mismatch exp=0x{expected_crc:08x} got=0x{actual_crc:08x}")
                    self.send_term_req(NVME_SC_DATA_DIGEST_ERROR, plen - ddgst_len)
                    return
            else:
                data_bytes = bytes(pdu_bytes[pdo : plen]) if pdo > 0 else b""

            self.dispatch_pdu(pdu_type, pdu_flags, pdu_bytes, data_bytes)

    def dispatch_pdu(self, pdu_type: int, pdu_flags: int, pdu_bytes: bytes, data_bytes: bytes):
        if pdu_type == PDU_CAPSULE_CMD:
            self.handle_capsule_cmd(pdu_flags, pdu_bytes, data_bytes)
        elif pdu_type == PDU_H2C_DATA:
            self.handle_h2c_data(pdu_flags, pdu_bytes, data_bytes)
        elif pdu_type == PDU_H2C_TERM_REQ:
            self.socket_state = "TERMINATED"
            self.log("RX H2C_TERM_REQ: Host terminated connection")
        else:
            self.log(f"Unknown PDU type 0x{pdu_type:02x}")
            self.send_term_req(NVME_SC_INVALID_FIELD, 0)

    def handle_capsule_cmd(self, flags: int, pdu_bytes: bytes, data_bytes: bytes):
        sqe = pdu_bytes[8:72]
        opcode = sqe[0]
        cid = struct.unpack("<H", sqe[2:4])[0]
        nsid = struct.unpack("<I", sqe[4:8])[0]
        slba = struct.unpack("<Q", sqe[16:24])[0]
        nlb = struct.unpack("<H", sqe[24:26])[0]

        self.stats["commands_processed"] += 1

        if opcode == NVME_OPC_CONNECT:
            self.log(f"RX CAPSULE_CMD (CONNECT) cid={cid}")
            self.send_capsule_resp(cid, NVME_SC_SUCCESS)

        elif opcode == NVME_OPC_WRITE:
            total_bytes = (nlb + 1) * self.block_size
            self.log(f"RX CAPSULE_CMD (WRITE) cid={cid} slba={slba} nlb={nlb} total_bytes={total_bytes} incapsule_len={len(data_bytes)}")
            if len(data_bytes) >= total_bytes:
                self.commit_write(slba, data_bytes[:total_bytes])
                self.send_capsule_resp(cid, NVME_SC_SUCCESS)
            else:
                ttag = self.next_ttag
                self.next_ttag += 1
                buf = bytearray(total_bytes)
                if len(data_bytes) > 0:
                    buf[:len(data_bytes)] = data_bytes
                    recv_bytes = len(data_bytes)
                else:
                    recv_bytes = 0

                self.active_commands[cid] = {
                    "opcode": NVME_OPC_WRITE,
                    "cid": cid,
                    "slba": slba,
                    "nlb": nlb,
                    "total_bytes": total_bytes,
                    "received_bytes": recv_bytes,
                    "buffer": buf,
                    "ttag": ttag
                }
                r2t_len = min(total_bytes - recv_bytes, self.max_r2t)
                self.send_r2t(cid, ttag, recv_bytes, r2t_len)

        elif opcode == NVME_OPC_READ:
            total_bytes = (nlb + 1) * self.block_size
            self.log(f"RX CAPSULE_CMD (READ) cid={cid} slba={slba} nlb={nlb} total_bytes={total_bytes}")
            read_data = self.read_storage(slba, total_bytes)
            self.stats["bytes_read"] += total_bytes

            if self.c2h_success:
                self.send_c2h_data(cid, 0, read_data, is_last=True, is_success=True)
            else:
                self.send_c2h_data(cid, 0, read_data, is_last=True, is_success=False)
                self.send_capsule_resp(cid, NVME_SC_SUCCESS)

        elif opcode == NVME_OPC_FLUSH:
            self.log(f"RX CAPSULE_CMD (FLUSH) cid={cid}")
            self.send_capsule_resp(cid, NVME_SC_SUCCESS)

        else:
            self.log(f"RX CAPSULE_CMD unknown opcode 0x{opcode:02x}")
            self.send_capsule_resp(cid, NVME_SC_INVALID_FIELD)

    def handle_h2c_data(self, flags: int, pdu_bytes: bytes, data_bytes: bytes):
        self.stats["h2c_data_pdus_received"] += 1
        cid, ttag = struct.unpack("<HH", pdu_bytes[8:12])
        data_offset, data_length = struct.unpack("<II", pdu_bytes[12:20])

        if cid not in self.active_commands:
            self.log(f"H2C_DATA cid={cid} not active")
            self.send_term_req(NVME_SC_INVALID_FIELD, 8)
            return

        cmd = self.active_commands[cid]
        if cmd["ttag"] != ttag or data_offset != cmd["received_bytes"]:
            self.log(f"H2C_DATA invalid offset {data_offset} expected {cmd['received_bytes']} or ttag mismatch")
            self.send_term_req(NVME_SC_INVALID_OFFSET, 12)
            return

        cmd["buffer"][data_offset : data_offset + len(data_bytes)] = data_bytes
        cmd["received_bytes"] += len(data_bytes)
        self.log(f"RX H2C_DATA cid={cid} offset={data_offset} len={len(data_bytes)} recvd={cmd['received_bytes']}/{cmd['total_bytes']}")

        if cmd["received_bytes"] < cmd["total_bytes"]:
            remaining = cmd["total_bytes"] - cmd["received_bytes"]
            r2t_len = min(remaining, self.max_r2t)
            self.send_r2t(cid, cmd["ttag"], cmd["received_bytes"], r2t_len)
        else:
            self.commit_write(cmd["slba"], bytes(cmd["buffer"]))
            del self.active_commands[cid]
            self.send_capsule_resp(cid, NVME_SC_SUCCESS)

    def commit_write(self, slba: int, data: bytes):
        self.stats["bytes_written"] += len(data)
        num_blocks = (len(data) + self.block_size - 1) // self.block_size
        for i in range(num_blocks):
            lba = slba + i
            chunk = data[i*self.block_size : (i+1)*self.block_size]
            if len(chunk) < self.block_size:
                chunk = chunk.ljust(self.block_size, b'\x00')
            self.storage[lba] = bytearray(chunk)
        self.log(f"COMMIT WRITE slba={slba} blocks={num_blocks} bytes={len(data)}")

    def read_storage(self, slba: int, total_bytes: int) -> bytes:
        res = bytearray()
        num_blocks = (total_bytes + self.block_size - 1) // self.block_size
        for i in range(num_blocks):
            lba = slba + i
            if lba in self.storage:
                res.extend(self.storage[lba])
            else:
                res.extend(b'\x00' * self.block_size)
        return bytes(res[:total_bytes])

def build_capsule_cmd(opcode, cid, nsid, slba, nlb, in_capsule_data=b"", hdgst=False, ddgst=False, corrupt_hd=False, corrupt_dd=False):
    hlen = 72
    hd_len = 4 if hdgst else 0
    dd_len = 4 if (ddgst and len(in_capsule_data) > 0) else 0
    pdo = (hlen + hd_len) if len(in_capsule_data) > 0 else 0
    plen = hlen + hd_len + len(in_capsule_data) + dd_len

    flags = 0
    if hdgst: flags |= HDGST_FLAG
    if ddgst and len(in_capsule_data) > 0: flags |= DDGST_FLAG

    sqe = struct.pack("<BBH I 8s Q H 38s", opcode, 0, cid, nsid, b'\x00'*8, slba, nlb, b'\x00'*38)
    hdr = struct.pack("<BBBB I", PDU_CAPSULE_CMD, flags, hlen, pdo, plen) + sqe
    pkt = bytearray(hdr)
    if hdgst:
        c = crc32c(bytes(hdr))
        if corrupt_hd: c ^= 0xDEADBEEF
        pkt.extend(struct.pack("<I", c))
    if len(in_capsule_data) > 0:
        pkt.extend(in_capsule_data)
        if ddgst:
            c = crc32c(in_capsule_data)
            if corrupt_dd: c ^= 0xDEADBEEF
            pkt.extend(struct.pack("<I", c))
    return bytes(pkt)

def build_h2c_data(cid, ttag, offset, data, is_last=False, hdgst=False, ddgst=False, corrupt_hd=False, corrupt_dd=False):
    hlen = 24
    hd_len = 4 if hdgst else 0
    dd_len = 4 if ddgst else 0
    pdo = hlen + hd_len
    plen = hlen + hd_len + len(data) + dd_len

    flags = 0
    if hdgst: flags |= HDGST_FLAG
    if ddgst: flags |= DDGST_FLAG
    if is_last: flags |= DATA_LAST

    payload_hdr = struct.pack("<HH II 4s", cid, ttag, offset, len(data), b'\x00'*4)
    hdr = struct.pack("<BBBB I", PDU_H2C_DATA, flags, hlen, pdo, plen) + payload_hdr
    pkt = bytearray(hdr)
    if hdgst:
        c = crc32c(bytes(hdr))
        if corrupt_hd: c ^= 0xDEADBEEF
        pkt.extend(struct.pack("<I", c))
    pkt.extend(data)
    if ddgst:
        c = crc32c(data)
        if corrupt_dd: c ^= 0xDEADBEEF
        pkt.extend(struct.pack("<I", c))
    return bytes(pkt)

def run_simulation(input_data: dict) -> dict:
    config = input_data.get("config", {})
    initial_storage = input_data.get("initial_storage", {})
    operations = input_data.get("operations", [])
    dump_lbas = input_data.get("dump_lbas", None)

    target = NVMeTCPTarget(config, initial_storage)

    def feed_bytes(b: bytes, chunk_size: int = 0):
        if chunk_size <= 0:
            target.rx_stream.extend(b)
            target.process_rx_stream()
        else:
            for i in range(0, len(b), chunk_size):
                chunk = b[i:i+chunk_size]
                target.rx_stream.extend(chunk)
                target.process_rx_stream()
                if target.socket_state == "TERMINATED":
                    break

    for op_info in operations:
        if target.socket_state == "TERMINATED":
            break
        op = op_info.get("op")

        if op == "CONNECT":
            cid = op_info.get("cid", 1)
            chunk_size = op_info.get("chunk_size", 0)
            pkt = build_capsule_cmd(NVME_OPC_CONNECT, cid, 0, 0, 0, b"",
                                    hdgst=target.hdgst_enable,
                                    ddgst=target.ddgst_enable,
                                    corrupt_hd=op_info.get("corrupt_header_crc", False))
            feed_bytes(pkt, chunk_size)

        elif op == "WRITE":
            cid = op_info.get("cid", 1)
            slba = op_info.get("slba", 0)
            nlb = op_info.get("nlb", 0)
            data_hex = op_info.get("data_hex", "")
            data = bytes.fromhex(data_hex) if data_hex else b""
            in_capsule = op_info.get("in_capsule", True if len(data) <= target.ioccsz else False)
            chunk_size = op_info.get("chunk_size", 0)

            in_capsule_data = data if in_capsule else b""
            pkt = build_capsule_cmd(NVME_OPC_WRITE, cid, 1, slba, nlb, in_capsule_data,
                                    hdgst=target.hdgst_enable,
                                    ddgst=target.ddgst_enable,
                                    corrupt_hd=op_info.get("corrupt_header_crc", False),
                                    corrupt_dd=op_info.get("corrupt_data_crc", False))
            feed_bytes(pkt, chunk_size)

        elif op == "READ":
            cid = op_info.get("cid", 1)
            slba = op_info.get("slba", 0)
            nlb = op_info.get("nlb", 0)
            chunk_size = op_info.get("chunk_size", 0)
            pkt = build_capsule_cmd(NVME_OPC_READ, cid, 1, slba, nlb, b"",
                                    hdgst=target.hdgst_enable,
                                    ddgst=target.ddgst_enable,
                                    corrupt_hd=op_info.get("corrupt_header_crc", False))
            feed_bytes(pkt, chunk_size)

        elif op == "FLUSH":
            cid = op_info.get("cid", 1)
            chunk_size = op_info.get("chunk_size", 0)
            pkt = build_capsule_cmd(NVME_OPC_FLUSH, cid, 1, 0, 0, b"",
                                    hdgst=target.hdgst_enable,
                                    ddgst=target.ddgst_enable,
                                    corrupt_hd=op_info.get("corrupt_header_crc", False))
            feed_bytes(pkt, chunk_size)

        elif op == "H2C_DATA":
            cid = op_info.get("cid", 1)
            ttag = op_info.get("ttag", 1)
            offset = op_info.get("offset", 0)
            data_hex = op_info.get("data_hex", "")
            data = bytes.fromhex(data_hex) if data_hex else b""
            is_last = op_info.get("is_last", False)
            chunk_size = op_info.get("chunk_size", 0)
            pkt = build_h2c_data(cid, ttag, offset, data, is_last=is_last,
                                 hdgst=target.hdgst_enable,
                                 ddgst=target.ddgst_enable,
                                 corrupt_hd=op_info.get("corrupt_header_crc", False),
                                 corrupt_dd=op_info.get("corrupt_data_crc", False))
            feed_bytes(pkt, chunk_size)

        elif op == "AUTO_WRITE_STREAM":
            cid = op_info.get("cid", 1)
            slba = op_info.get("slba", 0)
            nlb = op_info.get("nlb", 0)
            data_hex = op_info.get("data_hex", "")
            data = bytes.fromhex(data_hex) if data_hex else b""
            chunk_size = op_info.get("chunk_size", 0)
            total_bytes = (nlb + 1) * target.block_size
            if len(data) < total_bytes:
                data = data.ljust(total_bytes, b'\x00')
            elif len(data) > total_bytes:
                data = data[:total_bytes]

            if len(data) <= target.ioccsz:
                pkt = build_capsule_cmd(NVME_OPC_WRITE, cid, 1, slba, nlb, data,
                                        hdgst=target.hdgst_enable,
                                        ddgst=target.ddgst_enable)
                feed_bytes(pkt, chunk_size)
            else:
                # Out of capsule: send command without data
                pkt = build_capsule_cmd(NVME_OPC_WRITE, cid, 1, slba, nlb, b"",
                                        hdgst=target.hdgst_enable,
                                        ddgst=target.ddgst_enable)
                feed_bytes(pkt, chunk_size)

                # Keep fulfilling R2Ts
                while cid in target.active_commands and target.socket_state != "TERMINATED":
                    # Look at latest R2T for this cid
                    pending_r2ts = [p for p in target.tx_pdus if p.get("pdu_type") == "R2T" and p.get("cid") == cid]
                    if not pending_r2ts:
                        break
                    latest_r2t = pending_r2ts[-1]
                    ttag = latest_r2t["ttag"]
                    offset = latest_r2t["r2t_offset"]
                    length = latest_r2t["r2t_length"]
                    chunk_data = data[offset : offset + length]
                    is_last = (offset + length >= len(data))

                    h2c_pkt = build_h2c_data(cid, ttag, offset, chunk_data, is_last=is_last,
                                             hdgst=target.hdgst_enable,
                                             ddgst=target.ddgst_enable)
                    feed_bytes(h2c_pkt, chunk_size)

        elif op == "INJECT_RAW_STREAM":
            stream_hex = op_info.get("stream_hex", "")
            data = bytes.fromhex(stream_hex) if stream_hex else b""
            chunk_size = op_info.get("chunk_size", 0)
            feed_bytes(data, chunk_size)

    storage_dump = {}
    if dump_lbas is not None:
        for lba in sorted(dump_lbas):
            if lba in target.storage:
                storage_dump[str(lba)] = bytes(target.storage[lba]).hex()
            else:
                storage_dump[str(lba)] = "00" * target.block_size
    else:
        for lba in sorted(target.storage.keys()):
            storage_dump[str(lba)] = bytes(target.storage[lba]).hex()

    return {
        "socket_state": target.socket_state,
        "stats": target.stats,
        "tx_pdus": target.tx_pdus,
        "storage_dump": storage_dump,
        "event_log": target.event_log
    }

if __name__ == "__main__":
    if sys.platform == "win32":
        try:
            sys.stdin.reconfigure(encoding="utf-8")
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    input_text = sys.stdin.read().strip()
    if not input_text:
        sys.exit(0)

    data = json.loads(input_text)
    result = run_simulation(data)
    print(json.dumps(result, ensure_ascii=False))
