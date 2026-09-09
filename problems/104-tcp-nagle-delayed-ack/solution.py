import sys

class TcpConnection:
    def __init__(self, conn_id, mss, nagle, delayed_ack):
        self.conn_id = conn_id
        self.mss = mss
        self.nagle = nagle
        self.delayed_ack = delayed_ack
        self.current_time = 0
        self.in_flight = 0
        self.client_buffer = 0
        self.server_unacked_packets = 0
        self.delayed_ack_timer = None
        
        # 통계
        self.total_written = 0
        self.total_packets_sent = 0
        self.total_interlock_delay_ms = 0
        self.nagle_buffered_count = 0

    def check_and_fire_timer(self, target_time):
        outputs = []
        while self.delayed_ack_timer is not None and self.delayed_ack_timer <= target_time:
            timer_time = self.delayed_ack_timer
            self.delayed_ack_timer = None
            acked = self.server_unacked_packets
            self.server_unacked_packets = 0
            self.in_flight = max(0, self.in_flight - acked)
            outputs.append(f"ACK_SENT id={self.conn_id} time={timer_time} acked_packets={acked} type=DELAYED_TIMER_EXPIRED")
            outputs.append(f"ACK_RECEIVED id={self.conn_id} time={timer_time} in_flight={self.in_flight}")
            
            # 버퍼에 대기 중이던 데이터가 있었다면 인터록 지연 발생 (40ms)
            if self.client_buffer > 0:
                self.total_interlock_delay_ms += 40
                drain_outputs = self._try_send_client(timer_time)
                outputs.extend(drain_outputs)
        return outputs

    def _server_receive(self, time_ms):
        outputs = []
        if not self.delayed_ack:
            # 즉시 ACK 전송
            self.in_flight = max(0, self.in_flight - 1)
            outputs.append(f"ACK_SENT id={self.conn_id} time={time_ms} acked_packets=1 type=IMMEDIATE")
            outputs.append(f"ACK_RECEIVED id={self.conn_id} time={time_ms} in_flight={self.in_flight}")
        else:
            self.server_unacked_packets += 1
            if self.server_unacked_packets >= 2:
                acked = self.server_unacked_packets
                self.server_unacked_packets = 0
                self.delayed_ack_timer = None
                self.in_flight = max(0, self.in_flight - acked)
                outputs.append(f"ACK_SENT id={self.conn_id} time={time_ms} acked_packets={acked} type=FULL_BURST")
                outputs.append(f"ACK_RECEIVED id={self.conn_id} time={time_ms} in_flight={self.in_flight}")
            else:
                # 1개 수신 -> Delayed ACK 타이머 가동 (40ms 뒤)
                self.delayed_ack_timer = time_ms + 40
        return outputs

    def _try_send_client(self, time_ms):
        outputs = []
        if not self.nagle:
            # TCP_NODELAY: 버퍼에 있는 모든 데이터를 최대 MSS 크기 패킷으로 즉시 분할 송신
            while self.client_buffer > 0:
                send_size = min(self.client_buffer, self.mss)
                self.client_buffer -= send_size
                self.in_flight += 1
                self.total_packets_sent += 1
                outputs.append(f"PACKET_SENT id={self.conn_id} time={time_ms} size={send_size} in_flight={self.in_flight}")
                recv_outputs = self._server_receive(time_ms)
                outputs.extend(recv_outputs)
        else:
            # Nagle 알고리즘 ON
            while self.client_buffer > 0:
                if self.client_buffer >= self.mss:
                    # MSS 이상이면 즉시 한 세그먼트 전송
                    send_size = self.mss
                    self.client_buffer -= send_size
                    self.in_flight += 1
                    self.total_packets_sent += 1
                    outputs.append(f"PACKET_SENT id={self.conn_id} time={time_ms} size={send_size} in_flight={self.in_flight}")
                    recv_outputs = self._server_receive(time_ms)
                    outputs.extend(recv_outputs)
                else:
                    # 버퍼 크기 < MSS
                    if self.in_flight == 0:
                        # 미확인 패킷이 없으므로 즉시 송신 허용
                        send_size = self.client_buffer
                        self.client_buffer = 0
                        self.in_flight += 1
                        self.total_packets_sent += 1
                        outputs.append(f"PACKET_SENT id={self.conn_id} time={time_ms} size={send_size} in_flight={self.in_flight}")
                        recv_outputs = self._server_receive(time_ms)
                        outputs.extend(recv_outputs)
                    else:
                        # In-flight 패킷이 있으므로 버퍼링 대기
                        self.nagle_buffered_count += 1
                        outputs.append(f"PACKET_BUFFERED id={self.conn_id} time={time_ms} buffered_bytes={self.client_buffer} in_flight={self.in_flight} reason=NAGLE_WAIT_ACK")
                        break
        return outputs

    def app_write(self, time_ms, byte_count):
        outputs = []
        # 먼저 시간 전진에 따른 타이머 처리
        if time_ms > self.current_time:
            timer_outputs = self.check_and_fire_timer(time_ms)
            outputs.extend(timer_outputs)
            self.current_time = time_ms
            
        self.total_written += byte_count
        self.client_buffer += byte_count
        
        send_outputs = self._try_send_client(time_ms)
        outputs.extend(send_outputs)
        return outputs

    def advance_time(self, target_time):
        outputs = []
        if target_time >= self.current_time:
            timer_outputs = self.check_and_fire_timer(target_time)
            outputs.extend(timer_outputs)
            self.current_time = target_time
        return outputs

    def stats(self):
        return f"STATS id={self.conn_id} total_written={self.total_written} total_packets_sent={self.total_packets_sent} interlock_delay_ms={self.total_interlock_delay_ms} nagle_buffered_count={self.nagle_buffered_count} in_flight={self.in_flight} buffered_bytes={self.client_buffer}"

def main():
    connections = {}
    lines = sys.stdin.read().splitlines()
    for line in lines:
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        parts = line.split()
        cmd = parts[0]
        
        if cmd == "INIT_CONN":
            conn_id = parts[1]
            mss = int(parts[2])
            nagle = (parts[3] == "ON")
            delayed_ack = (parts[4] == "ON")
            connections[conn_id] = TcpConnection(conn_id, mss, nagle, delayed_ack)
            print(f"INIT_CONN id={conn_id} mss={mss} nagle={'ON' if nagle else 'OFF'} delayed_ack={'ON' if delayed_ack else 'OFF'}")
            
        elif cmd == "APP_WRITE":
            conn_id = parts[1]
            time_ms = int(parts[2])
            byte_count = int(parts[3])
            conn = connections[conn_id]
            outputs = conn.app_write(time_ms, byte_count)
            for out in outputs:
                print(out)
                
        elif cmd == "ADVANCE_TIME":
            conn_id = parts[1]
            target_time = int(parts[2])
            conn = connections[conn_id]
            outputs = conn.advance_time(target_time)
            for out in outputs:
                print(out)
                
        elif cmd == "STATS":
            conn_id = parts[1]
            conn = connections[conn_id]
            print(conn.stats())

if __name__ == "__main__":
    main()
