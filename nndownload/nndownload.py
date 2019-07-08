#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Download videos from Niconico (nicovideo.jp), formerly known as Nico Nico Douga."""

from bs4 import BeautifulSoup
import requests
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry

from itertools import tee
import json
import math
import xml.dom.minidom
import urllib.parse
import re
import argparse
import os
import sys
import threading
import getpass
import time
import netrc
import collections
import logging
import traceback

__author__ = "Alex Aplin"
__copyright__ = "Copyright 2016 Alex Aplin"

__license__ = "MIT"
__version__ = "0.9"

HOST = "nicovideo.jp"
LOGIN_URL = "https://account.nicovideo.jp/api/v1/login?site=niconico"
VIDEO_URL = "http://nicovideo.jp/watch/{0}"
USER_VIDEOS_URL = "https://www.nicovideo.jp/user/{0}/video?page={1}"
VIDEO_URL_RE = re.compile(r"(?:https?://(?:(?:(?:sp|www)\.)?(?:(live[0-9]?|cas)\.)?(?:(?:nicovideo\.jp/(watch|mylist|user))|nico\.ms)/))(?:(?:[0-9]+)/)?((?:[a-z]{2})?[0-9]+)")

NAMA_API = "http://watch.live.nicovideo.jp/api/getplayerstatus?v={0}"
CAS_QUALITIES_API = "https://api.cas.nicovideo.jp/v1/services/live/programs/{0}/watching-qualities"
CAS_WATCHING_API = "https://api.cas.nicovideo.jp/v1/services/live/programs/{0}/watching"
THUMB_INFO_API = "http://ext.nicovideo.jp/api/getthumbinfo/{0}"
MYLIST_API = "http://flapi.nicovideo.jp/api/getplaylist/mylist/{0}"
COMMENTS_API = "http://nmsg.nicovideo.jp/api"
COMMENTS_POST_JP = "<packet><thread thread=\"{0}\" version=\"20061206\" res_from=\"-1000\" scores=\"1\"/></packet>"
COMMENTS_POST_EN = "<packet><thread thread=\"{0}\" version=\"20061206\" res_from=\"-1000\" language=\"1\" scores=\"1\"/></packet>"

DMC_HEARTBEAT_INTERVAL_S = 15
CAS_HEARTBEAT_INTERVAL_S = 20
KILOBYTE = 1024
BLOCK_SIZE = 1024 * KILOBYTE
EPSILON = 0.0001

HTML5_COOKIE = {
    "watch_flash": "0"
}

FLASH_COOKIE = {
    "watch_flash": "1"
}

EN_COOKIE = {
    "lang": "en-us"
}

RETRY_ATTEMPTS = 5
BACKOFF_FACTOR = 2 # retry_timeout_s = BACK_OFF_FACTOR * (2 ** ({number_of_retries} - 1))

logger = logging.getLogger(__name__)

cmdl_usage = "%(prog)s [options] input"
cmdl_version = __version__
cmdl_parser = argparse.ArgumentParser(usage=cmdl_usage, conflict_handler="resolve")

cmdl_parser.add_argument("-u", "--username", dest="username", metavar="USERNAME", help="account username")
cmdl_parser.add_argument("-p", "--password", dest="password", metavar="PASSWORD", help="account password")
cmdl_parser.add_argument("-n", "--netrc", action="store_true", dest="netrc", help="use .netrc authentication")
cmdl_parser.add_argument("-q", "--quiet", action="store_true", dest="quiet", help="suppress output to console")
cmdl_parser.add_argument("-l", "--log", action="store_true", dest="log", help="log output to file")
cmdl_parser.add_argument("-v", "--version", action="version", version=cmdl_version)
cmdl_parser.add_argument("input", help="URL or file")

