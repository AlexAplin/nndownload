#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Download videos and process other links from Niconico (nicovideo.jp)."""
import argparse
import asyncio
import collections
import contextlib
import getpass
import json
import logging
import math
import mimetypes
import netrc
import os
import re
import shutil
import sys
import tempfile
import threading
import time
import xml.dom.minidom
from typing import AnyStr, List, Match

import aiohttp
import requests
from aiohttp_socks import ProxyConnector
from bs4 import BeautifulSoup
from mutagen.mp4 import MP4, MP4StreamInfoError
from requests.adapters import HTTPAdapter
from requests.utils import add_dict_to_cookiejar
from urllib3.util import Retry

from ffmpeg_dl import FfmpegDL, FfmpegDLException

__version__ = "1.16.1"
__author__ = "Alex Aplin"
__copyright__ = "Copyright 2024 Alex Aplin"
__license__ = "MIT"

MODULE_NAME = "nndownload"
HOST = "nicovideo.jp"

MY_URL = "https://www.nicovideo.jp/my"
# LOGIN_URL = "https://account.nicovideo.jp/api/v1/login?site=niconico"
LOGIN_URL = "https://account.nicovideo.jp/login/redirector?show_button_twitter=1&site=niconico&show_button_facebook=1&sec=header_pc&next_url=/"
VIDEO_URL = "https://nicovideo.jp/watch/{0}"
NAMA_URL = "https://live.nicovideo.jp/watch/{0}"
SERIES_URL = "https://www.nicovideo.jp/series/{0}"
CHANNEL_VIDEOS_URL = "https://ch.nicovideo.jp/{0}/video?page={1}"
CHANNEL_LIVES_URL = "https://ch.nicovideo.jp/{0}/live?page={1}"
CHANNEL_BLOMAGA_URL = "https://ch.nicovideo.jp/{0}/blomaga?page={1}"
CHANNEL_ARTICLE_URL = "https://ch.nicovideo.jp/article/{0}"
SEIGA_USER_ILLUST_URL = "https://seiga.nicovideo.jp/user/illust/{0}?page={1}"
SEIGA_USER_MANGA_URL = "https://seiga.nicovideo.jp/manga/list?user_id={0}&page={1}"  # Not all manga are not listed with /user/manga/{0}
SEIGA_IMAGE_URL = "https://seiga.nicovideo.jp/seiga/{0}"
SEIGA_MANGA_URL = "https://seiga.nicovideo.jp/comic/{0}"
SEIGA_CHAPTER_URL = "https://seiga.nicovideo.jp/watch/{0}"
SEIGA_SOURCE_URL = "https://seiga.nicovideo.jp/image/source/{0}"
SEIGA_CDN_URL = "https://lohas.nicoseiga.jp/"
TIMESHIFT_USE_URL = "https://live.nicovideo.jp/api/timeshift.ticket.use"
TIMESHIFT_RESERVE_URL = "https://live.nicovideo.jp/api/timeshift.reservations"

CONTENT_TYPE = r"(watch|mylist|user\/illust|user\/manga|user|comic|seiga|gate|article|channel|manga|illust|series)"
VALID_URL_RE = re.compile(r"https?://(?:(?:(?:(ch|sp|www|seiga)\.)|(?:(live[0-9]?|cas)\.))?"
                          rf"(?:(?:nicovideo\.jp/{CONTENT_TYPE}?)(?(3)/|))|(nico\.ms)/)"
                          r"((?:(?:[a-z]{2})?\d+)|[a-zA-Z0-9-]+?)/?(?:/(video|mylist|live|blomaga|list))?"
                          r"(?(6)/((?:[a-z]{2})?\d+))?(?:\?(?:user_id=(.*)|.*)?)?$")
M3U8_STREAM_RE = re.compile(r"(?:(?:#EXT-X-STREAM-INF)|#EXT-X-I-FRAME-STREAM-INF):.*(?:BANDWIDTH=(\d+)).*\n(.*)")
M3U8_MEDIA_RE = re.compile(r"(?:#EXT-X-MEDIA:TYPE=)(?:(\w+))(?:.*),URI=\"(.*)\"")
M3U8_KEY_RE = re.compile(r"((?:#EXT-X-KEY)(?:.*),?URI=\")(.*)\"(.*)")
M3U8_MAP_RE = re.compile(r"((?:#EXT-X-MAP)(?:.*),?URI=\")(.*)\"(.*)")
SEIGA_DRM_KEY_RE = re.compile(r"/image/([a-z0-9]+)")
SEIGA_USER_ID_RE = re.compile(r"user_id=(\d+)")
SEIGA_MANGA_ID_RE = re.compile(r"/comic/(\d+)")

THUMB_INFO_API = "http://ext.nicovideo.jp/api/getthumbinfo/{0}"
MYLIST_API = "https://nvapi.nicovideo.jp/v2/mylists/{0}?pageSize=500"  # 500 video limit for premium mylists
VIDEO_DMS_WATCH_API = "https://nvapi.nicovideo.jp/v1/watch/{0}/access-rights/hls?actionTrackId={1}"
USER_VIDEOS_API = "https://nvapi.nicovideo.jp/v1/users/{0}/videos?sortKey=registeredAt&sortOrder=desc&pageSize={1}&page={2}"
USER_MYLISTS_API = "https://nvapi.nicovideo.jp/v1/users/{0}/mylists"
SEIGA_MANGA_TAGS_API = "https://seiga.nicovideo.jp/ajax/manga/tag/list?id={0}"
COMMENTS_API = "https://nv-comment.nicovideo.jp/v1/threads"
COMMENTS_API_POST_DATA = "{{\'params\':{0},\'threadKey\':\'{1}\',\'additionals\':{{}}}}"

REGION_LOCK_ERRORS = {  "お住まいの地域・国からは視聴することができません。",
                        "この動画は投稿( アップロード )された地域と同じ地域からのみ視聴できます。"
                     }

USER_VIDEOS_API_N = 25
NAMA_HEARTBEAT_INTERVAL_S = 30
NAMA_PLAYLIST_INTERVAL_S = 5
DMC_HEARTBEAT_INTERVAL_S = 15
KILOBYTE = 1024
KILOBIT = 1000
BLOCK_SIZE = 1024
EPSILON = 0.0001
RETRY_ATTEMPTS = 5
BACKOFF_FACTOR = 2  # retry_timeout_s = BACKOFF_FACTOR * (2 ** ({RETRY_ATTEMPTS} - 1))

MIMETYPES = {
    "image/gif": "gif",
    "image/jpeg": "jpg",
    "image/png": "png"
}

HTML5_COOKIE = {
    "watch_flash": "0"
}

FLASH_COOKIE = {
    "watch_flash": "1"
}

EN_COOKIE = {
    "lang": "en-us"
}

TW_COOKIE = {
    "lang": "zh-tw"
}

API_HEADERS = {
    "X-Frontend-Id": "6",
    "X-Frontend-Version": "0",
    "X-Niconico-Language": "ja-jp"
}

NAMA_ORIGIN_HEADER = {"Origin": "https://live2.nicovideo.jp"}

NAMA_PERMIT_FRAME = json.loads("""
{
    "type": "startWatching",
    "data": {
        "stream": {
            "quality": "super_high",
            "protocol": "hls",
            "latency": "low",
            "chasePlay": false
        },
        "room": {
            "protocol": "webSocket",
            "commentable": true
        },
        "reconnect": false
    }
}
""")

NAMA_QUALITY_FRAME = json.loads("""
{
    "type": "changeStream",
    "data": {
        "quality": "{0}",
        "protocol": "hls",
        "latency": "low",
        "chasePlay": false
    }
}
""")

NAMA_WATCHING_FRAME = json.loads("""{"type": "keepSeat"}""")

PONG_FRAME = json.loads("""{"type":"pong"}""")

logger = logging.getLogger(__name__)

cmdl_usage = "%(prog)s [options] input"
cmdl_version = __version__
cmdl_parser = argparse.ArgumentParser(usage=cmdl_usage, conflict_handler="resolve")

cmdl_parser.add_argument("-u", "--username", dest="username", metavar="EMAIL/TEL",
                         help="account email address or telephone number")
cmdl_parser.add_argument("-p", "--password", dest="password", metavar="PASSWORD", help="account password")
cmdl_parser.add_argument("--session-cookie", dest="session_cookie", metavar="COOKIE", help="user_session cookie value (string or filepath)")
cmdl_parser.add_argument("-n", "--netrc", action="store_true", dest="netrc", help="use .netrc authentication")
cmdl_parser.add_argument("-q", "--quiet", action="store_true", dest="quiet", help="suppress output to console")
cmdl_parser.add_argument("-l", "--log", action="store_true", dest="log", help="log output to file")
cmdl_parser.add_argument("-v", "--version", action="version", version=cmdl_version)
cmdl_parser.add_argument("input", action="store", nargs="*", help="URLs or files")

dl_group = cmdl_parser.add_argument_group("download options")
dl_group.add_argument("-y", "--proxy", dest="proxy", metavar="PROXY", help="http or socks proxy")
dl_group.add_argument("-o", "--output-path", dest="output_path", metavar="TEMPLATE",
                      help="custom output path (see template options)")
dl_group.add_argument("-r", "--threads", dest="threads", metavar="N", type=int,
                      help="download videos using a specified number of threads")
dl_group.add_argument("-g", "--no-login", action="store_true", dest="no_login",
                      help="create a download session without logging in")
dl_group.add_argument("-f", "--force-high-quality", action="store_true", dest="force_high_quality",
                      help="only download if the high quality video source is available")
dl_group.add_argument("-a", "--add-metadata", action="store_true", dest="add_metadata",
                      help="add metadata to video file (MP4 only)")
dl_group.add_argument("-m", "--dump-metadata", action="store_true", dest="dump_metadata", help="dump metadata to file")
dl_group.add_argument("-t", "--download-thumbnail", action="store_true", dest="download_thumbnail",
                      help="download video thumbnail")
dl_group.add_argument("-c", "--download-comments", action="store_true", dest="download_comments",
                      help="download video comments")
dl_group.add_argument("-e", "--english", action="store_true", dest="download_english",
                      help="request video on english site")
dl_group.add_argument("--chinese", action="store_true", dest="download_chinese",
                      help="request video on traditional chinese (taiwan) site")
