import sys
import json
import hashlib
import hmac

SUPPORTED_ALGS = {
    "hash": {
        "sha256": {"digest_len": 32, "key_required": False},
        "sha512": {"digest_len": 64, "key_required": False},
        "hmac(sha256)": {"digest_len": 32, "key_required": True}
    },
    "skcipher": {
        "cbc(aes)": {"valid_key_lens": [16, 24, 32], "iv_len": 16, "block_size": 16},
        "ctr(aes)": {"valid_key_lens": [16, 24, 32], "iv_len": 16, "block_size": 1}
    },
    "aead": {
        "gcm(aes)": {"valid_key_lens": [16, 24, 32], "iv_len": 12, "tag_len": 16}
    }
}

class AfAlgEngine:
    def __init__(self):
        self.listeners = {}
        self.conns = {}
        self.stats = {
            "sockets_bound": 0,
            "keys_configured": 0,
            "sessions_accepted": 0,
            "encrypt_ops": 0,
            "decrypt_ops": 0,
            "hash_ops": 0,
            "auth_failures": 0
        }

    def bind_socket(self, fd, salg_type, salg_name):
        if fd in self.listeners or fd in self.conns:
            return {"status": "EBADF_DUPLICATE_FD", "fd": fd}

        if salg_type not in SUPPORTED_ALGS or salg_name not in SUPPORTED_ALGS[salg_type]:
            return {"status": "ENOENT_NO_CIPHER", "type": salg_type, "name": salg_name}

        self.listeners[fd] = {
            "type": salg_type,
            "name": salg_name,
            "key": None
        }
        self.stats["sockets_bound"] += 1
        return {"status": "SOCKET_BOUND", "fd": fd, "type": salg_type, "name": salg_name}

    def set_key(self, fd, key_hex):
        if fd not in self.listeners:
            return {"status": "EBADF_NOT_LISTENER", "fd": fd}

        key_bytes = bytes.fromhex(key_hex)
        sock = self.listeners[fd]
        salg_type = sock["type"]
        salg_name = sock["name"]

        spec = SUPPORTED_ALGS[salg_type][salg_name]
        if "valid_key_lens" in spec:
            if len(key_bytes) not in spec["valid_key_lens"]:
                return {"status": "EINVAL_KEY_LEN", "len": len(key_bytes), "allowed": spec["valid_key_lens"]}

        sock["key"] = key_bytes
        self.stats["keys_configured"] += 1
        return {"status": "KEY_CONFIGURED", "fd": fd, "key_len": len(key_bytes)}

    def accept_session(self, listen_fd, conn_fd):
        if listen_fd not in self.listeners:
            return {"status": "EBADF_NOT_LISTENER", "fd": listen_fd}
        if conn_fd in self.listeners or conn_fd in self.conns:
            return {"status": "EBADF_DUPLICATE_FD", "fd": conn_fd}

        l_sock = self.listeners[listen_fd]
        spec = SUPPORTED_ALGS[l_sock["type"]][l_sock["name"]]
        if spec.get("key_required", False) or "valid_key_lens" in spec:
            if l_sock["key"] is None:
                return {"status": "ENOKEY_KEY_NOT_SET", "listen_fd": listen_fd}

        self.conns[conn_fd] = {
            "listen_fd": listen_fd,
            "type": l_sock["type"],
            "name": l_sock["name"],
            "key": l_sock["key"],
            "op": "ENCRYPT",
            "iv": b"",
            "assoclen": 0,
            "tag_len": spec.get("tag_len", 16),
            "data_buf": b""
        }
        self.stats["sessions_accepted"] += 1
        return {"status": "SESSION_ACCEPTED", "listen_fd": listen_fd, "conn_fd": conn_fd, "name": l_sock["name"]}

    def _simulated_stream_cipher(self, data, key, iv):
        keystream = hashlib.sha256(key + iv).digest()
        out = bytearray()
        for i, b in enumerate(data):
            out.append(b ^ keystream[i % len(keystream)])
        return bytes(out)

    def _simulated_aead_tag(self, key, iv, aad, ciphertext):
        h = hmac.new(key, iv + aad + ciphertext, hashlib.sha256)
        return h.digest()[:16]

    def send_msg(self, conn_fd, data_hex, op=None, iv_hex=None, assoclen=0):
        if conn_fd not in self.conns:
            return {"status": "EBADF_NOT_CONN", "fd": conn_fd}

        conn = self.conns[conn_fd]
        if op is not None:
            conn["op"] = op
        if iv_hex is not None:
            conn["iv"] = bytes.fromhex(iv_hex)
        conn["assoclen"] = assoclen
        conn["data_buf"] = bytes.fromhex(data_hex)

        return {
            "status": "MSG_BUFFERED",
            "conn_fd": conn_fd,
            "op": conn["op"],
            "data_len": len(conn["data_buf"]),
            "assoclen": conn["assoclen"]
        }

    def recv_msg(self, conn_fd):
        if conn_fd not in self.conns:
            return {"status": "EBADF_NOT_CONN", "fd": conn_fd}

        conn = self.conns[conn_fd]
        salg_type = conn["type"]
        salg_name = conn["name"]
        data = conn["data_buf"]

        if salg_type == "hash":
            self.stats["hash_ops"] += 1
            if salg_name == "sha256":
                digest = hashlib.sha256(data).digest()
            elif salg_name == "sha512":
                digest = hashlib.sha512(data).digest()
            elif salg_name == "hmac(sha256)":
                digest = hmac.new(conn["key"], data, hashlib.sha256).digest()
            conn["data_buf"] = b""
            return {
                "status": "DIGEST_GENERATED",
                "conn_fd": conn_fd,
                "name": salg_name,
                "digest_hex": digest.hex()
            }

        elif salg_type == "skcipher":
            key = conn["key"]
            iv = conn["iv"]
            if conn["op"] == "ENCRYPT":
                self.stats["encrypt_ops"] += 1
                res = self._simulated_stream_cipher(data, key, iv)
            else:
                self.stats["decrypt_ops"] += 1
                res = self._simulated_stream_cipher(data, key, iv)
            conn["data_buf"] = b""
            return {
                "status": "CIPHER_PROCESSED",
                "conn_fd": conn_fd,
                "op": conn["op"],
                "out_hex": res.hex()
            }

        elif salg_type == "aead":
            key = conn["key"]
            iv = conn["iv"]
            assoclen = conn["assoclen"]
            tag_len = conn["tag_len"]

            if conn["op"] == "ENCRYPT":
                self.stats["encrypt_ops"] += 1
                aad = data[:assoclen]
                plaintext = data[assoclen:]
                ciphertext = self._simulated_stream_cipher(plaintext, key, iv)
                tag = self._simulated_aead_tag(key, iv, aad, ciphertext)
                result = ciphertext + tag
                conn["data_buf"] = b""
                return {
                    "status": "AEAD_ENCRYPTED",
                    "conn_fd": conn_fd,
                    "ciphertext_len": len(ciphertext),
                    "tag_hex": tag.hex(),
                    "out_hex": result.hex()
                }
            else:
                self.stats["decrypt_ops"] += 1
                aad = data[:assoclen]
                payload = data[assoclen:]
                if len(payload) < tag_len:
                    self.stats["auth_failures"] += 1
                    return {"status": "EBADMSG_PAYLOAD_TOO_SHORT"}

                ciphertext = payload[:-tag_len]
                received_tag = payload[-tag_len:]
                expected_tag = self._simulated_aead_tag(key, iv, aad, ciphertext)

                if received_tag != expected_tag:
                    self.stats["auth_failures"] += 1
                    return {"status": "EBADMSG_AUTH_FAILED", "conn_fd": conn_fd}

                plaintext = self._simulated_stream_cipher(ciphertext, key, iv)
                conn["data_buf"] = b""
                return {
                    "status": "AEAD_DECRYPTED",
                    "conn_fd": conn_fd,
                    "plaintext_hex": plaintext.hex(),
                    "plaintext_str": plaintext.decode("utf-8", errors="replace")
                }

    def query_state(self):
        return {
            "active_listeners": len(self.listeners),
            "active_connections": len(self.conns),
            "stats": self.stats
        }

