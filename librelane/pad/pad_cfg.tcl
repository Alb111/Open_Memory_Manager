# Copyright 2025 LibreLane Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

source $::env(SCRIPTS_DIR)/openroad/common/set_global_connections.tcl
set_global_connections

puts "\[INFO\] Generating padring..."

set ::block [ord::get_db_block]
set block $::block
set ::units [$block getDefUnits]
set units $::units

set ::DIE_HEIGHT [expr {[lindex $::env(DIE_AREA) 3] - [lindex $::env(DIE_AREA) 1]}]
set ::DIE_WIDTH [expr {[lindex $::env(DIE_AREA) 2] - [lindex $::env(DIE_AREA) 0]}]
set DIE_HEIGHT $::DIE_HEIGHT
set DIE_WIDTH $::DIE_WIDTH

# Get pad and corner site
set pad_site [pad::find_site $::env(PAD_SITE_NAME)]
set pad_corner_site [pad::find_site $::env(PAD_CORNER_SITE_NAME)]

if { $pad_site == "NULL" } {
    puts stderr "\[ERROR\] No pad site $::env(PAD_SITE_NAME) found."
    exit 1
}

if { $pad_corner_site == "NULL" } {
    puts stderr "\[ERROR\] No pad corner site $::env(PAD_CORNER_SITE_NAME) found."
    exit 1
}

if { [$pad_site getClass] != "PAD" } {
    puts stderr "\[ERROR\] Wrong class for pad site $::env(PAD_SITE_NAME): [$pad_site getClass] (expected PAD)."
    exit 1
}

if { [$pad_corner_site getClass] != "PAD" } {
    puts stderr "\[ERROR\] Wrong class for pad corner site $::env(PAD_CORNER_SITE_NAME): [$pad_corner_site getClass] (expected PAD)."
    exit 1
}

set ::pad_site_width [expr double([$pad_site getWidth]) / $units]
set ::pad_site_height [expr double([$pad_site getHeight]) / $units]
set pad_site_width $::pad_site_width
set pad_site_height $::pad_site_height

set ::pad_corner_site_width [expr double([$pad_corner_site getWidth]) / $units]
set ::pad_corner_site_height [expr double([$pad_corner_site getHeight]) / $units]
set pad_corner_site_width $::pad_corner_site_width
set pad_corner_site_height $::pad_corner_site_height

puts "\[INFO\] $::env(PAD_SITE_NAME): $pad_site_width um by $pad_site_height um"
puts "\[INFO\] $::env(PAD_CORNER_SITE_NAME): $pad_corner_site_width um by $pad_corner_site_height um"

# Make IO sites
make_io_sites \
    -horizontal_site $::env(PAD_SITE_NAME) \
    -vertical_site $::env(PAD_SITE_NAME) \
    -corner_site $::env(PAD_CORNER_SITE_NAME) \
    -offset $::env(PAD_EDGE_SPACING)

set ::sides {PAD_SOUTH PAD_EAST PAD_NORTH PAD_WEST}
set ::vertical_sides [list PAD_EAST PAD_WEST]
set ::horizontal_sides [list PAD_SOUTH PAD_NORTH]
set ::row_names [dict create PAD_SOUTH IO_SOUTH PAD_EAST IO_EAST PAD_NORTH IO_NORTH PAD_WEST IO_WEST]
set sides $::sides
set vertical_sides $::vertical_sides
set horizontal_sides $::horizontal_sides
set row_names $::row_names

proc env_int_or_default {name default} {
    if {[info exists ::env($name)]} {
        return [expr {int($::env($name))}]
    }

    return $default
}

proc env_float_or_default {name default} {
    if {[info exists ::env($name)]} {
        return [expr {double($::env($name))}]
    }

    return $default
}

proc env_str_or_default {name default} {
    if {[info exists ::env($name)]} {
        return [string tolower $::env($name)]
    }

    return $default
}

