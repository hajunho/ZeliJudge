import sys

class StockItem:
    def __init__(self, item_id, stock):
        self.item_id = item_id
        self.stock = stock
        self.version = 1

class LockBenchmarkSimulator:
    def __init__(self):
        self.items = {}

    def init_stock(self, item_id, stock):
        self.items[item_id] = StockItem(item_id, stock)
        return f"INIT_STOCK item={item_id} stock={stock} version=1"

    def benchmark_occ(self, item_id, threads, retry_limit):
        item = self.items[item_id]
        successes = 0
        conflicts = 0
        total_retries = 0
        aborts = 0
        db_queries = 0

        # active_threads: 각 스레드의 현재 retry_count 리스트
        active_threads = [0] * threads

        while active_threads and item.stock > 0:
            # 1. 모든 활성 스레드가 현재 상태를 SELECT (db_queries += len(active_threads))
            n = len(active_threads)
            db_queries += n
            current_version = item.version

            if item.stock <= 0:
                break

            # 2. 모든 활성 스레드가 UPDATE 시도 (db_queries += n)
            db_queries += n

            # 오직 1개 스레드만 성공
            item.stock -= 1
            item.version += 1
            successes += 1

            # 성공한 스레드 1개 제거 (첫 번째 스레드 성공 처리)
            active_threads.pop(0)

            # 나머지 실패한 스레드들은 충돌 및 재시도 처리
            new_active = []
            for r_count in active_threads:
                conflicts += 1
                total_retries += 1
                if r_count + 1 <= retry_limit:
                    new_active.append(r_count + 1)
                else:
                    aborts += 1
            active_threads = new_active

        # 재고 소진 후 남은 스레드들은 aborts 처리
        if active_threads:
            aborts += len(active_threads)
            active_threads.clear()

        return f"RESULT_OCC item={item_id} initial_threads={threads} successes={successes} conflicts={conflicts} total_retries={total_retries} aborts={aborts} db_queries={db_queries} final_stock={item.stock} final_version={item.version}"

    def benchmark_pcc(self, item_id, threads):
        item = self.items[item_id]
        successes = 0
        db_queries = 0
        lock_waits = max(0, threads - 1)

        for _ in range(threads):
            # SELECT FOR UPDATE (1 쿼리)
            db_queries += 1
            if item.stock > 0:
                # UPDATE (1 쿼리)
                db_queries += 1
                item.stock -= 1
                successes += 1
            else:
                # 재고 소진 확인 후 롤백/종료 (추가 UPDATE 없음)
                pass

        return f"RESULT_PCC item={item_id} initial_threads={threads} successes={successes} lock_waits={lock_waits} conflicts=0 retries=0 db_queries={db_queries} final_stock={item.stock}"

    def benchmark_dist_lock(self, item_id, threads, mode):
        item = self.items[item_id]
        if mode == "FAST_FAIL":
            # 1개만 Redis 락 획득 후 DB 접근, 나머지 즉시 거절 (DB 쿼리 없음)
            successes = 0
            db_queries = 0
            if item.stock > 0:
                db_queries += 2  # SELECT + UPDATE
                item.stock -= 1
                successes = 1
            fast_fail_rejected = threads - successes
            return f"RESULT_DIST_LOCK item={item_id} mode=FAST_FAIL successes={successes} fast_fail_rejected={fast_fail_rejected} db_queries={db_queries} final_stock={item.stock}"
        else: # WAIT_QUEUE
            successes = 0
            db_queries = 0
            redis_waits = max(0, threads - 1)
            for _ in range(threads):
                db_queries += 1
                if item.stock > 0:
                    db_queries += 1
                    item.stock -= 1
                    successes += 1
            return f"RESULT_DIST_LOCK item={item_id} mode=WAIT_QUEUE successes={successes} redis_waits={redis_waits} db_queries={db_queries} final_stock={item.stock}"

    def stats(self, item_id):
        item = self.items[item_id]
        return f"STATS item={item_id} stock={item.stock} version={item.version}"

def main():
    sim = LockBenchmarkSimulator()
    lines = sys.stdin.read().splitlines()
    for line in lines:
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        parts = line.split()
        cmd = parts[0]
        
        if cmd == "INIT_STOCK":
            item_id = parts[1]
            stock = int(parts[2])
            print(sim.init_stock(item_id, stock))
            
        elif cmd == "BENCHMARK_OCC":
            item_id = parts[1]
            threads = int(parts[2])
            retry_limit = int(parts[3])
            print(sim.benchmark_occ(item_id, threads, retry_limit))
            
        elif cmd == "BENCHMARK_PCC":
            item_id = parts[1]
            threads = int(parts[2])
            print(sim.benchmark_pcc(item_id, threads))
            
        elif cmd == "BENCHMARK_DIST_LOCK":
            item_id = parts[1]
            threads = int(parts[2])
            mode = parts[3]
            print(sim.benchmark_dist_lock(item_id, threads, mode))
            
        elif cmd == "STATS":
            item_id = parts[1]
            print(sim.stats(item_id))

if __name__ == "__main__":
    main()
