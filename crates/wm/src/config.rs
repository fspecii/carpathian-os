//! Standalone configuration parsing for Carpathian WM.
//!
//! Built directly on `toml::Value` (toml 0.8) — no serde derives, no other
//! dependencies beyond `std`. It reads the legacy `carpatic-os` file formats:
//!
//! * `[active] theme = "carpatic"` selects one of the nested `[theme.<name>]`
//!   tables. An unknown name is an error. A file with neither `[active]` nor
//!   any `[theme.*]` table (or a legacy flat file with colours at the top
//!   level) falls back to the built-in Carpathian defaults.
//! * `[appearance] borderpx` (or legacy `border_width`) sets the border width.
//! * Colours accept `#RRGGBB`, `RRGGBB`, `0xRRGGBB` and plain integers.
//! * Toggles accept `0`/`1` and `true`/`false` (also `yes`/`no`, `on`/`off`).
//! * Numeric settings are clamped to safe ranges instead of being rejected.
//!
//! Theme table → [`Config`] colour mapping:
//! `selbgcolor`→`background`, `selfgcolor`→`foreground`,
//! `normbgcolor`→`inactive_background`, `normfgcolor`→`inactive_foreground`,
//! `selbordercolor`→`border_active` (focused border / accent),
//! `normbordercolor`→`border_inactive`,
//! `term_color1/2/3`→`red`/`green`/`yellow`.
//!
//! Title bars default to disabled ([`TitlebarConfig::enabled`] is `false`)
//! until a settings file explicitly enables them.

use std::fs;
use std::path::Path;

use toml::Value;

/// Look-and-feel configuration parsed from a `themes.toml` style file.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Config {
    /// Name of the selected theme (`[active] theme`).
    pub theme: String,
    /// Border width in pixels (`[appearance] borderpx` / `border_width`).
    pub border: u32,
    /// Focused window border colour (theme accent unless overridden).
    pub border_active: u32,
    /// Unfocused window border colour.
    pub border_inactive: u32,
    /// Active/selected background (`selbgcolor`).
    pub background: u32,
    /// Active/selected foreground (`selfgcolor`).
    pub foreground: u32,
    /// Inactive background (`normbgcolor`).
    pub inactive_background: u32,
    /// Inactive foreground (`normfgcolor`).
    pub inactive_foreground: u32,
    /// Terminal/UI accent red (`term_color1`).
    pub red: u32,
    /// Terminal/UI accent green (`term_color2`).
    pub green: u32,
    /// Terminal/UI accent yellow (`term_color3`).
    pub yellow: u32,
    /// Pixels between tiled windows.
    pub inner_gap: u32,
    /// Pixels between tiled windows and the screen/bar edge.
    pub outer_gap: u32,
    /// No gaps when a workspace holds a single tiled window.
    pub smart_gaps: bool,
    /// Rounded corner radius in pixels (`corner_radius`).
    pub radius: u32,
    /// Extra border pixels on the focused window (`border_highlight`).
    pub border_highlight: u32,
    /// UI scale in percent (`ui_scale`).
    pub scale: u32,
    /// Default per-tag layout: `"tile"` or `"float"`.
    pub default_layout: String,
    /// Number of workspaces (1–9).
    pub workspaces: u32,
    pub focus_follows_mouse: bool,
    pub fullscreen_spaces: bool,
    /// Optional per-workspace names; shorter than [`Config::workspaces`] is
    /// fine, longer lists are truncated.
    pub workspace_names: Vec<String>,
    /// Fontconfig pattern for the bar and title bars (`bar_font`).
    pub font: String,
    /// Title bar settings.
    pub titlebar: TitlebarConfig,
    pub drag_place: bool,
    pub bar_enabled: bool,
    pub bar_height: u32,
    pub power_button: bool,
    pub tray_enabled: bool,
    pub tray_size: u32,
    pub tray_gap: u32,
}

/// Window title bar settings (`[titlebar]` table).
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct TitlebarConfig {
    /// Master switch; disabled by default until explicitly enabled.
    pub enabled: bool,
    /// Show title bars on tiled windows.
    pub tiled: bool,
    /// Show title bars on floating windows.
    pub floating: bool,
    /// Draw window buttons (minimise/maximise/close).
    pub buttons: bool,
    /// Double-click on the title bar toggles maximise.
    pub dblclick_maximize: bool,
    /// Button look: `windows`, `macos`, `gnome`, `kde`, `minimal`, …
    pub style: String,
    /// Button side: `auto`, `left` or `right`.
    pub side: String,
    /// Which buttons are shown: `all` or `close`.
    pub shown: String,
    /// Optional explicit button order, e.g. `close,min,max`.
    pub order: String,
    /// Title alignment: `auto`, `left` or `center`.
    pub align: String,
    /// Title bar height in pixels (0 = automatic from font height).
    pub height: u32,
    /// Nominal button size in pixels (0 = scales with the bar height).
    pub size: u32,
    /// Pixels between buttons (negative = style default).
    pub gap: i32,
}

impl Default for TitlebarConfig {
    fn default() -> Self {
        Self {
            enabled: false,
            tiled: true,
            floating: true,
            buttons: true,
            dblclick_maximize: true,
            style: "windows".to_string(),
            side: "auto".to_string(),
            shown: "all".to_string(),
            order: String::new(),
            align: "auto".to_string(),
            height: 0,
            size: 0,
            gap: -1,
        }
    }
}

impl Default for Config {
    /// Built-in Carpathian defaults (matching `[theme.carpatic]` in the legacy
    /// `themes.toml`), with title bars disabled until a file enables them.
    fn default() -> Self {
        Self {
            theme: "carpatic".to_string(),
            border: 2,
            border_active: 0x5c_c8_a8,
            border_inactive: 0x3a_44_55,
            background: 0x1d3232,
            foreground: 0xe7_ec_f3,
            inactive_background: 0x17_1c_25,
            inactive_foreground: 0xa3_ae_c0,
            red: 0xf0_70_7a,
            green: 0x7b_d3_89,
            yellow: 0xf2_c2_5a,
            inner_gap: 8,
            outer_gap: 8,
            smart_gaps: false,
            radius: 0,
            border_highlight: 0,
            scale: 100,
            default_layout: "tile".to_string(),
            workspaces: 4,
            focus_follows_mouse: false,
            fullscreen_spaces: true,
            workspace_names: Vec::new(),
            font: "DejaVu Sans Mono:size=11".to_string(),
            titlebar: TitlebarConfig::default(),
            drag_place: false,
            bar_enabled: false,
            bar_height: 32,
            power_button: true,
            tray_enabled: true,
            tray_size: 20,
            tray_gap: 6,
        }
    }
}

