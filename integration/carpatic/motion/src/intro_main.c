/* carpatic-intro-play: native login animation. Starts in a few milliseconds, draws into an override-redirect fullscreen window (no focus taken,
 * no grabs: keys and clicks are polled), opens an iris onto the live desktop at the end.
 *   carpatic-intro-play [--force-play] [--windowed WxH] [--ready-file F]       play (normally started by `carpatic-intro auto`)
 *   carpatic-intro-play --dump DIR [--size WxH] [--fps N]                       write PPM frames, no display needed
 *   carpatic-intro-play --selftest                                              incremental drawing == full drawing for every frame
 * Colours: the active theme (settings.conf THEME/ACCENT, theme colors.toml accent + orange). Log: $STATE/intro.log.json; slow screens: $STATE/intro.slow */
#define _POSIX_C_SOURCE 200809L
#include "intro_scene.h"
#include <errno.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>
#include <sys/stat.h>
#ifdef HAVE_X11
#include <X11/Xlib.h>
#include <X11/Xatom.h>
#include <X11/Xutil.h>
#include <X11/extensions/shape.h>
#include <X11/extensions/XShm.h>
#include <sys/ipc.h>
#include <sys/shm.h>
#endif

#define UNUSED __attribute__((unused))
static UNUSED double now(void) { struct timespec ts; clock_gettime(CLOCK_MONOTONIC, &ts); return ts.tv_sec + ts.tv_nsec / 1e9; }
static UNUSED double uptime(void) { FILE *f = fopen("/proc/uptime", "r"); double u = 0; if (f) { if (fscanf(f, "%lf", &u) != 1) u = 0; fclose(f); } return u; }
static const char *envs(const char *k, const char *d) { const char *v = getenv(k); return v && *v ? v : d; }

static UNUSED int cmp_d(const void *a, const void *b) { double x = *(const double *)a, y = *(const double *)b; return x < y ? -1 : x > y; }

/* ---- settings and theme colours ---- */
static char cfgdir[512], statedir[512];
static int setting(const char *key, char *out, size_t n) {
    char path[600], line[512]; snprintf(path, sizeof path, "%s/settings.conf", cfgdir);
    FILE *f = fopen(path, "r"); if (!f) return 0;
    size_t kl = strlen(key); int found = 0;
    while (fgets(line, sizeof line, f)) if (!strncmp(line, key, kl) && line[kl] == '=' && line[kl + 1] == '"') {
        char *e = strrchr(line, '"'); if (e && e > line + kl + 1) { *e = 0; snprintf(out, n, "%s", line + kl + 2); found = 1; }
    }
    fclose(f); return found;
}
static uint32_t parse_hex(const char *s, uint32_t d) { if (*s == '#') { s++; } if (strlen(s) < 6) return d; char b[7]; memcpy(b, s, 6); b[6] = 0; char *e; unsigned long v = strtoul(b, &e, 16); return *e ? d : (uint32_t)v; }
static int toml_color(const char *file, const char *key, uint32_t *out) {
    FILE *f = fopen(file, "r"); if (!f) return 0; char line[256]; size_t kl = strlen(key); int ok = 0;
    while (fgets(line, sizeof line, f)) {
        if (strncmp(line, key, kl)) continue; char *p = line + kl; while (*p == ' ') p++; if (*p != '=') continue;
        char *q = strchr(p, '#'); if (q) { *out = parse_hex(q, *out); ok = 1; break; }
    }
    fclose(f); return ok;
}
static void theme_colors(uint32_t *accent, uint32_t *ember) {
    char theme[128] = "carpatic", acc[32] = "", path[700], exe[512] = "", share[512];
    setting("THEME", theme, sizeof theme); setting("ACCENT", acc, sizeof acc);
    ssize_t n = readlink("/proc/self/exe", exe, sizeof exe - 1); if (n > 0) exe[n] = 0;
    char *sl = strrchr(exe, '/'); if (sl) *sl = 0;
    snprintf(share, sizeof share, "%s", envs("CARPATIC_SHARE", "/usr/local/share/carpatic/configurator"));
    const char *dirs[4]; char d1[600], d2[600], d3[700];
    snprintf(d1, sizeof d1, "%s/themes/%s", cfgdir, theme); snprintf(d2, sizeof d2, "%s/themes/%s", share, theme); snprintf(d3, sizeof d3, "%s/../../configurator/themes/%s", exe, theme);
    dirs[0] = envs("CARPATIC_THEME_DIR", ""); dirs[1] = d1; dirs[2] = d2; dirs[3] = d3;
    for (int i = 0; i < 4; i++) {
        if (!*dirs[i]) continue; snprintf(path, sizeof path, "%s/colors.toml", dirs[i]);
        if (access(path, R_OK)) continue;
        toml_color(path, "accent", accent); toml_color(path, "orange", ember); break;
    }
    if (acc[0]) *accent = parse_hex(acc, *accent);
}

