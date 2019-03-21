#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Download videos from Niconico (nicovideo.jp), formerly known as Nico Nico Douga."""

from bs4 import BeautifulSoup
import requests

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
import random

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
dl_group.add_argument("-e", "--english", action="store_true", dest="download_english", help="download english comments")

cmdl_opts = cmdl_parser.parse_args()


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


if cmdl_opts.log:
    logger = logging.getLogger(__name__)
    logger.setLevel(logging.INFO)
    log_handler = logging.FileHandler("[{0}] {1}.log".format("nndownload", time.strftime("%Y-%m-%d")))
    formatter = logging.Formatter("%(asctime)s %(levelname)s: %(message)s")
    log_handler.setFormatter(formatter)
    logger.addHandler(log_handler)


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


def request_rtmp(session, nama_id):
    """Build the RTMP stream URL for a Niconama broadcast and print to console."""

    nama_xml = session.get(NAMA_API.format(nama_id), allow_redirects=False)
    nama_xml.raise_for_status()
    if not nama_xml.text:
        raise FormatNotAvailableException("Could not retrieve nama info from API")

    nama_info = xml.dom.minidom.parseString(nama_xml.text)
    if nama_info.getElementsByTagName("error"):
        raise FormatNotAvailableException("Requested nama is not available")

    url = None
    urls = urllib.parse.unquote(nama_info.getElementsByTagName("contents")[0].firstChild.nodeValue).split(",")
    is_premium = nama_info.getElementsByTagName("is_premium")[0].firstChild.nodeValue
    provider_type = nama_info.getElementsByTagName("provider_type")[0].firstChild.nodeValue

    if provider_type == "official":
        for details, stream_name in pairwise(urls):
            split = details.split(":", maxsplit=2)
            if (is_premium and split[0] == "premium") or ((not is_premium or provider_type == "official") and (split[0] == "default" or split[0] == "limelight")):
                url = split[2] + "/" + stream_name
                if nama_info.getElementsByTagName("hqstream"):
                    url = url.split(":", maxsplit=1)[1]
                break

        if not url:
            raise FormatNotSupportedException("RTMP URL not found for requested nama")
    elif provider_type == "community":
        raise FormatNotSupportedException("Community nama broadcasts are not supported")
    elif provider_type == "channel":
        raise FormatNotSupportedException("Channel nama broadcasts are not supported")
    else:
        raise FormatNotSupportedException("Not a recognized stream provider type")

    for stream in nama_info.getElementsByTagName("stream"):
        if stream.getAttribute("name") == stream_name:
            rtmp = url + "?" + stream.firstChild.nodeValue
            output("{0}\n".format(rtmp), logging.INFO)
            return


def request_cas(session, nama_id):
    """Build the HLS stream URL for an experimental Niconama broadcast."""

    output("Support for CAS streams is still experimental.\n", logging.WARNING)

    cas_headers = {
        "Content-Type": "application/json",
        "X-Connection-Environment": "ethernet",
        "X-Frontend-Id": "91"
    }

    cas_cors = {
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "content-type,x-connection-environment,x-frontend-id",
        "Origin": "https://cas.nicovideo.jp",
    }

    qualities_options = session.options(CAS_QUALITIES_API.format(nama_id), headers=cas_cors)
    qualities_options.raise_for_status()

    nama_qualities = session.get(CAS_QUALITIES_API.format(nama_id), headers=cas_headers)
    nama_qualities.raise_for_status()

    watching_url = CAS_WATCHING_API.format(nama_id)
    watching_options = session.options(watching_url, headers=cas_cors)
    watching_options.raise_for_status()

    watching_data = {
        "actionTrackId": generate_track_id(),
        "isBroadcaster": "false",
        "streamProtocol": "https",
        "streamQuality": "auto"
    }

    watching = session.post(watching_url, headers=cas_headers, json=watching_data)
    watching.raise_for_status()

    watching_json = json.loads(watching.text)
    master_url = watching_json["data"]["streamServer"]["url"]
    sync_url = watching_json["data"]["streamServer"]["syncUrl"]

    m3u8 = session.get(master_url)
    m3u8.raise_for_status()

    playlist_url = parse_m3u8(m3u8.text.splitlines())
    stream_url = master_url.rsplit("/", maxsplit=1)[0] + "/" + playlist_url
    output("{0}\n".format(stream_url), logging.INFO)

    perform_cas_heartbeat(session, watching_url, cas_headers, watching_data)


