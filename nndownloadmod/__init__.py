def download(args: list, progress_callback=None):
    """
    Wraps nndownload as a module. If successfully executed, downloads mp4 to the current directory.
    :param args: arguments as a list of strings (See README.md)
    :param progress_callback: Callback function that gets invoked every time there is progress with the download.
                              The function should accept the following parameters:
                              - (float) percent
                              - (string) speed_str
                              - (string) progress_msg
    :return: None
    """
    import nndownloadmod.nndownload as inner_module

    inner_module.cmdl_opts = inner_module.cmdl_parser.parse_args(args)
    inner_module.progress_callback = progress_callback
    inner_module.main()
