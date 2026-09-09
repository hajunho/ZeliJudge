import sys

class FlowConnection:
    def __init__(self, conn_id, rcv_buf_size, persist_interval):
        self.conn_id = conn_id
        self.rcv_buf_max = rcv_buf_size
        self.rcv_buf_used = 0
        self.rwnd = rcv_buf_size
        self.persist_interval = persist_interval
        
        self.sender_buffer = 0
        self.zero_window_state = False
        
        # 통계
        self.total_sent_bytes = 0
        self.total_received_bytes = 0
        self.zero_window_events = 0
        self.zwp_sent = 0
        self.window_update_lost_events = 0

    def app_write(self, byte_count):
        outputs = []
        if self.rwnd > 0 and not self.zero_window_state:
            sendable = min(byte_count, self.rwnd)
            remaining = byte_count - sendable
            if remaining > 0:
                self.sender_buffer += remaining
                
            self.rcv_buf_used += sendable
            self.rwnd = self.rcv_buf_max - self.rcv_buf_used
            self.total_sent_bytes += sendable
            outputs.append(f"DATA_SENT id={self.conn_id} sent={sendable} buffered={self.sender_buffer} rwnd={self.rwnd}")
            
            if self.rwnd == 0:
                self.zero_window_events += 1
                self.zero_window_state = True
                outputs.append(f"ZERO_WINDOW_ADVERTISED id={self.conn_id} rwnd=0 persist_timer={self.persist_interval}ms")
        else:
            self.sender_buffer += byte_count
            outputs.append(f"DATA_BLOCKED id={self.conn_id} requested={byte_count} buffered={self.sender_buffer} reason=ZERO_WINDOW")
            
        return outputs

    def app_read(self, byte_count):
        read_bytes = min(byte_count, self.rcv_buf_used)
        self.rcv_buf_used -= read_bytes
        self.rwnd = self.rcv_buf_max - self.rcv_buf_used
        self.total_received_bytes += read_bytes
        return f"APP_READ id={self.conn_id} read={read_bytes} remaining_in_buf={self.rcv_buf_used} new_rwnd={self.rwnd}"

    def simulate_window_update_lost(self):
        self.window_update_lost_events += 1
        # 송신자는 여전히 제로 윈도우로 인식하고 있음
        self.zero_window_state = True
        return f"WINDOW_UPDATE_LOST id={self.conn_id} actual_rwnd={self.rwnd} sender_still_sees_zero_window=True"

    def tick_persist_timer(self, elapsed_ms):
        outputs = []
        self.zwp_sent += 1
        outputs.append(f"ZERO_WINDOW_PROBE_SENT id={self.conn_id} probe_bytes=1B")
        outputs.append(f"PROBE_ACK_RECEIVED id={self.conn_id} received_rwnd={self.rwnd}")
        
        if self.rwnd > 0:
            self.zero_window_state = False
            drain_bytes = min(self.sender_buffer, self.rwnd)
            self.sender_buffer -= drain_bytes
            self.rcv_buf_used += drain_bytes
            self.rwnd = self.rcv_buf_max - self.rcv_buf_used
            self.total_sent_bytes += drain_bytes
            outputs.append(f"WINDOW_OPENED id={self.conn_id} drained_from_buffer={drain_bytes} remaining_buffer={self.sender_buffer} current_rwnd={self.rwnd}")
            if self.rwnd == 0 and self.sender_buffer > 0:
                self.zero_window_events += 1
                self.zero_window_state = True
                outputs.append(f"ZERO_WINDOW_ADVERTISED id={self.conn_id} rwnd=0 persist_timer={self.persist_interval}ms")
        else:
            outputs.append(f"ZERO_WINDOW_PERSISTS id={self.conn_id} rwnd=0 persist_timer_reset={self.persist_interval}ms")
            
        return outputs

    def stats(self):
        return f"STATS id={self.conn_id} total_sent={self.total_sent_bytes} total_recv={self.total_received_bytes} rcv_buf_used={self.rcv_buf_used} rwnd={self.rwnd} sender_buffer={self.sender_buffer} zero_window_events={self.zero_window_events} zwp_sent={self.zwp_sent}"

def main():
    connections = {}
    lines = sys.stdin.read().splitlines()
    for line in lines:
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        parts = line.split()
        cmd = parts[0]
        
        if cmd == "INIT_FLOW":
            conn_id = parts[1]
            rcv_buf = int(parts[2])
            persist_interval = int(parts[3])
            connections[conn_id] = FlowConnection(conn_id, rcv_buf, persist_interval)
            print(f"INIT_FLOW id={conn_id} rcv_buf={rcv_buf} rwnd={rcv_buf} persist_interval={persist_interval}ms")
            
        elif cmd == "APP_WRITE":
            conn_id = parts[1]
            byte_count = int(parts[2])
            for out in connections[conn_id].app_write(byte_count):
                print(out)
                
        elif cmd == "APP_READ":
            conn_id = parts[1]
            byte_count = int(parts[2])
            print(connections[conn_id].app_read(byte_count))
            
        elif cmd == "SIMULATE_WINDOW_UPDATE_LOST":
            conn_id = parts[1]
            print(connections[conn_id].simulate_window_update_lost())
            
        elif cmd == "TICK_PERSIST_TIMER":
            conn_id = parts[1]
            elapsed_ms = int(parts[2])
            for out in connections[conn_id].tick_persist_timer(elapsed_ms):
                print(out)
                
        elif cmd == "STATS":
            conn_id = parts[1]
            print(connections[conn_id].stats())

if __name__ == "__main__":
    main()
