# nndownload

[![PyPI](https://img.shields.io/pypi/v/nndownload.svg)](https://pypi.org/project/nndownload/)

<p align='center'>
    <a href='./README.md'>EN</a> | JA | <a href='./README_ZH-CN.md'>中文</a>
</p>

nndownload では、 [Niconico](http://nicovideo.jp)(通称ニコニコ動画)から動画、画像、マンガをダウンロードしたり、その他のリンクを処理したりできます。従来のダウンローダーとは異なり、nndownload では DMC(Dwango Media Cluster)と DMS(Dwango Media Services)サーバーと通信して、高品質の動画へのアクセスを確保します。

## Disclaimers

- [プレミアムアカウント](https://secure.nicovideo.jp/secure/premium_detail/)を持っていない場合、エコノミーモードの時間帯 (通常は日本時間の午後 12 時～午前 2 時) または混雑する時間帯では低品質の動画となります。
- ログインせずに (-g/--no-login を使用して) ダウンロードする場合、一部の動画はダウンロードできないか、低品質でしか利用できない場合があります。
- 同じ接続で複数のダウンロードセッションを実行すると、一時的なブロックやスロットリングが発生する可能性があります。
- 次の機能は現在サポートされていません。
  - ニコ生タイムシフトのダウンロード
  - ニコニコ静画コメントのダウンロード
  - チャンネルやブログ、コメントのダウンロード

## Features

- コメント、サムネイル、メタデータを含む動画のダウンロード
- メタデータを含むニコニコ静画の画像やマンガのダウンロード
- メタデータを含むチャンネル動画やブログのダウンロード
- マイリストのダウンロード
- ユーザの動画、マイリスト、イラスト、マンガのダウンロード
- ニコ生用のストリーム URL の生成
- 複数スレッドによる動画ダウンロードの高速化
- テキストファイルで受け取った URL リストの処理

## Requirements

### Python version

Python >=3.5.3

### Dependencies

`requirements.txt`を参照

# Installation

```bash
pip install nndownload
```

## Usage

### CLI

```
usage: nndownload.py [options] input

positional arguments:
  input                 URL または ファイル

options:
  -h, --help            ヘルプメッセージを表示
  -u EMAIL/TEL, --username EMAIL/TEL
                        アカウントのメールアドレス または 電話番号
  -p PASSWORD, --password PASSWORD
                        アカウントのパスワード
  --session-cookie COOKIE
                        user_session クッキー値 (文字列またはファイルパス)
  -n, --netrc           .netrcを認証に利用
  -q, --quiet           コンソールに出力しない
  -l [PATH], --log [PATH]
                        ファイルにログ出力
  -v, --version         プログラムのバージョン情報を表示

download options:
  -y PROXY, --proxy PROXY
                        HTTP または SOCKS プロキシ
  -o TEMPLATE, --output-path TEMPLATE
                        出力パスを指定 (テンプレートオプションを参照)
  -r N, --threads N     指定したスレッド数で動画をダウンロードする
  -g, --no-login        ログインなしでダウンロードセッションを作成
  -f, --force-high-quality
                        高品質な動画ソースが利用可能な場合のみダウンロードを行う
  -a, --add-metadata    動画ファイルにメタデータを付与 (MP4 のみ)
  -m, --dump-metadata   メタデータをファイルにダンプ
  -t, --download-thumbnail
                        動画のサムネイルをダウンロード
  -c, --download-comments
                        動画のコメントをダウンロード
  --comments-limit N    スレッドごとにダウンロードするコメント数 (デフォルト: 1000)
  --comments-from DATETIME_OR_TIMESTAMP
                        指定された時刻より前に投稿されたコメントのみをダウンロード:
                        - Unix タイムスタンプ (例: 1686787200)
                        - ISO 8601 日付 (例: '2023-06-15' → 23:59:59に設定)
                        - ISO 8601 日時 (例: '2023-06-15T14:30:00' または '2023-06-15 14:30:00')
  --all-comments        すべてのコメントをリクエスト (--comments-limitを無視)
  -e, --english         英語版サイトにリクエストする
  -chinese              中文版サイトにリクエストする
  -aq AUDIO_QUALITY, --audio-quality AUDIO_QUALITY
                        音質を指定
  -vq VIDEO_QUALITY, --video-quality VIDEO_QUALITY
                        画質を指定
  -an, --no-audio       音声をダウンロードしない
  -vn, --no-video       動画をダウンロードしない
  -Q, --list-qualities  リストの画質と音質
  -s, --skip-media      メディアのダウンロードをスキップ
  --break-on-existing   既存のダウンロードが見つかったら抜ける
  --playlist-start N    リストの開始番号を指定 (最小値：0)
  --user-agent USER_AGENT
                    ユーザーエージェントを指定
```

### Module

```python
import nndownload

url = "https://www.nicovideo.jp/watch/sm35249846"
output_path = "/tmp/{id}.{ext}"
nndownload.execute("-g", "-o", output_path, url)
```

### Custom Output Paths

カスタムファイルパスは、標準の Python テンプレート文字列のように構築されます。例：`{uploader} - {title}.{ext}`  
ニコニコ静画の場合、出力パスはチャプターディレクトリのテンプレートにする必要があります。例：`{manga_id}\{id} - {title}`  
利用可能なオプションは以下の通りです。

- comment_count (動画、静画、漫画、記事)
- description (動画、静画、漫画)
- document_url (動画、静画、漫画、記事)
- ext (動画、静画、記事)
- id (動画、静画、漫画、記事)
- published (動画、静画、漫画、記事)
- tags (動画、静画、漫画、記事)
- title (動画、静画、漫画、記事)
- uploader (動画、静画、漫画、記事)
- uploader_id (動画、静画、漫画、記事)
- url (動画、静画)
- view_count (動画、静画、漫画)
- audio_quality (動画)
- video_quality (動画)
- article (記事)
- blog_title (記事)
- clip_count (静画)
- dms_video_uri (動画)
- dms_audio_uri (動画)
- duration (動画)
- manga_id (漫画)
- manga_title (漫画)
- mylist_count (動画)
- page_count (漫画)
- size_high (動画)
- size_low (動画)
- thread_id (動画)
- thread_key (動画)
- thread_params (動画)
- thumbnail_url (動画)

### Using Stream Links

ストリーム URL の生成後は、ストリームをアクティブな状態に保つためにプログラムを実行し続ける必要があります。生成されたストリーム URL を再生するには、[mpv](https://github.com/mpv-player/mpv)と[streamlink](https://github.com/streamlink/streamlink)が最適なオプションです。ただし、アグレッシブな HLS キャッシングとスレッドを使用する他のプログラムも動作する可能性があります。

`mpv https://...`
`streamlink https://... best`

## Known Bugs

- 既知のバグについては「Issues」をご参照ください。

## License

This project is licensed under the MIT License.