// Safe ranges: values outside are clamped, never rejected.
const MAX_BORDER_PX: u32 = 16;
const MAX_BORDER_HIGHLIGHT: u32 = 6;
const MAX_RADIUS: u32 = 40;
const MAX_GAP: u32 = 100;
const MIN_SCALE: u32 = 50;
const MAX_SCALE: u32 = 300;
const MIN_WORKSPACES: u32 = 1;
const MAX_WORKSPACES: u32 = 9;
const MAX_TITLEBAR_HEIGHT: u32 = 100;
const MAX_BUTTON_SIZE: u32 = 64;
const MIN_BUTTON_GAP: i32 = -64;
const MAX_BUTTON_GAP: i32 = 128;

impl Config {
    /// Parse a `themes.toml` style configuration from text.
    pub fn parse(text: &str) -> Result<Self, String> {
        let root: Value = text
            .parse()
            .map_err(|e| format!("config: invalid TOML: {e}"))?;
        let root = root
            .as_table()
            .ok_or_else(|| "config: top level must be a table".to_string())?;

        let mut cfg = Self::default();

        // ---- [active] theme selector --------------------------------------
        let active: Option<String> = match root.get("active") {
            None => None,
            Some(v) => {
                let t = v
                    .as_table()
                    .ok_or_else(|| "config: [active] must be a table".to_string())?;
                match t.get("theme") {
                    Some(Value::String(s)) if !s.trim().is_empty() => Some(s.trim().to_string()),
                    Some(_) => {
                        return Err("config: [active] theme must be a non-empty string".to_string())
                    }
                    None => return Err("config: [active] table is missing `theme`".to_string()),
                }
            }
        };

        // ---- resolve the selected theme colour table -----------------------
        let selected: Option<(String, &toml::value::Table)> = match active.as_deref() {
            Some(name) => {
                let themes = root.get("theme").and_then(Value::as_table).ok_or_else(|| {
                    format!("config: unknown theme \"{name}\": no [theme.*] tables defined")
                })?;
                match themes.get(name).and_then(Value::as_table) {
                    Some(t) => Some((name.to_string(), t)),
                    None => return Err(format!("config: unknown theme \"{name}\"")),
                }
            }
            // No active name: a missing theme map may fall back to the
            // defaults, otherwise prefer `carpatic`, else the first theme.
            None => match root.get("theme") {
                None => root
                    .contains_key("normbgcolor")
                    .then_some(("carpatic".to_string(), root)),
                Some(Value::Table(themes)) => {
                    let name = if themes.contains_key("carpatic") {
                        "carpatic".to_string()
                    } else {
                        match themes.keys().next() {
                            Some(k) => k.clone(),
                            None => return Err("config: [theme] table is empty".to_string()),
                        }
                    };
                    themes
                        .get(&name)
                        .and_then(Value::as_table)
                        .map(|t| (name.clone(), t))
                        .ok_or_else(|| format!("config: [theme].{name} must be a table"))?
                        .into()
                }
                Some(_) => {
                    return Err("config: [theme] must be a table of theme tables".to_string());
                }
            },
        };

        if let Some((name, theme)) = selected {
            cfg.theme = name.to_string();
            apply_theme(&mut cfg, theme)?;
        }

        // ---- [appearance] / legacy flat settings ---------------------------
        let appearance = match root.get("appearance") {
            None => None,
            Some(v) => Some(
                v.as_table()
                    .ok_or_else(|| "config: [appearance] must be a table".to_string())?,
            ),
        };
        let reader = Reader { appearance, root };

        let borderpx = match reader.get_u32("borderpx")? {
            Some(v) => Some(v),
            None => reader.get_u32("border_width")?,
        };
        if let Some(v) = borderpx {
            cfg.border = v.min(MAX_BORDER_PX);
        }
        if let Some(c) = reader.get_color("border_active")? {
            cfg.border_active = c;
        }
        if let Some(c) = reader.get_color("border_inactive")? {
            cfg.border_inactive = c;
        }
        if let Some(v) = reader.get_u32("border_highlight")? {
            cfg.border_highlight = v.min(MAX_BORDER_HIGHLIGHT);
        }
        cfg.drag_place = reader.get_string("drag_tiled")?.as_deref() == Some("place");
        if let Some(v) = reader.get_u32("corner_radius")? {
            cfg.radius = v.min(MAX_RADIUS);
        }
        if let Some(v) = reader.get_u32("inner_gap")? {
            cfg.inner_gap = v.min(MAX_GAP);
        }
        if let Some(v) = reader.get_u32("outer_gap")? {
            cfg.outer_gap = v.min(MAX_GAP);
        }
        if let Some(v) = reader.get_bool("smart_gaps")? {
            cfg.smart_gaps = v;
        }
        if let Some(v) = reader.get_bool("focus_follows_mouse")? {
            cfg.focus_follows_mouse = v;
        }
        if let Some(v) = reader.get_bool("fullscreen_spaces")? {
            cfg.fullscreen_spaces = v;
        }
        if let Some(v) = reader.get_u32("ui_scale")? {
            cfg.scale = v.clamp(MIN_SCALE, MAX_SCALE);
        }
        if let Some(v) = reader.get_string("default_layout")? {
            let v = v.trim().to_ascii_lowercase();
            match v.as_str() {
                "tile" | "float" => cfg.default_layout = v,
                other => {
                    return Err(format!(
                        "config: default_layout \"{other}\" must be \"tile\" or \"float\""
                    ))
                }
            }
        }
        if let Some(v) = reader.get_u32("workspaces")? {
            cfg.workspaces = v.clamp(MIN_WORKSPACES, MAX_WORKSPACES);
        }
        if let Some(mut names) = reader.get_workspace_names()? {
            names.truncate(cfg.workspaces as usize);
            cfg.workspace_names = names;
        }
        if let Some(f) = reader.get_string("bar_font")? {
            if !f.trim().is_empty() {
                cfg.font = f;
            }
        }

        cfg.bar_enabled = root.contains_key("bar") || root.contains_key("tray");
        for (name, bar) in [("bar", true), ("tray", false)] {
            if let Some(table) = root.get(name) {
                let table = table
                    .as_table()
                    .ok_or_else(|| format!("config: [{name}] must be a table"))?;
                if let Some(value) = table.get("enabled") {
                    if bar {
                        cfg.bar_enabled = parse_bool(value)?;
                    } else {
                        cfg.tray_enabled = parse_bool(value)?;
                    }
                }
                if bar {
                    if let Some(value) = table.get("height").and_then(Value::as_integer) {
                        cfg.bar_height = value.clamp(20, 100) as u32;
                    }
                    if let Some(value) = table.get("power_button") {
                        cfg.power_button = parse_bool(value)?;
                    }
                } else {
                    if let Some(value) = table.get("icon_size").and_then(Value::as_integer) {
                        cfg.tray_size = if value <= 0 { 20 } else { value.min(64) as u32 };
                    }
                    if let Some(value) = table.get("gap").and_then(Value::as_integer) {
                        cfg.tray_gap = value.clamp(0, 32) as u32;
                    }
                }
            }
        }
        // ---- [titlebar] ----------------------------------------------------
        match root.get("titlebar") {
            None => {}
            Some(v) => {
                let t = v
                    .as_table()
                    .ok_or_else(|| "config: [titlebar] must be a table".to_string())?;
                cfg.titlebar.apply(t)?;
            }
        }

        cfg.bar_height = (cfg.bar_height * cfg.scale / 100).max(1);
        cfg.tray_size = (cfg.tray_size * cfg.scale / 100).max(1);
        cfg.tray_gap = cfg.tray_gap * cfg.scale / 100;
        Ok(cfg)
    }