dl_group = cmdl_parser.add_argument_group("download options")
dl_group.add_argument("-y", "--proxy", dest="proxy", metavar="PROXY", help="http or socks proxy")
dl_group.add_argument("-o", "--output-path", dest="output_path", help="custom output path (see template options)")
dl_group.add_argument("-g", "--no-login", action="store_true", dest="no_login", help="create a download session without logging in")
dl_group.add_argument("-f", "--force-high-quality", action="store_true", dest="force_high_quality", help="only download if the high quality source is available")
dl_group.add_argument("-m", "--dump-metadata", action="store_true", dest="dump_metadata", help="dump video metadata to file")
dl_group.add_argument("-t", "--download-thumbnail", action="store_true", dest="download_thumbnail", help="download video thumbnail")
dl_group.add_argument("-c", "--download-comments", action="store_true", dest="download_comments", help="download video comments")
dl_group.add_argument("-e", "--english", action="store_true", dest="download_english", help="request video on english site")
dl_group.add_argument("-aq", "--audio-quality", dest="audio_quality", help="specify audio quality (DMC videos only)")
dl_group.add_argument("-vq", "--video-quality", dest="video_quality", help="specify video quality (DMC videos only)")


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


def configure_logger():
    if cmdl_opts.log:
        logger.setLevel(logging.INFO)
        log_handler = logging.FileHandler("[{0}] {1}.log".format("nndownload", time.strftime("%Y-%m-%d")))
        formatter = logging.Formatter("%(asctime)s %(levelname)s: %(message)s")
        log_handler.setFormatter(formatter)
        logger.addHandler(log_handler)


def log_exception(error):
    if cmdl_opts.log:
        logger.exception("{0}: {1}\n".format(type(error).__name__, str(error)))


def output(string, level=logging.INFO):
    """Print status to console unless quiet flag is set."""

    global cmdl_opts
    if cmdl_opts.log:
        logger.log(level, string.strip("\n"))

    if not cmdl_opts.quiet:
        sys.stdout.write(string)
        sys.stdout.flush()


def login(username, password):
    """Login to Nico. Will raise an exception for errors."""

    session = requests.session()

    retry = Retry(
        total = RETRY_ATTEMPTS,
        read = RETRY_ATTEMPTS,
        connect = RETRY_ATTEMPTS,
        backoff_factor = BACKOFF_FACTOR,
        status_forcelist = (500, 502, 503, 504),
    )
    adapter = HTTPAdapter(max_retries = retry)
    session.mount('http://', adapter)
    session.mount('https://', adapter)

    session.headers.update({"User-Agent": "nndownload/{0}".format(__version__)})

    if not cmdl_opts.no_login:
        output("Logging in...\n", logging.INFO)

        LOGIN_POST = {
            "mail_tel": username,
            "password": password
        }

        if cmdl_opts.proxy:
            proxies = {
                "http": cmdl_opts.proxy,
                "https": cmdl_opts.proxy
            }
            session.proxies.update(proxies)

        response = session.post(LOGIN_URL, data=LOGIN_POST)
        response.raise_for_status()
        if not session.cookies.get_dict().get("user_session", None):
            output("Failed to login.\n", logging.INFO)
            raise AuthenticationException("Failed to login. Please verify your username and password")

        output("Logged in.\n", logging.INFO)

    return session


def pairwise(iterable):
    """Helper method to pair RTMP URL with stream label."""

    a, b = tee(iterable)
    next(b, None)
    return zip(a, b)


def live_url_stub():
    """Stub function for building HLS stream URLs for Niconama broadcasts."""

    output("Support for HLS streams is not yet implemented.\n", logging.ERROR)
    return


def perform_heartbeat(session, heartbeat_url, response):
    """Perform a response heartbeat to keep the download connection alive."""

    response = session.post(heartbeat_url, data=response.toxml())
    response.raise_for_status()
    response = xml.dom.minidom.parseString(response.text).getElementsByTagName("session")[0]
    heartbeat_timer = threading.Timer(DMC_HEARTBEAT_INTERVAL_S, perform_heartbeat, (session, heartbeat_url, response))
    heartbeat_timer.daemon = True
    heartbeat_timer.start()


