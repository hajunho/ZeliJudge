import sys
import json
import math

class DualQRouter:
    def __init__(self, capacity=10, l_thresh=2, c_target=8, coupling_k=2.0, l_max_quota_ratio=0.8):
        self.capacity = capacity
        self.l_thresh = l_thresh
        self.c_target = c_target
        self.coupling_k = coupling_k
        self.l_max_quota_ratio = l_max_quota_ratio

        self.q_classic = []
        self.q_l4s = []

        self.p_classic = 0.0
        self.p_coupled = 0.0

        self.drops_classic = 0
        self.drops_l4s = 0
        self.marks_classic = 0
        self.marks_l4s = 0

    def enqueue(self, pkt):
        ecn = pkt.get("ecn", "Not-ECT")
        if ecn == "ECT(1)":
            if len(self.q_l4s) >= 100:
                self.drops_l4s += 1
                return False
            self.q_l4s.append(pkt)
            return True
        else:
            if len(self.q_classic) >= self.c_target * 3:
                self.drops_classic += 1
                return False
            self.q_classic.append(pkt)
            return True

    def step(self):
        qlen_c = len(self.q_classic)
        if qlen_c > self.c_target:
            self.p_classic = min(1.0, self.p_classic + 0.05 * ((qlen_c - self.c_target) / self.c_target))
        else:
            self.p_classic = max(0.0, self.p_classic * 0.85)

        self.p_coupled = min(1.0, self.coupling_k * math.sqrt(self.p_classic))

        drained = []
        budget = self.capacity
        l_quota = math.ceil(self.capacity * self.l_max_quota_ratio)

        # 1. Drain L4S queue up to quota
        while self.q_l4s and budget > 0 and l_quota > 0:
            pkt = self.q_l4s.pop(0)
            if len(self.q_l4s) >= self.l_thresh or self.p_coupled > 0.35:
                pkt["ecn"] = "CE"
                self.marks_l4s += 1
            drained.append(pkt)
            budget -= 1
            l_quota -= 1

        # 2. Drain Classic queue
        while self.q_classic and budget > 0:
            pkt = self.q_classic.pop(0)
            if self.p_classic > 0.12:
                if pkt["ecn"] == "ECT(0)":
                    pkt["ecn"] = "CE"
                    self.marks_classic += 1
                else:
                    self.drops_classic += 1
                    budget -= 1
                    continue
            drained.append(pkt)
            budget -= 1

        # 3. Drain remaining L4S if budget allows
        while self.q_l4s and budget > 0:
            pkt = self.q_l4s.pop(0)
            if len(self.q_l4s) >= self.l_thresh or self.p_coupled > 0.35:
                pkt["ecn"] = "CE"
                self.marks_l4s += 1
            drained.append(pkt)
            budget -= 1

        return drained

class Flow:
    def __init__(self, flow_id, flow_type="PRAGUE", initial_cwnd=10.0, ecn_type="ECT(1)", ewma_g=0.0625):
        self.flow_id = flow_id
        self.flow_type = flow_type
        self.cwnd = float(initial_cwnd)
        self.ecn_type = ecn_type
        self.ewma_g = ewma_g
        self.alpha = 0.0 if flow_type == "PRAGUE" else None
        self.delivered = 0
        self.drops = 0
        self.marks = 0

    def send(self):
        pkts = []
        count = math.floor(self.cwnd)
        for i in range(count):
            pkts.append({
                "id": f"{self.flow_id}-{self.delivered + i}",
                "flow": self.flow_id,
                "ecn": self.ecn_type
            })
        return pkts

    def on_feedback(self, acked, ce_marks, drops):
        self.delivered += acked
        self.marks += ce_marks
        self.drops += drops

        if self.flow_type == "CUBIC":
            if drops > 0 or ce_marks > 0:
                self.cwnd = max(2.0, self.cwnd * 0.7)
            else:
                self.cwnd += 1.0
        elif self.flow_type == "PRAGUE":
            if acked > 0:
                f = ce_marks / acked
                self.alpha = (1.0 - self.ewma_g) * self.alpha + self.ewma_g * f
                if f > 0:
                    decrease = 1.0 - (self.alpha / 2.0)
                    self.cwnd = max(2.0, self.cwnd * decrease)
                else:
                    self.cwnd += 1.0

