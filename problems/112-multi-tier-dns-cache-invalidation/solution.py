import sys

class MultiTierDNSResolver:
    def __init__(self):
        self.reset()

    def reset(self):
        # Authoritative
        self.auth_records = {}   # domain -> {"type": str, "value": str, "ttl": int}
        self.auth_soa = {}       # domain -> negative_ttl (default 30)
        self.default_soa_negative_ttl = 30

        # ISP Resolver
        self.isp_min_ttl_clamp = 0
        self.isp_cache = {}      # domain -> {"value": str, "remaining_ttl": int, "is_nxdomain": bool}

        # OS Resolver
        self.os_cache = {}       # domain -> {"value": str, "remaining_ttl": int, "is_nxdomain": bool}

        # App Resolver
        self.app_ttl = 30
        self.app_negative_ttl = 10
        self.app_cache = {}      # domain -> {"value": str, "remaining_ttl": int, "is_nxdomain": bool}

    def set_auth_record(self, domain, rtype, value, ttl):
        self.auth_records[domain] = {
            "type": rtype.upper(),
            "value": value,
            "ttl": int(ttl)
        }
        return f"SET_AUTH_RECORD_OK domain={domain} value={value} ttl={ttl}"

    def del_auth_record(self, domain):
        if domain in self.auth_records:
            del self.auth_records[domain]
        return f"DEL_AUTH_RECORD_OK domain={domain}"

    def set_auth_soa(self, domain, negative_ttl):
        self.auth_soa[domain] = int(negative_ttl)
        return f"SET_AUTH_SOA_OK domain={domain} negative_ttl={negative_ttl}"

    def config_isp(self, min_ttl_clamp):
        self.isp_min_ttl_clamp = int(min_ttl_clamp)
        return f"CONFIG_ISP_OK min_ttl_clamp={self.isp_min_ttl_clamp}"

    def config_app(self, ttl, negative_ttl):
        self.app_ttl = int(ttl)
        self.app_negative_ttl = int(negative_ttl)
        return f"CONFIG_APP_OK ttl={self.app_ttl} negative_ttl={self.app_negative_ttl}"

    def flush_cache(self, target):
        target = target.upper()
        if target == "APP":
            self.app_cache.clear()
        elif target == "OS":
            self.os_cache.clear()
        elif target == "ISP":
            self.isp_cache.clear()
        elif target == "ALL":
            self.app_cache.clear()
            self.os_cache.clear()
            self.isp_cache.clear()
        return f"FLUSH_OK target={target}"

    def tick(self, seconds):
        seconds = int(seconds)
        for cache in (self.app_cache, self.os_cache, self.isp_cache):
            expired = []
            for dom, entry in cache.items():
                if entry["remaining_ttl"] == -1:
                    continue
                entry["remaining_ttl"] -= seconds
                if entry["remaining_ttl"] <= 0:
                    expired.append(dom)
            for dom in expired:
                del cache[dom]
        return f"TICK_OK elapsed={seconds}"

    def _populate_app_cache(self, domain, value, src_remaining_ttl, is_nxdomain):
        if is_nxdomain:
            if self.app_negative_ttl == -1:
                ttl_val = -1
            elif self.app_negative_ttl == 0:
                return
            else:
                ttl_val = self.app_negative_ttl if src_remaining_ttl == -1 else min(self.app_negative_ttl, src_remaining_ttl)
            self.app_cache[domain] = {"value": "NXDOMAIN", "remaining_ttl": ttl_val, "is_nxdomain": True}
        else:
            if self.app_ttl == -1:
                ttl_val = -1
            elif self.app_ttl == 0:
                return
            else:
                ttl_val = self.app_ttl if src_remaining_ttl == -1 else min(self.app_ttl, src_remaining_ttl)
            self.app_cache[domain] = {"value": value, "remaining_ttl": ttl_val, "is_nxdomain": False}

    def resolve(self, domain):
        # 1. Check APP cache
        if domain in self.app_cache:
            entry = self.app_cache[domain]
            val = "NXDOMAIN" if entry["is_nxdomain"] else entry["value"]
            return f"RESOLVED {domain} {val} source=APP_CACHE ttl={entry['remaining_ttl']}"

        # 2. Check OS cache
        if domain in self.os_cache:
            entry = self.os_cache[domain]
            self._populate_app_cache(domain, entry["value"], entry["remaining_ttl"], entry["is_nxdomain"])
            val = "NXDOMAIN" if entry["is_nxdomain"] else entry["value"]
            return f"RESOLVED {domain} {val} source=OS_CACHE ttl={entry['remaining_ttl']}"

        # 3. Check ISP cache
        if domain in self.isp_cache:
            entry = self.isp_cache[domain]
            # Populate OS
            self.os_cache[domain] = {
                "value": entry["value"],
                "remaining_ttl": entry["remaining_ttl"],
                "is_nxdomain": entry["is_nxdomain"]
            }
            # Populate APP
            self._populate_app_cache(domain, entry["value"], entry["remaining_ttl"], entry["is_nxdomain"])
            val = "NXDOMAIN" if entry["is_nxdomain"] else entry["value"]
            return f"RESOLVED {domain} {val} source=ISP_CACHE ttl={entry['remaining_ttl']}"

        # 4. Query Authoritative
        if domain in self.auth_records:
            rec = self.auth_records[domain]
            auth_val = rec["value"]
            auth_ttl = rec["ttl"]

            isp_ttl = max(auth_ttl, self.isp_min_ttl_clamp)
            self.isp_cache[domain] = {
                "value": auth_val,
                "remaining_ttl": isp_ttl,
                "is_nxdomain": False
            }
            self.os_cache[domain] = {
                "value": auth_val,
                "remaining_ttl": isp_ttl,
                "is_nxdomain": False
            }
            self._populate_app_cache(domain, auth_val, isp_ttl, False)

            return f"RESOLVED {domain} {auth_val} source=AUTHORITATIVE ttl={auth_ttl}"
        else:
            neg_ttl = self.auth_soa.get(domain, self.default_soa_negative_ttl)
            self.isp_cache[domain] = {
                "value": "NXDOMAIN",
                "remaining_ttl": neg_ttl,
                "is_nxdomain": True
            }
            self.os_cache[domain] = {
                "value": "NXDOMAIN",
                "remaining_ttl": neg_ttl,
                "is_nxdomain": True
            }
            self._populate_app_cache(domain, "NXDOMAIN", neg_ttl, True)

            return f"RESOLVED {domain} NXDOMAIN source=AUTHORITATIVE_NXDOMAIN ttl={neg_ttl}"

    def status(self, domain):
        def format_entry(cache):
            if domain not in cache:
                return "MISS"
            e = cache[domain]
            if e["is_nxdomain"]:
                return f"NXDOMAIN (ttl={e['remaining_ttl']})"
            return f"{e['value']} (ttl={e['remaining_ttl']})"

        app_str = format_entry(self.app_cache)
        os_str = format_entry(self.os_cache)
        isp_str = format_entry(self.isp_cache)

        if domain in self.auth_records:
            rec = self.auth_records[domain]
            auth_str = f"{rec['value']} (ttl={rec['ttl']})"
        else:
            auth_str = "NXDOMAIN"

        lines = [
            f"--- DNS_STATUS {domain} ---",
            f"APP: {app_str}",
            f"OS: {os_str}",
            f"ISP: {isp_str}",
            f"AUTH: {auth_str}",
            "--- END_STATUS ---"
        ]
        return "\n".join(lines)