def generate_track_id():
    """Generate a tracking ID string for use in DMC requests."""

    epoch_str = str(time.time()).replace(".", "")
    return ("".join(random.choice("0123456789abcdef") for n in range(10)) + "_" + epoch_str)[:24]


def parse_m3u8(m3u8):
    """Get the first playlist from the master .m3u8."""

    text = iter(m3u8)
    for line in text:
        if line.startswith("#EXT-X-STREAM-INF"):
            return next(text)


def perform_cas_heartbeat(session, heartbeat_url, cas_headers, watching_data):
    """Perform a heartbeat to keep the stream alive."""

    # TODO: Report if the stream URL changes

    output("Keeping stream URL alive. Press ^C to quit.\n", logging.INFO)
    past = time.time()

    while True:
        try:
            current = time.time()
            if current - past >= CAS_HEARTBEAT_INTERVAL_S:
                past = current
                response = session.put(heartbeat_url, headers=cas_headers, json=watching_data)
                response.raise_for_status()
        except KeyboardInterrupt:
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

    # This is the file type for the original encode
    # When logged out, Flash videos will sometimes be served on the HTML5 player with a low quality .mp4 re-encode
    # Some Flash videos are not available outside of the Flash player
    video_type = video_info.getElementsByTagName("movie_type")[0].firstChild.nodeValue
    if video_type == "swf" or video_type == "flv":
        response = session.get(VIDEO_URL.format(video_id), cookies=FLASH_COOKIE)
    elif video_type == "mp4":
        response = session.get(VIDEO_URL.format(video_id), cookies=HTML5_COOKIE)
    else:
        raise FormatNotAvailableException("Video type not supported")

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
        current_byte_pos = os.path.getsize(filename)
        if current_byte_pos < video_len:
            file_condition = "ab"
            resume_header = {"Range": "bytes={0}-".format(current_byte_pos)}
            dl = current_byte_pos
            output("Resuming previous download.\n", logging.INFO)

        elif current_byte_pos >= video_len:
            output("File exists and is complete.\n", logging.INFO)
            return

    else:
        file_condition = "wb"
        resume_header = {"Range": "bytes=0-"}
        dl = 0

    dl_stream = session.get(template_params["url"], headers=resume_header, stream=True)
    dl_stream.raise_for_status()

    with open(filename, file_condition) as file:
        start_time = time.time()
        for block in dl_stream.iter_content(BLOCK_SIZE):
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
            if cmdl_opts.log:
                logger.exception("{0}: {1}\n".format(type(error).__name__, str(error)))
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
            if cmdl_opts.log:
                logger.exception("{0}: {1}\n".format(type(error).__name__, str(error)))
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
                if cmdl_opts.log:
                    logger.exception("{0}: {1}\n".format(type(error).__name__, str(error)))
                traceback.print_exc()
                continue


