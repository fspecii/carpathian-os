use x11rb::protocol::randr::ConnectionExt as _;
mod decoration;
mod dropzones;
mod monitor;
mod runtime;
mod tray;
use carpatic_wm::config::{Binding, Config, MouseBinding, Rule};
use carpatic_wm::{clamp, weighted_tile, Rect};
use decoration::{BarAction, BarHit, Button, Icon, Label, Renderer};
use std::time::{Duration, Instant};
use std::{error::Error, process::Command};
use std::{os::fd::AsRawFd, path::PathBuf};
use x11rb::{
    connection::Connection,
    protocol::{xproto::*, Event},
    rust_connection::RustConnection,
    wrapper::ConnectionExt as _,
    CURRENT_TIME, NONE,
};

type Result<T> = std::result::Result<T, Box<dyn Error>>;
const SUPER: u16 = 64;

x11rb::atom_manager! {
    pub Atoms: AtomsCookie {
        WM_PROTOCOLS, WM_DELETE_WINDOW, WM_STATE, WM_TAKE_FOCUS, WM_TRANSIENT_FOR,
        UTF8_STRING, _NET_SUPPORTED, _NET_SUPPORTING_WM_CHECK, _NET_WM_NAME, _CARPATIC_ANIMATION,
        _CARPATIC_ANIMATION_PREPARE, _CARPATIC_SNAP, _CARPATIC_SNAP_SAVED, _NET_WM_CM_S0, _CARPATIC_FRAME_GEOMETRY,
        _NET_CLIENT_LIST, _NET_ACTIVE_WINDOW, _NET_NUMBER_OF_DESKTOPS, _NET_CURRENT_DESKTOP,
        _NET_DESKTOP_NAMES, _NET_WM_DESKTOP, _NET_WM_STATE, _NET_WM_STATE_FULLSCREEN,
        _NET_WM_WINDOW_TYPE, _NET_WM_WINDOW_TYPE_DIALOG, _NET_CLOSE_WINDOW, _NET_WORKAREA, _NET_WM_PID, _CARPATIC_FLOATING, _CARPATIC_BUTTONS, _CARPATIC_CLIENT, _NET_WM_STATE_HIDDEN, WM_CHANGE_STATE, _MOTIF_WM_HINTS, _GTK_FRAME_EXTENTS, _NET_WM_STATE_MAXIMIZED_VERT, _NET_WM_STATE_MAXIMIZED_HORZ, _CARPATIC_DRAGGING, _CARPATIC_TAGS, _CARPATIC_LAYOUT, _NET_WM_WINDOW_TYPE_DOCK, _NET_WM_WINDOW_TYPE_DESKTOP, _NET_WM_STRUT_PARTIAL, _NET_WM_STRUT, _NET_WM_MOVERESIZE, _CARPATIC_DROP_TARGET, _CARPATIC_MAX_SAVED, _CARPATIC_FAKE_FULLSCREEN, _NET_WM_STATE_ABOVE, _NET_CLIENT_LIST_STACKING, _CARPATIC_MINLIST, _CARPATIC_DROP_ZONE, _NET_WM_STATE_DEMANDS_ATTENTION, _NET_FRAME_EXTENTS, _NET_REQUEST_FRAME_EXTENTS, _CARPATIC_URGENT_TAGS, _CARPATIC_CONFIG_SERIAL, _NET_SHOWING_DESKTOP, _CARPATIC_MINIMIZED_AT, _CARPATIC_PRESSED_BUTTON, _NET_WM_ICON, _CARPATIC_FULLSCREEN_ORIGIN,
    }
}

#[derive(Clone)]
struct AppSpace {
    client: Window,
    desktop: u32,
    tags: u32,
    origin_desktop: u32,
    monitor: usize,
    view: u32,
}

#[derive(Clone, Copy, PartialEq, Eq)]
struct FrameShapeKey {
    frame: Window,
    width: u32,
    height: u32,
    border: u32,
    title: u32,
    radius: u32,
    square: bool,
}

struct Client {
    id: Window,
    desktop: u32,
    tags: u32,
    monitor: usize,
    dock: bool,
    floating: bool,
    fullscreen: bool,
    fake_fullscreen: bool,
    floating_rect: Rect,
    applied: Option<Rect>,
    applied_border: Option<u32>,
    applied_extents: Option<[u32; 4]>,
    mapped: bool,
    ignored_unmaps: u32,
    titlebar: Window,
    frame: Option<Window>,
    original_border: u16,
    depth: u8,
    shape_dirty: bool,
    frame_shape: Option<FrameShapeKey>,
    chrome_surface: Option<(u32, u32)>,
    title: String,
    icon: Option<Icon>,
    minimized: bool,
    min_stamp: u32,
    max_saved: Option<(Rect, bool)>,
    snap_saved: Option<(Rect, bool)>,
    snap_maximized: bool,
    snap_constrained: bool,
    chrome_dirty: bool,
    hover: Option<Button>,
    pressed: Option<Button>,
    has_csd: bool,
    weight: f32,
    terminal: bool,
    noswallow: bool,
    above: bool,
    pid: u32,
    swallowed_by: Option<Window>,
    swallow_parent: Option<Window>,
    size_hints: Option<x11rb::properties::WmSizeHints>,
    input: bool,
    urgent: bool,
    tile_slot: Option<usize>,
}

impl Client {
    fn caption_height(&self) -> u32 {
        self.applied_extents.map_or(1, |extents| extents[2].max(1))
    }

    fn border_pixel(&self, color: u32) -> u32 {
        opaque_border_pixel(self.depth, color)
    }

    fn surface(&self) -> Window {
        self.frame.unwrap_or(self.id)
    }
}

struct Drag {
    id: Window,
    x: i32,
    y: i32,
    rect: Rect,
    resize: bool,
    pending_float: bool,
    edges: u8,
    original_floating: bool,
    original: DragOrigin,
    moved: bool,
    target: Option<dropzones::Target>,
}

struct DragOrigin {
    rect: Rect,
    monitor: usize,
    tags: u32,
    desktop: u32,
    max_saved: Option<(Rect, bool)>,
    snap_constrained: bool,
    snap_maximized: bool,
    tile_slot: Option<usize>,
    order: Vec<Window>,
    active_monitor: usize,
}

struct Bar {
    id: Window,
    monitor: usize,
    hits: Vec<BarHit>,
}

struct Wm {
    conn: RustConnection,
    root: Window,
    support: Window,
    atoms: Atoms,
    area: Rect,
    clients: Vec<Client>,
    desktop_surfaces: Vec<Window>,
    focused: Option<Window>,
    desktop: u32,
    master: u32,
    keys: Vec<(u8, u32)>,
    drag: Option<Drag>,
    running: bool,
    config: Config,
    config_dir: PathBuf,
    renderer: Renderer,
    watch: runtime::Watch,
    bindings: Vec<Binding>,
    rules: Vec<Rule>,
    mouse_bindings: Vec<MouseBinding>,
    drop_overlay: Window,
    last_time: u32,
    last_pointer: (i16, i16),
    config_serial: u32,
    min_clock: u32,
    showing_desktop: bool,
    app_spaces: Vec<AppSpace>,
    priority_overlays: Vec<Window>,
    lock_overlays: Vec<Window>,
    last_title_click: Option<(Window, u32)>,
    pressed_button: Option<(Window, Button)>,
    desktop_menu_press: Option<(i16, i16)>,
    animation_expiry: Vec<(Window, Instant)>,
    deferred_unmaps: Vec<(Window, Instant)>,

    monitors: Vec<monitor::Monitor>,
    active_monitor: usize,
    bars: Vec<Bar>,
    tray: tray::Tray,
}

impl Wm {
    fn new() -> Result<Self> {
        if std::env::var("CARPATIC_SESSION").as_deref() != Ok("1") {
            return Err("Run through carpatic-rust-session, or set CARPATIC_SESSION=1 on a private test display.".into());
        }
        let (conn, screen) = x11rb::connect(None)?;
        let s = &conn.setup().roots[screen];
        let root = s.root;
        let area = Rect {
            x: 0,
            y: 0,
            width: s.width_in_pixels.into(),
            height: s.height_in_pixels.into(),
        };
        conn.change_window_attributes(
            root,
            &ChangeWindowAttributesAux::new().event_mask(
                EventMask::SUBSTRUCTURE_REDIRECT
                    | EventMask::SUBSTRUCTURE_NOTIFY
                    | EventMask::STRUCTURE_NOTIFY
                    | EventMask::PROPERTY_CHANGE
                    | EventMask::BUTTON_PRESS
                    | EventMask::BUTTON_RELEASE,
            ),
        )?
        .check()
        .map_err(|_| "Another window manager already owns this display")?;
        let cursor_font = conn.generate_id()?;
        let cursor = conn.generate_id()?;
        conn.open_font(cursor_font, b"cursor")?;
        conn.create_glyph_cursor(
            cursor,
            cursor_font,
            cursor_font,
            68,
            69,
            0,
            0,
            0,
            65535,
            65535,
            65535,
        )?;
        conn.change_window_attributes(root, &ChangeWindowAttributesAux::new().cursor(cursor))?;
        conn.close_font(cursor_font)?;
        // An explicit passive grab keeps desktop clicks available when another
        // session component selects XI2 events on the root window.
        for lock in [0u16, 2, 16, 18] {
            conn.grab_button(
                true,
                root,
                EventMask::BUTTON_PRESS | EventMask::BUTTON_RELEASE,
                GrabMode::SYNC,
                GrabMode::ASYNC,
                NONE,
                NONE,
                ButtonIndex::M3,
                ModMask::from(lock),
            )?
            .check()?;
        }
        let atoms = Atoms::new(&conn)?.reply()?;
        let support = conn.generate_id()?;
        conn.create_window(
            0,
            support,
            root,
            -1,
            -1,
            1,
            1,
            0,
            WindowClass::INPUT_OUTPUT,
            0,
            &CreateWindowAux::new(),
        )?
        .check()?;
        let config_dir = std::env::var_os("CARPATIC_CONFIG_DIR")
            .map(PathBuf::from)
            .unwrap_or_else(|| {
                PathBuf::from(std::env::var("XDG_CONFIG_HOME").unwrap_or_else(|_| {
                    format!("{}/.config", std::env::var("HOME").unwrap_or_default())
                }))
                .join("dwm-titus")
            });
        let config = load_config(&config_dir);
        let renderer = Renderer::new(&config);
        let watch = runtime::Watch::new(&[
            (
                config_dir.clone(),
                &["themes.toml", "hotkeys.toml", "window-rules.toml"],
            ),
            (
                config_dir.parent().unwrap_or(&config_dir).join("carpatic"),
                &["dwm-font"],
            ),
        ])?;
        let mut monitors = monitor::discover(&conn, root, area, config.default_layout == "float");
        for m in &mut monitors {
            m.all_mask = (1 << config.workspaces) - 1;
        }
        let tray = tray::Tray::new(&conn, root)?;
        let drop_overlay = conn.generate_id()?;
        conn.create_window(
            0,
            drop_overlay,
            root,
            0,
            0,
            1,
            1,
            0,
            WindowClass::INPUT_OUTPUT,
            0,
            &CreateWindowAux::new().override_redirect(1),
        )?;
        use x11rb::protocol::shape::{ConnectionExt as _, SK, SO};
        conn.shape_rectangles(
            SO::SET,
            SK::INPUT,
            ClipOrdering::UNSORTED,
            drop_overlay,
            0,
            0,
            &[],
        )?;
        let pointer = conn.query_pointer(root)?.reply()?;
        let mut wm = Self {
            conn,
            root,
            support,
            atoms,
            area,
            clients: Vec::new(),
            desktop_surfaces: Vec::new(),
            focused: None,
            desktop: 0,
            master: 55,
            keys: Vec::new(),
            drag: None,
            running: true,
            renderer,
            watch,
            config,
            config_dir,
            bindings: Vec::new(),
            rules: Vec::new(),
            mouse_bindings: Vec::new(),
            drop_overlay,
            last_time: CURRENT_TIME,
            last_pointer: (pointer.root_x, pointer.root_y),
            config_serial: 0,
            min_clock: 0,
            showing_desktop: false,
            app_spaces: Vec::new(),
            priority_overlays: Vec::new(),
            lock_overlays: Vec::new(),
            last_title_click: None,
            pressed_button: None,
            desktop_menu_press: None,
            animation_expiry: Vec::new(),
            deferred_unmaps: Vec::new(),
            monitors,
            active_monitor: 0,
            bars: Vec::new(),
            tray,
        };
        let _ = wm.conn.randr_select_input(
            wm.root,
            x11rb::protocol::randr::NotifyMask::SCREEN_CHANGE
                | x11rb::protocol::randr::NotifyMask::CRTC_CHANGE
                | x11rb::protocol::randr::NotifyMask::OUTPUT_CHANGE,
        );
        wm.load_aux_config();
        wm.publish()?;
        // The root survives WM restarts. Publish this instance's counter before
        // adoption so a stale predecessor value cannot mask its first reload.
        wm.conn.change_property32(
            PropMode::REPLACE,
            root,
            wm.atoms._CARPATIC_CONFIG_SERIAL,
            AtomEnum::CARDINAL,
            &[wm.config_serial],
        )?;
        wm.client_list()?;
        wm.bind_keys()?;
        let children = wm.conn.query_tree(root)?.reply()?.children;
        for id in children {
            // A root child may disappear after QueryTree while its old session
            // bus shuts down. It must not abort adoption of the surviving apps.
            let attributes = match wm.conn.get_window_attributes(id)?.reply() {
                Ok(attributes) => attributes,
                Err(x11rb::errors::ReplyError::X11Error(error))
                    if error.error_kind == x11rb::protocol::ErrorKind::Window =>
                {
                    continue
                }
                Err(error) => return Err(error.into()),
            };
            let mapped = attributes.map_state == MapState::VIEWABLE;
            // Off-workspace windows remain managed even when deliberately unmapped.
            let managed = matches!(wm.property(id, wm.atoms.WM_STATE).first(), Some(1 | 3));
            if id != support && (mapped || managed) {
                if let Err(error) = wm.manage(id) {
                    let vanished = matches!(error.downcast_ref::<x11rb::errors::ReplyError>(),
                        Some(x11rb::errors::ReplyError::X11Error(error)) if matches!(error.error_kind, x11rb::protocol::ErrorKind::Window | x11rb::protocol::ErrorKind::Drawable));
                    if !vanished {
                        return Err(error);
                    }
                }
            }
        }
        wm.arrange()?;
        wm.conn.change_property32(
            PropMode::REPLACE,
            wm.support,
            wm.atoms._NET_WM_PID,
            AtomEnum::CARDINAL,
            &[std::process::id()],
        )?;
        wm.conn.flush()?;
        println!(
            "carpatic-wm ready: four workspaces, tiling and floating; {} clients adopted",
            wm.clients.len()
        );
        Ok(wm)
    }

    fn window_pid(&self, id: Window) -> u32 {
        let pid = self
            .property(id, self.atoms._NET_WM_PID)
            .first()
            .copied()
            .unwrap_or(0);
        if pid > 0 {
            return pid;
        }
        use x11rb::protocol::res::ConnectionExt as _;
        self.conn
            .res_query_client_ids(&[x11rb::protocol::res::ClientIdSpec {
                client: id,
                mask: x11rb::protocol::res::ClientIdMask::LOCAL_CLIENT_PID,
            }])
            .ok()
            .and_then(|c| c.reply().ok())
            .and_then(|r| r.ids.into_iter().find_map(|id| id.value.first().copied()))
            .unwrap_or(0)
    }

    fn update_workareas(&mut self) -> Result<()> {
        let struts: Vec<_> = self
            .clients
            .iter()
            .filter(|c| c.dock)
            .map(|c| {
                let partial = self.property(c.id, self.atoms._NET_WM_STRUT_PARTIAL);
                if partial.is_empty() {
                    self.property(c.id, self.atoms._NET_WM_STRUT)
                } else {
                    partial
                }
            })
            .collect();
        for m in &mut self.monitors {
            m.work = monitor::reserve(m.area, self.area, &struts);
            if self.config.bar_enabled && !self.clients.iter().any(|c| c.dock) {
                let height = self.config.bar_height.min(m.work.height.saturating_sub(1));
                m.work.y += height as i32;
                m.work.height -= height;
            }
        }
        let mut work = monitor::reserve(self.area, self.area, &struts);
        if self.config.bar_enabled && !self.clients.iter().any(|c| c.dock) {
            let height = self.config.bar_height.min(work.height.saturating_sub(1));
            work.y += height as i32;
            work.height -= height;
        }
        let mut values = Vec::new();
        for _ in 0..self.desktop_count() {
            values.extend([work.x as u32, work.y as u32, work.width, work.height]);
        }
        self.conn.change_property32(
            PropMode::REPLACE,
            self.root,
            self.atoms._NET_WORKAREA,
            AtomEnum::CARDINAL,
            &values,
        )?;
        Ok(())
    }

    fn refresh_monitors(&mut self) -> Result<()> {
        if self.drag.is_some() {
            self.end_drag(true)?;
        }
        let mut monitors = monitor::discover(
            &self.conn,
            self.root,
            self.area,
            self.config.default_layout == "float",
        );
        for m in &mut monitors {
            m.all_mask = (1 << self.config.workspaces) - 1;
            if let Some(old) = self.monitors.iter().find(|old| old.name == m.name) {
                m.desktop = old.desktop;
                m.view = old.view;
                m.previous_view = old.previous_view;
                m.all_view = old.all_view;
                m.previous_all = old.previous_all;
                m.layouts = old.layouts;
                m.masters = old.masters;
                m.factors = old.factors;
            }
        }
        let active_name = self.monitors[self.active_monitor].name;
        self.active_monitor = monitors
            .iter()
            .position(|m| m.name == active_name)
            .unwrap_or(0);
        for c in &mut self.clients {
            let old_name = self.monitors[c.monitor].name;
            let surviving = monitors.iter().position(|m| m.name == old_name);
            c.monitor = surviving.unwrap_or(self.active_monitor);
            if surviving.is_none() && !c.dock {
                c.desktop = monitors[c.monitor].desktop;
                c.tags = monitors[c.monitor].view;
                c.floating_rect = clamp(c.floating_rect, monitors[c.monitor].work);
                self.conn.change_property32(
                    PropMode::REPLACE,
                    c.id,
                    self.atoms._NET_WM_DESKTOP,
                    AtomEnum::CARDINAL,
                    &[c.desktop],
                )?;
                self.conn.change_property32(
                    PropMode::REPLACE,
                    c.id,
                    self.atoms._CARPATIC_TAGS,
                    AtomEnum::CARDINAL,
                    &[c.tags],
                )?;
            }
            c.applied = None;
        }
        self.monitors = monitors;
        self.desktop = self.monitors[self.active_monitor].desktop;
        self.arrange()
    }

    fn window_icon(&self, id: Window) -> Option<Icon> {
        let property = self
            .conn
            .get_property(
                false,
                id,
                self.atoms._NET_WM_ICON,
                AtomEnum::CARDINAL,
                0,
                262144,
            )
            .ok()?
            .reply()
            .ok()?;
        let values: Vec<_> = property.value32()?.collect();
        Icon::from_argb(&values, 24)
    }
    fn window_title(&self, id: Window) -> String {
        for atom in [self.atoms._NET_WM_NAME, u32::from(AtomEnum::WM_NAME)] {
            if let Ok(cookie) = self
                .conn
                .get_property(false, id, atom, AtomEnum::ANY, 0, 1024)
            {
                if let Ok(reply) = cookie.reply() {
                    if !reply.value.is_empty() {
                        return String::from_utf8_lossy(&reply.value)
                            .trim_end_matches('\0')
                            .to_string();
                    }
                }
            }
        }
        String::new()
    }

    fn load_aux_config(&mut self) {
        let read = |name: &str| {
            config_paths(&self.config_dir, name)
                .into_iter()
                .find_map(|p| std::fs::read_to_string(p).ok())
        };
        if read("hotkeys.toml").is_none() {
            self.bindings.clear();
            self.mouse_bindings.clear();
        }
        if read("window-rules.toml").is_none() {
            self.rules.clear();
        }
        if let Some(text) = read("hotkeys.toml") {
            match carpatic_wm::config::parse_mouse_bindings(&text) {
                Ok(bindings) => self.mouse_bindings = bindings,
                Err(e) => eprintln!("Mouse bindings unchanged: {e}"),
            }
            match carpatic_wm::config::parse_bindings(&text) {
                Ok(value) => self.bindings = value,
                Err(e) => eprintln!("Hotkeys unchanged: {e}"),
            }
        }
        if let Some(text) = read("window-rules.toml") {
            match carpatic_wm::config::parse_rules(&text) {
                Ok(value) => self.rules = value,
                Err(e) => eprintln!("Window rules unchanged: {e}"),
            }
        }
    }