    /// Load and parse a configuration file from disk.
    pub fn load(path: &Path) -> Result<Self, String> {
        let text = fs::read_to_string(path)
            .map_err(|e| format!("config: cannot read {}: {e}", path.display()))?;
        Self::parse(&text)
    }
}

impl TitlebarConfig {
    fn apply(&mut self, t: &toml::value::Table) -> Result<(), String> {
        set_bool(t, &mut self.enabled, &["enabled"])?;
        set_bool(t, &mut self.tiled, &["tiled"])?;
        set_bool(t, &mut self.floating, &["floating"])?;
        set_bool(t, &mut self.buttons, &["buttons"])?;
        set_bool(t, &mut self.dblclick_maximize, &["dblclick_maximize"])?;
        set_string(t, &mut self.style, &["button_style", "style"])?;
        set_string(t, &mut self.side, &["button_side", "side"])?;
        set_string(t, &mut self.shown, &["buttons_shown", "shown"])?;
        set_string(t, &mut self.order, &["button_order", "order"])?;
        set_string(t, &mut self.align, &["title_align", "align"])?;
        set_u32(t, &mut self.height, &["height"])?;
        set_u32(t, &mut self.size, &["button_size", "size"])?;
        set_i32(t, &mut self.gap, &["button_gap", "gap"])?;
        self.height = self.height.min(MAX_TITLEBAR_HEIGHT);
        self.size = self.size.min(MAX_BUTTON_SIZE);
        self.gap = self.gap.clamp(MIN_BUTTON_GAP, MAX_BUTTON_GAP);
        Ok(())
    }
}

/// One window rule parsed from a `window-rules.toml` style file.
///
/// Empty `class`/`instance` match anything; `title` is `None` when the rule
/// does not constrain the window title.
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct Rule {
    pub class: String,
    pub instance: String,
    pub title: Option<String>,
    pub floating: bool,
    pub floating_explicit: bool,
    pub terminal: bool,
    pub noswallow: bool,
    pub above: bool,
    /// Target tag 1–9, or 0 to follow the current tag.
    pub tags: u32,
    /// Monitor index, -1 = any monitor.
    pub monitor: i32,
}

/// One key binding parsed from a `hotkeys.toml` style file.
#[derive(Clone, Debug, PartialEq)]
pub struct Binding {
    /// Space-separated modifiers, e.g. `"SUPER SHIFT"` ("" = none).
    pub modifiers: String,
    /// X11 key name, e.g. `"Return"`.
    pub key: String,
    /// Action function name, e.g. `"spawn"`.
    pub func: String,
    /// argv for `spawn` with `[vars]` `$name` references substituted.
    pub exec: Vec<String>,
    /// Optional shell command (also `$name`-substituted).
    pub cmd: Option<String>,
    /// Signed integer argument (`focusstack`, `incgaps`, …).
    pub i: i32,
    /// Unsigned-ish integer argument (`view` uses -1 for "show all").
    pub ui: i64,
    /// Float argument (`setmfact`, `setcfact`).
    pub f: f32,
    /// Layout index for `setlayout`.
    pub layout_idx: usize,
}

#[derive(Clone, Debug)]
pub struct MouseBinding {
    pub context: String,
    pub button: u8,
    pub binding: Binding,
}
pub fn parse_mouse_bindings(text: &str) -> Result<Vec<MouseBinding>, String> {
    let root: Value = text.parse().map_err(|e: toml::de::Error| e.to_string())?;
    let source = root
        .get("buttons")
        .or_else(|| root.get("vars").and_then(|v| v.get("buttons")));
    let Some(source) = source else {
        return Ok(Vec::new());
    };
    let items = source.as_array().ok_or("buttons must be an array")?;
    let mut out = Vec::new();
    for item in items {
        let mut table = item.as_table().ok_or("button must be a table")?.clone();
        let context = table
            .get("click")
            .and_then(Value::as_str)
            .ok_or("button click context required")?
            .to_string();
        let button = table
            .get("button")
            .and_then(Value::as_integer)
            .ok_or("button number required")?;
        if !(1..=5).contains(&button) {
            return Err("button must be 1–5".into());
        }
        table.insert("key".into(), Value::String("mouse".into()));
        let mut document = toml::Table::new();
        document.insert("keys".into(), Value::Array(vec![Value::Table(table)]));
        if let Some(vars) = root.get("vars") {
            document.insert("vars".into(), vars.clone());
        }
        let serialized = toml::to_string(&document).map_err(|e| e.to_string())?;
        let binding = parse_bindings(&serialized)?.remove(0);
        out.push(MouseBinding {
            context,
            button: button as u8,
            binding,
        });
    }
    Ok(out)
}

/// Parse window rules from a `window-rules.toml` style text.
pub fn parse_rules(text: &str) -> Result<Vec<Rule>, String> {
    let root: Value = text
        .parse()
        .map_err(|e| format!("rules: invalid TOML: {e}"))?;
    let root = root
        .as_table()
        .ok_or_else(|| "rules: top level must be a table".to_string())?;
    let list = match root.get("rules") {
        None => return Ok(Vec::new()),
        Some(v) => v
            .as_array()
            .ok_or_else(|| "rules: `rules` must be an array".to_string())?,
    };

    let mut out = Vec::with_capacity(list.len());
    for (idx, item) in list.iter().enumerate() {
        let t = item
            .as_table()
            .ok_or_else(|| format!("rules: rules[{idx}] must be a table"))?;
        let class = string_field(t, "class", idx, String::new())?;
        let instance = string_field(t, "instance", idx, String::new())?;
        let title = match t.get("title") {
            None => None,
            Some(Value::String(s)) => Some(s.clone()),
            Some(_) => return Err(format!("rules: rules[{idx}].title must be a string")),
        };
        let floating = match t.get("isfloating").or_else(|| t.get("float")) {
            None => false,
            Some(v) => parse_bool(v).map_err(|e| format!("rules: rules[{idx}]: {e}"))?,
        };
        let tags = match t.get("tags") {
            None => 0,
            Some(Value::Integer(n)) if *n > 0 => (*n as u32).min((1 << MAX_WORKSPACES) - 1),
            Some(Value::Integer(_)) => 0,
            Some(_) => return Err(format!("rules: rules[{idx}].tags must be an integer")),
        };
        let monitor = match t.get("monitor") {
            None => -1,
            Some(Value::Integer(n)) => i32::try_from(*n).unwrap_or(-1),
            Some(_) => return Err(format!("rules: rules[{idx}].monitor must be an integer")),
        };
        let toggle = |name: &str| {
            t.get(name)
                .map(parse_bool)
                .transpose()
                .map(|value| value.unwrap_or(false))
        };
        out.push(Rule {
            class,
            instance,
            title,
            floating,
            floating_explicit: t.contains_key("isfloating") || t.contains_key("float"),
            terminal: toggle("isterminal")?,
            noswallow: toggle("noswallow")?,
            above: toggle("alwaysontop")?,
            tags,
            monitor,
        });
    }
    Ok(out)
}

