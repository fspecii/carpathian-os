[global]
    follow = mouse
    width = (0, {{ @NOTIFY_WIDTH }})
    origin = {{ @NOTIFY_POS }}
    offset = ({{ px 12 }}, {{ @NOTIFY_OFFSET_Y }})
    frame_width = {{ px 1 }}
    markup = full
    format = "{{ @NOTIFY_FORMAT }}"
    show_age_threshold = 60
    icon_position = left
    min_icon_size = {{ px 40 }}
    max_icon_size = {{ px 48 }}
    frame_color = "{{ accent }}"
    highlight = "{{ accent }}"
    corner_radius = {{ @NOTIFY_RADIUS }}
    font = {{ @UI }} {{ @SZ }}
    padding = {{ px 10 }}
    horizontal_padding = {{ px 12 }}
    icon_theme = {{ @ICONTHEME }}
    enable_recursive_icon_lookup = true
[urgency_low]
    background = "{{ dark_background }}"
    foreground = "{{ foreground }}"
    timeout = 5
[urgency_normal]
    background = "{{ background }}"
    foreground = "{{ foreground }}"
    timeout = 8
[urgency_critical]
    background = "{{ background }}"
    foreground = "{{ foreground }}"
    frame_color = "{{ red }}"
    timeout = 0
