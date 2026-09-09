import sys

class Resource:
    def __init__(self, resource_id, value):
        self.resource_id = resource_id
        self.value = value
        self.max_fencing_token = 0

class Lock:
    def __init__(self, resource_id, holder, token, expire_at):
        self.resource_id = resource_id
        self.holder = holder
        self.token = token
        self.expire_at = expire_at

class DistributedSystem:
    def __init__(self):
        self.resources = {}      # resource_id -> Resource
        self.locks = {}          # resource_id -> Lock
        self.default_ttl = 5000  # 5000ms
        self.current_time = 0
        self.global_token_counter = 0

    def init_resource(self, resource_id, value):
        self.resources[resource_id] = Resource(resource_id, value)
        return f"INIT_RESOURCE_OK resource={resource_id} value={value} initial_token=0"

    def config_lock_server(self, default_ttl_ms):
        self.default_ttl = int(default_ttl_ms)
        return f"CONFIG_LOCK_SERVER_OK default_ttl={self.default_ttl}ms"

    def tick(self, ms):
        self.current_time += int(ms)
        # Check expired locks
        for res_id, lock in list(self.locks.items()):
            if lock and lock.expire_at <= self.current_time:
                self.locks[res_id] = None
        return f"TICK_OK elapsed={ms}ms current_time={self.current_time}ms"

    def acquire_lock(self, client_id, resource_id, ttl_ms=None):
        ttl = int(ttl_ms) if ttl_ms else self.default_ttl
        curr_lock = self.locks.get(resource_id)

        # Check if currently held and not expired
        if curr_lock and curr_lock.expire_at > self.current_time:
            remaining = curr_lock.expire_at - self.current_time
            return f"LOCK_ACQUIRE_DENIED client={client_id} resource={resource_id} holder={curr_lock.holder} remaining_ttl={remaining}ms"

        # Lock is free or expired: grant lock
        self.global_token_counter += 1
        token = self.global_token_counter
        expire_at = self.current_time + ttl
        self.locks[resource_id] = Lock(resource_id, client_id, token, expire_at)
        return f"LOCK_ACQUIRED client={client_id} resource={resource_id} token={token} expire_at={expire_at}ms"

    def release_lock(self, client_id, resource_id):
        curr_lock = self.locks.get(resource_id)
        if not curr_lock or curr_lock.expire_at <= self.current_time:
            return f"ERROR:LOCK_NOT_HELD client={client_id} resource={resource_id}"
        if curr_lock.holder != client_id:
            return f"ERROR:NOT_LOCK_HOLDER client={client_id} holder={curr_lock.holder}"

        self.locks[resource_id] = None
        return f"LOCK_RELEASED client={client_id} resource={resource_id}"

    def unsafe_write(self, client_id, resource_id, new_value):
        if resource_id not in self.resources:
            return f"ERROR:UNKNOWN_RESOURCE resource={resource_id}"
        res = self.resources[resource_id]
        res.value = new_value
        return f"UNSAFE_WRITE_OK client={client_id} resource={resource_id} value={new_value}"

    def safe_write(self, client_id, resource_id, token_str, new_value):
        if resource_id not in self.resources:
            return f"ERROR:UNKNOWN_RESOURCE resource={resource_id}"
        res = self.resources[resource_id]
        token = int(token_str)

        # Fencing token check: token must be strictly greater than max_fencing_token
        if token <= res.max_fencing_token:
            return f"ERROR:FENCED_OUT client={client_id} token={token} storage_token={res.max_fencing_token} reason=TOKEN_STALE"

        res.value = new_value
        res.max_fencing_token = token
        return f"SAFE_WRITE_OK client={client_id} resource={resource_id} value={new_value} token={token}"

    def stats(self, resource_id):
        if resource_id not in self.resources:
            return f"ERROR:UNKNOWN_RESOURCE resource={resource_id}"
        res = self.resources[resource_id]
        curr_lock = self.locks.get(resource_id)
        if curr_lock and curr_lock.expire_at > self.current_time:
            holder = curr_lock.holder
            remaining = curr_lock.expire_at - self.current_time
        else:
            holder = "NONE"
            remaining = 0

        return (f"STATS resource={resource_id} value={res.value} "
                f"storage_max_token={res.max_fencing_token} lock_holder={holder} "
                f"remaining_ttl={remaining}ms global_token_counter={self.global_token_counter}")

def main():
    ds = DistributedSystem()
    lines = sys.stdin.read().splitlines()
    for line in lines:
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        parts = line.split()
        cmd = parts[0].upper()

        if cmd == "INIT_RESOURCE":
            print(ds.init_resource(parts[1], parts[2]))
        elif cmd == "CONFIG_LOCK_SERVER":
            print(ds.config_lock_server(parts[1]))
        elif cmd == "TICK":
            print(ds.tick(parts[1]))
        elif cmd == "ACQUIRE_LOCK":
            ttl = parts[3] if len(parts) > 3 else None
            print(ds.acquire_lock(parts[1], parts[2], ttl))
        elif cmd == "RELEASE_LOCK":
            print(ds.release_lock(parts[1], parts[2]))
        elif cmd == "UNSAFE_WRITE":
            print(ds.unsafe_write(parts[1], parts[2], parts[3]))
        elif cmd == "SAFE_WRITE":
            print(ds.safe_write(parts[1], parts[2], parts[3], parts[4]))
        elif cmd == "STATS":
            print(ds.stats(parts[1]))

if __name__ == '__main__':
    main()
