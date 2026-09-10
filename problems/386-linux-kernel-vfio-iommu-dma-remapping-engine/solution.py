# -*- coding: utf-8 -*-
"""
ZeliJudge Pro #386: Linux Kernel VFIO Userspace Driver & IOMMU DMA Remapping Engine
Implementation in Python 3.
"""
import sys
import json

PAGE_SIZE = 4096

class VfioEngine:
    def __init__(self, config):
        self.memlock_limit = config.get("memlock_limit", 16 * 1024 * 1024)
        self.containers = {}
        self.groups = config.get("iommu_groups", {})
        self.devices = {}

        for gid, devs in self.groups.items():
            for d in devs:
                self.devices[d] = {
                    "group_id": gid,
                    "msix_vectors": {}
                }

        self.eventfds = {}
        self.events = []
        self.dma_faults = 0

    def run_commands(self, commands):
        for cmd in commands:
            op = cmd.get("op")
            if op == "CREATE_CONTAINER":
                self._handle_create_container(cmd)
            elif op == "ATTACH_GROUP":
                self._handle_attach_group(cmd)
            elif op == "MAP_DMA":
                self._handle_map_dma(cmd)
            elif op == "UNMAP_DMA":
                self._handle_unmap_dma(cmd)
            elif op == "DMA_ACCESS":
                self._handle_dma_access(cmd)
            elif op == "CONFIG_MSIX":
                self._handle_config_msix(cmd)
            elif op == "SET_IRQ_EVENTFD":
                self._handle_set_irq_eventfd(cmd)
            elif op == "TRIGGER_IRQ":
                self._handle_trigger_irq(cmd)

    def _handle_create_container(self, cmd):
        cid = cmd["container_id"]
        self.containers[cid] = {
            "groups": set(),
            "mappings": [],
            "pinned_bytes": 0
        }
        self.events.append({
            "op": "CREATE_CONTAINER",
            "container_id": cid,
            "status": "SUCCESS"
        })

    def _handle_attach_group(self, cmd):
        cid = cmd["container_id"]
        gid = cmd["group_id"]

        if cid not in self.containers:
            self.events.append({"op": "ATTACH_GROUP", "status": "FAIL_NO_CONTAINER", "container_id": cid})
            return

        if gid not in self.groups:
            self.events.append({"op": "ATTACH_GROUP", "status": "FAIL_NO_GROUP", "group_id": gid})
            return

        self.containers[cid]["groups"].add(gid)
        self.events.append({
            "op": "ATTACH_GROUP",
            "container_id": cid,
            "group_id": gid,
            "status": "SUCCESS",
            "device_count": len(self.groups[gid])
        })

    def _handle_map_dma(self, cmd):
        cid = cmd["container_id"]
        iova = cmd["iova"]
        vaddr = cmd["vaddr"]
        size = cmd["size"]
        flags = set(cmd.get("flags", ["READ", "WRITE"]))

        container = self.containers.get(cid)
        if not container:
            self.events.append({"op": "MAP_DMA", "status": "FAIL_NO_CONTAINER"})
            return

        if (iova % PAGE_SIZE != 0) or (size % PAGE_SIZE != 0):
            self.events.append({
                "op": "MAP_DMA",
                "status": "FAIL_UNALIGNED",
                "reason": "IOVA and size must be 4KB aligned"
            })
            return

        if container["pinned_bytes"] + size > self.memlock_limit:
            self.events.append({
                "op": "MAP_DMA",
                "status": "FAIL_MEMLOCK_EXCEEDED",
                "requested": size,
                "current_pinned": container["pinned_bytes"],
                "limit": self.memlock_limit
            })
            return

        iova_end = iova + size
        for m in container["mappings"]:
            m_end = m["iova"] + m["size"]
            if not (iova_end <= m["iova"] or iova >= m_end):
                self.events.append({
                    "op": "MAP_DMA",
                    "status": "FAIL_IOVA_COLLISION",
                    "iova": hex(iova),
                    "conflicting_iova": hex(m["iova"])
                })
                return

        container["mappings"].append({
            "iova": iova,
            "vaddr": vaddr,
            "size": size,
            "flags": list(flags)
        })
        container["pinned_bytes"] += size
        self.events.append({
            "op": "MAP_DMA",
            "container_id": cid,
            "iova": hex(iova),
            "size": size,
            "flags": sorted(list(flags)),
            "status": "SUCCESS"
        })

    def _handle_unmap_dma(self, cmd):
        cid = cmd["container_id"]
        iova = cmd["iova"]
        size = cmd["size"]

        container = self.containers.get(cid)
        if not container:
            self.events.append({"op": "UNMAP_DMA", "status": "FAIL_NO_CONTAINER"})
            return

        unmapped_bytes = 0
        new_mappings = []
        for m in container["mappings"]:
            if m["iova"] == iova and m["size"] == size:
                unmapped_bytes += m["size"]
            else:
                new_mappings.append(m)

        container["mappings"] = new_mappings
        container["pinned_bytes"] -= unmapped_bytes
        self.events.append({
            "op": "UNMAP_DMA",
            "container_id": cid,
            "iova": hex(iova),
            "unmapped_bytes": unmapped_bytes,
            "status": "SUCCESS" if unmapped_bytes > 0 else "FAIL_NOT_FOUND"
        })

    def _handle_dma_access(self, cmd):
        cid = cmd["container_id"]
        dev_id = cmd["device_id"]
        target_iova = cmd["target_iova"]
        length = cmd["length"]
        access_type = cmd.get("access_type", "READ")

        container = self.containers.get(cid)
        if not container:
            self.events.append({"op": "DMA_ACCESS", "status": "FAIL_NO_CONTAINER"})
            return

        dev_entry = self.devices.get(dev_id)
        if not dev_entry or dev_entry["group_id"] not in container["groups"]:
            self.events.append({"op": "DMA_ACCESS", "status": "FAIL_DEVICE_NOT_IN_CONTAINER"})
            return

        target_end = target_iova + length
        matched = None
        for m in container["mappings"]:
            m_end = m["iova"] + m["size"]
            if m["iova"] <= target_iova and target_end <= m_end:
                matched = m
                break

        if matched is None:
            self.dma_faults += 1
            self.events.append({
                "op": "DMA_ACCESS",
                "device_id": dev_id,
                "target_iova": hex(target_iova),
                "status": "IOMMU_DMA_FAULT",
                "fault_type": "UNMAPPED_IOVA"
            })
            return

        if access_type not in matched["flags"]:
            self.dma_faults += 1
            self.events.append({
                "op": "DMA_ACCESS",
                "device_id": dev_id,
                "target_iova": hex(target_iova),
                "status": "IOMMU_DMA_FAULT",
                "fault_type": "PERMISSION_DENIED",
                "required": access_type,
                "granted": sorted(matched["flags"])
            })
            return

        self.events.append({
            "op": "DMA_ACCESS",
            "device_id": dev_id,
            "target_iova": hex(target_iova),
            "length": length,
            "access_type": access_type,
            "status": "SUCCESS"
        })

    def _handle_config_msix(self, cmd):
        dev_id = cmd["device_id"]
        num_vectors = cmd["num_vectors"]
        if dev_id in self.devices:
            self.devices[dev_id]["num_vectors"] = num_vectors
            self.events.append({
                "op": "CONFIG_MSIX",
                "device_id": dev_id,
                "num_vectors": num_vectors,
                "status": "SUCCESS"
            })

    def _handle_set_irq_eventfd(self, cmd):
        dev_id = cmd["device_id"]
        vec_idx = cmd["vector_idx"]
        efd = cmd["eventfd_id"]

        if dev_id in self.devices:
            self.devices[dev_id]["msix_vectors"][vec_idx] = efd
            if efd not in self.eventfds:
                self.eventfds[efd] = 0
            self.events.append({
                "op": "SET_IRQ_EVENTFD",
                "device_id": dev_id,
                "vector_idx": vec_idx,
                "eventfd_id": efd,
                "status": "SUCCESS"
            })

    def _handle_trigger_irq(self, cmd):
        dev_id = cmd["device_id"]
        vec_idx = cmd["vector_idx"]

        if dev_id not in self.devices:
            self.events.append({"op": "TRIGGER_IRQ", "status": "FAIL_NO_DEVICE"})
            return

        dev = self.devices[dev_id]
        if vec_idx in dev["msix_vectors"]:
            efd = dev["msix_vectors"][vec_idx]
            self.eventfds[efd] += 1
            self.events.append({
                "op": "TRIGGER_IRQ",
                "device_id": dev_id,
                "vector_idx": vec_idx,
                "signaled_eventfd": efd,
                "new_count": self.eventfds[efd],
                "status": "DELIVERED"
            })
        else:
            self.events.append({
                "op": "TRIGGER_IRQ",
                "device_id": dev_id,
                "vector_idx": vec_idx,
                "status": "DROPPED_NO_EVENTFD"
            })

    def get_result(self):
        container_stats = {}
        for cid, c in self.containers.items():
            container_stats[cid] = {
                "attached_groups": sorted(list(c["groups"])),
                "active_mappings": len(c["mappings"]),
                "pinned_bytes": c["pinned_bytes"]
            }

        return {
            "containers": container_stats,
            "dma_faults": self.dma_faults,
            "eventfd_signals": self.eventfds,
            "events": self.events
        }

def main():
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return
    data = json.loads(raw_input)
    config = data.get("config", {})
    commands = data.get("commands", [])

    engine = VfioEngine(config)
    engine.run_commands(commands)
    result = engine.get_result()

    sys.stdout.write(json.dumps(result, separators=(',', ':'), ensure_ascii=False))

if __name__ == "__main__":
    main()
