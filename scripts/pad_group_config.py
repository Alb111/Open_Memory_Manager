import os

import yaml


PAD_GROUP_CONFIG_KEYS = (
    "GROUP_PLACEMENT",
    "GROUP_COUNT",
    "GROUP_SIZES",
    "GROUP_START_UM",
    "GROUP_PAD_GAP_UM",
    "GROUP_GAP_UM",
)
PAD_GROUP_CONFIG_SIDES = ("PAD_SOUTH", "PAD_EAST", "PAD_NORTH", "PAD_WEST")


def tcl_env_value(value):
    if isinstance(value, list):
        return " ".join(str(item) for item in value)
    return str(value)


def collect_pad_group_config(flow_cfg, consume=False):
    env = {}
    if not flow_cfg:
        return env

    for suffix in PAD_GROUP_CONFIG_KEYS:
        global_key = f"PAD_{suffix}"
        if global_key in flow_cfg:
            env[global_key] = tcl_env_value(flow_cfg[global_key])
            if consume:
                flow_cfg.pop(global_key)

        for side in PAD_GROUP_CONFIG_SIDES:
            side_key = f"{side}_{suffix}"
            if side_key in flow_cfg:
                env[side_key] = tcl_env_value(flow_cfg[side_key])
                if consume:
                    flow_cfg.pop(side_key)

    return env


def export_pad_group_config(flow_cfg, consume=False):
    for key, value in collect_pad_group_config(flow_cfg, consume=consume).items():
        os.environ[key] = value


def load_pad_group_config(config_path):
    config_path = os.fspath(config_path)
    pad_group_path = os.path.join(os.path.dirname(config_path), "pad_groups.yaml")
    if not os.path.exists(pad_group_path):
        return {}

    with open(pad_group_path) as f:
        return yaml.safe_load(f) or {}
