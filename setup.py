import setuptools

with open("README.md", "r") as fh:
    long_description = fh.read()

setuptools.setup(
    name="nndownload",
    version="0.9",
    author="AlexAplin",
    description="nndownload allows you to process videos and other links from Niconico.",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/AlexAplin/nndownload",
    packages=["nndownload"],
    install_requires=["requests", "beautifulsoup4"],
    classifiers=[
        "Programming Language :: Python",
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Natural Language :: English"
    ]
)
