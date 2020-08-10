# nndownload

![PyPI](https://img.shields.io/pypi/v/nndownload.svg)

nndownload allows you to download videos, images, manga, and process other links from [Niconico](http://nicovideo.jp), formerly known as Nico Nico Douga. Unlike other existing downloaders, this program communicates wth DMC (Dwango Media Cluster) servers to ensure access to high quality videos.

## Disclaimers
- If you do not have a [premium account](https://secure.nicovideo.jp/secure/premium_detail/), you may download low quality videos during economy mode hours (typically 12 PM - 2 AM JST) or during other periods of high traffic.
- When downloading without a login (using -g/--no-login), Flash videos (some video IDs starting with "nm") may not be available for download or will only be available in a lower quality.
- Running multiple download sessions on the same connection may lead to temporary blocks or throttling.
- These functions are not currently supported:
  - Downloading Niconama timeshifts
  - Downloading a user's manga
  - Downloading Seiga thumbnails and comments
  - Dwnloading channel blog comments

## Features
 - Download videos with comments, thumbnails, and metadata
 - Download Seiga images and manga with metadata
 - Download channel blog articles
 - Download mylists
 - Download a user's videos, mylists, or illustrations
 - Download a channel's videos or blog
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
  -u USERNAME, --username USERNAME
                        account username
  -p PASSWORD, --password PASSWORD
                        account password
  -n, --netrc           use .netrc authentication
  -q, --quiet           suppress output to console
  -l, --log             log output to file
  -v, --version         show program's version number and exit

download options:
  -y PROXY, --proxy PROXY
                        http or socks proxy
  -o TEMPLATE, --output-path TEMPLATE
                        custom output path (see template options)
  -r N, --threads N     download using a specified number of threads
  -g, --no-login        create a download session without logging in
  -f, --force-high-quality
                        only download if the high quality source is available
  -m, --dump-metadata   dump video metadata to file
  -t, --download-thumbnail
                        download video thumbnail
  -c, --download-comments
                        download video comments
  -e, --english         request video on english site
  -aq AUDIO_QUALITY, --audio-quality AUDIO_QUALITY
                        specify audio quality (DMC videos only)
  -vq VIDEO_QUALITY, --video-quality VIDEO_QUALITY
                        specify video quality (DMC videos only)
  -s, --skip-media      skip downloading media
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

- comment_count
- description
- duration
- ext
- id
- mylist_count
- published
- quality
- size_high
- size_low
- thread_id
- thumbnail_url
- title
- uploader
- uploader_id
- url
- view_count
- audio_quality (DMC)
- video_quality (DMC)
- manga_id (manga)
- manga_title (manga)
- page_count (manga)
- clip_count (images)
- blog_title (articles)
- tags (videos, images, articles)

### Using Stream Links
After generating a stream URL, the program must be kept running to keep the stream active. [mpv](https://github.com/mpv-player/mpv) and [streamlink](https://github.com/streamlink/streamlink) are the best options for playing generated stream URLs. Other programs that use aggressive HLS caching and threading may also work.

`mpv https://...`
`streamlink https://... best`

## Known Bugs
- Check open issues.

## License
This project is licensed under the MIT License.
