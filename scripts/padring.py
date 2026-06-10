#!/usr/bin/env python3

# Copyright (c) 2025 Leo Moser <leo.moser@pm.me>
# SPDX-License-Identifier: Apache-2.0

import os
import sys
import yaml
import shutil
import argparse

from typing import List, Type, Tuple

from librelane.common import Path
from librelane.config import Variable
from librelane.state import DesignFormat, State
from librelane.flows.sequential import SequentialFlow
from librelane.steps import (
    KLayout,
    Checker,
    Magic,
    Misc,
    Yosys,
    Verilator,
    OpenROAD,
    Odb,
    Step,
    ViewsUpdate,
    MetricsUpdate,
    StepError,
    StepException,
)
from librelane.steps.klayout import KLayoutStep
from librelane.flows.flow import FlowError


class PadringFlow(SequentialFlow):

    Steps: List[Type[Step]] = [
        Verilator.Lint,
        Checker.LintTimingConstructs,
        Checker.LintErrors,
        Checker.LintWarnings,
        Yosys.JsonHeader,
        Yosys.Synthesis,
        Checker.YosysUnmappedCells,
        Checker.YosysSynthChecks,
        Checker.NetlistAssignStatements,
        OpenROAD.CheckSDCFiles,
        OpenROAD.CheckMacroInstances,
        OpenROAD.STAPrePNR,
        OpenROAD.Floorplan,
        OpenROAD.DumpRCValues,
        Odb.SetPowerConnections,
        OpenROAD.PadRing,
        Odb.CheckMacroAntennaProperties,
        Odb.ManualMacroPlacement,
        KLayout.StreamOut,
        KLayout.SealRing,
    ]


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


def export_pad_group_config(flow_cfg):
    for suffix in PAD_GROUP_CONFIG_KEYS:
        global_key = f"PAD_{suffix}"
        if global_key in flow_cfg:
            os.environ[global_key] = tcl_env_value(flow_cfg.pop(global_key))

        for side in PAD_GROUP_CONFIG_SIDES:
            side_key = f"{side}_{suffix}"
            if side_key in flow_cfg:
                os.environ[side_key] = tcl_env_value(flow_cfg.pop(side_key))


def load_pad_group_config(config_path):
    pad_group_path = os.path.join(os.path.dirname(config_path), "pad_groups.yaml")
    if not os.path.exists(pad_group_path):
        return {}

    with open(pad_group_path) as f:
        return yaml.safe_load(f) or {}


def main(slot_config_path, config_path):

    PDK_ROOT = os.getenv("PDK_ROOT", os.path.expanduser("~/.ciel"))
    PDK = os.getenv("PDK", "gf180mcuD")

    print(f"PDK_ROOT = {PDK_ROOT}")
    print(f"PDK = {PDK}")

    flow_cfg = yaml.safe_load(open(slot_config_path))
    flow_cfg.update(yaml.safe_load(open(config_path)))
    pad_group_cfg = load_pad_group_config(config_path)
    export_pad_group_config(pad_group_cfg)
    export_pad_group_config(flow_cfg)

    # Run flow
    flow = PadringFlow(
        flow_cfg,
        design_dir=os.path.dirname(config_path),
        pdk_root=PDK_ROOT,
        pdk=PDK,
    )

    try:
        # Start the flow
        flow.start()
    except FlowError as e:
        print(f"Error: \n{e}")
        sys.exit(1)

    print(f"Run successfully completed.")


if __name__ == "__main__":

    parser = argparse.ArgumentParser()
    parser.add_argument("slot", default=".", help="path to slot config")
    parser.add_argument("config", default=".", help="path to config")

    args = parser.parse_args()

    main(args.slot, args.config)
