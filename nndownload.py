#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Download videos from Niconico (nicovideo.jp), formerly known as Nico Nico Douga."""

from bs4 import BeautifulSoup
import requests

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

__author__ = "Alex Aplin"
__copyright__ = "Copyright 2016 Alex Aplin"

__license__ = "MIT"
__version__ = "0.9"

HOST = "nicovideo.jp"
LOGIN_URL = "https://account.nicovideo.jp/api/v1/login?site=niconico"
VIDEO_URL = "http://nicovideo.jp/watch/{0}"
THUMB_INFO_API = "http://ext.nicovideo.jp/api/getthumbinfo/{0}"
MYLIST_API = "http://flapi.nicovideo.jp/api/getplaylist/mylist/{0}"
COMMENTS_API = "http://nmsg.nicovideo.jp/api"
COMMENTS_POST = "<packet><thread thread=\"{0}\" version=\"20061206\" res_from=\"-1000\" scores=\"1\"/></packet>"
VIDEO_URL_RE = re.compile(r"(^|(http:\/\/)?(www.)?)(nicovideo.jp\/(watch|mylist)\/|nico.ms\/)?((sm|nm)*[\d]+)")
DMC_HEARTBEAT_INTERVAL_S = 15
KILOBYTE = 1024
BLOCK_SIZE = 10 * KILOBYTE
EPSILON = 0.0001

FINISHED_DOWNLOADING = False

HTML5_COOKIE = {
    "watch_html5": "1"
    }

cmdl_usage = "%prog [options] url_id"
cmdl_version = __version__
cmdl_parser = optparse.OptionParser(usage=cmdl_usage, version=cmdl_version, conflict_handler="resolve")
cmdl_parser.add_option("-u", "--username", dest="username", metavar="USERNAME", help="account username")
cmdl_parser.add_option("-p", "--password", dest="password", metavar="PASSWORD", help="account password")
cmdl_parser.add_option("-d", "--save-to-user-directory", action="store_true", dest="use_user_directory", help="save video to user directory")
cmdl_parser.add_option("-t", "--download-thumbnail", action="store_true", dest="download_thumbnail", help="download video thumbnail")
cmdl_parser.add_option("-c", "--download-comments", action="store_true", dest="download_comments", help="download video comments")
cmdl_parser.add_option("-m", "--mylist", action="store_true", dest="mylist", help="indicate that id is a mylist")
cmdl_parser.add_option("-n", "--netrc", action="store_true", dest="netrc", help="use .netrc authentication")
cmdl_parser.add_option("-v", "--verbose", action="store_true", dest="verbose", help="print status to console")
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


def request_video(session, video_id):
    """Request the video page and initiate download of the video URI."""

    response = session.get(VIDEO_URL.format(video_id), cookies=HTML5_COOKIE)
    response.raise_for_status()
    document = BeautifulSoup(response.text, "html.parser")
    result = perform_api_request(session, document)
    download_video(session, result)
    if cmdl_opts.download_thumbnail:
        download_thumbnail(session, result)
    if cmdl_opts.download_comments:
        download_comments(session, result)

def perform_heartbeat(response, session, heartbeat_url):
    """Perform a response heartbeat to keep the download connection alive."""

    try:
        response = session.post(heartbeat_url, data=response.toxml())
        response.raise_for_status()
        response = xml.dom.minidom.parseString(response.text).getElementsByTagName("session")[0]
        if not FINISHED_DOWNLOADING:
            heartbeat_timer = threading.Timer(DMC_HEARTBEAT_INTERVAL_S, perform_heartbeat, (response, session, heartbeat_url))
            heartbeat_timer.daemon = True
            heartbeat_timer.start()
            time.sleep(1)

    except (KeyboardInterrupt, SystemExit):
        sys.exit("Caught interrupt request")


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


def download_video(session, result):
    """Download video from response URI and display progress."""

    if cmdl_opts.use_user_directory:
        try:
            if not os.path.exists("{0}".format(result["user"])):
                cond_print("Making directory for {0}...".format(result["user"]))
                os.makedirs("{0}".format(result["user"]))
                cond_print(" done\n")

            filename = "{0}\{1} - {2}.{3}".format(result["user"], result["video"], result["title"], result["extension"])

        except (IOError, OSError):
            sys.exit("Error downloading video: Unable to open {0} for writing".format(filename))

    else:
        filename = "{0} - {1}.{2}".format(result["video"], result["title"], result["extension"])

    try:
        dl_stream = session.head(result["uri"])
        dl_stream.raise_for_status()
        video_len = int(dl_stream.headers["content-length"])

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

        dl_stream = session.get(result["uri"], headers=resume_header, stream=True)
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


