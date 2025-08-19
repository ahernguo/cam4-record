#region includes
import json, logging, re, requests, sys, os
from datetime import datetime, timedelta
from livestreamer import Livestreamer
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from os import makedirs, path
from threading import Thread
from time import sleep
from typing import Dict, List
#endregion

#region definitions
save_dir: str = "D:\Cam4"
"the directory to saving video"
wanted: List[str] = []
"the `username` list to monitoring and recording"
monitor_interval: float = 60.0
"interval in seconds of scan `wanted` again"
recording: List[str] = []
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
    sp = filename.split(".")
    return f"{sp[0]}_{sp[2]}.{sp[1]}"

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

fileHdl = getDailyTextHandler("E:\\Cam4\\logs\\capture.log", 7)
csHdl = getConsoleHandler()
log = logging.getLogger("cam4_capture")
log.setLevel(logging.INFO)
log.addHandler(fileHdl)
log.addHandler(csHdl)
#endregion

#region methods
def isOnline(model: str) -> bool:
    """
    check `username` is online?
    @model: the `username` of Cam4
    @return: (True)on-line (False)off-line
    """
    try:
        log.info(f"checking {model} has online...")

        # result = requests.get(
        #     f"https://www.cam4.com/rest/v1.0/profile/{model}/info"
        # ).json()
        # online = bool(result["online"])
        
        result = reqSs.get(
            f"https://www.cam4.com/directoryCams?directoryJson=true&online=true&username={model}",
            headers=headers
        ).json()
        online = len(result) > 0

        log.info(f"    ...{'online' if online else 'offline'}")
        return online
    except:
        log.exception("getOnlineModel")

def startRecording(model: str) -> None:
    """
    Start recording to .mp4
    @model: the `username` of Cam4
    """
    try:
        log.info(f"{model} is online. catching stream info...")
        recording.append(model)
        stmInfo = reqSs.get(
            f"https://www.cam4.com/rest/v1.0/profile/{model}/streamInfo",
            headers=headers
        ).json()
        if stmInfo["canUseCDN"]:
            hlsurl = stmInfo["cdnURL"]
            log.info(f"caught cdnURL at {hlsurl}")

            session = Livestreamer()
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
                f"{model}_{st}.mp4"
            )
            
            with open(file, "wb") as f:
                log.info(f"starts to recording '{model}' on '{file}'")
                while True:
                    try:
                        data = fd.read(1024)
                        f.write(data)
                    except KeyboardInterrupt:
                        break
                    except:
                        log.exception("recording")
                        break
        else:
            log.info(f"{model} was in private show")
    except KeyboardInterrupt:
        return
    except:
        log.exception("startRecording")
    finally:
        log.info(f"stop to recording '{model}'")
        if model in recording:
            recording.remove(model)
#endregion

#region main
if __name__ == "__main__":
    lastTime = (datetime.now() - timedelta(seconds=monitor_interval))
    try:
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
        wanted = config["wanted"]
        # loop for monitoring
        while True:
            # if less than interval, sleep it
            if (datetime.now() - lastTime).total_seconds() < monitor_interval:
                sleep(10)
                continue
            lastTime = datetime.now()
            # check each `username`
            for model in wanted:
                if isOnline(model):
                    # if recording, just log it
                    if model in recording:
                        log.info(f"    {model} had recording...")
                        continue
                    # first time on-line, create a new thread to record
                    thread = Thread(target=startRecording, args=(model.lower(),))
                    thread.start()
                    # wait thread start. to prevent next `for-loop` too fast than add `recording`
                    while not thread.is_alive():
                        sleep(1)
    except KeyboardInterrupt:
        print("terminate")
#endregion