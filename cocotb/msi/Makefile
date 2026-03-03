SIM                 = icarus
TOPLEVEL_LANG       = verilog
VERILOG_SOURCES     = /workspaces/Open_Memory_Manager/src/msi_protocol/msi.v
TOPLEVEL            = msi_protocol
COCOTB_TEST_MODULES = msi_test

PYTHON_BIN := /home/codespace/.python/current/bin/python3
export PYGPI_PYTHON_BIN := $(PYTHON_BIN)
export VIRTUAL_ENV := /home/codespace/.python/current
export PYTHONHOME :=
export PYTHONPATH := $(shell $(PYTHON_BIN) -c "import site; print(':'.join(site.getsitepackages()+[site.getusersitepackages()]))"):$(CURDIR):$(PYTHONPATH)
include $(shell cocotb-config --makefiles)/Makefile.sim