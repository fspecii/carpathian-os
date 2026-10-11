"""Delete only thumbnail caches using anchored, no-follow directory descriptors.

Call on a worker. Symlinks at the two cleanup targets are unlinked; symlinks in
parents inside the declared cache are refused. The declared root may be a link
(e.g. relocated home/cache); it is resolved once before anchoring the descriptor.
"""
from dataclasses import dataclass
import os
import shutil
import stat


@dataclass(frozen=True)
class CleanupResult:
    failed: tuple = ()


def cache_directory():
    configured = os.environ.get('XDG_CACHE_HOME', '')
    path = configured if os.path.isabs(configured) else os.path.join(os.path.expanduser('~'), '.cache')
    if not os.path.isabs(path):
        raise ValueError('Invalid cache directory')
    resolved = os.path.realpath(path)
    if resolved == '/':
        raise ValueError('Invalid cache directory')
    return resolved


def _open_directory(path):
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    fd = os.open('/', flags)
    try:
        for component in path.split('/'):
            if not component:
                continue
            new_fd = os.open(component, flags, dir_fd=fd)
            os.close(fd)
            fd = new_fd
        return fd
    except Exception:
        os.close(fd)
        raise


def _remove(parent, name):
    try:
        info = os.stat(name, dir_fd=parent, follow_symlinks=False)
    except FileNotFoundError:
        return
    if stat.S_ISDIR(info.st_mode):
        if not shutil.rmtree.avoids_symlink_attacks:
            raise RuntimeError('Safe directory removal is unavailable')
        shutil.rmtree(name, dir_fd=parent)
    else:
        os.unlink(name, dir_fd=parent)
    # Concurrent regeneration is not reported as successful cleanup.
    try:
        os.stat(name, dir_fd=parent, follow_symlinks=False)
    except FileNotFoundError:
        return
    raise OSError('Thumbnail cache was recreated during cleanup')


def clear_thumbnails():
    try:
        path = cache_directory()
        root = _open_directory(path)
    except FileNotFoundError:
        return CleanupResult()
    except Exception:
        return CleanupResult(('cache directory',))
    failed = []
    try:
        try:
            _remove(root, 'thumbnails')
        except Exception:
            failed.append('thumbnails')
        parent = None
        try:
            parent = os.open('carpatic', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=root)
            _remove(parent, 'thumbs')
        except FileNotFoundError:
            pass
        except Exception:
            failed.append('Carpathian thumbnails')
        finally:
            if parent is not None:
                os.close(parent)
    finally:
        os.close(root)
    return CleanupResult(tuple(failed))


def status_text(result):
    if isinstance(result, Exception):
        return 'Thumbnail cleanup failed. Try again or check the cache folder permissions in Files.'
    if result.failed:
        return 'Could not clear ' + ', '.join(result.failed) + '. Check folder permissions or linked cache folders in Files, then try again.'
    return 'Cached thumbnails cleared. They are made again when needed.'