dl_group.add_argument("-aq", "--audio-quality", dest="audio_quality", help="specify audio quality")
dl_group.add_argument("-vq", "--video-quality", dest="video_quality", help="specify video quality")
dl_group.add_argument("-an", "--no-audio", action="store_true", dest="no_audio", help="don't download audio")
dl_group.add_argument("-vn", "--no-video", action="store_true", dest="no_video", help="don't download video")
dl_group.add_argument("-Q", "--list-qualities", action="store_true", dest="list_qualities", help="list video and audio qualities with availability status")
dl_group.add_argument("-s", "--skip-media", action="store_true", dest="skip_media", help="skip downloading media")
dl_group.add_argument("--break-on-existing", action="store_true", dest="break_on_existing", help="break after encountering an existing download")
dl_group.add_argument("--playlist-start", dest="playlist_start", metavar="N", type=int, default=0,
                      help="specify the index to start a list of items from (begins at 0)")


# Globals

_start_time = _progress = 0
_cmdl_opts = None


class AuthenticationException(Exception):
    """Raised when logging in to Niconico failed."""
    pass


class ArgumentException(Exception):
    """Raised when reading the argument failed."""
    pass


class FormatNotSupportedException(Exception):
    """Raised when the response format is not supported."""
    pass


class FormatNotAvailableException(Exception):
    """Raised when the requested format is not available."""
    pass


class ParameterExtractionException(Exception):
    """Raised when parameters could not be successfully extracted."""
    pass

class ExistingDownloadEncounteredQuit(Exception):
    """Raised when an existing and complete download is encountered."""
    pass

class ListQualitiesQuit(Exception):
    """Raised when listing available qualities for a video."""
    pass


## Utility methods

def configure_logger():
    """Initialize logger."""

    if _cmdl_opts.log:
        logger.setLevel(logging.INFO)
        log_handler = logging.FileHandler(f"[{MODULE_NAME}] {time.strftime('%Y-%m-%d')}.log", encoding="utf-8")
        formatter = logging.Formatter("%(asctime)s %(levelname)s: %(message)s")
        log_handler.setFormatter(formatter)
        logger.addHandler(log_handler)


def log_exception(error: Exception):
    """Process exception for logger."""

    if _cmdl_opts.log:
        sys.stdout.write("{0}: {1}\n".format(type(error).__name__, str(error)))
        sys.stdout.flush()
        logger.exception("An exception was encountered:\n".format(type(error).__name__, str(error)))
    else:
        output("{0}: {1}\n".format(type(error).__name__, str(error)), logging.ERROR, force=True)


def output(string: AnyStr, level=logging.INFO, force: bool = False):
    """Print status to console unless quiet flag is set."""

    global _cmdl_opts
    if _cmdl_opts.log:
        logger.log(level, string.strip("\n"))

    if not _cmdl_opts.quiet or force:
        sys.stdout.write(string)
        sys.stdout.flush()


def format_value(value: int, custom_type: str = "B", use_bits: bool = False):
    """Attach suffix (e.g. 10 T) to number of bytes."""

    base = KILOBIT if use_bits else KILOBYTE

    try:
        exponent = int(math.log(value, base))
        suffix = "\0KMGTPE"[exponent]
        suffix = suffix.lower() if use_bits else suffix

        if exponent == 0:
            return "{0}{1}".format(value, suffix)

        converted = float(value / base ** exponent)
        return "{0:.2f}{1}{2}".format(converted, suffix, custom_type) if not use_bits else "{0}{1}{2}".format(converted, suffix, custom_type)

    except IndexError:
        raise IndexError("Could not format number of bytes")


def calculate_speed(start, now, prog_bytes):
    """Calculate speed based on difference between start and current block call."""

    dif = now - start
    if prog_bytes == 0 or dif < EPSILON:
        return "N/A B"
    return format_value(prog_bytes / dif)


def replace_extension(filename: AnyStr, new_extension: AnyStr):
    """Replace the extension in a file path."""

    base_path, _ = os.path.splitext(filename)
    return "{0}.{1}".format(base_path, new_extension)


def sanitize_for_path(value: AnyStr, replace: AnyStr = ' '):
    """Remove potentially illegal characters from a path."""

    return re.sub(r'[<>\"\?\\/\*:|]', replace, value).strip()


def create_filename(template_params: dict, is_comic: bool = False):
    """Create filename from document parameters."""

    filename_template = _cmdl_opts.output_path

    if filename_template:
        template_dict = dict(template_params)
        template_dict = dict((k, sanitize_for_path(str(v))) for k, v in template_dict.items() if v)
        template_dict = collections.defaultdict(lambda: "__NONE__", template_dict)

        filename = filename_template.format_map(template_dict).strip()
        if is_comic:
            os.makedirs(filename, exist_ok=True)
        elif (os.path.dirname(filename) and not os.path.exists(os.path.dirname(filename))) or os.path.exists(
                os.path.dirname(filename)):
            os.makedirs(os.path.dirname(filename), exist_ok=True)

        return filename

    elif is_comic:
        directory = os.path.join(
            "{0} - {1}".format(template_params["manga_id"], sanitize_for_path(template_params["manga_title"])),
            "{0} - {1}".format(template_params["id"], sanitize_for_path(template_params["title"]))).strip()
        os.makedirs(directory, exist_ok=True)
        return directory

    else:
        filename = "{0} - {1}.{2}".format(template_params["id"], template_params["title"], template_params["ext"])
        return sanitize_for_path(filename)


def read_file(session: requests.Session, file: AnyStr):
    """Read file and process each line as a URL."""

    with open(file) as file:
        content = file.readlines()

    total_lines = len(content)
    for index, line in enumerate(content):
        try:
            output("{0}/{1}\n".format(index + 1, total_lines), logging.INFO)
            url_mo = VALID_URL_RE.match(line)
            if url_mo is None:
                raise ArgumentException("URL argument is not of a known or accepted type of Nico URL")
            process_url_mo(session, url_mo)

        except (FormatNotSupportedException, FormatNotAvailableException, ParameterExtractionException) as error:
            log_exception(error)
            continue


def get_media_from_manifest(manifest_text: AnyStr, media_type: AnyStr) -> AnyStr:
    """Return the first seen media match for a given type from a .m3u8 manifest."""

    media_type = media_type.capitalize()
    match = M3U8_MEDIA_RE.search(manifest_text)

    if not match:
        raise FormatNotAvailableException("Could not retrieve media playlist from manifest")

    media_url = match[2]
    return media_url


def get_stream_from_manifest(manifest_text: AnyStr) -> AnyStr:
    """Return the highest quality stream from a .m3u8 manifest."""

    best_bandwidth, best_stream = -1, None
    matches = M3U8_STREAM_RE.findall(manifest_text)

    if not matches:
        raise FormatNotAvailableException("Could not retrieve stream playlist from manifest")

    else:
        for match in matches:
            stream_bandwidth = int(match[0])
            if stream_bandwidth > best_bandwidth:
                best_bandwidth = stream_bandwidth
                best_stream = match[1]

    return best_stream


def find_extension(mimetype: AnyStr) -> AnyStr:
    """Determine the file extension from the mimetype."""

    return MIMETYPES.get(mimetype) or mimetypes.guess_extension(mimetype, strict=True)


def generic_dl_request(session: requests.Session, uri: AnyStr, filename: AnyStr, binary: bool=False):
    """Generic request to download and write to file."""

    request = session.get(uri)
    request.raise_for_status()
    request_body = request.content if binary else request.text
    mode = "wb" if binary else "w"
    with open(filename, mode) as file:
        file.write(request_body)
    return request_body


def rewrite_file(filename: AnyStr, old_str: AnyStr, new_str: AnyStr):
    """Replace a string in a text file."""

    with open(filename, "r+") as file:
        raw = file.read()
        new = raw.replace(old_str, new_str)
        file.seek(0)
        file.write(new)
        file.truncate()


@contextlib.contextmanager
def get_temp_dir():
    """Get a temporary working directory."""

    tmpdir = tempfile.mkdtemp()
    try:
        yield tmpdir
    finally:
        shutil.rmtree(tmpdir)


## Nama methods

def generate_stream(session: requests.Session, master_url: AnyStr) -> AnyStr:
    """Output the highest quality stream URL for a live Niconama broadcast."""

    output("Retrieving master playlist...\n", logging.INFO)

    m3u8_request = session.get(master_url)
    m3u8_request.raise_for_status()

    output("Retrieved master playlist.\n", logging.INFO)

    playlist_slug = get_stream_from_manifest(m3u8_request.text)
    stream_url = master_url.rsplit("/", maxsplit=1)[0] + "/" + playlist_slug

    return stream_url


async def download_stream_clips(session: requests.Session, stream_url: AnyStr):
    """Download the clips associated with a stream playlist and stitch them into a file."""

    # TODO: Determine end condition, stitch downloads together, end task on completion
    while True:
        stream_request = session.get(stream_url)
        stream_request.raise_for_status()
        # stream_length = re.search(r"(?:#STREAM-DURATION:)(.*)", stream_request.text)[1]

        clip_matches = re.compile(r"(?:#EXTINF):.*\n(.*)").findall(stream_request.text)
        if not clip_matches:
            raise FormatNotAvailableException("Could not retrieve stream clips from playlist")

        # else:
        # for match in clip_matches:
        # output("{0}\n".format(match), logging.DEBUG)
        # clip_slug = match
        # clip_url = stream_url.rsplit("/", maxsplit=1)[0] + "/" + clip_slug

        await asyncio.sleep(NAMA_PLAYLIST_INTERVAL_S)


async def perform_nama_heartbeat(websocket: aiohttp.ClientWebSocketResponse, watching_frame: dict):
    """Send a watching frame periodically to keep the stream alive."""

    while True:
        await websocket.send_str(json.dumps(watching_frame))
        # output("Sending watching frame.\n", logging.DEBUG)
        await asyncio.sleep(NAMA_HEARTBEAT_INTERVAL_S)


