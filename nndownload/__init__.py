"""Module entry for nndownload."""

from . import nndownload


def execute(*args):
    """Pass arguments to be executed by nndownload."""

    args_list = [e.strip() for e in args]
    nndownload._CMDL_OPTS = nndownload.cmdl_parser.parse_args(args_list)
    nndownload.main()
