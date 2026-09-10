# -*- coding: utf-8 -*-
"""
ZeliJudge Pro Track Problem #381: Linux Kernel Device Drivers: dma-buf & Explicit Synchronization Engine
Canonical Solution Implementation
"""
import sys
import json
import copy

if hasattr(sys.stdin, "reconfigure"):
    sys.stdin.reconfigure(encoding="utf-8")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

class DmaBufEngine:
    def __init__(self, config):
        self.cma_pool_bytes = config.get("total_cma_memory_bytes", 1073741824)
        self.allocated_cma_bytes = 0
        self.devices = {d["dev_id"]: dict(d) for d in config.get("devices", [])}
        self.buffers = {}
        self.fences = {}
        self.jobs = {}
        self.history = []
        self.stats = {
            "buffers_exported": 0,
            "zero_copy_attachments": 0,
            "fences_created": 0,
            "fences_signaled": 0,
            "jobs_completed": 0,
            "cpu_sync_operations": 0,
            "peak_memory_used_bytes": 0,
            "deadlocks_detected": 0
        }

    def execute_op(self, op):
        cmd = op["op"]
        ts = op.get("timestamp", 0)

        if cmd == "EXPORT_BUFFER":
            bid = op["buf_id"]
            dev_id = op["exporter_dev"]
            size = op["size_bytes"]
            contig = op.get("contiguous_required", True)
            
            if bid in self.buffers:
                self.history.append({"op": cmd, "buf_id": bid, "status": "ERR_BUF_EXISTS", "detail": "buffer id already exported"})
                return

            if self.allocated_cma_bytes + size > self.cma_pool_bytes:
                self.history.append({"op": cmd, "buf_id": bid, "status": "ERR_ENOMEM", "detail": f"CMA pool limit {self.cma_pool_bytes} exceeded"})
                return

            self.allocated_cma_bytes += size
            self.stats["buffers_exported"] += 1
            self.stats["peak_memory_used_bytes"] = max(self.stats["peak_memory_used_bytes"], self.allocated_cma_bytes)
            
            self.buffers[bid] = {
                "buf_id": bid,
                "exporter_dev": dev_id,
                "size_bytes": size,
                "contiguous": contig,
                "attachments": {},
                "cpu_access": False,
                "last_sync": None
            }
            self.history.append({
                "op": cmd, "buf_id": bid, "status": "SUCCESS",
                "allocated_bytes": size, "exporter": dev_id,
                "detail": f"dma-buf exported {size} bytes from {dev_id} (contiguous={contig})"
            })

        elif cmd == "ATTACH_DEVICE":
            bid = op["buf_id"]
            imp_dev = op["importer_dev"]
            direction = op.get("direction", "DMA_BIDIRECTIONAL")
            
            buf = self.buffers.get(bid)
            if not buf:
                self.history.append({"op": cmd, "buf_id": bid, "importer": imp_dev, "status": "ERR_BUF_NOT_FOUND", "detail": "buffer not found"})
                return
            dev = self.devices.get(imp_dev)
            if not dev:
                self.history.append({"op": cmd, "buf_id": bid, "importer": imp_dev, "status": "ERR_DEV_NOT_FOUND", "detail": "device not found"})
                return

            if not dev.get("iommu_supported", True) and not buf["contiguous"]:
                self.history.append({
                    "op": cmd, "buf_id": bid, "importer": imp_dev, "status": "ERR_CONTIGUOUS_REQUIRED",
                    "detail": f"device {imp_dev} lacks IOMMU and requires contiguous memory"
                })
                return

            buf["attachments"][imp_dev] = {"direction": direction, "attached_ts": ts}
            self.stats["zero_copy_attachments"] += 1
            self.history.append({
                "op": cmd, "buf_id": bid, "importer": imp_dev, "status": "SUCCESS",
                "direction": direction,
                "detail": f"dma-buf zero-copy attached to {imp_dev} ({direction})"
            })

        elif cmd == "CREATE_FENCE":
            fid = op["fence_id"]
            dev = op.get("device")
            bid = op.get("buf_id")
            
            self.fences[fid] = {
                "fence_id": fid,
                "device": dev,
                "buf_id": bid,
                "signaled": False,
                "signaled_ts": None
            }
            self.stats["fences_created"] += 1
            self.history.append({
                "op": cmd, "fence_id": fid, "status": "SUCCESS",
                "detail": f"dma_fence created on {dev} for buffer {bid} (status=UNSIGNALED)"
            })

        elif cmd == "QUEUE_HARDWARE_JOB":
            jid = op["job_id"]
            dev = op["device"]
            wait_fences = op.get("wait_fences", [])
            sig_fence = op.get("signal_fence")
            dur = op.get("duration_ms", 10)
            
            if sig_fence in wait_fences:
                self.stats["deadlocks_detected"] += 1
                self.history.append({
                    "op": cmd, "job_id": jid, "status": "ERR_DEADLOCK",
                    "detail": f"deadlock detected: job {jid} waits on its own signal fence {sig_fence}"
                })
                return

            all_signaled = all(self.fences.get(f, {}).get("signaled", False) for f in wait_fences)
            job_status = "RUNNING" if all_signaled else "WAITING"

            self.jobs[jid] = {
                "job_id": jid,
                "device": dev,
                "wait_fences": list(wait_fences),
                "signal_fence": sig_fence,
                "duration_ms": dur,
                "status": job_status,
                "start_ts": ts if all_signaled else None,
                "finish_ts": (ts + dur) if all_signaled else None
            }
            self.history.append({
                "op": cmd, "job_id": jid, "status": job_status,
                "wait_count": len(wait_fences),
                "detail": f"hardware job {jid} queued on {dev} (state={job_status}, duration={dur}ms)"
            })

        elif cmd == "SIGNAL_FENCE":
            fid = op["fence_id"]
            fence = self.fences.get(fid)
            if not fence:
                self.history.append({"op": cmd, "fence_id": fid, "status": "ERR_FENCE_NOT_FOUND", "detail": "fence not found"})
                return

            fence["signaled"] = True
            fence["signaled_ts"] = ts
            self.stats["fences_signaled"] += 1
            
            unblocked_jobs = []
            for jid, job in self.jobs.items():
                if job["status"] == "WAITING":
                    if all(self.fences.get(f, {}).get("signaled", False) for f in job["wait_fences"]):
                        job["status"] = "RUNNING"
                        job["start_ts"] = ts
                        job["finish_ts"] = ts + job["duration_ms"]
                        unblocked_jobs.append(jid)

            self.history.append({
                "op": cmd, "fence_id": fid, "status": "SUCCESS",
                "unblocked_jobs": unblocked_jobs,
                "detail": f"dma_fence {fid} signaled at ts={ts}; unblocked {len(unblocked_jobs)} hardware jobs"
            })

        elif cmd == "CPU_SYNC_ACCESS":
            bid = op["buf_id"]
            phase = op["phase"]
            atype = op.get("access_type", "READ")
            buf = self.buffers.get(bid)
            if not buf:
                self.history.append({"op": cmd, "buf_id": bid, "status": "ERR_BUF_NOT_FOUND", "detail": "buffer not found"})
                return

            self.stats["cpu_sync_operations"] += 1
            if phase == "START":
                buf["cpu_access"] = True
                buf["last_sync"] = atype
                self.history.append({
                    "op": cmd, "buf_id": bid, "phase": phase, "status": "SUCCESS",
                    "detail": f"DMA_BUF_IOCTL_SYNC START: CPU cache invalidated/flushed for {atype} access"
                })
            else:
                buf["cpu_access"] = False
                self.history.append({
                    "op": cmd, "buf_id": bid, "phase": phase, "status": "SUCCESS",
                    "detail": f"DMA_BUF_IOCTL_SYNC END: buffer ownership returned to hardware DMA engine"
                })

        elif cmd == "MERGE_SYNC_FILES":
            merged_fid = op["merged_fence_id"]
            src_fences = op.get("source_fences", [])
            all_sig = all(self.fences.get(f, {}).get("signaled", False) for f in src_fences)
            
            self.fences[merged_fid] = {
                "fence_id": merged_fid,
                "device": "sync_file_merge",
                "buf_id": None,
                "signaled": all_sig,
                "signaled_ts": ts if all_sig else None
            }
            self.stats["fences_created"] += 1
            if all_sig:
                self.stats["fences_signaled"] += 1
            self.history.append({
                "op": cmd, "merged_fence_id": merged_fid, "status": "SUCCESS",
                "source_count": len(src_fences), "signaled": all_sig,
                "detail": f"sync_file merge created composite fence {merged_fid} from {src_fences} (signaled={all_sig})"
            })

        elif cmd == "RELEASE_BUFFER":
            bid = op["buf_id"]
            buf = self.buffers.get(bid)
            if not buf:
                self.history.append({"op": cmd, "buf_id": bid, "status": "ERR_BUF_NOT_FOUND", "detail": "buffer not found"})
                return

            size = buf["size_bytes"]
            self.allocated_cma_bytes -= size
            del self.buffers[bid]
            self.history.append({
                "op": cmd, "buf_id": bid, "status": "SUCCESS", "freed_bytes": size,
                "detail": f"dma-buf {bid} released; {size} bytes reclaimed to CMA pool"
            })

    def get_summary(self):
        active_bufs = len(self.buffers)
        total_attached = sum(len(b["attachments"]) for b in self.buffers.values())
        sig_fences_count = sum(1 for f in self.fences.values() if f["signaled"])
        unsig_fences_count = sum(1 for f in self.fences.values() if not f["signaled"])
        
        return {
            "active_buffers_count": active_bufs,
            "allocated_cma_bytes": self.allocated_cma_bytes,
            "peak_memory_used_bytes": self.stats["peak_memory_used_bytes"],
            "total_attachments_count": total_attached,
            "fences_summary": {
                "created": len(self.fences),
                "signaled": sig_fences_count,
                "unsignaled": unsig_fences_count
            },
            "deadlocks_detected": self.stats["deadlocks_detected"],
            "cpu_sync_operations": self.stats["cpu_sync_operations"]
        }

def main():
    raw = sys.stdin.read().strip()
    if not raw:
        return
    data = json.loads(raw)
    eng = DmaBufEngine(data["config"])
    for op in data["operations"]:
        eng.execute_op(op)
    result = {
        "history": eng.history,
        "summary": eng.get_summary()
    }
    print(json.dumps(result, separators=(',', ':'), ensure_ascii=False))

if __name__ == "__main__":
    main()
