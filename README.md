# NNDownload
NNDownload allows you to download videos from [Niconico](http://nicovideo.jp), formerly known as Nico Nico Douga. It simulates the HTML5 player by performing a session request to get the HQ source. Where not available, it will fallback to the Flash player. Filenames are formatted to include the video ID, title, and optionally the uploader username. Keep in mind that if your account doesn't have premium, it may download the LQ source during economy mode hours (12 PM - 2 AM JST).

## Requirements
### Python version
- Python 3.x

### Dependencies
- beautifulsoup4
- requests

## Usage
```
Usage: nndownload.py [options] video_id

Options:
  --version             show program's version number and exit
  -h, --help            show this help message
  -u USERNAME, --username=USERNAME
                        account username
  -p PASSWORD, --password=PASSWORD
                        account password
  -d, --save-to-user-directory
                        save video to user directory
  -q, --quiet           activate quiet mode
```

## Known Bugs
- NicoMovieMaker videos (nm#) may not be viewable in an external player. Videos with still images (e.g. [nm11960162](http://www.nicovideo.jp/watch/nm11960162)) will play fine with a pass through ffmpeg. Slideshows and GIFs (e.g. [nm2829323](http://www.nicovideo.jp/watch/nm2829323)) may play with improper frame timings or loops. Flash animations (e.g. [nm4809023](http://www.nicovideo.jp/watch/nm4809023)) will likely not play at all and may require other libraries or solutions.

## License
This project is licensed under the MIT License.
