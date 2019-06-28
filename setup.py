import setuptools

with open("README.md", "r") as fh:
    long_description = fh.read()

setuptools.setup(
    name="nndownloadmod",
    version="1.0.1",
    description="A modularized version of AlexAplin/nndownload",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/jaeseopark/nndownloadmod",
    packages=setuptools.find_packages(exclude=["tests", "tests.*"]),
    install_requires=['requests', 'beautifulsoup4'],
    classifiers=[
        "Programming Language :: Python :: 3",
        "Natural Language :: English"
    ]
)
