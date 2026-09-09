import sys

class NPlusOneSimulator:
    def __init__(self, network_rtt_ms, query_exec_ms):
        self.rtt_ms = network_rtt_ms
        self.query_ms = query_exec_ms
        self.per_query_ms = self.rtt_ms + self.query_ms

        self.users = {}      # id -> name
        self.posts = {}      # id -> {id, title, author_id}
        self.comments = {}   # id -> {id, post_id, commenter_id, content}

        # Naive Metrics
        self.naive_queries = 0
        self.naive_latency_ms = 0

        # DataLoader Metrics
        self.dataloader_queries = 0
        self.dataloader_latency_ms = 0

        self.total_fetch_requests = 0

    def insert_user(self, u_id, name):
        self.users[u_id] = name

    def insert_post(self, p_id, title, author_id):
        self.posts[p_id] = {"id": p_id, "title": title, "author_id": author_id}

    def insert_comment(self, c_id, post_id, commenter_id, content):
        self.comments[c_id] = {"id": c_id, "post_id": post_id, "commenter_id": commenter_id, "content": content}

    def fetch_posts_with_authors(self, post_ids):
        self.total_fetch_requests += 1

        # -------------------------------------------------------------
        # 1. Naive ORM Execution
        # -------------------------------------------------------------
        # Step 1: 1 query to fetch posts
        naive_q = 1
        fetched_posts = [self.posts[pid] for pid in post_ids if pid in self.posts]

        # Step 2: For each post, 1 query to fetch author (N queries)
        naive_result = []
        for p in fetched_posts:
            naive_q += 1  # SELECT * FROM users WHERE id = p.author_id
            author_name = self.users.get(p["author_id"], "UNKNOWN")
            naive_result.append(f"{p['id']}:{p['title']}({author_name})")

        naive_lat = naive_q * self.per_query_ms
        self.naive_queries += naive_q
        self.naive_latency_ms += naive_lat

        # -------------------------------------------------------------
        # 2. DataLoader Execution
        # -------------------------------------------------------------
        # Step 1: 1 query to fetch posts
        dl_q = 1
        # Step 2: Collect unique author_ids across posts (batching & deduplication)
        author_ids = list(dict.fromkeys([p["author_id"] for p in fetched_posts]))
        # 1 batch query to fetch all authors: SELECT * FROM users WHERE id IN (...)
        if author_ids:
            dl_q += 1

        user_cache = {aid: self.users.get(aid, "UNKNOWN") for aid in author_ids}
        dl_result = []
        for p in fetched_posts:
            dl_result.append(f"{p['id']}:{p['title']}({user_cache.get(p['author_id'], 'UNKNOWN')})")

        dl_lat = dl_q * self.per_query_ms
        self.dataloader_queries += dl_q
        self.dataloader_latency_ms += dl_lat

        is_match = (naive_result == dl_result)
        res_str = f"[{','.join(dl_result)}]" if dl_result else "[]"

        return naive_q, naive_lat, dl_q, dl_lat, len(author_ids), res_str, is_match

    def fetch_post_details_with_comments(self, post_id):
        self.total_fetch_requests += 1

        # -------------------------------------------------------------
        # 1. Naive ORM Execution
        # -------------------------------------------------------------
        # Query 1: Post
        naive_q = 1
        p = self.posts.get(post_id)
        if not p:
            # Post not found
            return 1, self.per_query_ms, 1, self.per_query_ms, 0, "NOT_FOUND", True

        # Query 2: Post Author
        naive_q += 1
        author_name = self.users.get(p["author_id"], "UNKNOWN")

        # Query 3: Comments for post
        naive_q += 1
        post_comments = [c for c in self.comments.values() if c["post_id"] == post_id]
        post_comments.sort(key=lambda c: c["id"])

        # Query 4..3+M: Comment author for each comment (M queries)
        c_entries_naive = []
        for c in post_comments:
            naive_q += 1  # SELECT * FROM users WHERE id = c.commenter_id
            c_author = self.users.get(c["commenter_id"], "UNKNOWN")
            c_entries_naive.append(f"{c['id']}:{c_author}:{c['content']}")

        naive_lat = naive_q * self.per_query_ms
        self.naive_queries += naive_q
        self.naive_latency_ms += naive_lat

        # -------------------------------------------------------------
        # 2. DataLoader Execution
        # -------------------------------------------------------------
        # Query 1: Post
        dl_q = 1
        # Query 2: Comments
        dl_q += 1

        # Query 3: Batch load all unique users (post author + all comment authors)
        needed_users = [p["author_id"]] + [c["commenter_id"] for c in post_comments]
        unique_users = list(dict.fromkeys(needed_users))
        if unique_users:
            dl_q += 1  # SELECT * FROM users WHERE id IN (...)

        user_cache = {uid: self.users.get(uid, "UNKNOWN") for uid in unique_users}
        c_entries_dl = [f"{c['id']}:{user_cache.get(c['commenter_id'], 'UNKNOWN')}:{c['content']}" for c in post_comments]

        dl_lat = dl_q * self.per_query_ms
        self.dataloader_queries += dl_q
        self.dataloader_latency_ms += dl_lat

        is_match = (c_entries_naive == c_entries_dl)
        res_str = f"POST:{p['id']}({author_name}) COMMENTS:[{','.join(c_entries_dl)}]"

        return naive_q, naive_lat, dl_q, dl_lat, len(unique_users), res_str, is_match


