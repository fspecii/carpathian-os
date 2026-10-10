use std::{
    error::Error,
    process::{Child, Command},
    thread,
    time::{Duration, Instant},
};
use x11rb::{
    connection::Connection, protocol::xproto::*, rust_connection::RustConnection,
    wrapper::ConnectionExt as _,
};
type Result<T> = std::result::Result<T, Box<dyn Error>>;

struct Process(Child);
impl Drop for Process {
    fn drop(&mut self) {
        let _ = self.0.kill();
        let _ = self.0.wait();
    }
}
struct ConfigRestore(Vec<(std::path::PathBuf, Option<Vec<u8>>)>);
impl ConfigRestore {
    fn new(dir: &std::path::Path) -> Self {
        Self(
            ["themes.toml", "hotkeys.toml", "window-rules.toml"]
                .into_iter()
                .map(|name| {
                    let path = dir.join(name);
                    let data = std::fs::read(&path).ok();
                    (path, data)
                })
                .collect(),
        )
    }
}
impl Drop for ConfigRestore {
    fn drop(&mut self) {
        for (path, data) in &self.0 {
            if let Some(data) = data {
                let _ = std::fs::write(path, data);
            } else {
                let _ = std::fs::remove_file(path);
            }
        }
    }
}
fn start() -> Result<Process> {
    start_with_policy(false, true)
}
fn start_with_policy(spaces: bool, hover: bool) -> Result<Process> {
    let log = std::fs::OpenOptions::new().create(true).append(true).open(
        std::env::var("CARPATIC_WM_TEST_LOG")
            .unwrap_or_else(|_| "/tmp/carpatic-wm-test.log".into()),
    )?;
    Ok(Process(
        Command::new(
            if let Ok(binary) = std::env::var("CARPATIC_WM_TEST_BINARY") {
                assert_eq!(
                    std::env::var("CARPATIC_WM_TEST_DISPLAY").as_deref(),
                    Ok("1")
                );
                assert!(!matches!(
                    std::env::var("DISPLAY").as_deref(),
                    Ok(":0" | ":1")
                ));
                assert!(std::env::var_os("WAYLAND_DISPLAY").is_none());
                binary
            } else {
                env!("CARGO_BIN_EXE_carpatic-wm").to_owned()
            },
        )
        .env("CARPATIC_SESSION", "1")
        .env("CARPATIC_FULLSCREEN_SPACES", if spaces { "1" } else { "0" })
        .env(
            "CARPATIC_FOCUS_FOLLOWS_MOUSE",
            if hover { "1" } else { "0" },
        )
        .env("CARPATIC_WM_DEBUG", "1")
        .stdout(log.try_clone()?)
        .stderr(log)
        .spawn()?,
    ))
}
fn atom(conn: &RustConnection, name: &str) -> Result<Atom> {
    Ok(conn.intern_atom(false, name.as_bytes())?.reply()?.atom)
}
fn property(conn: &RustConnection, id: Window, name: &str) -> Result<Vec<u32>> {
    Ok(conn
        .get_property(false, id, atom(conn, name)?, AtomEnum::ANY, 0, 100)?
        .reply()?
        .value32()
        .map(|v| v.collect())
        .unwrap_or_default())
}
fn message(
    conn: &RustConnection,
    root: Window,
    window: Window,
    name: &str,
    data: [u32; 5],
) -> Result<()> {
    conn.send_event(
        false,
        root,
        EventMask::SUBSTRUCTURE_REDIRECT | EventMask::SUBSTRUCTURE_NOTIFY,
        ClientMessageEvent::new(32, window, atom(conn, name)?, data),
    )?;
    conn.flush()?;
    Ok(())
}
fn wait(label: &str, mut check: impl FnMut() -> bool) {
    let deadline = Instant::now() + Duration::from_secs(5);
    while !check() {
        assert!(Instant::now() < deadline, "timed out: {label}");
        thread::sleep(Duration::from_millis(25));
    }
    println!("PASS {label}");
}
fn xdotool(args: &[&str]) {
    assert!(Command::new("xdotool")
        .args(args)
        .status()
        .unwrap()
        .success());
}
fn geometry(conn: &RustConnection, id: Window) -> GetGeometryReply {
    let mut geometry = conn.get_geometry(id).unwrap().reply().unwrap();
    let root_position = conn
        .translate_coordinates(id, geometry.root, 0, 0)
        .unwrap()
        .reply()
        .unwrap();
    // TranslateCoordinates gives the interior origin. Preserve the old helper's
    // outer-client coordinates while supporting a client inside a WM frame.
    geometry.x = root_position.dst_x - geometry.border_width as i16;
    geometry.y = root_position.dst_y - geometry.border_width as i16;
    geometry
}

fn native_chrome(conn: &RustConnection, root: Window, client: Window) -> Option<Window> {
    let parent = conn.query_tree(client).ok()?.reply().ok()?.parent;
    let container = if parent == root { root } else { parent };
    conn.query_tree(container)
        .ok()?
        .reply()
        .ok()?
        .children
        .into_iter()
        .find(|window| {
            *window != client
                && property(conn, *window, "_CARPATIC_CLIENT").ok() == Some(vec![client])
                && !property(conn, *window, "_CARPATIC_BUTTONS")
                    .unwrap_or_default()
                    .is_empty()
        })
}

fn root_surface(conn: &RustConnection, client: Window) -> Window {
    let mut window = client;
    for _ in 0..20 {
        let tree = conn.query_tree(window).unwrap().reply().unwrap();
        if tree.parent == tree.root {
            return window;
        }
        window = tree.parent;
    }
    panic!("unexpectedly deep app hierarchy");
}

fn not_viewable(conn: &RustConnection, id: Window) -> bool {
    conn.get_window_attributes(id)
        .ok()
        .and_then(|cookie| cookie.reply().ok())
        .is_some_and(|attributes| attributes.map_state != MapState::VIEWABLE)
}

fn ready(conn: &RustConnection, root: Window, process: &Process) -> bool {
    property(conn, root, "_NET_SUPPORTING_WM_CHECK")
        .ok()
        .and_then(|ids| ids.first().copied())
        .and_then(|id| property(conn, id, "_NET_WM_PID").ok())
        == Some(vec![process.0.id()])
}

#[test]
#[ignore = "requires private Xvfb; run tests/run.sh"]
fn real_x11_window_lifecycle() -> Result<()> {
    std::fs::write(
        std::path::PathBuf::from(std::env::var("CARPATIC_CONFIG_DIR")?).join("themes.toml"),
        "[appearance]\nworkspaces=4\n[titlebar]\nenabled=0\n",
    )?;
    assert_eq!(
        std::env::var("CARPATIC_WM_TEST_DISPLAY").as_deref(),
        Ok("1")
    );
    let display = std::env::var("DISPLAY")?;
    assert!(display != ":1" && display != ":0");
    assert!(std::env::var_os("WAYLAND_DISPLAY").is_none());
    let (conn, screen) = x11rb::connect(None)?;
    let root = conn.setup().roots[screen].root;
    let mut wm = start()?;
    wait("WM ownership", || ready(&conn, root, &wm));
    assert_eq!(property(&conn, root, "_NET_NUMBER_OF_DESKTOPS")?, vec![4]);
    let output = Command::new(env!("CARGO_BIN_EXE_carpatic-wm"))
        .env("CARPATIC_SESSION", "1")
        .output()?;
    assert!(!output.status.success());
    assert!(String::from_utf8_lossy(&output.stderr).contains("already owns"));
    println!("PASS second WM rejected");
    let mut windows = Vec::new();
    for index in 0..3 {
        let id = conn.generate_id()?;
        conn.create_window(
            0,
            id,
            root,
            50,
            50,
            280,
            180,
            0,
            WindowClass::INPUT_OUTPUT,
            0,
            &CreateWindowAux::new()
                .background_pixel([0x183646, 0x24344a, 0x35344b][index])
                .event_mask(EventMask::STRUCTURE_NOTIFY),
        )?;
        conn.change_property8(
            PropMode::REPLACE,
            id,
            AtomEnum::WM_NAME,
            AtomEnum::STRING,
            format!("Carpatic test {}", index + 1).as_bytes(),
        )?;
        conn.change_property32(
            PropMode::REPLACE,
            id,
            atom(&conn, "WM_PROTOCOLS")?,
            AtomEnum::ATOM,
            &[atom(&conn, "WM_DELETE_WINDOW")?],
        )?;
        conn.map_window(id)?;
        conn.flush()?;
        windows.push(id);
        wait("client managed", || {
            property(&conn, root, "_NET_CLIENT_LIST")
                .unwrap_or_default()
                .contains(&id)
        });
    }
    wait("newly mapped window retains keyboard focus", || {
        property(&conn, root, "_NET_ACTIVE_WINDOW").unwrap_or_default() == vec![windows[2]]
    });
    let first = windows[0];
    let second = windows[1];
    let third = windows[2];
    wait("master and stack tiling", || {
        let a = geometry(&conn, first);
        let b = geometry(&conn, second);
        let c = geometry(&conn, third);
        a.x < b.x && b.x == c.x && b.y < c.y && a.width > b.width && a.height > b.height
    });
    let before = geometry(&conn, first);
    conn.configure_window(first, &ConfigureWindowAux::new().width(50).height(50))?;
    conn.flush()?;
    thread::sleep(Duration::from_millis(100));
    assert_eq!(geometry(&conn, first).width, before.width);
    println!("PASS client cannot override tiled geometry");
    message(&conn, root, first, "_NET_ACTIVE_WINDOW", [1, 0, 0, 0, 0])?;
    wait("focus request", || {
        property(&conn, root, "_NET_ACTIVE_WINDOW").ok() == Some(vec![first])
    });
    xdotool(&["key", "super+shift+space"]);
    thread::sleep(Duration::from_millis(100));
    conn.configure_window(
        first,
        &ConfigureWindowAux::new().x(40).y(40).width(280).height(180),
    )?;
    conn.flush()?;
    wait("floating geometry accepted", || {
        geometry(&conn, first).width == 280
    });
    xdotool(&["key", "super+t"]); // Isolate free mouse movement from drop-to-tile behavior.
    xdotool(&[
        "mousemove",
        "70",
        "70",
        "keydown",
        "Super_L",
        "mousedown",
        "1",
        "mousemove",
        "220",
        "170",
        "mouseup",
        "1",
        "keyup",
        "Super_L",
    ]);
    wait("floating mouse drag", || {
        let g = geometry(&conn, first);
        g.x == 190 && g.y == 140
    });
    xdotool(&[
        "mousemove",
        "220",
        "170",
        "keydown",
        "Super_L",
        "mousedown",
        "3",
        "mousemove",
        "300",
        "230",
        "mouseup",
        "3",
        "keyup",
        "Super_L",
    ]);
    wait("floating mouse resize", || {
        let g = geometry(&conn, first);
        g.width == 360 && g.height == 240
    });
    xdotool(&["key", "super+t"]);
    message(&conn, root, first, "_NET_ACTIVE_WINDOW", [1, 0, 0, 0, 0])?;
    wait("focus before fullscreen", || {
        property(&conn, root, "_NET_ACTIVE_WINDOW").ok() == Some(vec![first])
    });
    xdotool(&["key", "super+f"]);
    wait("fullscreen", || {
        let g = geometry(&conn, first);
        g.width == 1280 && g.height == 800 && g.border_width == 0
    });
    xdotool(&["key", "super+f"]);
    wait("fullscreen restores floating size", || {
        geometry(&conn, first).width == 360
    });
    xdotool(&["key", "super+shift+2"]);
    wait("move to workspace", || {
        property(&conn, first, "_NET_WM_DESKTOP").ok() == Some(vec![1])
    });
    wait("off-workspace window hidden", || not_viewable(&conn, first));
    xdotool(&["key", "super+2"]);
    wait("workspace switched", || {
        property(&conn, root, "_NET_CURRENT_DESKTOP").ok() == Some(vec![1])
    });
    wait("workspace window restored", || {
        conn.get_window_attributes(first)
            .unwrap()
            .reply()
            .unwrap()
            .map_state
            == MapState::VIEWABLE
    });
    xdotool(&["key", "super+1"]);
    wait("switch back preserves clients", || {
        property(&conn, root, "_NET_CLIENT_LIST").unwrap().len() == 3
    });
    let dialog = conn.generate_id()?;
    conn.create_window(
        0,
        dialog,
        root,
        400,
        100,
        200,
        120,
        0,
        WindowClass::INPUT_OUTPUT,
        0,
        &CreateWindowAux::new(),
    )?;
    conn.change_property32(
        PropMode::REPLACE,
        dialog,
        atom(&conn, "WM_TRANSIENT_FOR")?,
        AtomEnum::WINDOW,
        &[second],
    )?;
    conn.map_window(dialog)?;
    conn.flush()?;
    wait("dialog floats", || {
        property(&conn, root, "_NET_CLIENT_LIST")
            .unwrap()
            .contains(&dialog)
            && geometry(&conn, dialog).width == 200
    });
    conn.destroy_window(dialog)?;
    conn.destroy_window(third)?;
    conn.flush()?;
    wait("destroy retile", || {
        property(&conn, root, "_NET_CLIENT_LIST").unwrap().len() == 2
    });
    // Polite close must reach the client, rather than killing its X connection.
    message(&conn, root, second, "_NET_CLOSE_WINDOW", [0; 5])?;
    let mut close_received = false;
    wait("WM_DELETE_WINDOW delivered", || {
        while let Some(event) = conn.poll_for_event().unwrap() {
            if let x11rb::protocol::Event::ClientMessage(e) = event {
                if e.window == second
                    && e.data.as_data32()[0] == atom(&conn, "WM_DELETE_WINDOW").unwrap()
                {
                    close_received = true;
                }
            }
        }
        close_received
    });
    conn.destroy_window(second)?;
    conn.flush()?;
    wait("close removes client", || {
        property(&conn, root, "_NET_CLIENT_LIST").unwrap().len() == 1
    });
    xdotool(&["key", "super+shift+q"]);
    wait("graceful WM exit", || wm.0.try_wait().unwrap().is_some());
    wm = start()?;
    wait("replacement WM ready", || ready(&conn, root, &wm));
    wait("restart adopts surviving window", || {
        property(&conn, root, "_NET_CLIENT_LIST").ok() == Some(vec![first])
    });
    message(&conn, root, root, "_NET_CURRENT_DESKTOP", [1, 0, 0, 0, 0])?;
    wait("restart preserves workspace", || {
        conn.get_window_attributes(first)
            .unwrap()
            .reply()
            .unwrap()
            .map_state
            == MapState::VIEWABLE
    });
    conn.configure_window(first, &ConfigureWindowAux::new().width(320))?;
    conn.flush()?;
    wait("restart preserves floating mode", || {
        geometry(&conn, first).width == 320
    });
    if let Ok(path) = std::env::var("CARPATIC_WM_SCREENSHOT") {
        assert!(Command::new("import")
            .args(["-window", "root", &path])
            .status()?
            .success());
    }
    conn.destroy_window(first)?;
    conn.flush()?;
    wait("last client destroyed", || {
        property(&conn, root, "_NET_CLIENT_LIST").ok() == Some(vec![])
    });
    xdotool(&["key", "super+shift+q"]);
    wait("final WM exit", || wm.0.try_wait().unwrap().is_some());
    Ok(())
}