static UNUSED void log_json(const char *tag, int W, int H, int frames, double mean, double p95, double mx, int late_frames, double seconds, double cpu, double reveal, double u0, double u1, int skipped_key, const char *note) {
    char path[700]; snprintf(path, sizeof path, "%s/intro.log.json", statedir); mkdir(statedir, 0755);
    FILE *f = fopen(path, "w"); if (!f) return;
    fprintf(f, "{\"player\": \"%s\", \"size\": \"%dx%d\", \"frames\": %d, \"mean_ms\": %.1f, \"p95_ms\": %.1f, \"max_ms\": %.1f, \"frames_over_25ms\": %d, \"seconds\": %.2f, \"cpu_seconds\": %.3f, \"reveal_start\": %.2f, \"uptime_start\": %.2f, \"uptime_end\": %.2f, \"skipped_by_key\": %s, \"note\": \"%s\"}\n",
            tag, W, H, frames, mean, p95, mx, late_frames, seconds, cpu, reveal, u0, u1, skipped_key ? "true" : "false", note);
    fclose(f);
}

/* ---- headless: dump and selftest ---- */
static void write_ppm(const char *path, const uint32_t *px, int W, int H) {
    FILE *f = fopen(path, "wb"); if (!f) return; fprintf(f, "P6\n%d %d\n255\n", W, H);
    for (int i = 0; i < W * H; i++) { unsigned char c[3] = {px[i] >> 16, px[i] >> 8, px[i]}; fwrite(c, 1, 3, f); }
    fclose(f);
}
static uint32_t standin(int x, int y, int W, int H) {   /* a stand-in desktop for the tests: a soft gradient and a bar */
    if (y < 24) return x < 70 ? 0x5cc8a8 : 0x0b0e13;
    int g = 60 + (x * 90 / W) + (y * 50 / H); return (uint32_t)(g << 16 | (g + 18) << 8 | (g + 30));
}
static void render_full_frame(const Scene *s, double t, double reveal, uint32_t *buf, uint32_t *cover) {
    int W = s->W, H = s->H; scene_render(s, t, cover, W, (Rect){0, 0, W, H});
    double r = scene_iris(s, t, reveal);
    for (int y = 0; y < H; y++) for (int x = 0; x < W; x++) {
        double dx = x + 0.5 - s->sunx, dy = y + 0.5 - s->suny;
        buf[(size_t)y * W + x] = (r > 0 && dx * dx + dy * dy < r * r) ? standin(x, y, W, H) : cover[(size_t)y * W + x];
    }
}
static int cmd_dump(const char *dir, int W, int H, double fps, uint32_t accent, uint32_t ember) {
    Scene s; if (scene_init(&s, W, H, accent, ember, 0x0b0e13)) return 1;
    mkdir(dir, 0755); uint32_t *buf = malloc((size_t)W * H * 4), *cover = malloc((size_t)W * H * 4); int n = (int)((REVEAL_MIN + REVEAL_DUR) * fps) + 2;
    for (int i = 0; i < n; i++) { char p[800]; render_full_frame(&s, i / fps, REVEAL_MIN, buf, cover); snprintf(p, sizeof p, "%s/%04d.ppm", dir, i); write_ppm(p, buf, W, H); }
    printf("%d frames in %s\n", n, dir); return 0;
}
static int cmd_selftest(uint32_t accent, uint32_t ember) {
    int W = 640, H = 400; Scene s; if (scene_init(&s, W, H, accent, ember, 0x0b0e13)) return 1;
    uint32_t *inc = calloc((size_t)W * H, 4), *full = calloc((size_t)W * H, 4); double prev = -1; long bad = 0, drawn = 0, total = 0;
    for (int i = 0; i <= 150; i++) {
        double t = i / 60.0; Rect r; total += (long)W * H;
        if (scene_damage(&s, prev, t, &r)) { scene_render(&s, t, inc, W, r); drawn += (long)r.w * r.h; }
        scene_render(&s, t, full, W, (Rect){0, 0, W, H});
        for (long k = 0; k < (long)W * H; k++) if (inc[k] != full[k]) bad++;
        prev = t;
    }
    printf("selftest: %ld wrong pixels, %d%% of the pixels redrawn\n", bad, (int)(100 * drawn / total)); return bad != 0;
}