def request_video(session, video_id):
    """Request the video page and initiate download of the video URL."""

    # Determine whether to request the Flash or HTML5 player
    # Only .mp4 videos are served on the HTML5 player, so we can sometimes miss the high quality .flv source
    response = session.get(THUMB_INFO_API.format(video_id))
    response.raise_for_status()

    video_info = xml.dom.minidom.parseString(response.text)

    if video_info.firstChild.getAttribute("status") != "ok":
        raise FormatNotAvailableException("Could not retrieve video info")

    concat_cookies = {}
    if cmdl_opts.download_english:
        concat_cookies = {**concat_cookies, **EN_COOKIE}

    # This is the file type for the original encode
    # When logged out, Flash videos will sometimes be served on the HTML5 player with a low quality .mp4 re-encode
    # Some Flash videos are not available outside of the Flash player
    video_type = video_info.getElementsByTagName("movie_type")[0].firstChild.nodeValue
    if video_type == "swf" or video_type == "flv":
        concat_cookies = {**concat_cookies, **FLASH_COOKIE}
    elif video_type == "mp4":
        concat_cookies = {**concat_cookies, **HTML5_COOKIE}
    else:
        raise FormatNotAvailableException("Video type not supported")

    response = session.get(VIDEO_URL.format(video_id), cookies=concat_cookies)

    response.raise_for_status()
    document = BeautifulSoup(response.text, "html.parser")

    template_params = perform_api_request(session, document)

    filename = create_filename(template_params)

    download_video(session, filename, template_params)
    if cmdl_opts.dump_metadata:
        dump_metadata(filename, template_params)
    if cmdl_opts.download_thumbnail:
        download_thumbnail(session, filename, template_params)
    if cmdl_opts.download_comments:
        download_comments(session, filename, template_params)


def format_bytes(number_bytes):
    """Attach suffix (e.g. 10 T) to number of bytes."""

    try:
        exponent = int(math.log(number_bytes, KILOBYTE))
        suffix = "\0KMGTPE"[exponent]

        if exponent == 0:
            return "{0}{1}".format(number_bytes, suffix)

        converted = float(number_bytes / KILOBYTE ** exponent)
        return "{0:.2f}{1}B".format(converted, suffix)

    except IndexError:
        raise IndexError("Could not format number of bytes")


def calculate_speed(start, now, bytes):
    """Calculate speed based on difference between start and current block call."""

    dif = now - start
    if bytes == 0 or dif < EPSILON:
        return "N/A B"
    return format_bytes(bytes / dif)


def replace_extension(filename, new_extension):
    """Replace the extension in a file path."""

    base_path, _ = os.path.splitext(filename)
    return "{0}.{1}".format(base_path, new_extension)


def sanitize_for_path(value, replace=' '):
    """Remove potentially illegal characters from a path."""
    return re.sub(r'[<>\"\?\\\/\*:]', replace, value)


def create_filename(template_params):
    """Create filename from document parameters."""

    filename_template = cmdl_opts.output_path

    if filename_template:
        template_dict = dict(template_params)
        template_dict = dict((k, sanitize_for_path(str(v))) for k, v in template_dict.items() if v)
        template_dict = collections.defaultdict(lambda: "__NONE__", template_dict)

        filename = filename_template.format_map(template_dict)
        if (os.path.dirname(filename) and not os.path.exists(os.path.dirname(filename))) or os.path.exists(os.path.dirname(filename)):
            os.makedirs(os.path.dirname(filename), exist_ok=True)

        return filename
    else:
        filename = "{0} - {1}.{2}".format(template_params["id"], template_params["title"], template_params["ext"])
        return sanitize_for_path(filename)


def download_video(session, filename, template_params):
    """Download video from response URL and display progress."""

    output("Downloading {0} to \"{1}\"...\n".format(template_params["id"], filename), logging.INFO)

    dl_stream = session.head(template_params["url"])
    dl_stream.raise_for_status()
    video_len = int(dl_stream.headers["content-length"])

    if os.path.isfile(filename):
        with open(filename, "rb") as file:
            current_byte_pos = os.path.getsize(filename)
            if current_byte_pos < video_len:
                file_condition = "ab"
                resume_header = {"Range": "bytes={0}-".format(current_byte_pos - BLOCK_SIZE)}
                dl = current_byte_pos - BLOCK_SIZE
                output("Checking file integrity before resuming.\n")

            elif current_byte_pos > video_len:
                raise FormatNotAvailableException("Current byte position exceeds the length of the video to be downloaded. Check the interity of the existing file and use --force-high-quality to resume this download when the high quality source is available.\n")

            # current_byte_pos == video_len
            else:
                output("File exists and matches current download length.\n", logging.INFO)
                return

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
        if current_byte_pos - new_data_len <= 0:
            output("Byte comparison block exceeds the length of the existing file. Deleting existing file and redownloading...\n")
            os.remove(filename)
            download_video(session, filename, template_params)
            return

        with open(filename, "rb") as file:
            file.seek(current_byte_pos - BLOCK_SIZE)
            existing_data = file.read()[:new_data_len]
            if new_data == existing_data:
                dl += new_data_len
                output("Resuming at byte position {0}.\n".format(dl))
            else:
                output("Byte comparison block does not match. Deleting existing file and redownloading...\n")
                os.remove(filename)
                download_video(session, filename, template_params)
                return

    with open(filename, file_condition) as file:
        file.seek(dl)
        start_time = time.time()
        for block in stream_iterator:
            dl += len(block)
            file.write(block)
            done = int(25 * dl / video_len)
            percent = int(100 * dl / video_len)
            speed_str = calculate_speed(start_time, time.time(), dl)
            output("\r|{0}{1}| {2}/100 @ {3:9}/s".format("#" * done, " " * (25 - done), percent, speed_str), logging.DEBUG)

    output("\nFinished downloading {0} to \"{1}\".\n".format(template_params["id"], filename), logging.INFO)