#[test]
#[ignore = "requires private Xvfb; run tests/run.sh"]
fn titlebars_and_live_themes() -> Result<()> {
    assert_eq!(
        std::env::var("CARPATIC_WM_TEST_DISPLAY").as_deref(),
        Ok("1")
    );
    let config_dir = std::path::PathBuf::from(std::env::var("CARPATIC_CONFIG_DIR")?);
    let file = config_dir.join("themes.toml");
    let config = |background: &str, style: &str| {
        format!("[active]\ntheme=\"test\"\n[appearance]\nworkspaces=4\n[theme.test]\nselbgcolor=\"{background}\"\nselfgcolor=\"#ffffff\"\nselbordercolor=\"#66aaff\"\n[titlebar]\nenabled=1\nbutton_style=\"{style}\"\nheight=32\n")
    };
    std::fs::write(&file, config("#183645", "windows"))?;
    let (conn, screen) = x11rb::connect(None)?;
    let root = conn.setup().roots[screen].root;
    let mut wm = start()?;
    wait("decorated WM ready", || ready(&conn, root, &wm));
    let serial = property(&conn, root, "_CARPATIC_CONFIG_SERIAL")?;
    let motion_dir = config_dir.parent().unwrap().join("carpatic");
    std::fs::create_dir_all(&motion_dir)?;
    // Animation preferences and generated compositor files must not trigger
    // a complete WM reload (which also cancels any active mouse drag).
    std::fs::write(motion_dir.join("animations.json"), "{}")?;
    std::fs::write(
        motion_dir.join("window-animations.conf.tmp"),
        "backend=xrender",
    )?;
    std::fs::rename(
        motion_dir.join("window-animations.conf.tmp"),
        motion_dir.join("window-animations.conf"),
    )?;
    thread::sleep(Duration::from_millis(250));
    assert_eq!(property(&conn, root, "_CARPATIC_CONFIG_SERIAL")?, serial);
    std::fs::write(motion_dir.join("dwm-font"), "DejaVu Sans Mono:size=12")?;
    wait("font preference reloads WM", || {
        property(&conn, root, "_CARPATIC_CONFIG_SERIAL").ok() != Some(serial.clone())
    });
    std::fs::remove_file(motion_dir.join("dwm-font"))?;
    let id = conn.generate_id()?;
    conn.create_window(
        0,
        id,
        root,
        80,
        80,
        280,
        180,
        0,
        WindowClass::INPUT_OUTPUT,
        0,
        &CreateWindowAux::new().background_pixel(0x111c2b),
    )?;
    conn.change_property8(
        PropMode::REPLACE,
        id,
        AtomEnum::WM_NAME,
        AtomEnum::STRING,
        b"Decorated window",
    )?;
    conn.change_property32(
        PropMode::REPLACE,
        id,
        atom(&conn, "WM_PROTOCOLS")?,
        AtomEnum::ATOM,
        &[atom(&conn, "WM_DELETE_WINDOW")?],
    )?;
    conn.map_window(id)?;
    conn.flush()?;
    let mut titlebar = 0;
    wait("native titlebar created", || {
        if let Some(child) = native_chrome(&conn, root, id) {
            titlebar = child;
            true
        } else {
            false
        }
    });
    wait("titlebar mapped", || {
        conn.get_window_attributes(titlebar)
            .unwrap()
            .reply()
            .unwrap()
            .map_state
            == MapState::VIEWABLE
    });
    assert!(geometry(&conn, id).y >= 40);
    let pixel = || {
        conn.get_image(ImageFormat::Z_PIXMAP, titlebar, 5, 5, 1, 1, u32::MAX)
            .unwrap()
            .reply()
            .unwrap()
            .data
    };
    wait("theme colors rendered", || {
        pixel().get(..3) == Some(&[0x45, 0x36, 0x18][..])
    });
    conn.change_window_attributes(
        id,
        &ChangeWindowAttributesAux::new().event_mask(EventMask::PROPERTY_CHANGE),
    )?
    .check()?;
    while conn.poll_for_event()?.is_some() {}
    // A size-hints notification forces arrange with the same frame extents.
    // Picom/GTK must not receive another identical frame-extents notification.
    x11rb::properties::WmSizeHints::new()
        .set_normal_hints(&conn, id)?
        .check()?;
    thread::sleep(Duration::from_millis(250));
    let frame_atom = atom(&conn, "_NET_FRAME_EXTENTS")?;
    while let Some(event) = conn.poll_for_event()? {
        assert!(
            !matches!(event, x11rb::protocol::Event::PropertyNotify(e) if e.atom == frame_atom)
        );
    }
    std::fs::write(&file, config("#f0e8dd", "macos"))?;
    wait("theme reload without restart", || {
        pixel().get(..3) == Some(&[0xdd, 0xe8, 0xf0][..])
    });
    wait("macOS button placement", || {
        property(&conn, titlebar, "_CARPATIC_BUTTONS")
            .unwrap_or_default()
            .get(4)
            .is_some_and(|x| *x < 20)
    });
    let click = |button_index: usize| {
        let ranges = property(&conn, titlebar, "_CARPATIC_BUTTONS").unwrap();
        let g = geometry(&conn, titlebar);
        let x = i32::from(g.x) + (ranges[button_index] + ranges[button_index + 1]) as i32 / 2;
        let y = i32::from(g.y) + i32::from(g.height) / 2;
        xdotool(&["mousemove", &x.to_string(), &y.to_string(), "click", "1"]);
    };
    let g = geometry(&conn, titlebar);
    let buttons = property(&conn, titlebar, "_CARPATIC_BUTTONS")?;
    let min_x = g.x as i32 + ((buttons[0] + buttons[1]) / 2) as i32;
    let min_y = g.y as i32 + g.height as i32 / 2;
    xdotool(&[
        "mousemove",
        "--sync",
        &min_x.to_string(),
        &min_y.to_string(),
        "mousedown",
        "1",
    ]);
    wait("titlebar button armed", || {
        property(&conn, root, "_CARPATIC_PRESSED_BUTTON").unwrap_or_default() == vec![id, 0]
    });
    assert_ne!(property(&conn, id, "WM_STATE")?.first(), Some(&3));
    xdotool(&["mousemove", "--sync", "1278", "798", "mouseup", "1"]);
    wait("drag off cancels button activation", || {
        property(&conn, root, "_CARPATIC_PRESSED_BUTTON")
            .unwrap_or_default()
            .is_empty()
    });
    assert_ne!(property(&conn, id, "WM_STATE")?.first(), Some(&3));
    click(0);
    wait("titlebar minimize", || not_viewable(&conn, id));
    xdotool(&["key", "super+shift+m"]);
    wait("restore minimized window", || {
        conn.get_window_attributes(id)
            .unwrap()
            .reply()
            .unwrap()
            .map_state
            == MapState::VIEWABLE
    });
    click(2);
    wait("titlebar maximize", || {
        property(&conn, id, "_NET_WM_STATE")
            .unwrap_or_default()
            .contains(&atom(&conn, "_NET_WM_STATE_MAXIMIZED_VERT").unwrap())
    });
    click(2);
    wait("titlebar restore from maximize", || {
        !property(&conn, id, "_NET_WM_STATE")
            .unwrap_or_default()
            .contains(&atom(&conn, "_NET_WM_STATE_MAXIMIZED_VERT").unwrap())
    });
    let g = geometry(&conn, titlebar);
    let x = i32::from(g.x) + 150;
    let y = i32::from(g.y) + 15;
    xdotool(&["mousemove", &x.to_string(), &y.to_string(), "click", "1"]);
    assert_ne!(property(&conn, id, "_CARPATIC_FLOATING")?, vec![1]);
    println!("PASS title click does not detach tile");
    // Start a separate drag gesture, outside the double-click interval.
    thread::sleep(Duration::from_millis(450));
    xdotool(&[
        "mousemove",
        &x.to_string(),
        &y.to_string(),
        "mousedown",
        "1",
        "mousemove",
        &(x + 80).to_string(),
        &(y + 70).to_string(),
        "mouseup",
        "1",
    ]);
    wait("plain titlebar drag floats window", || {
        property(&conn, id, "_CARPATIC_FLOATING").ok() == Some(vec![1])
    });
    wait("titlebar drag released", || {
        property(&conn, root, "_CARPATIC_DRAGGING").ok() == Some(vec![0])
    });
    click(4);
    let mut closed = false;
    wait("titlebar polite close", || {
        while let Some(e) = conn.poll_for_event().unwrap() {
            if let x11rb::protocol::Event::ClientMessage(e) = e {
                if e.window == id
                    && e.data.as_data32()[0] == atom(&conn, "WM_DELETE_WINDOW").unwrap()
                {
                    closed = true;
                }
            }
        }
        closed
    });
    conn.destroy_window(id)?;
    conn.flush()?;
    wait("decorated client cleanup", || {
        property(&conn, root, "_NET_CLIENT_LIST").ok() == Some(vec![])
    });
    xdotool(&["key", "super+shift+q"]);
    wait("decorated WM exit", || wm.0.try_wait().unwrap().is_some());
    std::fs::write(file, "[appearance]\nworkspaces=4\n[titlebar]\nenabled=0\n")?;
    Ok(())
}

