#!/usr/bin/env python3
"""
sysstat-recorder collector — periodically samples system metrics and stores in SQLite.
"""

import os
import time
import json
import sqlite3
import logging
import platform
import subprocess
from datetime import datetime
from pathlib import Path

try:
    import psutil
except ImportError:
    psutil = None
    print("WARNING: psutil not available — some metrics will be missing.")

logger = logging.getLogger("sysstat-collector")

DB_PATH = os.environ.get("SYSSTAT_DB", "/data/sysstat.db")
INTERVAL = int(os.environ.get("SYSSTAT_INTERVAL", "3600"))  # seconds (1 hour)
RETENTION_DAYS = int(os.environ.get("SYSSTAT_RETENTION", "60"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          REAL NOT NULL,          -- unix timestamp
    ts_text     TEXT NOT NULL,           -- ISO-8601
    cpu_percent REAL,
    cpu_count   INTEGER,
    load_1m     REAL, load_5m REAL, load_15m REAL,
    mem_total   INTEGER, mem_used INTEGER, mem_percent REAL,
    swap_total  INTEGER, swap_used INTEGER, swap_percent REAL,
    disk_total  INTEGER, disk_used INTEGER, disk_percent REAL,
    net_sent    INTEGER, net_recv INTEGER,
    procs       INTEGER,
    boot_ts     REAL,
    hostname    TEXT,
    extra       TEXT                    -- JSON blob for extensibility
);

CREATE INDEX IF NOT EXISTS idx_ts ON snapshots(ts);
"""


def init_db():
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


def collect(conn):
    """Sample system metrics and insert a row."""
    ts = time.time()
    ts_text = datetime.fromtimestamp(ts).isoformat()
    hostname = platform.node()

    cpu_pct = cpu_cnt = None
    load1 = load5 = load15 = None
    mem_tot = mem_used = mem_pct = None
    swap_tot = swap_used = swap_pct = None
    disk_tot = disk_used = disk_pct = None
    net_s = net_r = None
    procs = None
    boot_ts = None
    extra = {}

    if psutil:
        try:
            cpu_pct = psutil.cpu_percent(interval=0.5)
            cpu_cnt = psutil.cpu_count()
            mem = psutil.virtual_memory()
            mem_tot = mem.total
            mem_used = mem.used
            mem_pct = mem.percent
            swap = psutil.swap_memory()
            swap_tot = swap.total
            swap_used = swap.used
            swap_pct = swap.percent
            disk = psutil.disk_usage("/")
            disk_tot = disk.total
            disk_used = disk.used
            disk_pct = disk.percent
            net = psutil.net_io_counters()
            net_s = net.bytes_sent
            net_r = net.bytes_recv
            procs = len(psutil.pids())
            boot_ts = psutil.boot_time()

            # Temperatures if available
            try:
                temps = psutil.sensors_temperatures()
                if temps:
                    extra["temps"] = {
                        k: [{"label": s.label, "current": s.current}
                            for s in v]
                        for k, v in temps.items()
                    }
            except Exception:
                pass

            # Disk I/O
            try:
                io = psutil.disk_io_counters()
                if io:
                    extra["disk"] = {
                        "read_bytes": io.read_bytes,
                        "write_bytes": io.write_bytes,
                    }
            except Exception:
                pass

            # Top processes by CPU
            procs_list = sorted(
                psutil.process_iter(["pid", "name", "cpu_percent", "memory_percent"]),
                key=lambda p: p.info.get("cpu_percent") or 0,
                reverse=True,
            )[:10]
            extra["top_procs"] = [
                {
                    "pid": p.info["pid"],
                    "name": p.info["name"],
                    "cpu": p.info.get("cpu_percent") or 0,
                    "mem": p.info.get("memory_percent") or 0,
                }
                for p in procs_list
            ]
        except Exception as e:
            logger.warning("psutil collection error: %s", e)

    # Load avg from os module as fallback
    try:
        load1, load5, load15 = os.getloadavg()
    except AttributeError:
        pass

    conn.execute(
        """INSERT INTO snapshots
        (ts, ts_text, cpu_percent, cpu_count, load_1m, load_5m, load_15m,
         mem_total, mem_used, mem_percent, swap_total, swap_used, swap_percent,
         disk_total, disk_used, disk_percent, net_sent, net_recv, procs, boot_ts,
         hostname, extra)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            ts,
            ts_text,
            cpu_pct,
            cpu_cnt,
            load1,
            load5,
            load15,
            mem_tot,
            mem_used,
            mem_pct,
            swap_tot,
            swap_used,
            swap_pct,
            disk_tot,
            disk_used,
            disk_pct,
            net_s,
            net_r,
            procs,
            boot_ts,
            hostname,
            json.dumps(extra) if extra else None,
        ),
    )
    conn.commit()


def purge_old(conn):
    """Remove rows older than RETENTION_DAYS."""
    cutoff = time.time() - RETENTION_DAYS * 86400
    conn.execute("DELETE FROM snapshots WHERE ts < ?", (cutoff,))
    conn.commit()


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] %(levelname)s %(message)s",
    )
    logger.info("sysstat-recorder collector starting (interval=%ds, retention=%dd)", INTERVAL, RETENTION_DAYS)
    conn = init_db()

    while True:
        try:
            collect(conn)
            purge_old(conn)
        except Exception as e:
            logger.error("collection error: %s", e)
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