def download_thumbnail(session, result):
    """Download the video thumbnail."""

    cond_print("Downloading thumbnail...")

    filename = ""
    if cmdl_opts.use_user_directory:
        filename += "{0}\\".format(result["user"])
    filename += "{0} - {1}.jpg".format(result["video"], result["title"])

    get_thumb = session.get(result["thumb"])
    with open(filename, "wb") as file:
        for block in get_thumb.iter_content(BLOCK_SIZE):
            file.write(block)

    cond_print(" done\n")


def download_comments(session, result):
    """Download the video comments."""

    cond_print("Downloading comments...")

    filename = ""
    if cmdl_opts.use_user_directory:
        filename += "{0}\\".format(result["user"])
    filename += "{0} - {1}.xml".format(result["video"], result["title"])

    get_comments = session.post(COMMENTS_API, COMMENTS_POST.format(result["thread_id"]))
    with open(filename, "wb") as file:
        file.write(get_comments.content)

    cond_print(" done\n")


def download_mylist(session, mylist_id):
    mylist = session.get(MYLIST_API.format(mylist_id))
    mylist_json = json.loads(mylist.text)
    for index, item in enumerate(mylist_json["items"]):
        cond_print("{0}/{1}\n".format(index, len(mylist_json["items"])))
        request_video(session, item["video_id"])


def perform_api_request(session, document):
    """Collect parameters from video document and build API request"""

    result = {}

    # SMILEVIDEO movies
    if document.find(id="js-initial-watch-data"):
        params = json.loads(document.find(id="js-initial-watch-data")["data-api-data"])

        result["video"] = params["video"]["id"]
        result["title"] = params["video"]["title"]
        result["extension"] = params["video"]["movieType"]
        result["user"] = params["owner"]["nickname"].strip(" さん")
        result["thumb"] = params["video"]["thumbnailURL"]
        result["thread_id"] = params["thread"]["ids"]["default"]

        # Economy mode (low quality)
        if not params["video"]["dmcInfo"] and "low" in params["video"]["smileInfo"]["url"]:
            cond_print("Currently in economy mode. Using low quality source\n")
            result["uri"] = params["video"]["smileInfo"]["url"]

        # HTML5 request
        elif params["video"]["dmcInfo"]:
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

            # Build request
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
            result["uri"] = response.getElementsByTagName("content_uri")[0].firstChild.nodeValue
            cond_print(" done\n")

            # Collect response for heartbeat
            session_id = response.getElementsByTagName("id")[0].firstChild.nodeValue
            response = response.getElementsByTagName("session")[0]
            heartbeat_url = params["video"]["dmcInfo"]["session_api"]["urls"][0]["url"] + "/" + session_id + "?_format=xml&_method=PUT"
            perform_heartbeat(response, session, heartbeat_url)

        # Legacy for pre-HTML5 videos
        elif params["video"]["smileInfo"]:
            cond_print("Using legacy URI\n")
            result["uri"] = params["video"]["smileInfo"]["url"]

        else:
            sys.exit("Error collecting parameters: Failed to find video URI. Nico may have updated their player")

    # NicoMovieMaker movies (SWF)
    # May need conversion to play properly in an external player
    elif document.find(id="watchAPIDataContainer"):
        params = json.loads(document.find(id="watchAPIDataContainer").text)

        result["video"] = params["videoDetail"]["id"]
        result["title"] = params["videoDetail"]["title"]
        result["user"] = params["uploaderInfo"]["nickname"].strip(" さん")
        result["extension"] = params["flashvars"]["movie_type"]
        result["thumb"] = params["videoDetail"]["thumbnail"]
        result["thread_id"] = params["videoDetail"]["thread_id"]

        video_url_param = urllib.parse.parse_qs(urllib.parse.unquote(urllib.parse.unquote(params["flashvars"]["flvInfo"])))
        if ("url" in video_url_param):
            result["uri"] = video_url_param["url"][0]

        else:
            sys.exit("Error collecting parameters: Failed to find video URI. Nico may have updated their player")

    else:
        sys.exit("Error collecting parameters: Failed to collect video paramters")

    return result


if __name__ == '__main__':
    if len(cmdl_args) == 0:
        sys.exit("Error parsing arguments: You must provide a video or mylist ID")

    url_id_mo = VIDEO_URL_RE.match(cmdl_args[0])
    if url_id_mo is None:
        sys.exit("Error parsing arguments: Not a valid video or mylist ID")
    url_id = url_id_mo.group(6)

    account_username = cmdl_opts.username
    account_password = cmdl_opts.password

    if cmdl_opts.netrc:
        if cmdl_opts.username or cmdl_opts.password:
            cond_print("Ignorning input credentials in favor of .netrc (-n)")

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
    if cmdl_opts.mylist or url_id_mo.group(5) == "mylist":
        download_mylist(session, url_id)
    else:
        request_video(session, url_id)
