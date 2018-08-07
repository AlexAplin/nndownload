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
import optparse
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
NAMA_API = "http://watch.live.nicovideo.jp/api/getplayerstatus?v={0}"
THUMB_INFO_API = "http://ext.nicovideo.jp/api/getthumbinfo/{0}"
MYLIST_API = "http://flapi.nicovideo.jp/api/getplaylist/mylist/{0}"
COMMENTS_API = "http://nmsg.nicovideo.jp/api"
COMMENTS_POST_JP = "<packet><thread thread=\"{0}\" version=\"20061206\" res_from=\"-1000\" scores=\"1\"/></packet>"
COMMENTS_POST_EN = "<packet><thread thread=\"{0}\" version=\"20061206\" res_from=\"-1000\" language=\"1\" scores=\"1\"/></packet>"
VIDEO_URL_RE = re.compile(r"(?:https?://(?:(?:(?:sp|www)\.)?(?:(live[0-9]?)\.)?(?:(?:nicovideo\.jp/(watch|mylist)/)|nico\.ms/)))((?:[a-z]{2})?[0-9]+)")
DMC_HEARTBEAT_INTERVAL_S = 15
KILOBYTE = 1024
BLOCK_SIZE = 10 * KILOBYTE
EPSILON = 0.0001

FINISHED_DOWNLOADING = False

HTML5_COOKIE = {
    "watch_flash": "0"
}

FLASH_COOKIE = {
    "watch_flash": "1"
}

cmdl_usage = "%prog [options] url"
cmdl_version = __version__
cmdl_parser = optparse.OptionParser(usage=cmdl_usage, version=cmdl_version, conflict_handler="resolve")
cmdl_parser.add_option("-u", "--username", dest="username", metavar="USERNAME", help="account username")
cmdl_parser.add_option("-p", "--password", dest="password", metavar="PASSWORD", help="account password")
cmdl_parser.add_option("-i", "--file", dest="file", metavar="FILE", help="read URLs from file")
cmdl_parser.add_option("-n", "--netrc", action="store_true", dest="netrc", help="use .netrc authentication")
cmdl_parser.add_option("-q", "--quiet", action="store_true", dest="quiet", help="suppress output to console")
cmdl_parser.add_option("-l", "--log", action="store_true", dest="log", help="log output to file")

dl_group = optparse.OptionGroup(cmdl_parser, "Download Options")
dl_group.add_option("-y", "--proxy", dest="proxy", metavar="PROXY", help="http or socks proxy")
dl_group.add_option("-o", "--output-path", dest="output_path", help="custom output path (see template options)")
dl_group.add_option("-f", "--force-high-quality", action="store_true", dest="force_high_quality", help="only download if the high quality source is available")
dl_group.add_option("-m", "--dump-metadata", action="store_true", dest="dump_metadata", help="dump video metadata to file")
dl_group.add_option("-t", "--download-thumbnail", action="store_true", dest="download_thumbnail", help="download video thumbnail")
dl_group.add_option("-c", "--download-comments", action="store_true", dest="download_comments", help="download video comments")
dl_group.add_option("-e", "--english", action="store_true", dest="download_english", help="download english comments")

cmdl_parser.add_option_group(dl_group)
(cmdl_opts, cmdl_args) = cmdl_parser.parse_args()


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

    output("Logging in...\n", logging.INFO)

    LOGIN_POST = {
        "mail_tel": username,
        "password": password
    }

    session = requests.session()
    session.headers.update({"User-Agent": "nndownload/%s".format(__version__)})

    if cmdl_opts.proxy:
        proxies = {
            "http": cmdl_opts.proxy,
            "https": cmdl_opts.proxy
        }
        session.proxies.update(proxies)

    response = session.post(LOGIN_URL, data=LOGIN_POST)
    response.raise_for_status()
    if session.cookies.get_dict().get("user_session", None) is None:
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
    """Build the RTMP stream URL for a Niconama broadcast and print to file."""

    nama_xml = session.get(NAMA_API.format(nama_id), allow_redirects=False).text
    if not nama_xml:
        raise FormatNotAvailableException("Could not retrieve nama info from API")

    nama_info = xml.dom.minidom.parseString(nama_xml)
    if nama_info.getElementsByTagName("error"):
        raise FormatNotAvailableException("Requested nama is not available")

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
    else:
        raise FormatNotSupportedException("Not a recognized stream provider type")

    for stream in nama_info.getElementsByTagName("stream"):
        if stream.getAttribute("name") == stream_name:
            rtmp = url + "?" + stream.firstChild.nodeValue
            output("{0}\n".format(rtmp), logging.INFO)