def perform_api_request(session, document):
    """Collect parameters from video document and build API request for video URL."""

    template_params = {}

    # .mp4 videos (HTML5)
    if document.find(id="js-initial-watch-data"):
        params = json.loads(document.find(id="js-initial-watch-data")["data-api-data"])

        if params["video"]["isDeleted"]:
            raise FormatNotAvailableException("Video was deleted")

        template_params = collect_parameters(session, template_params, params, isHtml5=True)

        if template_params["quality"] != "auto" and cmdl_opts.force_high_quality:
            raise FormatNotAvailableException("High quality source is not available")

        # Perform request to Dwango Media Cluster (DMC)
        if params["video"].get("dmcInfo"):
            api_url = params["video"]["dmcInfo"]["session_api"]["urls"][0]["url"] + "?suppress_response_codes=true&_format=xml"
            recipe_id = params["video"]["dmcInfo"]["session_api"]["recipe_id"]
            content_id = params["video"]["dmcInfo"]["session_api"]["content_id"]
            protocol = params["video"]["dmcInfo"]["session_api"]["protocols"][0]
            file_extension = template_params["ext"]
            priority = params["video"]["dmcInfo"]["session_api"]["priority"]
            video_sources = params["video"]["dmcInfo"]["session_api"]["videos"]
            audio_sources = params["video"]["dmcInfo"]["session_api"]["audios"]
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
            template_params["url"] = params["video"]["smileInfo"]["url"]

        else:
            raise ParameterExtractionException("Failed to find video URL. Nico may have updated their player")

    # Flash videos (.flv, .swf)
    # NicoMovieMaker videos (.swf) may need conversion to play properly in an external player
    elif document.find(id="watchAPIDataContainer"):
        params = json.loads(document.find(id="watchAPIDataContainer").text)

        if params["videoDetail"]["isDeleted"]:
            raise FormatNotAvailableException("Video was deleted")

        template_params = collect_parameters(session, template_params, params, isHtml5=False)

        if template_params["quality"] != "auto" and cmdl_ops.force_high_quality:
            raise FormatNotAvailableException("High quality source is not available")

        video_url_param = urllib.parse.parse_qs(urllib.parse.unquote(urllib.parse.unquote(params["flashvars"]["flvInfo"])))
        if ("url" in video_url_param):
            template_params["url"] = video_url_param["url"][0]

        else:
            raise ParameterExtractionException("Failed to find video URL. Nico may have updated their player")

    else:
        raise ParameterExtractionException("Failed to collect video paramters")

    return template_params


def collect_parameters(session, template_params, params, isHtml5):
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

        if params["video"].get("dmcInfo"):
            template_params["video_quality"] = params["video"]["dmcInfo"]["quality"]["videos"][0]["id"]
            template_params["audio_quality"] = params["video"]["dmcInfo"]["quality"]["audios"][0]["id"]

            # Qualities are sorted in descending order, so we use this assumption to check availability
            if params["video"]["dmcInfo"]["quality"]["videos"][0]["available"]:
                template_params["quality"] = "auto"
            else:
                template_params["quality"] = "low"

        elif params["video"].get("smileInfo"):
            template_params["quality"] = params["video"]["smileInfo"]["currentQualityId"]

        else:
            raise ParameterExtractionException("Failed to extract video quality")

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
        template_params["quality"] = "auto"  # If we've reached the Flash player, we're being served the highest quality possible

    response = session.get(THUMB_INFO_API.format(template_params["id"]))
    response.raise_for_status()
    video_info = xml.dom.minidom.parseString(response.text)

    # DMC videos do not expose the file type in the video page parameters when not logged in
    # If this is a Flash video being served on the HTML5 player, it's guaranteed to be a low quality .mp4 re-encode
    template_params["ext"] = video_info.getElementsByTagName("movie_type")[0].firstChild.nodeValue
    if isHtml5 and (template_params["ext"] == "swf" or template_params["ext"] == "flv"):
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
    elif url_mo.group(1) == "cas":
        request_cas(session, url_id)
    elif url_mo.group(2) == "user":
        request_user(session, url_id)
    elif url_mo.group(1):
        request_rtmp(session, url_id)
    else:
        request_video(session, url_id)


def main():
    try:
        # Test if input is a valid URL or file
        url_mo = valid_url(cmdl_opts.input)
        if not url_mo:
            open(cmdl_opts.input)

        account_username = cmdl_opts.username
        account_password = cmdl_opts.password

        if cmdl_opts.netrc:
            if cmdl_opts.username or cmdl_opts.password:
                output("Ignorning input credentials in favor of .netrc (-n)\n", logging.WARNING)

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
            output("Proceeding with no login. Some videos may not be available for download or may only be available in low quality. For access to all videos, please provide a login with --username/--password or --netrc.\n", logging.WARNING)

        session = login(account_username, account_password)
        if url_mo:
            process_url_mo(session, url_mo)
        else:
            read_file(session, cmdl_opts.input)

    except Exception as error:
        if cmdl_opts.log:
            logger.exception("{0}: {1}\n".format(type(error).__name__, str(error)))
        traceback.print_exc()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(1)
