"""Pure first-visible-presentation oracle; no GTK or display side effects."""


def classify(opacity, pixels, backdrop, surface, seen):
    if opacity not in (0, 1):
        raise AssertionError(f'Whole-window opacity changed during local slide: {opacity}')
    if opacity == 0:
        if seen or any(pixel != backdrop for pixel in pixels):
            raise AssertionError(f'Hidden popup changed presented backdrop: {pixels!r}')
        return 'hidden'
    if not seen and all(pixel == backdrop for pixel in pixels):
        # X opacity publication can precede compositor presentation. Only the
        # unchanged backdrop is permitted during that interval, not arbitrary
        # foreign pixels until a later correct frame happens to arrive.
        return 'pending-presentation'
    if any(pixel != surface for pixel in pixels):
        raise AssertionError(f'First/ongoing opaque presentation contains foreign or blended pixels: {pixels!r}')
    return 'visible'
