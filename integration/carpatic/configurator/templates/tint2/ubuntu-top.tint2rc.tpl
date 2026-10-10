# GNOME-style top bar: Activities | ... clock (centre) ... | tray
# 1 panel
rounded = 0
border_width = 0
background_color = {{ mix bar_bg background 0 }} 100
border_color = {{ bar_bg }} 100
# 2 activities button
rounded = 12
border_width = 0
background_color = {{ bar_bg }} 0
border_color = {{ bar_bg }} 0
background_color_hover = {{ hover }} 100
border_color_hover = {{ hover }} 100
background_color_pressed = {{ hover }} 100
border_color_pressed = {{ hover }} 100

panel_items = FCFS
panel_size = 100% 28
panel_margin = 0 0
panel_padding = 4 0 4
panel_background_id = 1
panel_position = top center horizontal
panel_layer = top
panel_monitor = all
panel_window_name = carpatic-bar
strut_policy = follow_size
wm_menu = 1
autohide = 0

systray_padding = 8 3 6
systray_background_id = 0
systray_sort = ascending
systray_icon_size = 18
systray_icon_asb = 100 0 0

time1_format = %a %d %b  %H:%M
time1_font = {{ @HEAD }} Bold {{ @SZ }}
clock_font_color = {{ foreground }} 100
clock_lclick_command = carpatic-flyout calendar
clock_rclick_command = carpatic-flyout quick
clock_tooltip = Power menu
clock_padding = 14 0
clock_background_id = 0
