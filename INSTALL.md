# Installing pre-release `oascomply`

`oascomply` requires Python 3.8 or later, and has primarily been tested with 3.8.

Currently, `oascomply` must be checked out from GitHub and installed using
the Python dependency management tool [`poetry`](https://python-poetry.org/docs/).
Publication to PyPI will be part of Milestone 4.

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

## A note on using `pip`

For those of you who prefer `pip` over `poetry`,
While it is possible to install `oascomply` using `pip -e .` from
the checked-out repository directory, `pip` may install slightly
different package versions as it understands the `pyproject.toml`
file, but 
up a b

## Installing `oascomply` from GitHub

`oascomply` is expected to be published to PyPI by October 2023.

Currently, it must be checked out from GitHub and installed
using [`poetry`](https://python-poetry.org/docs/) (preferably)
or alternatively with `pip -e`..

```ShellSession
~/src % git clone https://github.com/OAI/oascomply.git
~/src % cd oascomply
~/src/oascomply %
```

### Installing  with `poetry` (recommended)

Installation instructions for `poetry` can be found in its
[documentation](https://python-poetry.org/docs/#installation),
but the simplest way on Mac OS X, Linux, or Windows (WSL) is:

```ShellSession
~/src/oascomply % curl -sSL https://install.python-poetry.org | python3 -
~/src/oascomply % which poetry
/Users/handrews/.local/bin/poetry
```

Or on Windows PowerShell (replace `py` with `python` if you installed
Python through the Microsoft Store):

```PowerShell
(Invoke-WebRequest -Uri https://install.python-poetry.org -UseBasicParsing).Content | py -
```

```ShellSession
~/src/oascomply % poetry install
```

This keeps all of the `oascomply` dependencies and command line scripts
in their own environment, which you can access with
[`poetry shell`](https://python-poetry.org/docs/cli/#shell) from either
a Posix/Linux/Max OS X shell or from Windows Powershell.  Alternatively,
you can prefix each command that you want to run with
[`poetry run`](https://python-poetry.org/docs/cli/#run), e.g.:

```ShellSession
~/src/oascomply % poetry run python oascomply -h
usage: oascomply [-h] [-f FILE [URI] [TYPE]] [-d DIRECTORY URI_PREFIX]
                 [-D DIRECTORY [URI_PREFIX]] [-x [{auto,true,false}]] [-n]
                 [-e {true,false}] [-i]
                 [-o [nt | ttl | n3 | trig | json-ld | xml | hext | ...]]
                 [-O OUTPUT_FILE] [-t {none}] [-v] [--test-mode]

optional arguments:
  -h, --help            show this help message and exit
...
```

Note that all `poetry` commands need to be run from inside
the repository directory, as `poetry` determines what environment
to use by looking in the current directory and its parent
directories for a `pyproject.toml` file.  Otherwise you will
see an error like this:

```ShellSession
~/src/src % poetry run python oascomply -h

Poetry could not find a pyproject.toml file in /Users/someone/src or its parents
```

However, if you use `poetry shell` you can work from any directory within that shell session:

```ShellSession
~/src/oascomply % poetry shell
Spawning shell within /Users/handrews/Library/Caches/pypoetry/virtualenvs/oascomply-4cBi6hCb-py3.8
(oascomply-py3.8) ~/src/oascomply % emulate bash -c '. /Users/handrews/Library/Caches/pypoetry/virtualenvs/oascomply-4cBi6hCb-py3.8/bin/activate'
(oascomply-py3.8) ~/src/oascomply % cd ..
(oascomply-py3.8) ~/src % which oascomply
/Users/handrews/Library/Caches/pypoetry/virtualenvs/oascomply-4cBi6hCb-py3.8/bin/oascomply
```

You can leave the `poetry` sub-shell with `exit`:

```ShellSession
(oascomply-py3.8) ~/src % exit

Saving session...
...saving history...truncating history files...
...completed.
```
~/src %
```

### Installing with `pip -e .`

It is possible to install `oascomply` in development mode using `pip -e .`,
optionally in a virtual environment that you have set up with `venv` or some
other tool.  Note that since `pip` only understands `pyrproject.toml` and
not `poetry`'s `poetry.lock` file, you may get slightly different versions
of some libraries.

If reporting a bug from a `pip`-intalled set-up, please verify your installed
library versions against `poetry.lock` first.