#[test]
#[ignore = "requires private Xvfb; run tests/run.sh"]
fn panels_monitors_rules_and_swallowing() -> Result<()> {
    std::fs::write(
        std::path::PathBuf::from(std::env::var("CARPATIC_CONFIG_DIR")?).join("themes.toml"),
        "[appearance]\nworkspaces=4\n[titlebar]\nenabled=0\n",
    )?;
    use x11rb::protocol::randr::{ConnectionExt as _, MonitorInfo};
    assert_eq!(
        std::env::var("CARPATIC_WM_TEST_DISPLAY").as_deref(),
        Ok("1")
    );
    let dir = std::path::PathBuf::from(std::env::var("CARPATIC_CONFIG_DIR")?);
    std::fs::write(
        dir.join("window-rules.toml"),
        "rules=[{class=\"RightApp\",monitor=1},{class=\"Gimp\",isfloating=1}]\n",
    )?;
    let (conn, screen) = x11rb::connect(None)?;
    let root = conn.setup().roots[screen].root;
    let left_name = atom(&conn, "TEST_LEFT")?;
    let right_name = atom(&conn, "TEST_RIGHT")?;
    for (name, x, primary) in [(left_name, 0, true), (right_name, 640, false)] {
        conn.randr_set_monitor(
            root,
            MonitorInfo {
                name,
                primary,
                automatic: false,
                x,
                y: 0,
                width: 640,
                height: 800,
                width_in_millimeters: 169,
                height_in_millimeters: 212,
                outputs: vec![],
            },
        )?
        .check()?;
    }
    let mut wm = start()?;
    wait("multi-monitor WM ready", || ready(&conn, root, &wm));
    let create = |class: &str,
                  x: i16,
                  y: i16,
                  width: u16,
                  height: u16,
                  pid: Option<u32>|
     -> Result<Window> {
        let id = conn.generate_id()?;
        conn.create_window(
            0,
            id,
            root,
            x,
            y,
            width,
            height,
            0,
            WindowClass::INPUT_OUTPUT,
            0,
            &CreateWindowAux::new(),
        )?;
        conn.change_property8(
            PropMode::REPLACE,
            id,
            AtomEnum::WM_CLASS,
            AtomEnum::STRING,
            format!("test\0{class}\0").as_bytes(),
        )?;
        if let Some(pid) = pid {
            conn.change_property32(
                PropMode::REPLACE,
                id,
                atom(&conn, "_NET_WM_PID")?,
                AtomEnum::CARDINAL,
                &[pid],
            )?;
        }
        Ok(id)
    };
    let dock = create("Panel", 0, 752, 1280, 48, None)?;
    conn.change_property32(
        PropMode::REPLACE,
        dock,
        atom(&conn, "_NET_WM_WINDOW_TYPE")?,
        AtomEnum::ATOM,
        &[atom(&conn, "_NET_WM_WINDOW_TYPE_DOCK")?],
    )?;
    conn.change_property32(
        PropMode::REPLACE,
        dock,
        atom(&conn, "_NET_WM_STRUT_PARTIAL")?,
        AtomEnum::CARDINAL,
        &[0, 0, 0, 48, 0, 0, 0, 0, 0, 0, 0, 1279],
    )?;
    conn.map_window(dock)?;
    conn.flush()?;
    wait("panel reserves work area", || {
        property(&conn, root, "_NET_WORKAREA")
            .unwrap_or_default()
            .get(3)
            == Some(&752)
    });
    let left = create("LeftApp", 50, 50, 280, 180, None)?;
    let right = create("RightApp", 50, 50, 280, 180, None)?;
    for id in [left, right] {
        conn.map_window(id)?;
    }
    conn.flush()?;
    wait("rule selects second monitor", || {
        geometry(&conn, right).x >= 640
    });
    assert_eq!(geometry(&conn, dock).width, 1280);
    assert_eq!(geometry(&conn, dock).border_width, 0);
    assert!(i32::from(geometry(&conn, left).y) + i32::from(geometry(&conn, left).height) <= 752);
    assert!(geometry(&conn, left).width > 600 && geometry(&conn, right).width > 600);
    println!("PASS independent tiling on two monitors");
    let floating = create("Gimp", 50, 50, 280, 180, None)?;
    let mut hints = x11rb::properties::WmSizeHints::new();
    hints.min_size = Some((100, 100));
    hints.max_size = Some((400, 300));
    hints.size_increment = Some((20, 10));
    hints.set_normal_hints(&conn, floating)?;
    conn.map_window(floating)?;
    conn.flush()?;
    wait("floating class rule", || {
        geometry(&conn, floating).width == 280
    });
    conn.configure_window(floating, &ConfigureWindowAux::new().width(315).height(185))?;
    conn.flush()?;
    wait("floating resize increments respected", || {
        let g = geometry(&conn, floating);
        g.width == 300 && g.height == 180
    });
    conn.destroy_window(floating)?;
    conn.flush()?;
    let terminal = create("St", 50, 50, 280, 180, Some(std::process::id()))?;
    conn.map_window(terminal)?;
    conn.flush()?;
    wait("terminal managed", || {
        property(&conn, root, "_NET_CLIENT_LIST")
            .unwrap_or_default()
            .contains(&terminal)
    });
    let sleeper = Process(Command::new("sleep").arg("120").spawn()?);
    let child = create("BrowserTest", 50, 50, 280, 180, Some(sleeper.0.id()))?;
    conn.map_window(child)?;
    conn.flush()?;
    wait("child swallows its terminal", || {
        let list = property(&conn, root, "_NET_CLIENT_LIST").unwrap_or_default();
        list.contains(&child) && !list.contains(&terminal)
    });
    conn.destroy_window(child)?;
    conn.flush()?;
    wait("terminal restored after child closes", || {
        property(&conn, root, "_NET_CLIENT_LIST")
            .unwrap_or_default()
            .contains(&terminal)
            && conn
                .get_window_attributes(terminal)
                .unwrap()
                .reply()
                .unwrap()
                .map_state
                == MapState::VIEWABLE
    });
    drop(sleeper);
    for id in [terminal, left, right, dock] {
        conn.destroy_window(id)?;
    }
    conn.flush()?;
    wait("panel removal restores work area", || {
        property(&conn, root, "_NET_WORKAREA")
            .unwrap_or_default()
            .get(3)
            == Some(&800)
    });
    wait("monitor test clients cleaned", || {
        property(&conn, root, "_NET_CLIENT_LIST").ok() == Some(vec![])
    });
    xdotool(&["key", "super+shift+q"]);
    wait("monitor WM exit", || wm.0.try_wait().unwrap().is_some());
    conn.randr_delete_monitor(root, left_name)?.check()?;
    conn.randr_delete_monitor(root, right_name)?.check()?;
    std::fs::remove_file(dir.join("window-rules.toml"))?;
    Ok(())
}

#[test]
#[ignore = "requires private Xvfb; run tests/run.sh"]
fn native_bar_tray_and_drag_cancel() -> Result<()> {
    assert_eq!(
        std::env::var("CARPATIC_WM_TEST_DISPLAY").as_deref(),
        Ok("1")
    );
    let path = std::path::PathBuf::from(std::env::var("CARPATIC_CONFIG_DIR")?).join("themes.toml");
    std::fs::write(
        &path,
        "[appearance]\nworkspaces=4\n[bar]\nenabled=1\n[tray]\nenabled=1\n[titlebar]\nenabled=1\n",
    )?;
    let (conn, screen) = x11rb::connect(None)?;
    let root = conn.setup().roots[screen].root;
    let mut wm = start()?;
    wait("native bar WM ready", || ready(&conn, root, &wm));
    let selection = atom(&conn, "_NET_SYSTEM_TRAY_S0")?;
    wait("native tray owns selection", || {
        conn.get_selection_owner(selection)
            .unwrap()
            .reply()
            .unwrap()
            .owner
            != 0
    });
    let owner = conn.get_selection_owner(selection)?.reply()?.owner;
    let icon = conn.generate_id()?;
    conn.create_window(
        0,
        icon,
        root,
        0,
        0,
        20,
        20,
        0,
        WindowClass::INPUT_OUTPUT,
        0,
        &CreateWindowAux::new().background_pixel(0xff0000),
    )?;
    let info = atom(&conn, "_XEMBED_INFO")?;
    conn.change_property32(PropMode::REPLACE, icon, info, info, &[0, 1])?;
    conn.send_event(
        false,
        owner,
        EventMask::NO_EVENT,
        ClientMessageEvent::new(
            32,
            owner,
            atom(&conn, "_NET_SYSTEM_TRAY_OPCODE")?,
            [0, 0, icon, 0, 0],
        ),
    )?;
    conn.flush()?;
    wait("tray embeds icon", || {
        conn.query_tree(icon).unwrap().reply().unwrap().parent == owner
    });
    wait("tray maps icon", || {
        conn.get_window_attributes(icon)
            .unwrap()
            .reply()
            .unwrap()
            .map_state
            == MapState::VIEWABLE
    });
    conn.change_property32(PropMode::REPLACE, icon, info, info, &[0, 0])?;
    conn.flush()?;
    wait("tray obeys XEMBED mapped flag", || {
        conn.get_window_attributes(icon)
            .unwrap()
            .reply()
            .unwrap()
            .map_state
            == MapState::UNMAPPED
    });
    let mut windows = Vec::new();
    for _ in 0..2 {
        let id = conn.generate_id()?;
        conn.create_window(
            0,
            id,
            root,
            0,
            0,
            250,
            150,
            0,
            WindowClass::INPUT_OUTPUT,
            0,
            &CreateWindowAux::new(),
        )?;
        conn.map_window(id)?;
        windows.push(id);
    }
    conn.flush()?;
    wait("bar clients tiled", || {
        property(&conn, root, "_NET_CLIENT_LIST")
            .unwrap_or_default()
            .len()
            == 2
    });
    assert!(geometry(&conn, windows[0]).y >= 32);
    let bar = conn.query_tree(owner)?.reply()?.parent;
    let fullscreen = atom(&conn, "_NET_WM_STATE_FULLSCREEN")?;
    message(
        &conn,
        root,
        windows[0],
        "_NET_WM_STATE",
        [1, fullscreen, 0, 0, 0],
    )?;
    wait("real fullscreen hides native bar", || {
        conn.get_window_attributes(bar)
            .unwrap()
            .reply()
            .unwrap()
            .map_state
            == MapState::UNMAPPED
    });
    message(
        &conn,
        root,
        windows[0],
        "_NET_WM_STATE",
        [0, fullscreen, 0, 0, 0],
    )?;
    wait("fullscreen exit restores native bar", || {
        conn.get_window_attributes(bar)
            .unwrap()
            .reply()
            .unwrap()
            .map_state
            == MapState::VIEWABLE
    });

    let titlebar = native_chrome(&conn, root, windows[0]).expect("managed native chrome");
    let g = geometry(&conn, titlebar);
    let x = g.x as i32 + 80;
    let y = g.y as i32 + 10;
    xdotool(&[
        "mousemove",
        "--sync",
        &x.to_string(),
        &y.to_string(),
        "mousedown",
        "1",
        "mousemove",
        "--sync",
        &(x + 100).to_string(),
        &(y + 100).to_string(),
    ]);
    wait("drag detached tile", || {
        property(&conn, windows[0], "_CARPATIC_FLOATING").unwrap_or_default() == vec![1]
    });
    xdotool(&["key", "Escape", "mouseup", "1"]);
    wait("Escape restores tiled state", || {
        property(&conn, windows[0], "_CARPATIC_FLOATING").unwrap_or_default() == vec![0]
    });
    wait("Escape ends pointer drag", || {
        property(&conn, root, "_CARPATIC_DRAGGING").unwrap_or_default() == vec![0]
    });
    thread::sleep(Duration::from_millis(450));
    let g = geometry(&conn, titlebar);
    let target = geometry(&conn, windows[1]);
    xdotool(&[
        "mousemove",
        "--sync",
        &(g.x as i32 + 80).to_string(),
        &(g.y as i32 + 10).to_string(),
        "mousedown",
        "1",
        "mousemove",
        "--sync",
        &(target.x as i32 + target.width as i32 / 2).to_string(),
        &(target.y as i32 + target.height as i32 / 2).to_string(),
    ]);
    wait("second drag detached", || {
        property(&conn, windows[0], "_CARPATIC_FLOATING").unwrap_or_default() == vec![1]
    });
    let target = geometry(&conn, windows[1]);
    xdotool(&[
        "mousemove",
        "--sync",
        &(target.x as i32 + target.width as i32 / 2).to_string(),
        &(target.y as i32 + target.height as i32 / 2).to_string(),
    ]);
    wait("drop target highlighted", || {
        property(&conn, root, "_CARPATIC_DROP_TARGET").unwrap_or_default() == vec![windows[1]]
    });
    xdotool(&["mouseup", "1"]);
    wait("drop returns window to tiling", || {
        property(&conn, windows[0], "_CARPATIC_FLOATING").unwrap_or_default() == vec![0]
    });
    let dock = conn.generate_id()?;
    conn.create_window(
        0,
        dock,
        root,
        0,
        760,
        1280,
        40,
        0,
        WindowClass::INPUT_OUTPUT,
        0,
        &CreateWindowAux::new(),
    )?;
    conn.change_property32(
        PropMode::REPLACE,
        dock,
        atom(&conn, "_NET_WM_WINDOW_TYPE")?,
        AtomEnum::ATOM,
        &[atom(&conn, "_NET_WM_WINDOW_TYPE_DOCK")?],
    )?;
    conn.map_window(dock)?;
    conn.flush()?;
    wait("external panel receives tray handoff", || {
        conn.get_selection_owner(selection)
            .unwrap()
            .reply()
            .unwrap()
            .owner
            == 0
    });
    conn.destroy_window(dock)?;
    conn.flush()?;
    wait("native bar reclaims tray after panel closes", || {
        conn.get_selection_owner(selection)
            .unwrap()
            .reply()
            .unwrap()
            .owner
            == owner
    });
    for id in windows {
        conn.destroy_window(id)?;
    }
    conn.destroy_window(icon)?;
    conn.flush()?;
    xdotool(&["key", "super+shift+q"]);
    wait("bar WM exits", || wm.0.try_wait().unwrap().is_some());
    Ok(())
}

