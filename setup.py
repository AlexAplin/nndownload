import setuptools
from distutils.util import convert_path


with open("README.md", "r") as fh:
    long_description = fh.read()

main_ns = {}
ver_path = convert_path("nndownload/nndownload.py")
with open(ver_path) as ver_file:
    exec(ver_file.read(), main_ns)

setuptools.setup(
    name="nndownload",
    version=main_ns["__version__"],
    author="AlexAplin",
    description="nndownload allows you to process videos and other links from Niconico.",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/AlexAplin/nndownload",
    packages=["nndownload"],
    install_requires=["requests", "beautifulsoup4", "websockets"],
    python_requires=">=3.6",
    scripts=["nndownload/nndownload.py"],
    classifiers=[
        "Programming Language :: Python",
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Natural Language :: English"
    ]
)
