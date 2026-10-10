# carpatic-intro-play. `make` builds the real player (needs libx11-dev libxext-dev); `make host` builds the display-less test binary (dump, selftest).
CC ?= cc
CFLAGS ?= -O2 -Wall -Wextra
SRC = intro_main.c intro_scene.c
all: carpatic-intro-play
carpatic-intro-play: $(SRC) intro_scene.h
	$(CC) $(CFLAGS) -DHAVE_X11 -o $@ $(SRC) -lX11 -lXext -lm
host: intro-host
intro-host: $(SRC) intro_scene.h
	$(CC) $(CFLAGS) -o $@ $(SRC) -lm
install: carpatic-intro-play
	install -D -m 755 carpatic-intro-play $(DESTDIR)/usr/local/bin/carpatic-intro-play
clean:
	rm -f carpatic-intro-play intro-host
