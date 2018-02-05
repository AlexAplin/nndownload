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
import subprocess
import collections

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
COMMENTS_POST = "<packet><thread thread=\"{0}\" version=\"20061206\" res_from=\"-1000\" scores=\"1\"/></packet>"
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
cmdl_parser.add_option("-f", "--file", dest="file", metavar="FILE", help="read URLs from file")
cmdl_parser.add_option("-n", "--netrc", action="store_true", dest="netrc", help="use .netrc authentication")
cmdl_parser.add_option("-v", "--verbose", action="store_true", dest="verbose", help="print status to console")

dl_group = optparse.OptionGroup(cmdl_parser, "Download Options")
dl_group.add_option("-o", "--output-path", dest="output_path", help="custom output path (see template options)")
dl_group.add_option("-f", "--force-high-quality", action="store_true", dest="force_high_quality", help="only download if the high quality source is available")
dl_group.add_option("-m", "--dump-metadata", action="store_true", dest="dump_metadata", help="dump video metadata to file")
dl_group.add_option("-t", "--download-thumbnail", action="store_true", dest="download_thumbnail", help="download video thumbnail")
dl_group.add_option("-c", "--download-comments", action="store_true", dest="download_comments", help="download video comments")

cmdl_parser.add_option_group(dl_group)
(cmdl_opts, cmdl_args) = cmdl_parser.parse_args()


def cond_print(string):
    """Print status to console if verbose flag is set."""

    global cmdl_opts
    if cmdl_opts.verbose:
        sys.stdout.write(string)
        sys.stdout.flush()


def login(username, password):
    """Login to Nico. Will raise an exception for errors."""

    cond_print("Logging in...")

    LOGIN_POST = {
        "mail_tel": username,
        "password": password
    }

    session = requests.session()
    session.headers.update({"User-Agent": "nndownload/%s".format(__version__)})
    response = session.post(LOGIN_URL, data=LOGIN_POST)
    response.raise_for_status()
    if session.cookies.get_dict().get("user_session", None) is None:
        cond_print(" failed\n")
        sys.exit("Error: Failed to login. Please verify your username and password")

    cond_print(" done\n")
    return session


def pairwise(iterable):
    """Helper method to pair RTMP URL with stream label."""

    a, b = tee(iterable)
    next(b, None)
    return zip(a, b)


def request_rtmp(session, nama_id):
    """Build the RTMP stream URL for a Niconama broadcast and print to file."""

    nama_info = xml.dom.minidom.parseString(session.get(NAMA_API.format(nama_id)).text)
    if nama_info.getElementsByTagName("error"):
        cond_print("Error: Broadcast is not available\n")
        return

    urls = urllib.parse.unquote(nama_info.getElementsByTagName("contents")[0].firstChild.nodeValue).split(',')
    is_premium = nama_info.getElementsByTagName("is_premium")[0].firstChild.nodeValue
    provider_type = nama_info.getElementsByTagName("provider_type")[0].firstChild.nodeValue
    if provider_type == "official":
        for details, stream_name in pairwise(urls):
            split = details.split(":", maxsplit=1)
            if (is_premium and split[0] == "premium") or ((not is_premium or provider_type == "official") and (split[0] == "default" or split[0] == "limelight")):
                url = split[1] + "/" + stream_name
                if nama_info.getElementsByTagName("hqstream"):
                    url = url.split(":", maxsplit=1)[1]
                break

        if not url:
            cond_print("Error: RTMP URL not found\n")
            return
    elif provider_type == "community":
        cond_print("Error: Community broadcasts are not supported\n")
        return
    else:
        cond_print("Error: Not a recognized stream provider type\n")
        return

    for stream in nama_info.getElementsByTagName("stream"):
        if stream.getAttribute('name') == stream_name:
            rtmp = url + '?' + stream.firstChild.nodeValue
            cond_print(rtmp)
            with open("{}.txt".format(nama_id), "w") as file:
                file.write(rtmp)


def request_video(session, video_id):
    """Request the video page and initiate download of the video URL."""

    # Determine whether to request the Flash or HTML5 player
    # Only .mp4 videos are served on the HTML5 player, so we can sometimes miss the high quality .flv source
    response = session.get(THUMB_INFO_API.format(video_id))
    response.raise_for_status()

    video_info = xml.dom.minidom.parseString(response.text)

    if video_info.firstChild.getAttribute("status") != "ok":
        cond_print("Error: Could not retrieve video info\n")
        return

    video_type = video_info.getElementsByTagName("movie_type")[0].firstChild.nodeValue
    if video_type == "swf" or "flv":
        response = session.get(VIDEO_URL.format(video_id), cookies=FLASH_COOKIE)
    elif video_type == "mp4":
        response = session.get(VIDEO_URL.format(video_id), cookies=HTML5_COOKIE)
    else:
        cond_print("Error: Video type not supported. Skipping...\n")
        return

    response.raise_for_status()
    document = BeautifulSoup(response.text, "html.parser")

    template_params = perform_api_request(session, document)
    template_params["size_high"] = int(video_info.getElementsByTagName("size_high")[0].firstChild.nodeValue)
    template_params["size_low"] = int(video_info.getElementsByTagName("size_low")[0].firstChild.nodeValue)

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
        sys.exit("Error: Could not format number of bytes")


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


