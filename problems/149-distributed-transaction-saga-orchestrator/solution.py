import sys

def solve():
    lines = sys.stdin.read().splitlines()
    if not lines:
        return
    k = int(lines[0].strip())
    services = lines[1].strip().split()
    n = int(lines[2].strip())
    
    committed_sagas = 0
    compensated_sagas = 0
    total_compensations = 0
    total_messages = 0
    last_compensated_order = []
    
    for i in range(3, 3 + n):
        if i >= len(lines):
            break
        parts = lines[i].strip().split()
        if not parts:
            continue
        saga_id = parts[0]
        statuses = parts[1:]
        
        executed_steps = []
        failed = False
        
        for idx in range(min(k, len(statuses))):
            total_messages += 2 # forward command + reply
            s_name = services[idx]
            st = statuses[idx]
            if st == "SUCCESS":
                executed_steps.append(s_name)
            else:
                failed = True
                break
                
        if not failed and len(executed_steps) == k:
            committed_sagas += 1
        else:
            compensated_sagas += 1
            comp_order = list(reversed(executed_steps))
            for _ in comp_order:
                total_messages += 2 # compensate command + reply
                total_compensations += 1
            if comp_order:
                last_compensated_order = comp_order
            else:
                last_compensated_order = []
                
    last_str = ",".join(last_compensated_order) if last_compensated_order else "NONE"
    print(f"COMMITTED_SAGAS: {committed_sagas} COMPENSATED_SAGAS: {compensated_sagas} TOTAL_COMPENSATIONS: {total_compensations} TOTAL_MESSAGES: {total_messages}")
    print(f"LAST_COMPENSATED_ORDER: {last_str}")

if __name__ == '__main__':
    solve()
