"""Per-user GVFS Trash operations; call on a worker, never on the GTK thread.

Deleting each top-level trash:/// item lets GVFS handle directories, matching
trashinfo and mounted-volume trash. Do not recurse into virtual descendants:
GVFS intentionally forbids modifying them. No shell or local-trash fallback.
"""
from dataclasses import dataclass
import threading
from typing import Optional
from gi.repository import Gio, GLib


@dataclass(frozen=True)
class TrashResult:
    count: Optional[int] = None
    failed: int = 0
    unavailable: bool = False


def _children(root, cancel):
    enum = root.enumerate_children('standard::name,standard::type,standard::is-symlink',
                                  Gio.FileQueryInfoFlags.NOFOLLOW_SYMLINKS, cancel)
    try:
        while True:
            info = enum.next_file(cancel)
            if info is None:
                break
            yield enum.get_child(info)
    finally:
        enum.close(None)


def inspect_trash(*, root=None, cancellable=None, timeout=30):
    root = root if root is not None else Gio.File.new_for_uri('trash:///')
    timer = None
    if cancellable is None:
        cancellable = Gio.Cancellable()
        timer = threading.Timer(timeout, cancellable.cancel)
        timer.daemon = True
        timer.start()
    try:
        return TrashResult(count=sum(1 for _ in _children(root, cancellable)))
    except Exception:
        return TrashResult(unavailable=True)
    finally:
        if timer is not None:
            timer.cancel()


def empty_trash(*, root=None, timeout=30):
    root = root if root is not None else Gio.File.new_for_uri('trash:///')
    cancel = Gio.Cancellable()
    timer = threading.Timer(timeout, cancel.cancel)
    timer.daemon = True
    timer.start()
    failed = 0
    try:
        # Snapshot the top-level names before mutation. New arrivals are left
        # alone and discovered by the final enumeration rather than deleted.
        items = list(_children(root, cancel))
        for item in items:
            try:
                if not item.delete(cancel):
                    failed += 1
            except GLib.Error as error:
                if not error.matches(Gio.io_error_quark(), Gio.IOErrorEnum.NOT_FOUND):
                    failed += 1
            except Exception:
                failed += 1
        result = inspect_trash(root=root, cancellable=cancel)
        return TrashResult(result.count, failed, result.unavailable)
    except Exception:
        return TrashResult(failed=failed, unavailable=True)
    finally:
        timer.cancel()


def status_text(result):
    if isinstance(result, Exception) or result.unavailable:
        return 'Trash is unavailable. Open Files → Trash, or try Refresh.'
    if result.failed:
        return f'{result.count} item(s) remain. Some items could not be deleted; open Files → Trash to check permissions.'
    return 'The Trash is empty' if result.count == 0 else f'{result.count} item(s) in the Trash'
