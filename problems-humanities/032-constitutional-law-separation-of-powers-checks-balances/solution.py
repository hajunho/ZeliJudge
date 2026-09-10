import sys
import json

def solve():
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    line = sys.stdin.read().strip()
    if not line:
        return
    req = json.loads(line)
    
    court_cfg = req.get("court_config", {})
    justice_count = court_cfg.get("justice_count", 9)
    unconstitutional_threshold = court_cfg.get("unconstitutional_threshold", 6)
    
    bills = {}
    enacted_laws = {}
    logs = []
    
    stats = {
        "bills_introduced": 0,
        "bills_enacted_signature": 0,
        "bills_enacted_override": 0,
        "vetoes_exercised": 0,
        "vetoes_sustained": 0,
        "filibusters_successful": 0,
        "judicial_reviews_conducted": 0,
        "laws_struck_down_entirely": 0,
        "laws_partially_severed": 0,
        "laws_upheld": 0
    }
    
    for op_item in req.get("operations", []):
        step = op_item["step"]
        op = op_item["op"]
        
        if op == "INTRODUCE_BILL":
            b_id = op_item["bill_id"]
            title = op_item["title"]
            articles = op_item["articles"]
            bills[b_id] = {
                "bill_id": b_id,
                "title": title,
                "articles": articles,
                "status": "INTRODUCED"
            }
            stats["bills_introduced"] += 1
            logs.append({"step": step, "op": op, "bill_id": b_id, "status": "INTRODUCED"})
            
        elif op == "LEGISLATIVE_VOTE":
            b_id = op_item["bill_id"]
            b = bills[b_id]
            
            h_votes = op_item["house_vote"]
            h_pass = h_votes["yeas"] > h_votes["nays"]
            
            s_data = op_item["senate_vote"]
            s_pass = False
            filibuster_killed = False
            
            if s_data.get("filibuster", False):
                cloture_yeas = s_data.get("cloture_yeas", 0)
                cloture_total = cloture_yeas + s_data.get("cloture_nays", 0)
                if cloture_total > 0 and (cloture_yeas / cloture_total) >= 0.60:
                    s_pass = s_data["yeas"] > s_data["nays"]
                else:
                    filibuster_killed = True
                    stats["filibusters_successful"] += 1
            else:
                s_pass = s_data["yeas"] > s_data["nays"]
                
            if filibuster_killed:
                b["status"] = "KILLED_BY_FILIBUSTER"
                logs.append({
                    "step": step,
                    "op": op,
                    "bill_id": b_id,
                    "house_pass": h_pass,
                    "senate_pass": False,
                    "filibuster_invoked": True,
                    "status": "KILLED_BY_FILIBUSTER"
                })
            elif h_pass and s_pass:
                b["status"] = "PASSED_LEGISLATURE"
                logs.append({
                    "step": step,
                    "op": op,
                    "bill_id": b_id,
                    "house_pass": True,
                    "senate_pass": True,
                    "status": "PASSED_LEGISLATURE"
                })
            else:
                b["status"] = "REJECTED_BY_LEGISLATURE"
                logs.append({
                    "step": step,
                    "op": op,
                    "bill_id": b_id,
                    "house_pass": h_pass,
                    "senate_pass": s_pass,
                    "status": "REJECTED_BY_LEGISLATURE"
                })
                
        elif op == "EXECUTIVE_ACTION":
            b_id = op_item["bill_id"]
            action = op_item["action"]
            b = bills[b_id]
            
            if action == "SIGN":
                b["status"] = "ENACTED_BY_SIGNATURE"
                enacted_laws[b_id] = {
                    "bill_id": b_id,
                    "title": b["title"],
                    "articles": [dict(a) for a in b["articles"]],
                    "status": "ENACTED"
                }
                stats["bills_enacted_signature"] += 1
                logs.append({"step": step, "op": op, "bill_id": b_id, "action": action, "status": "ENACTED_BY_SIGNATURE"})
            elif action == "VETO":
                b["status"] = "VETOED"
                stats["vetoes_exercised"] += 1
                logs.append({"step": step, "op": op, "bill_id": b_id, "action": action, "status": "VETOED"})
            elif action == "POCKET_VETO":
                b["status"] = "POCKET_VETOED"
                stats["vetoes_exercised"] += 1
                stats["vetoes_sustained"] += 1
                logs.append({"step": step, "op": op, "bill_id": b_id, "action": action, "status": "POCKET_VETOED"})
                
        elif op == "VETO_OVERRIDE_VOTE":
            b_id = op_item["bill_id"]
            b = bills[b_id]
            h_votes = op_item["house_override_vote"]
            s_votes = op_item["senate_override_vote"]
            
            h_tot = h_votes["yeas"] + h_votes["nays"]
            s_tot = s_votes["yeas"] + s_votes["nays"]
            
            h_override = (h_tot > 0 and (h_votes["yeas"] / h_tot) >= (2.0 / 3.0) - 1e-6)
            s_override = (s_tot > 0 and (s_votes["yeas"] / s_tot) >= (2.0 / 3.0) - 1e-6)
            
            if h_override and s_override:
                b["status"] = "ENACTED_BY_VETO_OVERRIDE"
                enacted_laws[b_id] = {
                    "bill_id": b_id,
                    "title": b["title"],
                    "articles": [dict(a) for a in b["articles"]],
                    "status": "ENACTED"
                }
                stats["bills_enacted_override"] += 1
                logs.append({
                    "step": step,
                    "op": op,
                    "bill_id": b_id,
                    "house_override": True,
                    "senate_override": True,
                    "status": "ENACTED_BY_VETO_OVERRIDE"
                })
            else:
                b["status"] = "VETO_SUSTAINED"
                stats["vetoes_sustained"] += 1
                logs.append({
                    "step": step,
                    "op": op,
                    "bill_id": b_id,
                    "house_override": h_override,
                    "senate_override": s_override,
                    "status": "VETO_SUSTAINED"
                })
                
        elif op == "JUDICIAL_REVIEW":
            law_id = op_item["law_id"]
            law = enacted_laws.get(law_id)
            stats["judicial_reviews_conducted"] += 1
            
            article_votes = op_item["article_votes"]
            
            unconst_articles = []
            has_essential_struck = False
            
            for art in law["articles"]:
                a_id = art["id"]
                u_votes = article_votes.get(str(a_id), article_votes.get(a_id, {})).get("unconstitutional_votes", 0)
                if u_votes >= unconstitutional_threshold:
                    unconst_articles.append(a_id)
                    if art.get("essential", False):
                        has_essential_struck = True
                        
            if not unconst_articles:
                verdict = "UPHELD_CONSTITUTIONAL"
                law["status"] = "ACTIVE_UPHELD"
                stats["laws_upheld"] += 1
                active_arts = [a["id"] for a in law["articles"]]
            elif has_essential_struck or len(unconst_articles) == len(law["articles"]):
                verdict = "STRUCK_DOWN_ENTIRELY"
                law["status"] = "NULL_AND_VOID"
                stats["laws_struck_down_entirely"] += 1
                active_arts = []
            else:
                verdict = "PARTIALLY_UPHELD_SEVERED"
                law["status"] = "ACTIVE_SEVERED"
                stats["laws_partially_severed"] += 1
                law["articles"] = [a for a in law["articles"] if a["id"] not in unconst_articles]
                active_arts = [a["id"] for a in law["articles"]]
                
            logs.append({
                "step": step,
                "op": op,
                "law_id": law_id,
                "verdict": verdict,
                "unconstitutional_article_ids": unconst_articles,
                "active_article_ids": active_arts,
                "status": verdict
            })
            
    active_laws = {}
    for lid, l in enacted_laws.items():
        if l["status"] in ["ACTIVE_UPHELD", "ACTIVE_SEVERED", "ENACTED"]:
            active_laws[lid] = {
                "title": l["title"],
                "active_articles": [a["id"] for a in l["articles"]]
            }
            
    res = {
        "operations_log": logs,
        "statistics": stats,
        "active_laws": active_laws
    }
    print(json.dumps(res, ensure_ascii=False))

if __name__ == "__main__":
    solve()
