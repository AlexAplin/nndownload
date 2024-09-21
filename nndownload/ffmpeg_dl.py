"""ffmpeg subprocess for merging DMS streams to output."""

import re
import subprocess
from datetime import timedelta, datetime
from shutil import which
from typing import AnyStr, List

import ffmpeg
from rich.progress import Progress


class FfmpegDLException(Exception):
    """Raised when a download fails."""

class FfmpegExistsException(Exception):
    """Raised when ffmpeg is not found on the PATH."""

class FfmpegDL:
    """Send input streams for download to an `ffmpeg` subprocess."""

    FF_GLOBAL_ARGS = (
        "-progress",
        "-",
        "-nostats",
        "-y"
    )

    REGEX_TIME_GROUP = "([0-9]{2}:[0-9]{2}:[0-9]{2}[.[0-9]*]?)"
    REGEX_OUT_TIME = re.compile(
        r"out_time=[ ]*" + REGEX_TIME_GROUP
    )

    @classmethod
    def get_timedelta(cls, time_str: AnyStr, str_format: AnyStr = "%H:%M:%S.%f"):
        """Return a timedelta for a given time string"""

        t = datetime.strptime(time_str, str_format)
        return timedelta(hours=t.hour, minutes=t.minute, seconds=t.second, microseconds=t.microsecond)

    def __init__(self, streams: List, input_kwargs: List, output_path: AnyStr, output_kwargs: List, global_args: List = FF_GLOBAL_ARGS, ffmpeg_binary: AnyStr = "ffmpeg"):
        """Initialize a downloader to perform an ffmpeg conversion task."""

        self.ffmpeg_binary = ffmpeg_binary
        if not self.is_ffmpeg_on_path():
            raise FfmpegExistsException(f"`{self.ffmpeg_binary}` was not found on your PATH")

        inputs = []
        for stream in streams:
            stream_input = ffmpeg.input(stream, **input_kwargs)
            inputs.append(stream_input)
        stream_spec = ffmpeg.output(*inputs, output_path, **output_kwargs).global_args(*global_args)

        self.proc_args = ffmpeg._run.compile(stream_spec=stream_spec)
        self.proc: subprocess.Popen = None

    def is_ffmpeg_on_path(self):
        return which(self.ffmpeg_binary) is not None

    def load_subprocess(self):
        """Open an ffmpeg subprocess."""

        self.proc = subprocess.Popen(
            args=self.proc_args,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=False,
        )

    def convert(self, name: AnyStr, duration: float):
        """Perform an ffmpeg conversion while printing progress using rich.progress."""

        with Progress() as progress:
            task = progress.add_task(name, total=duration)
            self.load_subprocess()

            stdout_line = None
            prev_line = None
            while True:
                if self.proc.stdout is None:
                    continue
                if stdout_line:
                    prev_line = stdout_line
                stdout_line = self.proc.stdout.readline().decode("utf-8", errors="replace").strip()
                out_time_data = self.REGEX_OUT_TIME.search(stdout_line)
                if out_time_data is not None:
                    out_time = self.get_timedelta(out_time_data.group(1))
                    progress.update(task, completed=out_time.total_seconds())
                    continue
                if not stdout_line and self.proc.poll() is not None:
                    exit_code = self.proc.poll()
                    if exit_code:
                        raise FfmpegDLException(prev_line)
                    else:
                        break
