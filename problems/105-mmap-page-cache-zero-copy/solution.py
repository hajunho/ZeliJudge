import sys

class FileObject:
    def __init__(self, name, size_bytes):
        self.name = name
        self.size_bytes = size_bytes
        self.total_pages = (size_bytes + 4095) // 4096 if size_bytes > 0 else 0
        self.disk_blocks = {}
        for p in range(self.total_pages):
            self.disk_blocks[p] = bytearray(4096)

class MmapSession:
    def __init__(self, conn_id, file_obj, prot):
        self.conn_id = conn_id
        self.file = file_obj
        self.prot = prot
        self.resident_pages = set()
        self.dirty_pages = set()
        self.cached_data = {}
        
        # 통계
        self.page_faults = 0
        self.cache_hits = 0
        self.total_disk_io_bytes = 0

    def read_byte(self, offset):
        outputs = []
        if offset < 0 or offset >= self.file.size_bytes:
            outputs.append(f"ERROR id={self.conn_id} reason=OFFSET_OUT_OF_BOUNDS offset={offset}")
            return outputs
            
        page_no = offset // 4096
        page_offset = offset % 4096
        
        if page_no not in self.resident_pages:
            # Page Fault 발생
            self.page_faults += 1
            self.total_disk_io_bytes += 4096
            self.resident_pages.add(page_no)
            self.cached_data[page_no] = bytearray(self.file.disk_blocks[page_no])
            outputs.append(f"PAGE_FAULT id={self.conn_id} page={page_no} reason=READ_MISS disk_io=4096B")
        else:
            self.cache_hits += 1
            outputs.append(f"PAGE_HIT id={self.conn_id} page={page_no} disk_io=0B")
            
        val = self.cached_data[page_no][page_offset]
        outputs.append(f"READ_SUCCESS id={self.conn_id} offset={offset} page={page_no} val={val}")
        return outputs

    def write_byte(self, offset, val):
        outputs = []
        if self.prot == "READ":
            outputs.append(f"ERROR id={self.conn_id} reason=PERMISSION_DENIED_READONLY")
            return outputs
            
        if offset < 0 or offset >= self.file.size_bytes:
            outputs.append(f"ERROR id={self.conn_id} reason=OFFSET_OUT_OF_BOUNDS offset={offset}")
            return outputs
            
        page_no = offset // 4096
        page_offset = offset % 4096
        
        if page_no not in self.resident_pages:
            self.page_faults += 1
            self.total_disk_io_bytes += 4096
            self.resident_pages.add(page_no)
            self.cached_data[page_no] = bytearray(self.file.disk_blocks[page_no])
            outputs.append(f"PAGE_FAULT id={self.conn_id} page={page_no} reason=WRITE_MISS disk_io=4096B")
        else:
            self.cache_hits += 1
            outputs.append(f"PAGE_HIT id={self.conn_id} page={page_no} disk_io=0B")
            
        self.cached_data[page_no][page_offset] = int(val)
        self.dirty_pages.add(page_no)
        outputs.append(f"WRITE_SUCCESS id={self.conn_id} offset={offset} page={page_no} val={val} dirty=True")
        return outputs

    def msync(self):
        flushed_count = len(self.dirty_pages)
        flushed_bytes = flushed_count * 4096
        self.total_disk_io_bytes += flushed_bytes
        for p in self.dirty_pages:
            self.file.disk_blocks[p] = bytearray(self.cached_data[p])
        self.dirty_pages.clear()
        return f"MSYNC id={self.conn_id} flushed_pages={flushed_count} flushed_bytes={flushed_bytes}"

    def munmap(self):
        flushed_count = len(self.dirty_pages)
        flushed_bytes = flushed_count * 4096
        self.total_disk_io_bytes += flushed_bytes
        for p in self.dirty_pages:
            self.file.disk_blocks[p] = bytearray(self.cached_data[p])
        self.dirty_pages.clear()
        released_rss = len(self.resident_pages) * 4096
        self.resident_pages.clear()
        self.cached_data.clear()
        return f"MUNMAP id={self.conn_id} auto_flushed_pages={flushed_count} released_rss_bytes={released_rss}"

    def stats(self):
        return f"STATS id={self.conn_id} page_faults={self.page_faults} cache_hits={self.cache_hits} total_disk_io_bytes={self.total_disk_io_bytes} current_rss_bytes={len(self.resident_pages)*4096} dirty_pages={len(self.dirty_pages)}"

def main():
    files = {}
    sessions = {}
    lines = sys.stdin.read().splitlines()
    for line in lines:
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        parts = line.split()
        cmd = parts[0]
        
        if cmd == "CREATE_FILE":
            name = parts[1]
            size = int(parts[2])
            f = FileObject(name, size)
            files[name] = f
            print(f"CREATE_FILE name={name} size={size} pages={f.total_pages}")
            
        elif cmd == "MMAP_FILE":
            conn_id = parts[1]
            file_name = parts[2]
            prot = parts[3]
            f = files[file_name]
            session = MmapSession(conn_id, f, prot)
            sessions[conn_id] = session
            print(f"MMAP_FILE id={conn_id} file={file_name} prot={prot} mapped_pages={f.total_pages} initial_rss_bytes=0")
            
        elif cmd == "READ_BYTE":
            conn_id = parts[1]
            offset = int(parts[2])
            session = sessions[conn_id]
            for out in session.read_byte(offset):
                print(out)
                
        elif cmd == "WRITE_BYTE":
            conn_id = parts[1]
            offset = int(parts[2])
            val = int(parts[3])
            session = sessions[conn_id]
            for out in session.write_byte(offset, val):
                print(out)
                
        elif cmd == "MSYNC":
            conn_id = parts[1]
            session = sessions[conn_id]
            print(session.msync())
            
        elif cmd == "MUNMAP":
            conn_id = parts[1]
            session = sessions[conn_id]
            print(session.munmap())
            del sessions[conn_id]
            
        elif cmd == "STATS":
            conn_id = parts[1]
            session = sessions[conn_id]
            print(session.stats())

if __name__ == "__main__":
    main()
