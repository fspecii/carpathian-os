# macOS-style menu bar: logo | active app | ... | tray | clock
# 1 panel
rounded = 0
border_width = 1
border_sides = B
background_color = {{ bar_bg }} 92
border_color = {{ border }} 100
# 2 logo button
rounded = 0
border_width = 0
background_color = {{ bar_bg }} 0
border_color = {{ bar_bg }} 0
background_color_hover = {{ hover }} 100
border_color_hover = {{ hover }} 100
background_color_pressed = {{ hover }} 100
border_color_pressed = {{ hover }} 100

panel_items = BPFSC
panel_size = 100% 28
panel_margin = 0 0
panel_padding = 4 0 8
panel_background_id = 1
panel_position = top center horizontal
panel_layer = top
panel_monitor = all
panel_window_name = carpatic-bar
strut_policy = follow_size
wm_menu = 1
autohide = 0

button = new
button_text = Carpathian
button_font = {{ @HEAD }} Bold {{ @SZ }}
button_font_color = {{ foreground }} 100
button_background_id = 2
button_padding = 12 0 0
button_lclick_command = carpatic-launch menu
button_rclick_command = carpatic-settings

execp = new
execp_command = xdotool getactivewindow getwindowname 2>/dev/null | cut -c1-48
execp_interval = 1
execp_continuous = 0
execp_has_icon = 0
execp_centered = 0
execp_font = {{ @HEAD }} Bold {{ @SZ }}
execp_font_color = {{ foreground }} 100
execp_padding = 12 0 0
execp_background_id = 0

systray_padding = 6 3 6
systray_background_id = 0
systray_sort = ascending
systray_icon_size = 18
systray_icon_asb = 100 0 0

time1_format = %a %d %b  %H:%M
time1_font = {{ @HEAD }} {{ @SZ }}
clock_font_color = {{ foreground }} 100
clock_lclick_command = carpatic-flyout calendar
clock_rclick_command = carpatic-flyout quick
clock_tooltip = Power menu
clock_padding = 12 0
clock_background_id = 0
