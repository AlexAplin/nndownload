import regex as re
import subprocess
import warnings
from datetime import timedelta, datetime
from typing import AnyStr, List

import ffmpeg
from tqdm import TqdmExperimentalWarning
from tqdm.rich import tqdm_rich

warnings.filterwarnings("ignore", category=TqdmExperimentalWarning)


class FfmpegDLException(Exception):
    """Raised when a download fails."""
    pass


class FfmpegDL:
    """Send input streams for download to an `ffmpeg` subprocess."""

    FF_GLOBAL_ARGS = [
        "-progress",
        "-",
        "-nostats",
        "-y"
    ]

    REGEX_TIME_GROUP = "([0-9]{2}:[0-9]{2}:[0-9]{2}[.[0-9]*]?)"
    REGEX_OUT_TIME = re.compile(
        r"out_time=[ ]*" + REGEX_TIME_GROUP
    )

    @classmethod
    def get_timedelta(cls, time_str: AnyStr, str_format: AnyStr = "%H:%M:%S.%f"):
        t = datetime.strptime(time_str, str_format)
        return timedelta(hours=t.hour, minutes=t.minute, seconds=t.second, microseconds=t.microsecond)

    def __init__(self, streams: List, input_kwargs: List, output_path: AnyStr, output_kwargs: List, global_args: List = FF_GLOBAL_ARGS):
        inputs = []
        for stream in streams:
            input = ffmpeg.input(stream, **input_kwargs)
            inputs.append(input)
        stream_spec = ffmpeg.output(*inputs, output_path, **output_kwargs).global_args(*global_args)

        self.proc_args = ffmpeg._run.compile(stream_spec=stream_spec)
        self.proc: subprocess.Popen = None

    def load_subprocess(self):
        self.proc = subprocess.Popen(
            args=self.proc_args,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=False,
        )

    def convert(self, name: AnyStr, duration: float):
        progress = tqdm_rich(desc=name, unit="seg", colour="green", total=duration)

        self.load_subprocess()

        stdout_line = None
        while True:
            if self.proc.stdout is None:
                continue
            prev_line = stdout_line
            stdout_line = self.proc.stdout.readline().decode("utf-8", errors="replace").strip()
            out_time_data = self.REGEX_OUT_TIME.search(stdout_line)
            if out_time_data is not None:
                out_time = self.get_timedelta(out_time_data.group(1))
                progress.update(out_time.total_seconds() - progress.n)
                continue
            if stdout_line == "" and self.proc.poll() is not None:
                progress.refresh()
                progress.close()
                exit_code = self.proc.poll()
                if exit_code:
                    raise FfmpegDLException(prev_line)
                else:
                    break
