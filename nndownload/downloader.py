import re
from concurrent.futures import ThreadPoolExecutor

from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad
from tqdm.rich import tqdm

M3U8_KEY_RE = re.compile(r"((?:#EXT-X-KEY)(?:.*),?URI=\")(?P<url>.*)\",IV=0x(?P<iv>.*)")
M3U8_MAP_RE = re.compile(r"((?:#EXT-X-MAP)(?:.*),?URI=\")(?P<url>.*)\"(.*)")
M3U8_SEGMENT_RE = re.compile(r"(?:#EXTINF):.*\n(.*)")

def download_hls(m3u8_url, filename, session, threads=5):
    from .nndownload import FormatNotAvailableException

    m3u8 = session.get(m3u8_url).text
    key_match = M3U8_KEY_RE.search(m3u8)
    init_match = M3U8_MAP_RE.search(m3u8)
    segments = M3U8_SEGMENT_RE.findall(m3u8)
    if not key_match:
        raise FormatNotAvailableException("Could not retrieve key file from manifest")
    if not init_match:
        raise FormatNotAvailableException("Could not retrieve init file from manifest")
    if not segments:
        raise FormatNotAvailableException("Could not retrieve segments from manifest")

    m3u8_type = 'video' if '/video/' in m3u8 else 'audio'
    key_url = key_match['url']
    key = session.get(key_url).content
    iv = key_match['iv']
    iv = bytes.fromhex(iv)
    init_url = init_match['url']
    with open(filename, "wb") as f:
        f.write(session.get(init_url).content)

    def download_segment(segment):
        r = session.get(segment)
        r.raise_for_status()
        cipher = AES.new(key, AES.MODE_CBC, iv=iv)
        return unpad(cipher.decrypt(r.content), AES.block_size)

    progress = tqdm(total=len(segments), colour="green", unit="seg", desc=f"Downloading {m3u8_type}")
    with ThreadPoolExecutor(max_workers=threads) as executor:
        results = executor.map(download_segment, segments)
        for decrypted in results:
            with open(filename, "ab") as f:
                f.write(decrypted)
            progress.update()
    progress.close()
