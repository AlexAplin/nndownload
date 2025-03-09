# nndownload

[![PyPI](https://img.shields.io/pypi/v/nndownload.svg)](https://pypi.org/project/nndownload/)

<p align='center'>
    <a href='./README.md'>EN</a> | <a href='./README_JA.md'>JA</a> | 中文
</p>

nndownload 允许您下载来自 [Niconico](http://nicovideo.jp)（前身为 Nico Nico Douga）的视频、图像、漫画以及处理其他链接。与其他现有下载器不同，该程序与 DMC（Dwango Media Cluster）和 Dwango Media Services（DMS）服务器进行通信，以确保访问高质量的视频。

## 免责声明

- 如果您没有 [高级账户](https://secure.nicovideo.jp/secure/premium_detail/)，则可能只能在经济模式时间段（通常为日本时间中午 12 点到凌晨 2 点）或其他高流量期间下载低质量视频。
- 在未登录的情况下下载（使用-g/--no-login），某些视频可能无法下载，或只能以低质量下载。
- 在同一连接上运行多个下载会话可能会导致暂时封锁或速度限制。
- 目前不支持以下功能：
  - 下载 Niconama 时间转换
  - 下载 Seiga 评论
  - 下载频道博客评论

## 特性

- 下载带评论、缩略图和元数据的视频
- 下载带元数据的 Seiga 图像和漫画
- 下载带元数据的频道视频或博客
- 下载我的列表
- 下载用户的视频、我的列表、插图或漫画
- 为 Niconama 直播生成流媒体 URL
- 使用多个线程更快地下载视频
- 从文本文件处理 URL 列表

## 要求

### Python 版本

Python >=3.5.3

### 依赖

请参阅 `requirements.txt`。在请求视频时，`ffmpeg`也必须在您的 PATH 中可用。

# 安装

```bash
pip install nndownload
```

## 使用

### 命令行接口（CLI）

```
用法: nndownload.py [选项] 输入

位置参数:
  输入                 URLs 或文件

选项:
  -h, --help            显示此帮助信息并退出
  -u EMAIL/TEL, --username EMAIL/TEL
                        账户电子邮件地址或电话号码
  -p PASSWORD, --password PASSWORD
                        账户密码
  --session-cookie COOKIE
                        用户会话 cookie 值（字符串或文件路径）
  -n, --netrc           使用.netrc 身份验证
  -q, --quiet           抑制控制台输出
  -l [PATH], --log [PATH]
                        将输出日志记录到文件
  -v, --version         显示程序的版本号并退出

下载选项:
  -y PROXY, --proxy PROXY
                        http 或 socks 代理
  -o TEMPLATE, --output-path TEMPLATE
                        自定义输出路径（请参见模板选项）
  -r N, --threads N     使用指定数量的线程下载视频
  -g, --no-login        创建不登录的下载会话
  -f, --force-high-quality
                        仅在高质量视频源可用时下载
  -a, --add-metadata    向视频文件添加元数据（仅限 MP4）
  -m, --dump-metadata   将元数据输出到文件
  -t, --download-thumbnail
                        下载视频缩略图
  -c, --download-comments
                        下载视频评论
  -e, --english         请求英语网站上的视频
  --chinese             请求繁体中文（台湾）网站上的视频
  -aq AUDIO_QUALITY, --audio-quality AUDIO_QUALITY
                        指定音频质量
  -vq VIDEO_QUALITY, --video-quality VIDEO_QUALITY
                        指定视频质量
  -an, --no-audio       不下载音频
  -vn, --no-video       不下载视频
  -Q, --list-qualities  列出视频和音频质量及可用状态
  -s, --skip-media      跳过下载媒体
  --break-on-existing   在遇到已存在下载后停止
  --playlist-start N    指定从列表中开始的项的索引（从 0 开始）
  --user-agent USER_AGENT
                      为下载会话指定自定义用户代理
```

### 模块

```python
import nndownload

url = "https://www.nicovideo.jp/watch/sm35249846"
output_path = "/tmp/{id}.{ext}"
nndownload.execute("-g", "-o", output_path, url)
```

### 自定义输出路径

自定义文件路径由标准 Python 模板字符串构建，例如 `{uploader} - {title}.{ext}`。对于 Seiga 漫画，输出路径应为章节目录的模板，例如 `{manga_id}\{id} - {title}`。可用的选项包括：

- comment_count（视频、图像、漫画、文章）
- description（视频、图像、漫画）
- document_url（视频、图像、漫画、文章）
- ext（视频、图像、文章）
- id（视频、图像、漫画、文章）
- published（视频、图像、漫画、文章）
- tags（视频、图像、漫画、文章）
- title（视频、图像、漫画、文章）
- uploader（视频、图像、漫画、文章）
- uploader_id（视频、图像、漫画、文章）
- url（视频、图像）
- view_count（视频、图像、漫画）
- audio_quality（视频）
- video_quality（视频）
- article（文章）
- blog_title（文章）
- clip_count（图像）
- dms_video_uri（视频）
- dms_audio_uri（视频）
- duration（视频）
- manga_id（漫画）
- manga_title（漫画）
- mylist_count（视频）
- page_count（漫画）
- size_high（视频）
- size_low（视频）
- thread_id（视频）
- thread_key（视频）
- thread_params（视频）
- thumbnail_url（视频）

### 使用流链接

生成流 URL 后，程序必须保持运行以保持流的活跃状态。[mpv](https://github.com/mpv-player/mpv)和[streamlink](https://github.com/streamlink/streamlink)是播放生成的流 URL 的最佳选择。其他使用激进 HLS 缓存和线程的程序也可能可行。

`mpv https://...`
`streamlink https://... best`

## 已知问题

- 请查看开放问题。

## 许可

该项目依据 MIT 许可证进行许可。
