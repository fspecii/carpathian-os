"""Owned MIT-SHM root snapshots; correctness instrumentation, not FPS."""
import ctypes as c
import os
from pathlib import Path


class Header(c.Structure):
    _fields_ = [('width', c.c_int), ('height', c.c_int), ('xoffset', c.c_int),
                ('format', c.c_int), ('data', c.c_void_p), ('byte_order', c.c_int),
                ('bitmap_unit', c.c_int), ('bitmap_bit_order', c.c_int),
                ('bitmap_pad', c.c_int), ('depth', c.c_int),
                ('bytes_per_line', c.c_int), ('bits_per_pixel', c.c_int),
                ('red_mask', c.c_ulong), ('green_mask', c.c_ulong), ('blue_mask', c.c_ulong)]


class Segment(c.Structure):
    _fields_ = [('shmseg', c.c_ulong), ('shmid', c.c_int),
                ('shmaddr', c.c_void_p), ('readOnly', c.c_int)]


class XError(c.Structure):
    _fields_ = [('type', c.c_int), ('display', c.c_void_p),
                ('resourceid', c.c_ulong), ('serial', c.c_ulong),
                ('error_code', c.c_ubyte), ('request_code', c.c_ubyte),
                ('minor_code', c.c_ubyte)]


class Snapshot:
    def __init__(self, display, width, height):
        if (os.environ.get('DISPLAY') != ':0' or 'WAYLAND_DISPLAY' in os.environ
                or os.environ.get('CARPATIC_VM_TEST') != '1'
                or not Path('/etc/alpine-release').exists()):
            raise RuntimeError('Shared capture requires marked isolated Alpine Xorg')
        self.x, self.display = display.x, display
        self.ext = c.CDLL('libXext.so.6')
        self.lib = c.CDLL(None, use_errno=True)
        self.segment = Segment(shmid=-1)
        self.image = None
        self.attached = False
        self.segment_marked = False
        ptr = c.c_void_p
        for library, name, result, args in (
            (self.x, 'XDefaultVisual', ptr, [ptr, c.c_int]),
            (self.x, 'XDefaultDepth', c.c_int, [ptr, c.c_int]),
            (self.ext, 'XShmQueryExtension', c.c_int, [ptr]),
            (self.ext, 'XShmCreateImage', ptr, [ptr, ptr, c.c_uint, c.c_int, ptr, c.POINTER(Segment), c.c_uint, c.c_uint]),
            (self.ext, 'XShmAttach', c.c_int, [ptr, c.POINTER(Segment)]),
            (self.ext, 'XShmDetach', c.c_int, [ptr, c.POINTER(Segment)]),
            (self.ext, 'XShmGetImage', c.c_int, [ptr, c.c_ulong, ptr, c.c_int, c.c_int, c.c_ulong]),
            (self.lib, 'shmget', c.c_int, [c.c_int, c.c_size_t, c.c_int]),
            (self.lib, 'shmat', ptr, [c.c_int, ptr, c.c_int]),
            (self.lib, 'shmdt', c.c_int, [ptr]),
            (self.lib, 'shmctl', c.c_int, [c.c_int, c.c_int, ptr]),
        ):
            fn = getattr(library, name)
            fn.restype, fn.argtypes = result, args
        try:
            if not self.ext.XShmQueryExtension(display.handle):
                raise RuntimeError('MIT-SHM unavailable')
            self.image = self.ext.XShmCreateImage(
                display.handle, self.x.XDefaultVisual(display.handle, 0),
                self.x.XDefaultDepth(display.handle, 0), 2, None,
                c.byref(self.segment), width, height)
            if not self.image:
                raise RuntimeError('XShmCreateImage failed')
            header = c.cast(self.image, c.POINTER(Header)).contents
            if (header.bits_per_pixel != 32 or header.byte_order != 0
                    or (header.red_mask, header.green_mask, header.blue_mask)
                    != (0xff0000, 0xff00, 0xff)):
                raise RuntimeError('Unsupported shared image layout')
            self.size = header.bytes_per_line * height
            self.segment.shmid = self.lib.shmget(0, self.size, 0o1000 | 0o600)
            if self.segment.shmid < 0:
                raise OSError(c.get_errno(), 'shmget')
            address = self.lib.shmat(self.segment.shmid, None, 0)
            if address == c.c_void_p(-1).value:
                raise OSError(c.get_errno(), 'shmat')
            self.segment.shmaddr = address
            header.data = address
            def attach():
                accepted = self.ext.XShmAttach(display.handle, c.byref(self.segment))
                # Track an issued attachment even if the following sync fails.
                self.attached = bool(accepted)
                return accepted
            self._request(attach, 'XShmAttach')
            # Kernel removes the owned segment after both attachments close,
            # including abnormal process exit. Never touch other segments.
            if self.lib.shmctl(self.segment.shmid, 0, None):
                raise OSError(c.get_errno(), 'IPC_RMID')
            self.segment_marked = True
            self.header = header
        except BaseException as original:
            try:
                self.close()
            except BaseException as cleanup:
                original.add_note(f'Shared capture cleanup also failed: {cleanup}')
            raise

    def _request(self, operation, name, flush_before=True, synchronize=True):
        # Flush older requests before attributing asynchronous errors to ours.
        if flush_before:
            self.display.sync()
        handler_type = c.CFUNCTYPE(c.c_int, c.c_void_p, c.c_void_p)
        errors = []
        def record_error(_display, event):
            if event:
                error = c.cast(event, c.POINTER(XError)).contents
                errors.append((error.error_code, error.request_code, error.minor_code))
            else:
                errors.append(('unknown',))
            return 0
        handler = handler_type(record_error)
        self.x.XSetErrorHandler.restype = c.c_void_p
        self.x.XSetErrorHandler.argtypes = [c.c_void_p]
        old_handler = self.x.XSetErrorHandler(c.cast(handler, c.c_void_p))
        try:
            accepted = operation()
            if synchronize:
                self.display.sync()
        finally:
            self.x.XSetErrorHandler(old_handler)
        if not accepted or errors:
            raise RuntimeError(f'{name} rejected by server: X11 errors {errors}')

    def capture(self, x=0, y=0):
        # libXext XShmGetImage waits for _XReply before returning. Its reply
        # drains earlier requests and delivers request errors with our handler
        # installed; extra XSync round trips add no completion guarantee.
        self._request(lambda: self.ext.XShmGetImage(
            self.display.handle, self.display.root, self.image, x, y, 0xffffffff),
            'XShmGetImage', flush_before=False, synchronize=False)
        return c.string_at(self.segment.shmaddr, self.size), self.header.bytes_per_line

    def close(self):
        failures = []
        def attempt(operation):
            try:
                operation()
            except BaseException as error:
                failures.append(error)
        if self.attached:
            self.attached = False
            attempt(lambda: self._request(lambda: self.ext.XShmDetach(
                self.display.handle, c.byref(self.segment)), 'XShmDetach', flush_before=False))
        if self.image:
            image, self.image = self.image, None
            c.cast(image, c.POINTER(Header)).contents.data = None
            attempt(lambda: self.x.XDestroyImage(image))
        if self.segment.shmaddr:
            address, self.segment.shmaddr = self.segment.shmaddr, None
            def detach_local():
                if self.lib.shmdt(address):
                    raise OSError(c.get_errno(), 'shmdt')
            attempt(detach_local)
        if self.segment.shmid >= 0:
            identifier, self.segment.shmid = self.segment.shmid, -1
            def remove_segment():
                if self.lib.shmctl(identifier, 0, None):
                    raise OSError(c.get_errno(), 'IPC_RMID')
            if not self.segment_marked:
                attempt(remove_segment)
        if failures:
            for extra in failures[1:]:
                failures[0].add_note(f'Additional shared capture cleanup failure: {extra}')
            raise failures[0]
