"""Calibrate watts per busy core on this Mac, from its own power telemetry: idle, then N spinning cores, then idle
again, each window long enough for the coarse telemetry (~30-60 s per update) to move several times.

    python3 calibrate_core.py      -> results/green_core_w.json
"""
from __future__ import annotations

import json
import multiprocessing as mp
import time

from neo4d import green as Gr

WINDOW, CORES = 150, 4


def spin(stop_at: float) -> None:
    x = 0
    while time.time() < stop_at:
        x = (x * 1103515245 + 12345) & 0x7FFFFFFF


def mean_w(seconds: float) -> float:
    m = Gr.Meter(period=1.0)
    m.start()
    time.sleep(seconds)
    m.stop.set(); m.join()
    ps = [p for _, p in m.samples]
    return sum(ps) / len(ps) / 1000


def main() -> int:
    idle1 = mean_w(WINDOW)
    stop = time.time() + WINDOW
    procs = [mp.Process(target=spin, args=(stop,)) for _ in range(CORES)]
    for p in procs:
        p.start()
    busy = mean_w(WINDOW)
    for p in procs:
        p.join()
    idle2 = mean_w(WINDOW)
    idle = (idle1 + idle2) / 2
    w = (busy - idle) / CORES
    rec = {"w_per_busy_core": round(w, 2), "idle_w": [round(idle1, 2), round(idle2, 2)], "busy_w": round(busy, 2),
           "cores": CORES, "window_s": WINDOW,
           "note": f"{CORES} spinning cores for {WINDOW} s between two {WINDOW} s idle windows: "
                   f"{busy:.1f} W busy vs {idle1:.1f} / {idle2:.1f} W idle"}
    json.dump(rec, open(Gr.ROOT / "results/green_core_w.json", "w"), indent=1)
    print(json.dumps(rec))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