proc get_side_group_config {side} {
    set placement [env_str_or_default ${side}_GROUP_PLACEMENT [env_str_or_default PAD_GROUP_PLACEMENT default]]
    set group_count [env_int_or_default ${side}_GROUP_COUNT [env_int_or_default PAD_GROUP_COUNT 1]]
    set pad_gap_um [env_float_or_default ${side}_GROUP_PAD_GAP_UM [env_float_or_default PAD_GROUP_PAD_GAP_UM 44.0]]
    set group_gap_um [env_float_or_default ${side}_GROUP_GAP_UM [env_float_or_default PAD_GROUP_GAP_UM 240.0]]
    set start_um [env_float_or_default ${side}_GROUP_START_UM [env_float_or_default PAD_GROUP_START_UM 0.0]]
    set group_sizes {}

    if {[info exists ::env(${side}_GROUP_SIZES)]} {
        set group_sizes $::env(${side}_GROUP_SIZES)
    } elseif {[info exists ::env(PAD_GROUP_SIZES)]} {
        set group_sizes $::env(PAD_GROUP_SIZES)
    }

    return [list $placement $group_count $pad_gap_um $group_gap_um $start_um $group_sizes]
}

proc get_side_width {side} {
    global DIE_WIDTH DIE_HEIGHT pad_corner_site_width pad_corner_site_height horizontal_sides vertical_sides

    if {[lsearch -exact $horizontal_sides $side] >= 0} {
        return [expr {$DIE_WIDTH - $::env(PAD_EDGE_SPACING) * 2 - $pad_corner_site_width * 2}]
    }

    if {[lsearch -exact $vertical_sides $side] >= 0} {
        return [expr {$DIE_HEIGHT - $::env(PAD_EDGE_SPACING) * 2 - $pad_corner_site_height * 2}]
    }

    puts stderr "\[ERROR\] Unknown side $side."
    exit 1
}

proc get_side_start {side space_side} {
    global pad_corner_site_width pad_corner_site_height horizontal_sides vertical_sides

    if {[lsearch -exact $horizontal_sides $side] >= 0} {
        return [expr {$space_side + $::env(PAD_EDGE_SPACING) + $pad_corner_site_width}]
    }

    if {[lsearch -exact $vertical_sides $side] >= 0} {
        return [expr {$space_side + $::env(PAD_EDGE_SPACING) + $pad_corner_site_height}]
    }

    puts stderr "\[ERROR\] Unknown side $side."
    exit 1
}

proc get_side_cells {side} {
    global block units

    set widths [list]
    set sum_of_cell_widths 0.0

    foreach inst_name $::env($side) {
        if { [set inst [$block findInst $inst_name]] == "NULL" } {
            puts stderr "\[ERROR\] No instance $inst_name found."
            exit 1
        }

        set master_name [[$inst getMaster] getName]
        set width [expr {double([[$inst getMaster] getWidth]) / $units}]
        set height [expr {double([[$inst getMaster] getHeight]) / $units}]

        puts "$master_name: $width $height"
        lappend widths $width
        set sum_of_cell_widths [expr {$sum_of_cell_widths + $width}]
    }

    return [list $sum_of_cell_widths $widths]
}

proc assert_fits_side {side span side_width} {
    if {$span > $side_width} {
        puts stderr "\[ERROR\] Pads for $side require $span um, larger than available side width $side_width um."
        exit 1
    }
}

proc place_side_with_default_spacing {side sum_of_cell_widths side_width} {
    global pad_site_width row_names

    set pad_count [llength $::env($side)]
    set space_for_fill [expr {$side_width - $sum_of_cell_widths}]
    puts "space_for_fill: $space_for_fill"

    set space_between_pads [expr {$space_for_fill / ($pad_count + 1)}]
    puts "space_between_pads: $space_between_pads"

    # Round to minimum site width (min. filler)
    set space_between_pads_min_filler [expr {round(floor($space_between_pads / $pad_site_width) * $pad_site_width * 1000) / 1000}]
    puts "space_between_pads_min_filler: $space_between_pads_min_filler"

    # The spacing for the pads on the side (the remaining space)
    set space_side [expr {round(($space_for_fill - $space_between_pads_min_filler * ($pad_count - 1)) / 2 * 1000) / 1000}]

    if { $space_side != [expr {round(floor($space_side / $pad_site_width) * $pad_site_width * 1000) / 1000}] } {
        puts stderr "\[ERROR\] The remaining area for the pads on the side ($space_side) is not divisible by the minimum site width (minimum filler: $pad_site_width)."
        exit 1
    }

    set cur_pos [get_side_start $side $space_side]

    foreach inst_name $::env($side) {
        global block units

        if { [set inst [$block findInst $inst_name]] == "NULL" } {
            puts stderr "\[ERROR\] No instance $inst_name found."
            exit 1
        }

        set master_name [[$inst getMaster] getName]
        set width [expr {double([[$inst getMaster] getWidth]) / $units}]

        place_pad -row [dict get $row_names $side] -location $cur_pos $inst_name -master $master_name
        set cur_pos [expr {$cur_pos + $space_between_pads_min_filler + $width}]
    }
}

