current_design $::env(DESIGN_NAME)
set_units -time ns

set clock_port __VIRTUAL_CLK__
set timing_clock_period $::env(CLOCK_PERIOD)

# chip_top_scan.sdc sets this flag before sourcing this file. P&R uses the
# default functional mode; scan timing can be checked separately at its much
# slower shift frequency.
set scan_timing_mode 0
if { [info exists ::SCAN_TIMING_MODE] && $::SCAN_TIMING_MODE } {
    set scan_timing_mode 1
    if { [info exists ::env(SCAN_CLOCK_PERIOD)] } {
        set timing_clock_period $::env(SCAN_CLOCK_PERIOD)
    } else {
        set timing_clock_period 1000
    }
}
if { [info exists ::env(CLOCK_PORT)] } {
    set port_count [llength $::env(CLOCK_PORT)]

    if { $port_count == "0" } {
        puts "\[WARNING] No CLOCK_PORT found. A dummy clock will be used."
    } elseif { $port_count != "1" } {
        puts "\[WARNING] Multi-clock files are not currently supported by the base SDC file. Only the first clock will be constrained."
    }

    if { $port_count > "0" } {
        set ::clock_port [lindex $::env(CLOCK_PORT) 0]
    }
}

if { $::env(CLOCK_PORT) == $::env(CLOCK_NET) } {
    set port_args [get_ports $clock_port]
} else {
    # This should actually use CLOCK_PIN?
    set port_args [get_pins [lindex $::env(CLOCK_NET) 0]]
}

puts "\[INFO] Using clock $clock_port…"
create_clock {*}$port_args -name $clock_port -period $timing_clock_period

# The two top-chip clocks are forwarded versions of clk_PAD, not synchronous
# data outputs. Model each dedicated-buffer and output-pad path as a generated
# clock related to the received primary clock at clk_pad/Y.
set forwarded_clock_ports [get_ports {
    bidir_PAD[29]
    bidir_PAD[63]
}]
if { [llength $forwarded_clock_ports] != 2 } {
    error "Could not uniquely identify both forwarded-clock pads"
}
create_generated_clock -name c0_forwarded_clk \
    -source $port_args -master_clock $clock_port -combinational \
    [get_ports {bidir_PAD[29]}]
create_generated_clock -name c1_forwarded_clk \
    -source $port_args -master_clock $clock_port -combinational \
    [get_ports {bidir_PAD[63]}]

set input_delay_value [expr $timing_clock_period * $::env(IO_DELAY_CONSTRAINT) / 100]
set output_delay_value [expr $timing_clock_period * $::env(IO_DELAY_CONSTRAINT) / 100]
# boot_pass_en is an asynchronous ownership handoff for the off-chip SPI flash,
# not cycle-by-cycle data. Bound its physical pad-to-pad release time separately
# from the clock-relative I/O budget.
set boot_pass_handoff_max_delay 20.0
set boot_pass_sdc_max_delay [expr {
    $boot_pass_handoff_max_delay
    + $output_delay_value
    + $::env(CLOCK_UNCERTAINTY_CONSTRAINT)
}]
puts "\[INFO] Setting output delay to: $output_delay_value"
puts "\[INFO] Setting input delay to: $input_delay_value"
puts "\[INFO] Setting boot-pass handoff max delay to: $boot_pass_handoff_max_delay"

set_max_fanout $::env(MAX_FANOUT_CONSTRAINT) [current_design]
if { [info exists ::env(MAX_TRANSITION_CONSTRAINT)] } {
    set_max_transition $::env(MAX_TRANSITION_CONSTRAINT) [current_design]
}
if { [info exists ::env(MAX_CAPACITANCE_CONSTRAINT)] } {
    set_max_capacitance $::env(MAX_CAPACITANCE_CONSTRAINT) [current_design]
}

set clocks [get_clocks $clock_port]