/// Parse key bindings from a `hotkeys.toml` style text.
///
/// `[vars]` entries are substituted into `exec` argv entries and `cmd`
/// wherever a `$name` token appears; unknown `$name` tokens are left as-is.
pub fn parse_bindings(text: &str) -> Result<Vec<Binding>, String> {
    let root: Value = text
        .parse()
        .map_err(|e| format!("hotkeys: invalid TOML: {e}"))?;
    let root = root
        .as_table()
        .ok_or_else(|| "hotkeys: top level must be a table".to_string())?;

    let vars: Vec<(String, String)> = match root.get("vars") {
        None => Vec::new(),
        Some(v) => {
            let t = v
                .as_table()
                .ok_or_else(|| "hotkeys: [vars] must be a table".to_string())?;
            let mut out = Vec::with_capacity(t.len());
            for (k, val) in t {
                if ["keys", "tag_keys", "buttons"].contains(&k.as_str()) {
                    continue;
                }
                match val.as_str() {
                    Some(s) => out.push((k.clone(), s.to_string())),
                    None => return Err(format!("hotkeys: [vars].{k} must be a string")),
                }
            }
            out
        }
    };
    let substitute = |s: &str| -> String {
        let mut out = s.to_string();
        for (name, value) in &vars {
            let pattern = format!("${name}");
            if out.contains(&pattern) {
                out = out.replace(&pattern, value);
            }
        }
        out
    };

    let list = match root.get("keys").or_else(|| {
        root.get("vars")
            .and_then(Value::as_table)
            .and_then(|v| v.get("keys"))
    }) {
        None => return Ok(Vec::new()),
        Some(v) => v
            .as_array()
            .ok_or_else(|| "hotkeys: `keys` must be an array".to_string())?,
    };

    let mut out = Vec::with_capacity(list.len());
    for (idx, item) in list.iter().enumerate() {
        let t = item
            .as_table()
            .ok_or_else(|| format!("hotkeys: keys[{idx}] must be a table"))?;
        let modifiers = match t.get("mod").or_else(|| t.get("modifiers")) {
            None => String::new(),
            Some(Value::String(s)) => s.trim().to_string(),
            Some(_) => return Err(format!("hotkeys: keys[{idx}].mod must be a string")),
        };
        let key = match t.get("key") {
            Some(Value::String(s)) if !s.trim().is_empty() => s.trim().to_string(),
            Some(_) => {
                return Err(format!(
                    "hotkeys: keys[{idx}].key must be a non-empty string"
                ))
            }
            None => return Err(format!("hotkeys: keys[{idx}] is missing `key`")),
        };
        let func = match t.get("func") {
            Some(Value::String(s)) if !s.trim().is_empty() => s.trim().to_string(),
            Some(_) => {
                return Err(format!(
                    "hotkeys: keys[{idx}].func must be a non-empty string"
                ));
            }
            None => return Err(format!("hotkeys: keys[{idx}] is missing `func`")),
        };
        let exec = match t.get("exec") {
            None => Vec::new(),
            Some(Value::Array(items)) => {
                let mut v = Vec::with_capacity(items.len());
                for entry in items {
                    match entry.as_str() {
                        Some(s) => v.push(substitute(s)),
                        None => {
                            return Err(format!(
                                "hotkeys: keys[{idx}].exec entries must be strings"
                            ))
                        }
                    }
                }
                v
            }
            Some(_) => {
                return Err(format!(
                    "hotkeys: keys[{idx}].exec must be an array of strings"
                ))
            }
        };
        let cmd = match t.get("cmd") {
            None => None,
            Some(Value::String(s)) => Some(substitute(s)),
            Some(_) => return Err(format!("hotkeys: keys[{idx}].cmd must be a string")),
        };
        let int_arg = |keys: &[&str]| -> Result<i64, String> {
            for k in keys {
                match t.get(*k) {
                    None => continue,
                    Some(Value::Integer(n)) => return Ok(*n),
                    Some(_) => {
                        return Err(format!("hotkeys: keys[{idx}].{} must be an integer", k));
                    }
                }
            }
            Ok(0)
        };
        let i = i32::try_from(int_arg(&["i"])?).unwrap_or(0);
        let ui = int_arg(&["ui"])?;
        let f = match t.get("f") {
            None => 0.0,
            Some(Value::Float(x)) => *x as f32,
            Some(Value::Integer(n)) => *n as f32,
            Some(_) => return Err(format!("hotkeys: keys[{idx}].f must be a number")),
        };
        let layout_idx = match t.get("layout_idx") {
            None => 0,
            Some(Value::Integer(n)) if *n >= 0 => *n as usize,
            Some(_) => {
                return Err(format!(
                    "hotkeys: keys[{idx}].layout_idx must be a non-negative integer"
                ))
            }
        };
        out.push(Binding {
            modifiers,
            key,
            func,
            exec,
            cmd,
            i,
            ui,
            f,
            layout_idx,
        });
    }
    let tags = root.get("tag_keys").or_else(|| {
        root.get("vars")
            .and_then(Value::as_table)
            .and_then(|t| t.get("tag_keys"))
    });
    if let Some(tags) = tags {
        for item in tags
            .as_array()
            .ok_or("hotkeys: tag_keys must be an array")?
        {
            let key = item
                .get("key")
                .and_then(Value::as_str)
                .ok_or("hotkeys: tag key missing key")?;
            let index = item
                .get("tag")
                .and_then(Value::as_integer)
                .ok_or("hotkeys: tag key missing tag")?;
            if !(0..9).contains(&index) {
                return Err("hotkeys: tag index must be 0..8".into());
            }
            for (modifiers, func) in [
                ("SUPER", "view"),
                ("SUPER CTRL", "toggleview"),
                ("SUPER SHIFT", "tag"),
                ("SUPER CTRL SHIFT", "toggletag"),
            ] {
                out.push(Binding {
                    modifiers: modifiers.into(),
                    key: key.into(),
                    func: func.into(),
                    exec: vec![],
                    cmd: None,
                    i: 0,
                    ui: 1 << index,
                    f: 0.0,
                    layout_idx: 0,
                });
            }
        }
    }
    Ok(out)
}