async def open_nama_websocket(
        session: requests.Session,
        uri: AnyStr, event_loop: asyncio.AbstractEventLoop,
        is_timeshift: bool = False
):
    """Open a WebSocket connection to receive and generate the stream playlist URL."""

    proxy = session.proxies.get("http://")  # Same mount as https://
    connector = ProxyConnector.from_url(proxy) if proxy else None
    async with aiohttp.ClientSession(connector=connector) as websocket_session:
        async with websocket_session.ws_connect(uri) as websocket:
            await websocket.send_str(json.dumps(NAMA_PERMIT_FRAME))
            heartbeat = event_loop.create_task(perform_nama_heartbeat(websocket, NAMA_WATCHING_FRAME))

            try:
                while True:
                    message = await websocket.receive()
                    if message.type == aiohttp.WSMsgType.CLOSED:
                        output("Connection closed by the server. Exiting...\n", logging.INFO)
                        break

                    if message.type == aiohttp.WSMsgType.ERROR:
                        raise FormatNotAvailableException("Nama connection closed by server with error")

                    if message.type != aiohttp.WSMsgType.TEXT:
                        continue

                    frame = json.loads(message.data)
                    frame_type = frame["type"]

                    # output("SERVER: {0}\n".format(frame), logging.DEBUG)

                    if frame_type == "stream":
                        master_url = frame["data"]["uri"]
                        stream_url = generate_stream(session, master_url)

                        if is_timeshift:
                            output("Downloading timeshifts is not currently supported.\n", logging.WARNING)
                            break
                            # event_loop.create_task(download_stream_clips(session, stream_url)
                        output(
                            "Generated stream URL. Please keep this window open to keep the stream active. Press ^C to exit.\n",
                            logging.INFO)
                        output("For more instructions on playing this stream, please consult the README.\n",
                               logging.INFO)
                        output("{0}\n".format(stream_url), logging.INFO, force=True)

                    elif frame_type == "disconnect":
                        command_param = frame["body"]["params"][1]
                        output(f"Disconnect command sent by the server with parameter \"{command_param}\". Exiting...", logging.INFO)
                        break

                    elif frame_type == "ping":
                        # output("Responding to ping frame.\n", logging.DEBUG)
                        await websocket.send_str(json.dumps(PONG_FRAME))

            finally:
                heartbeat.cancel()
                return


def reserve_timeshift(session: requests.Session, nama_id: AnyStr) -> AnyStr:
    """Attempt to reserve a timeshift and generate a WebSocket URL."""

    timeshift_data = {"vid": nama_id.lstrip("lv")}

    timeshift_use_request = session.post(TIMESHIFT_USE_URL, headers=NAMA_ORIGIN_HEADER, data=timeshift_data)
    if timeshift_use_request.status_code == 403:
        timeshift_data["overwrite"] = "0"

        timeshift_reservation_request = session.post(TIMESHIFT_RESERVE_URL, headers=NAMA_ORIGIN_HEADER,
                                                     data=timeshift_data)
        timeshift_reservation_request.raise_for_status()

    nama_request = session.get(NAMA_URL.format(nama_id))
    nama_request.raise_for_status()

    nama_document = BeautifulSoup(nama_request.text, "html.parser")
    params = json.loads(nama_document.find(id="embedded-data")["data-props"])
    websocket_url = params["site"]["relive"]["webSocketUrl"]
    if not websocket_url:
        raise FormatNotAvailableException("Failed to use timeshift ticket")

    return websocket_url


def request_nama(session: requests.Session, nama_id: AnyStr):
    """Generate a stream URL for a live Niconama broadcast."""

    nama_request = session.get(NAMA_URL.format(nama_id))
    nama_request.raise_for_status()

    nama_document = BeautifulSoup(nama_request.text, "html.parser")

    if nama_document.find(id="embedded-data"):
        params = json.loads(nama_document.find(id="embedded-data")["data-props"])

        rejection_errors = params["userProgramWatch"]["rejectedReasons"]
        if rejection_errors:
            raise ParameterExtractionException(f"Stream not available to user with the following errors given: {rejection_errors}")

        websocket_url = params["site"]["relive"]["webSocketUrl"]
        event_loop = asyncio.get_event_loop()

        if params["program"]["status"] == "ENDED":
            if not websocket_url:
                websocket_url = reserve_timeshift(session, nama_id)
            event_loop.run_until_complete(
                open_nama_websocket(session, websocket_url, event_loop, is_timeshift=True))

        elif params["program"]["status"] == "ON_AIR":
            event_loop.run_until_complete(
                open_nama_websocket(session, websocket_url, event_loop, is_timeshift=False))

    else:
        raise FormatNotAvailableException("Could not retrieve nama info")


## Seiga methods

def decrypt_seiga_drm(enc_bytes, key):
    """Decrypt the light DRM applied to certain Seiga images."""

    n = []
    a = 8

    for i in range(a):
        start = 2 * i
        value = int(key[start:start + 2], 16)
        n.append(value)

    dec_bytes = bytearray(enc_bytes)
    for i in range(len(enc_bytes)):
        dec_bytes[i] = dec_bytes[i] ^ n[i % a]

    return dec_bytes


def determine_seiga_file_type(dec_bytes):
    """Determine the image file type from a bytes array using magic numbers."""

    if 255 == dec_bytes[0] and 216 == dec_bytes[1] and 255 == dec_bytes[len(dec_bytes) - 2] and 217 == dec_bytes[len(dec_bytes) - 1]:
        return "jpg"
    elif 137 == dec_bytes[0] and 80 == dec_bytes[1] and 78 == dec_bytes[2] and 71 == dec_bytes[3]:
        return "png"
    elif 71 == dec_bytes[0] and 73 == dec_bytes[1] and 70 == dec_bytes[2] and 6 == dec_bytes[3]:
        return "gif"
    else:
        raise FormatNotSupportedException("Could not determine image file type")


def collect_seiga_image_parameters(session: requests.Session, document: BeautifulSoup, template_params: dict) -> dict:
    """Extract template parameters from a Seiga image page."""

    template_params["id"] = document.select("#clip_group_list")[0]["data-target_id"]
    template_params["title"] = document.select("h1.title")[0].text
    template_params["description"] = document.select("p.discription")[0].text
    template_params["published"] = document.select("span.created")[0].text
    template_params["uploader"] = document.select("li.user_name strong")[0].text
    template_params["uploader_id"] = int(document.select("li.user_link a")[0]["href"].replace("/user/illust/", ""))
    template_params["view_count"] = int(document.select("li.view span.count_value")[0].text)
    template_params["comment_count"] = int(document.select("li.comment span.count_value")[0].text)
    template_params["clip_count"] = int(document.select("li.clip span.count_value")[0].text)
    template_params["tags"] = document.select("meta[name=\"keywords\"]")[0]["content"]
    template_params["document_url"] = SEIGA_IMAGE_URL.format(template_params["id"])

    seiga_source_request = session.get(SEIGA_SOURCE_URL.format(template_params["id"].lstrip("im")))
    seiga_source_request.raise_for_status()
    seiga_source_document = BeautifulSoup(seiga_source_request.text, "html.parser")

    source_url_relative = seiga_source_document.select("div.illust_view_big")[0]["data-src"]
    template_params["url"] = source_url_relative

    source_image_request = session.get(template_params["url"])
    source_image_request.raise_for_status()
    mimetype = source_image_request.headers["Content-Type"]
    template_params["ext"] = find_extension(mimetype)

    return template_params


def collect_seiga_manga_parameters(session, document, template_params):
    """Extract template parameters from a Seiga manga chapter page."""

    bare_chapter_id = document.select("#full_watch_head_bar")[0]["data-theme-id"]
    template_params["manga_id"] = int(document.select("#full_watch_head_bar")[0]["data-content-id"])
    template_params["manga_title"] = document.select("div.manga_title a")[0].text
    template_params["id"] = "mg" + bare_chapter_id
    template_params["page_count"] = int(document.select("#full_watch_head_bar")[0]["data-page-count"])
    template_params["title"] = document.select("span.episode_title")[0].text
    template_params["published"] = document.select("span.created")[0].text
    template_params["description"] = document.select("div.description .full")[0].text
    template_params["comment_count"] = int(document.select("#comment_count")[0].text)
    template_params["view_count"] = int(document.select("#view_count")[0].text)
    template_params["uploader"] = document.select("span.author_name")[0].text
    template_params["document_url"] = SEIGA_CHAPTER_URL.format(template_params["id"])

    tags = []
    tags_request = session.get(SEIGA_MANGA_TAGS_API.format(bare_chapter_id))
    tags_request.raise_for_status()
    tags_json = tags_request.json()
    if tags_json.get("tag_list"):
        for tag in tags_json["tag_list"]:
            tags.append(tag["name"])
    template_params["tags"] = tags

    # No uploader ID for official manga uploads
    if document.select("dd.user_name a"):
        template_params["uploader_id"] = int(SEIGA_USER_ID_RE.search(document.select("dd.user_name a")[0]["href"]).group(1))

    return template_params


def download_manga_chapter(session, chapter_id):
    """Download the requested chapter for a Seiga manga."""

    chapter_request = session.get(SEIGA_CHAPTER_URL.format(chapter_id))
    chapter_request.raise_for_status()

    chapter_document = BeautifulSoup(chapter_request.text, "html.parser")

    template_params = {}
    template_params = collect_seiga_manga_parameters(session, chapter_document, template_params)
    chapter_directory = create_filename(template_params, is_comic=True)

    if not _cmdl_opts.skip_media:
        output("Downloading {0} to \"{1}\"...\n".format(chapter_id, chapter_directory), logging.INFO)

        images = chapter_document.select("img.lazyload")
        for index, image in enumerate(images):
            image_url = image["data-original"]
            image_request = session.get(image_url)
            image_request.raise_for_status()
            image_bytes = image_request.content

            if "drm" in image_url:
                key_match = SEIGA_DRM_KEY_RE.search(image_url)
                if key_match:
                    key = key_match.group(1)
                else:
                    raise FormatNotSupportedException("Could not succesffully extract DRM key")
                image_bytes = decrypt_seiga_drm(image_bytes, key)

            data_type = determine_seiga_file_type(image_bytes)

            filename = str(index) + "." + data_type
            image_path = os.path.join(chapter_directory, filename)

            with open(image_path, "wb") as file:
                output("\rPage {0}/{1}".format(index + 1, len(images)), logging.DEBUG)
                file.write(image_bytes)

        output("\n", logging.DEBUG)
        output("Finished downloading {0} to \"{1}\".\n".format(chapter_id, chapter_directory), logging.INFO)

    if _cmdl_opts.dump_metadata:
        metadata_path = os.path.join(chapter_directory, "metadata.json")
        dump_metadata(metadata_path, template_params)
    if _cmdl_opts.download_thumbnail:
        output("Downloading thumbnails for Seiga comics is not currently supported.\n", logging.WARNING)
    if _cmdl_opts.download_comments:
        output("Downloading comments for Seiga comics is not currently supported.\n", logging.WARNING)


