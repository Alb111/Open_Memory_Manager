set omm_repo_dir [file dirname [file dirname [file normalize [info script]]]]
source [file join $omm_repo_dir gf180mcu gf180mcuD libs.tech netgen gf180mcuD_setup.tcl]

# The used pads are functionally distinct and should continue to match by name.
# The remaining bidirectional pads are intentionally unused in the synthesized
# netlist, so their top-level pad wrappers are electrically symmetric.
set omm_unused_bidir_pads {
    5 6 7 8 9
    10 11 12 13 14 15 16 17 18 19
    20 21 22 23 24 25 26 27 28 29
    30 31 32 33 34 35 36 37 38 39
    43 44 45 46 47 48 49 50 51
}

set omm_fnum1 [uplevel 1 {set fnum1}]
set omm_fnum2 [uplevel 1 {set fnum2}]
set omm_cell1 [uplevel 1 {set cell1}]
set omm_cell2 [uplevel 1 {set cell2}]

set omm_prev_pin ""
foreach omm_idx $omm_unused_bidir_pads {
    set omm_pin [format {bidir_PAD[%d]} $omm_idx]
    if {$omm_prev_pin != ""} {
        permute pins "$omm_fnum1 $omm_cell1" $omm_prev_pin $omm_pin
        permute pins "$omm_fnum2 $omm_cell2" $omm_prev_pin $omm_pin
    }
    set omm_prev_pin $omm_pin
}