def dump_metadata(filename, template_params):
    """Dump the collected video metadata to a file."""

    output("Downloading metadata for {0}...\n".format(template_params["id"]), logging.INFO)

    filename = replace_extension(filename, "json")

    with open(filename, "w") as file:
        json.dump(template_params, file, sort_keys=True)

    output("Finished downloading metadata for {0}.\n".format(template_params["id"]), logging.INFO)


def download_thumbnail(session, filename, template_params):
    """Download the video thumbnail."""

    output("Downloading thumbnail for {0}...\n".format(template_params["id"]), logging.INFO)

    filename = replace_extension(filename, "jpg")

    # Try to retrieve the large thumbnail
    get_thumb = session.get(template_params["thumbnail_url"] + ".L")
    if get_thumb.status_code == 404:
        get_thumb = session.get(template_params["thumbnail_url"])
        get_thumb.raise_for_status()

    with open(filename, "wb") as file:
        for block in get_thumb.iter_content(BLOCK_SIZE):
            file.write(block)

    output("Finished downloading thumbnail for {0}.\n".format(template_params["id"]), logging.INFO)


def download_comments(session, filename, template_params):
    """Download the video comments."""

    output("Downloading comments for {0}...\n".format(template_params["id"]), logging.INFO)

    filename = replace_extension(filename, "xml")

    if cmdl_opts.download_english:
        post_packet = COMMENTS_POST_EN
    else:
        post_packet = COMMENTS_POST_JP
    get_comments = session.post(COMMENTS_API, post_packet.format(template_params["thread_id"]))
    get_comments.raise_for_status()
    with open(filename, "wb") as file:
        file.write(get_comments.content)

    output("Finished downloading comments for {0}.\n".format(template_params["id"]), logging.INFO)


def request_user(session, user_id):
    """Download videos associated with a user."""

    output("Downloading videos from user {0}...\n".format(user_id), logging.INFO)
    page_counter = 1
    video_ids = []

    # Dumb loop, process pages until we reach a page with no videos
    while True:
        user_videos_page = session.get(USER_VIDEOS_URL.format(user_id, page_counter))
        user_videos_page.raise_for_status()

        user_videos_document = BeautifulSoup(user_videos_page.text, "html.parser")
        video_links = user_videos_document.select(".VideoItem-videoDetail h5 a")

        if len(video_links) == 0:
            break

        for link in video_links:
            unstripped_id = link["href"]
            video_ids.append(unstripped_id.lstrip("watch/"))

        page_counter += 1

    total_ids = len(video_ids)
    if total_ids == 0:
        raise ParameterExtractionException("Failed to collect user videos. Please verify that the user's videos page is public")

    for index, video_id in enumerate(video_ids):
        try:
            output("{0}/{1}\n".format(index + 1, total_ids), logging.INFO)
            request_video(session, video_id)

        except (FormatNotSupportedException, FormatNotAvailableException, ParameterExtractionException) as error:
            log_exception(error)
            traceback.print_exc()
            continue


