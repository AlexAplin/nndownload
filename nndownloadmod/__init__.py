def download(args: list):
    """
    Wraps nndownload as a module. If successfully executed, downloads mp4 to the current directory.
    :param args: arguments as a list of strings (See README.md)
    :return: None
    """
    import nndownloadmod.nndownload as inner_module

    inner_module.cmdl_opts = inner_module.cmdl_parser.parse_args(args)
    inner_module.main()
