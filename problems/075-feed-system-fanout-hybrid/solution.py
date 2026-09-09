import sys

class FeedSimulator:
    def __init__(self, celebrity_threshold, feed_limit):
        self.celebrity_threshold = celebrity_threshold
        self.feed_limit = feed_limit

        self.global_post_seq = 0
        self.followers = {}  # user -> set of followers
        self.following = {}  # user -> set of followees
        self.follow_seq = {} # (follower, followee) -> seq when followed

        # Naive Engine Data
        self.naive_inbox = {}  # user -> list of post dicts (latest at end)
        self.naive_writes = 0
        self.naive_reads = 0

        # Hybrid Engine Data
        self.hybrid_inbox = {}   # user -> list of post dicts from normal followees
        self.hybrid_outbox = {}  # user -> list of post dicts authored by user
        self.hybrid_writes = 0
        self.hybrid_reads = 0

        self.total_posts = 0
        self.total_read_requests = 0

    def get_followers(self, user):
        if user not in self.followers:
            self.followers[user] = set()
        return self.followers[user]

    def get_following(self, user):
        if user not in self.following:
            self.following[user] = set()
        return self.following[user]

    def is_celebrity(self, user):
        return len(self.get_followers(user)) >= self.celebrity_threshold

    def follow(self, follower, followee):
        self.get_followers(followee).add(follower)
        self.get_following(follower).add(followee)
        self.follow_seq[(follower, followee)] = self.global_post_seq

    def post(self, author, post_id):
        self.global_post_seq += 1
        self.total_posts += 1
        post_obj = {
            "id": post_id,
            "author": author,
            "seq": self.global_post_seq
        }

        author_followers = self.get_followers(author)
        num_followers = len(author_followers)

        # 1. Naive Engine: Always push to all followers
        # Cost: 1 (author write) + num_followers (push to each follower inbox)
        naive_w = 1 + num_followers
        self.naive_writes += naive_w
        for f in author_followers:
            if f not in self.naive_inbox:
                self.naive_inbox[f] = []
            self.naive_inbox[f].append(post_obj)

        # 2. Hybrid Engine:
        if author not in self.hybrid_outbox:
            self.hybrid_outbox[author] = []
        self.hybrid_outbox[author].append(post_obj)

        is_celeb = self.is_celebrity(author)
        if is_celeb:
            # Celebrity: Only write to outbox, 0 pushes!
            hybrid_w = 1
            self.hybrid_writes += hybrid_w
            role_str = "CELEBRITY"
        else:
            # Normal: Push to all followers
            hybrid_w = 1 + num_followers
            self.hybrid_writes += hybrid_w
            role_str = "NORMAL"
            for f in author_followers:
                if f not in self.hybrid_inbox:
                    self.hybrid_inbox[f] = []
                self.hybrid_inbox[f].append(post_obj)

        return naive_w, self.naive_writes, role_str, hybrid_w, self.hybrid_writes

    def read_feed(self, user):
        self.total_read_requests += 1

        # 1. Naive Read: Just read own inbox
        self.naive_reads += 1
        naive_posts = self.naive_inbox.get(user, [])
        # Latest first
        naive_sorted = sorted(naive_posts, key=lambda p: p["seq"], reverse=True)
        naive_feed = [p["id"] for p in naive_sorted[:self.feed_limit]]
        naive_r_ops = 1

        # 2. Hybrid Read: Read own inbox + outbox of followed celebrities
        user_following = self.get_following(user)
        celeb_followees = [f for f in user_following if self.is_celebrity(f)]
        celeb_count = len(celeb_followees)

        hybrid_r_ops = 1 + celeb_count
        self.hybrid_reads += hybrid_r_ops

        # Collect candidate posts
        candidates = []
        # From own inbox (normal users)
        candidates.extend(self.hybrid_inbox.get(user, []))

        # From each followed celebrity's outbox (only posts created after following)
        for c in celeb_followees:
            c_f_seq = self.follow_seq.get((user, c), 0)
            c_posts = self.hybrid_outbox.get(c, [])
            for p in c_posts:
                if p["seq"] > c_f_seq:
                    candidates.append(p)

        hybrid_sorted = sorted(candidates, key=lambda p: p["seq"], reverse=True)
        hybrid_feed = [p["id"] for p in hybrid_sorted[:self.feed_limit]]

        is_match = (naive_feed == hybrid_feed)
        return naive_r_ops, naive_feed, hybrid_r_ops, celeb_count, hybrid_feed, is_match


