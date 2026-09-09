import sys
import math

class KafkaCompressionSimulator:
    def __init__(self):
        self.reset()

    def reset(self):
        # Producer config
        self.producer_batch_size = 16384  # 16 KB default
        self.producer_codec = "NONE"
        self.producer_zstd_level = 3

        # Broker config
        self.broker_codec = "PRODUCER"
        self.broker_zstd_level = 3

        # Active batch
        self.curr_records = 0
        self.curr_raw_bytes = 0
        self.curr_weighted_redundancy = 0.0

        # Cumulative metrics
        self.total_records = 0
        self.total_batches = 0
        self.raw_payload_bytes = 0
        self.total_raw_bytes = 0
        self.total_wire_bytes = 0
        self.producer_cpu_units = 0
        self.broker_cpu_units = 0
        self.broker_recompressions = 0

    def _calc_codec(self, codec, level, s_raw, redundancy):
        if s_raw <= 0:
            return 0, 0, 0
        k = math.ceil(s_raw / 1024.0)
        r_frac = redundancy / 100.0

        if codec == "NONE":
            s_comp = s_raw
            cpu_comp = 0
            cpu_decomp = 0
        elif codec == "SNAPPY":
            c_eff = 1.0 - (r_frac * 0.55)
            s_comp = min(s_raw, math.floor(s_raw * c_eff)) + 24
            cpu_comp = k * 6
            cpu_decomp = k * 2
        elif codec == "LZ4":
            c_eff = 1.0 - (r_frac * 0.65)
            s_comp = min(s_raw, math.floor(s_raw * c_eff)) + 16
            cpu_comp = k * 8
            cpu_decomp = k * 2
        elif codec == "GZIP":
            c_eff = 1.0 - (r_frac * 0.80)
            s_comp = min(s_raw, math.floor(s_raw * c_eff)) + 32
            cpu_comp = k * 45
            cpu_decomp = k * 15
        elif codec == "ZSTD":
            eff_red = 0.70 + (level * 0.02)
            c_eff = 1.0 - (r_frac * eff_red)
            s_comp = min(s_raw, math.floor(s_raw * c_eff)) + 20
            cpu_comp = k * (10 + level * 3)
            cpu_decomp = k * 4
        else:
            s_comp = s_raw
            cpu_comp = 0
            cpu_decomp = 0

        return int(s_comp), int(cpu_comp), int(cpu_decomp)

    def _flush_current_batch(self):
        if self.curr_records == 0:
            return 0, 0

        flushed_rec = self.curr_records
        s_raw = self.curr_raw_bytes
        r_avg = self.curr_weighted_redundancy / s_raw if s_raw > 0 else 0.0

        # 1. Producer compression
        s_comp, p_cpu_comp, p_cpu_decomp = self._calc_codec(
            self.producer_codec, self.producer_zstd_level, s_raw, r_avg
        )

        batch_envelope = 20
        wire_bytes = s_comp + batch_envelope
        raw_bytes = s_raw + batch_envelope

        self.total_records += flushed_rec
        self.total_batches += 1
        self.raw_payload_bytes += s_raw
        self.total_raw_bytes += raw_bytes
        self.total_wire_bytes += wire_bytes
        self.producer_cpu_units += p_cpu_comp

        # 2. Broker handling
        if self.broker_codec == "PRODUCER" or self.broker_codec == self.producer_codec:
            # Zero-copy passthrough
            pass
        else:
            # Broker recompression hazard!
            # Broker must decompress from producer_codec
            b_decomp_cpu = p_cpu_decomp
            # Broker must recompress into broker_codec
            _, b_recomp_cpu, _ = self._calc_codec(
                self.broker_codec, self.broker_zstd_level, s_raw, r_avg
            )
            self.broker_cpu_units += (b_decomp_cpu + b_recomp_cpu)
            self.broker_recompressions += 1

        # Reset active batch
        self.curr_records = 0
        self.curr_raw_bytes = 0
        self.curr_weighted_redundancy = 0.0

        return flushed_rec, s_raw

    def set_producer_config(self, params):
        if self.curr_records > 0:
            self._flush_current_batch()

        if "batch_size" in params:
            self.producer_batch_size = int(params["batch_size"])
        if "codec" in params:
            self.producer_codec = params["codec"].upper()
        if "zstd_level" in params:
            self.producer_zstd_level = max(1, min(9, int(params["zstd_level"])))

        if self.producer_codec == "ZSTD":
            return f"PRODUCER_CONFIG_OK batch_size={self.producer_batch_size} codec=ZSTD level={self.producer_zstd_level}"
        return f"PRODUCER_CONFIG_OK batch_size={self.producer_batch_size} codec={self.producer_codec}"

    def set_broker_config(self, params):
        if "codec" in params:
            self.broker_codec = params["codec"].upper()
        if "zstd_level" in params:
            self.broker_zstd_level = max(1, min(9, int(params["zstd_level"])))
        return f"BROKER_CONFIG_OK codec={self.broker_codec}"

    def produce(self, count, size, redundancy):
        redundancy = max(0, min(100, redundancy))
        total_raw = count * size

        for _ in range(count):
            if self.curr_records > 0 and (self.curr_raw_bytes + size > self.producer_batch_size):
                self._flush_current_batch()

            self.curr_records += 1
            self.curr_raw_bytes += size
            self.curr_weighted_redundancy += (size * redundancy)

            if self.curr_raw_bytes >= self.producer_batch_size:
                self._flush_current_batch()

        return f"PRODUCE_OK records={count} total_raw_bytes={total_raw}"

    def flush(self):
        if self.curr_records == 0:
            return "FLUSH_OK idle"
        rec, raw = self._flush_current_batch()
        return f"FLUSH_OK flushed_records={rec} flushed_raw_bytes={raw}"

    def report(self):
        ratio = (self.total_wire_bytes / self.total_raw_bytes) if self.total_raw_bytes > 0 else 1.0

        wire_norm = self.total_wire_bytes / 1000.0
        cpu_norm = self.producer_cpu_units / 20.0

        if self.broker_recompressions > 0:
            bottleneck = "BROKER_DEGRADED"
        elif wire_norm > 2.0 * cpu_norm:
            bottleneck = "NETWORK_BOUND"
        elif cpu_norm > 2.0 * wire_norm:
            bottleneck = "CPU_BOUND"
        else:
            bottleneck = "BALANCED"

        lines = [
            "--- KAFKA_METRICS_REPORT ---",
            f"TOTAL_RECORDS: {self.total_records}",
            f"TOTAL_BATCHES: {self.total_batches}",
            f"RAW_PAYLOAD_BYTES: {self.raw_payload_bytes}",
            f"TOTAL_RAW_BYTES: {self.total_raw_bytes}",
            f"TOTAL_WIRE_BYTES: {self.total_wire_bytes}",
            f"COMPRESSION_RATIO: {ratio:.4f}",
            f"PRODUCER_CPU_UNITS: {self.producer_cpu_units}",
            f"BROKER_CPU_UNITS: {self.broker_cpu_units}",
            f"BROKER_RECOMPRESSIONS: {self.broker_recompressions}",
            f"BOTTLENECK: {bottleneck}",
            "--- END_REPORT ---"
        ]
        return "\n".join(lines)


def parse_kv(tokens):
    kv = {}
    for t in tokens:
        if "=" in t:
            k, v = t.split("=", 1)
            kv[k.strip().lower()] = v.strip()
    return kv


def main():
    sim = KafkaCompressionSimulator()
    for line in sys.stdin:
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        tokens = line.split()
        cmd = tokens[0].upper()

        if cmd == "PRODUCER_CONFIG":
            kv = parse_kv(tokens[1:])
            print(sim.set_producer_config(kv))
        elif cmd == "BROKER_CONFIG":
            kv = parse_kv(tokens[1:])
            print(sim.set_broker_config(kv))
        elif cmd == "PRODUCE":
            kv = parse_kv(tokens[1:])
            count = int(kv.get("count", 1))
            size = int(kv.get("size", 100))
            red = int(kv.get("redundancy", 50))
            print(sim.produce(count, size, red))
        elif cmd == "FLUSH":
            print(sim.flush())
        elif cmd == "REPORT":
            print(sim.report())
        elif cmd == "RESET":
            sim.reset()
            print("RESET_OK")


if __name__ == "__main__":
    main()
