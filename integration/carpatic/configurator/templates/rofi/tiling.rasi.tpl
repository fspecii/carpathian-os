/* Tiling: dmenu-like bar across the top */
@import "colors.rasi"
* { background-color: transparent; text-color: @fg; font: "{{ @UI }} {{ @SZ_L }}"; }
configuration { show-icons: false; display-drun: "run"; drun-display-format: "{name}"; }
window { location: north; anchor: north; width: 100%; background-color: @bg; border: 0 0 2px 0; border-color: @accent; }
mainbox { orientation: horizontal; children: [ prompt, entry, listview ]; padding: 4px 8px; spacing: 10px; }
prompt { enabled: false; } entry { expand: false; width: 14em; text-color: @fg; }
listview { layout: horizontal; lines: 20; scrollbar: false; fixed-height: true; }
element { padding: 0 8px; text-color: @fg; }
element selected { background-color: @accent; text-color: @accent-fg; }
element-text { text-color: inherit; }