def download_manga(session, manga_id):
    """Download all chapters for a requested Seiga manga."""

    output("Downloading comic {0}...\n".format(manga_id), logging.INFO)

    manga_request = session.get(SEIGA_MANGA_URL.format(manga_id))
    manga_request.raise_for_status()

    manga_document = BeautifulSoup(manga_request.text, "html.parser")
    chapters = manga_document.select("div.episode .title a")
    for index, chapter in enumerate(chapters):
        chapter_id = chapter["href"].lstrip("/watch/").split("?")[0]
        output("{0}/{1}\n".format(index + 1, len(chapters)), logging.INFO)
        download_manga_chapter(session, chapter_id)


def download_image(session, image_id):
    """Download an individual Seiga image."""

    seiga_image_request = session.get(SEIGA_IMAGE_URL.format(image_id))
    seiga_image_request.raise_for_status()

    seiga_image_document = BeautifulSoup(seiga_image_request.text, "html.parser")
    template_params = {}
    template_params = collect_seiga_image_parameters(session, seiga_image_document, template_params)

    filename = create_filename(template_params)

    if not _cmdl_opts.skip_media:
        output("Downloading {0} to \"{1}\"...\n".format(image_id, filename), logging.INFO)

        source_image_request = session.get(template_params["url"], stream=True)
        source_image_request.raise_for_status()

        with open(filename, "wb") as file:
            for block in source_image_request.iter_content(BLOCK_SIZE):
                file.write(block)

        output("Finished donwloading {0} to \"{1}\".\n".format(image_id, filename), logging.INFO)

    if _cmdl_opts.dump_metadata:
        dump_metadata(filename, template_params)
    if _cmdl_opts.download_thumbnail:
        output("Downloading thumbnails for Seiga images is not currently supported.\n", logging.WARNING)
    if _cmdl_opts.download_comments:
        output("Downloading comments for Seiga images is not currently supported.\n", logging.WARNING)


def request_seiga_user(session, user_id):
    """Request images associated with a Seiga user."""

    output("Downloading images from Seiga user {0}...\n".format(user_id), logging.INFO)

    page_counter = 1
    illust_ids = []

    # Dumb loop, process pages until we reach a page with no images
    while True:
        user_illust_request = session.get(SEIGA_USER_ILLUST_URL.format(user_id, page_counter))
        user_illust_request.raise_for_status()

        user_illust_document = BeautifulSoup(user_illust_request.text, "html.parser")
        illust_links = user_illust_document.select(".illust_list .list_item a")

        if len(illust_links) == 0:
            break

        for link in illust_links:
            unstripped_id = link["href"]
            illust_ids.append(re.sub(r"^/seiga/", "", unstripped_id))

        page_counter += 1

    total_ids = len(illust_ids)
    if total_ids == 0:
        raise ParameterExtractionException("Failed to collect user images. Please verify that the user's images page is public")

    if _cmdl_opts.playlist_start:
        start_index = _cmdl_opts.playlist_start
        if start_index >= len(illust_ids):
            raise ArgumentException("Starting index exceeds length of the user's available images")
        else:
            illust_ids = illust_ids[start_index:]
            output("Beginning at index {}.\n".format(start_index), logging.INFO)

    for index, illust_id in enumerate(illust_ids):
        try:
            output("{0}/{1}\n".format(index + 1, len(illust_ids)), logging.INFO)
            download_image(session, illust_id)

        except (FormatNotSupportedException, FormatNotAvailableException, ParameterExtractionException) as error:
            log_exception(error)
            continue


def request_seiga_user_manga(session, user_id):
    """Request manga associated with a Seiga user."""

    output("Downloading manga from Seiga user {0}...\n".format(user_id), logging.INFO)

    page_counter = 1
    manga_ids = []

    # Dumb loop, process pages until we reach a page with no images
    while True:
        user_manga_request = session.get(SEIGA_USER_MANGA_URL.format(user_id, page_counter))
        user_manga_request.raise_for_status()

        user_manga_document = BeautifulSoup(user_manga_request.text, "html.parser")
        manga_links = user_manga_document.select("#comic_list .mg_item .title a")

        if len(manga_links) == 0:
            break

        for link in manga_links:
            unstripped_id = link["href"]
            manga_id = SEIGA_MANGA_ID_RE.match(unstripped_id).group(1)
            manga_ids.append(manga_id)

        page_counter += 1

    total_ids = len(manga_ids)
    if total_ids == 0:
        raise ParameterExtractionException("Failed to collect user images. Please verify that the user's manga page is public")

    if _cmdl_opts.playlist_start:
        start_index = _cmdl_opts.playlist_start
        if start_index >= len(manga_ids):
            raise ArgumentException("Starting index exceeds length of the user's available manga")
        else:
            manga_ids = manga_ids[start_index:]
            output("Beginning at index {}.\n".format(start_index), logging.INFO)

    for index, manga_id in enumerate(manga_ids):
        try:
            output("{0}/{1}\n".format(index + 1, len(manga_ids)), logging.INFO)
            download_manga(session, manga_id)

        except (FormatNotSupportedException, FormatNotAvailableException, ParameterExtractionException) as error:
            log_exception(error)
            continue


## Channel methods

def download_channel_article(session: requests.Session, article_id: AnyStr):
    """Download a blog article."""

    article_request = session.get(CHANNEL_ARTICLE_URL.format(article_id))
    article_request.raise_for_status()
    article_document = BeautifulSoup(article_request.text, "html.parser")

    template_params = {
        "ext": "txt",
        "id": article_id,
        "blog_title": article_document.select_one(".blomaga_name").text,
        "uploader": article_document.select_one(".profileArea span.name").text
    }

    if article_document.select_one(".profileArea span.name a"):
        template_params["uploader_id"] = int(article_document.select_one(".profileArea span.name a")["href"].rsplit("/")[-1])

    template_params["comment_count"] = 0
    if article_document.select_one("header.content .comment_count"):
        template_params["comment_count"] = int(article_document.select_one("header.content .comment_count").text)

    template_params["title"] = article_text = article_document.select_one("#article_blog_title").text
    template_params["published"] = article_document.select_one(".article_blog_data_first span").text
    template_params["article"] = article_text = article_document.select_one(".main_blog_txt").decode_contents()
    template_params["document_url"] = article_request.url

    tags = []
    for tag in article_document.select(".tag_list li"):
        tags.append(tag.text)
    template_params["tags"] = tags

    filename = create_filename(template_params)

    if not _cmdl_opts.skip_media:
        output("Downloading {0} to \"{1}\"...\n".format(article_id, filename), logging.INFO)

        with open(filename, "w", encoding="utf-8") as article_file:
            pretty_article_text = article_text.replace("<br/>", "\n").replace("<br>", "\n").replace("</br>", "").replace("<p>", "\n").replace(
                "</p>", "\n").replace("<hr/>", "---\n").replace("<strong>", "**").replace("</strong>", "**").replace( "<h2>", "\n## ").replace(
                "</h2>", "\n").replace("<h3>", "\n### ").replace("</h3>", "\n").replace("<ul>", "").replace( "</ul>", "").replace(
                "<li>", "- ").replace("</li>", "\n").strip()
            article_file.write(pretty_article_text)
    if _cmdl_opts.dump_metadata:
        dump_metadata(filename, template_params)
    if _cmdl_opts.download_comments:
        output("Downloading article comments is not currently supported.\n", logging.WARNING)

    output("Finished downloading {0} to \"{1}\".\n".format(article_id, filename), logging.INFO)


def request_channel(session: requests.Session, channel_slug: AnyStr):
    """Request videos associated with a channel."""

    output("Requesting videos from channel {0}...\n".format(channel_slug), logging.INFO)
    page_counter = 1
    video_ids = []

    # Dumb loop, process pages until we reach a page with no videos
    while True:
        channel_videos_request = session.get(CHANNEL_VIDEOS_URL.format(channel_slug, page_counter))
        channel_videos_request.raise_for_status()
        channel_videos_document = BeautifulSoup(channel_videos_request.text, "html.parser")
        video_links = channel_videos_document.select("h6.title a")

        if len(video_links) == 0:
            break

        for link in video_links:
            unstripped_id = link["href"]
            video_ids.append(re.sub(r"^https://www.nicovideo.jp/watch/", "", unstripped_id))

        page_counter += 1

    total_ids = len(video_ids)
    if total_ids == 0:
        raise ParameterExtractionException("Failed to collect channel videos. Please verify that the channel's videos page is public")
    output("{} videos returned.\n".format(total_ids), logging.INFO)

    if _cmdl_opts.playlist_start:
        start_index = _cmdl_opts.playlist_start
        if start_index >= len(video_ids):
            raise ArgumentException("Starting index exceeds length of the channel's video playlist")
        else:
            video_ids = video_ids[start_index:]
            output("Beginning at index {}.\n".format(start_index), logging.INFO)

    for index, video_id in enumerate(video_ids):
        try:
            output("{0}/{1}\n".format(index + 1, len(video_ids)), logging.INFO)
            request_video(session, video_id)

        except (FormatNotSupportedException, FormatNotAvailableException, ParameterExtractionException) as error:
            log_exception(error)
            continue


def request_channel_blog(session: requests.Session, channel_slug: AnyStr):
    """Request articles associated with a channel blog."""

    blog_request = session.get(CHANNEL_BLOMAGA_URL.format(channel_slug, 1))
    blog_request.raise_for_status()
    blog_document = BeautifulSoup(blog_request.text, "html.parser")
    total_pages = int(blog_document.select_one("span.page_all").text)

    for page in range(1, total_pages + 1):
        output("Page {0}/{1}\n".format(page, total_pages), logging.INFO)
        blog_request = session.get(CHANNEL_BLOMAGA_URL.format(channel_slug, page))
        blog_request.raise_for_status()
        blog_document = BeautifulSoup(blog_request.text, "html.parser")
        articles = blog_document.select("h3:first-child a")
        for article in articles:
            download_channel_article(session, article["href"].rsplit("/")[-1])


def request_channel_lives(session: requests.Session, channel_id: AnyStr):
    """Request lives associated with a channel."""

    output("Downloading channel lives is not currently supported.\n", logging.WARNING)


## Video methods

