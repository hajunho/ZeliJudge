import sys

class ThunderingHerdSimulator:
    def __init__(self, worker_count, mode):
        self.worker_count = worker_count
        self.mode = mode
        self.rr_index = 0
        
        # 통계
        self.total_connections = 0
        self.total_wakeups = 0
        self.successful_accepts = 0
        self.eagain_failures = 0
        self.wasted_wakeups = 0
        self.worker_accepted_counts = [0] * worker_count

    def connect(self, conn_id):
        self.total_connections += 1
        outputs = []
        
        if self.mode == "LEGACY_SHARED":
            # 모든 워커가 동시에 깨어남
            woken = self.worker_count
            self.total_wakeups += woken
            self.successful_accepts += 1
            eagain = woken - 1
            self.eagain_failures += eagain
            self.wasted_wakeups += eagain
            self.worker_accepted_counts[0] += 1
            outputs.append(f"CONNECT id={conn_id} mode=LEGACY_SHARED woken_workers={woken} accepted_by=0 eagain_count={eagain}")
            
        elif self.mode == "EPOLLEXCLUSIVE":
            # 정확히 1개 워커만 순차적으로 깨어남
            target = self.rr_index % self.worker_count
            self.rr_index += 1
            self.total_wakeups += 1
            self.successful_accepts += 1
            self.worker_accepted_counts[target] += 1
            outputs.append(f"CONNECT id={conn_id} mode=EPOLLEXCLUSIVE woken_workers=1 accepted_by={target} eagain_count=0")
            
        elif self.mode == "SO_REUSEPORT":
            # 커널 해시 분배 (결정론적 해시: conn_id 정수 또는 문자열 합)
            h = sum(ord(c) for c in conn_id)
            target = h % self.worker_count
            self.total_wakeups += 1
            self.successful_accepts += 1
            self.worker_accepted_counts[target] += 1
            outputs.append(f"CONNECT id={conn_id} mode=SO_REUSEPORT hash_target={target} woken_workers=1 accepted_by={target} eagain_count=0")
            
        return outputs

    def batch_connect(self, count, prefix):
        batch_wakeups = 0
        batch_accepts = 0
        batch_eagain = 0
        batch_wasted = 0
        
        for i in range(count):
            cid = f"{prefix}_{i}"
            self.total_connections += 1
            
            if self.mode == "LEGACY_SHARED":
                w = self.worker_count
                self.total_wakeups += w
                self.successful_accepts += 1
                ea = w - 1
                self.eagain_failures += ea
                self.wasted_wakeups += ea
                self.worker_accepted_counts[0] += 1
                
                batch_wakeups += w
                batch_accepts += 1
                batch_eagain += ea
                batch_wasted += ea
                
            elif self.mode == "EPOLLEXCLUSIVE":
                target = self.rr_index % self.worker_count
                self.rr_index += 1
                self.total_wakeups += 1
                self.successful_accepts += 1
                self.worker_accepted_counts[target] += 1
                
                batch_wakeups += 1
                batch_accepts += 1
                
            elif self.mode == "SO_REUSEPORT":
                h = sum(ord(c) for c in cid)
                target = h % self.worker_count
                self.total_wakeups += 1
                self.successful_accepts += 1
                self.worker_accepted_counts[target] += 1
                
                batch_wakeups += 1
                batch_accepts += 1
                
        return f"BATCH_RESULT count={count} batch_wakeups={batch_wakeups} batch_accepts={batch_accepts} batch_eagain={batch_eagain} batch_wasted={batch_wasted}"

    def stats(self):
        worker_dist = ",".join(f"w{i}:{cnt}" for i, cnt in enumerate(self.worker_accepted_counts))
        return f"STATS mode={self.mode} workers={self.worker_count} total_conn={self.total_connections} total_wakeups={self.total_wakeups} accepts={self.successful_accepts} eagain={self.eagain_failures} wasted_wakeups={self.wasted_wakeups} dist=[{worker_dist}]"

def main():
    sim = None
    lines = sys.stdin.read().splitlines()
    for line in lines:
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        parts = line.split()
        cmd = parts[0]
        
        if cmd == "INIT_SERVER":
            w = int(parts[1])
            m = parts[2]
            sim = ThunderingHerdSimulator(w, m)
            print(f"INIT_SERVER workers={w} mode={m}")
            
        elif cmd == "CONNECT":
            conn_id = parts[1]
            for out in sim.connect(conn_id):
                print(out)
                
        elif cmd == "BATCH_CONNECT":
            count = int(parts[1])
            prefix = parts[2]
            print(sim.batch_connect(count, prefix))
            
        elif cmd == "STATS":
            print(sim.stats())

if __name__ == "__main__":
    main()
