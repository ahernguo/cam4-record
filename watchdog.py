"""Run the recorder in a restartable process; use the same Python environment."""
import argparse
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import subprocess
import sys
import time


def stale_status(status, pid, now, timeout):
    return (status.get("pid") != pid or
            now - status["updated"] > timeout or
            status.get("unhealthy", False))


def stop_child(child, stop_path):
    stop_path.touch()
    try:
        child.wait(timeout=80)
    except subprocess.TimeoutExpired:
        child.kill()
        child.wait()


def run(log_dir):
    log_dir.mkdir(parents=True, exist_ok=True)
    # Holding this lock prevents two supervisors recording the same accounts.
    import msvcrt
    lock = open(log_dir / "watchdog.lock", "a+b")
    lock.seek(0)
    if not lock.read(1):
        lock.write(b"0")
        lock.flush()
    lock.seek(0)
    msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
    logger = logging.getLogger("watchdog")
    logger.setLevel(logging.INFO)
    handler = RotatingFileHandler(log_dir / "watchdog.log", maxBytes=2_000_000,
                                  backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
    health = log_dir / "health.json"
    stop_path = log_dir / "stop.request"
    child = None
    failures = 0
    try:
        while True:
            health.unlink(missing_ok=True)
            stop_path.unlink(missing_ok=True)
            env = dict(os.environ, CAM4_LOG_DIR=str(log_dir),
                       CAM4_HEALTH_FILE=str(health), CAM4_STOP_FILE=str(stop_path))
            # Preserve native crashes, import errors and logging failures outside E:.
            console = log_dir / "console.log"
            if console.exists() and console.stat().st_size > 10_000_000:
                console.replace(log_dir / "console.previous.log")
            started = time.monotonic()
            with open(console, "ab", buffering=0) as output:
                child = subprocess.Popen(
                    [sys.executable, "-u", str(Path(__file__).with_name("main.py"))],
                    env=env, stdout=output, stderr=subprocess.STDOUT,
                    creationflags=subprocess.CREATE_NO_WINDOW)
                logger.info("started pid=%s", child.pid)
                last_valid = started
                while child.poll() is None:
                    time.sleep(5)
                    now = time.monotonic()
                    try:
                        status = json.loads(health.read_text(encoding="utf-8"))
                        stale = stale_status(status, child.pid, now, 180)
                        if not stale:
                            last_valid = now
                    except (OSError, ValueError, KeyError, TypeError):
                        stale = now - last_valid > 180
                    if stale:
                        logger.error("stalled pid=%s; requesting shutdown", child.pid)
                        stop_child(child, stop_path)
                        break
                logger.error("child exited pid=%s code=%s", child.pid, child.returncode)
            failures = 0 if time.monotonic() - started > 600 else failures + 1
            time.sleep(min(60, 5 * 2 ** min(failures, 4)))
    except KeyboardInterrupt:
        logger.info("supervisor stopped by user")
    finally:
        if child is not None and child.poll() is None:
            stop_child(child, stop_path)
        lock.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log-dir", type=Path,
                        default=Path(__file__).resolve().parent / "logs")
    args = parser.parse_args()
    run(args.log_dir.resolve())
