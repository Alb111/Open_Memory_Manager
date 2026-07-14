set sram_macros_NS [list \
    i_chip_core.i_main_memory.memblock0.sram0 \
    i_chip_core.i_main_memory.memblock0.sram1 \
    i_chip_core.i_main_memory.memblock0.sram2 \
    i_chip_core.i_main_memory.memblock0.sram3 \
    i_chip_core.i_main_memory.memblock1.sram0 \
    i_chip_core.i_main_memory.memblock1.sram1 \
    i_chip_core.i_main_memory.memblock1.sram2 \
    i_chip_core.i_main_memory.memblock1.sram3 \
    i_chip_core.i_main_memory.memblock2.sram0 \
    i_chip_core.i_main_memory.memblock2.sram1 \
    i_chip_core.i_main_memory.memblock2.sram2 \
    i_chip_core.i_main_memory.memblock2.sram3 \
    i_chip_core.i_main_memory.memblock3.sram0 \
    i_chip_core.i_main_memory.memblock3.sram1 \
    i_chip_core.i_main_memory.memblock3.sram2 \
    i_chip_core.i_main_memory.memblock3.sram3 \
    i_chip_core.i_dir_metadata.plane0 \
    i_chip_core.i_dir_metadata.plane1 \
    i_chip_core.i_dir_metadata.plane2 \
]

# SRAM macros. All configured SRAM instances are north-oriented.
define_pdn_grid \
    -macro \
    -instances $sram_macros_NS \
    -name sram_macros_NS \
    -starts_with POWER \
    -halo "$::env(PDN_HORIZONTAL_HALO) $::env(PDN_VERTICAL_HALO)"

add_pdn_connect \
    -grid sram_macros_NS \
    -layers "$::env(PDN_VERTICAL_LAYER) $::env(PDN_HORIZONTAL_LAYER)"

add_pdn_connect \
    -grid sram_macros_NS \
    -layers "$::env(PDN_VERTICAL_LAYER) Metal3"

# Add stripes on W/E edges of SRAM.
add_pdn_stripe \
    -grid sram_macros_NS \
    -layer Metal4 \
    -width 2.36 \
    -offset 1.18 \
    -spacing 0.28 \
    -pitch 426.86 \
    -starts_with GROUND \
    -number_of_straps 2

# Since the above stripes block the top level PDN at Metal4, add some more
# stripes to improve the PDN's integrity and ensure better macro connections.
add_pdn_stripe \
    -grid sram_macros_NS \
    -layer Metal4 \
    -width 4.00 \
    -offset 65.93 \
    -spacing 0.28 \
    -pitch 50 \
    -starts_with GROUND \
    -number_of_straps 9