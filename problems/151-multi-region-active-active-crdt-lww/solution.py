import sys

class MultiRegionSimulator:
    def __init__(self, regions):
        self.regions = regions
        self.drifts = {r: 0 for r in regions}
        self.lww = {r: {} for r in regions}
        self.hlc_reg = {r: {} for r in regions}
        self.hlc_clock = {r: [0, 0] for r in regions}
        self.pn = {r: {} for r in regions}
        self.orset = {r: {} for r in regions}
        self.true_history = {}  # key: (pt, val, reg, op_idx)
        self.op_counter = 0

    def set_drift(self, region, drift_ms):
        self.drifts[region] = int(drift_ms)

    def write_lww(self, pt, region, key, val):
        self.op_counter += 1
        pt = int(pt)
        wall_ts = pt + self.drifts[region]
        curr = self.lww[region].get(key)
        new_entry = (val, wall_ts, region)
        if curr is None:
            self.lww[region][key] = new_entry
        else:
            _, cur_ts, cur_reg = curr
            if (wall_ts, region) > (cur_ts, cur_reg):
                self.lww[region][key] = new_entry

        if key not in self.true_history:
            self.true_history[key] = (pt, val, region, self.op_counter)
        else:
            prev_pt, _, _, prev_op = self.true_history[key]
            if (pt, self.op_counter) >= (prev_pt, prev_op):
                self.true_history[key] = (pt, val, region, self.op_counter)

    def write_hlc(self, pt, region, key, val):
        pt = int(pt)
        phys = pt + self.drifts[region]
        l, c = self.hlc_clock[region]
        l_prime = l
        new_l = max(l_prime, phys)
        if new_l == l_prime:
            new_c = c + 1
        else:
            new_c = 0
        self.hlc_clock[region] = [new_l, new_c]

        curr = self.hlc_reg[region].get(key)
        new_entry = (val, new_l, new_c, region)
        if curr is None:
            self.hlc_reg[region][key] = new_entry
        else:
            _, cur_l, cur_c, cur_r = curr
            if (new_l, new_c, region) > (cur_l, cur_c, cur_r):
                self.hlc_reg[region][key] = new_entry

    def pn_inc(self, region, counter, delta):
        delta = int(delta)
        if counter not in self.pn[region]:
            self.pn[region][counter] = {'P': {r: 0 for r in self.regions}, 'N': {r: 0 for r in self.regions}}
        self.pn[region][counter]['P'][region] += delta

    def pn_dec(self, region, counter, delta):
        delta = int(delta)
        if counter not in self.pn[region]:
            self.pn[region][counter] = {'P': {r: 0 for r in self.regions}, 'N': {r: 0 for r in self.regions}}
        self.pn[region][counter]['N'][region] += delta

    def orset_add(self, region, set_name, item, tag):
        if set_name not in self.orset[region]:
            self.orset[region][set_name] = {'add': set(), 'rem': set()}
        self.orset[region][set_name]['add'].add((item, tag))

    def orset_rem(self, region, set_name, item):
        if set_name not in self.orset[region]:
            self.orset[region][set_name] = {'add': set(), 'rem': set()}
        for (i, t) in self.orset[region][set_name]['add']:
            if i == item:
                self.orset[region][set_name]['rem'].add(t)

    def replicate(self, pt, src, dst):
        pt = int(pt)
        # 1. Merge LWW
        for k, v_tuple in self.lww[src].items():
            s_val, s_ts, s_reg = v_tuple
            if k not in self.lww[dst]:
                self.lww[dst][k] = v_tuple
            else:
                d_val, d_ts, d_reg = self.lww[dst][k]
                if (s_ts, s_reg) > (d_ts, d_reg):
                    self.lww[dst][k] = v_tuple

        # 2. Merge HLC clock & registers
        phys_dst = pt + self.drifts[dst]
        d_l, d_c = self.hlc_clock[dst]
        s_l, s_c = self.hlc_clock[src]
        l_prime = d_l
        new_l = max(l_prime, phys_dst, s_l)
        if new_l == l_prime and new_l == s_l:
            new_c = max(d_c, s_c) + 1
        elif new_l == l_prime:
            new_c = d_c + 1
        elif new_l == s_l:
            new_c = s_c + 1
        else:
            new_c = 0
        self.hlc_clock[dst] = [new_l, new_c]

        for k, v_tuple in self.hlc_reg[src].items():
            s_val, sl, sc, sr = v_tuple
            if k not in self.hlc_reg[dst]:
                self.hlc_reg[dst][k] = v_tuple
            else:
                d_val, dl, dc, dr = self.hlc_reg[dst][k]
                if (sl, sc, sr) > (dl, dc, dr):
                    self.hlc_reg[dst][k] = v_tuple

        # 3. Merge PN-Counters
        for c_name, data in self.pn[src].items():
            if c_name not in self.pn[dst]:
                self.pn[dst][c_name] = {'P': {r: 0 for r in self.regions}, 'N': {r: 0 for r in self.regions}}
            for r in self.regions:
                self.pn[dst][c_name]['P'][r] = max(self.pn[dst][c_name]['P'][r], data['P'].get(r, 0))
                self.pn[dst][c_name]['N'][r] = max(self.pn[dst][c_name]['N'][r], data['N'].get(r, 0))

        # 4. Merge OR-Sets
        for s_name, data in self.orset[src].items():
            if s_name not in self.orset[dst]:
                self.orset[dst][s_name] = {'add': set(), 'rem': set()}
            self.orset[dst][s_name]['add'].update(data['add'])
            self.orset[dst][s_name]['rem'].update(data['rem'])

    def replicate_all(self, pt):
        pt = int(pt)
        for _ in range(2):
            for s in self.regions:
                for d in self.regions:
                    if s != d:
                        self.replicate(pt, s, d)

    def dump_region(self, region):
        out = []
        out.append(f"REGION: {region}")
        lww_items = sorted(self.lww[region].items())
        lww_str = ", ".join([f"{k}={v[0]}" for k, v in lww_items]) if lww_items else "EMPTY"
        out.append(f"  LWW: {lww_str}")

        hlc_items = sorted(self.hlc_reg[region].items())
        hlc_str = ", ".join([f"{k}={v[0]}" for k, v in hlc_items]) if hlc_items else "EMPTY"
        out.append(f"  HLC: {hlc_str}")

        pn_res = []
        for c_name in sorted(self.pn[region].keys()):
            p_val = sum(self.pn[region][c_name]['P'].values())
            n_val = sum(self.pn[region][c_name]['N'].values())
            pn_res.append(f"{c_name}={p_val - n_val}")
        pn_str = ", ".join(pn_res) if pn_res else "EMPTY"
        out.append(f"  PN_COUNTER: {pn_str}")

        orset_res = []
        for s_name in sorted(self.orset[region].keys()):
            data = self.orset[region][s_name]
            active_items = sorted(list(set(item for item, tag in data['add'] if tag not in data['rem'])))
            orset_res.append(f"{s_name}=[{','.join(active_items)}]")
        orset_str = ", ".join(orset_res) if orset_res else "EMPTY"
        out.append(f"  OR_SET: {orset_str}")
        return "\n".join(out)

    def audit(self):
        out = []
        out.append("=== AUDIT SUMMARY ===")
        first_r = self.regions[0]

        lww_converged = all(
            {k: v[0] for k, v in self.lww[r].items()} == {k: v[0] for k, v in self.lww[first_r].items()}
            for r in self.regions
        )
        out.append(f"LWW_STATUS: {'CONVERGED' if lww_converged else 'DIVERGED'}")

        lost_updates = []
        for k in sorted(self.true_history.keys()):
            true_pt, true_v, true_r, _ = self.true_history[k]
            val = self.lww[first_r].get(k, (None,))[0]
            if val != true_v:
                lost_updates.append(f"LOST_UPDATE on key '{k}': expected '{true_v}' (written at t={true_pt} by {true_r}) but got '{val}'")
        if lost_updates:
            for lu in lost_updates:
                out.append(f"  [ANOMALY] {lu}")
        else:
            out.append("  [LWW_ANOMALIES] NONE")

        hlc_converged = all(
            {k: v[0] for k, v in self.hlc_reg[r].items()} == {k: v[0] for k, v in self.hlc_reg[first_r].items()}
            for r in self.regions
        )
        out.append(f"HLC_STATUS: {'CONVERGED' if hlc_converged else 'DIVERGED'}")

        pn_vals = {}
        for r in self.regions:
            pn_vals[r] = {
                c: sum(self.pn[r][c]['P'].values()) - sum(self.pn[r][c]['N'].values())
                for c in self.pn[r]
            }
        pn_converged = all(pn_vals[r] == pn_vals[first_r] for r in self.regions)
        out.append(f"PN_STATUS: {'CONVERGED' if pn_converged else 'DIVERGED'}")

        orset_vals = {}
        for r in self.regions:
            orset_vals[r] = {
                s: sorted(list(set(item for item, tag in self.orset[r][s]['add'] if tag not in self.orset[r][s]['rem'])))
                for s in self.orset[r]
            }
        orset_converged = all(orset_vals[r] == orset_vals[first_r] for r in self.regions)
        out.append(f"ORSET_STATUS: {'CONVERGED' if orset_converged else 'DIVERGED'}")

        return "\n".join(out)

