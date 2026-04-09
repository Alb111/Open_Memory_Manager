MAKEFILE_DIR := $(shell dirname $(realpath $(firstword $(MAKEFILE_LIST))))

RUN_TAG = $(shell ls librelane/runs/ | tail -n 1)
TOP = chip_top

PDK_ROOT ?= $(MAKEFILE_DIR)/gf180mcu
PDK ?= gf180mcuD
PDK_TAG ?= 1.6.6

AVAILABLE_SLOTS = 1x1 0p5x1 1x0p5 0p5x0p5
DEFAULT_SLOT = 1x1

# Slot can be any of AVAILABLE_SLOTS
SLOT ?= $(DEFAULT_SLOT)

ifeq ($(SLOT),default)        
    SLOT = $(DEFAULT_SLOT)
endif

ifeq ($(filter $(SLOT),$(AVAILABLE_SLOTS)),)
    $(error $(SLOT) does not exist in AVAILABLE_SLOTS: $(AVAILABLE_SLOTS))
endif

.DEFAULT_GOAL := help

help: ## Show this help message
	@echo 'Usage: make [target]'
	@echo ''
	@echo 'Available targets:'
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-20s %s\n", $$1, $$2}'
.PHONY: help

all: librelane ## Build the project (runs LibreLane)
.PHONY: all

clone-pdk: ## Clone the GF180MCU PDK repository
	rm -rf $(MAKEFILE_DIR)/gf180mcu
	git clone https://github.com/wafer-space/gf180mcu.git $(MAKEFILE_DIR)/gf180mcu --depth 1 --branch ${PDK_TAG}
.PHONY: clone-pdk

librelane: ## Run LibreLane flow (synthesis, PnR, verification)
	librelane librelane/slots/slot_${SLOT}.yaml librelane/config.yaml --pdk ${PDK} --pdk-root ${PDK_ROOT} --manual-pdk
.PHONY: librelane

librelane-nodrc: ## Run LibreLane flow without DRC checks
	librelane librelane/slots/slot_${SLOT}.yaml librelane/config.yaml --pdk ${PDK} --pdk-root ${PDK_ROOT} --manual-pdk --skip KLayout.Antenna --skip KLayout.DRC --skip Magic.DRC
.PHONY: librelane-nodrc

librelane-klayoutdrc: ## Run LibreLane flow without magic DRC checks
	librelane librelane/slots/slot_${SLOT}.yaml librelane/config.yaml --pdk ${PDK} --pdk-root ${PDK_ROOT} --manual-pdk --skip Magic.DRC
.PHONY: librelane-klayoutdrc

librelane-magicdrc: ## Run LibreLane flow without KLayout DRC checks
	librelane librelane/slots/slot_${SLOT}.yaml librelane/config.yaml --pdk ${PDK} --pdk-root ${PDK_ROOT} --manual-pdk --skip KLayout.DRC
.PHONY: librelane-magicdrc

librelane-openroad: ## Open the last run in OpenROAD
	librelane librelane/slots/slot_${SLOT}.yaml librelane/config.yaml --pdk ${PDK} --pdk-root ${PDK_ROOT} --manual-pdk --last-run --flow OpenInOpenROAD
.PHONY: librelane-openroad

librelane-klayout: ## Open the last run in KLayout
	librelane librelane/slots/slot_${SLOT}.yaml librelane/config.yaml --pdk ${PDK} --pdk-root ${PDK_ROOT} --manual-pdk --last-run --flow OpenInKLayout
.PHONY: librelane-klayout

librelane-padring: ## Only create the padring
	PDK_ROOT=${PDK_ROOT} PDK=${PDK} python3 scripts/padring.py librelane/slots/slot_${SLOT}.yaml librelane/config.yaml
.PHONY: librelane-padring

sim: ## Run RTL simulation with cocotb
	cd cocotb; PDK_ROOT=${PDK_ROOT} PDK=${PDK} SLOT=${SLOT} python3 chip_top_tb.py
.PHONY: sim

sim-gl: ## Run gate-level simulation with cocotb (after copy-final)
	cd cocotb; GL=1 PDK_ROOT=${PDK_ROOT} PDK=${PDK} SLOT=${SLOT} python3 chip_top_tb.py
.PHONY: sim-gl

sim-view: ## View simulation waveforms in GTKWave
	gtkwave cocotb/sim_build/chip_top.fst
.PHONY: sim-view

copy-final: ## Copy final output files from the last run
	rm -rf final/
	cp -r librelane/runs/${RUN_TAG}/final/ final/
.PHONY: copy-final

render-image: ## Render an image from the final layout (after copy-final)
	mkdir -p img/
	PDK_ROOT=${PDK_ROOT} PDK=${PDK} python3 scripts/lay2img.py final/gds/${TOP}.gds img/${TOP}.png --width 2048 --oversampling 4
.PHONY: copy-final

# Our Commands
test-mem: ## Run all cocotb on mem
	cd cocotb; PDK_ROOT=${PDK_ROOT} PDK=${PDK} SLOT=${SLOT} python3 mem_test.py
.PHONY: test-mem

mem-wave: ## View simulation waveforms for mem
	gtkwave cocotb/sim_build/mem_ctrl_2048x32.fst
.PHONY: mem-wave

test-msi: ## Run all cocotb tests on msi
	cd cocotb; PDK_ROOT=${PDK_ROOT} PDK=${PDK} SLOT=${SLOT} python3 msi_test.py
.PHONY: test-msi

test-arb: ## Run all cocotb tests on msi
	cd cocotb; PDK_ROOT=${PDK_ROOT} PDK=${PDK} SLOT=${SLOT} python3 wrr_arbiter_test.py
.PHONY: test-arb

test-tserializer: ## Run all cocotb tests on tserializer
	cd cocotb; PDK_ROOT=${PDK_ROOT} PDK=${PDK} SLOT=${SLOT} python3 test_tserializer.py
.PHONY: test-tserializer

test-rserializer: ## Run all cocotb tests on rserializer
	cd cocotb; PDK_ROOT=${PDK_ROOT} PDK=${PDK} SLOT=${SLOT} python3 test_rserializer.py
.PHONY: test-rserializer
	
arb-wave: ## View simulation waveforms for mem
	gtkwave cocotb/sim_build/wrr_arbiter.fst
.PHONY: arb-wave

test-boot: ## Run all cocotb tests on boot contlr
	cd cocotb; PDK_ROOT=${PDK_ROOT} PDK=${PDK} SLOT=${SLOT} python3 housekeeping_tb.py
.PHONY: test-boot

boot-wave: ## View simulation waveforms for boot contlr
	gtkwave cocotb/sim_build/housekeeping_top.fst
.PHONY: boot-wave

test-all: ## Run all cocotb testbenches via pytest
	cd cocotb; PDK_ROOT=${PDK_ROOT} PDK=${PDK} SLOT=${SLOT} pytest test_all_cocotb.py -v
.PHONY: test-all

clean-sim: ## Remove all sim-build dirs in cocotb
	cd cocotb; rm -r sim_build*
.PHONY: clean-sim