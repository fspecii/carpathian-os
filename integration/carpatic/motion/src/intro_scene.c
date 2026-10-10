#include "intro_scene.h"
#include <math.h>
#include <stdlib.h>
#include <string.h>

static double clamp01(double v) { return v < 0 ? 0 : v > 1 ? 1 : v; }
static double ease_out(double t) { t = clamp01(t); double u = 1 - t; return 1 - u * u * u; }
static double ease_in(double t) { t = clamp01(t); return t * t * t; }
static double smooth(double t) { t = clamp01(t); return t * t * (3 - 2 * t); }

uint32_t rgb_mix(uint32_t a, uint32_t b, int t) {
    int ar = a >> 16 & 255, ag = a >> 8 & 255, ab = a & 255, br = b >> 16 & 255, bg = b >> 8 & 255, bb = b & 255;
    return (uint32_t)(((ar * (64 - t) + br * t) >> 6) << 16 | ((ag * (64 - t) + bg * t) >> 6) << 8 | ((ab * (64 - t) + bb * t) >> 6));
}

static const double stops_d[] = {0, 0.10, 0.30, 0.55, 1.0}, stops_a[] = {0.62, 0.40, 0.15, 0.045, 0.0};
static double glow_alpha(double d) {      /* d = distance / radius */
    if (d >= 1) return 0;
    for (int i = 0; i < 4; i++) if (d <= stops_d[i + 1]) { double k = (d - stops_d[i]) / (stops_d[i + 1] - stops_d[i]); return stops_a[i] + (stops_a[i + 1] - stops_a[i]) * k; }
    return 0;
}

int scene_init(Scene *s, int W, int H, uint32_t accent, uint32_t ember, uint32_t start) {
    memset(s, 0, sizeof *s);
    s->W = W; s->H = H; s->start = start; s->ember = ember; s->rh = (int)(H * 0.46);
    s->sunx = (int)(W * 0.64); s->suny = (int)(H * 0.50);
    s->glow_r = (int)(H * 0.50); s->gh = 2 * s->glow_r;
    static const int tint[3] = {23, 15, 8};      /* 0.36, 0.23, 0.12 of 64 */
    static const double base[3] = {0.40, 0.55, 0.70}, amp[3] = {0.34, 0.28, 0.20}, sc[3] = {0.011, 0.016, 0.022};
    static const double fa[5] = {0.50, 0.28, 0.14, 0.08, 0.05}, ff[5] = {1.0, 2.3, 4.9, 9.7, 17.0};
    for (int i = 0; i < 3; i++) {
        s->col[i] = rgb_mix(start, accent, tint[i]);
        s->top[i] = malloc(sizeof(int) * (size_t)W); s->grad[i] = malloc(sizeof(uint32_t) * (size_t)s->rh);
        if (!s->top[i] || !s->grad[i]) return -1;
        double ph[5]; for (int k = 0; k < 5; k++) ph[k] = fmod((201 + i) * 1.7 + k * 2.3, 6.28);
        int mn = s->rh;
        for (int x = 0; x < W; x++) {
            double u = x * sc[i] * (1280.0 / (W > 0 ? W : 1)) * ((double)W / 1280.0), v = 0;
            for (int k = 0; k < 5; k++) {
                double sv = sin(u * ff[k] * 6.28 / 12 + ph[k]);
                v += fa[k] * (i == 0 ? 1 - fabs(sv) : 0.5 + 0.5 * sv);
            }
            int t = (int)(s->rh * (base[i] - (v - 0.5) * amp[i])); if (t < 0) t = 0; if (t >= s->rh) t = s->rh - 1;
            s->top[i][x] = t; if (t < mn) mn = t;
        }
        for (int y = 0; y < s->rh; y++) s->grad[i][y] = rgb_mix(s->col[i], rgb_mix(s->col[i], start, 42), y < mn ? 0 : (y - mn) * 64 / (s->rh - mn > 0 ? s->rh - mn : 1));
    }
    s->gmap = malloc((size_t)s->gh * (size_t)s->gh);
    if (!s->gmap) return -1;
    for (int y = 0; y < s->gh; y++) for (int x = 0; x < s->gh; x++) {
        double d = hypot(x - s->glow_r + 0.5, y - s->glow_r + 0.5) / s->glow_r;
        s->gmap[(size_t)y * s->gh + x] = (uint8_t)(glow_alpha(d) * 255 + 0.5);
    }
    s->R0 = hypot(fmax(s->sunx, W - s->sunx), fmax(s->suny, H - s->suny)) + 4;
    return 0;
}

void scene_free(Scene *s) { for (int i = 0; i < 3; i++) { free(s->top[i]); free(s->grad[i]); } free(s->gmap); memset(s, 0, sizeof *s); }

double scene_iris(const Scene *s, double t, double rs) {
    double p = (t - rs) / REVEAL_DUR;
    if (p <= 0) return 0;
    return p >= 1 ? s->R0 + 1 : s->R0 * smooth(p);
}

