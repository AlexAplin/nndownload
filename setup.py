import setuptools

with open("README.md", "r") as fh:
    long_description = fh.read()

setuptools.setup(
    name="nndownload",
    version="0.9",
    author="AlexAplin",
    description="nndownload allows you to download videos from Niconico, formerly known as Nico Nico Douga.",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/AlexAplin/nndownload",
    packages=['nndownload'],
    install_requires=['requests', 'beautifulsoup4'],
    classifiers=[
        "Programming Language :: Python :: 3",
        "Natural Language :: English"
    ]
)
