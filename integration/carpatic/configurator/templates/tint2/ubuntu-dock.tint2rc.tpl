# GNOME-style left dock: favourites + running apps, vertical. Secondary dock: dwm only reserves its strut.
# 1 panel
rounded = 0
border_width = 1
border_sides = R
background_color = {{ bar_bg }} 100
border_color = {{ border }} 100
# 2 running app: small dot on the left edge
rounded = 0
border_width = 3
border_sides = L
background_color = {{ bar_bg }} 0
border_color = {{ muted }} 100
background_color_hover = {{ hover }} 100
border_color_hover = {{ muted }} 100
# 3 active app: orange (accent) dot + soft plate
rounded = 0
border_width = 3
border_sides = L
background_color = {{ mix bar_bg accent 22 }} 100
border_color = {{ accent }} 100
background_color_hover = {{ mix bar_bg accent 30 }} 100
border_color_hover = {{ accent }} 100

panel_items = LT
panel_size = 100% 56
panel_margin = 0 36
panel_padding = 4 8 6
panel_background_id = 1
panel_position = center left vertical
panel_layer = top
panel_monitor = all
panel_window_name = carpatic-dock-left
strut_policy = follow_size
wm_menu = 1
autohide = 0

launcher_padding = 0 0 8
launcher_background_id = 0
launcher_icon_size = 40
launcher_icon_theme = {{ @ICONTHEME }}
launcher_item_app = {{ @HOME }}/.local/share/applications/carpatic-start.desktop
launcher_item_app = /usr/share/applications/thunar.desktop
launcher_item_app = /usr/local/share/applications/carpatic-terminal.desktop
launcher_item_app = /usr/local/share/applications/carpatic-store.desktop
launcher_item_app = /usr/local/share/applications/carpatic-settings.desktop

taskbar_mode = single_desktop
taskbar_padding = 0 8 8
taskbar_background_id = 0
task_text = 0
task_icon = 1
task_centered = 1
task_maximum_size = 40 44
task_padding = 4 4 4
task_background_id = 2
task_active_background_id = 3
mouse_left = toggle_iconify
mouse_right = close