#ifdef HAVE_X11
static int cmd_play(int force_play, const char *windowed, const char *ready_file) {
    double t_proc = now(); double u0 = uptime(); clock_t c0 = clock();
    Display *dpy = XOpenDisplay(NULL); if (!dpy) { log_json("x11", 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, u0, u0, 0, "no display"); return 0; }
    int scr = DefaultScreen(dpy), W = DisplayWidth(dpy, scr), H = DisplayHeight(dpy, scr);
    if (windowed) sscanf(windowed, "%dx%d", &W, &H);
    uint32_t accent = 0x5cc8a8, ember = 0xf2a65a; theme_colors(&accent, &ember);
    XSetWindowAttributes at; at.override_redirect = windowed ? False : True; at.background_pixel = 0x0b0e13; at.event_mask = ExposureMask;
    Window win = XCreateWindow(dpy, RootWindow(dpy, scr), 0, 0, W, H, 0, CopyFromParent, InputOutput, CopyFromParent, CWOverrideRedirect | CWBackPixel | CWEventMask, &at);
    XStoreName(dpy, win, "Carpathian intro");
    XShapeSelectInput(dpy, win, 0);
    XMapRaised(dpy, win); XSync(dpy, False);          /* the server paints the background colour at once: the first frame is the colour the screen already has */
    if (ready_file) { FILE *f = fopen(ready_file, "w"); if (f) fclose(f); }
    double t_ready = now();
    Scene s; if (scene_init(&s, W, H, accent, ember, 0x0b0e13)) { XDestroyWindow(dpy, win); XCloseDisplay(dpy); return 0; }
    GC gc = XCreateGC(dpy, win, 0, NULL); Visual *vis = DefaultVisual(dpy, scr); int depth = DefaultDepth(dpy, scr);
    XImage *img = NULL; XShmSegmentInfo shm; int use_shm = 0; uint32_t *px = NULL;
    if (depth >= 24 && XShmQueryExtension(dpy)) {
        img = XShmCreateImage(dpy, vis, depth, ZPixmap, NULL, &shm, W, H);
        if (img && img->bits_per_pixel == 32) {
            shm.shmid = shmget(IPC_PRIVATE, (size_t)img->bytes_per_line * H, IPC_CREAT | 0600);
            if (shm.shmid >= 0) { shm.shmaddr = img->data = shmat(shm.shmid, NULL, 0); shm.readOnly = False;
                if (shm.shmaddr != (void *)-1 && XShmAttach(dpy, &shm)) { use_shm = 1; XSync(dpy, False); shmctl(shm.shmid, IPC_RMID, NULL); px = (uint32_t *)img->data; } }
        }
        if (!use_shm && img) { XDestroyImage(img); img = NULL; }
    }
    if (!use_shm) { px = calloc((size_t)W * H, 4); img = XCreateImage(dpy, vis, depth, ZPixmap, 0, (char *)px, W, H, 32, 0); }
    if (!img || !px || img->bits_per_pixel != 32) { XDestroyWindow(dpy, win); XCloseDisplay(dpy); log_json("x11", W, H, 0, 0, 0, 0, 0, 0, 0, 0, u0, u0, 0, "unsupported visual"); return 0; }
    int stride = img->bytes_per_line / 4;
    char keys0[32], keys[32]; XQueryKeymap(dpy, keys0);
    Window rr, cr; int rx, ry, wx, wy; unsigned mask0, mask; XQueryPointer(dpy, RootWindow(dpy, scr), &rr, &cr, &rx, &ry, &wx, &wy, &mask0);
    Atom pm = XInternAtom(dpy, "_XROOTPMAP_ID", False);
    /* lateness: carpatic-intro passes the session start (uptime). Late = the desktop is already waiting under us: play the short version. */
    double late = 0; const char *t0e = getenv("CARPATIC_INTRO_T0"); if (t0e) { late = u0 - atof(t0e); if (late < 0) late = 0; }
    double reveal_min = late < 1.2 ? REVEAL_MIN : REVEAL_SHORT, ts = atof(envs("CARPATIC_INTRO_TIMESCALE", "1")); if (ts <= 0) ts = 1;
    double frame_s = 1.0 / 60, t_start = now(), next = t_start, prev_t = -1, reveal = -1, last = t_start;
    double *dts = malloc(sizeof(double) * 400); int nd = 0, over25 = 0; int slow = 0, skipped = 0; const char *note = "";
    int cover_done = 0;
    for (;;) {
        double tn = now(), t = (tn - t_start) / ts; double dt = tn - last; last = tn;
        if (prev_t >= 0 && nd < 400) { dts[nd++] = dt; if (dt > 0.025) over25++; }
        /* skip: a NEW key or a mouse button (keys held down from the login are ignored) */
        XQueryKeymap(dpy, keys); int newkey = 0; for (int i = 0; i < 32; i++) if (keys[i] & ~keys0[i]) newkey = 1;
        for (int i = 0; i < 32; i++) keys0[i] &= keys[i];      /* a key released during the intro may be pressed again */
        XQueryPointer(dpy, RootWindow(dpy, scr), &rr, &cr, &rx, &ry, &wx, &wy, &mask);
        if (newkey || (mask & (Button1Mask | Button2Mask | Button3Mask | Button4Mask | Button5Mask) & ~mask0)) { skipped = 1; break; }
        if (!force_play && !slow && reveal < 0) {
            if (nd == 14) { qsort(dts + 2, 12, sizeof(double), cmp_d); if (dts[8] > 0.045) { slow = 1; note = "slow screen: skipped ahead"; } }
            if (dt > 0.35 && nd > 2) { slow = 1; note = "a long stall: skipped ahead"; }
            if (slow) reveal = t;
        }
        if (reveal < 0 && t >= reveal_min) {
            Atom at_; int fmt; unsigned long ni, ba; unsigned char *data = NULL;
            int ready = XGetWindowProperty(dpy, RootWindow(dpy, scr), pm, 0, 1, False, XA_PIXMAP, &at_, &fmt, &ni, &ba, &data) == Success && data;
            if (data) XFree(data);
            if (ready || t >= REVEAL_LATEST) reveal = t;
        }
        if (!cover_done) {
            Rect r;
            if (scene_damage(&s, prev_t, t, &r)) {
                scene_render(&s, t, px, stride, r);
                if (use_shm) XShmPutImage(dpy, win, gc, img, r.x, r.y, r.x, r.y, r.w, r.h, False); else XPutImage(dpy, win, gc, img, r.x, r.y, r.x, r.y, r.w, r.h);
            }
            prev_t = t; if (t > SINK_AT + SINK_DUR + 0.05) cover_done = 1;
        }
        if (reveal >= 0) {
            double dur = slow ? 0.12 : REVEAL_DUR;
            if (t - reveal >= dur) break;
            double p = (t - reveal) / dur, r = s.R0 * p * p * (3 - 2 * p);
            enum { B = 2 }; static XRectangle *rects = NULL; if (!rects) rects = malloc(sizeof(XRectangle) * (size_t)(H / B + 1) * 2); int nr = 0;
            for (int y = 0; y < H; y += B) {
                double yy = y + B / 2.0 - s.suny;
                if (fabs(yy) >= r) { rects[nr++] = (XRectangle){0, y, W, B}; continue; }
                int dx = (int)sqrt(r * r - yy * yy), l = s.sunx - dx, rg = s.sunx + dx;
                if (l > 0) rects[nr++] = (XRectangle){0, y, l < W ? l : W, B};
                if (rg < W) rects[nr++] = (XRectangle){rg > 0 ? rg : 0, y, W - (rg > 0 ? rg : 0), B};
            }
            XShapeCombineRectangles(dpy, win, ShapeBounding, 0, 0, rects, nr, ShapeSet, YXBanded);
        }
        XFlush(dpy);
        next += frame_s; double w = next - now(); if (w < -0.2) next = now(); else if (w > 0) { struct timespec rq = {0, (long)(w * 1e9)}; nanosleep(&rq, NULL); }
        if (now() - t_start > (REVEAL_LATEST + REVEAL_DUR + 1.5) * ts) { note = "timeout"; break; }
    }
    XDestroyWindow(dpy, win); XSync(dpy, False);
    if (use_shm) { XShmDetach(dpy, &shm); shmdt(shm.shmaddr); }
    XCloseDisplay(dpy);
    double sum = 0, p95 = 0, mx = 0; if (nd > 1) { for (int i = 1; i < nd; i++) { sum += dts[i]; if (dts[i] > mx) mx = dts[i]; } qsort(dts + 1, nd - 1, sizeof(double), cmp_d); p95 = dts[1 + (int)((nd - 1) * 0.95) - (nd > 2)]; }
    log_json("native", W, H, nd, nd > 1 ? 1000 * sum / (nd - 1) : 0, 1000 * p95, 1000 * mx, over25, now() - t_proc, (double)(clock() - c0) / CLOCKS_PER_SEC, reveal, u0, uptime(), skipped, note);
    (void)t_ready;
    if (slow && !force_play) { char p[700]; snprintf(p, sizeof p, "%s/intro.slow", statedir); FILE *f = fopen(p, "w"); if (f) { fprintf(f, "%.1f ms per frame on %dx%d\n", nd > 1 ? 1000 * sum / (nd - 1) : 0, W, H); fclose(f); } }
    return 0;
}
#endif

