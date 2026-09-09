import sys

class RTRSystem:
    def __init__(self):
        self.families = {} # fid -> {'status': 'ACTIVE'/'REVOKED', 'active_rt': rt, 'used_rts': set(), 'active_ats': set()}
        self.access_granted = 0
        self.access_denied = 0
        self.refresh_success = 0
        self.breaches = 0

    def execute(self, line):
        parts = line.strip().split()
        if not parts:
            return
        cmd = parts[0]
        if cmd == 'LOGIN':
            user = parts[1]
            fid = parts[2]
            rt = parts[3]
            at = parts[4]
            self.families[fid] = {
                'status': 'ACTIVE',
                'active_rt': rt,
                'used_rts': set(),
                'active_ats': {at}
            }
        elif cmd == 'ACCESS':
            fid = parts[1]
            at = parts[2]
            if fid in self.families and self.families[fid]['status'] == 'ACTIVE' and at in self.families[fid]['active_ats']:
                self.access_granted += 1
            else:
                self.access_denied += 1
        elif cmd == 'REFRESH':
            fid = parts[1]
            provided_rt = parts[2]
            new_rt = parts[3]
            new_at = parts[4]
            if fid in self.families and self.families[fid]['status'] == 'ACTIVE':
                fam = self.families[fid]
                if provided_rt == fam['active_rt']:
                    fam['used_rts'].add(provided_rt)
                    fam['active_rt'] = new_rt
                    fam['active_ats'].add(new_at)
                    self.refresh_success += 1
                elif provided_rt in fam['used_rts']:
                    # Breach detected!
                    self.breaches += 1
                    fam['status'] = 'REVOKED'
                    fam['active_rt'] = None
                    fam['active_ats'].clear()
                else:
                    pass
            else:
                pass
        elif cmd == 'LOGOUT':
            fid = parts[1]
            if fid in self.families and self.families[fid]['status'] == 'ACTIVE':
                self.families[fid]['status'] = 'REVOKED'
                self.families[fid]['active_rt'] = None
                self.families[fid]['active_ats'].clear()

    def summary(self):
        revoked = sum(1 for f in self.families.values() if f['status'] == 'REVOKED')
        return f"ACCESS_GRANTED: {self.access_granted} ACCESS_DENIED: {self.access_denied} REFRESH_SUCCESS: {self.refresh_success} BREACHES: {self.breaches} REVOKED_FAMILIES: {revoked}"

def solve():
    input_data = sys.stdin.read().splitlines()
    if not input_data:
        return
    n = int(input_data[0].strip())
    sys_inst = RTRSystem()
    for i in range(1, n + 1):
        if i < len(input_data):
            sys_inst.execute(input_data[i])
    print(sys_inst.summary())

if __name__ == '__main__':
    solve()
