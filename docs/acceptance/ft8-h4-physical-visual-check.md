# H4 visual acceptance — physical controls, no RF

The operator must be parked. This test **requires a reviewed deployment of the new
UI revision** before running; it does not work on production commit 3232ded.

With FT8 reception enabled and FT8 transmit disabled, navigate to the FT8 page
using the existing physical controls. From an SSH terminal, create the trigger:

    touch /home/geoff/rolling-thunder-h4-visual-test.trigger

The live UI consumes the marker and displays the actual yellow alarm overlay,
but uses a separate in-memory FT8PttAlarm test object, never the live alarm or
radio. The operator presses the physical mapped discard/voice-cancel control to
acknowledge. The green 26-point bold white 1-3-1 panel then appears. Press the
real short Command 1, Command 3, Command 1 buttons in that order to clear it.
Test expires in 90 seconds, restoring the normal screen without affecting CAT,
PTT, transmit authorization, or ongoing production alarm state. A real active
safety alarm takes precedence over the test; this procedure cannot override it.
If no screen change occurs, confirm the FT8 screen is selected and that the new
UI version is installed. Record clipping/readability and physical button response.
This is only a UI/physical-button check; it does not validate RF feedback.
