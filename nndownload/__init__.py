from nndownload import nndownload


def execute(*args):
    args_list = [e.strip() for e in args]
    nndownload.cmdl_opts = nndownload.cmdl_parser.parse_args(args_list)
    nndownload.main()
