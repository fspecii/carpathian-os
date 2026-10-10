//! Filesystem and signal notifications integrated with the blocking X11 loop.
use std::{
    collections::HashMap,
    io,
    os::fd::{AsRawFd, FromRawFd, OwnedFd},
    path::PathBuf,
    sync::atomic::{AtomicI32, Ordering},
};
static SIGNAL_FD: AtomicI32 = AtomicI32::new(-1);
extern "C" fn reload_signal(_: libc::c_int) {
    let fd = SIGNAL_FD.load(Ordering::Relaxed);
    if fd >= 0 {
        // write(2) is async-signal-safe; a full nonblocking pipe already means pending reload.
        unsafe {
            let saved_errno = *libc::__errno_location();
            libc::write(fd, [1u8].as_ptr().cast(), 1);
            *libc::__errno_location() = saved_errno;
        }
    }
}

pub struct Watch {
    input: OwnedFd,
    names: HashMap<i32, Vec<Vec<u8>>>,
    signal_read: OwnedFd,
    _signal_write: OwnedFd,
}
impl Watch {
    pub fn new(dirs: &[(PathBuf, &[&str])]) -> io::Result<Self> {
        let fd = unsafe { libc::inotify_init1(libc::IN_NONBLOCK | libc::IN_CLOEXEC) };
        if fd < 0 {
            return Err(io::Error::last_os_error());
        }
        let input = unsafe { OwnedFd::from_raw_fd(fd) };
        let mut names: HashMap<i32, Vec<Vec<u8>>> = HashMap::new();
        for (dir, files) in dirs {
            std::fs::create_dir_all(dir)?;
            let path = std::ffi::CString::new(dir.as_os_str().as_encoded_bytes())?;
            let result = unsafe {
                libc::inotify_add_watch(
                    fd,
                    path.as_ptr(),
                    libc::IN_CLOSE_WRITE | libc::IN_MOVED_TO | libc::IN_DELETE,
                )
            };
            if result < 0 {
                return Err(io::Error::last_os_error());
            }
            names
                .entry(result)
                .or_default()
                .extend(files.iter().map(|s| s.as_bytes().to_vec()));
        }
        let mut pipe = [-1; 2];
        if unsafe { libc::pipe2(pipe.as_mut_ptr(), libc::O_NONBLOCK | libc::O_CLOEXEC) } < 0 {
            return Err(io::Error::last_os_error());
        }
        let signal_read = unsafe { OwnedFd::from_raw_fd(pipe[0]) };
        let signal_write = unsafe { OwnedFd::from_raw_fd(pipe[1]) };
        SIGNAL_FD.store(pipe[1], Ordering::Relaxed);
        let mut action: libc::sigaction = unsafe { std::mem::zeroed() };
        action.sa_sigaction = reload_signal as *const () as usize;
        unsafe {
            libc::sigemptyset(&mut action.sa_mask);
            if libc::sigaction(libc::SIGUSR1, &action, std::ptr::null_mut()) < 0 {
                SIGNAL_FD.store(-1, Ordering::Relaxed);
                return Err(io::Error::last_os_error());
            }
        }
        Ok(Self {
            input,
            names,
            signal_read,
            _signal_write: signal_write,
        })
    }

    pub fn wait(&self, x11_fd: i32, timeout: Option<std::time::Duration>) -> io::Result<bool> {
        let mut fds = [
            libc::pollfd {
                fd: x11_fd,
                events: libc::POLLIN,
                revents: 0,
            },
            libc::pollfd {
                fd: self.input.as_raw_fd(),
                events: libc::POLLIN,
                revents: 0,
            },
            libc::pollfd {
                fd: self.signal_read.as_raw_fd(),
                events: libc::POLLIN,
                revents: 0,
            },
        ];
        let millis = timeout
            .map(|d| d.as_millis().saturating_add(1).min(i32::MAX as u128) as i32)
            .unwrap_or(-1);
        let result = unsafe { libc::poll(fds.as_mut_ptr(), fds.len() as libc::nfds_t, millis) };
        if result < 0 {
            let e = io::Error::last_os_error();
            if e.kind() == io::ErrorKind::Interrupted {
                return Ok(false);
            }
            return Err(e);
        }
        if fds[0].revents & (libc::POLLERR | libc::POLLHUP | libc::POLLNVAL) != 0 {
            return Err(io::Error::new(
                io::ErrorKind::ConnectionAborted,
                "X11 connection closed",
            ));
        }
        let mut changed = false;
        for (index, entry) in fds[1..].iter().enumerate() {
            if entry.revents & libc::POLLIN != 0 {
                let mut buffer = [0u8; 4096];
                loop {
                    let count =
                        unsafe { libc::read(entry.fd, buffer.as_mut_ptr().cast(), buffer.len()) };
                    if count <= 0 {
                        break;
                    }
                    if index == 1 {
                        changed = true; // explicit SIGUSR1
                    } else {
                        changed |= self.config_changed(&buffer[..count as usize]);
                    }
                }
            }
        }
        Ok(changed)
    }

    fn config_changed(&self, bytes: &[u8]) -> bool {
        let header = std::mem::size_of::<libc::inotify_event>();
        let mut offset = 0;
        while offset + header <= bytes.len() {
            // The byte buffer has no alignment guarantee.
            let event = unsafe {
                std::ptr::read_unaligned(bytes[offset..].as_ptr().cast::<libc::inotify_event>())
            };
            if event.mask & libc::IN_Q_OVERFLOW != 0 {
                return true;
            }
            let end = offset + header + event.len as usize;
            if end > bytes.len() {
                return true;
            }
            let name = bytes[offset + header..end]
                .split(|b| *b == 0)
                .next()
                .unwrap_or_default();
            if self
                .names
                .get(&event.wd)
                .is_some_and(|files| files.iter().any(|file| file == name))
            {
                return true;
            }
            offset = end;
        }
        false
    }
}
impl Drop for Watch {
    fn drop(&mut self) {
        SIGNAL_FD.store(-1, Ordering::Relaxed);
    }
}
