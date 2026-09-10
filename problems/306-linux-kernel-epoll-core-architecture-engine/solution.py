# -*- coding: utf-8 -*-
"""
ZeliJudge Problem #306: 리눅스 커널 epoll(fs/eventpoll.c) 핵심 아키텍처 엔진
LT vs ET, EPOLLEXCLUSIVE Thundering Herd 방지, EPOLLONESHOT, ELOOP 순환 검증 시뮬레이션
"""
import sys
import json

if sys.platform == "win32":
    try:
        sys.stdin.reconfigure(encoding="utf-8")
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


def run_epoll_engine(data):
    config = data.get("config", {})
    global_max_events = config.get("max_events_per_wait", 32)

    fds = {f["fd"]: dict(f) for f in data.get("file_descriptors", [])}
    ops = data.get("operations", [])

    epolls = {}
    wait_results = []
    errors = []
    exclusive_cursor = {}

    def evaluate_fd_state(target_fd, events_interest):
        f = fds.get(target_fd, {})
        ready_events = []
        if "EPOLLIN" in events_interest and f.get("unread_bytes", 0) > 0:
            ready_events.append("EPOLLIN")
        if "EPOLLOUT" in events_interest and f.get("writable", False):
            ready_events.append("EPOLLOUT")
        if f.get("hup", False):
            ready_events.append("EPOLLHUP")
        return sorted(ready_events)

    def trigger_edge_or_level(target_fd, is_edge_event):
        non_exclusive = []
        exclusive = []

        for epfd in sorted(epolls.keys()):
            ep_inst = epolls[epfd]
            if target_fd in ep_inst["rbr"]:
                item = ep_inst["rbr"][target_fd]
                if not item["active"]:
                    continue
                ready_events = evaluate_fd_state(target_fd, item["events"])
                is_et = "EPOLLET" in item["events"]
                is_excl = "EPOLLEXCLUSIVE" in item["events"]

                if ready_events:
                    if is_et:
                        if is_edge_event:
                            if is_excl:
                                exclusive.append((epfd, ep_inst, item))
                            else:
                                non_exclusive.append((epfd, ep_inst, item))
                    else:
                        if is_excl:
                            exclusive.append((epfd, ep_inst, item))
                        else:
                            non_exclusive.append((epfd, ep_inst, item))
                else:
                    if not is_et:
                        if target_fd in ep_inst["rdllist"]:
                            ep_inst["rdllist"].remove(target_fd)
                            item["in_rdllist"] = False

        for epfd, ep_inst, item in non_exclusive:
            if target_fd not in ep_inst["rdllist"]:
                ep_inst["rdllist"].append(target_fd)
                item["in_rdllist"] = True

        if exclusive:
            idx = exclusive_cursor.get(target_fd, 0) % len(exclusive)
            epfd, ep_inst, item = exclusive[idx]
            exclusive_cursor[target_fd] = idx + 1
            if target_fd not in ep_inst["rdllist"]:
                ep_inst["rdllist"].append(target_fd)
                item["in_rdllist"] = True

    for op in ops:
        op_id = op["op_id"]
        op_type = op["type"]

        if op_type == "EPOLL_CREATE":
            epfd = op["epfd"]
            epolls[epfd] = {"rbr": {}, "rdllist": []}

        elif op_type == "EPOLL_CTL_ADD":
            epfd = op["epfd"]
            t_fd = op["target_fd"]
            ev_list = set(op.get("events", []))

            # Loop check
            if t_fd in epolls:
                visited = set([epfd])
                has_loop = False
                queue = [t_fd]
                while queue:
                    node = queue.pop(0)
                    if node == epfd:
                        has_loop = True
                        break
                    if node in epolls:
                        for child in epolls[node]["rbr"].keys():
                            if child in epolls and child not in visited:
                                visited.add(child)
                                queue.append(child)
                if has_loop:
                    errors.append({"op_id": op_id, "error": "ELOOP", "target_fd": t_fd})
                    continue

            epolls[epfd]["rbr"][t_fd] = {
                "events": ev_list,
                "active": True,
                "in_rdllist": False
            }
            ready = evaluate_fd_state(t_fd, ev_list)
            if ready:
                epolls[epfd]["rdllist"].append(t_fd)
                epolls[epfd]["rbr"][t_fd]["in_rdllist"] = True

        elif op_type == "EPOLL_CTL_MOD":
            epfd = op["epfd"]
            t_fd = op["target_fd"]
            ev_list = set(op.get("events", []))
            if epfd in epolls and t_fd in epolls[epfd]["rbr"]:
                item = epolls[epfd]["rbr"][t_fd]
                item["events"] = ev_list
                item["active"] = True
                ready = evaluate_fd_state(t_fd, ev_list)
                if ready and (t_fd not in epolls[epfd]["rdllist"]):
                    epolls[epfd]["rdllist"].append(t_fd)
                    item["in_rdllist"] = True
                elif (not ready) and ("EPOLLET" not in ev_list) and (t_fd in epolls[epfd]["rdllist"]):
                    epolls[epfd]["rdllist"].remove(t_fd)
                    item["in_rdllist"] = False

        elif op_type == "EPOLL_CTL_DEL":
            epfd = op["epfd"]
            t_fd = op["target_fd"]
            if epfd in epolls and t_fd in epolls[epfd]["rbr"]:
                del epolls[epfd]["rbr"][t_fd]
                if t_fd in epolls[epfd]["rdllist"]:
                    epolls[epfd]["rdllist"].remove(t_fd)

        elif op_type == "FD_DATA_ARRIVE":
            t_fd = op["fd"]
            delta = op.get("new_bytes", 0)
            if t_fd not in fds:
                fds[t_fd] = {"fd": t_fd, "unread_bytes": 0, "writable": False, "hup": False}
            fds[t_fd]["unread_bytes"] = fds[t_fd].get("unread_bytes", 0) + delta
            trigger_edge_or_level(t_fd, is_edge_event=True)

        elif op_type == "FD_DATA_READ":
            t_fd = op["fd"]
            read_cnt = op.get("read_bytes", 0)
            if t_fd in fds:
                fds[t_fd]["unread_bytes"] = max(0, fds[t_fd].get("unread_bytes", 0) - read_cnt)
            trigger_edge_or_level(t_fd, is_edge_event=False)

        elif op_type == "FD_WRITABLE_CHANGE":
            t_fd = op["fd"]
            old_w = fds.get(t_fd, {}).get("writable", False)
            new_w = op.get("writable", False)
            if t_fd not in fds:
                fds[t_fd] = {"fd": t_fd, "unread_bytes": 0, "writable": False, "hup": False}
            fds[t_fd]["writable"] = new_w
            is_edge = (not old_w and new_w)
            trigger_edge_or_level(t_fd, is_edge_event=is_edge)

        elif op_type == "FD_HUP":
            t_fd = op["fd"]
            if t_fd not in fds:
                fds[t_fd] = {"fd": t_fd, "unread_bytes": 0, "writable": False, "hup": False}
            fds[t_fd]["hup"] = True
            trigger_edge_or_level(t_fd, is_edge_event=True)

        elif op_type == "EPOLL_WAIT":
            epfd = op["epfd"]
            th_id = op.get("thread_id", "t0")
            max_ev = op.get("max_events") or global_max_events
            limit = min(max_ev, global_max_events)

            ep_inst = epolls.get(epfd, {"rbr": {}, "rdllist": []})
            returned_events = []

            to_process = list(ep_inst["rdllist"])
            ep_inst["rdllist"] = []
            re_insert_lt = []

            for t_fd in to_process:
                if len(returned_events) >= limit:
                    re_insert_lt.append(t_fd)
                    continue

                if t_fd not in ep_inst["rbr"]:
                    continue

                item = ep_inst["rbr"][t_fd]
                if not item["active"]:
                    continue

                ready = evaluate_fd_state(t_fd, item["events"])
                if not ready:
                    item["in_rdllist"] = False
                    continue

                returned_events.append({
                    "fd": t_fd,
                    "events": ready
                })

                is_et = "EPOLLET" in item["events"]
                is_oneshot = "EPOLLONESHOT" in item["events"]

                if is_oneshot:
                    item["active"] = False
                    item["in_rdllist"] = False
                elif is_et:
                    item["in_rdllist"] = False
                else:
                    still_ready = evaluate_fd_state(t_fd, item["events"])
                    if still_ready:
                        re_insert_lt.append(t_fd)
                    else:
                        item["in_rdllist"] = False

            ep_inst["rdllist"].extend(re_insert_lt)

            wait_results.append({
                "op_id": op_id,
                "epfd": epfd,
                "thread_id": th_id,
                "events_count": len(returned_events),
                "events": returned_events
            })

    return {
        "summary": {
            "total_epoll_instances": len(epolls),
            "total_waits": len(wait_results),
            "total_events_delivered": sum(w["events_count"] for w in wait_results),
            "total_errors": len(errors)
        },
        "wait_results": wait_results,
        "errors": errors
    }


def main():
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return
    data = json.loads(raw_input)
    result = run_epoll_engine(data)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