    fn reload(&mut self) -> Result<()> {
        if self.drag.is_some() {
            self.end_drag(true)?;
        }
        let file = config_paths(&self.config_dir, "themes.toml")
            .into_iter()
            .find(|p| p.is_file())
            .unwrap_or_else(|| self.config_dir.join("themes.toml"));
        if file.exists() {
            match Config::load(&file) {
                Ok(config) => {
                    if config.default_layout != self.config.default_layout {
                        for m in &mut self.monitors {
                            m.layouts.fill(if config.default_layout == "float" {
                                1
                            } else {
                                0
                            });
                        }
                    }
                    let mut config = policy_overrides(config);
                    if let Ok(font) = std::fs::read_to_string(
                        self.config_dir
                            .parent()
                            .unwrap_or(&self.config_dir)
                            .join("carpatic/dwm-font"),
                    ) {
                        config.font = font.trim().to_string();
                    }
                    self.renderer = Renderer::new(&config);
                    self.config = config;
                    self.reconcile_app_spaces()?;
                    self.desktop = self.desktop.min(self.desktop_count() - 1);
                    let count = self.desktop_count();
                    for c in &mut self.clients {
                        c.desktop = c.desktop.min(count - 1);
                        c.tags &= (1 << count) - 1;
                        if c.tags == 0 {
                            c.tags = 1 << c.desktop;
                        }
                        c.applied = None;
                        c.chrome_dirty = true;
                        self.conn.change_property32(
                            PropMode::REPLACE,
                            c.id,
                            self.atoms._CARPATIC_TAGS,
                            AtomEnum::CARDINAL,
                            &[c.tags],
                        )?;
                        self.conn.change_property32(
                            PropMode::REPLACE,
                            c.id,
                            self.atoms._NET_WM_DESKTOP,
                            AtomEnum::CARDINAL,
                            &[c.desktop],
                        )?;
                    }
                }
                Err(error) => eprintln!("Theme unchanged: {error}"),
            }
        }
        let count = self.desktop_count();
        for m in &mut self.monitors {
            let all = (1 << self.config.workspaces) - 1;
            if m.all_view {
                m.view = all;
            }
            m.all_mask = all;
            m.desktop = m.desktop.min(count - 1);
            m.previous_view &= (1 << count) - 1;
            if m.previous_all {
                m.previous_view = all;
            }
            if m.previous_view == 0 {
                m.previous_view = 1 << m.desktop;
            }
            m.view &= (1 << count) - 1;
            if m.view == 0 {
                m.view = 1 << m.desktop;
            }
        }
        self.load_aux_config();
        self.bind_keys()?;
        for c in &self.clients {
            self.grab_mouse_buttons(c.id)?;
        }
        let children = self.conn.query_tree(self.root)?.reply()?.children;
        for id in children {
            self.track_overlay(id)?;
        }
        self.publish()?;
        self.arrange()?;
        self.config_serial = self.config_serial.wrapping_add(1);
        self.conn.change_property32(
            PropMode::REPLACE,
            self.root,
            self.atoms._CARPATIC_CONFIG_SERIAL,
            AtomEnum::CARDINAL,
            &[self.config_serial],
        )?;
        Ok(())
    }

    fn begin_mouse_drag(&mut self, id: Window, e: &ButtonPressEvent, resize: bool) -> Result<()> {
        self.begin_drag(
            id,
            e.root_x.into(),
            e.root_y.into(),
            if resize { 10 } else { 0 },
            e.time,
        )
    }
    fn begin_drag(&mut self, id: Window, x: i32, y: i32, edges: u8, _time: u32) -> Result<()> {
        if self.drag.is_some() {
            self.end_drag(true)?;
        }
        let Some(c) = self
            .clients
            .iter()
            .find(|c| c.id == id && !c.fullscreen && !c.dock)
        else {
            return Ok(());
        };
        let rect = c.applied.unwrap_or(c.floating_rect);
        let original_floating = c.floating;
        let original = DragOrigin {
            rect,
            monitor: c.monitor,
            tags: c.tags,
            desktop: c.desktop,
            max_saved: c.max_saved,
            snap_constrained: c.snap_constrained,
            snap_maximized: c.snap_maximized,
            tile_slot: c.tile_slot,
            order: self.clients.iter().map(|c| c.id).collect(),
            active_monitor: self.active_monitor,
        };
        let pending_float = !c.floating || c.max_saved.is_some();
        self.focus(id)?;
        let grab = self
            .conn
            .grab_pointer(
                false,
                self.root,
                EventMask::POINTER_MOTION | EventMask::BUTTON_RELEASE,
                GrabMode::ASYNC,
                GrabMode::ASYNC,
                NONE,
                NONE,
                CURRENT_TIME,
            )?
            .reply()?;
        if grab.status != GrabStatus::SUCCESS {
            return Ok(());
        }
        self.grab_drag_keyboard()?;
        self.drag = Some(Drag {
            id,
            x,
            y,
            rect,
            resize: edges != 0,
            pending_float,
            edges,
            original_floating,
            original,
            moved: false,
            target: None,
        });
        self.animation_drag(id, 1)?;
        self.conn.change_property32(
            PropMode::REPLACE,
            self.root,
            self.atoms._CARPATIC_DRAGGING,
            AtomEnum::CARDINAL,
            &[1],
        )?;
        Ok(())
    }
    fn grab_drag_keyboard(&self) -> Result<()> {
        self.conn.grab_keyboard(
            false,
            self.root,
            CURRENT_TIME,
            GrabMode::ASYNC,
            GrabMode::ASYNC,
        )?;
        Ok(())
    }
    fn drag_motion(&mut self, x: i32, y: i32) -> Result<()> {
        let Some(drag) = &self.drag else {
            return Ok(());
        };
        let dx = x - drag.x;
        let dy = y - drag.y;
        if !drag.moved && dx.abs() < 4 && dy.abs() < 4 {
            return Ok(());
        }
        let id = drag.id;
        let resize = drag.resize;
        let place = self.config.drag_place
            && !resize
            && !drag.original_floating
            && self.monitors[drag.original.monitor.min(self.monitors.len() - 1)].layouts
                [drag.original.desktop as usize]
                != 1;
        if !drag.moved {
            let pending = drag.pending_float;
            let original = drag.rect;
            self.drag.as_mut().unwrap().moved = true;
            if pending && !place {
                let index = self.clients.iter().position(|c| c.id == id).unwrap();
                let c = &mut self.clients[index];
                c.tile_slot = Some(index);
                c.floating = true;
                c.max_saved = None;
                c.applied = None;
                self.sync_states(id)?;
                let mut rect = if resize {
                    original
                } else {
                    self.detach_rect(id, original)?
                };
                let anchor_x =
                    (self.drag.as_ref().unwrap().x - original.x).clamp(0, original.width as i32);
                let anchor_y =
                    (self.drag.as_ref().unwrap().y - original.y).clamp(0, original.height as i32);
                rect.x = self.drag.as_ref().unwrap().x
                    - (i64::from(anchor_x) * i64::from(rect.width)
                        / i64::from(original.width.max(1))) as i32;
                let title_height = self.renderer.height(&self.config) as i32;
                let anchor_y = if anchor_y <= title_height {
                    anchor_y
                } else {
                    (i64::from(anchor_y) * i64::from(rect.height)
                        / i64::from(original.height.max(1))) as i32
                };
                rect.y = self.drag.as_ref().unwrap().y - anchor_y;
                let drag = self.drag.as_mut().unwrap();
                drag.rect = rect;
                drag.pending_float = false;
            }
        }
        if !place {
            let drag = self.drag.as_ref().unwrap();
            let mut rect = drag.rect;
            if resize {
                if drag.edges & 1 != 0 {
                    rect.width = (drag.rect.width as i32 - dx).max(64) as u32;
                    rect.x = drag.rect.x + drag.rect.width as i32 - rect.width as i32;
                }
                if drag.edges & 2 != 0 {
                    rect.width = (drag.rect.width as i32 + dx).max(64) as u32;
                }
                if drag.edges & 4 != 0 {
                    rect.height = (drag.rect.height as i32 - dy).max(48) as u32;
                    rect.y = drag.rect.y + drag.rect.height as i32 - rect.height as i32;
                }
                if drag.edges & 8 != 0 {
                    rect.height = (drag.rect.height as i32 + dy).max(48) as u32;
                }
            } else {
                rect.x += dx;
                rect.y += dy;
            }
            let monitor = self
                .monitors
                .iter()
                .position(|m| dropzones::contains(m.area, x, y))
                .unwrap_or(self.clients.iter().find(|c| c.id == id).unwrap().monitor);
            let m = &self.monitors[monitor];
            if let Some(c) = self.clients.iter_mut().find(|c| c.id == id) {
                c.monitor = monitor;
                c.desktop = m.desktop;
                c.tags = m.view;
                c.snap_constrained = false;
                c.snap_maximized = false;
                c.floating_rect = clamp(rect, m.work);
            }
            self.publish_client_workspace(id)?;
            self.sync_states(id)?;
            self.arrange()?;
        }
        self.update_drop_target(x, y)?;
        Ok(())
    }
    fn update_drop_target(&mut self, x: i32, y: i32) -> Result<()> {
        let Some(drag) = &self.drag else {
            return Ok(());
        };
        let target = if drag.resize || !drag.moved {
            None
        } else {
            self.monitors
                .iter()
                .enumerate()
                .find(|(_, m)| dropzones::contains(m.area, x, y))
                .and_then(|(index, m)| {
                    if m.layouts[m.slot()] == 1 {
                        return None;
                    }
                    let tiles: Vec<_> = self
                        .clients
                        .iter()
                        .filter(|c| {
                            c.id != drag.id
                                && c.monitor == index
                                && c.tags & m.view != 0
                                && !c.floating
                                && !c.minimized
                                && !c.dock
                                && c.swallowed_by.is_none()
                                && !c.fullscreen
                        })
                        .filter_map(|c| c.applied.map(|r| (c.id, r)))
                        .collect();
                    dropzones::choose(index, inset(m.work, self.config.outer_gap), &tiles, x, y)
                })
        };
        let target = target
            .filter(|t| t.mode != dropzones::Mode::Empty || t.monitor != drag.original.monitor);
        let changed = self.drag.as_ref().unwrap().target != target;
        self.drag.as_mut().unwrap().target = target;
        if changed {
            self.show_drop_zone(target)?;
        }
        if self.config.drag_place {
            if let Some(mut target) = target {
                // Live place mode inserts at the side, while ordinary drops can swap.
                if target.mode == dropzones::Mode::Swap {
                    target.mode = dropzones::Mode::Before;
                }
                self.retile_drag(target)?;
            }
        }
        Ok(())
    }
    fn show_drop_zone(&self, target: Option<dropzones::Target>) -> Result<()> {
        self.conn.change_property32(
            PropMode::REPLACE,
            self.root,
            self.atoms._CARPATIC_DROP_TARGET,
            AtomEnum::WINDOW,
            &[target.and_then(|t| t.client).unwrap_or(NONE)],
        )?;
        let Some(target) = target else {
            self.conn.unmap_window(self.drop_overlay)?;
            self.conn
                .delete_property(self.root, self.atoms._CARPATIC_DROP_ZONE)?;
            return Ok(());
        };
        let r = target.rect;
        let w = r.width.max(1);
        let h = r.height.max(1);
        let t = (4 * self.config.scale / 100)
            .max(2)
            .min(w / 2)
            .min(h / 2)
            .max(1);
        let ring = [
            Rectangle {
                x: 0,
                y: 0,
                width: w as u16,
                height: t as u16,
            },
            Rectangle {
                x: 0,
                y: (h - t) as i16,
                width: w as u16,
                height: t as u16,
            },
            Rectangle {
                x: 0,
                y: t as i16,
                width: t as u16,
                height: h.saturating_sub(t * 2).max(1) as u16,
            },
            Rectangle {
                x: (w - t) as i16,
                y: t as i16,
                width: t as u16,
                height: h.saturating_sub(t * 2).max(1) as u16,
            },
        ];
        use x11rb::protocol::shape::{ConnectionExt as _, SK, SO};
        self.conn.configure_window(
            self.drop_overlay,
            &ConfigureWindowAux::new()
                .x(r.x)
                .y(r.y)
                .width(w)
                .height(h)
                .stack_mode(StackMode::ABOVE),
        )?;
        self.conn.shape_rectangles(
            SO::SET,
            SK::BOUNDING,
            ClipOrdering::UNSORTED,
            self.drop_overlay,
            0,
            0,
            &ring,
        )?;
        self.conn.change_window_attributes(
            self.drop_overlay,
            &ChangeWindowAttributesAux::new().background_pixel(self.config.border_active),
        )?;
        self.conn.map_window(self.drop_overlay)?;
        self.conn.clear_area(false, self.drop_overlay, 0, 0, 0, 0)?;
        self.conn.change_property32(
            PropMode::REPLACE,
            self.root,
            self.atoms._CARPATIC_DROP_ZONE,
            AtomEnum::CARDINAL,
            &[
                self.drop_overlay,
                target.client.unwrap_or(NONE),
                target.mode as u32,
                r.x as u32,
                r.y as u32,
                w,
                h,
                target.monitor as u32,
            ],
        )?;
        Ok(())
    }
    fn retile_drag(&mut self, target: dropzones::Target) -> Result<()> {
        let Some(id) = self.drag.as_ref().map(|d| d.id) else {
            return Ok(());
        };
        let Some(index) = self.clients.iter().position(|c| c.id == id) else {
            return Ok(());
        };
        if let Some(target_id) = target.client {
            let Some(target_index) = self.clients.iter().position(|c| c.id == target_id) else {
                return Ok(());
            };
            if target.mode == dropzones::Mode::Swap
                && self.drag.as_ref().unwrap().original.monitor == target.monitor
            {
                self.clients.swap(index, target_index);
            } else {
                let client = self.clients.remove(index);
                let next = self
                    .clients
                    .iter()
                    .position(|c| c.id == target_id)
                    .unwrap_or(0)
                    + usize::from(target.mode == dropzones::Mode::After);
                self.clients.insert(next, client);
            }
        }
        let m = &self.monitors[target.monitor];
        if let Some(c) = self.clients.iter_mut().find(|c| c.id == id) {
            c.monitor = target.monitor;
            c.tags = m.view;
            c.desktop = m.desktop;
            c.floating = false;
            c.max_saved = None;
            c.applied = None;
        }
        self.publish_client_workspace(id)?;
        self.sync_states(id)?;
        self.arrange()?;
        self.focus(id)?;
        Ok(())
    }
    fn publish_client_workspace(&self, id: Window) -> Result<()> {
        if let Some(c) = self.clients.iter().find(|c| c.id == id) {
            self.conn.change_property32(
                PropMode::REPLACE,
                id,
                self.atoms._NET_WM_DESKTOP,
                AtomEnum::CARDINAL,
                &[c.desktop],
            )?;
            self.conn.change_property32(
                PropMode::REPLACE,
                id,
                self.atoms._CARPATIC_TAGS,
                AtomEnum::CARDINAL,
                &[c.tags],
            )?;
        }
        Ok(())
    }
    fn end_drag(&mut self, cancel: bool) -> Result<()> {
        if let Some(id) = self.drag.as_ref().map(|d| d.id) {
            self.animation_drag(id, 0)?;
        }
        if !cancel && !self.config.drag_place {
            if let Some(target) = self.drag.as_ref().and_then(|d| d.target) {
                self.retile_drag(target)?;
            }
        }
        let id = self.drag.as_ref().map(|d| d.id);
        if let Some(drag) = self.drag.take() {
            if cancel {
                if let Some(c) = self.clients.iter_mut().find(|c| c.id == drag.id) {
                    c.floating = drag.original_floating;
                    c.floating_rect = drag.original.rect;
                    c.monitor = drag.original.monitor.min(self.monitors.len() - 1);
                    c.tags = drag.original.tags;
                    c.desktop = drag.original.desktop;
                    c.max_saved = drag.original.max_saved;
                    c.snap_constrained = drag.original.snap_constrained;
                    c.snap_maximized = drag.original.snap_maximized;
                    c.tile_slot = drag.original.tile_slot;
                    c.applied = None;
                }
                self.clients.sort_by_key(|c| {
                    drag.original
                        .order
                        .iter()
                        .position(|id| *id == c.id)
                        .unwrap_or(usize::MAX)
                });
                self.active_monitor = drag.original.active_monitor.min(self.monitors.len() - 1);
                self.desktop = self.monitors[self.active_monitor].desktop;
                self.publish_client_workspace(drag.id)?;
                self.sync_states(drag.id)?;
            }
        }
        self.conn.ungrab_keyboard(CURRENT_TIME)?;
        self.conn.ungrab_pointer(CURRENT_TIME)?;
        self.show_drop_zone(None)?;
        self.arrange()?;
        if let Some(id) = id {
            self.focus(id)?;
        }
        self.conn.change_property32(
            PropMode::REPLACE,
            self.root,
            self.atoms._CARPATIC_DRAGGING,
            AtomEnum::CARDINAL,
            &[0],
        )?;
        Ok(())
    }

    fn detach_rect(&mut self, id: Window, rect: Rect) -> Result<Rect> {
        let monitor = self
            .clients
            .iter()
            .find(|c| c.id == id)
            .map(|c| c.monitor)
            .unwrap_or(self.active_monitor);
        let work = self.monitors[monitor].work;
        let rect = clamp(
            Rect {
                width: rect.width.min((work.width * 2 / 3).max(64)),
                height: rect.height.min((work.height * 2 / 3).max(48)),
                ..rect
            },
            work,
        );
        if let Some(c) = self.clients.iter_mut().find(|c| c.id == id) {
            c.floating_rect = rect;
            c.applied = None;
        }
        self.arrange()?;
        Ok(rect)
    }

    fn sync_states(&self, id: Window) -> Result<()> {
        let Some(c) = self.clients.iter().find(|c| c.id == id) else {
            return Ok(());
        };
        let own = [
            self.atoms._NET_WM_STATE_FULLSCREEN,
            self.atoms._NET_WM_STATE_HIDDEN,
            self.atoms._NET_WM_STATE_MAXIMIZED_HORZ,
            self.atoms._NET_WM_STATE_MAXIMIZED_VERT,
            self.atoms._NET_WM_STATE_DEMANDS_ATTENTION,
            self.atoms._NET_WM_STATE_ABOVE,
        ];
        let mut states = self.property(id, self.atoms._NET_WM_STATE);
        states.retain(|state| !own.contains(state));
        if c.fullscreen || c.fake_fullscreen {
            states.push(own[0]);
        }
        if c.minimized {
            states.push(own[1]);
        }
        if c.max_saved.is_some() {
            states.extend_from_slice(&own[2..4]);
        }
        if c.urgent {
            states.push(own[4]);
        }
        if c.above {
            states.push(own[5]);
        }
        self.conn.change_property32(
            PropMode::REPLACE,
            id,
            self.atoms._CARPATIC_FAKE_FULLSCREEN,
            AtomEnum::CARDINAL,
            &[u32::from(c.fake_fullscreen)],
        )?;
        if let Some((r, f)) = c.snap_saved {
            self.conn.change_property32(
                PropMode::REPLACE,
                id,
                self.atoms._CARPATIC_SNAP_SAVED,
                AtomEnum::CARDINAL,
                &[
                    r.x as u32,
                    r.y as u32,
                    r.width,
                    r.height,
                    u32::from(f),
                    u32::from(c.snap_constrained),
                    u32::from(c.snap_maximized),
                ],
            )?;
        } else {
            self.conn
                .delete_property(id, self.atoms._CARPATIC_SNAP_SAVED)?;
        }
        if let Some((r, f)) = c.max_saved {
            self.conn.change_property32(
                PropMode::REPLACE,
                id,
                self.atoms._CARPATIC_MAX_SAVED,
                AtomEnum::CARDINAL,
                &[r.x as u32, r.y as u32, r.width, r.height, u32::from(f)],
            )?;
        } else {
            self.conn
                .delete_property(id, self.atoms._CARPATIC_MAX_SAVED)?;
        }
        self.conn.change_property32(
            PropMode::REPLACE,
            id,
            self.atoms._CARPATIC_FLOATING,
            AtomEnum::CARDINAL,
            &[u32::from(c.floating)],
        )?;
        self.conn.change_property32(
            PropMode::REPLACE,
            id,
            self.atoms._NET_WM_STATE,
            AtomEnum::ATOM,
            &states,
        )?;
        Ok(())
    }

    fn minimize(&mut self, id: Window) -> Result<()> {
        self.animation_kind(id, 1)?;
        // Picom resolves window rules while a window is still mapped. Give it
        // two frames to observe the minimise marker before the UnmapNotify.
        // This is a nonblocking deadline, and is absent with reduced motion,
        // disabled effects, or no compositor owning the display.
        let delay = self
            .property(self.root, self.atoms._CARPATIC_ANIMATION_PREPARE)
            .first()
            .copied()
            .unwrap_or(0)
            .min(100);
        if delay > 0
            && self
                .conn
                .get_selection_owner(self.atoms._NET_WM_CM_S0)?
                .reply()?
                .owner
                != NONE
        {
            self.deferred_unmaps.retain(|(w, _)| *w != id);
            self.deferred_unmaps
                .push((id, Instant::now() + Duration::from_millis(delay.into())));
        }
        self.min_clock = self.min_clock.wrapping_add(1);
        if let Some(c) = self.clients.iter_mut().find(|c| c.id == id) {
            c.minimized = true;
            c.min_stamp = self.min_clock;
            self.conn.change_property32(
                PropMode::REPLACE,
                id,
                self.atoms._CARPATIC_MINIMIZED_AT,
                AtomEnum::CARDINAL,
                &[c.min_stamp],
            )?;
            self.conn.change_property32(
                PropMode::REPLACE,
                id,
                self.atoms.WM_STATE,
                self.atoms.WM_STATE,
                &[3, 0],
            )?;
        }
        self.sync_states(id)?;
        self.arrange()?;
        self.focus_available()
    }

    fn restore(&mut self, id: Window) -> Result<()> {
        self.deferred_unmaps.retain(|(w, _)| *w != id);
        self.animation_kind(id, 2)?;
        if let Some(c) = self.clients.iter_mut().find(|c| c.id == id) {
            c.minimized = false;
            self.conn.change_property32(
                PropMode::REPLACE,
                id,
                self.atoms.WM_STATE,
                self.atoms.WM_STATE,
                &[1, 0],
            )?;
        }
        self.sync_states(id)?;
        self.arrange()?;
        self.focus(id)
    }