// ---------------------------------------------------------------------------
// internals
// ---------------------------------------------------------------------------

/// Copy theme palette colours into `cfg` (only keys that are present).
fn apply_theme(cfg: &mut Config, t: &toml::value::Table) -> Result<(), String> {
    type ColorSetter = (&'static [&'static str], fn(&mut Config, u32));
    let pairs: [ColorSetter; 9] = [
        (&["selbgcolor"], |c, v| c.background = v),
        (&["selfgcolor"], |c, v| c.foreground = v),
        (&["normbgcolor"], |c, v| c.inactive_background = v),
        (&["normfgcolor"], |c, v| c.inactive_foreground = v),
        (&["selbordercolor"], |c, v| c.border_active = v),
        (&["normbordercolor"], |c, v| c.border_inactive = v),
        (&["term_color1"], |c, v| c.red = v),
        (&["term_color2"], |c, v| c.green = v),
        (&["term_color3"], |c, v| c.yellow = v),
    ];
    for (keys, set) in pairs {
        for key in keys {
            if let Some(v) = t.get(*key) {
                let color =
                    parse_color(v).map_err(|e| format!("config: theme key `{key}`: {e}"))?;
                set(cfg, color);
                break;
            }
        }
    }
    Ok(())
}

/// Reads settings from `[appearance]` when present, else from the root table
/// (legacy flat files).
struct Reader<'a> {
    appearance: Option<&'a toml::value::Table>,
    root: &'a toml::value::Table,
}

impl<'a> Reader<'a> {
    fn get(&self, key: &str) -> Option<&'a Value> {
        self.appearance
            .and_then(|t| t.get(key))
            .or_else(|| self.root.get(key))
    }

    fn get_string(&self, key: &str) -> Result<Option<String>, String> {
        match self.get(key) {
            None => Ok(None),
            Some(Value::String(s)) => Ok(Some(s.clone())),
            Some(_) => Err(format!("config: `{key}` must be a string")),
        }
    }

    fn get_bool(&self, key: &str) -> Result<Option<bool>, String> {
        match self.get(key) {
            None => Ok(None),
            Some(v) => parse_bool(v)
                .map(Some)
                .map_err(|e| format!("config: `{key}`: {e}")),
        }
    }

    fn get_u32(&self, key: &str) -> Result<Option<u32>, String> {
        match self.get(key) {
            None => Ok(None),
            Some(Value::Integer(n)) => Ok(Some(if *n < 0 { 0 } else { *n as u32 })),
            Some(_) => Err(format!("config: `{key}` must be an integer")),
        }
    }

    fn get_color(&self, key: &str) -> Result<Option<u32>, String> {
        match self.get(key) {
            None => Ok(None),
            Some(Value::String(s)) if s.trim().is_empty() => Ok(None),
            Some(v) => parse_color(v)
                .map(Some)
                .map_err(|e| format!("config: `{key}`: {e}")),
        }
    }

    fn get_workspace_names(&self) -> Result<Option<Vec<String>>, String> {
        match self.get("workspace_names") {
            None => Ok(None),
            Some(Value::String(s)) => Ok(Some(
                s.split(',')
                    .map(str::trim)
                    .filter(|part| !part.is_empty())
                    .map(str::to_string)
                    .collect(),
            )),
            Some(Value::Array(items)) => {
                let mut out = Vec::with_capacity(items.len());
                for item in items {
                    match item.as_str() {
                        Some(s) if !s.trim().is_empty() => out.push(s.trim().to_string()),
                        Some(_) => {}
                        None => {
                            return Err(
                                "config: `workspace_names` entries must be strings".to_string()
                            )
                        }
                    }
                }
                Ok(Some(out))
            }
            Some(_) => Err(
                "config: `workspace_names` must be a comma-separated string or an array of strings"
                    .to_string(),
            ),
        }
    }
}

/// Accepts `true`/`false` booleans, `0`/`1` integers and their string forms.
fn parse_bool(v: &Value) -> Result<bool, String> {
    match v {
        Value::Boolean(b) => Ok(*b),
        Value::Integer(0) => Ok(false),
        Value::Integer(1) => Ok(true),
        Value::Integer(other) => Err(format!("expected 0 or 1, got {other}")),
        Value::String(s) => match s.trim().to_ascii_lowercase().as_str() {
            "0" | "false" | "no" | "off" => Ok(false),
            "1" | "true" | "yes" | "on" => Ok(true),
            other => Err(format!("expected 0/1 or true/false, got \"{other}\"")),
        },
        other => Err(format!("expected a boolean toggle, got {other:?}")),
    }
}

/// Accepts `#RRGGBB`, `RRGGBB`, `0xRRGGBB` and plain integers (≤ 0xFFFFFF).
fn parse_color(v: &Value) -> Result<u32, String> {
    match v {
        Value::Integer(n) if (0..=0xff_ffff).contains(n) => Ok(*n as u32),
        Value::Integer(n) => Err(format!("colour integer {n} out of range 0..0xFFFFFF")),
        Value::String(s) => parse_color_str(s),
        other => Err(format!("expected a colour, got {other:?}")),
    }
}

fn parse_color_str(s: &str) -> Result<u32, String> {
    let trimmed = s.trim();
    let hex = trimmed
        .strip_prefix('#')
        .or_else(|| trimmed.strip_prefix("0x"))
        .or_else(|| trimmed.strip_prefix("0X"))
        .unwrap_or(trimmed);
    if hex.len() != 6 || !hex.bytes().all(|b| b.is_ascii_hexdigit()) {
        return Err(format!("invalid colour \"{s}\" (expected #RRGGBB)"));
    }
    u32::from_str_radix(hex, 16)
        .ok()
        .filter(|c| *c <= 0xff_ffff)
        .ok_or_else(|| format!("invalid colour \"{s}\" (expected #RRGGBB)"))
}

fn set_bool(t: &toml::value::Table, dst: &mut bool, keys: &[&str]) -> Result<(), String> {
    for key in keys {
        if let Some(v) = t.get(*key) {
            *dst = parse_bool(v).map_err(|e| format!("config: [titlebar] `{key}`: {e}"))?;
            return Ok(());
        }
    }
    Ok(())
}

fn set_string(t: &toml::value::Table, dst: &mut String, keys: &[&str]) -> Result<(), String> {
    for key in keys {
        if let Some(v) = t.get(*key) {
            match v {
                Value::String(s) => {
                    *dst = s.clone();
                    return Ok(());
                }
                other => {
                    return Err(format!(
                        "config: [titlebar] `{key}` must be a string, got {other:?}"
                    ))
                }
            }
        }
    }
    Ok(())
}

