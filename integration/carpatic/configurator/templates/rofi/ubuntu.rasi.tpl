/* Ubuntu: Activities-style fullscreen app grid */
@import "colors.rasi"
* { background-color: transparent; text-color: @fg; font: "{{ @UI }} {{ @SZ_L }}"; }
configuration { show-icons: true; icon-theme: "{{ @ROFI_ICONS }}"; display-drun: ""; drun-display-format: "{name}"; }
window { fullscreen: true; background-color: rgba(0,0,0,0%); transparency: "real"; padding: 6% 12%; }
window { background-color: @bg; }
mainbox { children: [ inputbar, listview ]; spacing: 36px; }
inputbar { padding: 12px 18px; background-color: @bg-alt; border-radius: 24px; border: 1px; border-color: @border-col; children: [ prompt, entry ]; spacing: 10px; margin: 0 20% 0 20%; }
prompt { enabled: false; } entry { text-color: @fg; placeholder: "Search apps, files, commands"; placeholder-color: @muted; }
listview { columns: 6; lines: 4; layout: vertical; flow: horizontal; scrollbar: false; spacing: 16px; fixed-columns: true; }
element { orientation: vertical; padding: 18px; border-radius: 14px; text-color: @fg; spacing: 8px; }
element-icon { size: 64px; horizontal-align: 0.5; }
element-text { horizontal-align: 0.5; text-color: inherit; }
element selected { background-color: @bg-hover; text-color: @fg; border: 2px; border-color: @accent; }
element-text { text-color: inherit; }