    fn keyboard_snap(&mut self, id: Window, action: u32) -> Result<()> {
        let Some(index) = self
            .clients
            .iter()
            .position(|c| c.id == id && !c.dock && !c.fullscreen)
        else {
            return Ok(());
        };
        let monitor = self.clients[index].monitor;
        let layout = self.monitors[monitor].layouts[self.monitors[monitor].slot()];
        if action < 2 && layout != 1 && !self.clients[index].floating {
            let visible: Vec<_> = self
                .clients
                .iter()
                .filter(|c| {
                    c.monitor == monitor
                        && !c.dock
                        && !c.minimized
                        && c.swallowed_by.is_none()
                        && c.tags & self.monitors[monitor].view != 0
                })
                .map(|c| c.id)
                .collect();
            if let Some(position) = visible.iter().position(|w| *w == id) {
                let next =
                    (position + if action == 0 { visible.len() - 1 } else { 1 }) % visible.len();
                self.focus(visible[next])?;
            }
            return Ok(());
        }
        let work = self.monitors[monitor].work;
        let c = &mut self.clients[index];
        if action == 3 {
            if let Some((rect, floating)) = c.snap_saved.take().or_else(|| c.max_saved.take()) {
                c.floating_rect = rect;
                c.floating = floating;
                c.max_saved = None;
                c.snap_maximized = false;
                c.snap_constrained = false;
            }
        } else if action <= 2 {
            if c.snap_saved.is_none() {
                c.snap_saved = Some(
                    c.max_saved
                        .unwrap_or((c.applied.unwrap_or(c.floating_rect), c.floating)),
                );
            }
            c.floating = true;
            c.snap_maximized = action == 2;
            c.snap_constrained = true;
            c.max_saved = if action == 2 { c.snap_saved } else { None };
            let left = work.width / 2;
            c.floating_rect = if action == 0 {
                Rect {
                    width: left.max(1),
                    ..work
                }
            } else if action == 1 {
                Rect {
                    x: work.x + left as i32,
                    width: work.width.saturating_sub(left).max(1),
                    ..work
                }
            } else {
                work
            };
        } else {
            return Ok(());
        }
        c.applied = None;
        self.sync_states(id)?;
        self.arrange()?;
        self.focus(id)?;
        self.client_list()?;
        Ok(())
    }

    fn maximize(&mut self, id: Window) -> Result<()> {
        if let Some(c) = self.clients.iter_mut().find(|c| c.id == id) {
            if c.fullscreen {
                return Ok(());
            }
            if let Some((rect, floating)) = c.max_saved.take() {
                c.floating_rect = rect;
                c.floating = floating;
            } else {
                c.max_saved = Some((c.applied.unwrap_or(c.floating_rect), c.floating));
                c.floating = true;
            }
            c.snap_saved = None;
            c.snap_maximized = false;
            c.snap_constrained = false;
            c.applied = None;
        }
        self.sync_states(id)?;
        self.arrange()?;
        self.focus(id)
    }

    fn animation_kind(&mut self, id: Window, kind: u32) -> Result<()> {
        let Some(c) = self.clients.iter().find(|c| c.id == id) else {
            return Ok(());
        };
        let windows: Vec<_> = [c.id, c.titlebar].into_iter().chain(c.frame).collect();
        self.animation_expiry.retain(|(w, _)| !windows.contains(w));
        for window in windows {
            self.conn.change_property32(
                PropMode::REPLACE,
                window,
                self.atoms._CARPATIC_ANIMATION,
                AtomEnum::CARDINAL,
                &[kind],
            )?;
            if kind == 2 {
                self.animation_expiry
                    .push((window, Instant::now() + Duration::from_secs(2)));
            }
        }
        Ok(())
    }

    fn animation_drag(&self, id: Window, active: u32) -> Result<()> {
        if let Some(c) = self.clients.iter().find(|c| c.id == id) {
            for window in [c.id, c.titlebar].into_iter().chain(c.frame) {
                self.conn.change_property32(
                    PropMode::REPLACE,
                    window,
                    self.atoms._CARPATIC_DRAGGING,
                    AtomEnum::CARDINAL,
                    &[active],
                )?;
            }
        }
        Ok(())
    }

    fn expire_animation_marks(&mut self) -> Result<()> {
        let now = Instant::now();
        let pending = self.deferred_unmaps.len();
        self.deferred_unmaps.retain(|(_, deadline)| *deadline > now);
        if self.deferred_unmaps.len() != pending {
            self.arrange()?;
        }
        let expired: Vec<_> = self
            .animation_expiry
            .iter()
            .filter(|(_, deadline)| *deadline <= now)
            .map(|(w, _)| *w)
            .collect();
        self.animation_expiry
            .retain(|(_, deadline)| *deadline > now);
        for window in expired {
            if self
                .clients
                .iter()
                .any(|c| c.id == window || c.titlebar == window || c.frame == Some(window))
            {
                self.conn.change_property32(
                    PropMode::REPLACE,
                    window,
                    self.atoms._CARPATIC_ANIMATION,
                    AtomEnum::CARDINAL,
                    &[0],
                )?;
            }
        }
        Ok(())
    }

    fn publish(&self) -> Result<()> {
        let a = &self.atoms;
        for window in [self.root, self.support] {
            self.conn.change_property32(
                PropMode::REPLACE,
                window,
                a._NET_SUPPORTING_WM_CHECK,
                AtomEnum::WINDOW,
                &[self.support],
            )?;
        }
        self.conn.change_property8(
            PropMode::REPLACE,
            self.support,
            a._NET_WM_NAME,
            a.UTF8_STRING,
            b"Carpathian OS",
        )?;
        self.conn.change_property32(
            PropMode::REPLACE,
            self.root,
            a._NET_SUPPORTED,
            AtomEnum::ATOM,
            &[
                a._NET_SUPPORTING_WM_CHECK,
                a._NET_WM_NAME,
                a._NET_CLIENT_LIST,
                a._NET_ACTIVE_WINDOW,
                a._NET_NUMBER_OF_DESKTOPS,
                a._NET_CURRENT_DESKTOP,
                a._NET_DESKTOP_NAMES,
                a._NET_WM_DESKTOP,
                a._NET_WM_STATE,
                a._NET_WM_STATE_FULLSCREEN,
                a._NET_CLOSE_WINDOW,
                a._NET_WORKAREA,
                a._NET_CLIENT_LIST_STACKING,
                a._NET_WM_STATE_HIDDEN,
                a._NET_WM_STATE_MAXIMIZED_VERT,
                a._NET_WM_STATE_MAXIMIZED_HORZ,
                a._NET_WM_STATE_ABOVE,
                a._NET_WM_STATE_DEMANDS_ATTENTION,
                a._NET_WM_MOVERESIZE,
                a._CARPATIC_SNAP,
                a._NET_FRAME_EXTENTS,
                a._NET_REQUEST_FRAME_EXTENTS,
                a._NET_WM_WINDOW_TYPE,
                a._NET_WM_WINDOW_TYPE_DESKTOP,
                a._NET_SHOWING_DESKTOP,
                a._NET_WM_ICON,
            ],
        )?;
        self.conn.change_property32(
            PropMode::REPLACE,
            self.root,
            a._NET_NUMBER_OF_DESKTOPS,
            AtomEnum::CARDINAL,
            &[self.desktop_count()],
        )?;
        self.conn.change_property8(
            PropMode::REPLACE,
            self.root,
            a._NET_DESKTOP_NAMES,
            a.UTF8_STRING,
            &desktop_names(&self.desktop_config()),
        )?;
        self.conn.change_property32(
            PropMode::REPLACE,
            self.root,
            a._NET_CURRENT_DESKTOP,
            AtomEnum::CARDINAL,
            &[self.desktop],
        )?;
        let mut workarea = Vec::new();
        for _ in 0..self.desktop_count() {
            workarea.extend([0, 0, self.area.width, self.area.height]);
        }
        self.conn.change_property32(
            PropMode::REPLACE,
            self.root,
            a._NET_WORKAREA,
            AtomEnum::CARDINAL,
            &workarea,
        )?;
        Ok(())
    }

    fn property(&self, id: Window, atom: Atom) -> Vec<u32> {
        self.conn
            .get_property(false, id, atom, AtomEnum::ANY, 0, 32)
            .ok()
            .and_then(|c| c.reply().ok())
            .and_then(|r| r.value32().map(|v| v.collect()))
            .unwrap_or_default()
    }

    fn grab_mouse_buttons(&self, id: Window) -> Result<()> {
        self.conn
            .ungrab_button(ButtonIndex::ANY, id, ModMask::ANY)?;
        self.conn.grab_button(
            false,
            id,
            EventMask::BUTTON_PRESS,
            GrabMode::SYNC,
            GrabMode::ASYNC,
            NONE,
            NONE,
            ButtonIndex::ANY,
            ModMask::ANY,
        )?;
        for button in [ButtonIndex::M1, ButtonIndex::M3] {
            for lock in [0, 2, 16, 18] {
                self.conn.grab_button(
                    false,
                    id,
                    EventMask::BUTTON_PRESS | EventMask::BUTTON_RELEASE | EventMask::POINTER_MOTION,
                    GrabMode::ASYNC,
                    GrabMode::ASYNC,
                    NONE,
                    NONE,
                    button,
                    ModMask::from(SUPER | lock),
                )?;
            }
        }
        for binding in self
            .mouse_bindings
            .iter()
            .filter(|b| b.context == "ClkClientWin")
        {
            for lock in [0, 2, 16, 18] {
                self.conn.grab_button(
                    false,
                    id,
                    EventMask::BUTTON_PRESS | EventMask::BUTTON_RELEASE | EventMask::POINTER_MOTION,
                    GrabMode::ASYNC,
                    GrabMode::ASYNC,
                    NONE,
                    NONE,
                    ButtonIndex::from(binding.button),
                    ModMask::from(modifier_mask(&binding.binding.modifiers) | lock),
                )?;
            }
        }
        Ok(())
    }
    fn bind_keys(&mut self) -> Result<()> {
        self.conn.ungrab_key(0u8, self.root, ModMask::ANY)?;
        let setup = self.conn.setup();
        let first = setup.min_keycode;
        let mapping = self
            .conn
            .get_keyboard_mapping(first, setup.max_keycode - first + 1)?
            .reply()?;
        self.keys.clear();
        for (index, symbols) in mapping
            .keysyms
            .chunks(mapping.keysyms_per_keycode as usize)
            .enumerate()
        {
            let Some(&sym) = symbols.first() else {
                continue;
            };
            let code = first + index as u8;
            self.keys.push((code, sym));
            let mut modifiers = Vec::new();
            if self.bindings.is_empty() {
                if [
                    0xff0d, 0x20, 0x6a, 0x6b, 0x68, 0x6c, 0x66, 0x71, 0x6e, 0x6d, 0x7a, 0x74,
                ]
                .contains(&sym)
                    || (0x31..=0x39).contains(&sym)
                {
                    modifiers.extend([SUPER, SUPER | 1]);
                }
            } else {
                modifiers.extend(
                    self.bindings
                        .iter()
                        .filter(|binding| keysym(&binding.key) == Some(sym))
                        .map(|b| modifier_mask(&b.modifiers)),
                );
            }
            for modifiers in modifiers {
                for lock in [0, 2, 16, 18] {
                    self.conn.grab_key(
                        false,
                        self.root,
                        ModMask::from(modifiers | lock),
                        code,
                        GrabMode::ASYNC,
                        GrabMode::ASYNC,
                    )?;
                }
            }
        }
        Ok(())
    }

    fn action(&mut self, binding: &Binding) -> Result<()> {
        let active_slot = self.monitors[self.active_monitor].slot();
        match binding.func.as_str() {
            "spawn" => {
                let args: Vec<&str> = if let Some(cmd) = &binding.cmd {
                    cmd.split_whitespace().collect()
                } else {
                    binding.exec.iter().map(String::as_str).collect()
                };
                if args.len() == 2 && args[0] == "carpatic-snap" {
                    let action = match args[1] {
                        "left" => Some(0),
                        "right" => Some(1),
                        "max" => Some(2),
                        "restore" => Some(3),
                        _ => None,
                    };
                    if let (Some(id), Some(action)) = (self.focused, action) {
                        return self.keyboard_snap(id, action);
                    }
                }
                let mut command = if let Some(cmd) = &binding.cmd {
                    let mut c = Command::new("sh");
                    c.args(["-c", cmd]);
                    c
                } else if let Some(executable) = binding.exec.first() {
                    let mut c = Command::new(executable);
                    c.args(&binding.exec[1..]);
                    c
                } else {
                    return Ok(());
                };
                match command.spawn() {
                    Ok(mut child) => {
                        std::thread::spawn(move || {
                            let _ = child.wait();
                        });
                    }
                    Err(e) => eprintln!("Could not launch application: {e}"),
                }
            }
            "quit" => self.running = false,
            "showdesktop" => self.show_desktop(!self.showing_desktop)?,
            "togglebar" => {
                self.config.bar_enabled = !self.config.bar_enabled;
                self.arrange()?;
            }
            "killclient" => {
                if let Some(id) = self.focused {
                    self.close(id)?;
                }
            }
            "togglefloating" => {
                if let Some(id) = self.focused {
                    self.float(id)?;
                }
            }
            "togglefakefullscreen" => {
                if let Some(id) = self.focused {
                    if let Some(c) = self.clients.iter_mut().find(|c| c.id == id) {
                        c.fake_fullscreen = !c.fake_fullscreen;
                        if c.fake_fullscreen {
                            c.fullscreen = false;
                            c.applied = None;
                        }
                    }
                    self.sync_states(id)?;
                    self.arrange()?;
                }
            }
            "fullscreen" => {
                if let Some(id) = self.focused {
                    self.fullscreen(id, 2)?;
                }
            }
            "togglemaximize" => {
                if let Some(id) = self.focused {
                    self.maximize(id)?;
                }
            }
            "minimize" => {
                if let Some(id) = self.focused {
                    self.minimize(id)?;
                }
            }
            "unminimize" => {
                if let Some(id) = self
                    .clients
                    .iter()
                    .rev()
                    .filter(|c| {
                        c.minimized
                            && c.monitor == self.active_monitor
                            && c.tags & self.monitors[c.monitor].view != 0
                    })
                    .max_by_key(|c| c.min_stamp)
                    .map(|c| c.id)
                {
                    self.restore(id)?;
                }
            }
            "setlayout" => {
                self.monitors[self.active_monitor].layouts[active_slot] =
                    binding.layout_idx.min(2) as u8;
                self.invalidate_layout()?;
            }
            "togglelayout" => {
                self.monitors[self.active_monitor].layouts[active_slot] =
                    u8::from(self.monitors[self.active_monitor].layouts[active_slot] == 0);
                self.invalidate_layout()?;
            }
            "setmfact" => {
                let factor = self.monitors[self.active_monitor].factors[active_slot] as f32 / 100.0;
                let factor = if binding.f < 1.0 {
                    factor + binding.f
                } else {
                    binding.f - 1.0
                };
                self.monitors[self.active_monitor].factors[active_slot] =
                    (factor.clamp(0.05, 0.95) * 100.0).round() as u32;
                self.invalidate_layout()?;
            }
            "incnmaster" => {
                self.monitors[self.active_monitor].masters[active_slot] =
                    (self.monitors[self.active_monitor].masters[active_slot] as i32 + binding.i)
                        .clamp(0, 32) as usize;
                self.invalidate_layout()?;
            }
            "incgaps" => {
                self.config.inner_gap =
                    (self.config.inner_gap as i32 + binding.i).clamp(0, 100) as u32;
                self.config.outer_gap =
                    (self.config.outer_gap as i32 + binding.i).clamp(0, 100) as u32;
                self.invalidate_layout()?;
            }
            "setcfact" => {
                if let Some(c) = self.clients.iter_mut().find(|c| Some(c.id) == self.focused) {
                    c.weight = if binding.f == 0.0 {
                        1.0
                    } else {
                        (c.weight + binding.f).clamp(0.25, 4.0)
                    };
                }
                self.invalidate_layout()?;
            }
            "focusstack" | "movestack" | "zoom" => {
                let indices: Vec<_> = self
                    .clients
                    .iter()
                    .enumerate()
                    .filter(|(_, c)| {
                        c.monitor == self.active_monitor
                            && c.tags & self.monitors[c.monitor].view != 0
                            && !c.minimized
                            && !c.dock
                            && c.swallowed_by.is_none()
                            && (binding.func == "focusstack"
                                || (!c.floating
                                    && !c.fullscreen
                                    && self.monitors[c.monitor].layouts
                                        [self.monitors[c.monitor].slot()]
                                        != 1))
                    })
                    .map(|(i, _)| i)
                    .collect();
                if !indices.is_empty() {
                    let position = indices
                        .iter()
                        .position(|i| Some(self.clients[*i].id) == self.focused)
                        .unwrap_or(0);
                    let next = (position + if binding.i < 0 { indices.len() - 1 } else { 1 })
                        % indices.len();
                    let target = if binding.func == "zoom" {
                        if position == 0 {
                            next
                        } else {
                            0
                        }
                    } else {
                        next
                    };
                    let id = self.clients[indices[position]].id;
                    if binding.func == "focusstack" {
                        self.focus(self.clients[indices[target]].id)?;
                    } else {
                        self.clients.swap(indices[position], indices[target]);
                        self.invalidate_layout()?;
                        self.focus(id)?;
                    }
                }
            }
            "view" | "tag" | "toggleview" | "toggletag" => {
                let all = (1 << self.config.workspaces) - 1;
                let mask = if binding.ui == 0 && binding.func == "view" {
                    self.monitors[self.active_monitor].previous_view
                } else if binding.ui < 0 {
                    all
                } else {
                    binding.ui as u32 & all
                };
                if mask == 0 {
                    return Ok(());
                }
                if binding.func == "tag" || binding.func == "toggletag" {
                    if let Some(c) = self.clients.iter_mut().find(|c| Some(c.id) == self.focused) {
                        let tags = if binding.func == "tag" {
                            mask
                        } else {
                            c.tags ^ mask
                        };
                        if tags != 0 {
                            c.tags = tags;
                            c.desktop = tags.trailing_zeros();
                            self.conn.change_property32(
                                PropMode::REPLACE,
                                c.id,
                                self.atoms._CARPATIC_TAGS,
                                AtomEnum::CARDINAL,
                                &[tags],
                            )?;
                            self.conn.change_property32(
                                PropMode::REPLACE,
                                c.id,
                                self.atoms._NET_WM_DESKTOP,
                                AtomEnum::CARDINAL,
                                &[c.desktop],
                            )?;
                        }
                    }
                    self.arrange()?;
                    self.focus_available()?;
                } else {
                    let view = if binding.func == "view" {
                        mask
                    } else {
                        self.monitors[self.active_monitor].view ^ mask
                    };
                    if view != 0 {
                        let all_view = binding.func == "view"
                            && if binding.ui == 0 {
                                self.monitors[self.active_monitor].previous_all
                            } else {
                                binding.ui < 0
                            };
                        self.set_view(view, all_view)?;
                    }
                }
            }
            "focusmon" | "tagmon" => {
                let target = (self.active_monitor as i32 + binding.i.signum())
                    .rem_euclid(self.monitors.len() as i32) as usize;
                if binding.func == "tagmon" {
                    if let Some(c) = self.clients.iter_mut().find(|c| Some(c.id) == self.focused) {
                        c.monitor = target;
                        c.desktop = self.monitors[target].desktop;
                        c.tags = self.monitors[target].view;
                        c.floating_rect = clamp(c.floating_rect, self.monitors[target].work);
                        c.applied = None;
                        self.conn.change_property32(
                            PropMode::REPLACE,
                            c.id,
                            self.atoms._NET_WM_DESKTOP,
                            AtomEnum::CARDINAL,
                            &[c.desktop],
                        )?;
                    }
                }
                self.active_monitor = target;
                self.desktop = self.monitors[target].desktop;
                self.master = self.monitors[target].factors[self.monitors[target].slot()];
                self.arrange()?;
                self.focus_available()?;
            }
            "viewrel" | "tagrel" => {
                let desktop =
                    (self.desktop as i32 + binding.i).rem_euclid(if binding.func == "viewrel" {
                        self.desktop_count()
                    } else {
                        self.config.workspaces
                    } as i32) as u32;
                if binding.func == "viewrel" {
                    self.switch(desktop)?;
                } else {
                    if let Some(c) = self.clients.iter_mut().find(|c| Some(c.id) == self.focused) {
                        c.desktop = desktop;
                        c.tags = 1 << desktop;
                        self.conn.change_property32(
                            PropMode::REPLACE,
                            c.id,
                            self.atoms._NET_WM_DESKTOP,
                            AtomEnum::CARDINAL,
                            &[desktop],
                        )?;
                    }
                    self.switch(desktop)?;
                }
            }
            "reload" => self.reload()?,
            other => eprintln!("Window-manager action is not available: {other}"),
        }
        Ok(())
    }

    fn invalidate_layout(&mut self) -> Result<()> {
        for c in &mut self.clients {
            c.applied = None;
            c.chrome_dirty = true;
        }
        self.arrange()
    }