fn set_u32(t: &toml::value::Table, dst: &mut u32, keys: &[&str]) -> Result<(), String> {
    for key in keys {
        if let Some(v) = t.get(*key) {
            match v {
                Value::Integer(n) => {
                    *dst = if *n < 0 { 0 } else { *n as u32 };
                    return Ok(());
                }
                other => {
                    return Err(format!(
                        "config: [titlebar] `{key}` must be an integer, got {other:?}"
                    ))
                }
            }
        }
    }
    Ok(())
}

fn set_i32(t: &toml::value::Table, dst: &mut i32, keys: &[&str]) -> Result<(), String> {
    for key in keys {
        if let Some(v) = t.get(*key) {
            match v {
                Value::Integer(n) => {
                    *dst = i32::try_from(*n).unwrap_or(if *n > 0 { i32::MAX } else { i32::MIN });
                    return Ok(());
                }
                other => {
                    return Err(format!(
                        "config: [titlebar] `{key}` must be an integer, got {other:?}"
                    ))
                }
            }
        }
    }
    Ok(())
}

fn string_field(
    t: &toml::value::Table,
    key: &str,
    idx: usize,
    default: String,
) -> Result<String, String> {
    match t.get(key) {
        None => Ok(default),
        Some(Value::String(s)) => Ok(s.clone()),
        Some(_) => Err(format!("rules: rules[{idx}].{key} must be a string")),
    }
}

// ---------------------------------------------------------------------------
// tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;
    use std::env;

    /// Carpathian subset of the legacy `themes.toml` (exact colours).
    const CARPATIC: &str = r##"
[active]
theme = "carpatic"

[appearance]
borderpx = 2
inner_gap = 8
outer_gap = 8