proc get_balanced_group_size {pad_count group_count group_index} {
    set base_group_size [expr {$pad_count / $group_count}]
    set remainder [expr {$pad_count % $group_count}]

    if {$group_index < $remainder} {
        return [expr {$base_group_size + 1}]
    }

    return $base_group_size
}

proc get_group_sizes {side pad_count group_count group_sizes_config} {
    if {[llength $group_sizes_config] == 0} {
        set sizes [list]
        for {set group_index 0} {$group_index < $group_count} {incr group_index} {
            lappend sizes [get_balanced_group_size $pad_count $group_count $group_index]
        }
        return $sizes
    }

    set explicit_group_count [llength $group_sizes_config]
    if {$explicit_group_count != $group_count} {
        puts stderr "\[ERROR\] PAD_GROUP_SIZES has $explicit_group_count entries, but PAD_GROUP_COUNT is $group_count."
        exit 1
    }

    set total 0
    set sizes [list]
    foreach size $group_sizes_config {
        set size [expr {int($size)}]
        if {$size < 1} {
            puts stderr "\[ERROR\] PAD_GROUP_SIZES entries must be positive integers."
            exit 1
        }
        lappend sizes $size
        set total [expr {$total + $size}]
    }

    if {$total != $pad_count} {
        puts stderr "\[ERROR\] PAD_GROUP_SIZES sum to $total, but $side has $pad_count pads."
        exit 1
    }

    return $sizes
}

proc place_side_with_group_spacing {side sum_of_cell_widths widths side_width placement group_count pad_gap_um group_gap_um start_um group_sizes_config} {
    global row_names block units

    set pad_count [llength $::env($side)]

    if {$placement != "start" && $placement != "center"} {
        puts stderr "\[ERROR\] ${side}_GROUP_PLACEMENT must be default, start, or center."
        exit 1
    }

    if {$group_count < 1 || $group_count > $pad_count} {
        puts stderr "\[ERROR\] ${side}_GROUP_COUNT ($group_count) must be between 1 and the pad count for $side ($pad_count)."
        exit 1
    }

    if {$pad_gap_um < 0 || $group_gap_um < 0 || $start_um < 0} {
        puts stderr "\[ERROR\] ${side}_GROUP_PAD_GAP_UM, ${side}_GROUP_GAP_UM, and ${side}_GROUP_START_UM must be non-negative."
        exit 1
    }

    set group_sizes [get_group_sizes $side $pad_count $group_count $group_sizes_config]
    set intra_group_gap $pad_gap_um
    set group_gap $group_gap_um
    set intra_group_gap_count [expr {$pad_count - $group_count}]
    set group_gap_count [expr {$group_count - 1}]
    set gap_span [expr {$intra_group_gap_count * $intra_group_gap + $group_gap_count * $group_gap}]
    set grouped_span [expr {$sum_of_cell_widths + $gap_span}]

    if {$placement == "center"} {
        assert_fits_side $side $grouped_span $side_width
        set space_side [expr {round(($side_width - $grouped_span) / 2 * 1000) / 1000}]
        set total_span $grouped_span
    } else {
        set total_span [expr {$start_um + $grouped_span}]
        assert_fits_side $side $total_span $side_width
        set space_side $start_um
    }

    puts "Using grouped pad spacing for $side: $placement placement, $group_count groups ($group_sizes), $pad_gap_um um inside groups, $group_gap_um um between groups, $space_side um from placement side"
    puts "grouped_pad_span: $grouped_span"
    puts "remaining_fill_span: [expr {$side_width - $total_span}]"

    set cur_pos [get_side_start $side $space_side]
    set group_index 0
    set pad_index_in_group 0
    set group_size [lindex $group_sizes $group_index]
    set pad_index 0

    foreach inst_name $::env($side) width $widths {
        if { [set inst [$block findInst $inst_name]] == "NULL" } {
            puts stderr "\[ERROR\] No instance $inst_name found."
            exit 1
        }

        set master_name [[$inst getMaster] getName]

        place_pad -row [dict get $row_names $side] -location $cur_pos $inst_name -master $master_name

        if {$pad_index == [expr {$pad_count - 1}]} {
            set gap 0
        } elseif {$pad_index_in_group == [expr {$group_size - 1}]} {
            set gap $group_gap
            incr group_index
            set pad_index_in_group 0
            set group_size [lindex $group_sizes $group_index]
        } else {
            set gap $intra_group_gap
            incr pad_index_in_group
        }

        set cur_pos [expr {$cur_pos + $width + $gap}]
        incr pad_index
    }
}