    fn track_overlay(&mut self, id: Window) -> Result<()> {
        if id == self.drop_overlay
            || id == self.support
            || id == self.tray.owner
            || self.tray.is_icon(id)
            || self.bars.iter().any(|b| b.id == id)
            || self
                .clients
                .iter()
                .any(|c| c.titlebar == id || c.frame == Some(id))
        {
            return Ok(());
        }
        let attrs = match self.conn.get_window_attributes(id)?.reply() {
            Ok(a) => a,
            Err(_) => return Ok(()),
        };
        if !attrs.override_redirect {
            return Ok(());
        }
        let title = self.window_title(id);
        let values = self
            .conn
            .get_property(false, id, AtomEnum::WM_CLASS, AtomEnum::STRING, 0, 1024)?
            .reply()?
            .value;
        let mut parts = values.split(|b| *b == 0);
        let instance = String::from_utf8_lossy(parts.next().unwrap_or_default());
        let class = String::from_utf8_lossy(parts.next().unwrap_or_default());
        let locker = [instance.as_ref(), class.as_ref()]
            .iter()
            .any(|name| name.eq_ignore_ascii_case("i3lock") || name.eq_ignore_ascii_case("slock"));
        self.lock_overlays.retain(|w| *w != id);
        if locker {
            self.lock_overlays.push(id);
        }
        self.conn.change_window_attributes(
            id,
            &ChangeWindowAttributesAux::new().event_mask(EventMask::PROPERTY_CHANGE),
        )?;
        let priority = self
            .property(id, self.atoms._NET_WM_STATE)
            .contains(&self.atoms._NET_WM_STATE_ABOVE)
            || self.rules.iter().any(|r| {
                r.above
                    && (r.class.is_empty() || class.contains(&r.class))
                    && (r.instance.is_empty() || instance.contains(&r.instance))
                    && r.title.as_ref().is_none_or(|t| title.contains(t))
            });
        self.priority_overlays.retain(|w| *w != id);
        if priority {
            self.priority_overlays.push(id);
            self.conn.change_window_attributes(
                id,
                &ChangeWindowAttributesAux::new().event_mask(EventMask::PROPERTY_CHANGE),
            )?;
            self.conn
                .configure_window(id, &ConfigureWindowAux::new().stack_mode(StackMode::ABOVE))?;
        }
        self.enforce_lock_stack()
    }

    // Lockers own authentication/input grabs. The WM only keeps their surfaces
    // above its chrome and independently raised panels/notifications.
    fn enforce_lock_stack(&self) -> Result<()> {
        if self.lock_overlays.is_empty() {
            return Ok(());
        }
        let children = self.conn.query_tree(self.root)?.reply()?.children;
        let mut covered = false;
        let mut locks = Vec::new();
        for id in children.iter().rev() {
            let Ok(attrs) = self.conn.get_window_attributes(*id)?.reply() else {
                continue;
            };
            if attrs.map_state != MapState::VIEWABLE {
                continue;
            }
            if self.lock_overlays.contains(id) {
                locks.push(*id);
                if !covered {
                    return Ok(());
                }
            } else {
                covered = true;
            }
        }
        // Query before raising: our own ConfigureNotify events become no-ops,
        // so this does not produce a restack loop or poll while idle.
        for id in locks.iter().rev() {
            self.conn
                .configure_window(*id, &ConfigureWindowAux::new().stack_mode(StackMode::ABOVE))?;
        }
        Ok(())
    }
    fn lower_desktop_surfaces(&self) -> Result<()> {
        if self.desktop_surfaces.is_empty() {
            return Ok(());
        }
        let children = self.conn.query_tree(self.root)?.reply()?.children;
        if children
            .iter()
            .take(self.desktop_surfaces.len())
            .all(|id| self.desktop_surfaces.contains(id))
        {
            return Ok(());
        }
        for id in &self.desktop_surfaces {
            self.conn
                .configure_window(*id, &ConfigureWindowAux::new().stack_mode(StackMode::BELOW))?;
        }
        Ok(())
    }

    fn create_app_frame(
        &self,
        id: Window,
        depth: u8,
        attributes: &GetWindowAttributesReply,
    ) -> Result<Window> {
        let frame = self.conn.generate_id()?;
        self.conn.create_window(
            depth,
            frame,
            self.root,
            0,
            0,
            1,
            1,
            0,
            WindowClass::INPUT_OUTPUT,
            attributes.visual,
            &CreateWindowAux::new()
                .override_redirect(1)
                .background_pixel(0)
                .border_pixel(0)
                .colormap(attributes.colormap)
                .event_mask(
                    EventMask::SUBSTRUCTURE_REDIRECT
                        | EventMask::SUBSTRUCTURE_NOTIFY
                        | EventMask::ENTER_WINDOW
                        | EventMask::BUTTON_PRESS,
                ),
        )?;
        self.conn.change_save_set(SetMode::INSERT, id)?.check()?;
        self.conn.reparent_window(id, frame, 0, 0)?.check()?;
        Ok(frame)
    }

    fn ensure_app_frame(&mut self, id: Window) -> Result<()> {
        let Some(index) = self
            .clients
            .iter()
            .position(|c| c.id == id && c.frame.is_none() && !c.dock && !c.has_csd)
        else {
            return Ok(());
        };
        let attributes = self.conn.get_window_attributes(id)?.reply()?;
        let geometry = self.conn.get_geometry(id)?.reply()?;
        let frame = self.create_app_frame(id, geometry.depth, &attributes)?;
        self.conn
            .reparent_window(self.clients[index].titlebar, frame, 0, 0)?
            .check()?;
        self.clients[index].frame = Some(frame);
        self.clients[index].ignored_unmaps += u32::from(attributes.map_state == MapState::VIEWABLE);
        self.clients[index].applied = None;
        self.clients[index].chrome_dirty = true;
        let kind = self
            .property(id, self.atoms._CARPATIC_ANIMATION)
            .first()
            .copied()
            .unwrap_or(0);
        self.animation_kind(id, kind)?;
        Ok(())
    }

    fn manage(&mut self, id: Window) -> Result<()> {
        if self.clients.iter().any(|c| c.id == id) {
            return Ok(());
        }
        let attributes = match self.conn.get_window_attributes(id)?.reply() {
            Ok(a) => a,
            Err(_) => return Ok(()),
        };
        if self
            .property(id, self.atoms._NET_WM_WINDOW_TYPE)
            .contains(&self.atoms._NET_WM_WINDOW_TYPE_DESKTOP)
        {
            if !self.desktop_surfaces.contains(&id) {
                self.desktop_surfaces.push(id);
            }
            self.conn.change_window_attributes(
                id,
                &ChangeWindowAttributesAux::new()
                    .event_mask(EventMask::STRUCTURE_NOTIFY | EventMask::PROPERTY_CHANGE),
            )?;
            self.conn.change_property32(
                PropMode::REPLACE,
                id,
                self.atoms._NET_WM_DESKTOP,
                AtomEnum::CARDINAL,
                &[u32::MAX],
            )?;
            // Focus the desktop before replaying ordinary and modified icon
            // selection clicks to GTK. Selecting ButtonPress would conflict
            // with the desktop application's own event subscription.
            self.conn
                .grab_button(
                    false,
                    id,
                    EventMask::BUTTON_PRESS,
                    GrabMode::SYNC,
                    GrabMode::ASYNC,
                    NONE,
                    NONE,
                    ButtonIndex::M1,
                    ModMask::ANY,
                )?
                .check()?;

            self.conn.map_window(id)?;
            self.lower_desktop_surfaces()?;
            self.client_list()?;
            return Ok(());
        }
        if attributes.override_redirect {
            self.track_overlay(id)?;
            return Ok(());
        }
        let g = self.conn.get_geometry(id)?.reply()?;
        let dock = self
            .property(id, self.atoms._NET_WM_WINDOW_TYPE)
            .contains(&self.atoms._NET_WM_WINDOW_TYPE_DOCK)
            || !self
                .property(id, self.atoms._NET_WM_STRUT_PARTIAL)
                .is_empty();
        let mut monitor = self
            .monitors
            .iter()
            .position(|m| {
                monitor::contains(
                    m.area,
                    i32::from(g.x) + i32::from(g.width) / 2,
                    i32::from(g.y) + i32::from(g.height) / 2,
                )
            })
            .unwrap_or(self.active_monitor);
        let mut floating = dock
            || self.property(id, self.atoms._CARPATIC_FLOATING).first() == Some(&1)
            || !self.property(id, self.atoms.WM_TRANSIENT_FOR).is_empty()
            || self
                .property(id, self.atoms._NET_WM_WINDOW_TYPE)
                .contains(&self.atoms._NET_WM_WINDOW_TYPE_DIALOG);
        let mut desktop = self
            .property(id, self.atoms._NET_WM_DESKTOP)
            .first()
            .copied()
            .filter(|d| *d < self.desktop_count())
            .unwrap_or(self.desktop);
        let title = self.window_title(id);
        let class_bytes = self
            .conn
            .get_property(false, id, AtomEnum::WM_CLASS, AtomEnum::STRING, 0, 1024)?
            .reply()?
            .value;
        let class_parts: Vec<_> = class_bytes
            .split(|b| *b == 0)
            .map(|b| String::from_utf8_lossy(b).to_string())
            .collect();
        let instance = class_parts.first().cloned().unwrap_or_default();
        let class = class_parts.get(1).cloned().unwrap_or_default();
        let mut terminal = matches!(
            class.as_str(),
            "XTerm" | "St" | "Alacritty" | "kitty" | "Dwmterm"
        );
        let mut noswallow = false;
        let mut above = false;
        let mut tags = 1 << desktop;
        for rule in &self.rules {
            if (!rule.class.is_empty() && !class.contains(&rule.class))
                || (!rule.instance.is_empty() && !instance.contains(&rule.instance))
                || rule
                    .title
                    .as_ref()
                    .is_some_and(|value| !title.contains(value))
            {
                continue;
            }
            if rule.floating_explicit {
                floating = rule.floating;
            }
            terminal |= rule.terminal;
            noswallow |= rule.noswallow;
            above |= rule.above;
            if rule.tags > 0 {
                tags = rule.tags & ((1 << self.config.workspaces) - 1);
                if tags > 0 {
                    desktop = tags.trailing_zeros();
                }
            }
            if rule.monitor >= 0 {
                (monitor) = (rule.monitor as usize).min(self.monitors.len() - 1);
            }
        }
        let size_hints = x11rb::properties::WmSizeHints::get_normal_hints(&self.conn, id)
            .ok()
            .and_then(|c| c.reply().ok())
            .flatten();
        if size_hints
            .as_ref()
            .is_some_and(|h| h.min_size.is_some() && h.min_size == h.max_size)
        {
            floating = true;
        }
        let wm_hints = x11rb::properties::WmHints::get(&self.conn, id)
            .ok()
            .and_then(|c| c.reply().ok())
            .flatten();
        let input = wm_hints.as_ref().and_then(|h| h.input).unwrap_or(true);
        let urgent = wm_hints.as_ref().is_some_and(|h| h.urgent)
            || self
                .property(id, self.atoms._NET_WM_STATE)
                .contains(&self.atoms._NET_WM_STATE_DEMANDS_ATTENTION);
        if size_hints
            .as_ref()
            .is_some_and(|h| h.min_size.is_some() && h.min_size == h.max_size)
        {
            floating = true;
        }
        let pid = self.window_pid(id);
        let swallowed_by = None;
        let parent = self
            .clients
            .iter()
            .find(|c| {
                c.terminal
                    && !c.noswallow
                    && c.swallowed_by.is_none()
                    && !noswallow
                    && !terminal
                    && !floating
                    && pid > 0
                    && c.pid > 0
                    && c.pid != pid
                    && process_descends_from(pid, c.pid)
            })
            .map(|c| {
                (
                    c.id,
                    c.desktop,
                    c.tags,
                    c.monitor,
                    c.floating_rect,
                    c.floating,
                )
            });
        let swallow_parent = parent.map(|p| p.0);
        if let Some((parent_id, parent_desktop, parent_tags, parent_monitor, _, parent_floating)) =
            parent
        {
            desktop = parent_desktop;
            tags = parent_tags;
            monitor = parent_monitor;
            floating = parent_floating;
            if let Some(c) = self.clients.iter_mut().find(|c| c.id == parent_id) {
                c.swallowed_by = Some(id);
            }
        }
        let minimized = self.property(id, self.atoms.WM_STATE).first() == Some(&3);
        let fake_fullscreen = self
            .property(id, self.atoms._CARPATIC_FAKE_FULLSCREEN)
            .first()
            == Some(&1);
        let saved = self.property(id, self.atoms._CARPATIC_MAX_SAVED);
        let max_saved = if saved.len() == 5 {
            Some((
                Rect {
                    x: saved[0] as i32,
                    y: saved[1] as i32,
                    width: saved[2],
                    height: saved[3],
                },
                saved[4] != 0,
            ))
        } else {
            None
        };
        let saved_snap = self.property(id, self.atoms._CARPATIC_SNAP_SAVED);
        let valid_snap = saved_snap.len() == 7
            && (1..=u16::MAX as u32).contains(&saved_snap[2])
            && (1..=u16::MAX as u32).contains(&saved_snap[3])
            && saved_snap[4..].iter().all(|v| *v <= 1)
            && (saved_snap[6] == 0 || (saved_snap[5] == 1 && max_saved.is_some()));
        let snap_saved = valid_snap.then(|| {
            (
                Rect {
                    x: saved_snap[0] as i32,
                    y: saved_snap[1] as i32,
                    width: saved_snap[2],
                    height: saved_snap[3],
                },
                saved_snap[4] == 1,
            )
        });
        let snap_constrained = valid_snap && saved_snap[5] == 1;
        let snap_maximized = valid_snap && saved_snap[6] == 1;
        let fullscreen = !fake_fullscreen
            && self
                .property(id, self.atoms._NET_WM_STATE)
                .contains(&self.atoms._NET_WM_STATE_FULLSCREEN);
        let motif = self.property(id, self.atoms._MOTIF_WM_HINTS);
        let has_csd = dock
            || !self.property(id, self.atoms._GTK_FRAME_EXTENTS).is_empty()
            || motif.len() >= 3 && motif[0] & 2 != 0 && motif[2] == 0;
        self.conn.change_window_attributes(
            id,
            &ChangeWindowAttributesAux::new()
                .event_mask(
                    EventMask::ENTER_WINDOW
                        | EventMask::PROPERTY_CHANGE
                        | EventMask::POINTER_MOTION,
                )
                .border_pixel(opaque_border_pixel(g.depth, self.config.border_inactive)),
        )?;
        {
            use x11rb::protocol::shape::ConnectionExt as _;
            self.conn.shape_select_input(id, true)?;
        }
        self.grab_mouse_buttons(id)?;
        self.conn.configure_window(
            id,
            &ConfigureWindowAux::new().border_width(if has_csd { 0 } else { self.config.border }),
        )?;
        self.conn.change_property32(
            PropMode::REPLACE,
            id,
            self.atoms.WM_STATE,
            self.atoms.WM_STATE,
            &[if minimized { 3 } else { 1 }, 0],
        )?;
        self.conn.change_property32(
            PropMode::REPLACE,
            id,
            self.atoms._NET_WM_DESKTOP,
            AtomEnum::CARDINAL,
            &[desktop],
        )?;
        let mut floating_rect = clamp(
            Rect {
                x: i32::from(g.x),
                y: i32::from(g.y),
                width: u32::from(g.width) + if has_csd { 0 } else { self.config.border * 2 },
                height: u32::from(g.height) + if has_csd { 0 } else { self.config.border * 2 },
            },
            self.area,
        );
        if floating && !dock {
            let work = self.monitors[monitor].work;
            floating_rect.x = work.x + (work.width.saturating_sub(floating_rect.width) / 2) as i32;
            floating_rect.y =
                work.y + (work.height.saturating_sub(floating_rect.height) / 2) as i32;
        }
        if let Some((_, _, _, _, rect, _)) = parent {
            floating_rect = rect;
        }
        let frame = if !has_csd && !dock {
            let frame = self.create_app_frame(id, g.depth, &attributes)?;
            Some(frame)
        } else {
            None
        };
        let saved_outer = self.property(id, self.atoms._CARPATIC_FRAME_GEOMETRY);
        if saved_outer.len() == 4 {
            floating_rect = clamp(
                Rect {
                    x: saved_outer[0] as i32,
                    y: saved_outer[1] as i32,
                    width: saved_outer[2].max(1),
                    height: saved_outer[3].max(1),
                },
                self.area,
            );
        }
        let titlebar = self.conn.generate_id()?;
        self.conn.create_window(
            self.conn.setup().roots[0].root_depth,
            titlebar,
            frame.unwrap_or(self.root),
            0,
            0,
            1,
            1,
            0,
            WindowClass::INPUT_OUTPUT,
            self.conn.setup().roots[0].root_visual,
            &CreateWindowAux::new()
                .colormap(self.conn.setup().roots[0].default_colormap)
                .border_pixel(0)
                .override_redirect(1)
                .event_mask(
                    EventMask::EXPOSURE
                        | EventMask::BUTTON_PRESS
                        | EventMask::BUTTON_RELEASE
                        | EventMask::POINTER_MOTION
                        | EventMask::LEAVE_WINDOW,
                ),
        )?;
        self.conn.change_property32(
            PropMode::REPLACE,
            titlebar,
            self.atoms._CARPATIC_CLIENT,
            AtomEnum::WINDOW,
            &[id],
        )?;
        let floating = floating || max_saved.is_some();
        let above = above
            || self
                .property(id, self.atoms._NET_WM_STATE)
                .contains(&self.atoms._NET_WM_STATE_ABOVE);
        self.clients.push(Client {
            id,
            desktop,
            tags,
            monitor,
            dock,
            floating,
            fullscreen,
            fake_fullscreen,
            floating_rect,
            applied: None,
            applied_border: None,
            applied_extents: None,
            mapped: attributes.map_state == MapState::VIEWABLE,
            ignored_unmaps: u32::from(
                frame.is_some() && attributes.map_state == MapState::VIEWABLE,
            ),
            titlebar,
            frame,
            original_border: g.border_width,
            depth: g.depth,
            shape_dirty: true,
            frame_shape: None,
            chrome_surface: None,
            title,
            icon: self.window_icon(id),
            minimized,
            min_stamp: self
                .property(id, self.atoms._CARPATIC_MINIMIZED_AT)
                .first()
                .copied()
                .unwrap_or(0),
            max_saved,
            snap_saved,
            snap_maximized,
            snap_constrained,
            chrome_dirty: true,
            hover: None,
            pressed: None,
            has_csd,
            weight: 1.0,
            terminal,
            noswallow,
            above,
            pid,
            swallowed_by,
            swallow_parent,
            size_hints,
            input,
            urgent,
            tile_slot: None,
        });
        self.min_clock = self
            .min_clock
            .max(self.clients.iter().map(|c| c.min_stamp).max().unwrap_or(0));
        self.animation_kind(id, if minimized { 1 } else { 0 })?;
        self.client_list()?;
        self.arrange()?;
        if desktop == self.desktop {
            self.focus(id)?;
        }
        Ok(())
    }

    fn client_list(&self) -> Result<()> {
        self.conn.change_property32(
            PropMode::REPLACE,
            self.root,
            self.atoms._NET_CLIENT_LIST,
            AtomEnum::WINDOW,
            &self
                .desktop_surfaces
                .iter()
                .copied()
                .chain(
                    self.clients
                        .iter()
                        .filter(|c| c.swallowed_by.is_none())
                        .map(|c| c.id),
                )
                .collect::<Vec<_>>(),
        )?;
        let stacking: Vec<_> = self
            .conn
            .query_tree(self.root)?
            .reply()?
            .children
            .into_iter()
            .filter_map(|id| {
                if self.desktop_surfaces.contains(&id) {
                    Some(id)
                } else {
                    self.clients
                        .iter()
                        .find(|c| c.surface() == id && !c.dock && c.swallowed_by.is_none())
                        .map(|c| c.id)
                }
            })
            .collect();
        self.conn.change_property32(
            PropMode::REPLACE,
            self.root,
            self.atoms._NET_CLIENT_LIST_STACKING,
            AtomEnum::WINDOW,
            &stacking,
        )?;
        Ok(())
    }

    fn desktop_count(&self) -> u32 {
        self.config.workspaces + self.app_spaces.len() as u32
    }

    fn desktop_config(&self) -> Config {
        let mut config = self.config.clone();
        config.workspace_names = (0..config.workspaces as usize)
            .map(|i| {
                config
                    .workspace_names
                    .get(i)
                    .cloned()
                    .unwrap_or_else(|| (i + 1).to_string())
            })
            .collect();
        for space in &self.app_spaces {
            config.workspace_names.push(self.window_title(space.client));
        }
        config.workspaces = self.desktop_count();
        config
    }

