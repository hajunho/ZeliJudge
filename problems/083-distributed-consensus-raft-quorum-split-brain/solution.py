import sys

class Node:
    def __init__(self, node_id: int):
        self.node_id = node_id
        self.role = "FOLLOWER"
        self.term = 1
        self.store = {}  # key -> value

class RaftCluster:
    def __init__(self, num_nodes: int):
        self.num_nodes = num_nodes
        self.quorum = num_nodes // 2 + 1
        self.current_term = 1
        self.nodes = {i: Node(i) for i in range(1, num_nodes + 1)}
        self.leader_id = 1
        self.nodes[1].role = "LEADER"
        self.partitions = [set(range(1, num_nodes + 1))]

    def _get_partition(self, node_id: int) -> set:
        for p in self.partitions:
            if node_id in p:
                return p
        return set()

    def write(self, node_id: int, key: str, value: str) -> str:
        if node_id not in self.nodes:
            return f"NODE_NOT_FOUND NODE={node_id}"

        if node_id != self.leader_id or self.nodes[node_id].role != "LEADER":
            lead_str = str(self.leader_id) if self.leader_id else "NONE"
            return f"REJECTED_NOT_LEADER CURRENT_LEADER={lead_str}"

        members = self._get_partition(node_id)
        group_size = len(members)

        if group_size < self.quorum:
            return f"REJECTED_NO_QUORUM (MEMBERS: {group_size}/{self.quorum})"

        for nid in members:
            self.nodes[nid].store[key] = value

        return f"COMMITTED KEY={key} VALUE={value} TERM={self.nodes[node_id].term} REPLICAS={group_size}"

    def elect(self, node_id: int) -> str:
        if node_id not in self.nodes:
            return f"NODE_NOT_FOUND NODE={node_id}"

        members = self._get_partition(node_id)
        group_size = len(members)

        if group_size < self.quorum:
            return f"ELECTION_FAILED NODE={node_id} (VOTES: {group_size}/{self.quorum})"

        self.current_term += 1
        if self.leader_id and self.leader_id in self.nodes:
            self.nodes[self.leader_id].role = "FOLLOWER"

        for nid in members:
            self.nodes[nid].term = self.current_term
            self.nodes[nid].role = "FOLLOWER"

        self.nodes[node_id].role = "LEADER"
        self.nodes[node_id].term = self.current_term
        self.leader_id = node_id
        return f"ELECTED NODE={node_id} TERM={self.current_term} (VOTES: {group_size}/{self.quorum})"

    def partition(self, groups_str: list) -> str:
        new_partitions = []
        for g in groups_str:
            p = set(int(x.strip()) for x in g.split(",") if x.strip())
            new_partitions.append(p)
        self.partitions = new_partitions
        formatted = [sorted(list(p)) for p in self.partitions]
        return f"PARTITIONED GROUPS={formatted}"

    def heal(self) -> str:
        self.partitions = [set(self.nodes.keys())]
        # Sync store from leader to all nodes
        if self.leader_id and self.leader_id in self.nodes:
            leader_term = self.nodes[self.leader_id].term
            leader_store = dict(self.nodes[self.leader_id].store)
            for nid, node in self.nodes.items():
                node.store = dict(leader_store)
                node.term = leader_term
                node.role = "LEADER" if nid == self.leader_id else "FOLLOWER"
            return f"NETWORK_HEALED LEADER={self.leader_id} TERM={leader_term}"
        else:
            return "NETWORK_HEALED LEADER=NONE"

    def read(self, node_id: int, key: str) -> str:
        if node_id not in self.nodes:
            return f"NODE_NOT_FOUND NODE={node_id}"
        val = self.nodes[node_id].store.get(key)
        if val is not None:
            return f"READ NODE={node_id} KEY={key} VALUE={val}"
        return f"READ NODE={node_id} KEY={key} VALUE=NONE"

    def get_status(self) -> str:
        lines = [
            f"TOTAL_NODES: {self.num_nodes}",
            f"QUORUM: {self.quorum}",
            f"TERM: {self.current_term}",
            f"LEADER: {self.leader_id if self.leader_id else 'NONE'}",
            f"PARTITIONS: {[sorted(list(p)) for p in self.partitions]}",
            "NODE_STATES:"
        ]
        for nid in sorted(self.nodes.keys()):
            node = self.nodes[nid]
            lines.append(f"  NODE {nid}: ROLE={node.role} TERM={node.term} COMMITTED_KEYS={len(node.store)}")
        return "\n".join(lines)

def run():
    input_data = sys.stdin.read().splitlines()
    cluster = None
    output = []

    for line in input_data:
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        parts = line.split()
        cmd = parts[0]

        if cmd == "INIT":
            n = int(parts[1])
            cluster = RaftCluster(n)
            output.append(f"INITIALIZED NODES={n} QUORUM={cluster.quorum} LEADER=1 TERM=1")

        elif cmd == "WRITE":
            nid = int(parts[1])
            key = parts[2]
            val = parts[3]
            res = cluster.write(nid, key, val)
            output.append(res)

        elif cmd == "ELECT":
            nid = int(parts[1])
            res = cluster.elect(nid)
            output.append(res)

        elif cmd == "PARTITION":
            groups_str = parts[1:]
            res = cluster.partition(groups_str)
            output.append(res)

        elif cmd == "HEAL":
            res = cluster.heal()
            output.append(res)

        elif cmd == "READ":
            nid = int(parts[1])
            key = parts[2]
            res = cluster.read(nid, key)
            output.append(res)

        elif cmd == "STATUS":
            output.append(cluster.get_status())

    print("\n".join(output))

if __name__ == "__main__":
    run()