int main(int argc, char **argv) {
    snprintf(cfgdir, sizeof cfgdir, "%s", getenv("CARPATIC_CONFIG") ? getenv("CARPATIC_CONFIG") : "");
    if (!cfgdir[0]) snprintf(cfgdir, sizeof cfgdir, "%s/.config/carpatic", envs("HOME", "/root"));
    snprintf(statedir, sizeof statedir, "%s", getenv("CARPATIC_STATE") ? getenv("CARPATIC_STATE") : "");
    if (!statedir[0]) snprintf(statedir, sizeof statedir, "%s/.local/state/carpatic", envs("HOME", "/root"));
    const char *dump = NULL, *windowed = NULL, *ready = NULL; int W = 1280, H = 800, force = 0, selftest = 0; double fps = 30;
    for (int i = 1; i < argc; i++) {
        if (!strcmp(argv[i], "--dump") && i + 1 < argc) dump = argv[++i];
        else if (!strcmp(argv[i], "--size") && i + 1 < argc) sscanf(argv[++i], "%dx%d", &W, &H);
        else if (!strcmp(argv[i], "--fps") && i + 1 < argc) fps = atof(argv[++i]);
        else if (!strcmp(argv[i], "--windowed") && i + 1 < argc) windowed = argv[++i];
        else if (!strcmp(argv[i], "--ready-file") && i + 1 < argc) ready = argv[++i];
        else if (!strcmp(argv[i], "--force-play") || !strcmp(argv[i], "--force")) force = 1;
        else if (!strcmp(argv[i], "--selftest")) selftest = 1;
        else { fprintf(stderr, "carpatic-intro-play: unknown option %s (see the top of motion/src/intro_main.c)\n", argv[i]); return 2; }
    }
    uint32_t accent = 0x5cc8a8, ember = 0xf2a65a; theme_colors(&accent, &ember);
    if (selftest) return cmd_selftest(accent, ember);
    if (dump) return cmd_dump(dump, W, H, fps, accent, ember);
#ifdef HAVE_X11
    return cmd_play(force, windowed, ready);
#else
    (void)windowed; (void)ready; (void)force; fprintf(stderr, "carpatic-intro-play: built without X11\n"); return 1;
#endif
}
