# Next update - the list

Fixes and changes collected for the next batch. Nothing here is built yet;
they all go in together when the list is called done.

(Empty - the last batch shipped. See below.)

## Shipped 2026-10-31

1. **Power button: tap to sleep, hold 4 s to power off.** A tap turns the
   screen fully off, drops the CPU to its slowest, and ignores every button
   but the volume; music keeps playing; another tap wakes. In a game a tap
   pauses the game for the sleep and the wake carries on from the same frame.
   The pocket lock and the settings menu's Screen Off are the same sleep now.
2. **Slow boot with a big music library.** The library is kept in
   `.userdata/pixel2/muse-index.bin` and loaded in one read at boot; the
   folders are read again in the background a few seconds after the menu is
   up, and a changed card updates the music menus and the index.
3. **Battery draining while off.** Power-off has a backstop that cuts the
   power 30 s later if anything on the way down stalls (the screen is dark by
   then, so a stall looked off). Every step of the way out is in the log.

### To confirm on the device

- A tap of power turns the screen fully dark; the volume buttons still work
  while asleep; a tap wakes; a 4-second hold turns it off.
- After a few days off, the battery holds. If not, after the next power-on,
  Windows app -> device -> show device log: look for `power: off`, `exit:
  done`, and whether `power: still on 30 s after power-off` appears.
- Boot time with the full library (the log's `muse: library from the index
  in N ms` and `boot: first frame`).
