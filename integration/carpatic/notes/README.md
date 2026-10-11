# Notes

Carpathian Notes is an on-demand GTK3 application for private, local plain-text
notes. Open **Notes** from the application menu. A second launch presents the
existing window instead of starting another editor.

Create a note with **New**, edit its title and text, and choose **Save**. The
status line distinguishes saved text, unsaved changes, and failed writes.
Switching notes or closing an unsaved draft offers Save, Discard, or Cancel.
Typing during a save remains unsaved until the newer text is saved too.

Search matches Unicode text literally. Trash keeps notes recoverable; select
**Show Trash** and restore a note to edit it again. Export writes the current
draft as UTF-8 text to a chosen file, with overwrite confirmation. A completed
temporary file replaces an existing export, preserving it if writing fails.

The list collapses in narrow windows. Its toolbar button and Ctrl+B reopen it;
Ctrl+F opens search. Ctrl+N creates a note, Ctrl+S saves, Ctrl+E exports, and
Ctrl+W closes the window through the unsaved-change prompt.

Storage lives at `$XDG_DATA_HOME/carpathian/notes/notes.sqlite3`, or under
`~/.local/share` when the environment variable is unset. The database is private
to its owner, uses versioned SQLite transactions and optimistic revisions, and
refuses unknown or corrupt databases without replacing their contents. A
conflicting save preserves the draft and offers reopening the saved version.
Export remains available when storage cannot be opened.

There is no network access, login service, or idle polling. One storage worker
keeps disk operations off the GTK main loop. Performance claims require measured
results; using an existing GTK toolkit avoids adding another desktop runtime.

`install.sh` installs program files and the application-menu entry. It accepts an
absolute `DESTDIR` for staging and does not open user databases or start services.
Storage and staging regressions are in `tests/notes-storage.py` and
`tests/notes-install.py`; actual GTK checks in `tests/notes-gui.py` require a
verified private Xvfb display and a private session bus.
