#!/usr/bin/env python

import os
import pydoc

"""
Generate the code documentation, using pydoc.
"""

for dirname in ['pasd', 'sid', 'simulate']:
    pydoc.writedocs(dirname, pkgpath='%s.' % dirname)
    pydoc.writedoc(dirname)
os.system('mv *.html docs')