def main():
    raw = sys.stdin.read()
    if not raw.strip():
        return

    data = json.loads(raw)
    config = data.get("config", {})
    cap = config.get("capacity_pkts_per_slot", 10)
    l_thresh = config.get("l_thresh_pkts", 2)
    c_target = config.get("c_target_pkts", 8)
    coupling_k = config.get("coupling_k", 2.0)
    l_quota_ratio = config.get("l_max_quota_ratio", 0.8)
    slots = config.get("duration_slots", 10)

    router = DualQRouter(cap, l_thresh, c_target, coupling_k, l_quota_ratio)

    flow_configs = data.get("flows", [])
    flows = {}
    for fc in flow_configs:
        fid = fc["id"]
        flows[fid] = Flow(
            flow_id=fid,
            flow_type=fc.get("type", "PRAGUE"),
            initial_cwnd=fc.get("initial_cwnd", 10.0),
            ecn_type=fc.get("ecn_type", "ECT(1)" if fc.get("type") == "PRAGUE" else "ECT(0)"),
            ewma_g=fc.get("ewma_g", 0.0625)
        )

    slot_history = []
    qlen_c_history = []
    qlen_l_history = []

    for s in range(slots):
        for f in flows.values():
            pkts = f.send()
            for p in pkts:
                router.enqueue(p)

        drained = router.step()

        qlen_c_history.append(len(router.q_classic))
        qlen_l_history.append(len(router.q_l4s))

        slot_flow_status = {}
        for fid, f in flows.items():
            f_drained = [p for p in drained if p["flow"] == fid]
            ce_count = sum(1 for p in f_drained if p["ecn"] == "CE")
            f.on_feedback(len(f_drained), ce_count, 0)
            slot_flow_status[fid] = {
                "cwnd": round(f.cwnd, 2),
                "delivered": f.delivered,
                "alpha": round(f.alpha, 4) if f.alpha is not None else None
            }

        slot_history.append({
            "slot": s,
            "qlen_classic": len(router.q_classic),
            "qlen_l4s": len(router.q_l4s),
            "drained_total": len(drained),
            "flows": slot_flow_status
        })

    mean_q_c = round(sum(qlen_c_history) / len(qlen_c_history), 2) if qlen_c_history else 0.0
    mean_q_l = round(sum(qlen_l_history) / len(qlen_l_history), 2) if qlen_l_history else 0.0
    delay_ratio = round(mean_q_c / max(mean_q_l, 0.01), 2)

    throughput_list = [f.delivered for f in flows.values()]
    sum_t = sum(throughput_list)
    sum_sq_t = sum(t ** 2 for t in throughput_list)
    n = len(throughput_list)
    jain_index = round((sum_t ** 2) / (n * sum_sq_t), 4) if sum_sq_t > 0 and n > 0 else 1.0

    delivered_map = {fid: f.delivered for fid, f in flows.items()}
    drops_map = {"classic": router.drops_classic, "l4s": router.drops_l4s}
    marks_map = {"classic": router.marks_classic, "l4s": router.marks_l4s}

    output = {
        "slots_simulated": slots,
        "history": slot_history,
        "summary": {
            "mean_qlen_classic": mean_q_c,
            "mean_qlen_l4s": mean_q_l,
            "l4s_latency_advantage_ratio": delay_ratio,
            "jains_fairness_index": jain_index,
            "delivered_per_flow": delivered_map,
            "drops": drops_map,
            "marks": marks_map
        }
    }
    print(json.dumps(output, ensure_ascii=False))

if __name__ == "__main__":
    main()
