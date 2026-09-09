import sys

class DnsRecord:
    def __init__(self, ip, ttl_ms):
        self.ip = ip
        self.ttl_ms = ttl_ms

class DnsServer:
    def __init__(self):
        self.records = {}
        self.ip_status = {}  # ip -> bool (is_alive)

    def register(self, domain, ip, ttl_ms):
        self.records[domain] = DnsRecord(ip, ttl_ms)
        self.ip_status[ip] = True

    def failover(self, domain, new_ip):
        old_ip = self.records[domain].ip if domain in self.records else "NONE"
        if old_ip in self.ip_status:
            self.ip_status[old_ip] = False  # Old IP dies
        self.ip_status[new_ip] = True       # New IP is up
        if domain in self.records:
            self.records[domain].ip = new_ip
        else:
            self.records[domain] = DnsRecord(new_ip, 5000)
        return old_ip, new_ip

    def is_ip_alive(self, ip):
        return self.ip_status.get(ip, False)

class ClientDnsCacheEntry:
    def __init__(self, ip, expires_at_ms):
        self.ip = ip
        self.expires_at_ms = expires_at_ms

class Connection:
    def __init__(self, target_ip, created_at_ms):
        self.target_ip = target_ip
        self.created_at_ms = created_at_ms

class ClientRuntime:
    def __init__(self, client_id, dns_ttl_ms, conn_pool_lifetime_ms):
        self.client_id = client_id
        self.dns_ttl_ms = dns_ttl_ms
        self.conn_pool_lifetime_ms = conn_pool_lifetime_ms
        self.dns_cache = {}
        self.active_conn = None
        self.total_queries = 0
        self.success_count = 0
        self.fail_count = 0
        self.dns_resolves = 0
        self.dns_cache_hits = 0

    def restart(self):
        self.dns_cache = {}
        self.active_conn = None

    def resolve(self, domain, current_time_ms, dns_server):
        # 1. Check DNS cache
        if domain in self.dns_cache:
            entry = self.dns_cache[domain]
            if self.dns_ttl_ms == -1 or current_time_ms < entry.expires_at_ms:
                self.dns_cache_hits += 1
                return entry.ip, "DNS_HIT"

        # 2. Cache miss or expired
        self.dns_resolves += 1
        if domain not in dns_server.records:
            return "0.0.0.0", "DNS_NXDOMAIN"

        record = dns_server.records[domain]
        expires_at = float('inf') if self.dns_ttl_ms == -1 else current_time_ms + self.dns_ttl_ms
        self.dns_cache[domain] = ClientDnsCacheEntry(record.ip, expires_at)
        return record.ip, "DNS_RESOLVED"

    def query(self, domain, query_id, current_time_ms, dns_server):
        self.total_queries += 1

        # Check existing connection from pool
        if self.active_conn is not None:
            if self.conn_pool_lifetime_ms > 0:
                age = current_time_ms - self.active_conn.created_at_ms
                if age >= self.conn_pool_lifetime_ms:
                    self.active_conn = None
            else:
                self.active_conn = None

        if self.active_conn is not None:
            target_ip = self.active_conn.target_ip
            dns_status = "POOL_REUSED"
        else:
            target_ip, dns_status = self.resolve(domain, current_time_ms, dns_server)
            if self.conn_pool_lifetime_ms > 0:
                self.active_conn = Connection(target_ip, current_time_ms)

        # Test reachability
        if dns_server.is_ip_alive(target_ip):
            self.success_count += 1
            return f"QUERY_OK client={self.client_id} ip={target_ip} status=SUCCESS [{dns_status}]"
        else:
            self.fail_count += 1
            # Broken connection is destroyed
            self.active_conn = None
            return f"QUERY_FAIL client={self.client_id} ip={target_ip} status=CONNECTION_REFUSED [{dns_status}]"

    def stats(self, dns_server):
        total = self.total_queries
        success = self.success_count
        fail = self.fail_count
        resolves = self.dns_resolves
        hits = self.dns_cache_hits
        avail = (success / total * 100.0) if total > 0 else 100.0

        last_target_ip = "NONE"
        if self.dns_cache:
            last_target_ip = list(self.dns_cache.values())[-1].ip

        if last_target_ip != "NONE" and not dns_server.is_ip_alive(last_target_ip):
            if self.dns_ttl_ms == -1:
                health = "STALE_DNS_PINNED_OUTAGE"
            else:
                health = "DEGRADED"
        elif avail < 70.0:
            health = "DEGRADED"
        else:
            health = "HEALTHY"

        return f"STATS client={self.client_id} total={total} success={success} fail={fail} dns_resolves={resolves} hits={hits} avail={avail:.1f}% target_ip={last_target_ip} health={health}"

class SimulationRunner:
    def __init__(self):
        self.dns_server = DnsServer()
        self.clients = {}
        self.current_time_ms = 0

    def config_dns(self, domain, ip, ttl_ms):
        self.dns_server.register(domain, ip, ttl_ms)
        return f"DNS_CONFIG_OK domain={domain} ip={ip} ttl={ttl_ms}ms"

    def config_client(self, client_id, dns_ttl_ms, pool_lifetime_ms):
        self.clients[client_id] = ClientRuntime(client_id, dns_ttl_ms, pool_lifetime_ms)
        return f"CLIENT_CONFIG_OK id={client_id} dns_ttl={dns_ttl_ms} pool_lifetime={pool_lifetime_ms}ms"

    def query(self, client_id, domain, query_id):
        client = self.clients[client_id]
        return client.query(domain, query_id, self.current_time_ms, self.dns_server)

    def failover(self, domain, new_ip):
        old_ip, new_ip = self.dns_server.failover(domain, new_ip)
        return f"FAILOVER_TRIGGERED domain={domain} old_ip={old_ip} new_ip={new_ip}"

    def restart_client(self, client_id):
        if client_id in self.clients:
            self.clients[client_id].restart()
        return f"CLIENT_RESTARTED id={client_id}"

    def tick(self, delta_ms):
        self.current_time_ms += delta_ms
        return f"TICK_OK time={self.current_time_ms}ms"

    def stats(self, client_id):
        client = self.clients[client_id]
        return client.stats(self.dns_server)

def main():
    runner = SimulationRunner()
    lines = sys.stdin.read().splitlines()
    for line in lines:
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        parts = line.split()
        cmd = parts[0].upper()

        if cmd == "CONFIG_DNS":
            domain = parts[1]
            ip = parts[2]
            ttl = int(parts[3])
            print(runner.config_dns(domain, ip, ttl))
        elif cmd == "CONFIG_CLIENT":
            c_id = parts[1]
            dns_ttl = int(parts[2])
            pool_life = int(parts[3])
            print(runner.config_client(c_id, dns_ttl, pool_life))
        elif cmd == "QUERY":
            c_id = parts[1]
            domain = parts[2]
            q_id = parts[3]
            print(runner.query(c_id, domain, q_id))
        elif cmd == "FAILOVER":
            domain = parts[1]
            new_ip = parts[2]
            print(runner.failover(domain, new_ip))
        elif cmd == "RESTART_CLIENT":
            c_id = parts[1]
            print(runner.restart_client(c_id))
        elif cmd == "TICK":
            delta = int(parts[1])
            print(runner.tick(delta))
        elif cmd == "STATS":
            c_id = parts[1]
            print(runner.stats(c_id))

if __name__ == '__main__':
    main()
