# nndownload
nndownload allows you to download videos from [Niconico](http://nicovideo.jp), formerly known as Nico Nico Douga. It simulates the HTML5 player by performing a session request to get the HQ source. Where not available, it will fallback to the Flash player. Keep in mind that if your account doesn't have premium, it may download the LQ source during economy mode hours (12 PM - 2 AM JST). When not providing a login, some Flash videos will not be available for download or will only be available in a lower quality.

## Features
 - Download videos with comments, thumbnails, and metadata
 - Download mylists
 - Build RTMP stream URLs for official Niconama broadcasts
 - Process text files with URLs

## Requirements
### Python version
- Python 3.x

### Dependencies
- beautifulsoup4
- requests

## Usage
```
usage: nndownload.py [options] input

positional arguments:
  input                 URL or file

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
  -o OUTPUT_PATH, --output-path OUTPUT_PATH
                        custom output path (see template options)
  -g, --no-login        create a download session without logging in
  -f, --force-high-quality
                        only download if the high quality source is available
  -m, --dump-metadata   dump video metadata to file
  -t, --download-thumbnail
                        download video thumbnail
  -c, --download-comments
                        download video comments
  -e, --english         download english comments
```

Custom filepaths are constructed like standard Python template strings, e.g. `{uploader} - {title}.{ext}`. The available options are:

- comment_count
- description
- duration
- ext
- id
- mylist_count
- published
- size_high
- size_low
- thread_id
- thumbnail_url
- title
- uploader
- uploader_id
- url
- view_count

## Known Bugs
- Check open issues.

## License
This project is licensed under the MIT License.