#[test]
#[ignore = "requires private Xvfb; run tests/run.sh"]
fn window_states_csd_shapes_and_restart() -> Result<()> {
    assert_eq!(
        std::env::var("CARPATIC_WM_TEST_DISPLAY").as_deref(),
        Ok("1")
    );
    let dir = std::path::PathBuf::from(std::env::var("CARPATIC_CONFIG_DIR")?);
    std::fs::write(
        dir.join("themes.toml"),
        "[appearance]\nworkspaces=4\ncorner_radius=12\n[titlebar]\nenabled=1\n",
    )?;
    std::fs::write(dir.join("hotkeys.toml"),"keys=[{mod='SUPER',key='f',func='togglefakefullscreen'},{mod='SUPER SHIFT',key='q',func='quit'}]\n")?;
    let (conn, screen) = x11rb::connect(None)?;
    let root = conn.setup().roots[screen].root;
    let mut wm = start()?;
    wait("state test WM ready", || ready(&conn, root, &wm));
    let id = conn.generate_id()?;
    conn.create_window(
        0,
        id,
        root,
        0,
        0,
        300,
        200,
        0,
        WindowClass::INPUT_OUTPUT,
        0,
        &CreateWindowAux::new(),
    )?;
    let state = atom(&conn, "_NET_WM_STATE")?;
    let sticky = atom(&conn, "_NET_WM_STATE_STICKY")?;
    conn.change_property32(PropMode::REPLACE, id, state, AtomEnum::ATOM, &[sticky])?;
    conn.map_window(id)?;
    conn.flush()?;
    wait("state client managed", || {
        property(&conn, root, "_NET_CLIENT_LIST")
            .unwrap_or_default()
            .contains(&id)
    });
    // EWMH registration precedes the first tiling ConfigureWindow. Compare
    // fullscreen against the settled tiled geometry, not the requested 300px.
    wait("state client initial tiling", || {
        geometry(&conn, id).width > 300
    });
    let before = geometry(&conn, id);
    xdotool(&["key", "super+f"]);
    let fullscreen = atom(&conn, "_NET_WM_STATE_FULLSCREEN")?;
    wait("fake fullscreen advertises state", || {
        property(&conn, id, "_NET_WM_STATE")
            .unwrap_or_default()
            .contains(&fullscreen)
    });
    assert_eq!(geometry(&conn, id).width, before.width);
    assert_eq!(geometry(&conn, id).y, before.y);
    assert!(property(&conn, id, "_NET_WM_STATE")?.contains(&sticky));
    xdotool(&["key", "super+f"]);
    wait("fake fullscreen removed", || {
        !property(&conn, id, "_NET_WM_STATE")
            .unwrap_or_default()
            .contains(&fullscreen)
    });
    use x11rb::protocol::shape::ConnectionExt as _;
    assert!(conn.shape_query_extents(id)?.reply()?.bounding_shaped);
    println!("PASS configured rounded client shape");
    wait("managed native chrome metadata ready", || {
        native_chrome(&conn, root, id).is_some()
    });
    let titlebar = native_chrome(&conn, root, id).expect("managed native chrome");
    conn.change_property32(
        PropMode::REPLACE,
        id,
        atom(&conn, "_GTK_FRAME_EXTENTS")?,
        AtomEnum::CARDINAL,
        &[0, 0, 0, 0],
    )?;
    conn.flush()?;
    wait("late CSD hides duplicate titlebar", || {
        conn.get_window_attributes(titlebar)
            .unwrap()
            .reply()
            .unwrap()
            .map_state
            == MapState::UNMAPPED
    });
    conn.delete_property(id, atom(&conn, "_GTK_FRAME_EXTENTS")?)?;
    conn.flush()?;
    wait("CSD removal restores native titlebar", || {
        conn.get_window_attributes(titlebar)
            .unwrap()
            .reply()
            .unwrap()
            .map_state
            == MapState::VIEWABLE
    });
    let max = atom(&conn, "_NET_WM_STATE_MAXIMIZED_VERT")?;
    message(&conn, root, id, "_NET_WM_STATE", [1, max, 0, 0, 0])?;
    wait("EWMH maximize add", || {
        property(&conn, id, "_NET_WM_STATE")
            .unwrap_or_default()
            .contains(&max)
    });
    message(&conn, root, id, "_NET_WM_STATE", [1, max, 0, 0, 0])?;
    thread::sleep(Duration::from_millis(80));
    assert!(property(&conn, id, "_NET_WM_STATE")?.contains(&max));
    assert!(property(&conn, id, "_NET_WM_STATE")?.contains(&sticky));
    message(&conn, root, id, "_NET_WM_STATE", [0, max, 0, 0, 0])?;
    wait("EWMH maximize remove", || {
        !property(&conn, id, "_NET_WM_STATE")
            .unwrap_or_default()
            .contains(&max)
    });
    message(&conn, root, id, "WM_CHANGE_STATE", [3, 0, 0, 0, 0])?;
    wait("minimized before restart", || {
        property(&conn, id, "WM_STATE").unwrap_or_default().first() == Some(&3)
    });
    xdotool(&["key", "super+shift+q"]);
    wait("state WM graceful exit", || {
        wm.0.try_wait().unwrap().is_some()
    });
    wm = start()?;
    wait("minimized client adopted after restart", || {
        ready(&conn, root, &wm)
            && property(&conn, root, "_NET_CLIENT_LIST")
                .unwrap_or_default()
                .contains(&id)
    });
    assert!(not_viewable(&conn, id));
    assert_eq!(property(&conn, id, "WM_STATE")?.first(), Some(&3));
    message(&conn, root, id, "_NET_ACTIVE_WINDOW", [1, 0, 0, 0, 0])?;
    wait("restart minimized client restored", || {
        conn.get_window_attributes(id)
            .unwrap()
            .reply()
            .unwrap()
            .map_state
            == MapState::VIEWABLE
    });
    assert!(property(&conn, id, "_NET_WM_STATE")?.contains(&sticky));
    conn.unmap_window(id)?;
    conn.flush()?;
    wait("withdrawn client removed", || {
        !property(&conn, root, "_NET_CLIENT_LIST")
            .unwrap_or_default()
            .contains(&id)
    });
    wait("withdrawn state cleared", || {
        property(&conn, id, "WM_STATE")
            .unwrap_or_default()
            .is_empty()
    });
    conn.destroy_window(id)?;
    conn.flush()?;
    xdotool(&["key", "super+shift+q"]);
    wait("state test exits", || wm.0.try_wait().unwrap().is_some());
    std::fs::remove_file(dir.join("hotkeys.toml"))?;
    Ok(())
}

#[test]
#[ignore = "requires private Xvfb; run tests/run.sh"]
fn complete_mouse_drop_modes_place_cancel_and_reload() -> Result<()> {
    assert_eq!(
        std::env::var("CARPATIC_WM_TEST_DISPLAY").as_deref(),
        Ok("1")
    );
    let dir = std::path::PathBuf::from(std::env::var("CARPATIC_CONFIG_DIR")?);
    let _config = ConfigRestore::new(&dir);
    let theme = |place: bool| {
        format!("[appearance]\nworkspaces=4\ninner_gap=12\nouter_gap=12\ndrag_tiled='{}'\n[titlebar]\nenabled=0\n",if place{"place"}else{"float"})
    };
    std::fs::write(dir.join("themes.toml"), theme(false))?;
    let keys="keys=[{mod='SUPER',key='space',func='togglefloating'},{mod='SUPER SHIFT',key='q',func='quit'}]\n";
    std::fs::write(
        dir.join("hotkeys.toml"),
        format!(
            "{keys}buttons=[{{click='ClkClientWin',mod='SUPER',button=1,func='moveorplace'}}]\n"
        ),
    )?;
    let (conn, screen) = x11rb::connect(None)?;
    let root = conn.setup().roots[screen].root;
    let mut wm = start()?;
    wait("full mouse WM ready", || ready(&conn, root, &wm));
    let mut windows = Vec::new();
    for _ in 0..4 {
        let id = conn.generate_id()?;
        conn.create_window(
            0,
            id,
            root,
            50,
            50,
            250,
            150,
            0,
            WindowClass::INPUT_OUTPUT,
            0,
            &CreateWindowAux::new(),
        )?;
        conn.map_window(id)?;
        windows.push(id);
    }
    conn.flush()?;
    wait("four drop clients managed", || {
        property(&conn, root, "_NET_CLIENT_LIST")
            .unwrap_or_default()
            .len()
            == 4
    });
    let dragged = windows[0];
    let target = windows[2];
    let begin = |modifier: &str| {
        let g = geometry(&conn, dragged);
        xdotool(&[
            "mousemove",
            "--sync",
            &(g.x as i32 + 30).to_string(),
            &(g.y as i32 + 30).to_string(),
            "keydown",
            modifier,
            "mousedown",
            "1",
        ]);
        wait("mouse grab active", || {
            property(&conn, root, "_CARPATIC_DRAGGING").unwrap_or_default() == vec![1]
        });
        xdotool(&["mousemove", "--sync", "8", "780"]);
        wait("tile pulled into floating", || {
            property(&conn, dragged, "_CARPATIC_FLOATING").unwrap_or_default() == vec![1]
        });
    };
    let point = |mode: u32| {
        let g = geometry(&conn, target);
        let x = if mode == 1 {
            g.x as i32 + 8
        } else if mode == 2 {
            g.x as i32 + g.width as i32 - 8
        } else {
            g.x as i32 + g.width as i32 / 2
        };
        let y = g.y as i32 + g.height as i32 / 2;
        xdotool(&["mousemove", "--sync", &x.to_string(), &y.to_string()]);
        wait("directional drop zone published", || {
            property(&conn, root, "_CARPATIC_DROP_ZONE")
                .unwrap_or_default()
                .get(2)
                == Some(&mode)
        });
        let zone = property(&conn, root, "_CARPATIC_DROP_ZONE").unwrap();
        assert_eq!(
            conn.get_window_attributes(zone[0])
                .unwrap()
                .reply()
                .unwrap()
                .map_state,
            MapState::VIEWABLE
        );
        use x11rb::protocol::shape::ConnectionExt as _;
        assert!(conn
            .shape_get_rectangles(zone[0], x11rb::protocol::shape::SK::INPUT)
            .unwrap()
            .reply()
            .unwrap()
            .rectangles
            .is_empty());
    };
    let release = |modifier: &str| {
        xdotool(&["mouseup", "1", "keyup", modifier]);
        wait("drop ends grab", || {
            property(&conn, root, "_CARPATIC_DRAGGING").unwrap_or_default() == vec![0]
        });
    };
    for mode in [1u32, 2, 3] {
        let original = property(&conn, root, "_NET_CLIENT_LIST")?;
        begin("Super_L");
        point(mode);
        release("Super_L");
        assert_eq!(property(&conn, dragged, "_CARPATIC_FLOATING")?, vec![0]);
        let order = property(&conn, root, "_NET_CLIENT_LIST")?;
        let a = order.iter().position(|id| *id == dragged).unwrap();
        let b = order.iter().position(|id| *id == target).unwrap();
        if mode == 1 {
            assert_eq!(a + 1, b);
        } else if mode == 2 {
            assert_eq!(b + 1, a);
        } else {
            assert_eq!(a, original.iter().position(|id| *id == target).unwrap());
            assert_eq!(b, original.iter().position(|id| *id == dragged).unwrap());
        }
        assert!(property(&conn, root, "_CARPATIC_DROP_ZONE")?.is_empty());
        println!("PASS mouse drop mode {mode}");
    }
    begin("Super_L"); // Release in a gap: remain freely movable.
    release("Super_L");
    assert_eq!(property(&conn, dragged, "_CARPATIC_FLOATING")?, vec![1]);
    message(&conn, root, dragged, "_NET_ACTIVE_WINDOW", [1, 0, 0, 0, 0])?;
    xdotool(&["key", "super+space"]);
    wait("keyboard returns to remembered tile", || {
        property(&conn, dragged, "_CARPATIC_FLOATING").unwrap_or_default() == vec![0]
    });
    let serial = property(&conn, root, "_CARPATIC_CONFIG_SERIAL")?
        .first()
        .copied()
        .unwrap_or(0);
    std::fs::write(
        dir.join("hotkeys.toml"),
        format!("{keys}buttons=[{{click='ClkClientWin',mod='ALT',button=1,func='moveorplace'}}]\n"),
    )?;
    wait("mouse bindings reloaded", || {
        property(&conn, root, "_CARPATIC_CONFIG_SERIAL")
            .unwrap_or_default()
            .first()
            .copied()
            .unwrap_or(0)
            > serial
    });
    begin("Alt_L");
    point(1);
    release("Alt_L");
    println!("PASS changed mouse modifier applies to existing windows");
    let serial = property(&conn, root, "_CARPATIC_CONFIG_SERIAL")?
        .first()
        .copied()
        .unwrap_or(0);
    std::fs::write(dir.join("themes.toml"), theme(true))?;
    wait("place mode reloaded", || {
        property(&conn, root, "_CARPATIC_CONFIG_SERIAL")
            .unwrap_or_default()
            .first()
            .copied()
            .unwrap_or(0)
            > serial
    });
    let original = property(&conn, root, "_NET_CLIENT_LIST")?;
    let g = geometry(&conn, dragged);
    let t = geometry(&conn, target);
    xdotool(&[
        "mousemove",
        "--sync",
        &(g.x as i32 + 30).to_string(),
        &(g.y as i32 + 30).to_string(),
        "keydown",
        "Alt_L",
        "mousedown",
        "1",
    ]);
    wait("live placement grab", || {
        property(&conn, root, "_CARPATIC_DRAGGING").unwrap_or_default() == vec![1]
    });
    xdotool(&[
        "mousemove",
        "--sync",
        &(t.x as i32 + t.width as i32 - 8).to_string(),
        &(t.y as i32 + t.height as i32 / 2).to_string(),
    ]);
    wait("live placement reorders before release", || {
        property(&conn, root, "_NET_CLIENT_LIST").unwrap_or_default() != original
    });
    assert_eq!(property(&conn, dragged, "_CARPATIC_FLOATING")?, vec![0]);
    xdotool(&["key", "Escape", "mouseup", "1", "keyup", "Alt_L"]);
    wait("Escape restores entire pre-drag order", || {
        property(&conn, root, "_NET_CLIENT_LIST").unwrap_or_default() == original
    });
    for id in windows {
        conn.destroy_window(id)?;
    }
    conn.flush()?;
    xdotool(&["key", "super+shift+q"]);
    wait("full mouse WM exits", || wm.0.try_wait().unwrap().is_some());
    std::fs::remove_file(dir.join("hotkeys.toml"))?;
    Ok(())
}