def read_file(session, file):
    """Read file and process each line as a URL."""

    with open(file) as file:
        content = file.readlines()

    total_lines = len(content)
    for index, line in enumerate(content):
        try:
            output("{0}/{1}\n".format(index + 1, total_lines), logging.INFO)
            url_mo = valid_url(line)
            if url_mo:
                process_url_mo(session, url_mo)
            else:
                raise ArgumentException("Not a valid URL")

        except (FormatNotSupportedException, FormatNotAvailableException, ParameterExtractionException) as error:
            log_exception(error)
            traceback.print_exc()
            continue


def request_mylist(session, mylist_id):
    """Download videos associated with a mylist."""

    output("Downloading mylist {0}...\n".format(mylist_id), logging.INFO)
    mylist_request = session.get(MYLIST_API.format(mylist_id))
    mylist_request.raise_for_status()
    mylist_json = json.loads(mylist_request.text)

    total_mylist = len(mylist_json["items"])
    if mylist_json["status"] != "ok":
        raise FormatNotAvailableException("Could not retrieve mylist info")
    else:
        for index, item in enumerate(mylist_json["items"]):
            try:
                output("{0}/{1}\n".format(index + 1, total_mylist), logging.INFO)
                request_video(session, item["video_id"])

            except (FormatNotSupportedException, FormatNotAvailableException, ParameterExtractionException) as error:
                log_exception(error)
                traceback.print_exc()
                continue

def determine_quality(template_params, params):
    """Determine the quality parameter for all videos."""

    if params.get("video"):
        if params["video"].get("dmcInfo"):
            if params["video"]["dmcInfo"]["quality"]["videos"][0]["id"] == template_params["video_quality"] and params["video"]["dmcInfo"]["quality"]["audios"][0]["id"] == template_params["audio_quality"]:
                template_params["quality"] = "auto"
            else:
                template_params["quality"] = "low"

        elif params["video"].get("smileInfo"):
            template_params["quality"] = params["video"]["smileInfo"]["currentQualityId"]

    if params.get("videoDetail"):
        template_params["quality"] = "auto"


def select_dmc_quality(template_params, template_key, sources: list, quality=None):
    """Select the specified quality from a sources list on DMC videos."""

    # TODO: Make sure source is available
    # Haven't seen a source marked as unavailable in the wild rather than be unlisted, but we might as well be sure

    if quality and cmdl_opts.force_high_quality:
        output("Video or audio quality specified with --force-high-quality. Ignoring quality...\n", logging.WARNING)

    if not quality or cmdl_opts.force_high_quality or quality.lower() == "highest":
        template_params[template_key] = sources[:1][0]
        return sources[:1]

    if quality.lower() == "lowest":
        template_params[template_key] = sources[-1:][0]
        return sources[-1:]

    filtered = list(filter(lambda q: q.lower() == quality.lower(), sources))
    if not filtered:
        raise FormatNotAvailableException(f"Quality '{quality}' is not available. Available qualities: {sources}")

    template_params[template_key] = filtered[:1][0]
    return filtered[:1]


