# Zen taskbar (original; look and behaviour inspired by the Zorin Taskbar defaults): 48 px, icon-only tasks, rounded hover tiles,
# a thin accent line under running apps (brighter on the focused one), tray, two-line clock, show-desktop strip on the far right.
# Shared with the other styles: nothing (own template); helper carpatic-taskpreview adds the hover previews.
# 1 panel
rounded = 0
border_width = 1
border_sides = T
background_color = {{ bar_bg }} 100
border_color = {{ border }} 100
# 2 hover tile (start, launchers, tray, clock)
rounded = 10
border_width = 0
background_color = {{ bar_bg }} 0
border_color = {{ bar_bg }} 0
background_color_hover = {{ mix bar_bg foreground 12 }} 100
border_color_hover = {{ bar_bg }} 0
background_color_pressed = {{ mix bar_bg foreground 20 }} 100
border_color_pressed = {{ bar_bg }} 0
# 3 task idle (running, not focused): small line
rounded = 10
border_width = 3
border_sides = B
background_color = {{ bar_bg }} 0
border_color = {{ mix bar_bg foreground 40 }} 100
background_color_hover = {{ mix bar_bg foreground 12 }} 100
border_color_hover = {{ mix bar_bg foreground 55 }} 100
background_color_pressed = {{ mix bar_bg foreground 20 }} 100
border_color_pressed = {{ mix bar_bg foreground 55 }} 100
# 4 task active (focused): accent line, tinted tile
rounded = 10
border_width = 3
border_sides = B
background_color = {{ mix bar_bg accent 22 }} 100
border_color = {{ accent }} 100
background_color_hover = {{ mix bar_bg accent 32 }} 100
border_color_hover = {{ accent }} 100
background_color_pressed = {{ mix bar_bg accent 22 }} 100
border_color_pressed = {{ accent }} 100
# 5 show-desktop strip
rounded = 0
border_width = 1
border_sides = L
background_color = {{ bar_bg }} 0
border_color = {{ border }} 100
background_color_hover = {{ mix bar_bg foreground 14 }} 100
border_color_hover = {{ border }} 100
background_color_pressed = {{ mix bar_bg foreground 22 }} 100
border_color_pressed = {{ border }} 100
# 6 tooltip
rounded = 8
border_width = 1
background_color = {{ dark_background }} 100
border_color = {{ border }} 100

panel_items = LTSCBE
panel_size = 100% 48
panel_margin = 0 0
panel_padding = 8 4 8
panel_background_id = 1
panel_position = bottom center horizontal
panel_layer = top
panel_monitor = all
panel_window_name = carpatic-bar
strut_policy = follow_size
wm_menu = 1
autohide = 0
font_shadow = 0

launcher_padding = 0 0 4
launcher_background_id = 0
launcher_icon_size = 32
launcher_icon_theme = {{ @ICONTHEME }}
launcher_tooltip = 1
launcher_item_app = /usr/local/share/applications/carpatic-start-zen.desktop
launcher_item_app = /usr/share/applications/thunar.desktop
launcher_item_app = /usr/share/applications/firefox.desktop
launcher_item_app = /usr/local/share/applications/carpatic-store.desktop
launcher_item_app = /usr/local/share/applications/carpatic-terminal.desktop
launcher_item_app = /usr/local/share/applications/carpatic-settings.desktop

taskbar_mode = single_desktop
taskbar_padding = 8 0 4
taskbar_background_id = 0
taskbar_active_background_id = 0
task_text = 0
task_icon = 1
task_centered = 1
task_maximum_size = 48 48
task_padding = 4 4 0
task_tooltip = 1
task_background_id = 3
task_active_background_id = 4
task_urgent_background_id = 3
task_iconified_background_id = 3
task_icon_asb = 100 0 0
task_active_icon_asb = 100 0 0
task_iconified_icon_asb = 70 0 0
mouse_left = toggle_iconify
mouse_middle = close
mouse_right = none
mouse_scroll_up = none
mouse_scroll_down = none

systray_padding = 8 4 4
systray_background_id = 0
systray_sort = ascending
systray_icon_size = 20
systray_icon_asb = 100 0 0

time1_format = %H:%M
time1_font = {{ @HEAD }} Bold {{ @SZ }}
time2_format = %d.%m.%Y
time2_font = {{ @HEAD }} {{ @SZ_SM }}
clock_font_color = {{ foreground }} 100
clock_padding = 10 0
clock_background_id = 2
clock_lclick_command = carpatic-sidebar

button = new
button_text =
button_lclick_command = carpatic-showdesktop
button_padding = 4 0 0
button_background_id = 5
button_max_icon_size = 1

# hover previews: an invisible item whose only job is to (re)start carpatic-taskpreview (tint2 has no window previews of its own)
execp = new
execp_command = carpatic-taskpreview --ensure
execp_interval = 5
execp_has_icon = 0
execp_padding = 0 0 0
execp_background_id = 0

tooltip_show_timeout = 0.4
tooltip_hide_timeout = 0.1
tooltip_padding = 8 5
tooltip_background_id = 6
tooltip_font_color = {{ foreground }} 100
tooltip_font = {{ @UI }} {{ @SZ }}