def solve():
    input_data = sys.stdin.read().splitlines()
    if not input_data:
        return

    mode = "CONFIG"
    celeb_threshold = 5
    feed_limit = 10
    actions = []

    for line in input_data:
        line = line.strip()
        if not line:
            continue
        if line == "SYSTEM_CONFIG":
            mode = "CONFIG"
            continue
        elif line == "ACTIONS":
            mode = "ACTIONS"
            continue

        parts = line.split()
        if mode == "CONFIG":
            if parts[0] == "CELEBRITY_THRESHOLD":
                celeb_threshold = int(parts[1])
            elif parts[0] == "FEED_LIMIT":
                feed_limit = int(parts[1])
        elif mode == "ACTIONS":
            actions.append(parts)

    sim = FeedSimulator(celeb_threshold, feed_limit)
    out_lines = []
    all_matched = True

    for act_idx, act in enumerate(actions, 1):
        cmd = act[0]

        if cmd == "FOLLOW":
            follower = act[1]
            followee = act[2]
            sim.follow(follower, followee)
            f_count = len(sim.get_followers(followee))
            out_lines.append(f"ACT {act_idx} FOLLOW {follower} -> {followee} (FOLLOWEE_FOLLOWERS:{f_count})")

        elif cmd == "POST":
            author = act[1]
            post_id = act[2]
            nw, cum_nw, role, hw, cum_hw = sim.post(author, post_id)
            out_lines.append(f"ACT {act_idx} POST AUTHOR:{author} POST_ID:{post_id}")
            out_lines.append(f"  NAIVE: FANOUT_WRITES:{nw} CUMULATIVE_WRITES:{cum_nw}")
            out_lines.append(f"  HYBRID: ROLE:{role} FANOUT_WRITES:{hw} CUMULATIVE_WRITES:{cum_hw}")

        elif cmd == "READ_FEED":
            user = act[1]
            nr, n_feed, hr, c_cnt, h_feed, is_match = sim.read_feed(user)
            if not is_match:
                all_matched = False
            n_str = f"[{','.join(n_feed)}]" if n_feed else "[]"
            h_str = f"[{','.join(h_feed)}]" if h_feed else "[]"
            out_lines.append(f"ACT {act_idx} READ_FEED USER:{user}")
            out_lines.append(f"  NAIVE: READ_OPS:{nr} FEED:{n_str}")
            out_lines.append(f"  HYBRID: READ_OPS:{hr} (CELEB_SOURCES:{c_cnt}) FEED:{h_str} MATCH:{str(is_match).upper()}")

        elif cmd == "CHECK_METRICS":
            n_tot = sim.naive_writes + sim.naive_reads
            h_tot = sim.hybrid_writes + sim.hybrid_reads
            out_lines.append(f"ACT {act_idx} CHECK_METRICS")
            out_lines.append(f"  NAIVE: TOTAL_WRITES:{sim.naive_writes} TOTAL_READS:{sim.naive_reads} TOTAL_IO:{n_tot}")
            out_lines.append(f"  HYBRID: TOTAL_WRITES:{sim.hybrid_writes} TOTAL_READS:{sim.hybrid_reads} TOTAL_IO:{h_tot}")

    # Summary
    saved_writes = sim.naive_writes - sim.hybrid_writes
    write_reduction_pct = (saved_writes / sim.naive_writes * 100.0) if sim.naive_writes > 0 else 0.0
    n_tot_io = sim.naive_writes + sim.naive_reads
    h_tot_io = sim.hybrid_writes + sim.hybrid_reads

    out_lines.append(f"SUMMARY TOTAL_POSTS:{sim.total_posts} TOTAL_READS:{sim.total_read_requests}")
    out_lines.append(f"SUMMARY NAIVE TOTAL_WRITES:{sim.naive_writes} TOTAL_READS:{sim.naive_reads} TOTAL_IO:{n_tot_io}")
    out_lines.append(f"SUMMARY HYBRID TOTAL_WRITES:{sim.hybrid_writes} TOTAL_READS:{sim.hybrid_reads} TOTAL_IO:{h_tot_io}")
    out_lines.append(f"SUMMARY WRITE_OPS_SAVED:{saved_writes} (WRITE_REDUCTION:{write_reduction_pct:.2f}%)")
    out_lines.append("SUMMARY FEED_CONSISTENCY: 100%_MATCH" if all_matched else "SUMMARY FEED_CONSISTENCY: MISMATCH_DETECTED")
    out_lines.append("SUMMARY ARCHITECTURE_VERDICT: HYBRID_FANOUT_ELIMINATES_CELEBRITY_BOTTLENECK")

    print("\n".join(out_lines))

if __name__ == "__main__":
    solve()