def perform_api_request(session, document):
    """Collect parameters from video document and build API request for video URL."""

    template_params = {}

    # .mp4 videos (HTML5)
    if document.find(id="js-initial-watch-data"):
        params = json.loads(document.find(id="js-initial-watch-data")["data-api-data"])

        if params["video"]["isDeleted"]:
            raise FormatNotAvailableException("Video was deleted")

        template_params = collect_parameters(session, template_params, params, is_html5=True)

        # Perform request to Dwango Media Cluster (DMC)
        if params["video"].get("dmcInfo"):
            api_url = params["video"]["dmcInfo"]["session_api"]["urls"][0]["url"] + "?suppress_response_codes=true&_format=xml"
            recipe_id = params["video"]["dmcInfo"]["session_api"]["recipe_id"]
            content_id = params["video"]["dmcInfo"]["session_api"]["content_id"]
            protocol = params["video"]["dmcInfo"]["session_api"]["protocols"][0]
            file_extension = template_params["ext"]
            priority = params["video"]["dmcInfo"]["session_api"]["priority"]

            video_sources = select_dmc_quality(template_params, "video_quality", params["video"]["dmcInfo"]["session_api"]["videos"], cmdl_opts.video_quality)
            audio_sources = select_dmc_quality(template_params, "audio_quality", params["video"]["dmcInfo"]["session_api"]["audios"], cmdl_opts.audio_quality)
            determine_quality(template_params, params)
            if template_params["quality"] != "auto" and cmdl_opts.force_high_quality:
                raise FormatNotAvailableException("High quality source is not available")

            heartbeat_lifetime = params["video"]["dmcInfo"]["session_api"]["heartbeat_lifetime"]
            token = params["video"]["dmcInfo"]["session_api"]["token"]
            signature = params["video"]["dmcInfo"]["session_api"]["signature"]
            auth_type = params["video"]["dmcInfo"]["session_api"]["auth_types"]["http"]
            service_user_id = params["video"]["dmcInfo"]["session_api"]["service_user_id"]
            player_id = params["video"]["dmcInfo"]["session_api"]["player_id"]

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
            response = session.post(api_url, headers=headers, data=root.toxml())
            response.raise_for_status()
            response = xml.dom.minidom.parseString(response.text)
            template_params["url"] = response.getElementsByTagName("content_uri")[0].firstChild.nodeValue
            output("Performed initial API request.\n", logging.INFO)

            # Collect response for heartbeat
            session_id = response.getElementsByTagName("id")[0].firstChild.nodeValue
            response = response.getElementsByTagName("session")[0]
            heartbeat_url = params["video"]["dmcInfo"]["session_api"]["urls"][0]["url"] + "/" + session_id + "?_format=xml&_method=PUT"
            perform_heartbeat(session, heartbeat_url, response)

        # Legacy URL for videos uploaded pre-HTML5 player (~2016-10-27)
        elif params["video"].get("smileInfo"):
            output("Using legacy URL...\n", logging.INFO)

            if cmdl_opts.video_quality or cmdl_opts.audio_quality:
                output("Video and audio qualities can't be specified on legacy videos. Ignoring...\n", logging.WARNING)
            determine_quality(template_params, params)
            if template_params["quality"] != "auto" and cmdl_opts.force_high_quality:
                raise FormatNotAvailableException("High quality source is not available")

            template_params["url"] = params["video"]["smileInfo"]["url"]

        else:
            raise ParameterExtractionException("Failed to find video URL. Nico may have updated their player")

    # Flash videos (.flv, .swf)
    # NicoMovieMaker videos (.swf) may need conversion to play properly in an external player
    elif document.find(id="watchAPIDataContainer"):
        params = json.loads(document.find(id="watchAPIDataContainer").text)

        if params["videoDetail"]["isDeleted"]:
            raise FormatNotAvailableException("Video was deleted")

        template_params = collect_parameters(session, template_params, params, is_html5=False)

        if cmdl_opts.video_quality or cmdl_opts.audio_quality:
            output("Video and audio qualities can't be specified on Flash videos. Ignoring...\n", logging.WARNING)
        determine_quality(template_params, params)
        if template_params["quality"] != "auto" and cmdl_opts.force_high_quality:
            raise FormatNotAvailableException("High quality source is not available")

        video_url_param = urllib.parse.parse_qs(urllib.parse.unquote(urllib.parse.unquote(params["flashvars"]["flvInfo"])))
        if ("url" in video_url_param):
            template_params["url"] = video_url_param["url"][0]

        else:
            raise ParameterExtractionException("Failed to find video URL. Nico may have updated their player")

    else:
        raise ParameterExtractionException("Failed to collect video paramters")

    return template_params


