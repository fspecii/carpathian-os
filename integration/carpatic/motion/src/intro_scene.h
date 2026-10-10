/* intro_scene: the login reveal, drawn without any library (plain C99, 32-bit 0x00RRGGBB pixels).
 * Used by carpatic-intro-play (X11 front end, intro_x11.c) and by the host tools (--dump, --selftest) so what the tests see is what the screen shows.
 * Timeline (seconds): three ridge layers rise 0.00-0.84 (600 ms each, 120 ms apart, ease-out), the ember glow warms up 0.20-1.00, the ridges sink
 * 1.00-1.40 and the glow fades, an iris opens from the sun onto the live desktop from REVEAL_MIN (default 1.15) for 0.40 s. Total about 1.55 s. */
#ifndef INTRO_SCENE_H
#define INTRO_SCENE_H
#include <stdint.h>

#define RISE_DUR 0.60
#define RISE_STEP 0.12
#define SINK_AT 1.00
#define SINK_DUR 0.40
#define REVEAL_MIN 1.15
#define REVEAL_SHORT 0.75   /* used when the start was late */
#define REVEAL_DUR 0.40
#define REVEAL_LATEST 2.00
#define GLOW_STEPS 8

typedef struct { int x, y, w, h; } Rect;

typedef struct {
    int W, H, rh, sunx, suny, glow_r, gh;
    uint32_t start, ember, col[3];
    int *top[3];          /* per layer, per column: first row (inside the layer) that is mountain */
    uint32_t *grad[3];    /* per layer, per row inside the layer */
    uint8_t *gmap;        /* glow alpha, (2*glow_r)^2 */
    double R0;            /* iris radius that covers the whole screen */
} Scene;

uint32_t rgb_mix(uint32_t a, uint32_t b, int t64);          /* t64 in 0..64 */
int scene_init(Scene *s, int W, int H, uint32_t accent, uint32_t ember, uint32_t start);
void scene_free(Scene *s);
double scene_iris(const Scene *s, double t, double reveal_start);   /* radius of the hole at time t (0 before the reveal) */
/* bounding box of everything that differs between the frames at t0 and t1 (0 = identical). t0 < 0: the whole screen. */
int scene_damage(const Scene *s, double t0, double t1, Rect *out);
/* draw the cover of time t into dst (stride in pixels) but only inside r */
void scene_render(const Scene *s, double t, uint32_t *dst, int stride, Rect r);
#endif
