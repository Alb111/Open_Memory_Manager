#!/usr/bin/env python3

import argparse
import shlex

from pad_group_config import collect_pad_group_config, load_pad_group_config


def emit_shell_exports(config):
    for key, value in collect_pad_group_config(config).items():
        print(f"export {key}={shlex.quote(value)}")


def main():
    parser = argparse.ArgumentParser(
        description="Emit shell exports for the project's pad_groups.yaml."
    )
    parser.add_argument("config", help="path to the main LibreLane config.yaml")
    args = parser.parse_args()

    emit_shell_exports(load_pad_group_config(args.config))


if __name__ == "__main__":
    main()