def main():
    if hasattr(sys.stdin, "reconfigure"):
        sys.stdin.reconfigure(encoding="utf-8")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    raw = sys.stdin.read()
    if not raw.strip():
        return
    input_data = json.loads(raw)

    engine = AfAlgEngine()
    results = []

    for op in input_data.get("operations", []):
        cmd = op.get("op")
        if cmd == "BIND_SOCKET":
            res = engine.bind_socket(op["fd"], op["salg_type"], op["salg_name"])
            results.append(res)
        elif cmd == "SET_KEY":
            res = engine.set_key(op["fd"], op["key_hex"])
            results.append(res)
        elif cmd == "ACCEPT_SESSION":
            res = engine.accept_session(op["listen_fd"], op["conn_fd"])
            results.append(res)
        elif cmd == "SEND_MSG":
            res = engine.send_msg(op["conn_fd"], op["data_hex"], op.get("cipher_op"), op.get("iv_hex"), op.get("assoclen", 0))
            results.append(res)
        elif cmd == "RECV_MSG":
            res = engine.recv_msg(op["conn_fd"])
            results.append(res)
        elif cmd == "QUERY_STATE":
            res = engine.query_state()
            results.append(res)

    out = {"results": results}
    print(json.dumps(out, separators=(',', ':'), ensure_ascii=False))

if __name__ == "__main__":
    main()
