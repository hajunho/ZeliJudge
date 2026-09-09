import sys

class TcpSocketConnection:
    def __init__(self, conn_id):
        self.conn_id = conn_id
        self.state = "ESTABLISHED"
        self.client_recv_buffer = 0
        self.server_recv_buffer = 0
        self.so_linger_on = 0
        self.so_linger_sec = 0
        
        # 통계
        self.fin_packets_sent = 0
        self.rst_packets_sent = 0
        self.time_wait_count = 0
        self.econnreset_count = 0

    def set_so_linger(self, onoff, linger_sec):
        self.so_linger_on = onoff
        self.so_linger_sec = linger_sec
        return f"SET_SO_LINGER id={self.conn_id} onoff={onoff} linger={linger_sec}"

    def app_send(self, from_role, byte_count):
        if self.state != "ESTABLISHED":
            return [f"ERROR id={self.conn_id} reason=SOCKET_NOT_ESTABLISHED state={self.state}"]
        if from_role == "CLIENT":
            self.server_recv_buffer += byte_count
            target_buf = self.server_recv_buffer
        else:
            self.client_recv_buffer += byte_count
            target_buf = self.client_recv_buffer
        return [f"APP_SEND id={self.conn_id} from={from_role} bytes={byte_count} target_recv_buffer={target_buf}"]

    def app_read(self, role, byte_count):
        if role == "CLIENT":
            read_bytes = min(byte_count, self.client_recv_buffer)
            self.client_recv_buffer -= read_bytes
            remaining = self.client_recv_buffer
        else:
            read_bytes = min(byte_count, self.server_recv_buffer)
            self.server_recv_buffer -= read_bytes
            remaining = self.server_recv_buffer
        return [f"APP_READ id={self.conn_id} role={role} requested={byte_count} read={read_bytes} remaining_recv_buffer={remaining}"]

    def close_socket(self, initiator):
        outputs = []
        if self.state in ["CLOSED", "TIME_WAIT"]:
            outputs.append(f"ERROR id={self.conn_id} reason=ALREADY_CLOSED state={self.state}")
            return outputs

        peer = "SERVER" if initiator == "CLIENT" else "CLIENT"
        my_recv_buf = self.client_recv_buffer if initiator == "CLIENT" else self.server_recv_buffer

        # Case 1: Zero Linger (l_onoff=1, l_linger=0)
        if self.so_linger_on == 1 and self.so_linger_sec == 0:
            self.state = "CLOSED"
            self.rst_packets_sent += 1
            self.econnreset_count += 1
            self.client_recv_buffer = 0
            self.server_recv_buffer = 0
            outputs.append(f"CLOSE_INITIATED id={self.conn_id} by={initiator} mode=ZERO_LINGER_ABRUPT")
            outputs.append(f"RST_SENT id={self.conn_id} from={initiator} reason=ZERO_LINGER_HARD_RESET")
            outputs.append(f"RST_RECEIVED id={self.conn_id} to={peer} error=ECONNRESET_CONNECTION_RESET_BY_PEER")
            outputs.append(f"CONN_CLOSED id={self.conn_id} state=CLOSED time_wait=SKIPPED")
            return outputs

        # Case 2: 수신 버퍼에 아직 읽지 않은 데이터가 남아있는 경우
        if my_recv_buf > 0:
            self.state = "CLOSED"
            self.rst_packets_sent += 1
            self.econnreset_count += 1
            unread = my_recv_buf
            self.client_recv_buffer = 0
            self.server_recv_buffer = 0
            outputs.append(f"CLOSE_INITIATED id={self.conn_id} by={initiator} mode=UNREAD_DATA_ABRUPT")
            outputs.append(f"RST_SENT id={self.conn_id} from={initiator} unread_bytes={unread} reason=UNREAD_DATA_IN_RECV_BUFFER")
            outputs.append(f"RST_RECEIVED id={self.conn_id} to={peer} error=ECONNRESET_CONNECTION_RESET_BY_PEER")
            outputs.append(f"CONN_CLOSED id={self.conn_id} state=CLOSED time_wait=SKIPPED")
            return outputs

        # Case 3: 정상 4-Way Handshake 종료 (FIN)
        self.state = "TIME_WAIT"
        self.fin_packets_sent += 2
        self.time_wait_count += 1
        outputs.append(f"CLOSE_INITIATED id={self.conn_id} by={initiator} mode=GRACEFUL_4WAY_HANDSHAKE")
        outputs.append(f"FIN_SENT id={self.conn_id} from={initiator} state=FIN_WAIT_1")
        outputs.append(f"ACK_RECEIVED id={self.conn_id} by={initiator} state=FIN_WAIT_2")
        outputs.append(f"FIN_SENT id={self.conn_id} from={peer} state=LAST_ACK")
        outputs.append(f"ACK_SENT id={self.conn_id} from={initiator} state=TIME_WAIT duration=60000ms")
        outputs.append(f"CONN_CLOSED id={self.conn_id} state=TIME_WAIT time_wait=ACTIVE")
        return outputs

    def expire_time_wait(self):
        if self.state != "TIME_WAIT":
            return [f"ERROR id={self.conn_id} reason=NOT_IN_TIME_WAIT state={self.state}"]
        self.state = "CLOSED"
        return [f"TIME_WAIT_EXPIRED id={self.conn_id} state=CLOSED"]

    def stats(self):
        return f"STATS id={self.conn_id} state={self.state} fin_sent={self.fin_packets_sent} rst_sent={self.rst_packets_sent} time_wait_count={self.time_wait_count} econnreset_count={self.econnreset_count} client_unread={self.client_recv_buffer} server_unread={self.server_recv_buffer}"

def main():
    connections = {}
    lines = sys.stdin.read().splitlines()
    for line in lines:
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        parts = line.split()
        cmd = parts[0]
        
        if cmd == "OPEN_CONN":
            conn_id = parts[1]
            connections[conn_id] = TcpSocketConnection(conn_id)
            print(f"OPEN_CONN id={conn_id} state=ESTABLISHED")
            
        elif cmd == "SET_SO_LINGER":
            conn_id = parts[1]
            onoff = int(parts[2])
            linger_sec = int(parts[3])
            print(connections[conn_id].set_so_linger(onoff, linger_sec))
            
        elif cmd == "APP_SEND":
            conn_id = parts[1]
            from_role = parts[2]
            byte_count = int(parts[3])
            for out in connections[conn_id].app_send(from_role, byte_count):
                print(out)
                
        elif cmd == "APP_READ":
            conn_id = parts[1]
            role = parts[2]
            byte_count = int(parts[3])
            for out in connections[conn_id].app_read(role, byte_count):
                print(out)
                
        elif cmd == "CLOSE_SOCKET":
            conn_id = parts[1]
            initiator = parts[2]
            for out in connections[conn_id].close_socket(initiator):
                print(out)
                
        elif cmd == "EXPIRE_TIME_WAIT":
            conn_id = parts[1]
            for out in connections[conn_id].expire_time_wait():
                print(out)
                
        elif cmd == "STATS":
            conn_id = parts[1]
            print(connections[conn_id].stats())

if __name__ == "__main__":
    main()
