#region includes
import json, logging, re, requests, sys, os
import faulthandler
import media_output
import math
import shutil
import threading
from datetime import datetime
from livestreamer import Livestreamer
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from os import makedirs, path
from threading import Thread, Lock, Event
from time import sleep, monotonic, time_ns
from typing import Dict, List
#endregion

#region definitions
save_dir: str = "D:\\Cam4"
"the directory to saving video"
wanted: List[str] = []
"the `username` list to monitoring and recording"
monitor_interval: float = 60.0
"interval in seconds of scan `wanted` again"
recording: List[str] = []
recording_lock = Lock()
progress_lock = Lock()
progress = {}
stop_event = Event()
main_progress = monotonic()
last_scan = None
"indicate who is recording"
headers: Dict[str, str] = {"User-Agent": "Mozilla/5.0 (X11; CrOS x86_64 12871.102.0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/81.0.4044.141 Safari/537.36"}
"default header for requests"
reqSs: requests.Session = requests.session()
"the requests session for query information"
#endregion

#region log
def dailyLogNamer(filename: str) -> str:
    """
    Gets the rollover filename of log
    @filename: the filename to check rollover.
    @return: new filename to rollover.
    """
    original, date_suffix = filename.rsplit(".log.", 1)
    return f"{original}_{date_suffix}"

class LogFileTimedRotatingFileHandler(TimedRotatingFileHandler):

    def getFilesToDelete(self):
        """
        Determine the files to delete when rolling over.

        More specific than the earlier method, which just used glob.glob().
        """
        dirName, baseName = os.path.split(self.baseFilename)
        fileNames = os.listdir(dirName)
        result = []
        for fileName in fileNames:
            if self.extMatch.match(fileName):
                result.append(os.path.join(dirName, fileName))
        if len(result) < self.backupCount:
            result = []
        else:
            result.sort()
            result = result[:len(result) - self.backupCount]
        return result

def getDailyTextHandler(fileName: str, keepDays: int) -> LogFileTimedRotatingFileHandler:
    """
    Gets the LogFileTimedRotatingFileHandler with change on midnight
    @filename: The fully file path. E.g. '/mnt/sda1/Logs/tcp.log'
    @keepDays: How many logs of days to keep/backup
    @return: instance of `FileHandler`
    """

    # create the formatter with log format and its strftime
    fmtr = logging.Formatter(
        fmt = "%(asctime)s.%(msecs)03d %(levelname)-8s %(message)s",
        datefmt = "%d-%b-%Y %H:%M:%S"
    )

    # get file name without extension to build extMatch
    fn_no_ext = Path(fileName).stem

    # routine file hanlder. backup (rollover) each day at midnight
    hdl = LogFileTimedRotatingFileHandler(
        filename = fileName,
        when = "midnight",
        interval = 1,
        backupCount = keepDays
    )
    hdl.suffix = "%Y%m%d.log"
    hdl.namer = dailyLogNamer
    hdl.extMatch = re.compile(rf".*\b{fn_no_ext}_\d{{8}}\.log$")
    hdl.setFormatter(fmtr)
    return hdl

def getConsoleHandler() -> logging.StreamHandler:
    """
    Gets the StreamHandler that point to stdout
    @return: instance of `StreamHandler`
    """
    
    # create the formatter with log format and its strftime
    fmtr = logging.Formatter(
        fmt = "%(asctime)s.%(msecs)03d %(levelname)-8s %(message)s",
        datefmt = "%d-%b-%Y %H:%M:%S"
    )
    # create stdout stream handler
    hdl = logging.StreamHandler(sys.stdout)
    hdl.setFormatter(fmtr)
    return hdl

log_dir = Path(os.environ.get("CAM4_LOG_DIR", "E:\\Cam4\\logs"))
log_dir.mkdir(parents=True, exist_ok=True)
fileHdl = getDailyTextHandler(str(log_dir / "capture.log"), 7)
csHdl = getConsoleHandler()
log = logging.getLogger("cam4_capture")
log.setLevel(logging.INFO)
log.addHandler(fileHdl)
log.addHandler(csHdl)
#endregion

