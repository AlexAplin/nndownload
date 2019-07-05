from nndownload import nndownload
from nndownload.nndownload import cmdl_parser


def download(args: list):
    args_copy = args.copy()
    if '-q' not in args_copy:
        # Always run nndownload in 'quiet' mode when used as a module
        args_copy.append('-q')

    nndownload.cmdl_opts = cmdl_parser.parse_args(args_copy)
    nndownload.main()