#[test]
#[ignore = "requires private Xvfb; run tests/run.sh"]
fn z_cross_monitor_drop_and_cancel() -> Result<()> {
    assert_eq!(
        std::env::var("CARPATIC_WM_TEST_DISPLAY").as_deref(),
        Ok("1")
    );
    use x11rb::protocol::randr::{ConnectionExt as _, MonitorInfo};
    let dir = std::path::PathBuf::from(std::env::var("CARPATIC_CONFIG_DIR")?);
    let _config = ConfigRestore::new(&dir);
    std::fs::write(
        dir.join("themes.toml"),
        "[appearance]\nworkspaces=4\n[titlebar]\nenabled=0\n",
    )?;
    let (conn, screen) = x11rb::connect(None)?;
    let root = conn.setup().roots[screen].root;
    let left_name = atom(&conn, "DROP_LEFT")?;
    let right_name = atom(&conn, "DROP_RIGHT")?;
    for (name, x, primary) in [(left_name, 0, true), (right_name, 640, false)] {
        conn.randr_set_monitor(
            root,
            MonitorInfo {
                name,
                primary,
                automatic: false,
                x,
                y: 0,
                width: 640,
                height: 800,
                width_in_millimeters: 169,
                height_in_millimeters: 212,
                outputs: vec![],
            },
        )?
        .check()?;
    }
    let mut wm = start()?;
    wait("cross-monitor WM ready", || ready(&conn, root, &wm));
    let mut windows = Vec::new();
    for x in [50, 700] {
        let id = conn.generate_id()?;
        conn.create_window(
            0,
            id,
            root,
            x,
            50,
            200,
            150,
            0,
            WindowClass::INPUT_OUTPUT,
            0,
            &CreateWindowAux::new(),
        )?;
        conn.map_window(id)?;
        windows.push(id);
    }
    conn.flush()?;
    wait("monitor drop clients ready", || {
        property(&conn, root, "_NET_CLIENT_LIST")
            .unwrap_or_default()
            .len()
            == 2
    });
    let left = windows[0];
    let right = windows[1];
    message(&conn, root, right, "_NET_ACTIVE_WINDOW", [1, 0, 0, 0, 0])?;
    wait("active window focuses right monitor", || {
        property(&conn, root, "_NET_ACTIVE_WINDOW").unwrap_or_default() == vec![right]
    });
    message(&conn, root, root, "_NET_CURRENT_DESKTOP", [1, 0, 0, 0, 0])?;
    wait("right monitor switched independently", || {
        not_viewable(&conn, right)
    });
    message(&conn, root, left, "_NET_ACTIVE_WINDOW", [1, 0, 0, 0, 0])?;
    wait("left monitor remains on first workspace", || {
        property(&conn, root, "_NET_CURRENT_DESKTOP").unwrap_or_default() == vec![0]
    });
    let original = geometry(&conn, left);
    let drag_to_right = || {
        xdotool(&[
            "mousemove",
            "--sync",
            &(original.x as i32 + 60).to_string(),
            &(original.y as i32 + 30).to_string(),
            "keydown",
            "Super_L",
            "mousedown",
            "1",
        ]);
        wait("cross-monitor drag started", || {
            property(&conn, root, "_CARPATIC_DRAGGING").unwrap_or_default() == vec![1]
        });
        xdotool(&["mousemove", "--sync", "900", "400"]);
        wait("empty destination preview", || {
            property(&conn, root, "_CARPATIC_DROP_ZONE")
                .unwrap_or_default()
                .get(2)
                == Some(&4)
        });
        assert_eq!(property(&conn, left, "_NET_WM_DESKTOP").unwrap(), vec![1]);
    };
    drag_to_right();
    xdotool(&["key", "Escape", "mouseup", "1", "keyup", "Super_L"]);
    wait("cancel restores original monitor and tag", || {
        property(&conn, left, "_NET_WM_DESKTOP").unwrap_or_default() == vec![0]
            && geometry(&conn, left).x == original.x
            && property(&conn, root, "_CARPATIC_DRAGGING").unwrap_or_default() == vec![0]
    });
    drag_to_right();
    xdotool(&["mouseup", "1", "keyup", "Super_L"]);
    wait("empty monitor drop retiles on its workspace", || {
        geometry(&conn, left).x >= 640
            && property(&conn, left, "_CARPATIC_FLOATING").unwrap_or_default() == vec![0]
            && property(&conn, root, "_CARPATIC_DRAGGING").unwrap_or_default() == vec![0]
    });
    assert_eq!(property(&conn, left, "_CARPATIC_TAGS")?, vec![2]);
    conn.randr_delete_monitor(root, right_name)?.check()?;
    wait(
        "removed monitor moves client onto surviving display",
        || geometry(&conn, left).x < 640,
    );
    for id in windows {
        conn.destroy_window(id)?;
    }
    conn.flush()?;
    xdotool(&["key", "super+shift+q"]);
    wait("cross-monitor WM exits", || {
        wm.0.try_wait().unwrap().is_some()
    });
    conn.randr_delete_monitor(root, left_name)?.check()?;
    Ok(())
}

#[test]
#[ignore = "requires private Xvfb; run tests/run.sh"]
fn urgency_show_desktop_aspect_and_recent_minimized() -> Result<()> {
    assert_eq!(
        std::env::var("CARPATIC_WM_TEST_DISPLAY").as_deref(),
        Ok("1")
    );
    let dir = std::path::PathBuf::from(std::env::var("CARPATIC_CONFIG_DIR")?);
    let _config = ConfigRestore::new(&dir);
    std::fs::write(
        dir.join("themes.toml"),
        "[appearance]\nworkspaces=4\n[bar]\nenabled=1\n[titlebar]\nenabled=1\n",
    )?;
    std::fs::write(dir.join("hotkeys.toml"),"keys=[{mod='SUPER',key='d',func='showdesktop'},{mod='SUPER',key='m',func='unminimize'},{mod='SUPER SHIFT',key='q',func='quit'}]\n")?;
    let (conn, screen) = x11rb::connect(None)?;
    let root = conn.setup().roots[screen].root;
    let mut wm = start()?;
    wait("extended state WM ready", || ready(&conn, root, &wm));
    let mut windows = Vec::new();
    for _ in 0..2 {
        let id = conn.generate_id()?;
        conn.create_window(
            0,
            id,
            root,
            20,
            20,
            200,
            150,
            0,
            WindowClass::INPUT_OUTPUT,
            0,
            &CreateWindowAux::new(),
        )?;
        conn.map_window(id)?;
        windows.push(id);
    }
    conn.flush()?;
    wait("state clients ready", || {
        property(&conn, root, "_NET_CLIENT_LIST")
            .unwrap_or_default()
            .len()
            == 2
    });
    message(
        &conn,
        root,
        windows[1],
        "_NET_ACTIVE_WINDOW",
        [1, 0, 0, 0, 0],
    )?;
    wait("second client active", || {
        property(&conn, root, "_NET_ACTIVE_WINDOW").unwrap_or_default() == vec![windows[1]]
    });
    x11rb::properties::WmHints {
        urgent: true,
        ..x11rb::properties::WmHints::new()
    }
    .set(&conn, windows[0])?;
    conn.flush()?;
    let attention = atom(&conn, "_NET_WM_STATE_DEMANDS_ATTENTION")?;
    wait("urgency appears in workspace indicator", || {
        property(&conn, root, "_CARPATIC_URGENT_TAGS").unwrap_or_default() == vec![1]
    });
    assert!(property(&conn, windows[0], "_NET_WM_STATE")?.contains(&attention));
    message(
        &conn,
        root,
        windows[0],
        "_NET_ACTIVE_WINDOW",
        [1, 0, 0, 0, 0],
    )?;
    wait("focus clears urgency", || {
        property(&conn, root, "_CARPATIC_URGENT_TAGS").unwrap_or_default() == vec![0]
    });
    assert!(
        !x11rb::properties::WmHints::get(&conn, windows[0])?
            .reply()?
            .unwrap()
            .urgent
    );
    xdotool(&["key", "super+d"]);
    wait("show desktop hides app windows", || {
        property(&conn, root, "_NET_SHOWING_DESKTOP").unwrap_or_default() == vec![1]
            && windows.iter().all(|id| not_viewable(&conn, *id))
    });
    xdotool(&["key", "super+d"]);
    wait("show desktop toggle restores app windows", || {
        windows.iter().all(|id| {
            conn.get_window_attributes(*id)
                .unwrap()
                .reply()
                .unwrap()
                .map_state
                == MapState::VIEWABLE
        })
    });
    message(&conn, root, windows[1], "WM_CHANGE_STATE", [3, 0, 0, 0, 0])?;
    wait("second minimized first", || {
        property(&conn, windows[1], "WM_STATE")
            .unwrap_or_default()
            .first()
            == Some(&3)
    });
    message(&conn, root, windows[0], "WM_CHANGE_STATE", [3, 0, 0, 0, 0])?;
    wait("first minimized most recently", || {
        property(&conn, windows[0], "WM_STATE")
            .unwrap_or_default()
            .first()
            == Some(&3)
    });
    xdotool(&["key", "super+m"]);
    wait("restore chooses most recent minimized window", || {
        property(&conn, windows[0], "WM_STATE")
            .unwrap_or_default()
            .first()
            == Some(&1)
    });
    assert_eq!(property(&conn, windows[1], "WM_STATE")?.first(), Some(&3));
    let app = conn.generate_id()?;
    conn.create_window(
        0,
        app,
        root,
        100,
        100,
        300,
        120,
        0,
        WindowClass::INPUT_OUTPUT,
        0,
        &CreateWindowAux::new(),
    )?;
    conn.change_property32(
        PropMode::REPLACE,
        app,
        atom(&conn, "_NET_WM_WINDOW_TYPE")?,
        AtomEnum::ATOM,
        &[atom(&conn, "_NET_WM_WINDOW_TYPE_DIALOG")?],
    )?;
    use x11rb::properties::{AspectRatio, WmSizeHints};
    WmSizeHints {
        aspect: Some((AspectRatio::new(1, 1), AspectRatio::new(1, 1))),
        min_size: Some((50, 50)),
        ..WmSizeHints::new()
    }
    .set_normal_hints(&conn, app)?;
    conn.map_window(app)?;
    conn.flush()?;
    wait("floating application honors content aspect", || {
        let g = geometry(&conn, app);
        g.width == g.height && g.width >= 50
    });
    let frame = conn.query_tree(app)?.reply()?.parent;
    let outer = conn.get_geometry(frame)?.reply()?;
    assert_eq!(
        property(&conn, app, "_CARPATIC_FRAME_GEOMETRY")?,
        vec![
            outer.x as u32,
            outer.y as u32,
            u32::from(outer.width),
            u32::from(outer.height)
        ],
        "restart metadata must describe the constrained frame"
    );
    assert!(
        property(&conn, app, "_NET_FRAME_EXTENTS")?[2]
            > property(&conn, app, "_NET_FRAME_EXTENTS")?[0]
    );
    for id in windows {
        conn.destroy_window(id)?;
    }
    conn.destroy_window(app)?;
    conn.flush()?;
    xdotool(&["key", "super+shift+q"]);
    wait("extended state WM exits", || {
        wm.0.try_wait().unwrap().is_some()
    });
    Ok(())
}

