# saver.awk: the Carpathian screensaver effects. One long-lived awk process: it reads one line per frame tick from stdin and writes the changes for that
# frame to stdout (cursor addressing, direct emission, only the cells that change). Records on stdin:
#   T            next frame            R rows cols   terminal was resized (screen is cleared, the effect restarts)            Q   quit
# Variables (-v): ROWS COLS DEPTH(24|256|16) FPS SEED EFFECTS("brand rain sunrise stars") LIFE(seconds per effect, 0 = forever)
#                 ACCENT EMBER BG BGDEEP FG MUTED (hex, from the active theme)  LOGO(file, mountain line art)  MARK(1: write \036 after every frame, for tests)
# Effects, all original: brand (the mountain logo with a colour wave from spruce to ember), rain (mountain glyphs fall and leave a spruce trail),
# sunrise (a sky gradient, three ridges and the ember sun rising behind them), stars (a starfield flying past, an ember star now and then).
function clamp(v, lo, hi) { return v < lo ? lo : (v > hi ? hi : v) }
function hexv(c) { return index("0123456789abcdef", tolower(c)) - 1 }
function rgbof(h,   s) { s = tolower(h); sub(/^#/, "", s); R_ = hexv(substr(s,1,1))*16 + hexv(substr(s,2,1)); G_ = hexv(substr(s,3,1))*16 + hexv(substr(s,4,1)); B_ = hexv(substr(s,5,1))*16 + hexv(substr(s,6,1)); return R_ * 65536 + G_ * 256 + B_ }
function mixp(a, b, t,   ar, ag, ab, br, bg_, bb) {
  t = clamp(t, 0, 1)
  ar = int(a / 65536); ag = int(a / 256) % 256; ab = a % 256; br = int(b / 65536); bg_ = int(b / 256) % 256; bb = b % 256
  return int(ar + (br - ar) * t + .5) * 65536 + int(ag + (bg_ - ag) * t + .5) * 256 + int(ab + (bb - ab) * t + .5)
}
function near256(p,   r, g, b, ri, gi, bi, grey, gl, best, bd, d, k, cr, cg, cb) {
  r = int(p / 65536); g = int(p / 256) % 256; b = p % 256
  ri = int(clamp((r - 35) / 40, 0, 5) + .5); gi = int(clamp((g - 35) / 40, 0, 5) + .5); bi = int(clamp((b - 35) / 40, 0, 5) + .5)
  cr = ri ? 55 + 40 * ri : 0; cg = gi ? 55 + 40 * gi : 0; cb = bi ? 55 + 40 * bi : 0
  bd = (r - cr) ^ 2 + (g - cg) ^ 2 + (b - cb) ^ 2; best = 16 + 36 * ri + 6 * gi + bi
  gl = int(clamp((r + g + b) / 3 - 8, 0, 230) / 10 + .5); k = 8 + gl * 10
  d = (r - k) ^ 2 + (g - k) ^ 2 + (b - k) ^ 2
  if (d < bd) best = 232 + clamp(gl, 0, 23)
  return best
}
function near16(p,   i, bd, d, best) {              # nearest of the role colours (a Linux VT maps the 16 codes to the theme palette)
  bd = 1e18; best = "39"
  for (i = 1; i <= NP16; i++) { d = (int(p/65536) - int(P16[i]/65536)) ^ 2 + (int(p/256)%256 - int(P16[i]/256)%256) ^ 2 + (p%256 - P16[i]%256) ^ 2; if (d < bd) { bd = d; best = C16[i] } }
  return best
}
function fgs(p) { if (p in FGC) return FGC[p]
  if (DEPTH == 24) FGC[p] = sprintf("38;2;%d;%d;%d", int(p/65536), int(p/256)%256, p%256)
  else if (DEPTH == 256) FGC[p] = "38;5;" near256(p)
  else FGC[p] = near16(p)
  return FGC[p] }
function bgs(p) { if (p in BGC) return BGC[p]
  if (DEPTH == 24) BGC[p] = sprintf("48;2;%d;%d;%d", int(p/65536), int(p/256)%256, p%256)
  else if (DEPTH == 256) BGC[p] = "48;5;" near256(p)
  else { BGC[p] = near16(p); if (BGC[p] ~ /^9/) BGC[p] = BGC[p] + 10; else BGC[p] = BGC[p] + 10 }
  return BGC[p] }
function put(y, x, ch, fg, bg) {                    # y, x are 1-based cells; fg/bg packed rgb or -1
  if (y < 1 || y > ROWS || x < 1 || x > COLS) return
  OUT = OUT sprintf("\033[%d;%dH\033[%s%sm%s", y, x, (fg < 0 ? "39" : fgs(fg)), (bg < 0 ? "" : ";" bgs(bg)), ch)
  if (length(OUT) > 6000) { printf "%s", OUT; OUT = "" }          # big repaints are written in pieces: repeated concatenation of a huge string is quadratic
}
function flush_frame() { if (OUT != "") { printf "%s\033[0m", OUT; OUT = "" } if (MARK) printf "%c", 30; fflush() }
function clearscreen() { OUT = OUT "\033[0m\033[2J" }

# ------------------------------------------------------------------ effect: brand
function brand_init(   i) {
  NL = 0; LW = 0
  while ((getline ln < LOGO) > 0) { LG[++NL] = ln; if (length(ln) > LW) LW = length(ln) }
  close(LOGO)
  LTOP = int((ROWS - (NL + 2)) / 2) + 1; if (LTOP < 1) LTOP = 1
  LLEFT = int((COLS - LW) / 2) + 1; if (LLEFT < 1) LLEFT = 1
  TAG = "Linux, with a view."; TAGX = int((COLS - length(TAG)) / 2) + 1
  BT = 0
}
function brand_frame(   r, x, ch, ph, c, base, line, k) {
  BT++
  if (BT % 2) return                                # 15 fps is plenty for a slow wave
  ph = BT / FPS
  for (r = 1; r <= NL; r++) {
    line = LG[r]
    for (x = 1; x <= length(line); x++) {
      ch = substr(line, x, 1)
      if (ch == " ") continue
      base = (r <= 4 && x != 0) ? SNOWP : ACCP
      if (r == NL) base = ACCP
      if (r <= 3 && x >= 46 && x <= 50) base = EMBP
      k = 0.5 + 0.5 * sin((x + 2 * r) / 9 - ph * 1.4)          # a slow wave travelling right
      c = mixp(base == ACCP ? mixp(ACCP, SNOWP, 0.18) : base, (base == EMBP ? SNOWP : EMBP), (base == EMBP ? 0.35 * k : 0.55 * k * k))
      if (r == NL - 2) c = mixp(MUTP, ACCP, k * 0.4)
      put(LTOP + r - 1, LLEFT + x - 1, ch, c, -1)
    }
  }
  if (BT == 2) { for (x = 1; x <= length(TAG); x++) put(LTOP + NL + 1, TAGX + x - 1, substr(TAG, x, 1), MUTP, -1) }
}
# ------------------------------------------------------------------ effect: rain of mountain glyphs
function rain_init(   x) {
  NG = split("▲ ◢ ◣ ⛰ ^ ∧", GL, " "); GL[4] = "▲"
  ND = 0; for (x = 1; x <= COLS; x += 2) { D_x[ND] = x + int(rand() * 2); D_y[ND] = int(rand() * ROWS); D_v[ND] = 0.18 + rand() * 0.5; D_len[ND] = 5 + int(rand() * 9); D_g[ND] = GL[1 + int(rand() * 3)]; D_row[ND] = -999; ND++ }
}
function rain_frame(   i, r, k, c, row) {
  for (i = 0; i < ND; i++) {
    D_y[i] += D_v[i]; row = int(D_y[i])
    if (row == D_row[i]) continue
    D_row[i] = row
    if (row - D_len[i] > ROWS) { D_y[i] = -int(rand() * 8); D_row[i] = -999; D_x[i] = 1 + int(rand() * COLS); D_v[i] = 0.18 + rand() * 0.5; D_len[i] = 5 + int(rand() * 9); D_g[i] = GL[1 + int(rand() * 3)]; continue }
    put(row - D_len[i], D_x[i], " ", -1, -1)       # erase the tail end
    for (k = 0; k < D_len[i]; k++) {
      r = row - k; if (r < 1 || r > ROWS) continue
      if (k == 0) c = SNOWP
      else if (k == 1) c = mixp(SNOWP, ACCP, 0.5)
      else c = mixp(ACCP, BGP, (k / D_len[i]) ^ 1.3)
      put(r, D_x[i], (k < 3 ? D_g[i] : (k % 2 ? "·" : ":")), c, -1)
    }
  }
}
# ------------------------------------------------------------------ effect: sunrise
function ridge_h(l, x,   v) { return RH0[l] + RA[l] * (sin(x / RS1[l] + RP1[l]) * 0.55 + sin(x / RS2[l] + RP2[l]) * 0.3 + sin(x / RS3[l] + RP3[l]) * 0.15) }
function sky_at(y,   t) { t = (y - 1) / (HOR - 1); return mixp(BGDEEPP, mixp(MIDP, mixp(EMBP, SNOWP, 0.25), t * t * t), t * 0.9) }
function cell_bg(y, x,   l, c) {                     # background of one cell: sky, or the ridge silhouette in front of it
  for (l = 3; l >= 1; l--) if (y >= HOR - RHT[l, x]) return mixp(mixp(BGDEEPP, ACCP, 0.20 - 0.065 * (l - 1)), BGDEEPP, clamp((y - (HOR - RHT[l, x])) / (ROWS * 0.5), 0, 0.7))
  return sky_at(y)
}
function sunrise_init(   l, x, y) {
  HOR = int(ROWS * 0.78); if (HOR < 6) HOR = 6
  MIDP = mixp(BGDEEPP, ACCP, 0.28)
  for (l = 1; l <= 3; l++) { RH0[l] = ROWS * (0.20 - 0.04 * l); RA[l] = ROWS * (0.10 + 0.02 * l); RS1[l] = 9 + 5 * l + rand() * 3; RS2[l] = 4 + 2 * l + rand(); RS3[l] = 2 + l; RP1[l] = rand() * 6; RP2[l] = rand() * 6; RP3[l] = rand() * 6 }
  for (l = 1; l <= 3; l++) for (x = 1; x <= COLS; x++) RHT[l, x] = int(ridge_h(l, x) + 0.5)
  for (l = 1; l <= 3; l++) for (x = 1; x <= COLS; x++) { RHT[l, x] = int(RH0[l] * 0.9 + RHT[l, x] - RH0[l] * 0.9) }
  for (y = 1; y <= ROWS; y++) for (x = 1; x <= COLS; x++) { put(y, x, " ", -1, cell_bg(y, x)); }
  SUNX = int(COLS * (0.3 + rand() * 0.4)); SR = clamp(int(ROWS / 7), 2, 7); SUNT = 0; SUNLAST = -999
}
function sunrise_frame(   y, x, py, cy, dx, dy, k, p, a) {
  SUNT++
  p = clamp(SUNT / (LIFEF * 0.9 + 1), 0, 1); if (LIFEF == 0) p = clamp(SUNT / (45 * FPS), 0, 1)
  cy = HOR + SR * 1.2 - p * (HOR * 0.55 + SR)                 # sun centre row (can start below the horizon)
  if (int(cy * 2) == SUNLAST) return
  # erase the old disc area, then draw the new one in half-block pixels (2 per row)
  if (SUNLAST > -999) for (y = int(SUNLAST / 2) - SR - 2; y <= int(SUNLAST / 2) + SR + 2; y++) for (x = SUNX - SR * 2 - 3; x <= SUNX + SR * 2 + 3; x++) put(y, x, " ", -1, cell_bg(y, x))
  SUNLAST = int(cy * 2)
  for (y = int(cy) - SR - 2; y <= int(cy) + SR + 2; y++) for (x = SUNX - SR * 2 - 3; x <= SUNX + SR * 2 + 3; x++) {
    if (y < 1 || y > ROWS) continue
    if (y >= HOR - RHT[1, x]) continue                      # behind the far ridge
    dx = (x - SUNX) / 2; k = 0
    dy = y - cy; a = dx * dx + dy * dy
    if (a <= SR * SR) { put(y, x, " ", -1, mixp(EMBP, SNOWP, 0.35 * (1 - (a / (SR * SR))))) }
    else if (a <= (SR + 2.2) ^ 2) { put(y, x, " ", -1, mixp(cell_bg(y, x), EMBP, 0.45 * (1 - (sqrt(a) - SR) / 2.2))) }
  }
}
# ------------------------------------------------------------------ effect: stars
function stars_init(   i) { NS = int(COLS * ROWS / 40); if (NS < 30) NS = 30; if (NS > 260) NS = 260; for (i = 0; i < NS; i++) star_new(i, 1); SGL[0] = "."; SGL[1] = "·"; SGL[2] = "∙"; SGL[3] = "+"; SGL[4] = "*" }
function star_new(i, init) { S_a[i] = rand() * 6.2832; S_r[i] = rand() ^ 0.5 * 0.9 + 0.05; S_z[i] = init ? rand() : 1; S_e[i] = (rand() < 0.04); S_x[i] = -1; S_y[i] = -1 }
function stars_frame(   i, sx, sy, z, c, g, spd) {
  for (i = 0; i < NS; i++) {
    S_z[i] -= 0.02 + 0.03 * (1 - S_z[i]); z = S_z[i]
    if (z <= 0.02) { if (S_x[i] > 0) put(S_y[i], S_x[i], " ", -1, -1); star_new(i, 0); continue }
    sx = int(COLS / 2 + cos(S_a[i]) * S_r[i] / z * COLS * 0.11 + .5); sy = int(ROWS / 2 + sin(S_a[i]) * S_r[i] / z * ROWS * 0.11 + .5)
    if (sx == S_x[i] && sy == S_y[i]) continue
    if (S_x[i] > 0) put(S_y[i], S_x[i], " ", -1, -1)
    if (sx < 1 || sx > COLS || sy < 1 || sy > ROWS) { star_new(i, 0); S_x[i] = -1; continue }
    c = mixp(MUTP, SNOWP, 1 - z); if (S_e[i]) c = mixp(EMBP, SNOWP, 1 - z)
    g = SGL[clamp(int((1 - z) * 5), 0, 4)]
    put(sy, sx, g, c, -1); S_x[i] = sx; S_y[i] = sy
  }
}
# ------------------------------------------------------------------ driver
function start_effect(e) {
  CUR = e; clearscreen(); FRAME = 0
  if (e == "brand") brand_init(); else if (e == "rain") rain_init(); else if (e == "sunrise") sunrise_init(); else stars_init()
}
function next_effect(   e) {
  do { e = EF[1 + int(rand() * NEF)] } while (NEF > 1 && e == CUR)
  start_effect(e)
}
BEGIN {
  srand(SEED ? SEED : 1); if (!FPS) FPS = 20; if (!DEPTH) DEPTH = 24
  ACCP = rgbof(ACCENT ? ACCENT : "#5cc8a8"); EMBP = rgbof(EMBER ? EMBER : "#f2a65a"); BGP = rgbof(BG ? BG : "#11151c"); BGDEEPP = rgbof(BGDEEP ? BGDEEP : "#0b0e13")
  FGP = rgbof(FG ? FG : "#e7ecf3"); MUTP = rgbof(MUTED ? MUTED : "#6b778c"); SNOWP = FGP
  P16[1] = BGDEEPP; C16[1] = "30"; P16[2] = MUTP; C16[2] = "90"; P16[3] = ACCP; C16[3] = "36"; P16[4] = mixp(ACCP, FGP, 0.4); C16[4] = "96"
  P16[5] = FGP; C16[5] = "97"; P16[6] = EMBP; C16[6] = "33"; P16[7] = mixp(EMBP, FGP, 0.4); C16[7] = "93"; P16[8] = mixp(BGP, ACCP, 0.3); C16[8] = "36"; NP16 = 8
  NEF = split(EFFECTS ? EFFECTS : "brand rain sunrise stars", EF, " ")
  LIFEF = int((LIFE ? LIFE : 45) * FPS); if (LIFE == "0") LIFEF = 0
  next_effect(); first = 1
  if (FIRST) start_effect(FIRST)
  flush_frame()
}
$1 == "Q" { exit }
$1 == "R" { ROWS = $2; COLS = $3; start_effect(CUR); flush_frame(); next }
$1 == "T" {
  FRAME++
  if (CUR == "brand") brand_frame(); else if (CUR == "rain") rain_frame(); else if (CUR == "sunrise") sunrise_frame(); else stars_frame()
  if (LIFEF > 0 && FRAME >= LIFEF) next_effect()
  flush_frame()
}
