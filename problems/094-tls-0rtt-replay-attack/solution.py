import sys

class SessionTicket:
    def __init__(self, ticket_id, user_id, issued_at):
        self.ticket_id = ticket_id
        self.user_id = user_id
        self.issued_at = issued_at
        self.is_used = False

class User:
    def __init__(self, user_id, balance):
        self.user_id = user_id
        self.balance = balance

class TlsServerSimulator:
    def __init__(self):
        self.max_ticket_age_window_ms = 5000
        self.anti_replay_mode = "NONE"  # NONE, SINGLE_USE, WINDOW_FILTER
        self.allow_non_idempotent = 0  # 0: reject with 425, 1: allow
        self.current_time_ms = 0
        self.tickets = {}
        self.users = {}
        self.seen_client_randoms = {}
        self.all_processed_randoms = set()
        self.total_0rtt_reqs = 0
        self.accepted_0rtt = 0
        self.rejected_0rtt = 0
        self.blocked_replays = 0
        self.replay_breaches = 0

    def config(self, window_ms, anti_replay_mode, allow_non_idempotent):
        self.max_ticket_age_window_ms = window_ms
        self.anti_replay_mode = anti_replay_mode
        self.allow_non_idempotent = allow_non_idempotent
        self.current_time_ms = 0
        self.tickets = {}
        self.users = {}
        self.seen_client_randoms = {}
        self.all_processed_randoms = set()
        self.total_0rtt_reqs = 0
        self.accepted_0rtt = 0
        self.rejected_0rtt = 0
        self.blocked_replays = 0
        self.replay_breaches = 0
        return f"CONFIG_OK window={window_ms} anti_replay={anti_replay_mode} allow_non_idempotent={allow_non_idempotent}"

    def issue_ticket(self, ticket_id, user_id, balance):
        if user_id not in self.users:
            self.users[user_id] = User(user_id, balance)
        else:
            self.users[user_id].balance = balance
        self.tickets[ticket_id] = SessionTicket(ticket_id, user_id, self.current_time_ms)
        return f"TICKET_ISSUED id={ticket_id} user={user_id} time={self.current_time_ms}ms"

    def req_0rtt(self, ticket_id, client_random, ticket_age_ms, method, path, amount=0):
        self.total_0rtt_reqs += 1

        # Check 1: Ticket existence
        if ticket_id not in self.tickets:
            self.rejected_0rtt += 1
            return "REJECT_EARLY_DATA reason=INVALID_TICKET"

        ticket = self.tickets[ticket_id]
        user = self.users[ticket.user_id]

        # Check 2: Ticket age skew
        elapsed_server = self.current_time_ms - ticket.issued_at
        skew = abs(elapsed_server - ticket_age_ms)
        if skew > self.max_ticket_age_window_ms:
            self.rejected_0rtt += 1
            return f"REJECT_EARLY_DATA reason=TICKET_AGE_SKEW_EXCEEDED skew={skew}ms"

        # Check 3: Anti-Replay mechanism
        if self.anti_replay_mode == "SINGLE_USE":
            if ticket.is_used:
                self.rejected_0rtt += 1
                self.blocked_replays += 1
                return "REJECT_EARLY_DATA reason=REPLAY_DETECTED_TICKET_REUSED"
        elif self.anti_replay_mode == "WINDOW_FILTER":
            if client_random in self.seen_client_randoms:
                self.rejected_0rtt += 1
                self.blocked_replays += 1
                return "REJECT_EARLY_DATA reason=REPLAY_DETECTED_NONCE_DUPLICATE"

        # Check 4: HTTP Idempotency (RFC 8446 & RFC 8470)
        is_safe = method.upper() in ("GET", "HEAD", "OPTIONS")
        if not is_safe and self.allow_non_idempotent == 0:
            self.rejected_0rtt += 1
            return "REJECT_EARLY_DATA status=425_TOO_EARLY fallback=1RTT_REQUIRED"

        # All checks passed: Accept Early Data
        if client_random in self.all_processed_randoms:
            # Replay attack succeeded because anti-replay defense was missing!
            self.replay_breaches += 1
        self.all_processed_randoms.add(client_random)

        # Update anti-replay records
        if self.anti_replay_mode == "SINGLE_USE":
            ticket.is_used = True
        elif self.anti_replay_mode == "WINDOW_FILTER":
            self.seen_client_randoms[client_random] = self.current_time_ms

        self.accepted_0rtt += 1
        if is_safe:
            return f"ACCEPT_EARLY_DATA status=200_OK result=BALANCE:{user.balance}"
        else:
            amount = int(amount)
            user.balance -= amount
            return f"ACCEPT_EARLY_DATA status=200_OK result=TRANSFERRED:{amount}_REMAINING:{user.balance}"

    def req_1rtt(self, user_id, method, path, amount=0):
        if user_id not in self.users:
            self.users[user_id] = User(user_id, 0)
        user = self.users[user_id]

        is_safe = method.upper() in ("GET", "HEAD", "OPTIONS")
        if is_safe:
            return f"HANDSHAKE_1RTT_OK status=200_OK result=BALANCE:{user.balance}"
        else:
            amount = int(amount)
            user.balance -= amount
            return f"HANDSHAKE_1RTT_OK status=200_OK result=TRANSFERRED:{amount}_REMAINING:{user.balance}"

    def tick(self, delta_ms):
        self.current_time_ms += delta_ms
        evicted = 0
        for cr, cached_time in list(self.seen_client_randoms.items()):
            if self.current_time_ms - cached_time > self.max_ticket_age_window_ms:
                del self.seen_client_randoms[cr]
                evicted += 1
        return f"TICK_OK time={self.current_time_ms}ms evicted_nonces={evicted}"

    def stats(self):
        if self.replay_breaches > 0:
            health = "COMPROMISED"
        elif self.anti_replay_mode == "NONE" or self.allow_non_idempotent == 1:
            health = "VULNERABLE"
        else:
            health = "SECURE"

        return f"STATS total_0rtt={self.total_0rtt_reqs} accepted={self.accepted_0rtt} rejected={self.rejected_0rtt} blocked_replays={self.blocked_replays} breaches={self.replay_breaches} health={health}"

def main():
    sim = TlsServerSimulator()
    lines = sys.stdin.read().splitlines()
    for line in lines:
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        parts = line.split()
        cmd = parts[0].upper()

        if cmd == "CONFIG":
            window_ms = int(parts[1])
            anti_replay = parts[2].upper()
            allow_non_idempotent = int(parts[3])
            print(sim.config(window_ms, anti_replay, allow_non_idempotent))
        elif cmd == "ISSUE_TICKET":
            ticket_id = parts[1]
            user_id = parts[2]
            balance = int(parts[3])
            print(sim.issue_ticket(ticket_id, user_id, balance))
        elif cmd == "REQ_0RTT":
            ticket_id = parts[1]
            client_rand = parts[2]
            ticket_age_ms = int(parts[3])
            method = parts[4]
            path = parts[5]
            amount = int(parts[6]) if len(parts) > 6 else 0
            print(sim.req_0rtt(ticket_id, client_rand, ticket_age_ms, method, path, amount))
        elif cmd == "REQ_1RTT":
            user_id = parts[1]
            method = parts[2]
            path = parts[3]
            amount = int(parts[4]) if len(parts) > 4 else 0
            print(sim.req_1rtt(user_id, method, path, amount))
        elif cmd == "TICK":
            delta_ms = int(parts[1])
            print(sim.tick(delta_ms))
        elif cmd == "STATS":
            print(sim.stats())

if __name__ == '__main__':
    main()