def solve():
    input_data = sys.stdin.read().splitlines()
    if not input_data:
        return

    mode = "CONFIG"
    rtt_ms = 5
    query_ms = 1
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
            if parts[0] == "NETWORK_RTT_MS":
                rtt_ms = int(parts[1])
            elif parts[0] == "QUERY_EXEC_MS":
                query_ms = int(parts[1])
        elif mode == "ACTIONS":
            actions.append(parts)

    sim = NPlusOneSimulator(rtt_ms, query_ms)
    out_lines = []
    all_matched = True

    for act_idx, act in enumerate(actions, 1):
        cmd = act[0]

        if cmd == "INSERT_USER":
            u_id = int(act[1])
            name = act[2]
            sim.insert_user(u_id, name)
            out_lines.append(f"ACT {act_idx} INSERT_USER ID:{u_id} NAME:{name}")

        elif cmd == "INSERT_POST":
            p_id = int(act[1])
            title = act[2]
            author_id = int(act[3])
            sim.insert_post(p_id, title, author_id)
            out_lines.append(f"ACT {act_idx} INSERT_POST ID:{p_id} TITLE:{title} AUTHOR_ID:{author_id}")

        elif cmd == "INSERT_COMMENT":
            c_id = int(act[1])
            post_id = int(act[2])
            commenter_id = int(act[3])
            content = act[4]
            sim.insert_comment(c_id, post_id, commenter_id, content)
            out_lines.append(f"ACT {act_idx} INSERT_COMMENT ID:{c_id} POST_ID:{post_id} COMMENTER_ID:{commenter_id}")

        elif cmd == "FETCH_POSTS_WITH_AUTHORS":
            pids = [int(x) for x in act[1].split(",") if x] if len(act) > 1 and act[1] != "EMPTY" else []
            nq, nlat, dq, dlat, u_cnt, res, match = sim.fetch_posts_with_authors(pids)
            if not match:
                all_matched = False
            out_lines.append(f"ACT {act_idx} FETCH_POSTS_WITH_AUTHORS COUNT:{len(pids)}")
            out_lines.append(f"  NAIVE: QUERIES:{nq} LATENCY:{nlat}ms DATA:{res}")
            out_lines.append(f"  DATALOADER: QUERIES:{dq} (BATCH_KEYS:{u_cnt}) LATENCY:{dlat}ms MATCH:{str(match).upper()}")

        elif cmd == "FETCH_POST_DETAILS_WITH_COMMENTS":
            pid = int(act[1])
            nq, nlat, dq, dlat, u_cnt, res, match = sim.fetch_post_details_with_comments(pid)
            if not match:
                all_matched = False
            out_lines.append(f"ACT {act_idx} FETCH_POST_DETAILS_WITH_COMMENTS POST_ID:{pid}")
            out_lines.append(f"  NAIVE: QUERIES:{nq} LATENCY:{nlat}ms DATA:{res}")
            out_lines.append(f"  DATALOADER: QUERIES:{dq} (BATCH_KEYS:{u_cnt}) LATENCY:{dlat}ms MATCH:{str(match).upper()}")

        elif cmd == "CHECK_METRICS":
            out_lines.append(f"ACT {act_idx} CHECK_METRICS")
            out_lines.append(f"  NAIVE: TOTAL_QUERIES:{sim.naive_queries} TOTAL_LATENCY:{sim.naive_latency_ms}ms")
            out_lines.append(f"  DATALOADER: TOTAL_QUERIES:{sim.dataloader_queries} TOTAL_LATENCY:{sim.dataloader_latency_ms}ms")

    saved_q = sim.naive_queries - sim.dataloader_queries
    q_red = (saved_q / sim.naive_queries * 100.0) if sim.naive_queries > 0 else 0.0
    saved_lat = sim.naive_latency_ms - sim.dataloader_latency_ms
    lat_red = (saved_lat / sim.naive_latency_ms * 100.0) if sim.naive_latency_ms > 0 else 0.0

    out_lines.append(f"SUMMARY TOTAL_FETCH_REQUESTS:{sim.total_fetch_requests}")
    out_lines.append(f"SUMMARY NAIVE TOTAL_QUERIES:{sim.naive_queries} TOTAL_LATENCY:{sim.naive_latency_ms}ms")
    out_lines.append(f"SUMMARY DATALOADER TOTAL_QUERIES:{sim.dataloader_queries} TOTAL_LATENCY:{sim.dataloader_latency_ms}ms")
    out_lines.append(f"SUMMARY QUERIES_SAVED:{saved_q} (QUERY_REDUCTION:{q_red:.2f}%)")
    out_lines.append(f"SUMMARY LATENCY_SAVED:{saved_lat}ms (LATENCY_REDUCTION:{lat_red:.2f}%)")
    out_lines.append("SUMMARY DATA_CONSISTENCY: 100%_MATCH" if all_matched else "SUMMARY DATA_CONSISTENCY: MISMATCH_DETECTED")
    out_lines.append("SUMMARY ORM_VERDICT: DATALOADER_ELIMINATES_N_PLUS_ONE")

    print("\n".join(out_lines))

if __name__ == "__main__":
    solve()