#[test]
#[ignore = "requires private Xvfb; run tests/run.sh"]
fn combined_states_icons_priority_and_all_tag_layout_memory() -> Result<()> {
    assert_eq!(
        std::env::var("CARPATIC_WM_TEST_DISPLAY").as_deref(),
        Ok("1")
    );
    let dir = std::path::PathBuf::from(std::env::var("CARPATIC_CONFIG_DIR")?);
    let _config = ConfigRestore::new(&dir);
    std::fs::write(
        dir.join("themes.toml"),
        "[appearance]\nworkspaces=4\n[bar]\nenabled=1\n[titlebar]\nenabled=1\n",
    )?;
    std::fs::write(
        dir.join("window-rules.toml"),
        "rules=[{title='Priority overlay',alwaysontop=1}]\n",
    )?;
    std::fs::write(dir.join("hotkeys.toml"),"keys=[{mod='SUPER',key='0',func='view',ui=-1},{mod='SUPER',key='1',func='view',ui=1},{mod='SUPER',key='2',func='view',ui=2},{mod='SUPER',key='f',func='setlayout',layout_idx=1},{mod='SUPER SHIFT',key='q',func='quit'}]\n")?;
    let (conn, screen) = x11rb::connect(None)?;
    let root = conn.setup().roots[screen].root;
    let mut wm = start()?;
    wait("complete protocol WM ready", || ready(&conn, root, &wm));
    let id = conn.generate_id()?;
    conn.create_window(
        0,
        id,
        root,
        20,
        20,
        300,
        200,
        0,
        WindowClass::INPUT_OUTPUT,
        0,
        &CreateWindowAux::new(),
    )?;
    conn.change_property32(
        PropMode::REPLACE,
        id,
        atom(&conn, "_NET_WM_ICON")?,
        AtomEnum::CARDINAL,
        &[2, 2, 0xffdd3322, 0xffdd3322, 0xffdd3322, 0xffdd3322],
    )?;
    conn.map_window(id)?;
    conn.flush()?;
    wait("icon client managed", || {
        property(&conn, root, "_NET_CLIENT_LIST")
            .unwrap_or_default()
            .contains(&id)
    });
    let titlebar = native_chrome(&conn, root, id).expect("managed native chrome");
    wait("native titlebar paints application icon", || {
        conn.get_image(ImageFormat::Z_PIXMAP, titlebar, 20, 17, 1, 1, u32::MAX)
            .ok()
            .and_then(|cookie| cookie.reply().ok())
            .is_some_and(|reply| reply.data.get(..3) == Some(&[0x22, 0x33, 0xdd]))
    });
    let layout = || {
        conn.get_property(
            false,
            root,
            atom(&conn, "_CARPATIC_LAYOUT").unwrap(),
            AtomEnum::ANY,
            0,
            16,
        )
        .unwrap()
        .reply()
        .unwrap()
        .value
    };
    xdotool(&["key", "super+0"]);
    thread::sleep(Duration::from_millis(50));
    xdotool(&["key", "super+f"]);
    wait("all-tag view chooses floating", || layout() == b"float");
    xdotool(&["key", "super+1"]);
    wait("first tag retains tile layout", || layout() == b"tile");
    xdotool(&["key", "super+0"]);
    wait("all-tag view retains its own layout", || {
        layout() == b"float"
    });
    xdotool(&["key", "super+1"]);
    wait("back to first tag", || layout() == b"tile");
    let fullscreen = atom(&conn, "_NET_WM_STATE_FULLSCREEN")?;
    let above = atom(&conn, "_NET_WM_STATE_ABOVE")?;
    message(
        &conn,
        root,
        id,
        "_NET_WM_STATE",
        [1, fullscreen, above, 0, 0],
    )?;
    wait("both EWMH state atoms are applied", || {
        let states = property(&conn, id, "_NET_WM_STATE").unwrap_or_default();
        states.contains(&fullscreen) && states.contains(&above)
    });
    let overlay = conn.generate_id()?;
    conn.create_window(
        0,
        overlay,
        root,
        50,
        50,
        100,
        60,
        0,
        WindowClass::INPUT_OUTPUT,
        0,
        &CreateWindowAux::new()
            .override_redirect(1)
            .background_pixel(0x33aa77),
    )?;
    conn.change_property8(
        PropMode::REPLACE,
        overlay,
        AtomEnum::WM_NAME,
        AtomEnum::STRING,
        b"Priority overlay",
    )?;
    conn.map_window(overlay)?;
    conn.flush()?;
    message(&conn, root, id, "_NET_WM_STATE", [1, fullscreen, 0, 0, 0])?;
    wait("priority unmanaged overlay stays above fullscreen", || {
        let children = conn.query_tree(root).unwrap().reply().unwrap().children;
        children.iter().position(|w| *w == overlay)
            > children.iter().position(|w| *w == root_surface(&conn, id))
    });
    let locker = conn.generate_id()?;
    conn.create_window(
        0,
        locker,
        root,
        0,
        0,
        1280,
        800,
        0,
        WindowClass::INPUT_OUTPUT,
        0,
        &CreateWindowAux::new()
            .override_redirect(1)
            .background_pixel(0x101010),
    )?;
    conn.change_property8(
        PropMode::REPLACE,
        locker,
        AtomEnum::WM_CLASS,
        AtomEnum::STRING,
        b"i3lock\0i3lock\0",
    )?;
    conn.map_window(locker)?;
    conn.flush()?;
    let lock_on_top = || {
        let children = conn.query_tree(root).unwrap().reply().unwrap().children;
        children.iter().rev().find(|w| {
            conn.get_window_attributes(**w)
                .unwrap()
                .reply()
                .is_ok_and(|a| a.map_state == MapState::VIEWABLE)
        }) == Some(&locker)
    };
    wait("locker covers all mapped chrome and overlays", lock_on_top);
    conn.change_property8(
        PropMode::REPLACE,
        root,
        AtomEnum::WM_NAME,
        AtomEnum::STRING,
        b"status update while locked",
    )?;
    conn.flush()?;
    std::thread::sleep(std::time::Duration::from_millis(100));
    wait("native bar status redraw stays beneath locker", lock_on_top);
    conn.configure_window(
        overlay,
        &ConfigureWindowAux::new().stack_mode(StackMode::ABOVE),
    )?;
    conn.flush()?;
    wait(
        "locker remains above independently raised panel",
        lock_on_top,
    );
    // A new unmanaged notification must not appear above an existing locker.
    let notification = conn.generate_id()?;
    conn.create_window(
        0,
        notification,
        root,
        900,
        20,
        200,
        60,
        0,
        WindowClass::INPUT_OUTPUT,
        0,
        &CreateWindowAux::new().override_redirect(1),
    )?;
    conn.map_window(notification)?;
    conn.flush()?;
    wait("locker covers newly mapped notification", lock_on_top);
    conn.destroy_window(locker)?;
    conn.destroy_window(notification)?;
    conn.configure_window(
        overlay,
        &ConfigureWindowAux::new().stack_mode(StackMode::ABOVE),
    )?;
    conn.flush()?;
    wait("panel can raise again after unlock", || {
        conn.query_tree(root)
            .unwrap()
            .reply()
            .unwrap()
            .children
            .last()
            == Some(&overlay)
    });
    message(
        &conn,
        root,
        id,
        "_NET_WM_STATE",
        [0, fullscreen, above, 0, 0],
    )?;
    wait("combined state removal", || {
        let states = property(&conn, id, "_NET_WM_STATE").unwrap_or_default();
        !states.contains(&fullscreen) && !states.contains(&above)
    });
    conn.destroy_window(overlay)?;
    conn.destroy_window(id)?;
    conn.flush()?;
    xdotool(&["key", "super+shift+q"]);
    wait("complete protocol WM exits", || {
        wm.0.try_wait().unwrap().is_some()
    });
    Ok(())
}

#[test]
#[ignore = "requires private Xvfb"]
fn click_focus_replay_and_temporary_fullscreen_spaces() -> Result<()> {
    let dir = std::path::PathBuf::from(std::env::var("CARPATIC_CONFIG_DIR")?);
    let _config = ConfigRestore::new(&dir);
    std::fs::write(
        dir.join("themes.toml"),
        "[appearance]\nworkspaces=4\ncorner_radius=12\n[titlebar]\nenabled=1\n",
    )?;
    std::fs::write(
        dir.join("hotkeys.toml"),
        "keys=[{mod='SUPER SHIFT',key='q',func='quit'}]\n",
    )?;
    let (conn, screen) = x11rb::connect(None)?;
    let root = conn.setup().roots[screen].root;
    let mut wm = start_with_policy(true, false)?;
    wait("click-focus WM ready", || ready(&conn, root, &wm));
    let mut ids = Vec::new();
    for title in [
        b"Fullscreen app A".as_slice(),
        b"Fullscreen app B".as_slice(),
    ] {
        let id = conn.generate_id()?;
        conn.create_window(
            0,
            id,
            root,
            40,
            80,
            320,
            200,
            0,
            WindowClass::INPUT_OUTPUT,
            0,
            &CreateWindowAux::new().event_mask(EventMask::BUTTON_PRESS | EventMask::BUTTON_RELEASE),
        )?;
        conn.change_property8(
            PropMode::REPLACE,
            id,
            AtomEnum::WM_NAME,
            AtomEnum::STRING,
            title,
        )?;
        conn.map_window(id)?;
        conn.flush()?;
        wait("test app mapped", || {
            property(&conn, root, "_NET_ACTIVE_WINDOW").unwrap_or_default() == vec![id]
        });
        ids.push(id);
    }
    let geometry = geometry(&conn, ids[0]);
    let x = (i32::from(geometry.x) + 60).to_string();
    let y = (i32::from(geometry.y) + 60).to_string();
    xdotool(&["mousemove", &x, &y]);
    thread::sleep(Duration::from_millis(100));
    assert_eq!(
        property(&conn, root, "_NET_ACTIVE_WINDOW")?,
        vec![ids[1]],
        "hover must not change focus"
    );
    xdotool(&["click", "3"]);
    let mut delivered = false;
    wait("right click focuses and reaches the app", || {
        while let Some(event) = conn.poll_for_event().unwrap() {
            if let x11rb::protocol::Event::ButtonPress(e) = event {
                delivered |= e.event == ids[0] && e.detail == 3;
            }
        }
        delivered && property(&conn, root, "_NET_ACTIVE_WINDOW").unwrap_or_default() == vec![ids[0]]
    });
    let full = atom(&conn, "_NET_WM_STATE_FULLSCREEN")?;
    let chrome = native_chrome(&conn, root, ids[0]).expect("managed native chrome");
    // Scroll clicks in an already focused client must be replayed without
    // repainting its separate titlebar (which produces visible border flicker).
    conn.change_window_attributes(
        chrome,
        &ChangeWindowAttributesAux::new().event_mask(EventMask::PROPERTY_CHANGE),
    )?;
    conn.get_input_focus()?.reply()?;
    thread::sleep(Duration::from_millis(150));
    while conn.poll_for_event()?.is_some() {}
    let buttons_atom = atom(&conn, "_CARPATIC_BUTTONS")?;
    xdotool(&["click", "--repeat", "6", "--delay", "15", "5"]);
    let mut scrolls = 0;
    let mut repaints = 0;
    wait("all wheel clicks reach focused app", || {
        while let Some(event) = conn.poll_for_event().unwrap() {
            match event {
                x11rb::protocol::Event::ButtonPress(e) if e.event == ids[0] && e.detail == 5 => {
                    scrolls += 1
                }
                x11rb::protocol::Event::PropertyNotify(e)
                    if e.window == chrome && e.atom == buttons_atom =>
                {
                    repaints += 1
                }
                _ => {}
            }
        }
        scrolls == 6
    });
    thread::sleep(Duration::from_millis(100));
    while let Some(event) = conn.poll_for_event()? {
        if let x11rb::protocol::Event::PropertyNotify(e) = event {
            if e.window == chrome && e.atom == buttons_atom {
                repaints += 1;
            }
        }
    }
    assert_eq!(repaints, 0, "scroll must not repaint titlebar buttons");
    assert_eq!(property(&conn, root, "_NET_ACTIVE_WINDOW")?, vec![ids[0]]);
    assert_eq!(property(&conn, ids[0], "_CARPATIC_ANIMATION")?, vec![0]);
    assert_eq!(property(&conn, chrome, "_CARPATIC_ANIMATION")?, vec![0]);
    let compositor = conn.generate_id()?;
    conn.create_window(
        0,
        compositor,
        root,
        -1,
        -1,
        1,
        1,
        0,
        WindowClass::INPUT_OUTPUT,
        0,
        &CreateWindowAux::new().override_redirect(1),
    )?;
    let selection = atom(&conn, "_NET_WM_CM_S0")?;
    conn.set_selection_owner(compositor, selection, x11rb::CURRENT_TIME)?;
    conn.change_property32(
        PropMode::REPLACE,
        root,
        atom(&conn, "_CARPATIC_ANIMATION_PREPARE")?,
        AtomEnum::CARDINAL,
        &[50],
    )?;
    message(&conn, root, ids[0], "WM_CHANGE_STATE", [3, 0, 0, 0, 0])?;
    wait("minimise marks both client and titlebar", || {
        property(&conn, ids[0], "_CARPATIC_ANIMATION").unwrap_or_default() == vec![1]
            && property(&conn, chrome, "_CARPATIC_ANIMATION").unwrap_or_default() == vec![1]
    });
    wait("staged minimise unmaps without further input", || {
        not_viewable(&conn, ids[0])
    });
    conn.set_selection_owner(0u32, selection, x11rb::CURRENT_TIME)?;
    conn.delete_property(root, atom(&conn, "_CARPATIC_ANIMATION_PREPARE")?)?;
    conn.destroy_window(compositor)?;
    message(&conn, root, ids[0], "_NET_ACTIVE_WINDOW", [1, 0, 0, 0, 0])?;
    wait("restore marks both client and titlebar", || {
        property(&conn, ids[0], "_CARPATIC_ANIMATION").unwrap_or_default() == vec![2]
            && property(&conn, chrome, "_CARPATIC_ANIMATION").unwrap_or_default() == vec![2]
    });
    wait("restore animation markers expire without input", || {
        property(&conn, ids[0], "_CARPATIC_ANIMATION").unwrap_or_default() == vec![0]
            && property(&conn, chrome, "_CARPATIC_ANIMATION").unwrap_or_default() == vec![0]
    });
    message(&conn, root, ids[0], "_NET_WM_STATE", [1, full, 0, 0, 0])?;
    wait("fullscreen creates and selects a fifth workspace", || {
        property(&conn, root, "_NET_NUMBER_OF_DESKTOPS").unwrap_or_default() == vec![5]
            && property(&conn, root, "_NET_CURRENT_DESKTOP").unwrap_or_default() == vec![4]
            && property(&conn, ids[0], "_NET_WM_DESKTOP").unwrap_or_default() == vec![4]
    });
    message(&conn, root, root, "_NET_CURRENT_DESKTOP", [0, 0, 0, 0, 0])?;
    wait("ordinary desktop remains selectable", || {
        property(&conn, root, "_NET_CURRENT_DESKTOP").unwrap_or_default() == vec![0]
    });
    message(&conn, root, ids[1], "_NET_WM_STATE", [1, full, 0, 0, 0])?;
    wait("second fullscreen app gets its own workspace", || {
        property(&conn, root, "_NET_NUMBER_OF_DESKTOPS").unwrap_or_default() == vec![6]
    });
    conn.destroy_window(ids[0])?;
    conn.flush()?;
    wait(
        "closing first app removes its space and compacts the second",
        || {
            property(&conn, root, "_NET_NUMBER_OF_DESKTOPS").unwrap_or_default() == vec![5]
                && property(&conn, ids[1], "_NET_WM_DESKTOP").unwrap_or_default() == vec![4]
                && property(&conn, root, "_NET_CURRENT_DESKTOP").unwrap_or_default() == vec![4]
        },
    );
    message(&conn, root, ids[1], "_NET_WM_STATE", [0, full, 0, 0, 0])?;
    wait("leaving fullscreen restores the original desktop", || {
        property(&conn, root, "_NET_NUMBER_OF_DESKTOPS").unwrap_or_default() == vec![4]
            && property(&conn, ids[1], "_NET_WM_DESKTOP").unwrap_or_default() == vec![0]
            && property(&conn, root, "_NET_CURRENT_DESKTOP").unwrap_or_default() == vec![0]
    });
    message(&conn, root, ids[1], "_NET_WM_STATE", [1, full, 0, 0, 0])?;
    wait("fullscreen space recreated", || {
        property(&conn, root, "_NET_NUMBER_OF_DESKTOPS").unwrap_or_default() == vec![5]
    });
    xdotool(&["key", "super+shift+q"]);
    wait("WM exits with fullscreen app alive", || {
        wm.0.try_wait().unwrap().is_some()
    });
    wm = start_with_policy(true, false)?;
    wait("restart adopts fullscreen app and its origin", || {
        ready(&conn, root, &wm)
            && property(&conn, root, "_NET_NUMBER_OF_DESKTOPS").unwrap_or_default() == vec![5]
    });
    message(&conn, root, ids[1], "_NET_WM_STATE", [0, full, 0, 0, 0])?;
    wait("restart exit restores original tags", || {
        property(&conn, ids[1], "_CARPATIC_TAGS").unwrap_or_default() == vec![1]
    });
    conn.destroy_window(ids[1])?;
    conn.flush()?;
    xdotool(&["key", "super+shift+q"]);
    wait("click-focus test WM exits", || {
        wm.0.try_wait().unwrap().is_some()
    });
    Ok(())
}

