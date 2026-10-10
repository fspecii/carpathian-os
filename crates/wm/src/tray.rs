//! XEMBED system-tray manager. Icons remain owned by their applications.
use std::error::Error;
use x11rb::{
    connection::Connection, protocol::xproto::*, rust_connection::RustConnection,
    wrapper::ConnectionExt as _, CURRENT_TIME, NONE,
};
type Result<T> = std::result::Result<T, Box<dyn Error>>;

x11rb::atom_manager! {
    pub Atoms:Cookie { _NET_SYSTEM_TRAY_S0, _NET_SYSTEM_TRAY_OPCODE, _NET_SYSTEM_TRAY_ORIENTATION,
        _NET_SYSTEM_TRAY_VISUAL, _XEMBED, _XEMBED_INFO, MANAGER, _CARPATIC_SYSTRAY, }
}

struct Icon {
    id: Window,
    mapped: bool,
}
pub struct Tray {
    pub owner: Window,
    atoms: Atoms,
    icons: Vec<Icon>,
    claimed: bool,
    parent: Window,
}

impl Tray {
    pub fn new(conn: &RustConnection, root: Window) -> Result<Self> {
        let atoms = Atoms::new(conn)?.reply()?;
        let owner = conn.generate_id()?;
        conn.create_window(
            0,
            owner,
            root,
            0,
            0,
            1,
            1,
            0,
            WindowClass::INPUT_OUTPUT,
            0,
            &CreateWindowAux::new()
                .override_redirect(1)
                .event_mask(EventMask::SUBSTRUCTURE_NOTIFY | EventMask::EXPOSURE),
        )?;
        conn.change_property32(
            PropMode::REPLACE,
            owner,
            atoms._NET_SYSTEM_TRAY_ORIENTATION,
            AtomEnum::CARDINAL,
            &[0],
        )?;
        let visual = conn.get_window_attributes(root)?.reply()?.visual;
        conn.change_property32(
            PropMode::REPLACE,
            owner,
            atoms._NET_SYSTEM_TRAY_VISUAL,
            AtomEnum::VISUALID,
            &[visual],
        )?;
        Ok(Self {
            owner,
            atoms,
            icons: Vec::new(),
            claimed: false,
            parent: root,
        })
    }

    pub fn opcode(&self) -> Atom {
        self.atoms._NET_SYSTEM_TRAY_OPCODE
    }
    pub fn info(&self) -> Atom {
        self.atoms._XEMBED_INFO
    }
    pub fn selection(&self) -> Atom {
        self.atoms._NET_SYSTEM_TRAY_S0
    }
    pub fn is_icon(&self, id: Window) -> bool {
        self.icons.iter().any(|i| i.id == id)
    }
    pub fn width(&self, size: u32, gap: u32) -> u32 {
        self.icons.iter().filter(|i| i.mapped).count() as u32 * (size + gap)
    }

    pub fn claim(&mut self, conn: &RustConnection, root: Window) -> Result<()> {
        if self.claimed {
            return Ok(());
        }
        let owner = conn
            .get_selection_owner(self.atoms._NET_SYSTEM_TRAY_S0)?
            .reply()?
            .owner;
        if owner != NONE && owner != self.owner {
            return Ok(());
        }
        conn.set_selection_owner(self.owner, self.atoms._NET_SYSTEM_TRAY_S0, CURRENT_TIME)?;
        self.claimed = conn
            .get_selection_owner(self.atoms._NET_SYSTEM_TRAY_S0)?
            .reply()?
            .owner
            == self.owner;
        if self.claimed {
            conn.send_event(
                false,
                root,
                EventMask::STRUCTURE_NOTIFY,
                ClientMessageEvent::new(
                    32,
                    root,
                    self.atoms.MANAGER,
                    [
                        CURRENT_TIME,
                        self.atoms._NET_SYSTEM_TRAY_S0,
                        self.owner,
                        0,
                        0,
                    ],
                ),
            )?;
        }
        Ok(())
    }

