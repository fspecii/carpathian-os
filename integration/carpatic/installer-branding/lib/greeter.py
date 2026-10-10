#!/usr/bin/env python3
"""Carpathian installer identity. Pure stdlib, one-cell UTF-8, no frame subprocesses."""
import argparse
from functools import lru_cache
import math
import os
from pathlib import Path
import select
import signal
import sys
import termios
import time
import unicodedata

ASSETS = Path(__file__).resolve().parent.parent / 'assets'
RESET = '\033[0m'


@lru_cache(maxsize=8)
def read_asset(name):
    rows = (ASSETS / name).read_text(encoding='utf-8').splitlines()
    for row in rows:
        for ch in row:
            if not ch.isprintable() or unicodedata.combining(ch) or unicodedata.east_asian_width(ch) in ('W', 'F'):
                raise ValueError('Brand assets must contain single-cell printable text')
    return tuple(rows)


@lru_cache(maxsize=8)
def composition(columns, rows):
    wide = columns >= 92 and rows >= 29
    mountains = read_asset('mountain-full.txt' if wide else 'mountain-compact.txt')
    word = read_asset('wordmark-wide.txt' if wide else 'wordmark-compact.txt')
    width = max(map(len, word))
    mountain_width = max(map(len, mountains))
    mountain_left = max(0, (width - mountain_width) // 2)
    lines = [('mountain', ' ' * mountain_left + line.ljust(mountain_width)) for line in mountains]
    lines += [('space', ''), *[('word', line) for line in word], ('space', ''), ('footer', 'OS'.center(width))]
    # Compact spacing retains every selected glyph at 80 columns.
    return lines, width, mountain_width


def paint_line(kind, line, row, elapsed, animate):
    if kind == 'space':
        return ''
    if kind == 'word':
        return '\033[1;36m' + line + RESET
    if kind == 'footer':
        return '\033[37m' + line + RESET
    if animate and elapsed < 1.8:
        # Bottom rows arrive first. Caller supplies mountain-relative row delay.
        progress = (elapsed - row) / .55
        if progress <= 0:
            return ' ' * len(line)
        color = '90' if progress < .4 else '36'
        return f'\033[{color}m' + line + RESET
    # A quiet light band travels across the mountains; wordmark stays legible.
    if not animate:
        return '\033[36m' + line + RESET
    center = (elapsed % 4) / 4 * (len(line) + 20) - 10
    output = []; previous = None
    for i, ch in enumerate(line):
        color = '97' if abs(i - center) < 2 else '96' if abs(i - center) < 5 else '36'
        if ch in '@()|':
            color = '33'
        if color != previous:
            output.append(f'\033[{color}m'); previous = color
        output.append(ch)
    return ''.join(output) + RESET


def frame(columns, rows, elapsed=2, animate=False, tagline='Linux, with a view.', hint='Press Enter to install Carpathian OS'):
    lines, width, _ = composition(columns, rows)
    height = len(lines) + 4
    top = max(0, (rows - height) // 2)
    left = max(0, (columns - width) // 2)
    mountain_count = sum(kind == 'mountain' for kind, _ in lines)
    output = []
    mountain_row = 0
    for index, (kind, text) in enumerate(lines):
        delay = (mountain_count - mountain_row - 1) / max(1, mountain_count) * .8
        if kind == 'mountain': mountain_row += 1
        # Clip a genuinely too-small terminal safely; do not wrap into prompts.
        visible = text[:max(0, columns - left)]
        if top + index >= rows - 4:
            break
        output.append(f'\033[{top + index + 1};{left + 1}H' + paint_line(kind, visible, delay, elapsed, animate))
    for offset, text in ((2, tagline), (4, hint)):
        y = min(rows, top + len(lines) + offset)
        text = text[:columns]
        x = max(0, (columns - len(text)) // 2) + 1
        output.append(f'\033[{y};{x}H\033[37m' + text + RESET)
    return ''.join(output)


def reduced_motion():
    if os.environ.get('CARPATIC_NO_ANIM') == '1' or os.environ.get('TERM') == 'dumb':
        return True
    config = Path(os.environ.get('CARPATIC_CONFIG', str(Path.home() / '.config/carpatic')))
    if (config / 'reduced-motion').exists():
        return True
    try:
        if 'MOTION="reduced"' in (config / 'settings.conf').read_text(): return True
    except FileNotFoundError:
        pass
    try:
        return 'carpatic.reduced-motion' in Path('/proc/cmdline').read_text().split()
    except FileNotFoundError:
        return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--logo', type=Path)  # Compatibility with the wizard call.
    parser.add_argument('--tagline', default='Linux, with a view.')
    parser.add_argument('--hint', default='Press Enter to install Carpathian OS')
    parser.add_argument('--measure', type=Path)
    parser.add_argument('--print-static', action='store_true')
    parser.add_argument('--padding', type=int, default=0)
    parser.add_argument('--dump', type=Path)
    parser.add_argument('--size', default='100x30')
    parser.add_argument('--seconds', type=float, default=6)
    args = parser.parse_args()
    if args.measure:
        print(max(map(len, args.measure.read_text().splitlines()), default=0)); return 0
    if args.print_static:
        content = args.logo.read_text().splitlines() if args.logo else [text for _, text in composition(80, 24)[0]]
        for line in content: print(' ' * max(0, args.padding) + '\033[36m' + line + RESET)
        return 0
    if args.dump:
        columns, rows = map(int, args.size.split('x'))
        if not 20 <= columns <= 240 or not 10 <= rows <= 100 or not 0 < args.seconds <= 12:
            parser.error('Invalid preview size/duration')
        args.dump.mkdir(parents=True, exist_ok=False)
        for index in range(math.ceil(args.seconds * 20)):
            output = '\033[2J' + frame(columns, rows, index / 20, True, args.tagline, args.hint)
            (args.dump / f'{index:04d}.ansi').write_text(output)
        return 0
    if not sys.stdout.isatty():
        return 0
    fd = os.open('/dev/tty', os.O_RDWR)
    saved = termios.tcgetattr(fd)
    handlers = {}
    def stop(signum, _frame):
        raise KeyboardInterrupt(signum)
    try:
        for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            handlers[sig] = signal.signal(sig, stop)
        current = termios.tcgetattr(fd)
        current[3] &= ~(termios.ICANON | termios.ECHO)
        current[6][termios.VMIN] = 0; current[6][termios.VTIME] = 0
        termios.tcsetattr(fd, termios.TCSANOW, current)
        os.write(fd, b'\033[?25l\033[2J')
        start = time.monotonic(); last_size = None; animate = not reduced_motion()
        while True:
            size = os.get_terminal_size(fd)
            if size != last_size:
                os.write(fd, b'\033[2J'); last_size = size
                changed = True
            else:
                changed = False
            if animate or changed:
                output = frame(size.columns, size.lines, time.monotonic() - start, animate, args.tagline, args.hint)
                os.write(fd, output.encode('utf-8'))
            ready, _, _ = select.select([fd], [], [], .05 if animate else .2)
            if ready:
                key = os.read(fd, 32)
                if not key or b'\r' in key or b'\n' in key: return 0
    except KeyboardInterrupt:
        return 130
    finally:
        termios.tcsetattr(fd, termios.TCSANOW, saved)
        os.write(fd, b'\033[0m\033[?25h\033[2J\033[H')
        os.close(fd)
        for sig, handler in handlers.items(): signal.signal(sig, handler)


if __name__ == '__main__':
    raise SystemExit(main())
