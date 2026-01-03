"""The setup script."""

from pathlib import Path

from setuptools import setup

with Path("README.md").open() as f:
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
    install_requires=["aiohttp>=3.13.0", "yarl>=1.21.0"],
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
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Programming Language :: Python :: 3.13",
        "Programming Language :: Python :: 3.14",
    ],
    python_requires=">=3.9",
)