    fn reconcile_app_spaces(&mut self) -> Result<Option<Window>> {
        let normal = (1 << self.config.workspaces) - 1;
        let old = self.app_spaces.clone();
        let mut changed = false;
        for (index, space) in old.iter().enumerate() {
            let remains = self.config.fullscreen_spaces
                && index < (31 - self.config.workspaces) as usize
                && self
                    .clients
                    .iter()
                    .any(|c| c.id == space.client && c.fullscreen);
            if remains {
                continue;
            }
            changed = true;
            if let Some(c) = self.clients.iter_mut().find(|c| c.id == space.client) {
                c.tags = space.tags & normal;
                if c.tags == 0 {
                    c.tags = 1 << space.origin_desktop.min(self.config.workspaces - 1);
                }
                c.desktop = c.tags.trailing_zeros();
                c.monitor = space.monitor.min(self.monitors.len() - 1);
                c.applied = None;
                self.conn
                    .delete_property(c.id, self.atoms._CARPATIC_FULLSCREEN_ORIGIN)?;
            }
            for monitor in &mut self.monitors {
                if monitor.desktop == space.desktop {
                    monitor.view = space.view & normal;
                    if monitor.view == 0 {
                        monitor.view = 1;
                    }
                    monitor.desktop = monitor.view.trailing_zeros();
                    monitor.all_view = false;
                }
            }
        }
        self.app_spaces.retain(|s| {
            self.config.fullscreen_spaces
                && self
                    .clients
                    .iter()
                    .any(|c| c.id == s.client && c.fullscreen)
        });
        self.app_spaces
            .truncate((31 - self.config.workspaces) as usize);
        let removed = old
            .iter()
            .filter(|s| !self.app_spaces.iter().any(|a| a.client == s.client))
            .collect::<Vec<_>>();
        let mut mapping = Vec::new();
        for (index, space) in self.app_spaces.iter_mut().enumerate() {
            let new = self.config.workspaces + index as u32;
            mapping.push((space.desktop, new));
            changed |= space.desktop != new;
            space.desktop = new;
        }
        let old_mask = old.iter().fold(0, |mask, s| mask | (1 << s.desktop));
        let remap = |tags: u32| {
            let mut new = tags & !old_mask & normal;
            for (from, to) in &mapping {
                if tags & (1 << from) != 0 {
                    new |= 1 << to;
                }
            }
            for s in &removed {
                if tags & (1 << s.desktop) != 0 {
                    new |= s.tags & normal;
                }
            }
            if new == 0 {
                1
            } else {
                new
            }
        };
        if changed {
            for c in &mut self.clients {
                if let Some(space) = self.app_spaces.iter().find(|s| s.client == c.id) {
                    c.tags = 1 << space.desktop;
                    c.desktop = space.desktop;
                } else {
                    c.tags = remap(c.tags);
                    c.desktop = c.tags.trailing_zeros();
                }
                c.applied = None;
            }
            for monitor in &mut self.monitors {
                let previous = monitor.clone();
                monitor.view = if monitor.all_view {
                    normal
                } else {
                    remap(monitor.view)
                };
                monitor.previous_view = remap(monitor.previous_view);
                monitor.desktop = monitor.view.trailing_zeros();
                for (from, to) in &mapping {
                    monitor.layouts[*to as usize + 1] = previous.layouts[*from as usize + 1];
                    monitor.masters[*to as usize + 1] = previous.masters[*from as usize + 1];
                    monitor.factors[*to as usize + 1] = previous.factors[*from as usize + 1];
                }
            }
        }
        let mut focus = None;
        if self.config.fullscreen_spaces {
            let ids = self
                .clients
                .iter()
                .filter(|c| {
                    c.fullscreen && !c.dock && !self.app_spaces.iter().any(|s| s.client == c.id)
                })
                .map(|c| c.id)
                .collect::<Vec<_>>();
            for id in ids {
                if self.desktop_count() >= 31 {
                    break;
                }
                let saved = self.property(id, self.atoms._CARPATIC_FULLSCREEN_ORIGIN);
                let c = self.clients.iter().find(|c| c.id == id).unwrap();
                let monitor = c.monitor.min(self.monitors.len() - 1);
                let origin_desktop = saved
                    .get(1)
                    .copied()
                    .unwrap_or(c.desktop)
                    .min(self.config.workspaces - 1);
                let tags = saved.first().copied().unwrap_or(c.tags) & normal;
                let view = saved.get(3).copied().unwrap_or(self.monitors[monitor].view) & normal;
                let desktop = self.desktop_count();
                let space = AppSpace {
                    client: id,
                    desktop,
                    tags: if tags == 0 { 1 << origin_desktop } else { tags },
                    origin_desktop,
                    monitor: saved
                        .get(2)
                        .copied()
                        .map(|m| m as usize)
                        .unwrap_or(monitor)
                        .min(self.monitors.len() - 1),
                    view: if view == 0 { 1 << origin_desktop } else { view },
                };
                self.conn.change_property32(
                    PropMode::REPLACE,
                    id,
                    self.atoms._CARPATIC_FULLSCREEN_ORIGIN,
                    AtomEnum::CARDINAL,
                    &[
                        space.tags,
                        space.origin_desktop,
                        space.monitor as u32,
                        space.view,
                    ],
                )?;
                let m = &mut self.monitors[monitor];
                m.previous_view = m.view;
                m.previous_all = m.all_view;
                m.view = 1 << desktop;
                m.desktop = desktop;
                m.all_view = false;
                m.layouts[desktop as usize + 1] = 1;
                self.active_monitor = monitor;
                let c = self.clients.iter_mut().find(|c| c.id == id).unwrap();
                c.desktop = desktop;
                c.tags = 1 << desktop;
                c.applied = None;
                self.app_spaces.push(space);
                focus = Some(id);
                changed = true;
            }
        }
        if changed {
            self.desktop = self.monitors[self.active_monitor].desktop;
            for c in &self.clients {
                self.conn.change_property32(
                    PropMode::REPLACE,
                    c.id,
                    self.atoms._NET_WM_DESKTOP,
                    AtomEnum::CARDINAL,
                    &[c.desktop],
                )?;
                self.conn.change_property32(
                    PropMode::REPLACE,
                    c.id,
                    self.atoms._CARPATIC_TAGS,
                    AtomEnum::CARDINAL,
                    &[c.tags],
                )?;
            }
            self.publish()?;
        }
        Ok(focus)
    }

    fn arrange(&mut self) -> Result<()> {
        let mut publish_frames = Vec::new();
        let space_focus = self.reconcile_app_spaces()?;
        let mode = if self.monitors[self.active_monitor].layouts
            [self.monitors[self.active_monitor].slot()]
            == 1
        {
            b"float".as_slice()
        } else {
            b"tile".as_slice()
        };
        self.conn.change_property8(
            PropMode::REPLACE,
            self.root,
            self.atoms._CARPATIC_LAYOUT,
            AtomEnum::STRING,
            mode,
        )?;

        self.update_workareas()?;
        let mut slots = std::collections::HashMap::new();
        for (index, m) in self.monitors.iter().enumerate() {
            let members: Vec<_> = self
                .clients
                .iter()
                .filter(|c| {
                    c.monitor == index
                        && c.tags & m.view != 0
                        && !c.minimized
                        && !c.dock
                        && c.swallowed_by.is_none()
                        && !c.floating
                        && !c.fullscreen
                })
                .collect();
            let weights: Vec<_> = members.iter().map(|c| c.weight).collect();
            let gap = if self.config.smart_gaps && members.len() == 1 {
                0
            } else {
                self.config.inner_gap
            };
            let outer = if self.config.smart_gaps && members.len() == 1 {
                0
            } else {
                self.config.outer_gap
            };
            let area = inset(m.work, outer);
            let rects = weighted_tile(
                area,
                &weights,
                m.masters[m.slot()],
                m.factors[m.slot()],
                gap,
            );
            for (client, rect) in members.into_iter().zip(rects) {
                slots.insert(client.id, rect);
            }
        }

        let fullscreen_monitors = self
            .clients
            .iter()
            .filter(|c| c.fullscreen && !c.minimized && c.tags & self.monitors[c.monitor].view != 0)
            .map(|c| c.monitor)
            .collect::<Vec<_>>();
        for c in &mut self.clients {
            self.conn.change_window_attributes(
                c.id,
                &ChangeWindowAttributesAux::new().border_pixel(c.border_pixel(
                    if Some(c.id) == self.focused {
                        self.config.border_active
                    } else if c.urgent {
                        self.config.red
                    } else {
                        self.config.border_inactive
                    },
                )),
            )?;
            let m = &self.monitors[c.monitor.min(self.monitors.len() - 1)];
            let layout = m.layouts[m.slot()];
            let visible = ((c.dock && !fullscreen_monitors.contains(&c.monitor))
                || (!c.dock && !self.showing_desktop && c.tags & m.view != 0))
                && !c.minimized
                && c.swallowed_by.is_none();
            if visible && !c.mapped {
                self.conn.map_window(c.id)?;
                c.mapped = true;
            }
            if !visible && c.mapped {
                if c.minimized && self.deferred_unmaps.iter().any(|(w, _)| *w == c.id) {
                    continue;
                }
                if !c.minimized {
                    for window in [c.id, c.titlebar].into_iter().chain(c.frame) {
                        self.conn.change_property32(
                            PropMode::REPLACE,
                            window,
                            self.atoms._CARPATIC_ANIMATION,
                            AtomEnum::CARDINAL,
                            &[3],
                        )?;
                    }
                    self.animation_expiry
                        .retain(|(w, _)| *w != c.id && *w != c.titlebar && c.frame != Some(*w));
                }
                self.conn.unmap_window(c.surface())?;
                c.mapped = false;
                if c.frame.is_none() {
                    c.ignored_unmaps += 1;
                }
            }
            if !visible {
                self.conn.unmap_window(c.titlebar)?;
                continue;
            }
            let mut rect = if c.dock {
                c.floating_rect
            } else if c.fullscreen {
                m.area
            } else if c.max_saved.is_some() {
                if c.snap_maximized {
                    m.work
                } else {
                    inset(m.work, self.config.outer_gap)
                }
            } else if c.floating || layout == 1 {
                clamp(c.floating_rect, m.work)
            } else if layout == 2 {
                inset(m.work, self.config.outer_gap)
            } else {
                slots[&c.id]
            };
            let border = if c.fullscreen || c.dock || c.has_csd {
                0
            } else {
                self.config.border
                    + if Some(c.id) == self.focused {
                        self.config.border_highlight
                    } else {
                        0
                    }
            };
            let title_height = if self.config.titlebar.enabled
                && !c.fullscreen
                && !c.has_csd
                && if c
                    .max_saved
                    .map(|(_, floating)| floating)
                    .unwrap_or(c.floating)
                    || layout == 1
                {
                    self.config.titlebar.floating
                } else {
                    self.config.titlebar.tiled
                } {
                self.renderer
                    .height(&self.config)
                    .min(rect.height.saturating_sub(border * 2 + 1))
            } else {
                0
            };
            let extents = [border, border, border + title_height, border];
            let extents_changed = c.applied_extents != Some(extents);
            if extents_changed {
                self.conn.change_property32(
                    PropMode::REPLACE,
                    c.id,
                    self.atoms._NET_FRAME_EXTENTS,
                    AtomEnum::CARDINAL,
                    &extents,
                )?;
                c.applied_extents = Some(extents);
            }
            let mut width = rect.width.saturating_sub(border * 2).max(1);
            let mut height = rect.height.saturating_sub(border * 2 + title_height).max(1);
            if (c.floating || layout == 1)
                && !c.fullscreen
                && c.max_saved.is_none()
                && !c.snap_constrained
            {
                if let Some(hints) = &c.size_hints {
                    (width, height) = constrain_size(width, height, hints);
                }
                rect.width = width + border * 2;
                rect.height = height + border * 2 + title_height;
                c.floating_rect = rect;
            }
            let geometry_changed =
                c.applied != Some(rect) || c.applied_border != Some(border) || extents_changed;
            if geometry_changed {
                // Restart adoption must restore the actual constrained outer
                // geometry, rather than the pre-hint layout request.
                self.conn.change_property32(
                    PropMode::REPLACE,
                    c.id,
                    self.atoms._CARPATIC_FRAME_GEOMETRY,
                    AtomEnum::CARDINAL,
                    &[rect.x as u32, rect.y as u32, rect.width, rect.height],
                )?;
                self.conn.configure_window(
                    c.id,
                    &ConfigureWindowAux::new()
                        .x(if c.frame.is_some() { 0 } else { rect.x })
                        .y(if c.frame.is_some() {
                            title_height as i32
                        } else {
                            rect.y + title_height as i32
                        })
                        .width(width)
                        .height(height)
                        .border_width(border),
                )?;
                // ConfigureRequest can invalidate applied geometry even for a
                // move. The caption surface depends on its size, not position.
                c.chrome_dirty |= title_height > 0
                    && c.chrome_surface != Some((rect.width, title_height + border));
                c.applied = Some(rect);
                c.applied_border = Some(border);
                self.conn.send_event(
                    false,
                    c.id,
                    EventMask::STRUCTURE_NOTIFY,
                    ConfigureNotifyEvent {
                        response_type: CONFIGURE_NOTIFY_EVENT,
                        sequence: 0,
                        event: c.id,
                        window: c.id,
                        above_sibling: NONE,
                        x: rect.x as i16,
                        y: (rect.y + title_height as i32) as i16,
                        width: width as u16,
                        height: height as u16,
                        border_width: border as u16,
                        override_redirect: false,
                    },
                )?;
            }
            if let Some(frame) = c.frame {
                if geometry_changed {
                    self.conn.configure_window(
                        frame,
                        &ConfigureWindowAux::new()
                            .x(rect.x)
                            .y(rect.y)
                            .width(rect.width)
                            .height(rect.height),
                    )?;
                }
                let shape_key = FrameShapeKey {
                    frame,
                    width: rect.width,
                    height: rect.height,
                    border,
                    title: title_height,
                    radius: self.config.radius,
                    square: c.fullscreen || c.has_csd,
                };
                if c.frame_shape != Some(shape_key) || c.shape_dirty {
                    shape_app_frame(
                        &self.conn,
                        frame,
                        c.id,
                        rect.width,
                        rect.height,
                        border,
                        title_height,
                        self.config.radius,
                        c.fullscreen || c.has_csd,
                    )?;
                    c.shape_dirty = false;
                    c.frame_shape = Some(shape_key);
                }
                publish_frames.push(frame);
            }
            if title_height > 0 {
                if c.chrome_dirty {
                    shape_window(
                        &self.conn,
                        c.titlebar,
                        rect.width,
                        title_height + border,
                        0,
                        self.config.radius,
                        true,
                        false,
                        false,
                    )?;
                }
                self.conn.configure_window(
                    c.titlebar,
                    &ConfigureWindowAux::new()
                        .x(if c.frame.is_some() { 0 } else { rect.x })
                        .y(if c.frame.is_some() { 0 } else { rect.y })
                        .width(rect.width)
                        .height(title_height + border)
                        .sibling(c.id)
                        .stack_mode(StackMode::ABOVE),
                )?;
                self.conn.map_window(c.titlebar)?;
            } else {
                self.conn.unmap_window(c.titlebar)?;
            }
            if c.fullscreen {
                self.conn.configure_window(
                    c.surface(),
                    &ConfigureWindowAux::new().stack_mode(StackMode::ABOVE),
                )?;
            }
        }
        for c in self.clients.iter().filter(|c| c.mapped && c.fullscreen) {
            self.conn.configure_window(
                c.surface(),
                &ConfigureWindowAux::new().stack_mode(StackMode::ABOVE),
            )?;
        }
        self.restack_above_clients()?;
        self.lower_desktop_surfaces()?;
        self.draw_chrome()?;
        for frame in publish_frames {
            self.conn.map_window(frame)?;
        }
        self.draw_bars()?;
        self.client_list()?;
        for id in &self.priority_overlays {
            self.conn
                .configure_window(*id, &ConfigureWindowAux::new().stack_mode(StackMode::ABOVE))?;
        }
        if self.drag.as_ref().is_some_and(|d| d.target.is_some()) {
            self.conn.configure_window(
                self.drop_overlay,
                &ConfigureWindowAux::new().stack_mode(StackMode::ABOVE),
            )?;
        }
        self.enforce_lock_stack()?;
        if let Some(id) = space_focus {
            self.focus(id)?;
        }
        Ok(())
    }

    // Keep the ABOVE layer above ordinary clients without replacing its peer
    // order with management order on every unrelated arrange. The selected
    // peer is highest within its layer, while overlays retain their priority.
    fn restack_above_clients(&self) -> Result<()> {
        let siblings = self.conn.query_tree(self.root)?.reply()?.children;
        let mut above: Vec<_> = self
            .clients
            .iter()
            .filter(|c| c.mapped && c.above)
            .collect();
        above.sort_by_key(|c| {
            (
                Some(c.id) == self.focused,
                siblings
                    .iter()
                    .position(|id| *id == c.surface())
                    .unwrap_or(0),
            )
        });
        for c in above {
            self.conn.configure_window(
                c.surface(),
                &ConfigureWindowAux::new().stack_mode(StackMode::ABOVE),
            )?;
            self.conn.configure_window(
                c.titlebar,
                &ConfigureWindowAux::new()
                    .sibling(c.id)
                    .stack_mode(StackMode::ABOVE),
            )?;
        }
        Ok(())
    }

    fn upload(&self, window: Window, image: &tiny_skia::Pixmap) -> Result<()> {
        let gc = self.conn.generate_id()?;
        self.conn.create_gc(gc, window, &CreateGCAux::new())?;
        let row = image.width() as usize * 4;
        let rows = (60_000 / row).max(1);
        let little = u8::from(self.conn.setup().image_byte_order) == 0;
        let bytes: Vec<u8> = image
            .data()
            .chunks_exact(4)
            .flat_map(|p| {
                if little {
                    [p[2], p[1], p[0], 0]
                } else {
                    [0, p[0], p[1], p[2]]
                }
            })
            .collect();
        for (index, chunk) in bytes.chunks(row * rows).enumerate() {
            self.conn.put_image(
                ImageFormat::Z_PIXMAP,
                window,
                gc,
                image.width() as u16,
                (chunk.len() / row) as u16,
                0,
                (index * rows) as i16,
                0,
                self.conn.setup().roots[0].root_depth,
                chunk,
            )?;
        }
        self.conn.free_gc(gc)?;
        Ok(())
    }

    fn draw_bars(&mut self) -> Result<()> {
        let urgent = self
            .clients
            .iter()
            .filter(|c| c.urgent && !c.dock)
            .fold(0, |tags, c| tags | c.tags);
        self.conn.change_property32(
            PropMode::REPLACE,
            self.root,
            self.atoms._CARPATIC_URGENT_TAGS,
            AtomEnum::CARDINAL,
            &[urgent],
        )?;
        let enabled = self.config.bar_enabled && !self.clients.iter().any(|c| c.dock);
        if !enabled {
            self.conn
                .delete_property(self.root, self.atoms._CARPATIC_MINLIST)?;
            self.tray.release(&self.conn, self.root)?;
            for bar in &self.bars {
                self.conn.unmap_window(bar.id)?;
            }
            return Ok(());
        }
        while self.bars.len() > self.monitors.len() {
            let bar = self.bars.pop().unwrap();
            self.tray.detach(&self.conn, self.root)?;
            self.conn.destroy_window(bar.id)?;
        }
        while self.bars.len() < self.monitors.len() {
            let id = self.conn.generate_id()?;
            self.conn.create_window(
                0,
                id,
                self.root,
                0,
                0,
                1,
                1,
                0,
                WindowClass::INPUT_OUTPUT,
                0,
                &CreateWindowAux::new()
                    .override_redirect(1)
                    .event_mask(EventMask::EXPOSURE | EventMask::BUTTON_PRESS),
            )?;
            self.bars.push(Bar {
                id,
                monitor: self.bars.len(),
                hits: Vec::new(),
            });
        }
        if self.config.tray_enabled {
            self.tray.claim(&self.conn, self.root)?;
        } else {
            self.tray.release(&self.conn, self.root)?;
        }
        let status = self.window_title(self.root);
        for index in 0..self.bars.len() {
            let m = &self.monitors[index];
            let height = self.config.bar_height.max(1);
            let occupied = self
                .clients
                .iter()
                .filter(|c| c.monitor == index && !c.dock)
                .fold(0, |tags, c| tags | c.tags);
            let minimized: Vec<_> = self
                .clients
                .iter()
                .filter(|c| c.monitor == index && c.minimized && c.tags & m.view != 0)
                .map(|c| (c.id, c.title.clone()))
                .collect();
            let title = self
                .clients
                .iter()
                .find(|c| Some(c.id) == self.focused && c.monitor == index);
            let title = Label {
                text: title.map(|c| c.title.as_str()).unwrap_or(""),
                icon: title.and_then(|c| c.icon.as_ref()),
            };
            let tray_width = if index == self.active_monitor && self.config.tray_enabled {
                self.tray.width(self.config.tray_size, self.config.tray_gap)
            } else {
                0
            };
            let (image, hits, tray_x) = self.renderer.bar(
                &self.desktop_config(),
                m.area.width,
                height,
                m.view,
                occupied,
                urgent,
                m.layouts[m.slot()],
                title,
                &status,
                &minimized,
                tray_width,
            );
            let id = self.bars[index].id;
            if self
                .clients
                .iter()
                .any(|c| c.monitor == index && c.mapped && c.fullscreen)
            {
                self.conn.unmap_window(id)?;
                continue;
            }
            self.conn.configure_window(
                id,
                &ConfigureWindowAux::new()
                    .x(m.area.x)
                    .y(m.area.y)
                    .width(m.area.width)
                    .height(height)
                    .stack_mode(StackMode::ABOVE),
            )?;
            self.conn.map_window(id)?;
            self.upload(id, &image)?;
            if index == 0 {
                let rects: Vec<_> = hits
                    .iter()
                    .filter(|h| matches!(h.action, BarAction::Restore(_)))
                    .flat_map(|h| [h.left as u32, h.right as u32, m.area.y as u32, height])
                    .collect();
                if rects.is_empty() {
                    self.conn
                        .delete_property(self.root, self.atoms._CARPATIC_MINLIST)?;
                } else {
                    self.conn.change_property32(
                        PropMode::REPLACE,
                        self.root,
                        self.atoms._CARPATIC_MINLIST,
                        AtomEnum::CARDINAL,
                        &rects,
                    )?;
                }
            }
            self.bars[index].hits = hits;
            if index == self.active_monitor && self.config.tray_enabled {
                self.tray.layout(
                    &self.conn,
                    self.root,
                    id,
                    tray_x,
                    height,
                    self.config.tray_size,
                    self.config.tray_gap,
                    self.config.inactive_background,
                )?;
            }
        }
        self.enforce_lock_stack()
    }