def request_video(session, video_id):
    """Request the video page and initiate download of the video URL."""

    # Determine whether to request the Flash or HTML5 player
    # Only .mp4 videos are served on the HTML5 player, so we can sometimes miss the high quality .flv source
    response = session.get(THUMB_INFO_API.format(video_id))
    response.raise_for_status()

    video_info = xml.dom.minidom.parseString(response.text)

    if video_info.firstChild.getAttribute("status") != "ok":
        raise FormatNotAvailableException("Could not retrieve video info")

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


def perform_heartbeat(response, session, heartbeat_url):
    """Perform a response heartbeat to keep the download connection alive."""

    response = session.post(heartbeat_url, data=response.toxml())
    response.raise_for_status()
    response = xml.dom.minidom.parseString(response.text).getElementsByTagName("session")[0]
    if not FINISHED_DOWNLOADING:
        heartbeat_timer = threading.Timer(DMC_HEARTBEAT_INTERVAL_S, perform_heartbeat, (response, session, heartbeat_url))
        heartbeat_timer.daemon = True
        heartbeat_timer.start()


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

    base_path, old_extension = os.path.splitext(filename)
    return "{0}.{1}".format(base_path, new_extension)


def sanitize_for_path(value, replace=' '):
    """Remove potentially illegal characters from a path."""
    return re.sub('[<>\"\?\\\/\*:]', replace, value)


def create_filename(template_params):
    """Create filename from document parameters."""

    filename_template = cmdl_opts.output_path

    if filename_template:
        template_dict = dict(template_params)
        template_dict = dict((k, sanitize_for_path(str(v))) for k, v in template_dict.items() if v is not None)
        template_dict = collections.defaultdict(lambda: "__NONE__", template_dict)

        filename = filename_template.format_map(template_dict)
        try:
            if (os.path.dirname(filename) and not os.path.exists(os.path.dirname(filename))) or os.path.exists(os.path.dirname(filename)):
                os.makedirs(os.path.dirname(filename), exist_ok=True)

        except (OSError, IOError):
            raise

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

    if cmdl_opts.force_high_quality and video_len == template_params["size_low"]:
        raise FormatNotAvailableException("High quality source not currently available")

    if os.path.isfile(filename):
        current_byte_pos = os.path.getsize(filename)
        if current_byte_pos < video_len:
            file_condition = "ab"
            resume_header = {"Range": "bytes={}-".format(current_byte_pos)}
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
    FINISHED_DOWNLOADING = True


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

    get_thumb = session.get(template_params["thumbnail_url"])
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
    with open(filename, "wb") as file:
        file.write(get_comments.content)

    output("Finished downloading comments for {0}.\n".format(template_params["id"]), logging.INFO)


def read_file(session, file):
    """Read file and process each line as a URL."""

    with open(file) as file:
        content = file.readlines()
    for line in content:
        try:
            url_mo = valid_url(line)
            if url_mo:
                process_url_mo(session, url_mo)
            else:
                raise ArgumentException("Not a valid URL")
        except FileCompleteException:
            output("File exists and is complete. Skipping...\n", logging.INFO)
            continue
        except (FormatNotSupportedException, FormatNotAvailableException, ParameterExtractionException) as error:
            if cmdl_opts.log:
                logger.exception("{0}: {1}\n".format(type(error).__name__, str(error)))
            traceback.print_exc()
            continue

