from argparse import ArgumentParser, Namespace


def get_runtime_args() -> Namespace:
    parser = ArgumentParser()
    parser.add_argument('db_name_like', nargs='+', default=None)
    parser.add_argument('-n', '--dry_run', action='store_true', default=False)
    return parser.parse_args()


if __name__ == '__main__':
    args = get_runtime_args()
    print(args.db_name_like, args.dry_run)