[theme.carpatic]
normfgcolor     = "#a3aec0"
normbgcolor     = "#171c25"
normbordercolor = "#3a4455"
selfgcolor      = "#e7ecf3"
selbgcolor      = "#1d3232"
selbordercolor  = "#5cc8a8"
term_color1     = "#f0707a"
term_color2     = "#7bd389"
term_color3     = "#f2c25a"
"##;

    #[test]
    fn defaults_match_carpatic_theme() {
        let cfg = Config::default();
        assert_eq!(cfg.theme, "carpatic");
        assert_eq!(cfg.border, 2);
        assert_eq!(cfg.border_active, 0x5cc8a8);
        assert_eq!(cfg.border_inactive, 0x3a4455);
        assert_eq!(cfg.background, 0x1d3232);
        assert_eq!(cfg.foreground, 0xe7ecf3);
        assert_eq!(cfg.inactive_background, 0x171c25);
        assert_eq!(cfg.inactive_foreground, 0xa3aec0);
        assert_eq!(cfg.red, 0xf0707a);
        assert_eq!(cfg.green, 0x7bd389);
        assert_eq!(cfg.yellow, 0xf2c25a);
        assert_eq!(cfg.inner_gap, 8);
        assert_eq!(cfg.outer_gap, 8);
        assert!(!cfg.smart_gaps);
        assert_eq!(cfg.radius, 0);
        assert_eq!(cfg.border_highlight, 0);
        assert_eq!(cfg.scale, 100);
        assert_eq!(cfg.default_layout, "tile");
        assert_eq!(cfg.workspaces, 4);
        assert!(cfg.workspace_names.is_empty());
        // Title bars stay disabled until a settings file enables them.
        assert!(!cfg.titlebar.enabled);
        assert!(cfg.titlebar.tiled);
        assert!(cfg.titlebar.floating);
        assert!(cfg.titlebar.buttons);
        assert!(cfg.titlebar.dblclick_maximize);
        assert_eq!(cfg.titlebar.style, "windows");
        assert_eq!(cfg.titlebar.gap, -1);
    }

    #[test]
    fn empty_config_parses_to_defaults() {
        assert_eq!(Config::parse("").unwrap(), Config::default());
    }

    #[test]
    fn active_theme_selects_nested_table() {
        let cfg = Config::parse(CARPATIC).unwrap();
        assert_eq!(cfg.theme, "carpatic");
        assert_eq!(cfg.border, 2);
        assert_eq!(cfg.inner_gap, 8);
        assert_eq!(cfg.outer_gap, 8);
        assert_eq!(cfg.background, 0x1d3232);
        assert_eq!(cfg.foreground, 0xe7ecf3);
        assert_eq!(cfg.inactive_background, 0x171c25);
        assert_eq!(cfg.inactive_foreground, 0xa3aec0);
        assert_eq!(cfg.border_active, 0x5cc8a8);
        assert_eq!(cfg.border_inactive, 0x3a4455);
        assert_eq!(cfg.red, 0xf0707a);
        assert_eq!(cfg.green, 0x7bd389);
        assert_eq!(cfg.yellow, 0xf2c25a);
        assert!(!cfg.titlebar.enabled);
    }

    #[test]
    fn unknown_theme_is_an_error() {
        let text = "[active]\ntheme = \"solarized\"\n\n[theme.nord]\nnormbgcolor = \"#434C5E\"\n";
        let err = Config::parse(text).unwrap_err();
        assert!(err.contains("unknown theme"), "got: {err}");
        assert!(err.contains("solarized"));
    }

    #[test]
    fn active_without_theme_map_is_an_error() {
        let err = Config::parse("[active]\ntheme = \"carpatic\"\n").unwrap_err();
        assert!(err.contains("unknown theme"), "got: {err}");
    }

    #[test]
    fn missing_theme_map_defaults_only_without_active_name() {
        let cfg = Config::parse("[appearance]\nborderpx = 3\n").unwrap();
        assert_eq!(
            cfg,
            Config {
                border: 3,
                ..Config::default()
            }
        );
    }

    #[test]
    fn no_active_selector_prefers_carpatic_then_first_theme() {
        let nord = "[theme.nord]\nselbordercolor = \"#81A1C1\"\n";
        let both = "[theme.zeta]\nselbordercolor = \"#111111\"\n\n[theme.carpatic]\nselbordercolor = \"#5cc8a8\"\n";
        assert_eq!(Config::parse(nord).unwrap().theme, "nord");
        assert_eq!(Config::parse(nord).unwrap().border_active, 0x81a1c1);
        assert_eq!(Config::parse(both).unwrap().theme, "carpatic");
    }

    #[test]
    fn legacy_flat_root_colours_are_supported() {
        let text =
            "normbgcolor = \"#101010\"\nselbordercolor = 0x00ff00\nterm_color3 = \"#f2c25a\"\n";
        let cfg = Config::parse(text).unwrap();
        assert_eq!(cfg.inactive_background, 0x101010);
        assert_eq!(cfg.border_active, 0x00ff00);
        assert_eq!(cfg.yellow, 0xf2c25a);
    }

    #[test]
    fn colour_formats_are_accepted() {
        let make = |v: &str| format!("[appearance]\nborder_active = {v}\nborder_inactive = {v}\n");
        for v in ["\"#5CC8A8\"", "\"5cc8a8\"", "\"0x5cc8a8\"", "6080680"] {
            let cfg = Config::parse(&make(v)).unwrap();
            assert_eq!(cfg.border_active, 0x5cc8a8, "v = {v}");
            assert_eq!(cfg.border_inactive, 0x5cc8a8, "v = {v}");
        }
        let err = Config::parse("[appearance]\nborder_active = \"#12gz45\"\n").unwrap_err();
        assert!(err.contains("invalid colour"), "got: {err}");
        let err = Config::parse("[appearance]\nborder_active = 999999999\n").unwrap_err();
        assert!(err.contains("out of range"), "got: {err}");
    }

    #[test]
    fn borderpx_wins_over_border_width() {
        let both = Config::parse("[appearance]\nborderpx = 2\nborder_width = 5\n").unwrap();
        assert_eq!(both.border, 2);
        let legacy = Config::parse("[appearance]\nborder_width = 5\n").unwrap();
        assert_eq!(legacy.border, 5);
    }

    #[test]
    fn appearance_overrides_theme_and_defaults() {
        let text = r##"
[active]
theme = "carpatic"

[appearance]
border_active = "#81A1C1"
smart_gaps = 1
default_layout = "float"
ui_scale = 125
workspaces = 6
workspace_names = "Main, Web, Dev"
bar_font = "Inter:size=10"

[theme.carpatic]
selbordercolor = "#5cc8a8"
"##;
        let cfg = Config::parse(text).unwrap();
        // Appearance overrides the theme accent.
        assert_eq!(cfg.border_active, 0x81a1c1);
        assert!(cfg.smart_gaps);
        assert_eq!(cfg.default_layout, "float");
        assert_eq!(cfg.scale, 125);
        assert_eq!(cfg.workspaces, 6);
        assert_eq!(cfg.workspace_names, vec!["Main", "Web", "Dev"]);
        assert_eq!(cfg.font, "Inter:size=10");
    }

    #[test]
    fn numeric_settings_are_clamped() {
        let text = r##"
[appearance]
borderpx = 999
border_highlight = 10
corner_radius = 99
inner_gap = 500
outer_gap = -7
ui_scale = 1000
workspaces = 99
"##;
        let cfg = Config::parse(text).unwrap();
        assert_eq!(cfg.border, 16);
        assert_eq!(cfg.border_highlight, 6);
        assert_eq!(cfg.radius, 40);
        assert_eq!(cfg.inner_gap, 100);
        assert_eq!(cfg.outer_gap, 0);
        assert_eq!(cfg.scale, 300);
        assert_eq!(cfg.workspaces, 9);
    }

    #[test]
    fn scale_clamps_to_minimum() {
        let cfg = Config::parse("[appearance]\nui_scale = 10\n").unwrap();
        assert_eq!(cfg.scale, 50);
    }

    #[test]
    fn malformed_configs_are_errors() {
        assert!(Config::parse("no = [")
            .unwrap_err()
            .contains("invalid TOML"));
        assert!(Config::parse("[appearance]\nborderpx = \"wide\"\n")
            .unwrap_err()
            .contains("borderpx"));
        assert!(Config::parse("[appearance]\nsmart_gaps = 2\n")
            .unwrap_err()
            .contains("0 or 1"));
        assert!(Config::parse("[appearance]\nsmart_gaps = \"maybe\"\n")
            .unwrap_err()
            .contains("true/false"));
        assert!(
            Config::parse("[appearance]\ndefault_layout = \"diagonal\"\n")
                .unwrap_err()
                .contains("tile")
        );
        assert!(Config::parse("[active]\n")
            .unwrap_err()
            .contains("missing `theme`"));
        assert!(Config::parse("[theme]\nbroken = 1\n")
            .unwrap_err()
            .contains("[theme]"));
    }

    #[test]
    fn default_layout_is_normalised() {
        let cfg = Config::parse("[appearance]\ndefault_layout = \" FLOAT \"\n").unwrap();
        assert_eq!(cfg.default_layout, "float");
    }

    #[test]
    fn toggle_forms_are_equivalent() {
        for v in ["1", "true", "\"yes\"", "\"on\""] {
            let cfg = Config::parse(&format!("[appearance]\nsmart_gaps = {v}\n")).unwrap();
            assert!(cfg.smart_gaps, "v = {v}");
        }
        for v in ["0", "false", "\"no\"", "\"off\""] {
            let cfg = Config::parse(&format!("[appearance]\nsmart_gaps = {v}\n")).unwrap();
            assert!(!cfg.smart_gaps, "v = {v}");
        }
    }

    #[test]
    fn titlebar_table_is_parsed_and_clamped() {
        let text = r##"
[titlebar]
enabled = 1
tiled = 0
floating = true
buttons = 0
dblclick_maximize = 1
button_style = "macos"
button_side = "left"
buttons_shown = "close"
title_align = "center"
height = 24
button_size = 999
button_gap = 4
"##;
        let cfg = Config::parse(text).unwrap();
        let tb = &cfg.titlebar;
        assert!(tb.enabled);
        assert!(!tb.tiled);
        assert!(tb.floating);
        assert!(!tb.buttons);
        assert!(tb.dblclick_maximize);
        assert_eq!(tb.style, "macos");
        assert_eq!(tb.side, "left");
        assert_eq!(tb.shown, "close");
        assert_eq!(tb.align, "center");
        assert_eq!(tb.height, 24);
        assert_eq!(tb.size, 64); // clamped from 999
        assert_eq!(tb.gap, 4);
        let negative = Config::parse("[titlebar]\nbutton_gap = -999\n").unwrap();
        assert_eq!(negative.titlebar.gap, -64);
    }

    #[test]
    fn workspace_names_accept_arrays_and_truncate() {
        let text = "[appearance]\nworkspaces = 2\nworkspace_names = [\"a\", \"b\", \"c\"]\n";
        let cfg = Config::parse(text).unwrap();
        assert_eq!(cfg.workspace_names, vec!["a", "b"]);
        let empty = Config::parse("[appearance]\nworkspace_names = \" , ,\"\n").unwrap();
        assert!(empty.workspace_names.is_empty());
    }

    #[test]
    fn load_reads_file_and_reports_missing() {
        let path =
            env::temp_dir().join(format!("carpatic-config-test-{}.toml", std::process::id()));
        fs::write(&path, CARPATIC).unwrap();
        let cfg = Config::load(&path).unwrap();
        assert_eq!(cfg.background, 0x1d3232);
        let _ = fs::remove_file(&path);

        let err = Config::load(Path::new("/nonexistent/carpatic/themes.toml")).unwrap_err();
        assert!(err.contains("cannot read"), "got: {err}");
    }

    #[test]
    fn rules_parse_full_and_minimal_entries() {
        let text = r##"
rules = [
  { class="St", instance="st", title="Event Tester", isfloating=1, tags=3, monitor=1 },
  { title="dwm launcher", float=true },
  { class="Gimp", tags=8, monitor=-1 },
  { class="Firefox", tags=99 },
]
"##;
        let rules = parse_rules(text).unwrap();
        assert_eq!(rules.len(), 4);
        assert_eq!(
            rules[0],
            Rule {
                class: "St".into(),
                instance: "st".into(),
                title: Some("Event Tester".into()),
                floating: true,
                tags: 3,
                monitor: 1,
                floating_explicit: true,
                ..Rule::default()
            }
        );
        // Missing fields fall back to match-anything defaults.
        assert_eq!(rules[1].class, "");
        assert_eq!(rules[1].instance, "");
        assert_eq!(rules[1].title.as_deref(), Some("dwm launcher"));
        assert!(rules[1].floating);
        assert_eq!(rules[1].tags, 0);
        assert_eq!(rules[1].monitor, -1);
        assert!(!rules[2].floating);
        assert_eq!(rules[2].monitor, -1);
        // tags clamp into the 0..=9 range.
        assert_eq!(rules[3].tags, 99);
        // Legacy window-rules.toml has no `rules` key in overlays; empty is ok.
        assert!(parse_rules("").unwrap().is_empty());
    }

    #[test]
    fn rules_malformed_entries_are_errors() {
        assert!(parse_rules("rules = [1]\n")
            .unwrap_err()
            .contains("must be a table"));
        assert!(parse_rules("rules = [{class=3}]\n")
            .unwrap_err()
            .contains("class"));
        assert!(parse_rules("rules = [{isfloating=\"maybe\"}]\n")
            .unwrap_err()
            .contains("expected"));
        assert!(parse_rules("rules = 5\n").unwrap_err().contains("array"));
    }

    #[test]
    fn bindings_parse_with_vars_substitution() {
        let text = r##"
[vars]
terminal = "st"
webapp   = "webapp-launch"

keys = [
  { mod="SUPER SHIFT", key="Return", desc="Terminal", func="spawn", exec=["$terminal"] },
  { mod="", key="XF86AudioRaiseVolume", func="spawn", exec=["carpatic-volume", "up"] },
  { mod="SUPER", key="h", func="setmfact", f=-0.05 },
  { mod="SUPER", key="j", func="focusstack", i=1 },
  { mod="SUPER", key="0", func="view", ui=-1 },
  { mod="SUPER", key="t", func="setlayout", layout_idx=0 },
  { mod="SUPER SHIFT", key="d", func="spawn", cmd="$terminal -e $webapp" },
]
"##;
        let keys = parse_bindings(text).unwrap();
        assert_eq!(keys.len(), 7);
        assert_eq!(keys[0].modifiers, "SUPER SHIFT");
        assert_eq!(keys[0].key, "Return");
        assert_eq!(keys[0].func, "spawn");
        assert_eq!(keys[0].exec, vec!["st"]);
        assert_eq!(keys[1].modifiers, "");
        assert_eq!(keys[1].exec, vec!["carpatic-volume", "up"]);
        assert_eq!(keys[2].i, 0);
        assert!((keys[2].f - -0.05).abs() < f32::EPSILON);
        assert_eq!(keys[3].i, 1);
        assert_eq!(keys[3].f, 0.0);
        assert_eq!(keys[4].ui, -1);
        assert_eq!(keys[5].layout_idx, 0);
        assert_eq!(keys[6].cmd.as_deref(), Some("st -e webapp-launch"));
        // Unknown $vars are left untouched for the shell to resolve.
        let unknown =
            parse_bindings("keys = [{ mod=\"\", key=\"x\", func=\"spawn\", exec=[\"$nope\"] }]\n")
                .unwrap();
        assert_eq!(unknown[0].exec, vec!["$nope"]);
        // No `keys` array at all is valid (empty binding set).
        assert!(parse_bindings("[vars]\nterminal = \"st\"\n")
            .unwrap()
            .is_empty());
    }

    #[test]
    fn bindings_malformed_entries_are_errors() {
        let missing_key = "keys = [{ mod=\"SUPER\", func=\"spawn\", exec=[\"x\"] }]\n";
        assert!(parse_bindings(missing_key)
            .unwrap_err()
            .contains("missing `key`"));
        let missing_func = "keys = [{ mod=\"SUPER\", key=\"x\" }]\n";
        assert!(parse_bindings(missing_func)
            .unwrap_err()
            .contains("missing `func`"));
        let bad_exec = "keys = [{ key=\"x\", func=\"spawn\", exec=[1] }]\n";
        assert!(parse_bindings(bad_exec).unwrap_err().contains("exec"));
        let bad_i = "keys = [{ key=\"x\", func=\"spawn\", i=\"1\" }]\n";
        assert!(parse_bindings(bad_i).unwrap_err().contains("integer"));
        let bad_layout = "keys = [{ key=\"x\", func=\"setlayout\", layout_idx=-1 }]\n";
        assert!(parse_bindings(bad_layout)
            .unwrap_err()
            .contains("layout_idx"));
        let not_tables = "keys = [\"SUPER-x\"]\n";
        assert!(parse_bindings(not_tables)
            .unwrap_err()
            .contains("must be a table"));
        let bad_vars = "[vars]\nterminal = 1\nkeys = []\n";
        assert!(parse_bindings(bad_vars).unwrap_err().contains("[vars]"));
        assert!(parse_bindings("keys = 1\n").unwrap_err().contains("array"));
    }

    #[test]
    fn bindings_accept_integer_f_and_mod_alias() {
        let text = "keys = [{ modifiers=\"SUPER\", key=\"o\", func=\"setcfact\", f=0 }]\n";
        let keys = parse_bindings(text).unwrap();
        assert_eq!(keys[0].modifiers, "SUPER");
        assert_eq!(keys[0].f, 0.0);
    }
}

#[cfg(test)]
mod mouse_tests {
    use super::*;
    #[test]
    fn legacy_buttons_keep_actions_and_arguments() {
        let bindings=parse_mouse_bindings("buttons=[{click='ClkTagBar',mod='SUPER',button=3,func='toggletag',ui=4},{click='ClkClientWin',mod='ALT',button=1,func='moveorplace'}]").unwrap();
        assert_eq!(bindings.len(), 2);
        assert_eq!(bindings[0].context, "ClkTagBar");
        assert_eq!(bindings[0].binding.ui, 4);
        assert_eq!(bindings[1].binding.modifiers, "ALT");
        assert!(
            parse_mouse_bindings("buttons=[{click='ClkRootWin',button=7,func='quit'}]").is_err()
        );
    }
    #[test]
    fn copied_legacy_mouse_bindings_parse() {
        let text = include_str!("../../../config/hotkeys.toml");
        let bindings = parse_mouse_bindings(text).unwrap();
        assert_eq!(bindings.len(), 6);
        assert_eq!(bindings[2].binding.func, "moveorplace");
    }
}