#region methods
def reportHealth() -> None:
    """Publish progress independently of the scanning and recording workers."""
    while not stop_event.is_set():
        now = monotonic()
        with progress_lock:
            workers = {name: dict(value) for name, value in progress.items()}
        unhealthy = now - main_progress > 180 or any(
            now - value["updated"] > 180 for value in workers.values())
        status = {"pid": os.getpid(), "updated": now,
                  "main_age": now - main_progress, "last_scan": last_scan,
                  "recordings": workers, "unhealthy": unhealthy,
                  "free_bytes": shutil.disk_usage(save_dir).free}
        log.info("heartbeat %s", json.dumps(status))
        if unhealthy:
            with open(log_dir / "stacks.log", "a", encoding="utf-8") as output:
                output.write(datetime.now().isoformat() + " stalled progress\n")
                output.flush()
                faulthandler.dump_traceback(file=output, all_threads=True)
        health_path = os.environ.get("CAM4_HEALTH_FILE")
        if health_path:
            target = Path(health_path)
            temporary = target.with_suffix(".tmp")
            temporary.write_text(json.dumps(status), encoding="utf-8")
            os.replace(temporary, target)
        stop_path = os.environ.get("CAM4_STOP_FILE")
        if stop_path and Path(stop_path).exists():
            stop_event.set()
        stop_event.wait(10)

def logThreadException(args) -> None:
    log.critical("uncaught thread exception: %s", args.thread.name,
                 exc_info=(args.exc_type, args.exc_value, args.exc_traceback))

def getStreamInfo(model: str) -> str:
    """
    Query user is online and return its stream url
    @model: the username to query info
    @returns: hlsurl
    """
    hlsurl: str = ""
    try:
        log.info(f"querying '{model}' ...")

        rsp = reqSs.get(
            f"https://www.cam4.com/rest/v1.0/profile/{model}/streamInfo",
            headers=headers,
            timeout=(10, 30)
        )
        rsp.raise_for_status()
        if rsp.ok and rsp.content:
            info = rsp.json()
            if info["canUseCDN"] and ("cdnURL" in info):
                hlsurl = info["cdnURL"]
                log.info(f"    ...{model} is online. caught cdnURL '{hlsurl}'")
            else:
                log.info(f"    ...{model} is online but no streaming")
    except Exception:
        log.exception("getStreamInfo")
    return hlsurl

def startRecording(model: str, hlsurl: str) -> None:
    """
    Start recording to .mp4
    @model: the `username` of Cam4
    @hlsurl: the 'cdnURL` of streaming
    """
    fd = None
    file = None
    try:
        log.info(f"starting to record '{model}' ...")
        if hlsurl:
            session = Livestreamer()
            session.set_option("http-timeout", 30.0)
            session.set_option("hls-segment-timeout", 15.0)
            session.set_option("hls-timeout", 60.0)
            session.set_option(
                "http-headers",
                f"referer=https://www.cam4.com/{model}"
            )
            streams = session.streams(
                f"hlsvariant://{hlsurl}"
            )
            stream = streams["best"]
            fd = stream.open()
            st = datetime.now().strftime("%Y%m%d_%H%M%S")
            tar_dir = path.join(
                save_dir,
                model
            )
            makedirs(tar_dir, exist_ok=True)
            file = path.join(
                save_dir,
                model,
                f"{model}_{st}_{time_ns()}.capture"
            )
            
            with open(file, "wb") as f:
                log.info(f"    recording '{model}' on '{file}'")
                while not stop_event.is_set():
                    try:
                        data = fd.read(64 * 1024)
                        if not data:
                            log.info("stream ended: %s", model)
                            break
                        f.write(data)
                        with progress_lock:
                            progress[model] = {
                                "updated": monotonic(),
                                "bytes": progress.get(model, {}).get("bytes", 0) + len(data)}
                    except KeyboardInterrupt:
                        break
                    except Exception:
                        log.exception("recording")
                        break
        else:
            log.info(f"{model} was in private show")
    except KeyboardInterrupt:
        return
    except Exception:
        log.exception("startRecording")
    finally:
        if fd is not None:
            try:
                fd.close()
            except Exception:
                log.exception("closing stream: %s", model)
        if file and path.exists(file):
            try:
                os.replace(file, str(Path(file).with_suffix(".source")))
            except OSError:
                log.exception("cannot publish capture for conversion: %s", file)
        log.info(f"stop to recording '{model}'")
        with progress_lock:
            progress.pop(model, None)
        with recording_lock:
            if model in recording:
                recording.remove(model)

