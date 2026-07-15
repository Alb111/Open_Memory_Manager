# 3.3V SRAM macros (gf180mcu_ocd_ip_sram 1024x8, 301.30 x 515.81).
# All 35 macros (8 memblocks x 4 lanes + 3 metadata planes) are placed N or FS.
# FS is a vertical flip only, so the W/E power-ring rails these Metal4 straps
# connect to keep their X positions -> one grid covers both orientations.
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
    i_chip_core.i_main_memory.memblock4.sram0 \
    i_chip_core.i_main_memory.memblock4.sram1 \
    i_chip_core.i_main_memory.memblock4.sram2 \
    i_chip_core.i_main_memory.memblock4.sram3 \
    i_chip_core.i_main_memory.memblock5.sram0 \
    i_chip_core.i_main_memory.memblock5.sram1 \
    i_chip_core.i_main_memory.memblock5.sram2 \
    i_chip_core.i_main_memory.memblock5.sram3 \
    i_chip_core.i_main_memory.memblock6.sram0 \
    i_chip_core.i_main_memory.memblock6.sram1 \
    i_chip_core.i_main_memory.memblock6.sram2 \
    i_chip_core.i_main_memory.memblock6.sram3 \
    i_chip_core.i_main_memory.memblock7.sram0 \
    i_chip_core.i_main_memory.memblock7.sram1 \
    i_chip_core.i_main_memory.memblock7.sram2 \
    i_chip_core.i_main_memory.memblock7.sram3 \
    i_chip_core.i_dir_metadata.plane0 \
    i_chip_core.i_dir_metadata.plane1 \
    i_chip_core.i_dir_metadata.plane2 \
]

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

# Stripes on the W/E edges of each 301.30um-wide SRAM (one near each edge).
add_pdn_stripe \
    -grid sram_macros_NS \
    -layer Metal4 \
    -width 1.36 \
    -offset 0.68 \
    -spacing 0.28 \
    -pitch 298.30 \
    -starts_with GROUND \
    -number_of_straps 2

# The edge stripes block the top-level PDN at Metal4, so add fill stripes across
# the width to keep PDN integrity and give the macro a solid connection.
add_pdn_stripe \
    -grid sram_macros_NS \
    -layer Metal4 \
    -width 4.00 \
    -offset 25.65 \
    -spacing 0.28 \
    -pitch 50 \
    -starts_with GROUND \
    -number_of_straps 6