def parse_tokens(tokens):
    kv = {}
    positional = []
    for t in tokens:
        if "=" in t:
            k, v = t.split("=", 1)
            kv[k.strip().lower()] = v.strip()
        else:
            positional.append(t.strip())
    return kv, positional


def main():
    resolver = MultiTierDNSResolver()
    for line in sys.stdin:
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        parts = line.split()
        cmd = parts[0].upper()
        kv, pos = parse_tokens(parts[1:])

        if cmd == "SET_AUTH_RECORD":
            domain = kv.get("domain", pos[0] if len(pos) > 0 else "")
            rtype = kv.get("type", pos[1] if len(pos) > 1 else "A")
            value = kv.get("value", pos[2] if len(pos) > 2 else "")
            ttl = int(kv.get("ttl", pos[3] if len(pos) > 3 else 60))
            print(resolver.set_auth_record(domain, rtype, value, ttl))
        elif cmd == "DEL_AUTH_RECORD":
            domain = kv.get("domain", pos[0] if len(pos) > 0 else "")
            print(resolver.del_auth_record(domain))
        elif cmd == "SET_AUTH_SOA":
            domain = kv.get("domain", pos[0] if len(pos) > 0 else "")
            neg_ttl = int(kv.get("negative_ttl", pos[1] if len(pos) > 1 else 30))
            print(resolver.set_auth_soa(domain, neg_ttl))
        elif cmd == "CONFIG_ISP":
            min_clamp = int(kv.get("min_ttl_clamp", pos[0] if len(pos) > 0 else 0))
            print(resolver.config_isp(min_clamp))
        elif cmd == "CONFIG_APP":
            ttl = int(kv.get("ttl", pos[0] if len(pos) > 0 else 30))
            neg_ttl = int(kv.get("negative_ttl", pos[1] if len(pos) > 1 else 10))
            print(resolver.config_app(ttl, neg_ttl))
        elif cmd == "TICK":
            secs = int(kv.get("seconds", pos[0] if len(pos) > 0 else 1))
            print(resolver.tick(secs))
        elif cmd == "FLUSH_CACHE":
            target = kv.get("target", pos[0] if len(pos) > 0 else "ALL")
            print(resolver.flush_cache(target))
        elif cmd == "RESOLVE":
            domain = kv.get("domain", pos[0] if len(pos) > 0 else "")
            print(resolver.resolve(domain))
        elif cmd == "STATUS":
            domain = kv.get("domain", pos[0] if len(pos) > 0 else "")
            print(resolver.status(domain))
        elif cmd == "RESET":
            resolver.reset()
            print("RESET_OK")


if __name__ == "__main__":
    main()
