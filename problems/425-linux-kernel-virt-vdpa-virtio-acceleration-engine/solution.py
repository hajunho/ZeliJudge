import sys
import json

class VDPAVirtIOEngine:
    def __init__(self, config=None):
        config = config or {}
        self.max_vqs = config.get("max_vqs", 4)
        self.features_supported = set(config.get("features_supported", [
            "VIRTIO_F_VERSION_1",
            "VIRTIO_NET_F_MRG_RXBUF",
            "VIRTIO_NET_F_MQ",
            "VIRTIO_F_LOG_ALL"
        ]))
        
        self.dev_name = None
        self.mgmt_dev = None
        self.features_negotiated = set()
        
        self.iotlb = {}
        
        self.vqs = {}
        for i in range(self.max_vqs):
            self.vqs[i] = {
                "num": 256,
                "avail_idx": 0,
                "used_idx": 0,
                "enabled": False,
                "svq_enabled": False
            }
            
        self.is_migrating = False
        self.svq_active = False
        self.dirty_pages = set()
        
        self.packets_transmitted = 0
        self.dma_errors = 0
        self.migration_checkpoints = 0
        
        self.migration_logs = []
        self.event_logs = []

    def dev_add(self, current_time, dev_name, mgmt_dev):
        self.dev_name = dev_name
        self.mgmt_dev = mgmt_dev
        self.event_logs.append({
            "time": current_time,
            "event": "VDPA_DEV_ADD_SUCCESS",
            "dev_name": dev_name,
            "mgmt_dev": mgmt_dev
        })

    def set_features(self, current_time, requested_features):
        req_set = set(requested_features)
        negotiated = req_set.intersection(self.features_supported)
        if "VIRTIO_F_VERSION_1" not in negotiated:
            self.event_logs.append({
                "time": current_time,
                "event": "VDPA_ERROR",
                "error": "LEGACY_VIRTIO_NOT_SUPPORTED",
                "requested": list(requested_features)
            })
            return False
            
        self.features_negotiated = negotiated
        self.event_logs.append({
            "time": current_time,
            "event": "VDPA_FEATURES_NEGOTIATED",
            "features": sorted(list(self.features_negotiated))
        })
        return True

    def dma_map(self, current_time, iova, hpa, size, perm="RW"):
        self.iotlb[iova] = {
            "hpa": hpa,
            "size": size,
            "perm": perm
        }
        self.event_logs.append({
            "time": current_time,
            "event": "VDPA_DMA_MAP_SUCCESS",
            "iova": iova,
            "hpa": hpa,
            "size": size,
            "perm": perm
        })

    def dma_unmap(self, current_time, iova, size):
        if iova in self.iotlb:
            del self.iotlb[iova]
            self.event_logs.append({
                "time": current_time,
                "event": "VDPA_DMA_UNMAP_SUCCESS",
                "iova": iova,
                "size": size
            })

    def set_vring_state(self, current_time, vq_idx, num, avail_idx=0, used_idx=0):
        if vq_idx not in self.vqs:
            return
        vq = self.vqs[vq_idx]
        vq["num"] = num
        vq["avail_idx"] = avail_idx
        vq["used_idx"] = used_idx
        self.event_logs.append({
            "time": current_time,
            "event": "VDPA_SET_VRING_STATE",
            "vq_idx": vq_idx,
            "num": num,
            "avail_idx": avail_idx,
            "used_idx": used_idx
        })

    def set_vring_enable(self, current_time, vq_idx, enable):
        if vq_idx not in self.vqs:
            return
        self.vqs[vq_idx]["enabled"] = enable
        self.event_logs.append({
            "time": current_time,
            "event": "VDPA_SET_VRING_ENABLE",
            "vq_idx": vq_idx,
            "enabled": enable
        })

    def packet_transmit(self, current_time, vq_idx, desc_iova, length):
        if vq_idx not in self.vqs:
            return False
        vq = self.vqs[vq_idx]
        if not vq["enabled"]:
            return False
            
        if desc_iova not in self.iotlb:
            self.dma_errors += 1
            self.event_logs.append({
                "time": current_time,
                "event": "VDPA_DMA_FAULT",
                "vq_idx": vq_idx,
                "desc_iova": desc_iova,
                "error": "IOMMU_TRANSLATION_FAILED"
            })
            return False
            
        entry = self.iotlb[desc_iova]
        hpa = entry["hpa"]
        
        vq["avail_idx"] = (vq["avail_idx"] + 1) % 65536
        vq["used_idx"] = (vq["used_idx"] + 1) % 65536
        self.packets_transmitted += 1
        
        if self.is_migrating:
            self.dirty_pages.add(hpa)
            
        self.event_logs.append({
            "time": current_time,
            "event": "VDPA_PACKET_TX_SUCCESS",
            "vq_idx": vq_idx,
            "hpa": hpa,
            "len": length,
            "svq_forwarded": self.svq_active
        })
        return True

    def live_migrate_start(self, current_time, use_svq=True):
        self.is_migrating = True
        self.svq_active = use_svq
        for vq in self.vqs.values():
            vq["svq_enabled"] = use_svq
        self.migration_logs.append({
            "time": current_time,
            "action": "LIVE_MIGRATION_STARTED",
            "use_svq": use_svq
        })
        self.event_logs.append({
            "time": current_time,
            "event": "VDPA_MIGRATION_START",
            "svq_active": use_svq
        })

    def suspend_and_save_state(self, current_time):
        self.is_migrating = False
        self.migration_checkpoints += 1
        
        vq_states = {}
        for idx, vq in self.vqs.items():
            vq_states[f"vq_{idx}"] = {
                "avail_idx": vq["avail_idx"],
                "used_idx": vq["used_idx"],
                "enabled": vq["enabled"]
            }
            
        snapshot = {
            "dev_name": self.dev_name,
            "dirty_pages_count": len(self.dirty_pages),
            "dirty_pages": sorted(list(self.dirty_pages)),
            "vq_states": vq_states
        }
        
        self.migration_logs.append({
            "time": current_time,
            "action": "DEVICE_SUSPENDED_STATE_SAVED",
            "snapshot": snapshot
        })
        self.event_logs.append({
            "time": current_time,
            "event": "VDPA_DEVICE_SUSPENDED",
            "dirty_pages_count": len(self.dirty_pages)
        })
        return snapshot

    def run_trace(self, trace):
        for ev in trace:
            t = ev.get("time", 0)
            ev_type = ev.get("type")
            if ev_type == "VDPA_DEV_ADD":
                self.dev_add(t, ev["dev_name"], ev["mgmt_dev"])
            elif ev_type == "VDPA_SET_FEATURES":
                self.set_features(t, ev["features"])
            elif ev_type == "VDPA_DMA_MAP":
                self.dma_map(t, ev["iova"], ev["hpa"], ev["size"], ev.get("perm", "RW"))
            elif ev_type == "VDPA_DMA_UNMAP":
                self.dma_unmap(t, ev["iova"], ev["size"])
            elif ev_type == "VDPA_SET_VRING_STATE":
                self.set_vring_state(t, ev["vq_idx"], ev["num"], ev.get("avail_idx", 0), ev.get("used_idx", 0))
            elif ev_type == "VDPA_SET_VRING_ENABLE":
                self.set_vring_enable(t, ev["vq_idx"], ev["enable"])
            elif ev_type == "VDPA_PACKET_TRANSMIT":
                self.packet_transmit(t, ev["vq_idx"], ev["desc_iova"], ev["len"])
            elif ev_type == "VDPA_LIVE_MIGRATE_START":
                self.live_migrate_start(t, ev.get("use_svq", True))
            elif ev_type == "VDPA_SUSPEND_AND_SAVE_STATE":
                self.suspend_and_save_state(t)

    def get_result(self):
        vqs_out = {}
        for idx, vq in sorted(self.vqs.items()):
            vqs_out[f"vq_{idx}"] = {
                "num": vq["num"],
                "avail_idx": vq["avail_idx"],
                "used_idx": vq["used_idx"],
                "enabled": vq["enabled"],
                "svq_enabled": vq["svq_enabled"]
            }
            
        return {
            "summary": {
                "packets_transmitted": self.packets_transmitted,
                "dma_errors": self.dma_errors,
                "migration_checkpoints": self.migration_checkpoints,
                "dirty_pages_logged": len(self.dirty_pages),
                "features_negotiated": sorted(list(self.features_negotiated)),
                "iotlb_entries": len(self.iotlb)
            },
            "vqs": vqs_out,
            "migration_logs": self.migration_logs,
            "event_logs": self.event_logs
        }

def main():
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    
    raw = sys.stdin.read().strip()
    if not raw:
        return
    data = json.loads(raw)
    
    engine = VDPAVirtIOEngine(data.get("config", {}))
    engine.run_trace(data.get("trace", []))
    res = engine.get_result()
    print(json.dumps(res, separators=(',', ':'), ensure_ascii=False))

if __name__ == "__main__":
    main()
