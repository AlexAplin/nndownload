# nndownload

![PyPI](https://img.shields.io/pypi/v/nndownload.svg)

nndownload allows you to download videos, images, manga, and process other links from [Niconico](http://nicovideo.jp), formerly known as Nico Nico Douga. Unlike other existing downloaders, this program communicates wth DMC (Dwango Media Cluster) servers to ensure access to high quality videos.

## Disclaimers
- If you do not have a [premium account](https://secure.nicovideo.jp/secure/premium_detail/), you may download low quality videos during economy mode hours (typically 12 PM - 2 AM JST) or during other periods of high traffic.
- When downloading without a login (using -g/--no-login), some videos may not be available for download or may only be available in a lower quality.
- Running multiple download sessions on the same connection may lead to temporary blocks or throttling.
- These functions are not currently supported:
  - Downloading Niconama timeshifts
  - Downloading Seiga thumbnails and comments
  - Downloading channel blog comments

## Features
 - Download videos with comments, thumbnails, and metadata
 - Download Seiga images and manga with metadata
 - Download channel videos or blogs with metadata
 - Download mylists
 - Download a user's videos, mylists, illustrations, or manga
 - Generate stream URLs for Niconama broadcasts
 - Download videos faster using multiple threads
 - Process lists of URLs from text files

## Requirements
### Python version
- Python >=3.5.3

### Dependencies
- aiohttp
- aiohttp-socks
- beautifulsoup4
- requests
- mutagen
- setuptools
- urllib3

# Installation
```bash
pip install nndownload
```

Binaries for Windows are available on the [releases page](https://github.com/AlexAplin/nndownload/releases).

## Usage
### CLI
```
usage: nndownload.py [options] input

positional arguments:
  input                 URLs or files

optional arguments:
  -h, --help            show this help message and exit
  -u EMAIL/TEL, --username EMAIL/TEL
                        account email address or telephone number
  -p PASSWORD, --password PASSWORD
                        account password
  --session-cookie COOKIE
                        session cookie
  -n, --netrc           use .netrc authentication
  -q, --quiet           suppress output to console
  -l, --log             log output to file
  -v, --version         show program's version number and exit

download options:
  -y PROXY, --proxy PROXY
                        http or socks proxy
  -o TEMPLATE, --output-path TEMPLATE
                        custom output path (see template options)
  -r N, --threads N     download videos using a specified number of threads
  -g, --no-login        create a download session without logging in
  -f, --force-high-quality
                        only download if the high quality video source is available
  -a, --add-metadata    add metadata to video file (MP4 only)
  -m, --dump-metadata   dump metadata to file
  -t, --download-thumbnail
                        download video thumbnail
  -c, --download-comments
                        download video comments
  -e, --english         request video on english site
  -aq AUDIO_QUALITY, --audio-quality AUDIO_QUALITY
                        specify audio quality
  -vq VIDEO_QUALITY, --video-quality VIDEO_QUALITY
                        specify video quality
  -s, --skip-media      skip downloading media
  --playlist-start N    specify the index to start a playlist from (begins at 0)
```

### Module
```python
import nndownload

url = "https://www.nicovideo.jp/watch/sm35249846"
output_path = "/tmp/{id}.{ext}"
nndownload.execute("-g", "-o", output_path, url)
```

### Custom Output Paths
Custom filepaths are constructed like standard Python template strings, e.g. `{uploader} - {title}.{ext}`. For Seiga manga, the output path should be the template for a chapter directory, e.g. `{manga_id}\{id} - {title}`. The available options are:

- comment_count (videos, images, manga, articles)
- description (videos, images, manga)
- document_url (videos, images, manga, articles)
- ext (videos, images, articles)
- id (videos, images, manga, articles)
- published (videos, images, manga, articles)
- tags (videos, images, manga, articles)
- title (videos, images, manga, articles)
- uploader (videos, images, manga, articles)
- uploader_id (videos, images, manga, articles)
- url (videos, images)
- view_count (videos, images, manga)
- audio_quality (videos)
- video_quality (videos)
- article (articles)
- blog_title (articles)
- clip_count (images)
- duration (videos)
- manga_id (manga)
- manga_title (manga)
- mylist_count (videos)
- page_count (manga)
- size_high (videos)
- size_low (videos)
- thread_id (videos)
- thumbnail_url (videos)

### Using Stream Links
After generating a stream URL, the program must be kept running to keep the stream active. [mpv](https://github.com/mpv-player/mpv) and [streamlink](https://github.com/streamlink/streamlink) are the best options for playing generated stream URLs. Other programs that use aggressive HLS caching and threading may also work.

`mpv https://...`
`streamlink https://... best`

## Known Bugs
- Check open issues.

## License
This project is licensed under the MIT License.
