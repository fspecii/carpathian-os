/* macOS: Spotlight-style centred search bar with results below */
@import "colors.rasi"
* { background-color: transparent; text-color: @fg; font: "{{ @UI }} {{ @SZ_L }}"; }
configuration { show-icons: true; icon-theme: "{{ @ROFI_ICONS }}"; display-drun: "Spotlight"; drun-display-format: "{name}"; }
window { location: north; anchor: north; y-offset: 22%; width: 640px; background-color: @bg-alt; border: 1px; border-color: @border-col; border-radius: 0; }
mainbox { children: [ inputbar, listview ]; padding: 10px; spacing: 6px; }
inputbar { padding: 12px; children: [ prompt, entry ]; spacing: 10px; }
prompt { enabled: false; }
entry { text-color: @fg; placeholder: "Search apps, files, commands"; placeholder-color: @muted; }
entry { font: "{{ @UI }} {{ @SZ_XL }}"; }
listview { lines: 6; scrollbar: false; dynamic: true; }
element { padding: 8px 12px; spacing: 10px; border-radius: 8px; text-color: @fg; }
element-icon { size: 26px; }
element selected { background-color: @accent; text-color: @accent-fg; }
element-text { text-color: inherit; }
