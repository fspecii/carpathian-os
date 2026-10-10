/* carpatic-supertap COMMAND... : run COMMAND when the Super key is tapped (pressed and released with no other key/button in between).
 * Uses XInput2 raw events, so it does not grab the keyboard and does not interfere with dwm's Super+key bindings. */
#include <X11/Xlib.h>
#include <X11/XKBlib.h>
#include <X11/extensions/XInput2.h>
#include <X11/keysym.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
int main(int argc, char **argv) {
	if (argc < 2) { fprintf(stderr, "usage: carpatic-supertap command [args]\n"); return 2; }
	signal(SIGCHLD, SIG_IGN);
	Display *d = XOpenDisplay(NULL);
	if (!d) return 1;
	int xi, ev, er;
	if (!XQueryExtension(d, "XInputExtension", &xi, &ev, &er)) return 1;
	unsigned char mask[XIMaskLen(XI_LASTEVENT)] = {0};
	XISetMask(mask, XI_RawKeyPress); XISetMask(mask, XI_RawKeyRelease); XISetMask(mask, XI_RawButtonPress);
	XIEventMask em = { XIAllMasterDevices, sizeof mask, mask };
	XISelectEvents(d, DefaultRootWindow(d), &em, 1);
	XFlush(d);
	KeyCode l = XKeysymToKeycode(d, XK_Super_L), r = XKeysymToKeycode(d, XK_Super_R);
	int tap = 0;
	for (;;) {
		XEvent e; XNextEvent(d, &e);
		if (e.xcookie.type != GenericEvent || e.xcookie.extension != xi || !XGetEventData(d, &e.xcookie)) continue;
		XIRawEvent *re = e.xcookie.data;
		int t = e.xcookie.evtype;
		if (t == XI_RawButtonPress) tap = 0;
		else if (t == XI_RawKeyPress) tap = (re->detail == l || re->detail == r) ? 1 : 0;
		else if (t == XI_RawKeyRelease && (re->detail == l || re->detail == r) && tap) {
			tap = 0;
			if (fork() == 0) { execvp(argv[1], argv + 1); _exit(1); }
		}
		XFreeEventData(d, &e.xcookie);
	}
}