    pub fn dock(&mut self, conn: &RustConnection, id: Window) -> Result<()> {
        if self.is_icon(id) {
            return Ok(());
        }
        conn.get_window_attributes(id)?.reply()?;
        conn.change_save_set(SetMode::INSERT, id)?;
        conn.change_window_attributes(
            id,
            &ChangeWindowAttributesAux::new()
                .event_mask(EventMask::PROPERTY_CHANGE | EventMask::STRUCTURE_NOTIFY),
        )?;
        conn.reparent_window(id, self.owner, 0, 0)?;
        conn.send_event(
            false,
            id,
            EventMask::NO_EVENT,
            ClientMessageEvent::new(
                32,
                id,
                self.atoms._XEMBED,
                [CURRENT_TIME, 0, 0, self.owner, 0],
            ),
        )?;
        self.icons.push(Icon { id, mapped: true });
        self.update_info(conn, id)?;
        Ok(())
    }

    pub fn update_info(&mut self, conn: &RustConnection, id: Window) -> Result<()> {
        let value = conn
            .get_property(
                false,
                id,
                self.atoms._XEMBED_INFO,
                self.atoms._XEMBED_INFO,
                0,
                2,
            )?
            .reply()?;
        if let Some(flags) = value.value32().and_then(|mut values| values.nth(1)) {
            if let Some(icon) = self.icons.iter_mut().find(|i| i.id == id) {
                icon.mapped = flags & 1 != 0;
            }
        }
        Ok(())
    }

    #[allow(clippy::too_many_arguments)]
    pub fn layout(
        &mut self,
        conn: &RustConnection,
        root: Window,
        parent: Window,
        x: i32,
        height: u32,
        size: u32,
        gap: u32,
        bg: u32,
    ) -> Result<()> {
        let width = self.width(size, gap).max(1);
        if self.parent != parent {
            conn.reparent_window(self.owner, parent, 0, 0)?;
            self.parent = parent;
        }
        conn.configure_window(
            self.owner,
            &ConfigureWindowAux::new()
                .x(x)
                .y(0)
                .width(width)
                .height(height),
        )?;
        conn.change_window_attributes(
            self.owner,
            &ChangeWindowAttributesAux::new().background_pixel(bg),
        )?;
        conn.map_window(self.owner)?;
        let mut position = 0;
        for icon in &self.icons {
            if icon.mapped {
                conn.configure_window(
                    icon.id,
                    &ConfigureWindowAux::new()
                        .x(position)
                        .y((height.saturating_sub(size) / 2) as i32)
                        .width(size.max(1))
                        .height(size.max(1))
                        .border_width(0),
                )?;
                conn.map_window(icon.id)?;
                position += (size + gap) as i32;
            } else {
                conn.unmap_window(icon.id)?;
            }
        }
        conn.change_property32(
            PropMode::REPLACE,
            root,
            self.atoms._CARPATIC_SYSTRAY,
            AtomEnum::CARDINAL,
            &[self.owner, self.icons.len() as u32],
        )?;
        Ok(())
    }

    pub fn lost(&mut self) {
        self.claimed = false;
    }
    pub fn detach(&mut self, conn: &RustConnection, root: Window) -> Result<()> {
        conn.reparent_window(self.owner, root, 0, 0)?;
        self.parent = root;
        Ok(())
    }

    pub fn remove(&mut self, id: Window) {
        self.icons.retain(|i| i.id != id);
    }

    pub fn release(&mut self, conn: &RustConnection, root: Window) -> Result<()> {
        if self.claimed {
            conn.set_selection_owner(NONE, self.atoms._NET_SYSTEM_TRAY_S0, CURRENT_TIME)?;
        }
        self.claimed = false;
        for icon in self.icons.drain(..) {
            conn.reparent_window(icon.id, root, 0, 0)?;
            conn.change_save_set(SetMode::DELETE, icon.id)?;
            conn.unmap_window(icon.id)?;
        }
        conn.unmap_window(self.owner)?;
        conn.change_property32(
            PropMode::REPLACE,
            root,
            self.atoms._CARPATIC_SYSTRAY,
            AtomEnum::CARDINAL,
            &[0, 0],
        )?;
        Ok(())
    }
}