#[test]
#[ignore = "requires private Xvfb; run tests/run.sh"]
fn desktop_surfaces_stay_below_apps_and_receive_input() -> Result<()> {
    assert_eq!(
        std::env::var("CARPATIC_WM_TEST_DISPLAY").as_deref(),
        Ok("1")
    );
    let display = std::env::var("DISPLAY")?;
    assert!(display != ":0" && display != ":1");
    assert!(std::env::var_os("WAYLAND_DISPLAY").is_none());
    let (conn, screen) = x11rb::connect(None)?;
    let root = conn.setup().roots[screen].root;
    let mut wm = start()?;
    wait("desktop test WM", || ready(&conn, root, &wm));
    let desktop = conn.generate_id()?;
    conn.create_window(
        0,
        desktop,
        root,
        0,
        0,
        1280,
        800,
        0,
        WindowClass::INPUT_OUTPUT,
        0,
        &CreateWindowAux::new()
            .background_pixel(0x304050)
            .event_mask(EventMask::BUTTON_PRESS | EventMask::BUTTON_RELEASE),
    )?;
    conn.change_property32(
        PropMode::REPLACE,
        desktop,
        atom(&conn, "_NET_WM_WINDOW_TYPE")?,
        AtomEnum::ATOM,
        &[atom(&conn, "_NET_WM_WINDOW_TYPE_DESKTOP")?],
    )?;
    conn.map_window(desktop)?;
    conn.flush()?;
    wait("file desktop registered", || {
        property(&conn, root, "_NET_CLIENT_LIST")
            .unwrap_or_default()
            .contains(&desktop)
    });
    assert_eq!(geometry(&conn, desktop).width, 1280);
    assert_eq!(geometry(&conn, desktop).height, 800);
    assert_eq!(property(&conn, desktop, "_NET_WM_DESKTOP")?, vec![u32::MAX]);
    let app = conn.generate_id()?;
    conn.create_window(
        0,
        app,
        root,
        100,
        100,
        400,
        250,
        0,
        WindowClass::INPUT_OUTPUT,
        0,
        &CreateWindowAux::new().background_pixel(0x25a9df),
    )?;
    conn.map_window(app)?;
    conn.flush()?;
    wait("normal app managed", || {
        property(&conn, root, "_NET_ACTIVE_WINDOW").unwrap_or_default() == vec![app]
    });
    let app_geometry = geometry(&conn, app);
    conn.configure_window(
        desktop,
        &ConfigureWindowAux::new()
            .stack_mode(StackMode::ABOVE)
            .width(1200),
    )?;
    conn.flush()?;
    wait("desktop may resize without covering apps", || {
        let tree = conn.query_tree(root).unwrap().reply().unwrap().children;
        geometry(&conn, desktop).width == 1200
            && tree.iter().position(|id| *id == desktop)
                < tree.iter().position(|id| *id == root_surface(&conn, app))
    });
    assert_eq!(geometry(&conn, app).width, app_geometry.width);
    message(&conn, root, root, "_NET_CURRENT_DESKTOP", [1, 0, 0, 0, 0])?;
    wait("desktop persists on another workspace", || {
        conn.get_window_attributes(desktop)
            .unwrap()
            .reply()
            .unwrap()
            .map_state
            == MapState::VIEWABLE
            && property(&conn, root, "_NET_CURRENT_DESKTOP").unwrap_or_default() == vec![1]
    });
    message(&conn, root, desktop, "_NET_ACTIVE_WINDOW", [1, 0, 0, 0, 0])?;
    wait("desktop keyboard focus", || {
        conn.get_input_focus().unwrap().reply().unwrap().focus == desktop
    });
    conn.set_input_focus(InputFocus::POINTER_ROOT, root, x11rb::CURRENT_TIME)?;
    conn.flush()?;
    xdotool(&["mousemove", "500", "500", "click", "1"]);
    wait("desktop selection click transfers native focus", || {
        conn.get_input_focus().unwrap().reply().unwrap().focus == desktop
    });
    xdotool(&["mousemove", "500", "500", "click", "3"]);
    wait("root passive grab replays desktop context click", || {
        while let Some(event) = conn.poll_for_event().unwrap() {
            if let x11rb::protocol::Event::ButtonPress(event) = event {
                if event.event == desktop && event.detail == 3 {
                    return true;
                }
            }
        }
        false
    });
    wm.0.kill()?;
    wm.0.wait()?;
    wm = start()?;
    wait("desktop restart adoption", || {
        ready(&conn, root, &wm)
            && property(&conn, root, "_NET_CLIENT_LIST")
                .unwrap_or_default()
                .contains(&desktop)
    });
    assert_eq!(geometry(&conn, desktop).width, 1200);
    conn.destroy_window(desktop)?;
    conn.flush()?;
    wait("desktop destruction removes EWMH entry", || {
        !property(&conn, root, "_NET_CLIENT_LIST")
            .unwrap_or_default()
            .contains(&desktop)
    });
    conn.destroy_window(app)?;
    conn.flush()?;
    Ok(())
}

#[test]
#[ignore = "requires private Xvfb; run tests/run.sh"]
fn native_frame_groups_chrome_and_preserves_clients() -> Result<()> {
    assert_eq!(
        std::env::var("CARPATIC_WM_TEST_DISPLAY").as_deref(),
        Ok("1")
    );
    assert!(!matches!(
        std::env::var("DISPLAY").as_deref(),
        Ok(":0" | ":1")
    ));
    assert!(std::env::var_os("WAYLAND_DISPLAY").is_none());
    let dir = std::path::PathBuf::from(std::env::var("CARPATIC_CONFIG_DIR")?);
    let _config = ConfigRestore::new(&dir);
    std::fs::write(
        dir.join("themes.toml"),
        "[appearance]\nworkspaces=4\n[titlebar]\nenabled=1\nfloating=1\ntiled=1\n",
    )?;
    std::fs::write(
        dir.join("hotkeys.toml"),
        "keys=[{mod='SUPER SHIFT',key='q',func='quit'}]\n",
    )?;
    let (conn, screen) = x11rb::connect(None)?;
    let root = conn.setup().roots[screen].root;
    conn.change_window_attributes(
        root,
        &ChangeWindowAttributesAux::new().event_mask(EventMask::SUBSTRUCTURE_NOTIFY),
    )?;
    let mut wm = start_with_policy(false, false)?;
    wait("frame regression WM ready", || ready(&conn, root, &wm));
    // A client which initially supplies CSD must still enter the shared frame
    // when it later asks for native decorations; keeping root siblings here
    // would reintroduce independently animated chrome.
    let dynamic = conn.generate_id()?;
    conn.create_window(
        0,
        dynamic,
        root,
        120,
        140,
        340,
        180,
        0,
        WindowClass::INPUT_OUTPUT,
        0,
        &CreateWindowAux::new().background_pixel(0x25a9df),
    )?;
    conn.change_property32(
        PropMode::REPLACE,
        dynamic,
        atom(&conn, "_GTK_FRAME_EXTENTS")?,
        AtomEnum::CARDINAL,
        &[8, 8, 8, 8],
    )?;
    conn.map_window(dynamic)?;
    conn.flush()?;
    wait("initial CSD retains single client surface", || {
        property(&conn, root, "_NET_CLIENT_LIST")
            .unwrap_or_default()
            .contains(&dynamic)
    });
    assert_eq!(conn.query_tree(dynamic)?.reply()?.parent, root);
    conn.delete_property(dynamic, atom(&conn, "_GTK_FRAME_EXTENTS")?)?;
    conn.flush()?;
    wait("CSD to native transition creates shared frame", || {
        let parent = conn.query_tree(dynamic).unwrap().reply().unwrap().parent;
        parent != root && native_chrome(&conn, root, dynamic).is_some()
    });
    conn.destroy_window(dynamic)?;
    conn.flush()?;
    wait("dynamic CSD client removal leaves no phantom", || {
        !property(&conn, root, "_NET_CLIENT_LIST")
            .unwrap_or_default()
            .contains(&dynamic)
    });
    let visual = conn.setup().roots[screen]
        .allowed_depths
        .iter()
        .find(|depth| depth.depth == 32)
        .and_then(|depth| depth.visuals.first())
        .expect("private Xvfb must provide a 32-bit client visual");
    let argb_map = conn.generate_id()?;
    conn.create_colormap(ColormapAlloc::NONE, argb_map, root, visual.visual_id)?;
    let argb = conn.generate_id()?;
    conn.create_window(
        32,
        argb,
        root,
        180,
        190,
        300,
        160,
        0,
        WindowClass::INPUT_OUTPUT,
        visual.visual_id,
        &CreateWindowAux::new()
            .colormap(argb_map)
            .background_pixel(0x8025a9df)
            .border_pixel(0),
    )?
    .check()?;
    conn.map_window(argb)?;
    conn.flush()?;
    wait("ARGB native client gets compatible common frame", || {
        let parent = conn.query_tree(argb).unwrap().reply().unwrap().parent;
        parent != root
            && conn
                .get_window_attributes(argb)
                .unwrap()
                .reply()
                .unwrap()
                .map_state
                == MapState::VIEWABLE
            && conn.get_geometry(parent).unwrap().reply().unwrap().depth == 32
            && native_chrome(&conn, root, argb).is_some()
    });
    conn.destroy_window(argb)?;
    conn.free_colormap(argb_map)?;
    conn.flush()?;
    wait("ARGB removal leaves no phantom frame", || {
        !property(&conn, root, "_NET_CLIENT_LIST")
            .unwrap_or_default()
            .contains(&argb)
    });
    let mut apps = Vec::new();
    for title in [
        b"First grouped frame".as_slice(),
        b"Second grouped frame".as_slice(),
    ] {
        let app = conn.generate_id()?;
        conn.create_window(
            0,
            app,
            root,
            240,
            180,
            320,
            190,
            0,
            WindowClass::INPUT_OUTPUT,
            0,
            &CreateWindowAux::new()
                .background_pixel(0x25a9df)
                .event_mask(EventMask::STRUCTURE_NOTIFY),
        )?;
        conn.change_property8(
            PropMode::REPLACE,
            app,
            AtomEnum::WM_NAME,
            AtomEnum::STRING,
            title,
        )?;
        conn.change_property32(
            PropMode::REPLACE,
            app,
            atom(&conn, "_NET_WM_WINDOW_TYPE")?,
            AtomEnum::ATOM,
            &[atom(&conn, "_NET_WM_WINDOW_TYPE_DIALOG")?],
        )?;
        conn.map_window(app)?;
        conn.flush()?;
        wait("grouped app published with logical ID", || {
            property(&conn, root, "_NET_CLIENT_LIST")
                .unwrap_or_default()
                .contains(&app)
        });
        let frame = conn.query_tree(app)?.reply()?.parent;
        assert_ne!(
            frame, root,
            "native chrome and app must share one root frame surface"
        );
        assert_eq!(conn.query_tree(frame)?.reply()?.parent, root);
        let chrome = native_chrome(&conn, root, app).expect("seeded native chrome child");
        assert_eq!(conn.query_tree(chrome)?.reply()?.parent, frame);
        assert_ne!(chrome, frame);
        assert_eq!(root_surface(&conn, app), frame);
        assert_eq!(root_surface(&conn, chrome), frame);
        let mut observed_frame_map = false;
        wait("first observed frame map includes painted chrome", || {
            while let Some(event) = conn.poll_for_event().unwrap() {
                if let x11rb::protocol::Event::MapNotify(event) = event {
                    if event.window == frame {
                        // Check on the first observed root publication. This is
                        // server state/pixels, not proof of physical presentation.
                        assert_eq!(
                            conn.get_window_attributes(chrome)
                                .unwrap()
                                .reply()
                                .unwrap()
                                .map_state,
                            MapState::VIEWABLE,
                            "frame published before its chrome mapped"
                        );
                        let g = conn.get_geometry(chrome).unwrap().reply().unwrap();
                        let image = conn
                            .get_image(
                                ImageFormat::Z_PIXMAP,
                                chrome,
                                0,
                                0,
                                g.width.min(160),
                                g.height.min(20),
                                u32::MAX,
                            )
                            .unwrap()
                            .reply()
                            .unwrap();
                        assert!(
                            image.data.iter().any(|byte| *byte != 0),
                            "native title pixels were not seeded at observed frame publication"
                        );
                        observed_frame_map = true;
                    }
                }
            }
            observed_frame_map
        });
        let list = property(&conn, root, "_NET_CLIENT_LIST")?;
        assert!(!list.contains(&frame) && !list.contains(&chrome));
        assert_eq!(property(&conn, app, "WM_STATE")?.first(), Some(&1));
        assert!(property(&conn, frame, "WM_STATE")?.is_empty());
        apps.push(app);
    }
    let first = apps[0];
    let second = apps[1];
    let first_frame = conn.query_tree(first)?.reply()?.parent;
    let second_frame = conn.query_tree(second)?.reply()?.parent;
    message(&conn, root, first, "_NET_ACTIVE_WINDOW", [1, 0, 0, 0, 0])?;
    wait("focus retains logical app identity", || {
        conn.get_input_focus().unwrap().reply().unwrap().focus == first
            && property(&conn, root, "_NET_ACTIVE_WINDOW").unwrap_or_default() == vec![first]
    });
    while conn.poll_for_event()?.is_some() {}
    conn.configure_window(
        first,
        &ConfigureWindowAux::new()
            .x(420)
            .y(260)
            .width(360)
            .height(210),
    )?;
    conn.flush()?;
    let mut synthetic = None;
    wait(
        "child ConfigureRequest yields root-relative synthetic geometry",
        || {
            while let Some(event) = conn.poll_for_event().unwrap() {
                if let x11rb::protocol::Event::ConfigureNotify(event) = event {
                    if event.window == first && event.response_type & 0x80 != 0 {
                        synthetic = Some(event);
                    }
                }
            }
            if let Some(event) = synthetic {
                let actual = geometry(&conn, first);
                event.width == 360
                    && actual.width == 360
                    && event.height == actual.height
                    && event.x == actual.x
                    && event.y == actual.y
                    && (event.x != 0 || event.y > 100)
            } else {
                false
            }
        },
    );
    conn.configure_window(
        first,
        &ConfigureWindowAux::new()
            .sibling(second)
            .stack_mode(StackMode::ABOVE),
    )?;
    conn.flush()?;
    wait("logical sibling request raises common root frame", || {
        let tree = conn.query_tree(root).unwrap().reply().unwrap().children;
        match (
            tree.iter().position(|w| *w == first_frame),
            tree.iter().position(|w| *w == second_frame),
        ) {
            (Some(a), Some(b)) => a > b,
            _ => false,
        }
    });
    let stack = property(&conn, root, "_NET_CLIENT_LIST_STACKING")?;
    assert!(stack.contains(&first) && stack.contains(&second));
    assert!(!stack.contains(&first_frame) && !stack.contains(&second_frame));
    message(&conn, root, first, "WM_CHANGE_STATE", [3, 0, 0, 0, 0])?;
    wait(
        "minimize hides frame without withdrawing mapped child",
        || {
            conn.get_window_attributes(first_frame)
                .unwrap()
                .reply()
                .unwrap()
                .map_state
                == MapState::UNMAPPED
                && not_viewable(&conn, first)
                && property(&conn, first, "WM_STATE")
                    .unwrap_or_default()
                    .first()
                    == Some(&3)
                && property(&conn, root, "_NET_CLIENT_LIST")
                    .unwrap_or_default()
                    .contains(&first)
        },
    );
    xdotool(&["key", "super+shift+q"]);
    wait("framed graceful exit", || {
        wm.0.try_wait().unwrap().is_some()
    });
    for app in &apps {
        assert_eq!(
            conn.query_tree(*app)?.reply()?.parent,
            root,
            "graceful teardown must release the foreign client before frame destruction"
        );
    }
    assert_eq!(
        conn.get_window_attributes(first)?.reply()?.map_state,
        MapState::UNMAPPED
    );
    assert_eq!(property(&conn, first, "WM_STATE")?.first(), Some(&3));
    assert!(conn.get_window_attributes(first_frame)?.reply().is_err());
    wm = start_with_policy(false, false)?;
    wait("graceful restart adopts logical app IDs", || {
        ready(&conn, root, &wm)
            && property(&conn, root, "_NET_CLIENT_LIST")
                .unwrap_or_default()
                .len()
                == 2
    });
    assert!(not_viewable(&conn, first));
    assert_ne!(conn.query_tree(first)?.reply()?.parent, root);
    message(&conn, root, first, "_NET_ACTIVE_WINDOW", [1, 0, 0, 0, 0])?;
    wait("framed minimized client restored after restart", || {
        !not_viewable(&conn, first)
    });
    let crash_frames: Vec<_> = apps
        .iter()
        .map(|app| conn.query_tree(*app).unwrap().reply().unwrap().parent)
        .collect();
    wm.0.kill()?;
    wm.0.wait()?;
    wait(
        "save set releases live clients after abrupt WM death",
        || {
            apps.iter().all(|app| {
                conn.query_tree(*app)
                    .ok()
                    .and_then(|cookie| cookie.reply().ok())
                    .is_some_and(|tree| tree.parent == root)
            })
        },
    );
    for frame in crash_frames {
        assert!(conn.get_window_attributes(frame)?.reply().is_err());
    }
    wm = start_with_policy(false, false)?;
    wait(
        "abrupt restart adopts surviving app IDs without phantom frames",
        || {
            ready(&conn, root, &wm)
                && property(&conn, root, "_NET_CLIENT_LIST")
                    .unwrap_or_default()
                    .len()
                    == 2
                && apps.iter().all(|app| {
                    property(&conn, root, "_NET_CLIENT_LIST")
                        .unwrap_or_default()
                        .contains(app)
                })
        },
    );
    for app in &apps {
        assert_ne!(conn.query_tree(*app)?.reply()?.parent, root);
    }
    conn.unmap_window(first)?;
    conn.flush()?;
    wait(
        "real client withdrawal still removes framed application",
        || {
            !property(&conn, root, "_NET_CLIENT_LIST")
                .unwrap_or_default()
                .contains(&first)
                && property(&conn, first, "WM_STATE")
                    .unwrap_or_default()
                    .is_empty()
        },
    );
    assert_eq!(conn.query_tree(first)?.reply()?.parent, root);
    for app in apps {
        conn.destroy_window(app)?;
    }
    conn.flush()?;
    xdotool(&["key", "super+shift+q"]);
    wait("frame regression exits", || {
        wm.0.try_wait().unwrap().is_some()
    });
    Ok(())
}