def request_video(session: requests.Session, video_id: AnyStr):
    """Request the video page and initiate download of the video URL."""

    # Retrieve video info to check for availability
    # Preserved as a sanity check, previously used to check video type
    thumb_info_request = session.get(THUMB_INFO_API.format(video_id))
    thumb_info_request.raise_for_status()
    video_info = xml.dom.minidom.parseString(thumb_info_request.text)

    if video_info.firstChild.getAttribute("status") != "ok":
        video_error_code = video_info.getElementsByTagName("error")[0].getElementsByTagName("code")[0].firstChild.nodeValue
        if video_error_code == "DELETED":
            raise FormatNotAvailableException("Video was deleted")
        elif video_error_code == "NOT_FOUND":
            raise FormatNotAvailableException("Video does not exist")
        else:
            raise FormatNotAvailableException("Could not retrieve video info from thumbnail API")

    concat_cookies = {}
    if _cmdl_opts.download_english:
        concat_cookies = {**concat_cookies, **EN_COOKIE}
    elif _cmdl_opts.download_chinese:
        concat_cookies = {**concat_cookies, **TW_COOKIE}

    if _cmdl_opts.download_english and _cmdl_opts.download_chinese:
        output("Multiple language flags were specified. --english will be used as the fallback.\n", logging.INFO)

    video_request = session.get(VIDEO_URL.format(video_id), cookies=concat_cookies)
    video_request.raise_for_status()
    document = BeautifulSoup(video_request.text, "html.parser")

    template_params = perform_api_request(session, document)

    filename = create_filename(template_params)

    if not _cmdl_opts.skip_media:
        continue_code = download_video_media(session, filename, template_params)
        if _cmdl_opts.break_on_existing and not continue_code:
            raise ExistingDownloadEncounteredQuit("Exiting as an existing video was encountered")
        if _cmdl_opts.add_metadata:
            add_metadata_to_container(filename, template_params)
    if _cmdl_opts.dump_metadata:
        dump_metadata(filename, template_params)
    if _cmdl_opts.download_thumbnail:
        download_thumbnail(session, filename, template_params)
    if _cmdl_opts.download_comments:
        download_comments(session, filename, template_params)


def request_user(session: requests.Session, user_id: AnyStr):
    """Request videos associated with a user."""

    output("Requesting videos from user {0}...\n".format(user_id), logging.INFO)

    video_ids = []

    session.options(USER_VIDEOS_API.format(user_id, USER_VIDEOS_API_N, 1), headers=API_HEADERS) # OPTIONS
    videos_request = session.get(USER_VIDEOS_API.format(user_id, USER_VIDEOS_API_N, 1), headers=API_HEADERS)
    videos_request.raise_for_status()
    user_videos_json = json.loads(videos_request.text)
    user_videos_count = int(user_videos_json["data"]["totalCount"])

    if user_videos_count == 0:
        output("No videos identified for speicifed user.\n", logging.INFO)
        return
    output("{} videos returned.\n".format(user_videos_count), logging.INFO)
    total_pages = math.ceil(user_videos_count / USER_VIDEOS_API_N)

    for page in range(1, total_pages + 1):
        videos_request = session.get(USER_VIDEOS_API.format(user_id, USER_VIDEOS_API_N, page), headers=API_HEADERS)
        videos_request.raise_for_status()
        user_videos_json = json.loads(videos_request.text)
        for video in user_videos_json["data"]["items"]:
            video_ids.append(video["id"])

    if _cmdl_opts.playlist_start:
        start_index = _cmdl_opts.playlist_start
        if start_index >= len(video_ids):
            raise ArgumentException("Starting index exceeds length of the user's video playlist")
        else:
            video_ids = video_ids[start_index:]
            output("Beginning at index {}.\n".format(start_index), logging.INFO)

    for index, video_id in enumerate(video_ids):
        try:
            output("{0}/{1}\n".format(index + 1, len(video_ids)), logging.INFO)
            request_video(session, video_id)

        except (FormatNotSupportedException, FormatNotAvailableException, ParameterExtractionException) as error:
            log_exception(error)
            continue


def request_mylist(session: requests.Session, mylist_id: AnyStr):
    """Request videos associated with a mylist."""

    output("Requesting mylist {0}...\n".format(mylist_id), logging.INFO)
    session.options(MYLIST_API.format(mylist_id), headers=API_HEADERS) # OPTIONS
    mylist_request = session.get(MYLIST_API.format(mylist_id), headers=API_HEADERS)
    mylist_request.raise_for_status()
    mylist_json = json.loads(mylist_request.text)
    items = mylist_json["data"]["mylist"]["items"]

    if _cmdl_opts.playlist_start:
        start_index = _cmdl_opts.playlist_start
        if start_index >= len(items):
            raise ArgumentException("Starting index exceeds length of the mylist")
        else:
            items = items[start_index:]
            output("Beginning at index {}.\n".format(start_index), logging.INFO)

    for index, item in enumerate(items):
        try:
            output("{0}/{1}\n".format(index + 1, len(items)), logging.INFO)
            request_video(session, item["watchId"])

        except (FormatNotSupportedException, FormatNotAvailableException, ParameterExtractionException) as error:
            log_exception(error)
            continue


def request_user_mylists(session: requests.Session, user_id: AnyStr):
    """Request mylists associated with a user."""

    output("Requesting mylists from user {0}...\n".format(user_id), logging.INFO)

    mylists_request = session.get(USER_MYLISTS_API.format(user_id), headers=API_HEADERS)
    mylists_request.raise_for_status()
    user_mylists_json = json.loads(mylists_request.text)
    user_mylists = user_mylists_json["data"]["mylists"]
    for index, item in enumerate(user_mylists):
        try:
            output("{0}/{1}\n".format(index + 1, len(user_mylists)), logging.INFO)
            request_mylist(session, item["id"])

        except (FormatNotSupportedException, FormatNotAvailableException, ParameterExtractionException) as error:
            log_exception(error)
            continue


def request_series(session: requests.Session, series_id: AnyStr):
    "Request videos associated with a series."

    output("Requesting series {0}...\n".format(series_id), logging.INFO)
    series_request = session.get(SERIES_URL.format(series_id))
    series_request.raise_for_status()
    series_page = BeautifulSoup(series_request.text, "html.parser")

    series_videos = series_page.select("div.SeriesVideoListContainer div.NC-MediaObject-main a")

    if len(series_videos) == 0:
        output("No videos identified for series.\n", logging.INFO)
        return

    video_ids = []
    for link in series_videos:
        unstripped_id = link["href"]
        video_ids.append(re.sub(r"^https://www.nicovideo.jp/watch/", "", unstripped_id))

    for index, video_id in enumerate(video_ids):
        try:
            output("{0}/{1}\n".format(index + 1, len(video_ids)), logging.INFO)
            request_video(session, video_id)

        except (FormatNotSupportedException, FormatNotAvailableException, ParameterExtractionException) as error:
            log_exception(error)
            continue


def show_multithread_progress(video_len):
    """Track overall download progress across threads."""

    global _progress, _start_time
    finished = False
    while not finished:
        if _progress >= video_len:
            finished = True
        done = int(25 * _progress / video_len)
        percent = int(100 * _progress / video_len)
        speed_str = calculate_speed(_start_time, time.time(), _progress)
        output("\r|{0}{1}| {2}/100 @ {3:9}/s".format("#" * done, " " * (25 - done), percent, speed_str), logging.DEBUG)


def update_multithread_progress(bytes_len):
    """Acquire lock on global download progress and update."""

    lock = threading.Lock()
    lock.acquire()
    try:
        global _progress
        _progress += bytes_len
    finally:
        lock.release()


def download_video_part(session: requests.Session, start, end, filename: AnyStr, url: AnyStr):
    """Download a video part using specified start and end byte boundaries."""

    resume_header = {"Range": "bytes={0}-{1}".format(start, end - 1)}

    dl_stream = session.get(url, headers=resume_header, stream=True)
    dl_stream.raise_for_status()
    stream_iterator = dl_stream.iter_content(BLOCK_SIZE)

    # part_length = end - start
    current_pos = start

    with open(filename, "r+b") as file:
        file.seek(current_pos)
        for block in stream_iterator:
            current_pos += len(block)
            file.write(block)
            update_multithread_progress(len(block))


def perform_ffmpeg_dl(video_id: AnyStr, filename: AnyStr, duration: float, streams: List):
    """Send video and/or audio stream to ffmpeg for download."""

    try:
        video_download = FfmpegDL(streams=streams,
                                    input_kwargs={
                                        "protocol_whitelist": "https,http,tls,tcp,file,crypto",
                                        "allowed_extensions": "ALL",
                                    },
                                    output_path=filename,
                                    output_kwargs={
                                        "vcodec": "copy",
                                        "acodec": "copy",
                                    })
        video_download.convert(name=video_id, duration=duration)
        return True
    except FfmpegDLException as error:
        raise FormatNotAvailableException(f"ffmpeg failed to download the video or audio stream with the following error: \"{error}\"")
    except Exception:
        raise FormatNotAvailableException("Failed to download video or audio stream")


