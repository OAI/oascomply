"""Root oascomply package

Ths package initializes libraries such as ``jschon`` that are always
or almost always used, and may be first accessed from any of several
code paths.  Wherever possible, library initialization should be
placed near the library's first use.
"""

import jschon

__all__ = ['schema_catalog']

schema_catalog = jschon.create_catalog('2020-12')
"""The default shared ``jschon`` schema loader and cache"""
