"""
[Problem #164] PostgreSQL MVCC Transaction ID (TXID) Wraparound 재앙과 Autovacuum Freeze 비상 셧다운 방어
Solution Implementation

이 모듈은 PostgreSQL의 32비트 트랜잭션 ID(TXID) 순환 비교 모델,
MVCC 튜플 가시성 판정, relfrozenxid 및 datfrozenxid 추적,
autovacuum_freeze_max_age 강제 실행, 그리고 긴급 읽기 전용 셧다운(Emergency Read-Only Shutdown) 메커니즘을
정밀하게 시뮬레이션합니다.
"""

import json
import sys
from typing import Any, Dict, List, Optional

WRAPAROUND_HORIZON = 2**31  # 2,147,483,648 (2^31)


class PostgresTxidSimulator:
    """PostgreSQL 트랜잭션 ID 순환 및 Autovacuum Freeze 시뮬레이터."""

    def __init__(self, config: Dict[str, Any]):
        self.autovacuum_enabled = config.get("autovacuum_enabled", True)
        self.freeze_max_age = config.get("autovacuum_freeze_max_age", 200_000_000)
        self.freeze_min_age = config.get("vacuum_freeze_min_age", 50_000_000)
        self.emergency_stop_remaining = config.get("emergency_stop_remaining", 10_000_000)

        self.current_xid = config.get("initial_xid", 1000)
        self.state = "HEALTHY"  # 'HEALTHY', 'WARNING', 'EMERGENCY_READ_ONLY', 'WRAPAROUND_DATA_LOSS'

        self.tables: Dict[str, Dict[str, Any]] = {}
        for t_name, t_cfg in config.get("tables", {}).items():
            self.tables[t_name] = {
                "relfrozenxid": t_cfg.get("relfrozenxid", 100),
                "autovacuum_enabled": t_cfg.get("autovacuum_enabled", self.autovacuum_enabled),
                "tuples": [dict(t) for t in t_cfg.get("tuples", [])],
            }

        self.events_log: List[str] = []
        self.check_database_health()

    def get_datfrozenxid(self) -> int:
        """데이터베이스 전체에서 가장 오래된 unfrozen xid 산출."""
        if not self.tables:
            return self.current_xid
        return min(t["relfrozenxid"] for t in self.tables.values())

    def check_database_health(self):
        """데이터베이스 래핑어라운드 안전 한계 및 비상 상태 머신 갱신."""
        datfrozenxid = self.get_datfrozenxid()
        age = self.current_xid - datfrozenxid
        remaining = (WRAPAROUND_HORIZON - 1) - age

        if remaining <= 0:
            if self.state != "WRAPAROUND_DATA_LOSS":
                self.state = "WRAPAROUND_DATA_LOSS"
                self.events_log.append("SILENT_DATA_LOSS_DETECTED")
        elif remaining <= self.emergency_stop_remaining:
            if self.state not in ("EMERGENCY_READ_ONLY", "WRAPAROUND_DATA_LOSS"):
                self.state = "EMERGENCY_READ_ONLY"
                self.events_log.append("EMERGENCY_SHUTDOWN_TRIGGERED")
        elif age >= (WRAPAROUND_HORIZON - 100_000_000):
            if self.state != "WARNING":
                self.state = "WARNING"
                self.events_log.append("WARNING_APPROACHING_WRAPAROUND")
        else:
            if self.state in ("EMERGENCY_READ_ONLY", "WARNING"):
                self.state = "HEALTHY"
                self.events_log.append("HEALTH_RESTORED_POST_VACUUM")

    def is_visible(self, t: Dict[str, Any]) -> bool:
        """PostgreSQL 32비트 모듈로 순환 공간 기반 MVCC 가시성 판정."""
        if t["frozen"]:
            return True
        xmin = t["xmin"]
        diff = (self.current_xid - xmin) % (2**32)
        # 2^31 이전이면 과거(가시), 2^31 이상이면 미래(비가시/유실)
        return diff < WRAPAROUND_HORIZON

    def vacuum_table(self, table_name: str, force_freeze: bool = False, aggressive: bool = False):
        """특정 테이블에 대해 VACUUM FREEZE 수행."""
        if table_name not in self.tables:
            return
        t = self.tables[table_name]
        min_unfrozen = self.current_xid

        for tup in t["tuples"]:
            if not tup["frozen"]:
                age = self.current_xid - tup["xmin"]
                if force_freeze or aggressive or age >= self.freeze_min_age:
                    tup["frozen"] = True
                else:
                    min_unfrozen = min(min_unfrozen, tup["xmin"])

        t["relfrozenxid"] = min_unfrozen
        self.check_database_health()

    def autovacuum_tick(self):
        """Autovacuum 백그라운드 워커 주기 실행 및 anti-wraparound 강제 실행."""
        for t_name, t in self.tables.items():
            age = self.current_xid - t["relfrozenxid"]
            if age >= self.freeze_max_age:
                # autovacuum_enabled 설정을 무시하고 강제 실행되는 Anti-wraparound Vacuum
                self.events_log.append(f"AUTOVACUUM_WRAPAROUND_TRIGGERED:{t_name}")
                self.vacuum_table(t_name, aggressive=True)
            elif t["autovacuum_enabled"] and age >= self.freeze_min_age:
                self.vacuum_table(t_name, aggressive=False)

    def advance_transactions(self, xid_count: int, writes: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        """트랜잭션 실행 및 쓰기 작업 처리 (비상 정지 시 쓰기 거부)."""
        if self.state == "EMERGENCY_READ_ONLY":
            self.events_log.append("WRITE_REJECTED_DUE_TO_EMERGENCY_STOP")
            return {"status": "ERROR_EMERGENCY_READ_ONLY", "error": "database is not accepting commands"}
        elif self.state == "WRAPAROUND_DATA_LOSS":
            self.events_log.append("WRITE_REJECTED_DUE_TO_WRAPAROUND")
            return {"status": "ERROR_WRAPAROUND", "error": "database suffered wraparound"}

        self.current_xid += xid_count
        if writes:
            for w in writes:
                t_name = w["table"]
                if t_name in self.tables:
                    for tup_data in w["tuples"]:
                        self.tables[t_name]["tuples"].append({
                            "id": tup_data["id"],
                            "xmin": self.current_xid,
                            "frozen": False,
                        })
        self.check_database_health()
        return {"status": "SUCCESS", "current_xid": self.current_xid}

    def execute_query(self, table_name: str) -> Dict[str, Any]:
        """테이블 전수 스캔 및 MVCC 튜플 가시성/유실 여부 집계."""
        if table_name not in self.tables:
            return {"error": "Table not found"}
        t = self.tables[table_name]
        visible_tuples = []
        invisible_tuples = []
        for tup in t["tuples"]:
            if self.is_visible(tup):
                visible_tuples.append(tup["id"])
            else:
                invisible_tuples.append(tup["id"])
        return {
            "table": table_name,
            "visible_count": len(visible_tuples),
            "invisible_count": len(invisible_tuples),
            "invisible_tuple_ids": invisible_tuples,
        }

    def get_summary(self) -> Dict[str, Any]:
        datfrozenxid = self.get_datfrozenxid()
        max_age = self.current_xid - datfrozenxid
        remaining = max(0, (WRAPAROUND_HORIZON - 1) - max_age)

        table_summaries = {}
        for t_name, t in self.tables.items():
            frozen_cnt = sum(1 for tup in t["tuples"] if tup["frozen"])
            unfrozen_cnt = len(t["tuples"]) - frozen_cnt
            invis_cnt = sum(1 for tup in t["tuples"] if not self.is_visible(tup))
            table_summaries[t_name] = {
                "relfrozenxid": t["relfrozenxid"],
                "age": self.current_xid - t["relfrozenxid"],
                "frozen_count": frozen_cnt,
                "unfrozen_count": unfrozen_cnt,
                "invisible_count": invis_cnt,
            }

        return {
            "current_xid": self.current_xid,
            "database_state": self.state,
            "datfrozenxid": datfrozenxid,
            "max_age": max_age,
            "remaining_xids_to_stop": remaining,
            "events_log": self.events_log,
            "tables": table_summaries,
        }


def solve(input_data: Dict[str, Any]) -> Dict[str, Any]:
    """ZeliJudge Problem #164 solve 진입점."""
    sim = PostgresTxidSimulator(input_data["config"])
    for op in input_data.get("operations", []):
        op_type = op["type"]
        if op_type == "ADVANCE_TX":
            sim.advance_transactions(op.get("xid_count", 1), op.get("writes"))
        elif op_type == "AUTOVACUUM_TICK":
            sim.autovacuum_tick()
        elif op_type == "VACUUM_MANUAL":
            sim.vacuum_table(
                op["table"],
                force_freeze=op.get("force_freeze", False),
                aggressive=op.get("aggressive", False),
            )
        elif op_type == "QUERY":
            sim.execute_query(op["table"])
    return sim.get_summary()


if __name__ == "__main__":
    raw = sys.stdin.read().strip()
    if raw:
        inp = json.loads(raw)
        out = solve(inp)
        print(json.dumps(out, indent=2))
