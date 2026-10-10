# macOS-style dock: centred, rounded, big icons. Secondary dock: dwm only reserves its strut.
# 1 panel
rounded = 14
border_width = 1
border_sides = TBLR
background_color = {{ bar_bg }} 88
border_color = {{ border }} 100
# 2 running app: small dot under the icon
rounded = 0
border_width = 3
border_sides = B
background_color = {{ bar_bg }} 0
border_color = {{ muted }} 100
# 3 active app: accent dot
rounded = 0
border_width = 3
border_sides = B
background_color = {{ bar_bg }} 0
border_color = {{ accent }} 100

panel_items = LT
panel_size = 500 68
panel_margin = 0 8
panel_padding = 10 6 8
panel_background_id = 1
panel_position = bottom center horizontal
panel_layer = top
panel_monitor = all
panel_window_name = carpatic-dock-bottom
strut_policy = follow_size
wm_menu = 1
autohide = 0

launcher_padding = 2 0 10
launcher_background_id = 0
launcher_icon_size = 52
launcher_icon_theme = {{ @ICONTHEME }}
launcher_item_app = /usr/share/applications/thunar.desktop
launcher_item_app = /usr/local/share/applications/carpatic-terminal.desktop
launcher_item_app = /usr/local/share/applications/carpatic-store.desktop
launcher_item_app = /usr/local/share/applications/carpatic-settings.desktop

taskbar_mode = single_desktop
taskbar_padding = 6 0 8
taskbar_background_id = 0
task_text = 0
task_icon = 1
task_centered = 1
task_maximum_size = 56 56
task_padding = 4 4 4
task_background_id = 2
task_active_background_id = 3
mouse_left = toggle_iconify
mouse_right = close
