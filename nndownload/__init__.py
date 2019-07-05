from nndownload import nndownload
from nndownload.nndownload import cmdl_parser


def download(*args):
    args_list = list(args)
    if '-q' not in args_list:
        # Always run nndownload in 'quiet' mode when used as a module
        args_list.append('-q')

    nndownload.cmdl_opts = cmdl_parser.parse_args(args_list)
    nndownload.main()
