/* carpatic-clipwatch: waits until the X clipboard (CLIPBOARD selection) gets a new owner or new content, then exits 0.
 * Used by carpatic-clipd for clipboard history. Same idea as the small `clipnotify` tool (public domain, Cyril Hrubis style), written for Carpathian.
 * Build: cc -O2 -o carpatic-clipwatch clipwatch.c -lX11 -lXfixes */
#include <stdio.h>
#include <stdlib.h>
#include <X11/Xlib.h>
#include <X11/extensions/Xfixes.h>

int main(void) {
    Display *d = XOpenDisplay(NULL);
    if (!d) { fprintf(stderr, "carpatic-clipwatch: no display\n"); return 2; }
    int ev, er;
    if (!XFixesQueryExtension(d, &ev, &er)) { fprintf(stderr, "carpatic-clipwatch: XFixes missing\n"); return 3; }
    Atom clip = XInternAtom(d, "CLIPBOARD", False);
    Window w = DefaultRootWindow(d);
    XFixesSelectSelectionInput(d, w, clip, XFixesSetSelectionOwnerNotifyMask);
    XEvent e;
    for (;;) {
        XNextEvent(d, &e);
        if (e.type == ev + XFixesSelectionNotify) { XCloseDisplay(d); return 0; }
    }
}