static int layer_y(const Scene *s, int i, double t) {
    double p = ease_out((t - i * RISE_STEP) / RISE_DUR), sink = ease_in((t - SINK_AT) / SINK_DUR);
    return (int)floor(s->H - s->rh + s->rh * (0.55 - 0.05 * i) * (1 - p) + sink * s->rh * (0.30 + 0.1 * i) + 0.5);
}
static int layer_a64(double t, int i) {
    double p = ease_out((t - i * RISE_STEP) / RISE_DUR), sink = ease_in((t - SINK_AT) / SINK_DUR);
    return (int)(p * (1 - sink) * 64 + 0.5);
}
static int glow_step(double t) {
    double g = ease_out((t - 0.20) / 0.80) * (1 - smooth((t - SINK_AT) / SINK_DUR));
    return (int)(g * GLOW_STEPS);
}

int scene_damage(const Scene *s, double t0, double t1, Rect *out) {
    if (t0 < 0) { *out = (Rect){0, 0, s->W, s->H}; return 1; }
    int x0 = s->W, y0 = s->H, x1 = 0, y1 = 0, any = 0;
    if (glow_step(t0) != glow_step(t1)) {
        x0 = s->sunx - s->glow_r; y0 = s->suny - s->glow_r; x1 = s->sunx + s->glow_r; y1 = s->suny + s->glow_r; any = 1;
    }
    int ch = 0, top = s->H;
    for (int i = 0; i < 3; i++) {
        int ya = layer_y(s, i, t0), yb = layer_y(s, i, t1);
        if (ya != yb || layer_a64(t0, i) != layer_a64(t1, i)) { ch = 1; if (ya < top) top = ya; if (yb < top) top = yb; }
    }
    if (ch) { if (top < 0) { top = 0; } x0 = 0; x1 = s->W; if (top < y0) { y0 = top; } y1 = s->H; any = 1; }
    if (!any) return 0;
    if (x0 < 0) { x0 = 0; }
    if (y0 < 0) { y0 = 0; }
    if (x1 > s->W) { x1 = s->W; }
    if (y1 > s->H) { y1 = s->H; }
    if (x1 <= x0 || y1 <= y0) return 0;
    *out = (Rect){x0, y0, x1 - x0, y1 - y0};
    return 1;
}

static inline uint32_t blend_px(uint32_t d, uint32_t sr, int a64) {
    int r = ((d >> 16 & 255) * (64 - a64) + (sr >> 16 & 255) * a64) >> 6, g = ((d >> 8 & 255) * (64 - a64) + (sr >> 8 & 255) * a64) >> 6, b = ((d & 255) * (64 - a64) + (sr & 255) * a64) >> 6;
    return (uint32_t)(r << 16 | g << 8 | b);
}

void scene_render(const Scene *s, double t, uint32_t *dst, int stride, Rect r) {
    int gq = glow_step(t);
    int gx0 = s->sunx - s->glow_r, gy0 = s->suny - s->glow_r;
    int sr = s->ember >> 16 & 255, sg = s->ember >> 8 & 255, sb = s->ember & 255;
    for (int y = r.y; y < r.y + r.h; y++) {
        uint32_t *row = dst + (size_t)y * stride;
        for (int x = r.x; x < r.x + r.w; x++) row[x] = s->start;
        if (gq > 0 && y >= gy0 && y < gy0 + s->gh) {
            const uint8_t *g = s->gmap + (size_t)(y - gy0) * s->gh;
            int xa = r.x > gx0 ? r.x : gx0, xb = r.x + r.w < gx0 + s->gh ? r.x + r.w : gx0 + s->gh;
            int st_r = s->start >> 16 & 255, st_g = s->start >> 8 & 255, st_b = s->start & 255;
            for (int x = xa; x < xb; x++) {
                int a = g[x - gx0] * gq / GLOW_STEPS;          /* 0..255 */
                if (!a) continue;
                row[x] = (uint32_t)((st_r + (sr - st_r) * a / 255) << 16 | (st_g + (sg - st_g) * a / 255) << 8 | (st_b + (sb - st_b) * a / 255));
            }
        }
    }
    for (int i = 0; i < 3; i++) {
        int a = layer_a64(t, i); if (a <= 0) continue;
        int ly = layer_y(s, i, t);
        for (int x = r.x; x < r.x + r.w; x++) {
            int ystart = ly + s->top[i][x]; if (ystart < r.y) ystart = r.y;
            int yend = ly + s->rh; if (yend > r.y + r.h) yend = r.y + r.h; if (yend > s->H) yend = s->H;
            for (int y = ystart; y < yend; y++) {
                uint32_t *p = dst + (size_t)y * stride + x;
                *p = a >= 64 ? s->grad[i][y - ly] : blend_px(*p, s->grad[i][y - ly], a);
            }
        }
    }
}