#[test]
#[ignore = "requires private Xvfb; run tests/run.sh"]
fn workspace_title_height_relayouts_body_with_unchanged_outer_frame() -> Result<()> {
    assert_eq!(
        std::env::var("CARPATIC_WM_TEST_DISPLAY").as_deref(),
        Ok("1")
    );
    assert!(std::env::var_os("WAYLAND_DISPLAY").is_none());
    let dir = std::path::PathBuf::from(std::env::var("CARPATIC_CONFIG_DIR")?);
    let _config = ConfigRestore::new(&dir);
    std::fs::write(dir.join("themes.toml"), "[appearance]\nworkspaces=4\nborderpx=2\nborder_highlight=0\nouter_gap=12\n[titlebar]\nenabled=1\ntiled=0\nfloating=1\nheight=32\n")?;
    std::fs::write(dir.join("window-rules.toml"), "rules=[]\n")?;
    std::fs::write(dir.join("hotkeys.toml"), "keys=[{mod='SUPER',key='f',func='setlayout',layout_idx=1},{mod='SUPER SHIFT',key='q',func='quit'}]\n")?;
    let (conn, screen) = x11rb::connect(None)?;
    let root = conn.setup().roots[screen].root;
    let mut wm = start_with_policy(false, false)?;
    wait("title-height WM ready", || ready(&conn, root, &wm));
    let layout = || {
        conn.get_property(
            false,
            root,
            atom(&conn, "_CARPATIC_LAYOUT").unwrap(),
            AtomEnum::ANY,
            0,
            16,
        )
        .unwrap()
        .reply()
        .unwrap()
        .value
    };
    message(&conn, root, root, "_NET_CURRENT_DESKTOP", [1, 0, 0, 0, 0])?;
    wait("prepare second workspace", || {
        property(&conn, root, "_NET_CURRENT_DESKTOP").unwrap() == vec![1]
    });
    xdotool(&["key", "super+f"]);
    wait("second workspace float layout prepared", || {
        layout() == b"float"
    });
    message(&conn, root, root, "_NET_CURRENT_DESKTOP", [0, 0, 0, 0, 0])?;
    wait("first workspace tile layout", || layout() == b"tile");
    let id = conn.generate_id()?;
    conn.create_window(
        0,
        id,
        root,
        30,
        40,
        400,
        250,
        0,
        WindowClass::INPUT_OUTPUT,
        0,
        &CreateWindowAux::new(),
    )?;
    conn.change_property8(
        PropMode::REPLACE,
        id,
        AtomEnum::WM_CLASS,
        AtomEnum::STRING,
        b"height-proof\0HeightProof\0",
    )?;
    conn.map_window(id)?;
    conn.flush()?;
    wait("title-height logical client managed", || {
        property(&conn, root, "_NET_CLIENT_LIST")
            .unwrap_or_default()
            .contains(&id)
    });
    wait("title-height metadata ready", || {
        native_chrome(&conn, root, id).is_some()
    });
    let max_h = atom(&conn, "_NET_WM_STATE_MAXIMIZED_HORZ")?;
    let max_v = atom(&conn, "_NET_WM_STATE_MAXIMIZED_VERT")?;
    message(&conn, root, id, "_NET_WM_STATE", [1, max_h, max_v, 0, 0])?;
    wait("title-height client maximized", || {
        let states = property(&conn, id, "_NET_WM_STATE").unwrap_or_default();
        states.contains(&max_h) && states.contains(&max_v)
    });
    assert_eq!(property(&conn, id, "_CARPATIC_MAX_SAVED")?.get(4), Some(&0));
    wait("maximized tiled extents settled", || {
        property(&conn, id, "_NET_FRAME_EXTENTS").unwrap_or_default() == vec![2, 2, 2, 2]
    });
    let frame = root_surface(&conn, id);
    let title = native_chrome(&conn, root, id).unwrap();
    let outer = geometry(&conn, frame);
    let body = conn.get_geometry(id)?.reply()?;
    let root_body = geometry(&conn, id);
    let dimensions = |g: &GetGeometryReply| (g.x, g.y, g.width, g.height, g.border_width);
    assert_eq!(body.y, 0);
    assert!(not_viewable(&conn, title));
    println!("TITLEHEIGHT baseline logical={id:#x} frame={frame:#x} outer={:?} local_body={:?} root_body={:?} extents={:?}", dimensions(&outer), dimensions(&body), dimensions(&root_body), property(&conn, id, "_NET_FRAME_EXTENTS")?);
    message(&conn, root, id, "_NET_WM_DESKTOP", [1, 0, 0, 0, 0])?;
    wait("height client assigned second workspace", || {
        property(&conn, id, "_NET_WM_DESKTOP").unwrap_or_default() == vec![1]
            && not_viewable(&conn, id)
    });
    message(&conn, root, root, "_NET_CURRENT_DESKTOP", [1, 0, 0, 0, 0])?;
    wait("float extents and caption visible", || {
        property(&conn, id, "_NET_FRAME_EXTENTS").unwrap_or_default() == vec![2, 2, 34, 2]
            && conn
                .get_window_attributes(title)
                .unwrap()
                .reply()
                .unwrap()
                .map_state
                == MapState::VIEWABLE
    });
    let changed_outer = geometry(&conn, frame);
    let changed_body = conn.get_geometry(id)?.reply()?;
    let changed_root_body = geometry(&conn, id);
    println!("TITLEHEIGHT float logical={id:#x} frame={:#x} outer={:?} local_body={:?} root_body={:?} extents={:?}", root_surface(&conn, id), dimensions(&changed_outer), dimensions(&changed_body), dimensions(&changed_root_body), property(&conn, id, "_NET_FRAME_EXTENTS")?);
    assert_eq!(root_surface(&conn, id), frame);
    assert_eq!(
        (
            changed_outer.x,
            changed_outer.y,
            changed_outer.width,
            changed_outer.height
        ),
        (outer.x, outer.y, outer.width, outer.height)
    );
    let logical = property(&conn, root, "_NET_CLIENT_LIST")?;
    assert!(logical.contains(&id) && !logical.contains(&frame));
    assert_eq!(
        changed_body.y,
        body.y + 32,
        "title extent must move body inside unchanged frame"
    );
    assert_eq!(changed_body.height, body.height - 32);
    assert_eq!(
        (changed_body.width, changed_body.border_width),
        (body.width, body.border_width)
    );
    assert_eq!(changed_root_body.y, root_body.y + 32);
    message(&conn, root, id, "_NET_WM_DESKTOP", [0, 0, 0, 0, 0])?;
    wait("height client returns first workspace", || {
        property(&conn, id, "_NET_WM_DESKTOP").unwrap_or_default() == vec![0]
            && not_viewable(&conn, id)
    });
    message(&conn, root, root, "_NET_CURRENT_DESKTOP", [0, 0, 0, 0, 0])?;
    wait("tiled body and extents restored", || {
        let g = conn.get_geometry(id).unwrap().reply().unwrap();
        property(&conn, id, "_NET_FRAME_EXTENTS").unwrap_or_default() == vec![2, 2, 2, 2]
            && g.y == body.y
            && g.height == body.height
            && not_viewable(&conn, title)
    });
    let restored_outer = geometry(&conn, frame);
    println!(
        "TITLEHEIGHT restored logical={id:#x} frame={frame:#x} outer={:?} body={:?}",
        dimensions(&restored_outer),
        dimensions(&conn.get_geometry(id)?.reply()?)
    );
    assert_eq!(root_surface(&conn, id), frame);
    assert_eq!(
        (
            restored_outer.x,
            restored_outer.y,
            restored_outer.width,
            restored_outer.height
        ),
        (outer.x, outer.y, outer.width, outer.height)
    );
    assert!(property(&conn, root, "_NET_CLIENT_LIST")?.contains(&id));
    conn.destroy_window(id)?;
    conn.flush()?;
    xdotool(&["key", "super+shift+q"]);
    assert!(wm.0.wait()?.success());
    Ok(())
}