def download_video_media(session: requests.Session, filename: AnyStr, template_params: dict):
    """Download video from response URL and display progress."""

    output("Downloading {0} to \"{1}\"...\n".format(template_params["id"], filename), logging.INFO)

    # If extension was rewritten, presume the download is complete
    if os.path.exists(filename):
        output("Video exists and appears to have been completed.\n", logging.INFO)
        return False

    complete_filename = filename
    filename = replace_extension(filename, f"part.{template_params['ext']}")

    # Dwango Media Service (DMS)
    if template_params.get("dms_video_uri") or template_params.get("dms_audio_uri"):

        # .part file
        if os.path.exists(filename):
            output("Resuming partial downloads is not supported for videos using DMS delivery. Any partial video data will be overwritten.\n", logging.WARNING)
        if _cmdl_opts.threads:
            output("Multithreading is only supported for DMC delivery. Video will be downloaded using one thread.\n", logging.WARNING)

        m3u8_streams = []
        with get_temp_dir() as temp_dir:
            for stream_type in ["dms_video_uri", "dms_audio_uri"]:
                if template_params.get(stream_type):
                    m3u8_path = os.path.join(temp_dir, f"{template_params['id']}_{stream_type}.m3u8")
                    m3u8 = generic_dl_request(session, template_params[stream_type], m3u8_path)
                    # It's minimally viable to only rewrite the key file locally for now
                    # Might be wise to eventually do this with the map and all individual segments
                    key_match = M3U8_KEY_RE.search(m3u8)
                    if not key_match:
                        raise FormatNotAvailableException("Could not retrieve key file from manifest")
                    key_url = key_match[2]
                    key_path =  os.path.join(temp_dir, f"{template_params['id']}_{stream_type}.key")
                    generic_dl_request(session, key_url, key_path, binary=True)
                    rewrite_file(m3u8_path, key_url, key_path)
                    m3u8_streams.append(m3u8_path)
            continue_code = perform_ffmpeg_dl(template_params["id"], filename, float(template_params["duration"]), m3u8_streams)
            os.rename(filename, complete_filename)
            return continue_code

    # Dwango Media Cluster (DMC)
    dl_stream = session.head(template_params["url"])
    dl_stream.raise_for_status()
    video_len = int(dl_stream.headers["content-length"])

    if _cmdl_opts.threads:
        output("Multithreading is experimental and will overwrite any existing files. --break-on-existing will be ignored.\n", logging.WARNING)

        threads = int(_cmdl_opts.threads)
        if threads <= 0:
            raise ArgumentException("Thread number must be a positive integer")

        # Track total bytes downloaded across threads
        global _progress
        _progress = 0

        # Pad out file to full length
        file = open(filename, "wb")
        file.truncate(video_len)
        file.close()

        # Calculate ranges for threads and dispatch
        part = math.ceil(video_len / threads)

        global _start_time
        _start_time = time.time()

        for i in range(threads):
            start = part * i
            end = video_len if i == threads - 1 else start + part

            part_thread = threading.Thread(
                target=download_video_part,
                kwargs={"start": start, "end": end, "filename": filename, "session": session, "url": template_params["url"]},
                daemon=True
            )
            part_thread.start()

        progress_thread = threading.Thread(target=show_multithread_progress, kwargs={"video_len": video_len})
        progress_thread.start()
        progress_thread.join()  # Wait for progress thread to terminate
        output("\n", logging.DEBUG)

        output("Finished downloading {0} to \"{1}\".\n".format(template_params["id"], filename), logging.INFO)
        os.rename(filename, complete_filename)
        return True

    # .part file
    if os.path.isfile(filename):
        with open(filename, "rb"):
            current_byte_pos = os.path.getsize(filename)
            if current_byte_pos < video_len:
                file_condition = "ab"
                resume_header = {"Range": "bytes={0}-".format(current_byte_pos - BLOCK_SIZE)}
                dl = current_byte_pos - BLOCK_SIZE
                output("Checking file integrity before resuming.\n")

            elif current_byte_pos > video_len:
                try:
                    if MP4(filename).tags:  # Container metadata is only written after a complete download
                        output("Existing file container has metadata written and should be complete.\n", logging.INFO)
                        return False
                    else:
                        raise FormatNotAvailableException(
                            "Current byte position exceeds the length of the video to be downloaded. Check the integrity of the existing file and "
                            "use --force-high-quality to resume this download when the high quality source is available.\n"
                        )
                except MP4StreamInfoError:  # Thrown if not a valid MP4 (FLV, SWF)
                    raise FormatNotAvailableException(
                        "Current byte position exceeds the length of the video to be downloaded. Check the integrity of the existing file and use "
                        "--force-high-quality to resume this download when the high quality source is available.\n"
                    )

            # current_byte_pos == video_len
            else:
                output("File exists and matches current download length.\n", logging.INFO)
                os.rename(filename, complete_filename)
                return True # Video was actually complete, but extension wasn't updated

    else:
        file_condition = "wb"
        resume_header = {"Range": "bytes=0-"}
        dl = 0

    dl_stream = session.get(template_params["url"], headers=resume_header, stream=True)
    dl_stream.raise_for_status()
    stream_iterator = dl_stream.iter_content(BLOCK_SIZE)

    if os.path.isfile(filename):
        new_data = next(stream_iterator)
        new_data_len = len(new_data)

        existing_byte_pos = os.path.getsize(filename)
        if existing_byte_pos - new_data_len <= 0:
            output("Byte comparison block exceeds the length of the existing file. Deleting existing file and redownloading...\n", logging.WARNING)
            os.remove(filename)
            download_video_media(session, filename, template_params)
            return True

        file = open(filename, "rb")
        file.seek(current_byte_pos - BLOCK_SIZE)
        existing_data = file.read()[:new_data_len]
        if new_data == existing_data:
            dl += new_data_len
            output("Resuming at byte position {0}.\n".format(dl))
            file.close()
        else:
            output("Byte comparison block does not match. Deleting existing file and redownloading...\n", logging.WARNING)
            file.close()
            os.remove(filename)
            download_video_media(session, filename, template_params)
            return True

    with open(filename, file_condition) as file:
        file.seek(dl)
        _start_time = time.time()
        for block in stream_iterator:
            dl += len(block)
            file.write(block)
            done = int(25 * dl / video_len)
            percent = int(100 * dl / video_len)
            speed_str = calculate_speed(_start_time, time.time(), dl)
            output("\r|{0}{1}| {2}/100 @ {3:9}/s".format("#" * done, " " * (25 - done), percent, speed_str), logging.DEBUG)
        output("\n", logging.DEBUG)

    output("Finished downloading {0} to \"{1}\".\n".format(template_params["id"], filename), logging.INFO)
    os.rename(filename, complete_filename)
    return True


def perform_heartbeat(session: requests.Session, heartbeat_url: AnyStr, api_request_el: xml.dom.minidom.Node):
    """Perform a response heartbeat to keep the video download connection alive."""
    heartbeat_response = session.post(heartbeat_url, data=api_request_el.toxml())
    heartbeat_response.raise_for_status()
    heartbeat_response_el = xml.dom.minidom.parseString(heartbeat_response.text).getElementsByTagName("session")[0]
    heartbeat_timer = threading.Timer(DMC_HEARTBEAT_INTERVAL_S, perform_heartbeat, (session, heartbeat_url, heartbeat_response_el)
    )
    heartbeat_timer.daemon = True
    heartbeat_timer.start()


def list_qualities(sources_type: str, sources: list, is_dms: bool):
    """Pretty print the list of available qualities from a provided sources list."""

    output(f"{sources_type.capitalize()}:\n")
    output(f"{'ID':<24} | {'Available':<10} | {'Info':<46}\n", logging.INFO, force=True)
    for source in sources:
        source_id = source["id"]
        is_available = source["isAvailable"]
        bit_rate = source["bitRate"] if is_dms else source["metadata"]["bitrate"]

        if sources_type == "video":
            width = source["width"] if is_dms else source["metadata"]["resolution"]["width"]
            height = source["height"] if is_dms else source["metadata"]["resolution"]["height"]
            label = source["label"] if is_dms else source["metadata"]["label"]
            quality_aggregate = "{0}x{1}({2})@{3}ps".format(width, height, label, format_value(bit_rate, use_bits=True, custom_type="b"))
        elif sources_type == "audio":
            sampling_rate = source["samplingRate"] if is_dms else source["metadata"]["samplingRate"]
            quality_aggregate = "{0}@{1}ps".format(format_value(sampling_rate, use_bits=True, custom_type="Hz"), format_value(bit_rate, use_bits=True, custom_type="b"))
        else:
            quality_aggregate = "-"

        output("{:<24} | {:<10} | {:<46}\n".format(source_id, str(is_available), quality_aggregate), logging.INFO, force=True)


def select_quality(template_params: dict, template_key: AnyStr, sources: list, quality="") -> List[AnyStr]:
    """Select the specified quality from a sources list on DMC and DMS videos."""

    if quality and _cmdl_opts.force_high_quality:
        output("-f/--force-high-quality was set. Ignoring specified quality...\n", logging.WARNING)

    # Assumes qualities are in descending order
    highest_quality = sources[0]
    lowest_quality = sources[-1]
    hq_available = highest_quality["isAvailable"]
    lq_available = lowest_quality["isAvailable"]

    # quality = "highest"
    if not hq_available and (_cmdl_opts.force_high_quality or (quality and quality.lower() == "highest")):
        raise FormatNotAvailableException("Highest quality is not currently available")
    elif _cmdl_opts.force_high_quality or (quality and quality.lower() == "highest"):
        template_params[template_key] = highest_quality["id"]
        return [template_params[template_key]]

    # quality = "lowest"
    if (quality and quality.lower() == "lowest") and lq_available:
        template_params[template_key] = lowest_quality["id"]
        return [template_params[template_key]]
    elif quality and quality.lower() == "lowest":
        raise FormatNotAvailableException("Lowest quality not available. Please verify that the video is able to be viewed")

    # Other specified quality
    bare_sources = [item["id"] for item in sources if item["isAvailable"]]
    if quality:
        filtered = list(filter(lambda q: q.lower() == quality.lower(), bare_sources))
        if not filtered:
            raise FormatNotAvailableException("{1} '{0}' is not available. Available qualities: {2}".format(quality, template_key, bare_sources))
        else:
            potential_quality = filtered[:1]
            template_params[template_key] = potential_quality
            return list(filtered[:1])

    # Default (return all qualities)
    else:
        default_quality = bare_sources[0]
        template_params[template_key] = default_quality
        return [default_quality]