def launchRecording(model: str, hlsurl: str) -> None:
    model = model.lower()
    with recording_lock:
        if model in recording:
            return
        recording.append(model)
    with progress_lock:
        progress[model] = {"updated": monotonic(), "bytes": 0}
    try:
        thread = Thread(target=startRecording, args=(model, hlsurl),
                        name=f"record-{model}", daemon=True)
        thread.start()
    except Exception:
        with recording_lock:
            recording.remove(model)
        with progress_lock:
            progress.pop(model, None)
        raise
#endregion

#region main
if __name__ == "__main__":
    threading.excepthook = logThreadException
    try:
        log.info("starting pid=%s python=%s", os.getpid(), sys.version)
        # loading setting
        curLoc = os.path.realpath(
            os.path.join(
                os.getcwd(),
                os.path.dirname(__file__)
            )
        )
        fn = os.path.join(curLoc, "setting.json")
        with open(fn, "rb") as fs:
            config = json.load(fs)
        save_dir = config["out_dir"]
        if (not save_dir):
            log.error("out_dir can not be empty or null. please setup in setting.json")
            exit(1)
        wanted = list(dict.fromkeys(model.lower() for model in config["wanted"]))
        if (not wanted) or (len(wanted) == 0):
            log.error("no wanted username. please setup in setting.json")
            exit(1)
        if "interval" in config:
            monitor_interval = float(config["interval"])
        if not math.isfinite(monitor_interval) or monitor_interval <= 0:
            raise ValueError("interval must be finite and positive")
        media_output.executable("ffmpeg")
        media_output.executable("ffprobe")
        makedirs(save_dir, exist_ok=True)
        Thread(target=media_output.worker, args=(save_dir, stop_event), name="media-output", daemon=True).start()
        main_progress = monotonic()
        Thread(target=reportHealth, name="health", daemon=True).start()
        # Rewind time monitor_interval seconds. so that can check online users on first execution
        lastTime = monotonic() - monitor_interval
        # loop for monitoring
        while not stop_event.is_set():
            main_progress = monotonic()
            # if less than interval, sleep it
            if monotonic() - lastTime < monitor_interval:
                stop_event.wait(min(10, monitor_interval))
                continue
            lastTime = monotonic()
            # check each `username`
            for model in wanted:
                main_progress = monotonic()
                if stop_event.is_set():
                    break
                # if recording, just log it
                with recording_lock:
                    is_recording = model in recording
                if is_recording:
                    log.info(f"    {model} had recording...")
                    continue
                # delay
                sleep(1)
                # check is online?
                hlsurl = getStreamInfo(model)
                if hlsurl:
                    launchRecording(model, hlsurl)
            last_scan = datetime.now().isoformat()
    except KeyboardInterrupt:
        log.info("termination requested")
    except Exception:
        log.exception("fatal main loop error")
        sys.exit(1)
    finally:
        stop_event.set()
        deadline = monotonic() + 70
        for worker in threading.enumerate():
            if worker.name.startswith("record-") or worker.name == "media-output":
                worker.join(max(0, deadline - monotonic()))
        reqSs.close()
        log.info("process stopping")
#endregion

