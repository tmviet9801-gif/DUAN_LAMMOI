"""Thu thập metrics cho hệ thống mô phỏng."""
import time


class Metrics:
    def __init__(self):
        self.reset()

    def reset(self):
        self.total_rounds = 0
        self.main_first = 0
        self.main_not_first = 0
        self.join_ok = 0
        self.join_fail = 0
        self.timeouts = 0
        self.reconnects = 0
        self.pass_count = 0
        self.fail_count = 0
        self.cycle_times = []  # ms
        self._last_cycle_start = None

    def start_cycle(self):
        self._last_cycle_start = time.monotonic()

    def end_cycle(self):
        if self._last_cycle_start is not None:
            self.cycle_times.append(int((time.monotonic() - self._last_cycle_start) * 1000))
            self._last_cycle_start = None

    def record_first_move(self, expected, actual, ok):
        self.total_rounds += 1
        if actual == "main":
            self.main_first += 1
        else:
            self.main_not_first += 1
        if ok:
            self.pass_count += 1
        else:
            self.fail_count += 1

    def record_join(self, ok):
        if ok:
            self.join_ok += 1
        else:
            self.join_fail += 1

    def record_timeout(self):
        self.timeouts += 1

    def record_reconnect(self):
        self.reconnects += 1

    @property
    def first_move_accuracy(self) -> float:
        total = self.pass_count + self.fail_count
        return round(self.pass_count / total, 3) if total else 0.0

    def avg_cycle_ms(self) -> int:
        return int(sum(self.cycle_times) / len(self.cycle_times)) if self.cycle_times else 0

    def to_dict(self) -> dict:
        return {
            "total_rounds": self.total_rounds,
            "main_first": self.main_first,
            "main_not_first": self.main_not_first,
            "first_move_accuracy": self.first_move_accuracy,
            "join_ok": self.join_ok,
            "join_fail": self.join_fail,
            "timeouts": self.timeouts,
            "reconnects": self.reconnects,
            "pass_count": self.pass_count,
            "fail_count": self.fail_count,
            "avg_cycle_ms": self.avg_cycle_ms(),
        }
