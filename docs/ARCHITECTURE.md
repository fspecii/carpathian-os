# Architecture

CarpathianOS combines Alpine Linux, an original Rust X11 window manager and desktop helper applications. The window manager implements master/stack tiling, floating drag and resize, workspaces, focus and window state handling. It uses x11rb for X11 protocol access; its implementation is separate from the legacy C window manager.

Native decorated applications use a common X11 frame containing the client and caption. Application XIDs remain the logical EWMH and protocol identities. Save-set recovery preserves foreign application windows across window-manager failure. Client geometry notifications use root-relative coordinates while framed client placement uses parent-relative coordinates.

Picom provides compositing and configured transitions. Backend policy, reduced motion and animation preferences are shared through the desktop configuration helpers. GTK flyouts prepare their first painted content before reveal and cancel callbacks on destruction. Hierarchy grouping is a correctness mechanism; complete action continuity and resource qualification require runtime tests.

Desktop components under integration/carpatic provide settings, the panel/calendar, reminders, file desktop integration, themes and supporting services. Runtime command names remain compatible with existing Carpatic integrations. Installation scripts assemble these components on Alpine; a complete release must separately qualify provisioning, updates, recovery and supported hardware.

Tests cover host logic, private-Xvfb X11 behavior, native Alpine builds and disposable real-Xorg compositor checks. Settled pixel checks, sampled transitions and performance evidence have different scopes and must be reported separately.