def request_mylist(session, mylist_id):
    """Download videos associated with a mylist."""

    output("Downloading mylist {0}...\n".format(mylist_id), logging.INFO)
    mylist_request = session.get(MYLIST_API.format(mylist_id))
    mylist_json = json.loads(mylist_request.text)

    if mylist_json["status"] != "ok":
        raise FormatNotAvailableException("Could not retrieve mylist info")
    else:
        for index, item in enumerate(mylist_json["items"]):
            try:
                output("{0}/{1}\n".format(index, len(mylist_json["items"])), logging.INFO)
                request_video(session, item["video_id"])
            except FileCompleteException:
                output("File exists and is complete. Skipping...\n", logging.INFO)
                continue
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

        template_params = collect_parameters(session, template_params, params)

        # Perform request to Dwango Media Cluster (DMC)
        if params["video"].get("dmcInfo"):
            api_url = params["video"]["dmcInfo"]["session_api"]["urls"][0]["url"] + "?suppress_response_codes=true&_format=xml"
            recipe_id = params["video"]["dmcInfo"]["session_api"]["recipe_id"]
            content_id = params["video"]["dmcInfo"]["session_api"]["content_id"]
            protocol = params["video"]["dmcInfo"]["session_api"]["protocols"][0]
            file_extension = params["video"]["movieType"]
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
            response = session.post(api_url, data=root.toxml())
            response.raise_for_status()
            response = xml.dom.minidom.parseString(response.text)
            template_params["url"] = response.getElementsByTagName("content_uri")[0].firstChild.nodeValue
            output("Performed initial API request.\n", logging.INFO)

            # Collect response for heartbeat
            session_id = response.getElementsByTagName("id")[0].firstChild.nodeValue
            response = response.getElementsByTagName("session")[0]
            heartbeat_url = params["video"]["dmcInfo"]["session_api"]["urls"][0]["url"] + "/" + session_id + "?_format=xml&_method=PUT"
            perform_heartbeat(response, session, heartbeat_url)

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

        template_params = collect_parameters(session, template_params, params)

        video_url_param = urllib.parse.parse_qs(urllib.parse.unquote(urllib.parse.unquote(params["flashvars"]["flvInfo"])))
        if ("url" in video_url_param):
            template_params["url"] = video_url_param["url"][0]

        else:
            raise ParameterExtractionException("Failed to find video URL. Nico may have updated their player")
            return

    else:
        raise ParameterExtractionException("Failed to collect video paramters")
        return

    return template_params


def collect_parameters(session, template_params, params):
    """Collect video parameters to make them available for an output filename template."""

    if params.get("video"):
        template_params["id"] = params["video"]["id"]
        template_params["title"] = params["video"]["title"]
        template_params["uploader"] = params["owner"]["nickname"].rstrip(" さん") if params.get("owner") else None
        template_params["uploader_id"] = int(params["owner"]["id"]) if params.get("owner") else None
        template_params["ext"] = params["video"]["movieType"]
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
        template_params["ext"] = params["flashvars"]["movie_type"]
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

    template_params["size_high"] = int(video_info.getElementsByTagName("size_high")[0].firstChild.nodeValue)
    template_params["size_low"] = int(video_info.getElementsByTagName("size_low")[0].firstChild.nodeValue)

    # Check if we couldn't capture uploader info before
    if not template_params["uploader"] or not template_params["uploader_id"]:
        ch_id = video_info.getElementsByTagName("ch_id")
        ch_name = video_info.getElementsByTagName("ch_name")
        user_id = video_info.getElementsByTagName("user_id")
        user_nickname = video_info.getElementsByTagName("user_nickname")
        if ch_id and ch_name:
            template_params["uploader"] = ch_name[0].firstChild.nodeValue
            template_params["uploader_id"] = ch_id[0].firstChild.nodeValue

        elif ch_id and ch_name:
            template_params["uploader"] = user_id[0].firstChild.nodeValue
            template_params["uploader_id"] = user_nickname[0].firstChild.nodeValue

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
        request_rtmp(session, url_id)
    else:
        request_video(session, url_id)


def main():
    try:
        if not cmdl_opts.file:
            if len(cmdl_args) == 0:
                raise ArgumentException("You must provide a video, nama, mylist, or file (-f)")
            else:
                global url_mo
                url_mo = valid_url(cmdl_args[0])
                if not url_mo:
                    raise ArgumentException("Not a valid video, nama, or mylist URL")

        account_username = cmdl_opts.username
        account_password = cmdl_opts.password

        if cmdl_opts.netrc:
            if cmdl_opts.username or cmdl_opts.password:
                output("Ignorning input credentials in favor of .netrc (-n)\n", logging.WARNING)

            try:
                account_credentials = netrc.netrc().authenticators(HOST)
                if account_credentials is not None:
                    account_username = account_credentials[0]
                    account_password = account_credentials[2]
                else:
                    raise netrc.NetrcParseError("No authenticator available for {}".format(HOST))

            except (FileNotFoundError, IOError, netrc.NetrcParseError):
                raise

        if account_username is None:
            account_username = getpass.getpass("Username: ")
        if account_password is None:
            account_password = getpass.getpass("Password: ")

        session = login(account_username, account_password)
        if cmdl_opts.file:
            if len(cmdl_args) > 0:
                output("Ignoring argument in favor of file (-f)\n", logging.WARNING)
            read_file(session, cmdl_opts.file)
        else:
            process_url_mo(session, url_mo)
    except Exception as error:
        if cmdl_opts.log:
            logger.exception("{0}: {1}\n".format(type(error).__name__, str(error)))
        traceback.print_exc()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        output("Exiting...", logging.INFO)
        sys.exit(1)
