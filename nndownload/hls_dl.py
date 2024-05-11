"""Native HLS downloader for DMS streams."""

import re
from concurrent.futures import ThreadPoolExecutor

from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad

M3U8_KEY_RE = re.compile(r"((?:#EXT-X-KEY)(?:.*),?URI=\")(?P<url>.*)\",IV=0x(?P<iv>.*)")
M3U8_MAP_RE = re.compile(r"((?:#EXT-X-MAP)(?:.*),?URI=\")(?P<url>.*)\"(.*)")
M3U8_SEGMENT_RE = re.compile(r"(?:#EXTINF):.*\n(.*)")


def download_hls(m3u8_url, filename, name, session, progress, threads):
    """Perform a native HLS download of a provided M3U8 manifest."""

    from .nndownload import FormatNotAvailableException

    with session.get(m3u8_url) as m3u8_request:
        m3u8_request.raise_for_status()
        m3u8 = m3u8_request.text
    key_match = M3U8_KEY_RE.search(m3u8)
    init_match = M3U8_MAP_RE.search(m3u8)
    segments = M3U8_SEGMENT_RE.findall(m3u8)
    if not key_match:
        raise FormatNotAvailableException("Could not retrieve key file from manifest")
    if not init_match:
        raise FormatNotAvailableException("Could not retrieve init file from manifest")
    if not segments:
        raise FormatNotAvailableException("Could not retrieve segments from manifest")

    key_url = key_match["url"]
    with session.get(key_url) as key_request:
        key_request.raise_for_status()
        key = key_request.content
    iv = key_match["iv"]
    iv = bytes.fromhex(iv)
    init_url = init_match["url"]
    with open(filename, "wb") as f:
        f.write(session.get(init_url).content)

    def download_segment(segment):
        with session.get(segment) as r:
            r.raise_for_status()
            cipher = AES.new(key, AES.MODE_CBC, iv=iv)
            return unpad(cipher.decrypt(r.content), AES.block_size)

    task_id = progress.add_task(name, total=len(segments))
    with ThreadPoolExecutor(max_workers=threads) as executor:
        results = executor.map(download_segment, segments)
        for decrypted in results:
            with open(filename, "ab") as f:
                f.write(decrypted)
            progress.advance(task_id)
