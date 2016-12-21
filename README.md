# NNDownload
NNDownload allows you to download videos from Niconico, formerly known as Nico Nico Douga. It simulates the HTML5 player by performing a session request to get the HQ source. Filenames are formatted to include the video ID and title. Keep in mind that if your account doesn't have premium, it may download the LQ source during economy mode hours (12 PM - 2 AM JST).

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
- Special IDs are not processed. See [http://dic.nicovideo.jp/a/id](http://dic.nicovideo.jp/a/id) for more.
- Certain videos (e.g. [nm11960162](http://www.nicovideo.jp/watch/nm11960162)) are not compatible with the HTML5 player and thus cannot be downloaded. The download URI can be parsed from the old API (e.g. [http://flapi.nicovideo.jp/api/getflv?v=nm11960162&as3=1](http://flapi.nicovideo.jp/api/getflv?v=nm11960162&as3=1)).

## License
This project is licensed under the MIT License.
