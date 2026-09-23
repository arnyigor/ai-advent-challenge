"""Local periodic runner. VPS deployment uses systemd timers instead."""

import argparse
from datetime import datetime, timedelta, timezone
import json
import threading
import time

from digest import build_digest
from feed_store import DB_PATH, collect, connect


def utc_now():
    return datetime.now(timezone.utc)


def schedule_status(db_path=DB_PATH):
    db = connect(db_path)
    try:
        return [dict(row) for row in db.execute("SELECT job, interval_seconds, last_at, next_at, last_result FROM schedule_state ORDER BY job")]
    finally:
        db.close()


def set_schedule(job, interval, next_at, *, db_path=DB_PATH):
    db = connect(db_path)
    try:
        with db:
            db.execute("INSERT INTO schedule_state (job, interval_seconds, next_at) VALUES (?, ?, ?) ON CONFLICT(job) DO UPDATE SET interval_seconds=excluded.interval_seconds, next_at=excluded.next_at", (job, interval, next_at.isoformat()))
    finally:
        db.close()


def record_run(job, interval, result, *, db_path=DB_PATH):
    now = utc_now()
    db = connect(db_path)
    try:
        with db:
            db.execute("UPDATE schedule_state SET last_at=?, next_at=?, last_result=? WHERE job=?", (now.isoformat(), (now + timedelta(seconds=interval)).isoformat(), result, job))
    finally:
        db.close()


def run_schedule(*, collect_seconds=7200, digest_seconds=86400, db_path=DB_PATH, stop=None, job_lock=None, on_event=None):
    if collect_seconds < 1 or digest_seconds < 1:
        raise ValueError("Intervals must be positive")
    stop = stop or threading.Event()
    job_lock = job_lock or threading.Lock()
    due = {"collect": time.monotonic(), "digest": time.monotonic() + digest_seconds}
    intervals = {"collect": collect_seconds, "digest": digest_seconds}
    for job in due:
        set_schedule(job, intervals[job], utc_now() + timedelta(seconds=max(0, due[job] - time.monotonic())), db_path=db_path)
    while not stop.is_set():
        now = time.monotonic()
        for job in ("collect", "digest"):
            if now < due[job]:
                continue
            with job_lock:
                try:
                    value = collect(db_path=db_path) if job == "collect" else build_digest(db_path=db_path)
                    result = f"ok: {value['inserted']} new" if job == "collect" else f"ok: {value['provider']}"
                except ValueError as exc:
                    result = f"skipped: {exc}" if job == "digest" and "No new articles" in str(exc) else f"error: {type(exc).__name__}"
                except Exception as exc:
                    result = f"error: {type(exc).__name__}"
                record_run(job, intervals[job], result, db_path=db_path)
                if on_event:
                    on_event(job, result)
            due[job] = time.monotonic() + intervals[job]
        stop.wait(min(1, max(0.1, min(due.values()) - time.monotonic())))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--collect-seconds", type=int, default=7200)
    parser.add_argument("--digest-seconds", type=int, default=86400)
    args = parser.parse_args()
    try:
        run_schedule(collect_seconds=args.collect_seconds, digest_seconds=args.digest_seconds, on_event=lambda job, result: print(json.dumps({"job": job, "result": result}, ensure_ascii=False), flush=True))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