# Bidirectional pads. Pad 1 is boot_pass_en and therefore does not receive the
# synchronous input delay. Pads 29 and 63 are forwarded clocks.
set clk_core_inout_names {}
set synchronous_inout_input_names {}
for {set i 0} {$i < 66} {incr i} {
    if {$i != 29 && $i != 63} {
        lappend clk_core_inout_names [format {bidir_PAD[%d]} $i]
        if {$i != 1} {
            lappend synchronous_inout_input_names [format {bidir_PAD[%d]} $i]
        }
    }
}
set clk_core_inout_ports [get_ports $clk_core_inout_names]
set synchronous_inout_input_ports [get_ports $synchronous_inout_input_names]
if { [llength $clk_core_inout_ports] != 64 } {
    error "Could not uniquely identify all non-clock bidirectional pads"
}
if { [llength $synchronous_inout_input_ports] != 63 } {
    error "Could not uniquely identify all synchronous bidirectional inputs"
}

set_input_delay -min 0 -clock $clocks $synchronous_inout_input_ports
set_input_delay -max $input_delay_value -clock $clocks $synchronous_inout_input_ports
set_output_delay $output_delay_value -clock $clocks $clk_core_inout_ports

set boot_pass_port [get_ports {bidir_PAD[1]}]
set boot_spi_output_ports [get_ports {
    bidir_PAD[2]
    bidir_PAD[4]
    bidir_PAD[5]
}]
if { [llength $boot_pass_port] != 1 || [llength $boot_spi_output_ports] != 3 } {
    error "Could not uniquely identify the boot-pass SPI handoff ports"
}
# Give the asynchronous input a zero boundary delay so it is not reported as
# missing an input constraint. OpenSTA subtracts the clock uncertainty and the
# outputs' external delay from a port-to-port set_max_delay. Add those values to
# the SDC exception so the resulting internal pad-to-pad requirement is exactly
# boot_pass_handoff_max_delay, independent of the functional clock period.
set_input_delay -min 0 -clock $clocks $boot_pass_port
set_input_delay -max 0 -clock $clocks $boot_pass_port
set_max_delay $boot_pass_sdc_max_delay \
    -from $boot_pass_port -to $boot_spi_output_ports
# The same asynchronous ownership control holds the boot SPI engine and boot
# FSM in reset while the external master owns the flash. It is not sampled as
# functional cycle data, so do not let its paths to sequential state determine
# the functional clock frequency. The explicit pad-output max delay above
# remains active because it has a disjoint endpoint set.
set_false_path -from $boot_pass_port -to [all_registers]

# Input-only pads
set clk_core_input_ports [get_ports { 
    rst_n_PAD
}] 

set_input_delay -min 0 -clock $clocks $clk_core_input_ports
set_input_delay -max $input_delay_value -clock $clocks $clk_core_input_ports

# Output load
set cap_load [expr $::env(OUTPUT_CAP_LOAD) / 1000.0]
puts "\[INFO] Setting load to: $cap_load"
set_load $cap_load [all_outputs]

puts "\[INFO] Setting clock uncertainty to: $::env(CLOCK_UNCERTAINTY_CONSTRAINT)"
set_clock_uncertainty $::env(CLOCK_UNCERTAINTY_CONSTRAINT) $clocks

puts "\[INFO] Setting clock transition to: $::env(CLOCK_TRANSITION_CONSTRAINT)"
set_clock_transition $::env(CLOCK_TRANSITION_CONSTRAINT) $clocks

puts "\[INFO] Setting timing derate to: $::env(TIME_DERATING_CONSTRAINT)%"
set_timing_derate -early [expr 1-[expr $::env(TIME_DERATING_CONSTRAINT) / 100]]
set_timing_derate -late [expr 1+[expr $::env(TIME_DERATING_CONSTRAINT) / 100]]

# bidir[0].pad/Y drives the buffered debug/scan-mode tree. Case analysis
# removes the inactive side of every scan/functional mux from timing analysis
# without false-pathing the pads used for scan data.
set debug_mode_pin [get_pins {bidir[0].pad/Y}]
if { [llength $debug_mode_pin] != 1 } {
    error "Could not uniquely identify debug/scan-mode pin bidir[0].pad/Y"
}
set_case_analysis $scan_timing_mode $debug_mode_pin

if { [info exists ::env(OPENLANE_SDC_IDEAL_CLOCKS)] && $::env(OPENLANE_SDC_IDEAL_CLOCKS) } {
    unset_propagated_clock [all_clocks]
} else {
    set_propagated_clock [all_clocks]
}

# Raw reset asynchronously asserts only the two-flop synchronizer. Paths from
# the synchronizer output remain timed to guarantee same-cycle core release.
set_false_path -from [get_ports {rst_n_PAD}]