    fn draw_chrome(&mut self) -> Result<()> {
        for c in &mut self.clients {
            if !c.chrome_dirty
                || !c.mapped
                || c.fullscreen
                || c.has_csd
                || !self.config.titlebar.enabled
            {
                continue;
            }
            let Some(rect) = c.applied else {
                continue;
            };
            let mut chrome = self.config.clone();
            chrome.border = c.applied_border.unwrap_or(self.config.border);
            // Arrangement may clamp the native caption for a tiny outer frame.
            // Paint and hit regions must use the published title-plus-border
            // extent, rather than allocating a nominal-height hidden canvas.
            let height = c.caption_height();
            let image = self.renderer.title(
                &chrome,
                rect.width,
                height,
                Label {
                    text: &c.title,
                    icon: c.icon.as_ref(),
                },
                Some(c.id) == self.focused,
                (c.hover, c.pressed, c.max_saved.is_some()),
            );
            let hits = self.renderer.hits(&self.config, rect.width, height);
            let mut buttons = [0u32; 6];
            for hit in hits {
                let i = match hit.button {
                    Button::Minimize => 0,
                    Button::Maximize => 2,
                    Button::Close => 4,
                };
                buttons[i] = hit.left.max(0) as u32;
                buttons[i + 1] = hit.right.max(0) as u32;
            }
            self.conn.change_property32(
                PropMode::REPLACE,
                c.titlebar,
                self.atoms._CARPATIC_BUTTONS,
                AtomEnum::CARDINAL,
                &buttons,
            )?;
            // Upload into an off-screen pixmap, then publish the whole chrome
            // with one CopyArea. Picom must never sample a half-uploaded title
            // image between the row chunks required by X11 request limits.
            let pixmap = self.conn.generate_id()?;
            self.conn.create_pixmap(
                self.conn.setup().roots[0].root_depth,
                pixmap,
                c.titlebar,
                rect.width as u16,
                height as u16,
            )?;
            let gc = self.conn.generate_id()?;
            self.conn
                .create_gc(gc, pixmap, &CreateGCAux::new().graphics_exposures(0))?;
            let bpp = 4usize;
            let row_bytes = rect.width as usize * bpp;
            let chunk_rows = (60_000 / row_bytes).max(1);
            let little = u8::from(self.conn.setup().image_byte_order) == 0;
            let data: Vec<u8> = image
                .data()
                .chunks_exact(4)
                .flat_map(|p| {
                    if little {
                        [p[2], p[1], p[0], 0]
                    } else {
                        [0, p[0], p[1], p[2]]
                    }
                })
                .collect();
            for (part, bytes) in data.chunks(row_bytes * chunk_rows).enumerate() {
                self.conn.put_image(
                    ImageFormat::Z_PIXMAP,
                    pixmap,
                    gc,
                    rect.width as u16,
                    (bytes.len() / row_bytes) as u16,
                    0,
                    (part * chunk_rows) as i16,
                    0,
                    self.conn.setup().roots[0].root_depth,
                    bytes,
                )?;
            }
            self.conn.change_window_attributes(
                c.titlebar,
                &ChangeWindowAttributesAux::new().background_pixmap(pixmap),
            )?;
            self.conn.copy_area(
                pixmap,
                c.titlebar,
                gc,
                0,
                0,
                0,
                0,
                rect.width as u16,
                height as u16,
            )?;
            self.conn.free_gc(gc)?;
            self.conn.free_pixmap(pixmap)?;
            c.chrome_dirty = false;
            c.chrome_surface = Some((rect.width, height));
        }
        Ok(())
    }

    fn client_border_pixel(&self, id: Window, color: u32) -> u32 {
        self.clients
            .iter()
            .find(|c| c.id == id)
            .map_or(color, |c| c.border_pixel(color))
    }

    fn focus(&mut self, id: Window) -> Result<()> {
        if self.desktop_surfaces.contains(&id) {
            if let Some(old) = self.focused {
                if let Some(client) = self.clients.iter_mut().find(|client| client.id == old) {
                    client.chrome_dirty = true;
                }
                self.conn.change_window_attributes(
                    old,
                    &ChangeWindowAttributesAux::new()
                        .border_pixel(self.client_border_pixel(old, self.config.border_inactive)),
                )?;
            }
            self.focused = None;
            let accepts_input = x11rb::properties::WmHints::get(&self.conn, id)?
                .reply()?
                .and_then(|hints| hints.input)
                .unwrap_or(true);
            if accepts_input {
                // A programmatic activation may follow a newer focus change;
                // the last observed PropertyNotify time can then be stale.
                self.conn
                    .set_input_focus(InputFocus::POINTER_ROOT, id, CURRENT_TIME)?;
            }
            if self
                .property(id, self.atoms.WM_PROTOCOLS)
                .contains(&self.atoms.WM_TAKE_FOCUS)
            {
                self.conn.send_event(
                    false,
                    id,
                    EventMask::NO_EVENT,
                    ClientMessageEvent::new(
                        32,
                        id,
                        self.atoms.WM_PROTOCOLS,
                        [self.atoms.WM_TAKE_FOCUS, self.last_time, 0, 0, 0],
                    ),
                )?;
            }
            self.conn.change_property32(
                PropMode::REPLACE,
                self.root,
                self.atoms._NET_ACTIVE_WINDOW,
                AtomEnum::WINDOW,
                &[id],
            )?;
            self.draw_chrome()?;
            self.draw_bars()?;
            return Ok(());
        }
        if let Some(index) = self
            .clients
            .iter()
            .find(|c| c.id == id && !c.dock)
            .map(|c| c.monitor)
        {
            self.active_monitor = index;
            self.desktop = self.monitors[index].desktop;
            self.master = self.monitors[index].factors[self.monitors[index].slot()];
            self.conn.change_property32(
                PropMode::REPLACE,
                self.root,
                self.atoms._NET_CURRENT_DESKTOP,
                AtomEnum::CARDINAL,
                &[self.desktop],
            )?;
        }

        if !self.clients.iter().any(|c| {
            c.id == id
                && c.tags & self.monitors[c.monitor].view != 0
                && !c.minimized
                && !c.dock
                && c.swallowed_by.is_none()
        }) {
            return Ok(());
        }
        if !self.clients.iter().any(|c| c.id == id && c.mapped) {
            return Ok(());
        }
        let urgent = self.clients.iter().any(|c| c.id == id && c.urgent);
        if urgent {
            if let Some(c) = self.clients.iter_mut().find(|c| c.id == id) {
                c.urgent = false;
            }
            if let Some(mut hints) = x11rb::properties::WmHints::get(&self.conn, id)?.reply()? {
                if hints.urgent {
                    hints.urgent = false;
                    hints.set(&self.conn, id)?;
                }
            }
            self.sync_states(id)?;
        }
        if let Some(old) = self.focused {
            if let Some(c) = self.clients.iter_mut().find(|c| c.id == old) {
                c.chrome_dirty = true;
            }
            self.conn.change_window_attributes(
                old,
                &ChangeWindowAttributesAux::new()
                    .border_pixel(self.client_border_pixel(old, self.config.border_inactive)),
            )?;
        }
        let changed = self.focused != Some(id);
        self.focused = Some(id);
        if let Some(c) = self.clients.iter_mut().find(|c| c.id == id) {
            c.chrome_dirty = true;
        }
        if self
            .clients
            .iter()
            .find(|c| c.id == id)
            .is_some_and(|c| c.input)
        {
            self.conn
                .set_input_focus(InputFocus::POINTER_ROOT, id, CURRENT_TIME)?;
        }
        self.conn.change_window_attributes(
            id,
            &ChangeWindowAttributesAux::new()
                .border_pixel(self.client_border_pixel(id, self.config.border_active)),
        )?;
        let raise = self.clients.iter().any(|c| {
            c.id == id
                && (c.floating
                    || c.fullscreen
                    || self.monitors[c.monitor].layouts[self.monitors[c.monitor].slot()] == 1)
        });
        if raise {
            self.conn.configure_window(
                self.clients.iter().find(|c| c.id == id).unwrap().surface(),
                &ConfigureWindowAux::new().stack_mode(StackMode::ABOVE),
            )?;
        }
        if self
            .property(id, self.atoms.WM_PROTOCOLS)
            .contains(&self.atoms.WM_TAKE_FOCUS)
        {
            self.protocol(id, self.atoms.WM_TAKE_FOCUS)?;
        }
        self.conn.change_property32(
            PropMode::REPLACE,
            self.root,
            self.atoms._NET_ACTIVE_WINDOW,
            AtomEnum::WINDOW,
            &[id],
        )?;
        if let Some(c) = self.clients.iter().find(|c| c.id == id) {
            if !c.fullscreen {
                self.conn.configure_window(
                    c.titlebar,
                    &ConfigureWindowAux::new()
                        .sibling(id)
                        .stack_mode(StackMode::ABOVE),
                )?;
            }
        }
        if changed && self.config.border_highlight > 0 {
            self.arrange()?;
        } else {
            self.draw_chrome()?;
            self.draw_bars()?;
        }
        if raise {
            self.restack_above_clients()?;
            for overlay in &self.priority_overlays {
                self.conn.configure_window(
                    *overlay,
                    &ConfigureWindowAux::new().stack_mode(StackMode::ABOVE),
                )?;
            }
            self.enforce_lock_stack()?;
            self.client_list()?;
        }
        Ok(())
    }

    fn focus_available(&mut self) -> Result<()> {
        if let Some(id) = self
            .clients
            .iter()
            .find(|c| {
                !self.showing_desktop
                    && c.mapped
                    && c.monitor == self.active_monitor
                    && c.tags & self.monitors[c.monitor].view != 0
                    && !c.minimized
                    && !c.dock
                    && c.swallowed_by.is_none()
            })
            .map(|c| c.id)
        {
            self.focus(id)?;
        } else {
            self.focused = None;
            self.conn
                .set_input_focus(InputFocus::POINTER_ROOT, self.root, CURRENT_TIME)?;
            self.conn.change_property32(
                PropMode::REPLACE,
                self.root,
                self.atoms._NET_ACTIVE_WINDOW,
                AtomEnum::WINDOW,
                &[NONE],
            )?;
        }
        Ok(())
    }

    fn show_desktop(&mut self, on: bool) -> Result<()> {
        self.showing_desktop = on;
        self.conn.change_property32(
            PropMode::REPLACE,
            self.root,
            self.atoms._NET_SHOWING_DESKTOP,
            AtomEnum::CARDINAL,
            &[u32::from(on)],
        )?;
        self.arrange()?;
        self.focus_available()
    }
    fn set_view(&mut self, view: u32, all_view: bool) -> Result<()> {
        let view = view & ((1 << self.desktop_count()) - 1);
        if view == 0 {
            return Ok(());
        }
        let m = &mut self.monitors[self.active_monitor];
        if m.view != view || m.all_view != all_view {
            m.previous_view = m.view;
            m.previous_all = m.all_view;
        }
        m.view = view;
        m.all_view = all_view;
        m.desktop = view.trailing_zeros();
        self.desktop = m.desktop;
        self.master = m.factors[m.slot()];
        self.conn.change_property32(
            PropMode::REPLACE,
            self.root,
            self.atoms._NET_CURRENT_DESKTOP,
            AtomEnum::CARDINAL,
            &[self.desktop],
        )?;
        self.arrange()?;
        self.focus_available()
    }
    fn switch(&mut self, desktop: u32) -> Result<()> {
        if desktop >= self.desktop_count() {
            return Ok(());
        }
        if self.showing_desktop {
            self.show_desktop(false)?;
        }
        self.set_view(1 << desktop, false)
    }

    fn protocol(&self, id: Window, atom: Atom) -> Result<()> {
        let event = ClientMessageEvent::new(
            32,
            id,
            self.atoms.WM_PROTOCOLS,
            [atom, self.last_time, 0, 0, 0],
        );
        self.conn
            .send_event(false, id, EventMask::NO_EVENT, event)?;
        Ok(())
    }

    fn close(&self, id: Window) -> Result<()> {
        if self
            .property(id, self.atoms.WM_PROTOCOLS)
            .contains(&self.atoms.WM_DELETE_WINDOW)
        {
            self.protocol(id, self.atoms.WM_DELETE_WINDOW)?;
        } else {
            self.conn.kill_client(id)?;
        }
        Ok(())
    }

    fn float(&mut self, id: Window) -> Result<()> {
        if self
            .clients
            .iter()
            .any(|c| c.id == id && c.max_saved.is_some())
        {
            return self.maximize(id);
        }
        let Some(index) = self
            .clients
            .iter()
            .position(|c| c.id == id && !c.fullscreen && !c.dock)
        else {
            return Ok(());
        };
        if self.clients[index]
            .size_hints
            .as_ref()
            .is_some_and(|h| h.min_size.is_some() && h.min_size == h.max_size)
        {
            return Ok(());
        }
        let was = self.clients[index].floating;
        let slot = self.clients[index].tile_slot;
        let rect = self.clients[index]
            .applied
            .unwrap_or(self.clients[index].floating_rect);
        if was {
            if let Some(slot) = slot {
                let c = self.clients.remove(index);
                self.clients.insert(slot.min(self.clients.len()), c);
            }
        }
        let c = self.clients.iter_mut().find(|c| c.id == id).unwrap();
        if !was {
            c.tile_slot = Some(index);
            c.floating_rect = rect;
        }
        c.floating = !was;
        c.applied = None;
        self.sync_states(id)?;
        self.arrange()?;
        if !was {
            self.detach_rect(id, rect)?;
        }
        self.focus(id)
    }

    fn change_states(&mut self, id: Window, action: u32, atoms: [Atom; 2]) -> Result<()> {
        if action > 2 {
            return Ok(());
        }
        let desired = |current: bool| match action {
            0 => false,
            1 => true,
            _ => !current,
        };
        if let Some(c) = self.clients.iter_mut().find(|c| c.id == id) {
            for (index, atom) in atoms.into_iter().enumerate() {
                if atom == NONE || (index == 1 && atoms[0] == atom) {
                    continue;
                }
                if atom == self.atoms._NET_WM_STATE_FULLSCREEN {
                    let on = desired(c.fullscreen || c.fake_fullscreen);
                    if c.fake_fullscreen {
                        c.fake_fullscreen = on;
                        c.fullscreen = false;
                    } else {
                        c.fullscreen = on;
                    }
                    c.applied = None;
                } else if atom == self.atoms._NET_WM_STATE_ABOVE {
                    c.above = desired(c.above);
                } else if atom == self.atoms._NET_WM_STATE_DEMANDS_ATTENTION {
                    c.urgent = desired(c.urgent) && self.focused != Some(c.id);
                } else if atom == self.atoms._NET_WM_STATE_MAXIMIZED_VERT
                    || atom == self.atoms._NET_WM_STATE_MAXIMIZED_HORZ
                {
                    // Both maximize atoms describe the same saved geometry, so apply once.
                    if index == 1
                        && [
                            self.atoms._NET_WM_STATE_MAXIMIZED_VERT,
                            self.atoms._NET_WM_STATE_MAXIMIZED_HORZ,
                        ]
                        .contains(&atoms[0])
                    {
                        continue;
                    }
                    let on = desired(c.max_saved.is_some());
                    if on && c.max_saved.is_none() {
                        c.max_saved = Some((
                            if c.fullscreen {
                                c.floating_rect
                            } else {
                                c.applied.unwrap_or(c.floating_rect)
                            },
                            c.floating,
                        ));
                        c.floating = true;
                    }
                    if !on {
                        if let Some((rect, floating)) = c.max_saved.take() {
                            c.floating_rect = rect;
                            c.floating = floating;
                        }
                    }
                    c.applied = None;
                }
            }
            self.sync_states(id)?;
            self.arrange()?;
        } else if atoms.contains(&self.atoms._NET_WM_STATE_ABOVE) {
            let mut states = self.property(id, self.atoms._NET_WM_STATE);
            let on = desired(states.contains(&self.atoms._NET_WM_STATE_ABOVE));
            states.retain(|a| *a != self.atoms._NET_WM_STATE_ABOVE);
            if on {
                states.push(self.atoms._NET_WM_STATE_ABOVE);
            }
            self.conn.change_property32(
                PropMode::REPLACE,
                id,
                self.atoms._NET_WM_STATE,
                AtomEnum::ATOM,
                &states,
            )?;
            self.track_overlay(id)?;
            self.arrange()?;
        }
        Ok(())
    }

    fn fullscreen(&mut self, id: Window, action: u32) -> Result<()> {
        if let Some(c) = self.clients.iter_mut().find(|c| c.id == id) {
            c.fullscreen = match action {
                0 => false,
                1 => true,
                _ => !c.fullscreen,
            };
            c.applied = None;
        }
        self.sync_states(id)?;
        self.arrange()
    }

    fn key(&mut self, event: KeyPressEvent) -> Result<()> {
        let active_slot = self.monitors[self.active_monitor].slot();
        let state = u16::from(event.state) & !(2 | 16);
        let sym = self
            .keys
            .iter()
            .find(|(code, _)| *code == event.detail)
            .map(|(_, sym)| *sym)
            .unwrap_or(0);
        if let Some(binding) = self
            .bindings
            .iter()
            .find(|b| keysym(&b.key) == Some(sym) && modifier_mask(&b.modifiers) == state)
            .cloned()
        {
            return self.action(&binding);
        }
        if !self.bindings.is_empty() {
            return Ok(());
        }
        let state = u16::from(event.state) & !(2 | 16);
        if state & SUPER == 0 {
            return Ok(());
        }
        let symbol = self
            .keys
            .iter()
            .find(|(code, _)| *code == event.detail)
            .map(|(_, sym)| *sym)
            .unwrap_or(0);
        let shift = state & 1 != 0;
        match symbol {
            0x31..=0x39 => {
                let desktop = symbol - 0x31;
                if desktop >= self.desktop_count() {
                    return Ok(());
                }
                if shift {
                    if let Some(c) = self.clients.iter_mut().find(|c| Some(c.id) == self.focused) {
                        c.desktop = desktop;
                        c.tags = 1 << desktop;
                        self.conn.change_property32(
                            PropMode::REPLACE,
                            c.id,
                            self.atoms._NET_WM_DESKTOP,
                            AtomEnum::CARDINAL,
                            &[desktop],
                        )?;
                    }
                    self.arrange()?;
                    self.focus_available()?;
                } else {
                    self.switch(desktop)?;
                }
            }
            0x20 if shift => {
                if let Some(id) = self.focused {
                    self.float(id)?;
                }
            }
            0x74 => {
                self.monitors[self.active_monitor].layouts[active_slot] =
                    u8::from(self.monitors[self.active_monitor].layouts[active_slot] == 0);
                self.invalidate_layout()?;
            }
            0x6e => {
                if let Some(id) = self.focused {
                    self.minimize(id)?;
                }
            }
            0x6d if shift => {
                if let Some(id) = self
                    .clients
                    .iter()
                    .rev()
                    .filter(|c| {
                        c.minimized
                            && c.monitor == self.active_monitor
                            && c.tags & self.monitors[c.monitor].view != 0
                    })
                    .max_by_key(|c| c.min_stamp)
                    .map(|c| c.id)
                {
                    self.restore(id)?;
                }
            }
            0x7a => {
                if let Some(id) = self.focused {
                    self.maximize(id)?;
                }
            }
            0x66 => {
                if let Some(id) = self.focused {
                    self.fullscreen(id, 2)?;
                }
            }
            0x71 if shift => self.running = false,
            0x71 => {
                if let Some(id) = self.focused {
                    self.close(id)?;
                }
            }
            0x6a | 0x6b => {
                let ids: Vec<_> = self
                    .clients
                    .iter()
                    .filter(|c| {
                        c.monitor == self.active_monitor
                            && c.tags & self.monitors[c.monitor].view != 0
                            && !c.minimized
                            && !c.dock
                            && c.swallowed_by.is_none()
                    })
                    .map(|c| c.id)
                    .collect();
                if !ids.is_empty() {
                    let position = ids
                        .iter()
                        .position(|id| Some(*id) == self.focused)
                        .unwrap_or(0);
                    let next =
                        (position + if symbol == 0x6a { 1 } else { ids.len() - 1 }) % ids.len();
                    self.focus(ids[next])?;
                }
            }
            0x68 | 0x6c => {
                self.master =
                    (self.master as i32 + if symbol == 0x68 { -5 } else { 5 }).clamp(20, 80) as u32;
                self.monitors[self.active_monitor].factors[active_slot] = self.master;
                self.arrange()?;
            }
            0xff0d => {
                let terminal =
                    std::env::var("CARPATIC_TERMINAL").unwrap_or_else(|_| "xterm".into());
                match Command::new(terminal).spawn() {
                    Ok(mut child) => {
                        std::thread::spawn(move || {
                            let _ = child.wait();
                        });
                    }
                    Err(error) => eprintln!("Could not open terminal: {error}"),
                }
            }
            _ => (),
        }
        Ok(())
    }

