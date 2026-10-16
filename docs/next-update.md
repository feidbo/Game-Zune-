# Next update - the list

Fixes and changes collected for the next batch. Nothing here is built yet;
they all go in together when the list is called done.

## 1. Power button: tap to sleep, hold to power off

- A single tap of the power button puts the device to sleep: the screen
  goes completely off and every button is locked.
- While asleep, the volume buttons still work, and music keeps playing.
- A second tap wakes it. MENU no longer wakes it from this sleep, so a
  press in a pocket can't turn the screen on.
- Holding the power button for 4 seconds powers the device off, as a tap
  does today.
- In a game, a tap pauses the game and sleeps. Waking returns to the same
  spot.

Notes: the launcher already sees the power button go down and come up, so
it can time the hold. Today about 20 screens power off on a tap, and the
in-game watcher (resident.c) stops the game on a tap. All of these move to
the tap/hold rule. The sleep reuses the lock's screen-off, so it depends on
the last update's screen-off working on the device (still to confirm).

## 2. Boot is still slow with a large music library

- With the full library on the card, power-on still sits on the loading
  screen for a long time.
- Wanted: start fast whatever the library size.

Notes: on the desktop, a 19,000-song card boots in about 1.2 s, so the
device is slow somewhere the desktop isn't (SD card speed, exFAT, or the
music daemon). The launcher already writes boot timings to its log.
Windows app -> device -> show device log, after one slow boot, says where
the time goes. Likely direction: keep the library index on the card, show
the menu straight away, and check the card for changes in the background,
rather than reading every folder before the first screen.

## Also to confirm from the last update

- Locking turns the screen fully dark.
- The Zune animation shows from the second boot on.
