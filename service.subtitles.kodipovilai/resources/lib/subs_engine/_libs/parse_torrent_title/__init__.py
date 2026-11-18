#!/usr/bin/env python

# (POV IL: upstream looked the module up with pkgutil.find_loader -- for Python 2's faster 'regex' -- and
# Python 3.14 removed that function: the whole subtitle engine failed at this import there. The add-on runs
# on Python 3 only, where the lookup always ended with the standard 're'. parse.py and post.py take it
# from here: "from . import re".)
import re

from .parse import PTN

__author__ = "Giorgio Momigliano"
__email__ = "gmomigliano@protonmail.com"
__version__ = "2.8.1"
__license__ = "MIT"


def parse(name, standardise=True, coherent_types=False):
    return PTN().parse(name, standardise, coherent_types)
