/* Passive scanout telemetry for an explicitly owned Alpine Xorg VM.
 * PresentCompleteNotify records the server's presentation timestamp/MSC.
 * No compositor patch, busy polling, window mapping or synthetic vblank.
 */
#define _POSIX_C_SOURCE 200809L
#include <X11/Xlib.h>
#include <X11/extensions/Xcomposite.h>
#include <X11/extensions/Xpresent.h>
#include <inttypes.h>
#include <poll.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

static uint64_t now_us(void) {
    struct timespec now;
    clock_gettime(CLOCK_MONOTONIC, &now);
    return (uint64_t)now.tv_sec * 1000000 + (uint64_t)now.tv_nsec / 1000;
}

int main(int argc, char **argv) {
    const char *marked = getenv("CARPATIC_VM_TEST"), *display = getenv("DISPLAY");
    if (!marked || strcmp(marked, "1") || !display || strcmp(display, ":0") ||
        getenv("WAYLAND_DISPLAY") || access("/etc/alpine-release", F_OK)) {
        fputs("Use only an explicitly marked isolated Alpine Xorg :0 VM\n", stderr);
        return 2;
    }
    char *end = NULL;
    long seconds = argc == 2 ? strtol(argv[1], &end, 10) : 20;
    if (argc > 2 || seconds < 1 || seconds > 300 || (argc == 2 && (!end || *end))) {
        fputs("Usage: presentation-probe [seconds:1..300]\n", stderr);
        return 2;
    }
    Display *d = XOpenDisplay(NULL);
    if (!d) return 2;
    int opcode, event_base, error_base, major, minor;
    if (!XPresentQueryExtension(d, &opcode, &event_base, &error_base) ||
        !XPresentQueryVersion(d, &major, &minor) ||
        !XCompositeQueryExtension(d, &event_base, &error_base) ||
        XGetSelectionOwner(d, XInternAtom(d, "_NET_WM_CM_S0", False)) == None) {
        fputs("A running compositor and Present/Composite extensions are required\n", stderr);
        XCloseDisplay(d);
        return 2;
    }
    Window root = DefaultRootWindow(d);
    Window overlay = XCompositeGetOverlayWindow(d, root);
    XID subscription = XPresentSelectInput(d, overlay, PresentCompleteNotifyMask);
    XSync(d, False);
    uint64_t deadline = now_us() + (uint64_t)seconds * 1000000;
    unsigned frames = 0;
    printf("{\"environment\":true,\"overlay\":%lu,\"start_us\":%" PRIu64 "}\n", overlay, now_us());
    fflush(stdout);
    while (now_us() < deadline) {
        while (XPending(d)) {
            XEvent e;
            XNextEvent(d, &e);
            if (getenv("CARPATIC_PRESENT_DEBUG"))
                fprintf(stderr, "event type=%d extension=%d evtype=%d expected=%d\n", e.type, e.xcookie.extension, e.xcookie.evtype, opcode);
            if (e.type != GenericEvent || e.xcookie.extension != opcode ||
                e.xcookie.evtype != PresentCompleteNotify || !XGetEventData(d, &e.xcookie)) continue;
            XPresentCompleteNotifyEvent *complete = e.xcookie.data;
            if (getenv("CARPATIC_PRESENT_DEBUG"))
                fprintf(stderr, "complete kind=%u mode=%u ust=%" PRIu64 " msc=%" PRIu64 "\n", complete->kind, complete->mode, complete->ust, complete->msc);
            if (complete->kind == PresentCompleteKindPixmap && complete->ust != 0) {
                printf("{\"present\":true,\"ust_us\":%" PRIu64 ",\"msc\":%" PRIu64
                       ",\"mode\":%u,\"received_us\":%" PRIu64 "}\n",
                       complete->ust, complete->msc, complete->mode, now_us());
                fflush(stdout);
                frames++;
            }
            XFreeEventData(d, &e.xcookie);
        }
        struct pollfd fd = {.fd = ConnectionNumber(d), .events = POLLIN};
        poll(&fd, 1, 50);
    }
    XPresentFreeInput(d, overlay, subscription);
    XCompositeReleaseOverlayWindow(d, root);
    XCloseDisplay(d);
    printf("{\"summary\":true,\"presented_frames\":%u}\n", frames);
    if (frames < 2) {
        fputs("Insufficient Present samples; do not infer FPS from this run\n", stderr);
        return 1;
    }
    return 0;
}