def collect_parameters(session, template_params, params, is_html5):
    """Collect video parameters to make them available for an output filename template."""

    if params.get("video"):
        template_params["id"] = params["video"]["id"]
        template_params["title"] = params["video"]["title"]
        template_params["uploader"] = params["owner"]["nickname"].rstrip(" さん") if params.get("owner") else None
        template_params["uploader_id"] = int(params["owner"]["id"]) if params.get("owner") else None
        template_params["description"] = params["video"]["description"]
        template_params["thumbnail_url"] = params["video"]["thumbnailURL"]
        template_params["thread_id"] = int(params["thread"]["ids"]["default"])
        template_params["published"] = params["video"]["postedDateTime"]
        template_params["duration"] = params["video"]["duration"]
        template_params["view_count"] = params["video"]["viewCount"]
        template_params["mylist_count"] = params["video"]["mylistCount"]
        template_params["comment_count"] = params["thread"]["commentCount"]

    elif params.get("videoDetail"):
        template_params["id"] = params["videoDetail"]["id"]
        template_params["title"] = params["videoDetail"]["title"]
        template_params["uploader"] = params["uploaderInfo"]["nickname"].rstrip(" さん") if params.get("uploaderInfo") else None
        template_params["uploader_id"] = int(params["uploaderInfo"]["id"]) if params.get("uploaderInfo") else None
        template_params["description"] = params["videoDetail"]["description"]
        template_params["thumbnail_url"] = params["videoDetail"]["thumbnail"]
        template_params["thread_id"] = int(params["videoDetail"]["thread_id"])
        template_params["published"] = params["videoDetail"]["postedAt"]
        template_params["duration"] = params["videoDetail"]["length"]
        template_params["view_count"] = params["videoDetail"]["viewCount"]
        template_params["mylist_count"] = params["videoDetail"]["mylistCount"]
        template_params["comment_count"] = params["videoDetail"]["commentCount"]

    response = session.get(THUMB_INFO_API.format(template_params["id"]))
    response.raise_for_status()
    video_info = xml.dom.minidom.parseString(response.text)

    # DMC videos do not expose the file type in the video page parameters when not logged in
    # If this is a Flash video being served on the HTML5 player, it's guaranteed to be a low quality .mp4 re-encode
    template_params["ext"] = video_info.getElementsByTagName("movie_type")[0].firstChild.nodeValue
    if is_html5 and (template_params["ext"] == "swf" or template_params["ext"] == "flv"):
        template_params["ext"] = "mp4"

    template_params["size_high"] = int(video_info.getElementsByTagName("size_high")[0].firstChild.nodeValue)
    template_params["size_low"] = int(video_info.getElementsByTagName("size_low")[0].firstChild.nodeValue)

    # Check if we couldn't capture uploader info before
    if not template_params["uploader_id"]:
        channel_id = video_info.getElementsByTagName("ch_id")
        user_id = video_info.getElementsByTagName("user_id")
        template_params["uploader_id"] = channel_id[0].firstChild.nodeValue if channel_id else user_id[0].firstChild.nodeValue if user_id else None

    if not template_params["uploader"]:
        channel_name = video_info.getElementsByTagName("ch_name")
        user_nickname = video_info.getElementsByTagName("user_nickname")
        template_params["uploader"] = channel_name[0].firstChild.nodeValue if channel_name else user_nickname[0].firstChild.nodeValue if user_nickname else None

    return template_params


def valid_url(url):
    """Check if the URL is valid and can be processed."""

    url_mo = VIDEO_URL_RE.match(url)
    return url_mo if not None else False


def process_url_mo(session, url_mo):
    """Determine which function should process this URL object."""

    url_id = url_mo.group(3)
    if url_mo.group(2) == "mylist":
        request_mylist(session, url_id)
    elif url_mo.group(1):
        live_url_stub()
    elif url_mo.group(2) == "user":
        request_user(session, url_id)
    else:
        request_video(session, url_id)


def main():
    try:
        configure_logger()
        # Test if input is a valid URL or file
        url_mo = valid_url(cmdl_opts.input)
        if not url_mo:
            open(cmdl_opts.input)

        account_username = cmdl_opts.username
        account_password = cmdl_opts.password

        if cmdl_opts.netrc:
            if cmdl_opts.username or cmdl_opts.password:
                output("Ignorning input credentials in favor of .netrc.\n", logging.WARNING)

            account_credentials = netrc.netrc().authenticators(HOST)
            if account_credentials:
                account_username = account_credentials[0]
                account_password = account_credentials[2]
            else:
                raise netrc.NetrcParseError("No authenticator available for {0}".format(HOST))
        elif not cmdl_opts.no_login:
            if not account_username:
                account_username = input("Username: ")
            if not account_password:
                account_password = getpass.getpass("Password: ")
        else:
            output("Proceeding with no login. Some videos may not be available for download or may only be available in a lower quality. For access to all videos, please provide a login with --username/--password or --netrc.\n", logging.WARNING)

        session = login(account_username, account_password)
        if url_mo:
            process_url_mo(session, url_mo)
        else:
            read_file(session, cmdl_opts.input)

    except Exception as error:
        log_exception(error)
        raise


if __name__ == "__main__":
    try:
        cmdl_opts = cmdl_parser.parse_args()
        main()
    except KeyboardInterrupt:
        sys.exit(1)
