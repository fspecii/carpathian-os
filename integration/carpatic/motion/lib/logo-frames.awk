# logo-frames.awk: frames of the Carpatic ASCII mountain logo for a terminal, using ONLY the 16 indexed ANSI colours (the console palette from
# design tokens decides the real look; truecolour would be crushed by the Linux framebuffer console).
# Usage: awk -v LOGO=logo.txt -v TOP=5 -v LEFT=10 -v FPS=30 -v MODE=rise|shift|final|static -v RS_OUT=... -f logo-frames.awk
#   MODE=rise   frames of the entrance (rows climb from the bottom, ember sun last, wordmark fades in): ends on the "final" look
#   MODE=shift  one seamless loop of the colour shift (a bright band drifts over the peaks, the sun pulses), starts and ends on the final look
#   MODE=final  one frame, the settled look (identical to installer/wizard/lib/logo.sh print_logo)
# Frames are written to stdout separated by the ASCII record separator (0x1e); each frame only repaints the logo rectangle (cursor addressing),
# so nothing else on screen flickers. Colour classes follow print_logo: snow 97, peaks 36, sun 33, base line 90, wordmark bold 36.
function clamp(v, lo, hi) { return v < lo ? lo : (v > hi ? hi : v) }
function ease(t) { t = clamp(t, 0, 1); return 1 - (1 - t) * (1 - t) * (1 - t) }
function base(r, i) {                        # final colour code of the cell
  if (r == L) return "1;36"
  if (r <= 3 && i >= 46 && i <= 50) return "33"
  if (r == L - 2) return "90"
  if (r <= 4) return "97"
  return "36"
}
function sinp(x) { return sin(x * 6.283185307) }
function frame(band, pulse,   r, i, ch, out, last, c, code, line, sgr) {
  out = ""
  for (r = 1; r <= L; r++) {
    line = row[r]; last = ""; s = sprintf("\033[%d;%dH", TOP + r, LEFT + 1)
    st = stage[r]
    for (i = 1; i <= length(line); i++) {
      ch = substr(line, i, 1)
      if (ch == " ") { s = s " "; continue }
      c = base(r, i)
      if (st < 1) { s = s " "; continue }                       # hidden
      if (st < 2) c = "90"                                       # dim: on its way up
      else if (st < 3 && r < L) c = (c == "97") ? "37" : (c == "36" ? "36" : c)   # almost there
      if (st >= 3) {                                             # settled: shift band + sun pulse
        if (band >= -100) {
          d = (i + 2 * r) - band; if (d < 0) d = -d
          if (d < 7) { if (c == "36") c = (d < 2) ? "97" : "96"; else if (c == "90") c = "37"; else if (c == "1;36") c = "1;96" }
        }
        if (c == "33" && pulse > 0.5) c = "93"
      }
      if (c != last) { s = s "\033[" c "m"; last = c }
      s = s ch
    }
    out = out s "\033[0m"
  }
  return out
}
BEGIN {
  L = 0
  while ((getline ln < LOGO) > 0) { row[++L] = ln; if (length(ln) > W) W = length(ln) }
  close(LOGO)
  if (!FPS) FPS = 30
  if (MODE == "static" || MODE == "final") { for (r = 1; r <= L; r++) stage[r] = 3; printf "%s", frame(-999, 0); exit }
  if (MODE == "rise") {
    N = int(1.8 * FPS)
    for (f = 0; f < N; f++) {
      t = f / FPS
      for (r = 1; r <= L; r++) {
        start = (L - r) / L * 0.8                                # the bottom climbs first
        p = clamp((t - start) / 0.55, 0, 1)
        stage[r] = (p <= 0) ? 0 : (p < 0.35 ? 1 : (p < 0.8 ? 2 : 3))
      }
      printf "%s%c", frame(-999, 0), 30
    }
    for (r = 1; r <= L; r++) stage[r] = 3
    printf "%s", frame(-999, 0)
    exit
  }
  if (MODE == "shift") {
    N = int(4 * FPS)                                             # 4 s loop
    for (r = 1; r <= L; r++) stage[r] = 3
    for (f = 0; f < N; f++) {
      ph = f / N
      band = -12 + ph * (W + 2 * L + 24)
      if (ph > 0.75) band = -999                                 # rest, so the loop joins the final look
      printf "%s%c", frame(band, sinp(ph * 2)), 30
    }
    exit
  }
}
