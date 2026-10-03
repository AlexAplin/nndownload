# Trimmed from yt_dlp/dependencies/__init__.py and yt_dlp/dependencies/Cryptodome.py
from types import SimpleNamespace

secretstorage = None
try:
    import secretstorage
    _SECRETSTORAGE_UNAVAILABLE_REASON = None
except ImportError:
    _SECRETSTORAGE_UNAVAILABLE_REASON = (
        'as the `secretstorage` module is not installed. '
        'Please install by running `python3 -m pip install secretstorage`')
except Exception as _err:
    _SECRETSTORAGE_UNAVAILABLE_REASON = f'as the `secretstorage` module could not be initialized. {_err}'


try:
    import sqlite3
    # We need to get the underlying `sqlite` version, see https://github.com/yt-dlp/yt-dlp/issues/8152
    sqlite3._yt_dlp__version = sqlite3.sqlite_version
except ImportError:
    # although sqlite3 is part of the standard library, it is possible to compile Python without
    # sqlite support. See: https://github.com/yt-dlp/yt-dlp/issues/544
    sqlite3 = None


# aes.py only needs `Cryptodome.AES` (falsy when no pycryptodome is installed)
try:
    from Cryptodome.Cipher import AES as _AES
except (ImportError, OSError):
    try:
        from Crypto.Cipher import AES as _AES
    except (ImportError, OSError, SyntaxError):
        _AES = None
Cryptodome = SimpleNamespace(AES=_AES)