def create_filename(template_params):
    """Create filename from document parameters."""

    filename_template = cmdl_opts.output_path

    if filename_template:
        template_dict = dict(template_params)
        template_dict = dict((k, v) for k, v in template_dict.items() if v is not None)
        template_dict = collections.defaultdict(lambda: "__NONE__", template_dict)

        filename = filename_template.format_map(template_dict)
        try:
            if (os.path.dirname(filename) and not os.path.exists(os.path.dirname(filename))) or os.path.exists(os.path.dirname(filename)):
                os.makedirs(os.path.dirname(filename), exist_ok=True)

        except (OSError, IOError):
            sys.exit("Error: Unable to create specified directory")

        return filename
    else:
        return "{0} - {1}.{2}".format(template_params["id"], template_params["title"], template_params["ext"])


def download_video(session, filename, template_params):
    """Download video from response URL and display progress."""

    try:
        dl_stream = session.head(template_params["url"])
        dl_stream.raise_for_status()
        video_len = int(dl_stream.headers["content-length"])

        if cmdl_opts.force_high_quality and video_len == template_params["size_low"]:
            cond_print("High quality source not currently available. Skipping... \n")
            return

        if os.path.isfile(filename):
            current_byte_pos = os.path.getsize(filename)
            if current_byte_pos < video_len:
                file_condition = "ab"
                resume_header = {"Range": "bytes={}-".format(current_byte_pos)}
                dl = current_byte_pos
                cond_print("Resuming previous download...\n")

            elif current_byte_pos >= video_len:
                cond_print("File exists and is complete. Skipping...\n")
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
                cond_print("\r|{0}{1}| {2}/100 @ {3:9}/s".format("#" * done, " " * (25 - done), percent, speed_str))

        cond_print("\n")
        FINISHED_DOWNLOADING = True

    except KeyboardInterrupt:
        sys.exit()


def dump_metadata(filename, template_params):
    """Dump the collected video metadata to a file."""

    cond_print("Downloading metadata...")

    filename = replace_extension(filename, "json")

    with open(filename, "w") as file:
        json.dump(template_params, file, sort_keys=True)

    cond_print(" done\n")


def download_thumbnail(session, filename, template_params):
    """Download the video thumbnail."""

    cond_print("Downloading thumbnail...")

    filename = replace_extension(filename, "jpg")

    get_thumb = session.get(template_params["thumbnail_url"])
    with open(filename, "wb") as file:
        for block in get_thumb.iter_content(BLOCK_SIZE):
            file.write(block)

    cond_print(" done\n")


def download_comments(session, filename, template_params):
    """Download the video comments."""

    cond_print("Downloading comments...")

    filename = replace_extension(filename, "xml")

    get_comments = session.post(COMMENTS_API, COMMENTS_POST.format(template_params["thread_id"]))
    with open(filename, "wb") as file:
        file.write(get_comments.content)

    cond_print(" done\n")


def read_file(session, file):
    """Read file and process each line as a URL."""

    with open(file) as file:
        content = file.readlines()
    download_list = []
    for line in content:
        url_mo = valid_url(line)
        if url_mo:
            process_url_mo(session, url_mo)
        else:
            cond_print("Error parsing arguments: Not a valid URL. Skipping...\n")


def request_mylist(session, mylist_id):
    """Download videos associated with a mylist."""

    mylist_request = session.get(MYLIST_API.format(mylist_id))
    mylist_json = json.loads(mylist_request.text)

    if mylist_json["status"] != "ok":
        cond_print("Error: Could not retrieve mylist info\n")
        return
    else:
        for index, item in enumerate(mylist_json["items"]):
            cond_print("{0}/{1}\n".format(index, len(mylist_json["items"])))
            request_video(session, item["video_id"])