def perform_api_request(session: requests.Session, document: BeautifulSoup) -> dict:
    """Collect parameters from video document and build API request for video URL."""

    template_params = {}

    # .mp4 videos (HTML5)
    # As of 2021, all videos are served this way
    if document.find(id="js-initial-watch-data"):
        params = json.loads(document.find(id="js-initial-watch-data")["data-api-data"])

        if params["video"]["isDeleted"]:
            raise FormatNotAvailableException("Video was deleted")

        template_params = collect_video_parameters(session, template_params, params)

        if (_cmdl_opts.no_audio and _cmdl_opts.no_video):
            output("--no-audio and --no-video were both specified. Treating this download as if --skip-media was set.\n", logging.WARNING)
            _cmdl_opts.skip_media = True
        if _cmdl_opts.skip_media and not _cmdl_opts.list_qualities:
            return template_params

        # Perform request to Dwango Media Service (DMS)
        # Began rollout starting 2023-11-01 for select videos and users (https://blog.nicovideo.jp/niconews/205042.html)
        # Videos longer than 30 minutes in HD (>720p) quality appear to be served this way exclusively 
        elif params["media"]["domand"]:
            if _cmdl_opts.list_qualities:
                list_qualities("video", params["media"]["domand"]["videos"], True)
                list_qualities("audio", params["media"]["domand"]["audios"], True)
                raise ListQualitiesQuit("Exiting after listing available qualities")

            video_id = params["video"]["id"]
            access_right_key = params["media"]["domand"]["accessRightKey"]
            watch_track_id = params["client"]["watchTrackId"]

            video_sources = select_quality(
                template_params,
                "video_quality",
                params["media"]["domand"]["videos"],
                _cmdl_opts.video_quality or "highest"
            )
            audio_sources = select_quality(
                template_params,
                "audio_quality",
                params["media"]["domand"]["audios"],
                _cmdl_opts.audio_quality or "highest"
            )

            # Limited to one video and audio source
            video_source = video_sources[0]
            audio_source = audio_sources[0]
            payload = json.dumps({"outputs":[[video_source, audio_source]]})

            output("Retrieving video manifest...\n", logging.INFO)
            headers = {
                "X-Access-Right-Key": access_right_key,
                "X-Request-With": "https://www.nicovideo.jp", # Only provided on this endpoint
            }
            session.options(VIDEO_DMS_WATCH_API.format(video_id, watch_track_id)) # OPTIONS
            get_manifest_request = session.post(VIDEO_DMS_WATCH_API.format(video_id, watch_track_id), headers={**API_HEADERS, **headers}, data=payload)
            get_manifest_request.raise_for_status()
            manifest_url = get_manifest_request.json()["data"]["contentUrl"]
            manifest_request = session.get(manifest_url)
            manifest_request.raise_for_status()
            manifest_text = manifest_request.text
            output("Retrieved video manifest.\n", logging.INFO)

            output("Collecting video media URIs...\n")
            if not _cmdl_opts.no_video:
                template_params["dms_video_uri"] = get_stream_from_manifest(manifest_text)
            if not _cmdl_opts.no_audio:
                template_params["dms_audio_uri"] = get_media_from_manifest(manifest_text, "audio")

            # Modify container when only one stream is specified
            if not template_params.get("dms_video_uri"):
                template_params["ext"] = "m4a"
            elif not template_params.get("dms_audio_uri"):
                template_params["ext"] = "m4v"

            output("Collected video media URIs.\n", logging.INFO)

        # Perform request to Dwango Media Cluster (DMC)
        elif params["media"]["delivery"]:
            output("Higher available qualities may not be available to download for certain videos uploaded after 2023-11-01. Follow this issue for more detail: https://github.com/AlexAplin/nndownload/issues/139\n", logging.INFO)

            if _cmdl_opts.list_qualities:
                list_qualities("video", params["media"]["delivery"]["movie"]["videos"], False)
                list_qualities("audio", params["media"]["delivery"]["movie"]["audios"], False)
                raise ListQualitiesQuit("Exiting after listing available qualities")

            api_url = params["media"]["delivery"]["movie"]["session"]["urls"][0]["url"]
            api_url += "?suppress_response_codes=true&_format=xml"
            recipe_id = params["media"]["delivery"]["movie"]["session"]["recipeId"]
            content_id = params["media"]["delivery"]["movie"]["session"]["contentId"]
            protocol = params["media"]["delivery"]["movie"]["session"]["protocols"][0]
            file_extension = template_params["ext"]
            priority = params["media"]["delivery"]["movie"]["session"]["priority"]

            video_sources = select_quality(
                template_params,
                "video_quality",
                params["media"]["delivery"]["movie"]["videos"],
                _cmdl_opts.video_quality
            )
            audio_sources = select_quality(
                template_params,
                "audio_quality",
                params["media"]["delivery"]["movie"]["audios"],
                _cmdl_opts.audio_quality
            )

            heartbeat_lifetime = params["media"]["delivery"]["movie"]["session"]["heartbeatLifetime"]
            token = params["media"]["delivery"]["movie"]["session"]["token"]
            signature = params["media"]["delivery"]["movie"]["session"]["signature"]
            auth_type = params["media"]["delivery"]["movie"]["session"]["authTypes"]["http"]
            service_user_id = params["media"]["delivery"]["movie"]["session"]["serviceUserId"]
            player_id = params["media"]["delivery"]["movie"]["session"]["playerId"]

            # Build initial heartbeat request
            post = """
                    <session>
                      <recipe_id>{0}</recipe_id>
                      <content_id>{1}</content_id>
                      <content_type>movie</content_type>
                      <protocol>
                        <name>{2}</name>
                        <parameters>
                          <http_parameters>
                            <method>GET</method>
                            <parameters>
                              <http_output_download_parameters>
                                <file_extension>{3}</file_extension>
                              </http_output_download_parameters>
                            </parameters>
                          </http_parameters>
                        </parameters>
                      </protocol>
                      <priority>{4}</priority>
                      <content_src_id_sets>
                        <content_src_id_set>
                          <content_src_ids>
                            <src_id_to_mux>
                              <video_src_ids>
                              </video_src_ids>
                              <audio_src_ids>
                              </audio_src_ids>
                            </src_id_to_mux>
                          </content_src_ids>
                        </content_src_id_set>
                      </content_src_id_sets>
                      <keep_method>
                        <heartbeat>
                          <lifetime>{5}</lifetime>
                        </heartbeat>
                      </keep_method>
                      <timing_constraint>unlimited</timing_constraint>
                      <session_operation_auth>
                        <session_operation_auth_by_signature>
                          <token>{6}</token>
                          <signature>{7}</signature>
                        </session_operation_auth_by_signature>
                      </session_operation_auth>
                      <content_auth>
                        <auth_type>{8}</auth_type>
                        <service_id>nicovideo</service_id>
                        <service_user_id>{9}</service_user_id>
                        <max_content_count>10</max_content_count>
                        <content_key_timeout>600000</content_key_timeout>
                      </content_auth>
                      <client_info>
                        <player_id>{10}</player_id>
                      </client_info>
                    </session>
                """.format(recipe_id,
                           content_id,
                           protocol,
                           file_extension,
                           priority,
                           heartbeat_lifetime,
                           token,
                           signature,
                           auth_type,
                           service_user_id,
                           player_id).strip()

            root = xml.dom.minidom.parseString(post)
            sources = root.getElementsByTagName("video_src_ids")[0]
            for video_source in video_sources:
                element = root.createElement("string")
                quality = root.createTextNode(video_source)
                element.appendChild(quality)
                sources.appendChild(element)

            sources = root.getElementsByTagName("audio_src_ids")[0]
            for audio_source in audio_sources:
                element = root.createElement("string")
                quality = root.createTextNode(audio_source)
                element.appendChild(quality)
                sources.appendChild(element)

            output("Performing initial API request...\n", logging.INFO)
            headers = {"Content-Type": "application/xml"}
            api_response = session.post(api_url, headers=headers, data=root.toxml())
            api_response.raise_for_status()
            api_request = xml.dom.minidom.parseString(api_response.text)
            template_params["url"] = api_request.getElementsByTagName("content_uri")[0].firstChild.nodeValue
            output("Performed initial API request.\n", logging.INFO)

            # Collect response for heartbeat
            session_id = api_request.getElementsByTagName("id")[0].firstChild.nodeValue
            session_url = params["media"]["delivery"]["movie"]["session"]["urls"][0]["url"]
            heartbeat_url = f"{session_url}/{session_id}?_format=xml&_method=PUT"
            api_request_el = api_request.getElementsByTagName("session")[0]
            perform_heartbeat(session, heartbeat_url, api_request_el)

        else:
            if params["payment"]["video"]["isPremium"] or params["payment"]["video"]["isAdmission"] or params["payment"]["video"]["isPpv"]:
                raise FormatNotAvailableException("Video requires payment or membership to download")
            else:
                raise FormatNotAvailableException("Video media not available for download")

    else:
        potential_region_error = document.select_one("p.fail-message") or document.select_one("p.font12")
        if potential_region_error and potential_region_error.text in REGION_LOCK_ERRORS:
            raise ParameterExtractionException("This video is not available in your region")
        else:
            raise ParameterExtractionException("Failed to collect video paramters")

    return template_params


## Metadata extraction

def collect_video_parameters(session: requests.Session, template_params: dict, params: dict) -> dict:
    """Collect video parameters to make them available for an output filename template."""

    if params.get("video"):
        template_params["id"] = params["video"]["id"]
        template_params["title"] = params["video"]["title"]
        template_params["uploader"] = params["owner"]["nickname"].rstrip(" さん") if params.get("owner") else None
        template_params["uploader_id"] = int(params["owner"]["id"]) if params.get("owner") else None
        template_params["description"] = params["video"]["description"]

        template_params["thumbnail_url"] = (  # Use highest quality thumbnail available
                params["video"]["thumbnail"]["ogp"]
                or params["video"]["thumbnail"]["player"]
                or params["video"]["thumbnail"]["largeUrl"]
                or params["video"]["thumbnail"]["middleUrl"]
                or params["video"]["thumbnail"]["url"])

        template_params["thread_id"] = int(params["comment"]["threads"][0]["id"])
        template_params["thread_key"] = params["comment"]["nvComment"]["threadKey"]
        template_params["thread_params"] = params["comment"]["nvComment"]["params"]
        template_params["published"] = params["video"]["registeredAt"]
        template_params["duration"] = params["video"]["duration"] # Seconds
        template_params["view_count"] = int(params["video"]["count"]["view"])
        template_params["mylist_count"] = int(params["video"]["count"]["mylist"])
        template_params["comment_count"] = int(params["video"]["count"]["comment"])
        template_params["like_count"] = int(params["video"]["count"]["like"])

        tags = []
        for tag in params["tag"]["items"]:
            tags.append(tag["name"])
        template_params["tags"] = tags

    template_params["document_url"] = VIDEO_URL.format(template_params["id"])

    thumb_info_request = session.get(THUMB_INFO_API.format(template_params["id"]))
    thumb_info_request.raise_for_status()
    thumb_info_document = xml.dom.minidom.parseString(thumb_info_request.text)

    # DMC and DMS videos do not expose the file type in the video page parameters when not logged in
    # As of 2021, all videos are served on the HTML5 player as .mp4
    # This is maintained as a sanity check
    if not template_params.get("ext"):
        template_params["ext"] = thumb_info_document.getElementsByTagName("movie_type")[0].firstChild.nodeValue
        if template_params["ext"] == "swf" or template_params["ext"] == "flv":
            template_params["ext"] = "mp4"

    # No longer really relevant for new videos, but the API continues to report for pre-DMC viodeos
    template_params["size_high"] = int(thumb_info_document.getElementsByTagName("size_high")[0].firstChild.nodeValue)
    template_params["size_low"] = int(thumb_info_document.getElementsByTagName("size_low")[0].firstChild.nodeValue)

    # Check if we couldn't capture uploader info before
    if not template_params["uploader_id"]:
        channel_id = thumb_info_document.getElementsByTagName("ch_id")
        user_id = thumb_info_document.getElementsByTagName("user_id")
        template_params["uploader_id"] = int(channel_id[0].firstChild.nodeValue) if channel_id else int(
            user_id[0].firstChild.nodeValue) if user_id else None

    if not template_params["uploader"]:
        channel_name = thumb_info_document.getElementsByTagName("ch_name")
        user_nickname = thumb_info_document.getElementsByTagName("user_nickname")
        template_params["uploader"] = channel_name[0].firstChild.nodeValue if channel_name else user_nickname[
            0].firstChild.nodeValue if user_nickname else None

    return template_params