    fn handle(&mut self, event: Event) -> Result<()> {
        match &event {
            Event::KeyPress(e) => self.last_time = e.time,
            Event::ButtonPress(e) | Event::ButtonRelease(e) => self.last_time = e.time,
            Event::MotionNotify(e) => self.last_time = e.time,
            Event::PropertyNotify(e) => self.last_time = e.time,
            _ => {}
        }
        match event {
            Event::SelectionClear(e) if e.selection == self.tray.selection() => {
                self.tray.lost();
                self.tray.release(&self.conn, self.root)?;
                self.draw_bars()?;
            }
            Event::ClientMessage(e) if e.type_ == self.tray.opcode() => {
                let data = e.data.as_data32();
                if data[1] == 0 {
                    self.tray.dock(&self.conn, data[2])?;
                    self.draw_bars()?;
                }
            }
            Event::PropertyNotify(e)
                if self.tray.is_icon(e.window) && e.atom == self.tray.info() =>
            {
                self.tray.update_info(&self.conn, e.window)?;
                self.draw_bars()?;
            }
            Event::DestroyNotify(e) if self.tray.is_icon(e.window) => {
                self.tray.remove(e.window);
                self.draw_bars()?;
            }
            Event::ConfigureRequest(e) if self.tray.is_icon(e.window) => {
                self.draw_bars()?;
            }
            Event::MapRequest(e) if self.tray.is_icon(e.window) => {
                self.tray.update_info(&self.conn, e.window)?;
                self.draw_bars()?;
            }
            Event::UnmapNotify(e) if self.tray.is_icon(e.window) => {}
            Event::MapNotify(e) => {
                self.track_overlay(e.window)?;
                self.enforce_lock_stack()?;
            }
            Event::ShapeNotify(e) => {
                if let Some(c) = self.clients.iter_mut().find(|c| c.id == e.affected_window) {
                    c.shape_dirty = true;
                    self.arrange()?;
                }
            }
            Event::MapRequest(e) => {
                if self.showing_desktop {
                    self.show_desktop(false)?;
                }
                if self.clients.iter().any(|c| c.id == e.window) {
                    self.restore(e.window)?;
                } else {
                    self.manage(e.window)?;
                }
            }
            Event::PropertyNotify(e)
                if e.atom == u32::from(AtomEnum::WM_NORMAL_HINTS)
                    || e.atom == u32::from(AtomEnum::WM_HINTS) =>
            {
                let size = x11rb::properties::WmSizeHints::get_normal_hints(&self.conn, e.window)
                    .ok()
                    .and_then(|c| c.reply().ok())
                    .flatten();
                let hints = x11rb::properties::WmHints::get(&self.conn, e.window)
                    .ok()
                    .and_then(|c| c.reply().ok())
                    .flatten();
                let input = hints.as_ref().and_then(|h| h.input).unwrap_or(true);
                let urgent =
                    hints.as_ref().is_some_and(|h| h.urgent) && self.focused != Some(e.window);
                if let Some(c) = self.clients.iter_mut().find(|c| c.id == e.window) {
                    c.size_hints = size;
                    c.input = input;
                    c.urgent = urgent;
                    c.applied = None;
                }
                self.sync_states(e.window)?;
                self.arrange()?;
            }
            Event::PropertyNotify(e)
                if e.atom == self.atoms._MOTIF_WM_HINTS
                    || e.atom == self.atoms._GTK_FRAME_EXTENTS =>
            {
                let motif = self.property(e.window, self.atoms._MOTIF_WM_HINTS);
                let has_csd = !self
                    .property(e.window, self.atoms._GTK_FRAME_EXTENTS)
                    .is_empty()
                    || motif.len() >= 3 && motif[0] & 2 != 0 && motif[2] == 0;
                if let Some(c) = self.clients.iter_mut().find(|c| c.id == e.window) {
                    c.has_csd = c.dock || has_csd;
                    c.applied = None;
                    c.chrome_dirty = true;
                }
                self.ensure_app_frame(e.window)?;
                self.arrange()?;
            }
            Event::PropertyNotify(e)
                if e.atom == self.atoms._NET_WM_STRUT_PARTIAL
                    || e.atom == self.atoms._NET_WM_STRUT =>
            {
                self.arrange()?
            }
            // Each event describes one damaged rectangle; redraw the complete
            // surface once the server has delivered the last rectangle.
            Event::Expose(e) if e.count > 0 => {}
            Event::Expose(e) if self.bars.iter().any(|bar| bar.id == e.window) => {
                self.draw_bars()?;
            }
            Event::Expose(e) => {
                if let Some(c) = self.clients.iter_mut().find(|c| c.titlebar == e.window) {
                    c.chrome_dirty = true;
                }
                self.draw_chrome()?;
            }
            Event::LeaveNotify(e) => {
                if let Some(c) = self.clients.iter_mut().find(|c| c.titlebar == e.event) {
                    c.hover = None;
                    c.chrome_dirty = true;
                }
                self.draw_chrome()?;
            }
            Event::PropertyNotify(e) if e.atom == self.atoms._NET_WM_ICON => {
                let icon = self.window_icon(e.window);
                if let Some(c) = self.clients.iter_mut().find(|c| c.id == e.window) {
                    c.icon = icon;
                    c.chrome_dirty = true;
                }
                self.draw_chrome()?;
                self.draw_bars()?;
            }
            Event::PropertyNotify(e)
                if e.atom == self.atoms._NET_WM_NAME
                    || e.atom == u32::from(AtomEnum::WM_NAME)
                    || e.atom == u32::from(AtomEnum::WM_CLASS) =>
            {
                if !self.clients.iter().any(|c| c.id == e.window) {
                    self.track_overlay(e.window)?;
                }
                let title = self.window_title(e.window);
                if let Some(c) = self.clients.iter_mut().find(|c| c.id == e.window) {
                    c.title = title;
                    c.chrome_dirty = true;
                }
                self.draw_chrome()?;
                self.draw_bars()?;
            }
            Event::DestroyNotify(e) => {
                self.priority_overlays.retain(|id| *id != e.window);
                self.lock_overlays.retain(|id| *id != e.window);
                self.remove(e.window)?;
            }
            Event::UnmapNotify(e) => {
                if self.desktop_surfaces.contains(&e.window) {
                    self.remove(e.window)?;
                }
                self.lock_overlays.retain(|id| *id != e.window);
                if let Some(c) = self.clients.iter_mut().find(|c| c.id == e.window) {
                    if c.ignored_unmaps > 0 {
                        c.ignored_unmaps -= 1;
                    } else {
                        self.remove(e.window)?;
                    }
                }
            }
            Event::EnterNotify(e)
                if self.drag.is_none()
                    && e.mode == NotifyMode::NORMAL
                    && e.detail != NotifyDetail::INFERIOR =>
            {
                if self.config.focus_follows_mouse && self.last_pointer != (e.root_x, e.root_y) {
                    self.last_pointer = (e.root_x, e.root_y);
                    let id = self
                        .clients
                        .iter()
                        .find(|c| c.frame == Some(e.event) || c.titlebar == e.event)
                        .map(|c| c.id)
                        .unwrap_or(e.event);
                    self.focus(id)?;
                }
            }
            Event::KeyPress(e)
                if self.drag.is_some()
                    && self
                        .keys
                        .iter()
                        .any(|(code, sym)| *code == e.detail && *sym == 0xff1b) =>
            {
                self.end_drag(true)?;
            }
            Event::KeyPress(e) => self.key(e)?,
            Event::MappingNotify(_) => self.bind_keys()?,
            Event::RandrScreenChangeNotify(_) | Event::RandrNotify(_) => self.refresh_monitors()?,
            Event::ConfigureNotify(e) if e.window == self.root => {
                self.area.width = u32::from(e.width);
                self.area.height = u32::from(e.height);
                self.refresh_monitors()?;
                self.publish()?;
                self.arrange()?;
            }
            Event::ConfigureNotify(e) if self.desktop_surfaces.contains(&e.window) => {
                self.lower_desktop_surfaces()?
            }
            Event::ConfigureNotify(_) => self.enforce_lock_stack()?,
            Event::ConfigureRequest(e) => {
                if self.desktop_surfaces.contains(&e.window) {
                    let mut geometry = ConfigureWindowAux::from_configure_request(&e);
                    geometry.sibling = None;
                    geometry.stack_mode = Some(StackMode::BELOW);
                    self.conn.configure_window(e.window, &geometry)?;
                    return Ok(());
                }
                if e.value_mask.contains(ConfigWindow::STACK_MODE) {
                    if let Some(client) = self.clients.iter().find(|c| c.id == e.window) {
                        let mut stacking = ConfigureWindowAux::new().stack_mode(e.stack_mode);
                        if e.value_mask.contains(ConfigWindow::SIBLING) {
                            let sibling = self
                                .clients
                                .iter()
                                .find(|c| c.id == e.sibling)
                                .map(Client::surface)
                                .unwrap_or(e.sibling);
                            if sibling != client.surface() {
                                stacking = stacking.sibling(sibling);
                            }
                        }
                        self.conn.configure_window(client.surface(), &stacking)?;
                    }
                }
                if let Some(c) = self.clients.iter_mut().find(|c| c.id == e.window) {
                    if c.dock {
                        if e.value_mask.contains(ConfigWindow::X) {
                            c.floating_rect.x = e.x.into();
                        }
                        if e.value_mask.contains(ConfigWindow::Y) {
                            c.floating_rect.y = e.y.into();
                        }
                        if e.value_mask.contains(ConfigWindow::WIDTH) {
                            c.floating_rect.width = e.width.into();
                        }
                        if e.value_mask.contains(ConfigWindow::HEIGHT) {
                            c.floating_rect.height = e.height.into();
                        }
                        self.conn.configure_window(
                            e.window,
                            &ConfigureWindowAux::from_configure_request(&e),
                        )?;
                        c.applied = None;
                        self.arrange()?;
                        return Ok(());
                    }
                    if (c.floating
                        || self.monitors[c.monitor].layouts
                            [self.monitors[c.monitor].desktop as usize]
                            == 1)
                        && !c.fullscreen
                        && !c.snap_constrained
                    {
                        if e.value_mask.contains(ConfigWindow::X) {
                            c.floating_rect.x = e.x.into();
                        }
                        if e.value_mask.contains(ConfigWindow::Y) {
                            c.floating_rect.y = e.y.into();
                        }
                        let border = if c.has_csd { 0 } else { self.config.border };
                        if e.value_mask.contains(ConfigWindow::WIDTH) {
                            c.floating_rect.width = u32::from(e.width) + border * 2;
                        }
                        if e.value_mask.contains(ConfigWindow::HEIGHT) {
                            let title = if self.config.titlebar.enabled
                                && self.config.titlebar.floating
                                && !c.has_csd
                            {
                                self.renderer.height(&self.config)
                            } else {
                                0
                            };
                            c.floating_rect.height = u32::from(e.height) + border * 2 + title;
                        }
                        c.applied = None;
                    }
                    // Tiled clients receive their real geometry, even if layout did not change.
                    if c.snap_constrained
                        || (!c.floating
                            && self.monitors[c.monitor].layouts
                                [self.monitors[c.monitor].desktop as usize]
                                != 1)
                    {
                        c.applied = None;
                    }
                    self.arrange()?;
                } else {
                    self.conn.configure_window(
                        e.window,
                        &ConfigureWindowAux::from_configure_request(&e),
                    )?;
                }
            }
            Event::ButtonPress(e) if self.bars.iter().any(|bar| bar.id == e.event) => {
                let bar = self.bars.iter().find(|bar| bar.id == e.event).unwrap();
                let action = bar
                    .hits
                    .iter()
                    .find(|hit| {
                        i32::from(e.event_x) >= hit.left && i32::from(e.event_x) < hit.right
                    })
                    .map(|hit| hit.action.clone());
                let context = match action {
                    Some(BarAction::Tag(_)) => "ClkTagBar",
                    Some(BarAction::Layout) => "ClkLtSymbol",
                    Some(BarAction::Restore(_)) => "ClkWinTitle",
                    _ => "ClkStatusText",
                };
                let custom = self
                    .mouse_bindings
                    .iter()
                    .find(|b| {
                        b.context == context
                            && b.button == e.detail
                            && modifier_mask(&b.binding.modifiers)
                                == (u16::from(e.state) & !(2 | 16))
                    })
                    .map(|b| b.binding.clone());
                self.active_monitor = bar.monitor;
                self.desktop = self.monitors[self.active_monitor].desktop;
                if let Some(mut binding) = custom {
                    if let Some(BarAction::Tag(tags)) = action {
                        if binding.ui == 0 {
                            binding.ui = tags as i64;
                        }
                    }
                    self.action(&binding)?;
                    return Ok(());
                }
                match action {
                    Some(BarAction::Tag(tags)) => self.switch(tags.trailing_zeros())?,
                    Some(BarAction::Layout) => {
                        let slot = self.monitors[self.active_monitor].slot();
                        let layout = &mut self.monitors[self.active_monitor].layouts[slot];
                        *layout = (*layout + 1) % 3;
                        self.invalidate_layout()?;
                    }
                    Some(BarAction::Restore(id)) => {
                        self.restore(id)?;
                        self.focus(id)?;
                    }
                    Some(BarAction::Power) => match Command::new("carpatic-powermenu").spawn() {
                        Ok(mut child) => {
                            std::thread::spawn(move || {
                                let _ = child.wait();
                            });
                        }
                        Err(e) => eprintln!("Power menu: {e}"),
                    },
                    None => {}
                }
            }
            Event::ButtonRelease(e)
                if e.event == self.root && e.detail == 3 && self.desktop_menu_press.is_some() =>
            {
                let (x, y) = self.desktop_menu_press.take().unwrap();
                if (i32::from(e.root_x) - i32::from(x)).abs() < 8
                    && (i32::from(e.root_y) - i32::from(y)).abs() < 8
                {
                    if let Ok(mut child) = Command::new("carpatic-desktop-menu")
                        .args([x.to_string(), y.to_string()])
                        .spawn()
                    {
                        std::thread::spawn(move || {
                            let _ = child.wait();
                        });
                    }
                }
            }
            Event::ButtonPress(e) => {
                if self.desktop_surfaces.contains(&e.event) {
                    self.focus(e.event)?;
                    self.conn.allow_events(Allow::REPLAY_POINTER, e.time)?;
                    return Ok(());
                }
                if e.detail == 3 && !self.clients.iter().any(|c| c.id == e.event) {
                    if e.event == self.root && e.child != NONE {
                        self.conn.allow_events(Allow::REPLAY_POINTER, e.time)?;
                        return Ok(());
                    }
                    self.conn.allow_events(Allow::ASYNC_POINTER, e.time)?;
                }
                let context = if e.event == self.root {
                    "ClkRootWin"
                } else {
                    "ClkClientWin"
                };
                if let Some(binding) = self
                    .mouse_bindings
                    .iter()
                    .find(|b| {
                        b.context == context
                            && b.button == e.detail
                            && modifier_mask(&b.binding.modifiers)
                                == (u16::from(e.state) & !(2 | 16))
                    })
                    .map(|b| b.binding.clone())
                {
                    if !matches!(
                        binding.func.as_str(),
                        "moveorplace" | "movemouse" | "resizemouse"
                    ) {
                        self.focus(e.event)?;
                        self.action(&binding)?;
                        return Ok(());
                    } else {
                        let id = self
                            .clients
                            .iter()
                            .find(|c| c.id == e.event || c.titlebar == e.event)
                            .map(|c| c.id);
                        if let Some(id) = id {
                            self.begin_mouse_drag(id, &e, binding.func == "resizemouse")?;
                            return Ok(());
                        }
                    }
                }
                if std::env::var_os("CARPATIC_WM_DEBUG").is_some() {
                    eprintln!(
                        "BUTTON window={} x={} y={} button={}",
                        e.event, e.event_x, e.event_y, e.detail
                    );
                }
                if let Some(id) = self
                    .clients
                    .iter()
                    .find(|c| c.titlebar == e.event)
                    .map(|c| c.id)
                {
                    self.focus(id)?;
                    let c = self.clients.iter().find(|c| c.id == id).unwrap();
                    let rect = c.applied.unwrap();
                    let height = c.caption_height();
                    let hit = self
                        .renderer
                        .hits(&self.config, rect.width, height)
                        .into_iter()
                        .find(|h| i32::from(e.event_x) >= h.left && i32::from(e.event_x) < h.right);
                    if std::env::var_os("CARPATIC_WM_DEBUG").is_some() {
                        eprintln!("HIT {:?}", hit.as_ref().map(|h| h.button));
                    }
                    if e.detail == 1 && u16::from(e.state) & SUPER == 0 {
                        if let Some(hit) = hit {
                            self.pressed_button = Some((id, hit.button));
                            self.conn.change_property32(
                                PropMode::REPLACE,
                                self.root,
                                self.atoms._CARPATIC_PRESSED_BUTTON,
                                AtomEnum::CARDINAL,
                                &[
                                    id,
                                    match hit.button {
                                        Button::Minimize => 0,
                                        Button::Maximize => 1,
                                        Button::Close => 2,
                                    },
                                ],
                            )?;
                            if let Some(c) = self.clients.iter_mut().find(|c| c.id == id) {
                                c.pressed = Some(hit.button);
                                c.hover = Some(hit.button);
                                c.chrome_dirty = true;
                            }
                            self.draw_chrome()?;
                            return Ok(());
                        }
                        if self.config.titlebar.dblclick_maximize
                            && self.last_title_click.is_some_and(|(window, time)| {
                                window == id && e.time.wrapping_sub(time) < 400
                            })
                        {
                            self.last_title_click = None;
                            self.maximize(id)?;
                            return Ok(());
                        }
                        self.last_title_click = Some((id, e.time));
                    }
                    if [1, 3].contains(&e.detail) {
                        self.begin_mouse_drag(id, &e, e.detail == 3)?;
                    }
                    return Ok(());
                }
                if u16::from(e.state) & SUPER != 0 && [1, 3].contains(&e.detail) {
                    self.begin_mouse_drag(e.event, &e, e.detail == 3)?;
                } else if self.clients.iter().any(|c| c.id == e.event) {
                    // A focused app already owns this click. In particular,
                    // wheel events must not toggle its border colours and
                    // repaint the separate chrome on every scroll step.
                    if self.focused != Some(e.event) {
                        self.focus(e.event)?;
                    }
                    self.conn.allow_events(Allow::REPLAY_POINTER, e.time)?;
                } else if e.event == self.root
                    && e.detail == 3
                    && (u16::from(e.state) & !(2 | 16)) == 0
                {
                    self.desktop_menu_press = Some((e.root_x, e.root_y));
                }
            }
            Event::MotionNotify(e) => {
                self.last_pointer = (e.root_x, e.root_y);
                if self.drag.is_none() {
                    if let Some(c) = self.clients.iter_mut().find(|c| c.titlebar == e.event) {
                        if let Some(rect) = c.applied {
                            let hover = self
                                .renderer
                                .hits(&self.config, rect.width, c.caption_height())
                                .into_iter()
                                .find(|h| {
                                    i32::from(e.event_x) >= h.left && i32::from(e.event_x) < h.right
                                })
                                .map(|h| h.button);
                            if hover != c.hover {
                                c.hover = hover;
                                c.chrome_dirty = true;
                            }
                        }
                    }
                    self.draw_chrome()?;
                }
                if self.drag.is_some() {
                    self.drag_motion(e.root_x.into(), e.root_y.into())?;
                }
            }
            Event::ButtonRelease(e) => {
                if let Some((id, button)) = self.pressed_button.take() {
                    self.conn
                        .delete_property(self.root, self.atoms._CARPATIC_PRESSED_BUTTON)?;
                    let valid = self
                        .clients
                        .iter()
                        .find(|c| c.id == id)
                        .and_then(|c| c.applied.map(|r| (c, r)))
                        .is_some_and(|(c, r)| {
                            e.detail == 1
                                && i32::from(e.root_y) >= r.y
                                && i32::from(e.root_y) < r.y + c.caption_height() as i32
                                && self
                                    .renderer
                                    .hits(&self.config, r.width, c.caption_height())
                                    .iter()
                                    .any(|h| {
                                        h.button == button
                                            && i32::from(e.root_x) - r.x >= h.left
                                            && i32::from(e.root_x) - r.x < h.right
                                    })
                        });
                    if let Some(c) = self.clients.iter_mut().find(|c| c.id == id) {
                        c.pressed = None;
                        c.chrome_dirty = true;
                    }
                    if valid {
                        match button {
                            Button::Minimize => self.minimize(id)?,
                            Button::Maximize => {
                                if self.config.fullscreen_spaces
                                    && self.config.titlebar.style == "macos"
                                {
                                    self.fullscreen(id, 2)?;
                                } else {
                                    self.maximize(id)?;
                                }
                            }
                            Button::Close => self.close(id)?,
                        }
                    }
                    self.draw_chrome()?;
                    return Ok(());
                }

                if self.drag.is_some() {
                    self.drag_motion(e.root_x.into(), e.root_y.into())?;
                }
                self.end_drag(false)?;
                self.conn.ungrab_pointer(CURRENT_TIME)?;
                self.conn.change_property32(
                    PropMode::REPLACE,
                    self.root,
                    self.atoms._CARPATIC_DRAGGING,
                    AtomEnum::CARDINAL,
                    &[0],
                )?;
            }
            Event::ClientMessage(e) => {
                let data = e.data.as_data32();
                if e.type_ == self.atoms._NET_SHOWING_DESKTOP {
                    self.show_desktop(data[0] != 0)?;
                } else if e.type_ == self.atoms._NET_REQUEST_FRAME_EXTENTS {
                    let motif = self.property(e.window, self.atoms._MOTIF_WM_HINTS);
                    let has_csd = !self
                        .property(e.window, self.atoms._GTK_FRAME_EXTENTS)
                        .is_empty()
                        || motif.len() >= 3 && motif[0] & 2 != 0 && motif[2] == 0;
                    let border = if has_csd { 0 } else { self.config.border };
                    let title = if self.config.titlebar.enabled && !has_csd {
                        self.renderer.height(&self.config)
                    } else {
                        0
                    };
                    self.conn.change_property32(
                        PropMode::REPLACE,
                        e.window,
                        self.atoms._NET_FRAME_EXTENTS,
                        AtomEnum::CARDINAL,
                        &[border, border, border + title, border],
                    )?;
                } else if e.type_ == self.atoms._NET_WM_STATE {
                    self.change_states(e.window, data[0], [data[1], data[2]])?;
                } else if e.type_ == self.atoms._NET_WM_MOVERESIZE {
                    if data[2] == 11 {
                        self.end_drag(true)?;
                        return Ok(());
                    }
                    if data[2] <= 8 {
                        let edges = match data[2] {
                            0 => 5,
                            1 => 4,
                            2 => 6,
                            3 => 2,
                            4 => 10,
                            5 => 8,
                            6 => 9,
                            7 => 1,
                            _ => 0,
                        };
                        self.begin_drag(
                            e.window,
                            data[0] as i32,
                            data[1] as i32,
                            edges,
                            CURRENT_TIME,
                        )?;
                    }
                } else if e.type_ == self.atoms.WM_CHANGE_STATE && data[0] == 3 {
                    self.minimize(e.window)?;
                } else if e.type_ == self.atoms._NET_CURRENT_DESKTOP {
                    self.switch(data[0])?;
                } else if e.type_ == self.atoms._NET_WM_DESKTOP {
                    if data[0] < self.desktop_count() {
                        if let Some(c) = self.clients.iter_mut().find(|c| c.id == e.window) {
                            c.desktop = data[0];
                            c.tags = 1 << data[0];
                        }
                        self.conn.change_property32(
                            PropMode::REPLACE,
                            e.window,
                            self.atoms._NET_WM_DESKTOP,
                            AtomEnum::CARDINAL,
                            &[data[0]],
                        )?;
                        self.arrange()?;
                        self.focus_available()?;
                    }
                } else if e.type_ == self.atoms._CARPATIC_SNAP {
                    self.keyboard_snap(e.window, e.data.as_data32()[0])?;
                } else if e.type_ == self.atoms._NET_ACTIVE_WINDOW {
                    if self.desktop_surfaces.contains(&e.window) {
                        self.focus(e.window)?;
                        return Ok(());
                    }
                    if self.clients.iter().any(|c| c.id == e.window && c.minimized) {
                        self.restore(e.window)?;
                    }
                    if let Some(monitor) = self
                        .clients
                        .iter()
                        .find(|c| c.id == e.window)
                        .map(|c| c.monitor)
                    {
                        self.active_monitor = monitor;
                        self.desktop = self.monitors[monitor].desktop;
                    }
                    if let Some(desktop) = self
                        .clients
                        .iter()
                        .find(|c| c.id == e.window)
                        .map(|c| c.desktop)
                    {
                        let monitor = &self.monitors[self.active_monitor];
                        // Same-view activation must not briefly focus the first
                        // available app before the requested target. A real
                        // view change still applies normal workspace policy.
                        if self.showing_desktop
                            || monitor.view != 1 << desktop
                            || monitor.all_view
                        {
                            self.switch(desktop)?;
                        }
                        self.focus(e.window)?;
                    }
                } else if e.type_ == self.atoms._NET_CLOSE_WINDOW {
                    self.close(e.window)?;
                }
            }
            // Clients can disappear between an event and a request; keep managing the desktop.
            Event::Error(error)
                if !matches!(
                    error.error_kind,
                    x11rb::protocol::ErrorKind::Window | x11rb::protocol::ErrorKind::Drawable
                ) =>
            {
                eprintln!("X11 request failed: {error:?}");
            }
            _ => (),
        }
        Ok(())
    }