foreach side $sides {
    puts "Placing pads for $side..."
    lassign [get_side_cells $side] sum_of_cell_widths widths
    puts "The sum of cell widths for $side: $sum_of_cell_widths"

    set side_width [get_side_width $side]
    if {[lsearch -exact $horizontal_sides $side] >= 0} {
        puts "horizontal_side_width: $side_width"
    }
    if {[lsearch -exact $vertical_sides $side] >= 0} {
        puts "vertical_side_width: $side_width"
    }

    assert_fits_side $side $sum_of_cell_widths $side_width

    lassign [get_side_group_config $side] group_placement group_count pad_gap_um group_gap_um start_um group_sizes

    if {$group_placement == "default"} {
        place_side_with_default_spacing $side $sum_of_cell_widths $side_width
    } else {
        place_side_with_group_spacing $side $sum_of_cell_widths $widths $side_width $group_placement $group_count $pad_gap_um $group_gap_um $start_um $group_sizes
    }
}

puts "\[INFO\] Placing corner cells..."

# Place corner cells
place_corners $::env(PAD_CORNER)

puts "\[INFO\] Placing filler cells..."

# Place filler cells
place_io_fill -row IO_NORTH {*}$::env(PAD_FILLERS)
place_io_fill -row IO_SOUTH {*}$::env(PAD_FILLERS)
place_io_fill -row IO_WEST {*}$::env(PAD_FILLERS)
place_io_fill -row IO_EAST {*}$::env(PAD_FILLERS)

puts "\[INFO\] Connecting ring signals..."

# Connect the ring signals
connect_by_abutment

# Place bondpads (if needed)
if { [info exists ::env(PAD_BONDPAD_NAME)] } {
    puts "\[INFO\] Placing bondpads..."

    foreach side $sides {
        foreach inst_name $::env($side) {
            if { [set inst [$block findInst $inst_name]] == "NULL" } {
                puts stderr "\[ERROR\] No instance $inst_name found."
                exit 1
            }
            set master_name [[$inst getMaster] getName]

            dict for {master_regex offset} $::env(PAD_BONDPAD_OFFSETS) {
                set offset_x [lindex $offset 0]
                set offset_y [lindex $offset 1]

                if {[regexp $master_regex $master_name match]} {
                    puts "\[INFO\] Placing bondpad $::env(PAD_BONDPAD_NAME) for $inst_name of type $master_name at offset ($offset_x, $offset_y)..."
                    place_bondpad -bond $::env(PAD_BONDPAD_NAME) $inst_name -offset [list $offset_x $offset_y]
                }
            }
        }
    }
}

# Place io terminals (if needed)
if { [info exists ::env(PAD_PLACE_IO_TERMINALS)] } {
    puts "\[INFO\] Placing I/O terminals..."

    foreach side $sides {
        foreach inst_name $::env($side) {
            if { [set inst [$block findInst $inst_name]] == "NULL" } {
                puts stderr "\[ERROR\] No instance $inst_name found."
                exit 1
            }
            set master_name [[$inst getMaster] getName]

            # Try to find the master in PAD_PLACE_IO_TERMINALS
            foreach master_pin $::env(PAD_PLACE_IO_TERMINALS) {

                # Split the master name and the pin name
                set parts [split $master_pin /]
                set check_master_name [lindex $parts 0]
                set pin_name [lindex $parts 1]

                # Found a match, place the terminal
                if {$master_name == $check_master_name} {
                    place_io_terminals $inst_name/$pin_name
                    break
                }
            }
        }
    }
}

# Remove io rows to avoid causing confusion with the other tools
puts "\[INFO\] Removing I/O rows..."
remove_io_rows
