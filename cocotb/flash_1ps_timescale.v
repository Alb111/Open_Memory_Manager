// Sets a picosecond time unit for the vendor S25FL128L flash model, which is
// listed immediately after this file in each flash testbench's source list.
//
// The vendor model (src/housekeeping/cypress_model/s25fl128l.v) ships with no
// `timescale of its own, and its internal delays are authored in ps units:
// e.g. tdevice_PU = 300e6 (power-up = 300 us) and CLK_PER < 20000 (20 ns =
// 50 MHz). If it inherits the surrounding 1ns unit instead, power-up becomes
// 300 ms and the flash never drives SO (reads come back Z -> 0). A `timescale
// persists across file boundaries in compilation order until the next one, so
// placing this file right before the model gives it the intended 1ps unit; the
// wrappers that follow reset to 1ns/1ps via their own `timescale.
//
// This lives in-repo (unlike the git-ignored proprietary model) so the fix
// survives re-extracting the vendor package.
`timescale 1ps/1ps
`default_nettype wire
