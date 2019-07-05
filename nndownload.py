import sys

from nndownload import nndownload
from nndownload.nndownload import cmdl_parser

if __name__ == "__main__":
    try:
        nndownload.cmdl_opts = cmdl_parser.parse_args()
        nndownload.main()
    except KeyboardInterrupt:
        sys.exit(1)
