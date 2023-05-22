# Installing pre-release `oascomply`

`oascomply` requires Python 3.8 or later, and has primarily been tested with 3.8.

Currently, `oascomply` must be checked out from GitHub and installed using
the Python dependency management tool `poetry`.  Publication to PyPI
and support for installation with `pip` will be part of Milestone 4.

## Installing Python

`oascomply` requires Python 3.8 or later.  Python.org provides installation
instructions for [Windows](https://docs.python.org/3.11/using/windows.html)
(through either the Python site or the
[Microsoft Store](https://devblogs.microsoft.com/python/python-in-the-windows-10-may-2019-update/))
and [Mac OS](https://docs.python.org/3.11/using/mac.html)
(through the Python site).

If your system has an older version of Python, you can use
[`pyenv`](https://github.com/pyenv/pyenv/blob/master/README.md),
[`pyenv` for Windows](https://github.com/pyenv-win/pyenv-win/blob/master/README.md),
or another similar tool to install an appropriate version.

_Note: At this stage, `oascomply` has only been tested with Python 3.8 on
Mac OS 12.6 on an Apple M1 chip.  Automated testing across Python 3.8-3.12
will be added prior to publication.  No support for earlier Python versions
will be added due to the requirements of various dependencies.  Please
contact the maintainer if you can help with Windows testing._

## Installing `oascomply` from GitHub with `poetry`

`oascomply` is expected to be `pip`-installable by October 2023.
Currently, it must be checked out from GitHub and installed
using [`poetry`](https://python-poetry.org/docs/).

```ShellSession
src % curl -sSL https://install.python-poetry.org | python3 -
src % git clone https://github.com//OAI/oascomply.git
src % cd oascomply
oascomply % poetry install
```

This keeps all of the `oascomply` dependencies in their own environment,
which you can access with
[`poetry shell`](https://python-poetry.org/docs/cli/#shell).  Alternatively,
you can prefix each command that you want to run with
[`poetry run`](https://python-poetry.org/docs/cli/#run), e.g.:

```ShellSession
oascomply % poetry run python oascomply -h
```

Note that all `poetry` commands need to be run from inside
the repository directory, as `poetry` determines what environment
to use by looking in the current directory and its parent
directories for a `pyproject.toml` file.  Otherwise you will
see an error like this:

```ShellSession
src % poetry run python oascomply -h

Poetry could not find a pyproject.toml file in /Users/someone/src or its parents
```

