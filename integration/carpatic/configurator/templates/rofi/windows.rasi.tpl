/* Windows: start-menu popup anchored bottom-left above the taskbar */
@import "colors.rasi"
* { background-color: transparent; text-color: @fg; font: "{{ @UI }} {{ @SZ_L }}"; }
configuration { show-icons: true; icon-theme: "{{ @ROFI_ICONS }}"; display-drun: "Search"; drun-display-format: "{name}"; }
window { location: southwest; anchor: southwest; y-offset: -{{ @BAR_BOTTOM }}px; width: 440px; height: 560px; background-color: @bg; border: 1px; border-color: @border-col; }
mainbox { children: [ listview, inputbar ]; padding: 8px; spacing: 8px; }
inputbar { padding: 10px; background-color: @bg-alt; border: 0 0 2px 0; border-color: @accent; children: [ prompt, entry ]; spacing: 8px; }
prompt { enabled: false; } entry { text-color: @fg; placeholder: "Search apps, files, commands"; placeholder-color: @muted; }
listview { lines: 10; scrollbar: false; fixed-height: true; }
element { padding: 8px; spacing: 10px; text-color: @fg; background-color: transparent; }
element-icon { size: 28px; }
element selected { background-color: @accent; text-color: @accent-fg; }
element-text { text-color: inherit; }