def dump_metadata(filename: AnyStr, template_params: dict):
    """Dump the collected video metadata to a file."""

    output("Downloading metadata for {0}...\n".format(template_params["id"]), logging.INFO)

    filename = replace_extension(filename, "json")

    with open(filename, "w", encoding="utf-8") as file:
        json.dump(template_params, file, sort_keys=True)

    output("Finished downloading metadata for {0}.\n".format(template_params["id"]), logging.INFO)


def download_thumbnail(session: requests.Session, filename: AnyStr, template_params: dict):
    """Download the video thumbnail."""

    output("Downloading thumbnail for {0}...\n".format(template_params["id"]), logging.INFO)

    filename = replace_extension(filename, "jpg")

    thumb_request = session.get(template_params["thumbnail_url"])
    thumb_request.raise_for_status()

    with open(filename, "wb") as file:
        for block in thumb_request.iter_content(BLOCK_SIZE):
            file.write(block)

    output("Finished downloading thumbnail for {0}.\n".format(template_params["id"]), logging.INFO)


def download_comments(session: requests.Session, filename: AnyStr, template_params: dict):
    """Download the video comments."""

    output("Downloading comments for {0}...\n".format(template_params["id"]), logging.INFO)

    filename = replace_extension(filename, "comments.json")

    comments_post = COMMENTS_API_POST_DATA.format(template_params["thread_params"], template_params["thread_key"]).replace("\'", "\"").replace(": ", ":").replace(", ", ",")
    session.options(COMMENTS_API, headers=API_HEADERS) # OPTIONS
    get_comments_request = session.post(COMMENTS_API, data=comments_post, headers=API_HEADERS)
    get_comments_request.raise_for_status()
    with open(filename, "wb") as file:
        file.write(get_comments_request.content)

    output("Finished downloading comments for {0}.\n".format(template_params["id"]), logging.INFO)


def add_metadata_to_container(filename: AnyStr, template_params: dict):
    """Add metadata to any MP4 container."""

    if template_params["ext"] in ["mp4", "m4a", "m4v"]:
        output("Adding metadata to {}...\n".format(filename), logging.INFO)
        container_file = MP4(filename)
        if not container_file.tags:
            container_file.add_tags()
        container_file["\251nam"] = template_params["title"]  # Title
        container_file["\251ART"] = template_params["uploader"]  # Uploader
        container_file["desc"] = template_params["description"]  # Description
        container_file.save(filename)
    else:
        output("Container metadata is not supported for this file extension. Skipping...\n", logging.INFO)


# Main entry

def login(username: str, password: str, session_cookie: str) -> requests.Session:
    """Login to Nico and create a session."""

    session = requests.session()

    retry = Retry(
        total=RETRY_ATTEMPTS,
        read=RETRY_ATTEMPTS,
        connect=RETRY_ATTEMPTS,
        backoff_factor=BACKOFF_FACTOR,
        status_forcelist=(500, 502, 503, 504),
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("http://", adapter)
    session.mount("https://", adapter)

    session.headers.update({"User-Agent": f"{MODULE_NAME}/{__version__}"})

    if _cmdl_opts.proxy:
        proxies = {
            "http": _cmdl_opts.proxy,
            "https": _cmdl_opts.proxy
        }
        session.proxies.update(proxies)

    if not _cmdl_opts.no_login:
        if not session_cookie:
            output("Logging in...\n", logging.INFO)

            login_post = {
                "mail_tel": username,
                "password": password
            }

            login_request = session.post(LOGIN_URL, data=login_post)
            login_request.raise_for_status()

            if ("message=cant_login" in login_request.url):
                raise AuthenticationException("Incorrect email/telephone or password. Please verify your login details")

            otp_code_request = session.get(login_request.url)
            otp_code_page = BeautifulSoup(otp_code_request.text, "html.parser")
            otp_code_account = otp_code_page.select("div.pageMainMsg span.userAccount")[0].text

            otp_requests_made = 0
            while otp_requests_made < 10 and not session.cookies.get_dict().get("user_session", None):
                otp_code = input("Enter the OTP code sent to the email/telephone on file for your account ({}): ".format(otp_code_account))
                otp_code = otp_code.strip()

                otp_post = {
                    "otp": otp_code,
                    "device_name": f"{MODULE_NAME}/{__version__}"
                }

                otp_post_request = session.post(login_request.url, data=otp_post)
                otp_requests_made += 1
                otp_post_request.raise_for_status()

                if not session.cookies.get_dict().get("user_session", None):
                    output("Failed to login. Please verify your OTP code and try again.\n", logging.INFO)

            if not session.cookies.get_dict().get("user_session", None):
                raise AuthenticationException("Failed to login. Please verify your email/telephone, password, and OTP code")

            output("Logged in.\n", logging.INFO)

        else:
            output("Using provided session cookie.\n", logging.INFO)

            try:
                session_cookie_path = session_cookie
                with open(session_cookie_path, "r") as session_cookie_file:
                    session_cookie = session_cookie_file.read()
                output("Session cookie read from file.\n", logging.INFO)
            except FileNotFoundError:
                output("Session cookie read as string.\n", logging.INFO)

            session_dict = {
                "user_session": session_cookie
            }

            cookie_jar = session.cookies
            session.cookies = add_dict_to_cookiejar(cookie_jar, session_dict)

            my_request = session.get(MY_URL)
            my_request.raise_for_status()
            if my_request.history:
                raise AuthenticationException("Failed to login. Please verify your session cookie")

    return session


def process_url_mo(session, url_mo: Match):
    """Dispatches URL to the appropriate function."""

    url_id = url_mo.group(5)
    if url_mo.group(8):
        output("Additional URL parameters will be ignored.\n", logging.WARNING)
    if url_mo.group(3) == "mylist":
        request_mylist(session, url_id)
    elif url_mo.group(2):
        request_nama(session, url_id)
    elif url_mo.group(3) == "user":
        if url_mo.group(6) == "mylist":
            if url_mo.group(7):
                url_id = url_mo.group(7)
                request_mylist(session, url_id)
            else:
                request_user_mylists(session, url_id)
        elif not url_mo.group(6) or url_mo.group(6) == "video":
            request_user(session, url_id)
        else:
            raise ArgumentException("User URL argument is not of a known or accepted type of Nico URL")
    elif url_mo.group(1) == "seiga":
        if url_mo.group(3) == "watch":
            download_manga_chapter(session, url_id)
        elif url_mo.group(3) == "comic":
            download_manga(session, url_id)
        elif url_mo.group(3) == "user/illust" or url_mo.group(3) == "illust":
            if url_mo.group(8):
                url_id = url_mo.group(8)
            request_seiga_user(session, url_id)
        elif url_mo.group(3) == "user/manga" or url_mo.group(3) == "manga":
            if url_mo.group(8):
                url_id = url_mo.group(8)
            request_seiga_user_manga(session, url_id)
        elif url_mo.group(3) == "seiga":
            download_image(session, url_id)
        else:
            raise ArgumentException("Seiga URL argument is not of a known or accepted type of Nico URL")
    elif url_mo.group(1) == "ch":
        if url_mo.group(3) == "article":
            download_channel_article(session, url_id)
        elif url_mo.group(6) == "live":
            request_channel_lives(session, url_id)
        elif url_mo.group(6) == "blomaga":
            if url_mo.group(7):
                article_id = url_mo.group(7)
                download_channel_article(session, article_id)
            else:
                request_channel_blog(session, url_id)
        elif not url_mo.group(6) or url_mo.group(6) == "video":
            request_channel(session, url_id)
        else:
            raise ArgumentException("Channel URL argument is not of a known or accepted type of Nico URL")
    elif url_mo.group(3) == "watch" or url_mo.group(4) == "nico.ms":
        request_video(session, url_id)
    elif url_mo.group(3) == "series":
        request_series(session, url_id)
    else:
        raise ArgumentException("URL argument is not of a known or accepted type of Nico URL")


def main():
    try:
        configure_logger()

        account_username = _cmdl_opts.username
        account_password = _cmdl_opts.password
        session_cookie = _cmdl_opts.session_cookie

        if _cmdl_opts.netrc:
            if _cmdl_opts.username or _cmdl_opts.password or _cmdl_opts.session_cookie:
                output("Ignoring input credentials in favor of .netrc.\n", logging.WARNING)

            account_credentials = netrc.netrc().authenticators(HOST)
            if account_credentials:
                account_username = account_credentials[0]
                account_password = account_credentials[2]
            else:
                raise netrc.NetrcParseError("No authenticator available for {0}".format(HOST))
        elif not _cmdl_opts.no_login:
            while not account_username and not account_password and not session_cookie:
                account_username = input("Email/telephone: ")
                if account_username and not account_password:
                    account_password = getpass.getpass("Password: ")
                else:
                    session_cookie = input("Session cookie: ")
        else:
            output("Proceeding with no login. Some content may not be available for download or may only be "
                   "available in a lower quality. For access to all content, please provide a login with "
                   "--username/--password, --session-cookie, or --netrc.\n", logging.WARNING)

        session = login(account_username, account_password, session_cookie)

        for arg_item in _cmdl_opts.input:
            try:
                # Test if input is a valid URL or file
                url_mo = VALID_URL_RE.match(arg_item)

                if url_mo is None:
                    output(
                        "Argument not recognized as a valid Nico URL. Attempting to read argument as file path...\n",
                        logging.INFO
                    )
                    read_file(session, arg_item)
                    continue
                process_url_mo(session, url_mo)

            except Exception as error:
                if len(_cmdl_opts.input) == 1:
                    raise
                else:
                    log_exception(error)
                    continue

    except (ExistingDownloadEncounteredQuit, ListQualitiesQuit) as inert_exception:
        output(f"{inert_exception}\n", logging.INFO)
    except Exception as error:
        log_exception(error)


if __name__ == "__main__":
    try:
        _cmdl_opts = cmdl_parser.parse_args()
        main()
    except KeyboardInterrupt:
        output(f"Keyboard interrupt received. Exiting...\n", logging.INFO)
        sys.exit(1)
