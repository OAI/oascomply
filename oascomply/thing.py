import argparse

class N2(argparse.Namespace):
    def __init__(self, **kwargs):
        self._arglist = []
        super().__init__(**kwargs)

    def __setattr__(self, name, value):
        if hasattr(self, '_arglist') and value is not None:
            self._arglist.append((name, value))
        return super().__setattr__(name, value)

    def __iter__(self):
        return iter(self._arglist)


class OrderedNamespace(argparse.Namespace):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.arglist = []

class OrderedAppend(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        items = getattr(namespace, self.dest, None)
        namespace.append((option_string, self.dest, values))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument(
        '-f', 
        '--file',
        action='append',
        dest='apidesc',
        help="An API description file as a local file path, which will"
             "appear in output as the corresponding 'file:' URL",
    )
    parser.add_argument(
        '-i', 
        '--identified-file',
        nargs=2,
        action='append',
        dest='apidesc',
        help="An API description file path followed by the URI used "
             "to identify it in references and output.",
    )

    args = parser.parse_args()# namespace=N2())
    # for a in args:
    #     print(repr(a))
    print(repr(args.apidesc))