def perform_api_request(session, document):
    """Collect parameters from video document and build API request for video URL."""

    template_params = {}

    # .mp4 videos (HTML5)
    if document.find(id="js-initial-watch-data"):
        params = json.loads(document.find(id="js-initial-watch-data")["data-api-data"])

        if params["video"]["isDeleted"]:
            cond_print("Error: Video was deleted. Skipping...\n")
            return

        template_params = collect_parameters(template_params, params)

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

            cond_print("Performing initial API request...")
            headers = {"Content-Type": "application/xml"}
            response = session.post(api_url, data=root.toxml())
            response.raise_for_status()
            response = xml.dom.minidom.parseString(response.text)
            template_params["url"] = response.getElementsByTagName("content_uri")[0].firstChild.nodeValue
            cond_print(" done\n")

            # Collect response for heartbeat
            session_id = response.getElementsByTagName("id")[0].firstChild.nodeValue
            response = response.getElementsByTagName("session")[0]
            heartbeat_url = params["video"]["dmcInfo"]["session_api"]["urls"][0]["url"] + "/" + session_id + "?_format=xml&_method=PUT"
            perform_heartbeat(response, session, heartbeat_url)

        # Legacy URL for videos uploaded pre-HTML5 player (~2016-10-27)
        elif params["video"].get("smileInfo"):
            cond_print("Using legacy URL...\n")
            template_params["url"] = params["video"]["smileInfo"]["url"]

        else:
            cond_print("Error collecting parameters: Failed to find video URL. Nico may have updated their player\n")
            return

    # Flash videos (.flv, .swf)
    # NicoMovieMaker videos (.swf) may need conversion to play properly in an external player
    elif document.find(id="watchAPIDataContainer"):
        params = json.loads(document.find(id="watchAPIDataContainer").text)

        if params["videoDetail"]["isDeleted"]:
            cond_print("Error: Video was deleted. Skipping...\n")
            return

        template_params = collect_parameters(template_params, params)

        video_url_param = urllib.parse.parse_qs(urllib.parse.unquote(urllib.parse.unquote(params["flashvars"]["flvInfo"])))
        if ("url" in video_url_param):
            template_params["url"] = video_url_param["url"][0]

        else:
            cond_print("Error collecting parameters: Failed to find video URL. Nico may have updated their player\n")
            return

    else:
        cond_print("Error collecting parameters: Failed to collect video paramters\n")
        return

    return template_params


def collect_parameters(template_params, params):
    """Collect video parameters to make them available for an output filename template."""

    if params.get("video"):
        template_params["id"] = params["video"]["id"]
        template_params["title"] = params["video"]["title"]
        template_params["uploader"] = params["owner"]["nickname"].rstrip(" さん") if params["owner"] else None
        template_params["uploader_id"] = int(params["owner"]["id"]) if params["owner"] else None
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
        template_params["uploader"] = params["uploaderInfo"]["nickname"].rstrip(" さん") if params["uploaderInfo"] else None
        template_params["uploader_id"] = int(params["uploaderInfo"]["id"]) if params["uploaderInfo"] else None
        template_params["ext"] = params["flashvars"]["movie_type"]
        template_params["description"] = params["videoDetail"]["description"]
        template_params["thumbnail_url"] = params["videoDetail"]["thumbnail"]
        template_params["thread_id"] = int(params["videoDetail"]["thread_id"])
        template_params["published"] = params["videoDetail"]["postedAt"]
        template_params["duration"] = params["videoDetail"]["length"]
        template_params["view_count"] = params["videoDetail"]["viewCount"]
        template_params["mylist_count"] = params["videoDetail"]["mylistCount"]
        template_params["comment_count"] = params["videoDetail"]["commentCount"]

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


if __name__ == "__main__":
    if not cmdl_opts.file:
        if len(cmdl_args) == 0:
            sys.exit("Error parsing arguments: You must provide a video, nama, mylist, or file (-f)")
        else:
            global url_mo
            url_mo = valid_url(cmdl_args[0])
            if not url_mo:
                sys.exit("Error parsing arguments: Not a valid video, nama, or mylist URL")

    account_username = cmdl_opts.username
    account_password = cmdl_opts.password

    if cmdl_opts.netrc:
        if cmdl_opts.username or cmdl_opts.password:
            cond_print("Ignorning input credentials in favor of .netrc (-n)\n")

        try:
            account_credentials = netrc.netrc().authenticators(HOST)
            if account_credentials is not None:
                account_username = account_credentials[0]
                account_password = account_credentials[2]
            else:
                sys.exit("Error parsing .netrc: No authenticator available for {}".format(HOST))

        except (IOError, netrc.NetrcParseError) as error:
            sys.exit("Error parsing .netrc: {}".format(error))

    if account_username is None:
        account_username = getpass.getpass("Username: ")
    if account_password is None:
        account_password = getpass.getpass("Password: ")

    session = login(account_username, account_password)
    if cmdl_opts.file:
        cond_print("Ignoring argument in favor of file (-f)\n")
        read_file(session, cmdl_opts.file)
    else:
        process_url_mo(session, url_mo)