def solve():
    input_data = sys.stdin.read()
    lines = [line.strip() for line in input_data.strip().splitlines() if line.strip()]
    if not lines:
        return
    
    first_line = lines[0].split()
    if first_line[0] != "REGIONS":
        return
    regions = first_line[1:]
    sim = MultiRegionSimulator(regions)

    for line in lines[1:]:
        if line == "END":
            break
        parts = line.split()
        cmd = parts[0]

        if cmd == "DRIFT":
            sim.set_drift(parts[1], parts[2])
        elif cmd == "WRITE_LWW":
            sim.write_lww(parts[1], parts[2], parts[3], parts[4])
        elif cmd == "WRITE_HLC":
            sim.write_hlc(parts[1], parts[2], parts[3], parts[4])
        elif cmd == "PN_INC":
            sim.pn_inc(parts[1], parts[2], parts[3])
        elif cmd == "PN_DEC":
            sim.pn_dec(parts[1], parts[2], parts[3])
        elif cmd == "ORSET_ADD":
            sim.orset_add(parts[1], parts[2], parts[3], parts[4])
        elif cmd == "ORSET_REM":
            sim.orset_rem(parts[1], parts[2], parts[3])
        elif cmd == "REPLICATE":
            sim.replicate(parts[1], parts[2], parts[3])
        elif cmd == "REPLICATE_ALL":
            sim.replicate_all(parts[1])
        elif cmd == "QUERY":
            print(sim.dump_region(parts[1]))
        elif cmd == "AUDIT":
            print(sim.audit())

if __name__ == '__main__':
    solve()
