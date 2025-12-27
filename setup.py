#!/usr/bin/env python
"""The setup script."""

from setuptools import setup

with open("README.md", "r") as f:
    readme = f.read()

setup(
    name="aiotractive",
    version="0.7.0",
    author="Gleb Sinyavskiy",
    author_email="zhulik.gleb@gmail.com",
    description="Asynchronous Python client for the Tractive REST API",
    long_description=readme,
    long_description_content_type="text/markdown",
    url="https://github.com/zhulik/aiotractive",
    license="The MIT License",
    install_requires=["aiohttp>=3.8.1", "yarl>=1.7.2"],
    packages=["aiotractive"],
    package_dir={"aiotractive": "aiotractive"},
    include_package_data=True,
    zip_safe=True,
    keywords="tractive,rest,api,aio,async,await",
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "Natural Language :: English",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
    ],
)
