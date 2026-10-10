# Windows-style taskbar: Start (launcher icon, the tint2 button item is not reliable here) | pinned apps | window list | tray | clock
# 1 panel
rounded = 0
border_width = 1
border_sides = T
background_color = {{ bar_bg }} 100
border_color = {{ border }} 100
# 2 start button
rounded = 0
border_width = 0
background_color = {{ accent }} 100
border_color = {{ accent }} 100
background_color_hover = {{ mix accent foreground 25 }} 100
border_color_hover = {{ accent }} 100
background_color_pressed = {{ mix accent background 25 }} 100
border_color_pressed = {{ accent }} 100
# 3 task normal
rounded = 8
border_width = 1
background_color = {{ hover }} 100
border_color = {{ border }} 100
background_color_hover = {{ mix hover accent 30 }} 100
border_color_hover = {{ border }} 100
background_color_pressed = {{ hover }} 100
border_color_pressed = {{ border }} 100
# 4 task active
rounded = 8
border_width = 0
border_sides = B
background_color = {{ mix bar_bg accent 40 }} 100
border_color = {{ accent }} 100
background_color_hover = {{ mix bar_bg accent 50 }} 100
border_color_hover = {{ accent }} 100
background_color_pressed = {{ mix bar_bg accent 40 }} 100
border_color_pressed = {{ accent }} 100

panel_items = LTSC
panel_size = 100% 48
panel_margin = 0 0
panel_padding = 0 0 6
panel_background_id = 1
panel_position = bottom center horizontal
panel_layer = top
panel_monitor = all
panel_window_name = carpatic-bar
strut_policy = follow_size
wm_menu = 1
autohide = 0
font_shadow = 0

launcher_padding = 8 4 6
launcher_background_id = 0
launcher_icon_size = 30
launcher_icon_theme = {{ @ICONTHEME }}
launcher_item_app = {{ @HOME }}/.local/share/applications/carpatic-start.desktop
launcher_item_app = /usr/local/share/applications/carpatic-terminal.desktop
launcher_item_app = /usr/share/applications/thunar.desktop
launcher_item_app = /usr/local/share/applications/carpatic-settings.desktop
launcher_item_app = /usr/local/share/applications/carpatic-power.desktop

taskbar_mode = single_desktop
taskbar_padding = 4 4 4
taskbar_background_id = 0
taskbar_active_background_id = 0
task_text = 1
task_icon = 1
task_centered = 0
task_maximum_size = 220 36
task_padding = 8 4 6
task_font = {{ @UI }} {{ @SZ }}
task_font_color = {{ foreground }} 100
task_active_font_color = {{ bright_foreground }} 100
task_background_id = 3
task_active_background_id = 4
task_urgent_background_id = 3
task_iconified_background_id = 3
mouse_left = toggle_iconify
mouse_middle = none
mouse_right = close
mouse_scroll_up = none
mouse_scroll_down = none

systray_padding = 6 4 6
systray_background_id = 0
systray_sort = ascending
systray_icon_size = 22
systray_icon_asb = 100 0 0

time1_format = %H:%M
time1_font = {{ @HEAD }} Bold {{ @SZ }}
time2_format = %d.%m.%Y
time2_font = {{ @HEAD }} {{ @SZ_SM }}
clock_font_color = {{ foreground }} 100
clock_lclick_command = carpatic-flyout calendar
clock_rclick_command = carpatic-flyout quick
clock_padding = 12 0
clock_background_id = 0
