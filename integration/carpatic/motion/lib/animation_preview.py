"""A real managed preview window: open, resize, minimise, restore and close."""
def show():
    import gi
    gi.require_version("Gtk", "3.0")
    gi.require_version("Gdk", "3.0")
    from gi.repository import Gtk, Gdk, GLib
    window = Gtk.Window(title="Animation preview")
    window.set_type_hint(Gdk.WindowTypeHint.DIALOG)
    window.set_default_size(480, 320)
    window.set_position(Gtk.WindowPosition.CENTER)
    window.connect("destroy", Gtk.main_quit)
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20)
    box.set_border_width(32)
    title = Gtk.Label(label="A little room to move")
    title.get_style_context().add_class("title")
    box.pack_start(title, True, True, 0)
    note = Gtk.Label(label="Watch this window maximise, snap, minimise, reappear and close.\nYour other windows stay open.")
    note.set_line_wrap(True); note.set_justify(Gtk.Justification.CENTER)
    box.pack_start(note, True, True, 0)
    button = Gtk.Button(label="Play again")
    button.set_halign(Gtk.Align.CENTER)
    box.pack_start(button, False, False, 0)
    window.add(box)
    pending = []
    def monitor_area():
        display = Gdk.Display.get_default()
        monitor = display.get_monitor_at_window(window.get_window()) or display.get_monitor(0)
        return monitor.get_workarea()
    def snap():
        area = monitor_area()
        window.move(area.x + 10, area.y + 42)
        window.resize(max(320, area.width // 2 - 24), max(240, area.height - 90))
    def return_to_center():
        area = monitor_area()
        window.resize(480, 320)
        window.move(area.x + (area.width - 480) // 2, area.y + (area.height - 352) // 2)
    def play(*_):
        for source in pending:
            if GLib.MainContext.default().find_source_by_id(source): GLib.source_remove(source)
        pending.clear()
        actions = [(800, window.maximize), (1900, window.unmaximize),
                   (2700, snap), (3700, return_to_center),
                   (4700, window.iconify), (5800, window.deiconify), (7100, window.destroy)]
        for delay, action in actions:
            def run(action=action):
                action(); return False
            pending.append(GLib.timeout_add(delay, run))
    button.connect("clicked", play)
    window.show_all(); play()
    Gtk.main()
