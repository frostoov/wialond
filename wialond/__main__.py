import argparse
from logging.config import dictConfig

import yaml


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', default='wialond.yml')
    args = parser.parse_args()

    with open(args.config) as f:
        config = yaml.load(f.read())
        dictConfig(config.pop('logging'))

    from wialond.wialond import run
    run(**config)
