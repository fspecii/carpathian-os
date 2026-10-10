# carpatic-managed starship prompt, coloured from the Carpatic palette ({{ @THEME }})
add_newline = false
palette = "carpatic"
format = "$directory$git_branch$git_status$character"
[palettes.carpatic]
fg = "{{ foreground }}"
accent = "{{ accent }}"
muted = "{{ muted }}"
red = "{{ red }}"
green = "{{ green }}"
yellow = "{{ yellow }}"
blue = "{{ blue }}"
magenta = "{{ magenta }}"
cyan = "{{ cyan }}"
[directory]
style = "bold blue"
truncation_length = 3
[git_branch]
style = "magenta"
format = "[$symbol$branch]($style) "
[git_status]
style = "yellow"
[character]
success_symbol = "[>](bold accent)"
error_symbol = "[>](bold red)"
