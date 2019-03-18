#!/usr/bin/env python

from setuptools import setup, find_packages
import json

# read the contents of your README file
from os import path
this_directory = path.abspath(path.dirname(__file__))
with open(path.join(this_directory, 'README.md')) as f:
    long_description = f.read()

if __name__ == '__main__':
    # Provide static information in setup.json
    # such that it can be discovered automatically
    with open('setup.json', 'r') as info:
        kwargs = json.load(info)
    # add long_description from readme.md:
    kwargs["long_description"] = long_description 
    # finihed reading everything in
    setup(
        packages=find_packages(),
        **kwargs
    )