    fn remove(&mut self, id: Window) -> Result<()> {
        if self.desktop_surfaces.contains(&id) {
            self.desktop_surfaces.retain(|window| *window != id);
            self.client_list()?;
            if self
                .property(self.root, self.atoms._NET_ACTIVE_WINDOW)
                .first()
                == Some(&id)
            {
                self.focus_available()?;
            }
            return Ok(());
        }
        if self.pressed_button.is_some_and(|(client, _)| client == id) {
            self.pressed_button = None;
        }
        if !self.clients.iter().any(|c| c.id == id) {
            return Ok(());
        }
        if let Some(c) = self.clients.iter().find(|c| c.id == id) {
            self.animation_expiry
                .retain(|(w, _)| *w != c.id && *w != c.titlebar && c.frame != Some(*w));
            self.deferred_unmaps.retain(|(w, _)| *w != c.id);
            self.conn.delete_property(c.id, self.atoms.WM_STATE)?;
            if let Some(frame) = c.frame {
                if self.conn.get_window_attributes(c.id)?.reply().is_ok() {
                    let position = self
                        .conn
                        .translate_coordinates(c.id, self.root, 0, 0)?
                        .reply()?;
                    self.conn.reparent_window(
                        c.id,
                        self.root,
                        position.dst_x.saturating_sub(c.original_border as i16),
                        position.dst_y.saturating_sub(c.original_border as i16),
                    )?;
                    self.conn.change_save_set(SetMode::DELETE, c.id)?;
                    self.conn.configure_window(
                        c.id,
                        &ConfigureWindowAux::new().border_width(u32::from(c.original_border)),
                    )?;
                    self.conn
                        .delete_property(c.id, self.atoms._CARPATIC_FRAME_GEOMETRY)?;
                }
                self.conn.destroy_window(frame)?;
            } else {
                self.conn.destroy_window(c.titlebar)?;
            }
        }
        for c in &mut self.clients {
            if c.swallowed_by == Some(id) {
                c.swallowed_by = None;
                c.applied = None;
            }
            if c.swallow_parent == Some(id) {
                c.swallow_parent = None;
            }
        }
        self.clients.retain(|c| c.id != id);
        if self.drag.as_ref().is_some_and(|d| d.id == id) {
            self.end_drag(true)?;
        }
        let focused = self.focused == Some(id);
        if focused {
            self.focused = None;
        }
        self.client_list()?;
        self.arrange()?;
        if focused {
            self.focus_available()?;
        }
        Ok(())
    }

    fn run(mut self) -> Result<()> {
        let debug = std::env::var_os("CARPATIC_WM_DEBUG").is_some();
        while self.running {
            self.expire_animation_marks()?;
            while let Some(event) = self.conn.poll_for_event()? {
                if debug {
                    match &event {
                        Event::Expose(e) => eprintln!(
                            "EVENT Expose window={} count={} x={} y={} width={} height={}",
                            e.window, e.count, e.x, e.y, e.width, e.height
                        ),
                        Event::ShapeNotify(e) => eprintln!(
                            "EVENT ShapeNotify window={} sequence={}",
                            e.affected_window, e.sequence
                        ),
                        Event::PropertyNotify(e) => eprintln!(
                            "EVENT PropertyNotify window={} atom={} state={:?}",
                            e.window, e.atom, e.state
                        ),
                        Event::ConfigureNotify(e) => eprintln!(
                            "EVENT ConfigureNotify window={} event={} width={} height={}",
                            e.window, e.event, e.width, e.height
                        ),
                        Event::ConfigureRequest(e) => eprintln!(
                            "EVENT ConfigureRequest window={} mask={:?} width={} height={}",
                            e.window, e.value_mask, e.width, e.height
                        ),
                        _ => eprintln!("EVENT {event:?}"),
                    }
                }
                if let Err(error) = self.handle(event) {
                    eprintln!("Window operation failed: {error}");
                }
                if !self.running {
                    break;
                }
            }
            self.conn.flush()?;
            let timeout = self
                .animation_expiry
                .iter()
                .chain(self.deferred_unmaps.iter())
                .map(|(_, deadline)| deadline.saturating_duration_since(Instant::now()))
                .min();
            if self.running && self.watch.wait(self.conn.stream().as_raw_fd(), timeout)? {
                self.reload()?;
            }
        }
        self.tray.release(&self.conn, self.root)?;
        for bar in &self.bars {
            self.conn.destroy_window(bar.id)?;
        }
        self.conn.destroy_window(self.tray.owner)?;
        self.conn.destroy_window(self.drop_overlay)?;
        for client in &self.clients {
            if let Some(frame) = client.frame {
                let position = self
                    .conn
                    .translate_coordinates(client.id, self.root, 0, 0)?
                    .reply()?;
                self.conn.reparent_window(
                    client.id,
                    self.root,
                    position.dst_x.saturating_sub(client.original_border as i16),
                    position.dst_y.saturating_sub(client.original_border as i16),
                )?;
                self.conn.change_save_set(SetMode::DELETE, client.id)?;
                self.conn.destroy_window(frame)?;
            } else {
                self.conn.destroy_window(client.titlebar)?;
            }
            if !client.minimized {
                self.conn.map_window(client.id)?;
            } else {
                self.conn.unmap_window(client.id)?;
            }
            self.conn.configure_window(
                client.id,
                &ConfigureWindowAux::new().border_width(u32::from(client.original_border)),
            )?;
        }
        self.conn
            .delete_property(self.root, self.atoms._NET_SUPPORTING_WM_CHECK)?;
        self.conn
            .delete_property(self.root, self.atoms._NET_ACTIVE_WINDOW)?;
        self.conn
            .delete_property(self.root, self.atoms._NET_CLIENT_LIST)?;
        for atom in [
            self.atoms._CARPATIC_DROP_ZONE,
            self.atoms._CARPATIC_PRESSED_BUTTON,
            self.atoms._CARPATIC_URGENT_TAGS,
            self.atoms._NET_SHOWING_DESKTOP,
        ] {
            self.conn.delete_property(self.root, atom)?;
        }
        self.conn.destroy_window(self.support)?;
        self.conn.flush()?;
        Ok(())
    }
}

fn opaque_border_pixel(depth: u8, color: u32) -> u32 {
    // RGB configuration colours need opaque alpha in a depth-32 ARGB border.
    // Zero-alpha RGB would be invalid premultiplied colour and produce halos.
    if depth == 32 {
        color | 0xff00_0000
    } else {
        color
    }
}

// Applications own their shapes. Compose their server-side regions into the
// frame instead of replacing the client's bounding, clip or input masks.
#[allow(clippy::too_many_arguments)]
fn shape_app_frame(
    conn: &RustConnection,
    frame: Window,
    client: Window,
    width: u32,
    height: u32,
    border: u32,
    title: u32,
    radius: u32,
    square: bool,
) -> Result<()> {
    use x11rb::protocol::shape::{ConnectionExt as _, SK, SO};
    shape_window(conn, frame, width, height, 0, radius, true, true, square)?;
    let caption = Rectangle {
        x: 0,
        y: 0,
        width: width as u16,
        height: (title + border) as u16,
    };
    for kind in [SK::BOUNDING, SK::INPUT] {
        conn.shape_combine(
            SO::SET,
            kind,
            kind,
            frame,
            border as i16,
            (title + border) as i16,
            client,
        )?;
        if title > 0 {
            conn.shape_rectangles(
                SO::UNION,
                kind,
                ClipOrdering::UNSORTED,
                frame,
                0,
                0,
                &[caption],
            )?;
        }
        // CLIP still holds the rounded outer region created above. Input also
        // intersects the composed bounding region so visual holes pass clicks.
        conn.shape_combine(
            SO::INTERSECT,
            kind,
            if kind == SK::BOUNDING {
                SK::CLIP
            } else {
                SK::BOUNDING
            },
            frame,
            0,
            0,
            frame,
        )?;
    }
    Ok(())
}

#[allow(clippy::too_many_arguments)]
fn shape_window(
    conn: &RustConnection,
    id: Window,
    width: u32,
    height: u32,
    border: u32,
    radius: u32,
    top: bool,
    bottom: bool,
    square: bool,
) -> Result<()> {
    use x11rb::protocol::shape::{ConnectionExt as _, SK, SO};
    if square || radius == 0 {
        conn.shape_mask(SO::SET, SK::BOUNDING, id, 0, 0, NONE)?;
        conn.shape_mask(SO::SET, SK::CLIP, id, 0, 0, NONE)?;
        return Ok(());
    }
    let w = width + border * 2;
    let h = height + border * 2;
    let r = radius.min(w / 2).min(h / 2);
    let mut rectangles = Vec::new();
    let top_h = if top { r } else { 0 };
    let bottom_h = if bottom { r } else { 0 };
    for y in 0..top_h {
        let dy = r as f64 - y as f64 - 0.5;
        let inset = (r as f64 - (r as f64 * r as f64 - dy * dy).sqrt()).ceil() as u32;
        rectangles.push(Rectangle {
            x: (inset as i32 - border as i32) as i16,
            y: (y as i32 - border as i32) as i16,
            width: w.saturating_sub(inset * 2).max(1) as u16,
            height: 1,
        });
    }
    rectangles.push(Rectangle {
        x: -(border as i16),
        y: (top_h as i32 - border as i32) as i16,
        width: w as u16,
        height: h.saturating_sub(top_h + bottom_h).max(1) as u16,
    });
    for y in 0..bottom_h {
        let dy = y as f64 + 0.5;
        let inset = (r as f64 - (r as f64 * r as f64 - dy * dy).sqrt()).ceil() as u32;
        rectangles.push(Rectangle {
            x: (inset as i32 - border as i32) as i16,
            y: ((h - bottom_h + y) as i32 - border as i32) as i16,
            width: w.saturating_sub(inset * 2).max(1) as u16,
            height: 1,
        });
    }
    conn.shape_rectangles(
        SO::SET,
        SK::BOUNDING,
        ClipOrdering::UNSORTED,
        id,
        0,
        0,
        &rectangles,
    )?;
    let inner_radius = radius.saturating_sub(border).min(width / 2).min(height / 2);
    let mut clips = Vec::new();
    for y in 0..height {
        let corner = if top && y < inner_radius {
            Some(inner_radius - y)
        } else if bottom && y >= height - inner_radius {
            Some(y - (height - inner_radius) + 1)
        } else {
            None
        };
        let inset = corner
            .map(|dy| {
                let dy = dy as f64 - 0.5;
                (inner_radius as f64 - ((inner_radius as f64).powi(2) - dy.powi(2)).sqrt()).ceil()
                    as u32
            })
            .unwrap_or(0);
        // Merge adjacent equal rows to keep the shape request bounded.
        if let Some(previous) = clips.last_mut() {
            let previous: &mut Rectangle = previous;
            if previous.x == inset as i16
                && previous.width == width.saturating_sub(inset * 2).max(1) as u16
            {
                previous.height += 1;
                continue;
            }
        }
        clips.push(Rectangle {
            x: inset as i16,
            y: y as i16,
            width: width.saturating_sub(inset * 2).max(1) as u16,
            height: 1,
        });
    }
    conn.shape_rectangles(SO::SET, SK::CLIP, ClipOrdering::UNSORTED, id, 0, 0, &clips)?;

    Ok(())
}

fn process_descends_from(mut pid: u32, ancestor: u32) -> bool {
    for _ in 0..64 {
        if pid <= 1 {
            break;
        }
        if pid == ancestor {
            return true;
        }
        let Ok(text) = std::fs::read_to_string(format!("/proc/{pid}/stat")) else {
            break;
        };
        let Some((_, tail)) = text.rsplit_once(')') else {
            break;
        };
        let Some(parent) = tail
            .split_whitespace()
            .nth(1)
            .and_then(|p| p.parse::<u32>().ok())
        else {
            break;
        };
        if parent == pid {
            break;
        }
        pid = parent;
    }
    false
}

fn constrain_size(
    mut width: u32,
    mut height: u32,
    hints: &x11rb::properties::WmSizeHints,
) -> (u32, u32) {
    let base = hints.base_size.or(hints.min_size).unwrap_or((0, 0));
    let bw = base.0.max(0) as u32;
    let bh = base.1.max(0) as u32;
    let base_is_min = Some(base) == hints.min_size;
    if !base_is_min {
        width = width.saturating_sub(bw).max(1);
        height = height.saturating_sub(bh).max(1);
    }
    if let Some((min, max)) = hints.aspect {
        if min.numerator > 0
            && min.denominator > 0
            && (u64::from(width) * min.denominator as u64)
                < u64::from(height) * min.numerator as u64
        {
            height =
                (u64::from(width) * min.denominator as u64 / min.numerator as u64).max(1) as u32;
        }
        if max.numerator > 0
            && max.denominator > 0
            && (u64::from(width) * max.denominator as u64)
                > u64::from(height) * max.numerator as u64
        {
            width =
                (u64::from(height) * max.numerator as u64 / max.denominator as u64).max(1) as u32;
        }
    }
    if base_is_min {
        width = width.saturating_sub(bw);
        height = height.saturating_sub(bh);
    }
    if let Some((x, y)) = hints.size_increment {
        if x > 0 {
            width = width / x as u32 * x as u32;
        }
        if y > 0 {
            height = height / y as u32 * y as u32;
        }
    }
    width = width.saturating_add(bw).max(1);
    height = height.saturating_add(bh).max(1);
    if let Some((x, y)) = hints.min_size {
        width = width.max(x.max(1) as u32);
        height = height.max(y.max(1) as u32);
    }
    if let Some((x, y)) = hints.max_size {
        if x > 0 {
            width = width.min(x as u32);
        }
        if y > 0 {
            height = height.min(y as u32);
        }
    }
    (width, height)
}

fn inset(mut area: Rect, gap: u32) -> Rect {
    let gap = gap.min(area.width / 4).min(area.height / 4);
    area.x += gap as i32;
    area.y += gap as i32;
    area.width = area.width.saturating_sub(gap * 2).max(1);
    area.height = area.height.saturating_sub(gap * 2).max(1);
    area
}

fn modifier_mask(text: &str) -> u16 {
    text.split_whitespace().fold(0, |value, name| {
        value
            | match name.to_ascii_uppercase().as_str() {
                "SUPER" | "WIN" | "MOD4" => 64,
                "SHIFT" => 1,
                "CTRL" | "CONTROL" => 4,
                "ALT" | "MOD1" => 8,
                "MOD2" => 16,
                "MOD3" => 32,
                "MOD5" => 128,
                _ => 0,
            }
    })
}

fn keysym(name: &str) -> Option<u32> {
    if name.chars().count() == 1 {
        return name.chars().next().map(|c| c as u32);
    }
    let symbol = match name {
        "space" => 0x20,
        "Return" => 0xff0d,
        "Tab" => 0xff09,
        "Escape" => 0xff1b,
        "BackSpace" => 0xff08,
        "Left" => 0xff51,
        "Up" => 0xff52,
        "Right" => 0xff53,
        "Down" => 0xff54,
        "Home" => 0xff50,
        "End" => 0xff57,
        "comma" => 0x2c,
        "period" => 0x2e,
        "minus" => 0x2d,
        "equal" => 0x3d,
        "Print" => 0xff61,
        "slash" => 0x2f,
        "XF86AudioLowerVolume" => 0x1008ff11,
        "XF86AudioMute" => 0x1008ff12,
        "XF86AudioRaiseVolume" => 0x1008ff13,
        "XF86AudioPlay" => 0x1008ff14,
        "XF86AudioPause" => 0x1008ff31,
        "XF86AudioPrev" => 0x1008ff16,
        "XF86AudioNext" => 0x1008ff17,
        "XF86AudioMicMute" => 0x1008ffb2,
        "XF86MonBrightnessUp" => 0x1008ff02,
        "XF86MonBrightnessDown" => 0x1008ff03,
        "XF86KbdBrightnessUp" => 0x1008ff05,
        "XF86KbdBrightnessDown" => 0x1008ff06,
        "XF86PowerOff" => 0x1008ff2a,
        "XF86Sleep" => 0x1008ff2f,
        "XF86Hibernate" => 0x1008ffa8,
        "XF86WLAN" => 0x1008ff95,
        "XF86Bluetooth" => 0x1008ff94,
        "XF86RFKill" => 0x1008ffb5,
        other if other.starts_with('F') => {
            let n = other[1..].parse::<u32>().ok()?;
            if !(1..=35).contains(&n) {
                return None;
            }
            0xffbd + n
        }
        _ => return None,
    };
    Some(symbol)
}

fn config_paths(dir: &std::path::Path, name: &str) -> Vec<PathBuf> {
    let mut paths = vec![dir.join(name)];
    if std::env::var_os("CARPATIC_CONFIG_DIR").is_none() {
        let data = std::env::var("XDG_DATA_HOME").unwrap_or_else(|_| {
            format!("{}/.local/share", std::env::var("HOME").unwrap_or_default())
        });
        paths.push(PathBuf::from(data).join("dwm-titus/config").join(name));
        paths.push(PathBuf::from("/usr/share/carpatic-rust/config").join(name));
    }
    paths
}

fn load_config(dir: &std::path::Path) -> Config {
    for path in config_paths(dir, "themes.toml") {
        if path.exists() {
            match Config::load(&path) {
                Ok(c) => return policy_overrides(c),
                Err(e) => eprintln!("Theme configuration: {e}"),
            }
        }
    }
    policy_overrides(Config::default())
}

fn policy_overrides(mut config: Config) -> Config {
    if let Ok(v) = std::env::var("CARPATIC_FULLSCREEN_SPACES") {
        config.fullscreen_spaces = v == "1";
    }
    if let Ok(v) = std::env::var("CARPATIC_FOCUS_FOLLOWS_MOUSE") {
        config.focus_follows_mouse = v == "1";
    }
    config
}

fn desktop_names(config: &Config) -> Vec<u8> {
    let mut bytes = Vec::new();
    for index in 0..config.workspaces as usize {
        let fallback = (index + 1).to_string();
        bytes.extend(
            config
                .workspace_names
                .get(index)
                .unwrap_or(&fallback)
                .as_bytes(),
        );
        bytes.push(0);
    }
    bytes
}

fn main() {
    if std::env::args().any(|a| a == "--version") {
        println!("carpatic-wm {}", env!("CARGO_PKG_VERSION"));
        return;
    }
    if let Err(error) = Wm::new().and_then(Wm::run) {
        eprintln!("carpatic-wm: {error}");
        std::process::exit(1);
    }
}

#[cfg(test)]
mod size_tests {
    use super::*;
    use x11rb::properties::{AspectRatio, WmSizeHints};
    #[test]
    fn content_aspect_base_increments_and_limits() {
        let hints = WmSizeHints {
            aspect: Some((AspectRatio::new(1, 1), AspectRatio::new(2, 1))),
            ..WmSizeHints::new()
        };
        assert_eq!(constrain_size(400, 100, &hints), (200, 100));
        assert_eq!(constrain_size(100, 300, &hints), (100, 100));
        let hints = WmSizeHints {
            base_size: Some((10, 20)),
            min_size: Some((60, 70)),
            max_size: Some((300, 400)),
            size_increment: Some((25, 50)),
            ..WmSizeHints::new()
        };
        assert_eq!(constrain_size(293, 379, &hints), (285, 370));
        assert_eq!(constrain_size(20, 20, &hints), (60, 70));
        assert_eq!(constrain_size(500, 500, &hints), (300, 400));
    }
}
