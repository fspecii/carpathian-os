/* carpatic-livecss: GTK3 module that makes ~/.config/gtk-3.0/gtk.css live.
 * GTK3 reads the user stylesheet once per process, so a running Thunar/Mousepad/Evince keeps the OLD colours (half light, half dark) when
 * carpatic-apply switches theme or accent. This module loads the same file a second time at a higher priority and reloads it whenever the
 * file changes (GFileMonitor), so every running GTK3 app follows the palette within a frame. Enabled through gtk-modules=carpatic-livecss
 * (settings.ini and xsettings). No effect in GTK4 programs (they never load GTK3 modules). MIT, part of Carpatic gtktheme/. */
#include <gtk/gtk.h>
#include <gmodule.h>

static GtkCssProvider *provider;
static GFileMonitor *monitor;
static gchar *path;

static void reload(void)
{
  if (!g_file_test(path, G_FILE_TEST_EXISTS)) return;
  gtk_css_provider_load_from_path(provider, path, NULL);
  gtk_style_context_reset_widgets(gdk_screen_get_default());
}

static void changed(GFileMonitor *m, GFile *f, GFile *o, GFileMonitorEvent ev, gpointer d)
{
  if (ev == G_FILE_MONITOR_EVENT_CHANGES_DONE_HINT || ev == G_FILE_MONITOR_EVENT_CREATED || ev == G_FILE_MONITOR_EVENT_RENAMED)
    reload();
}

G_MODULE_EXPORT void gtk_module_init(gint *argc, gchar ***argv)
{
  GdkScreen *screen = gdk_screen_get_default();
  GFile *file;
  if (provider || !screen) return;
  path = g_build_filename(g_get_user_config_dir(), "gtk-3.0", "gtk.css", NULL);
  provider = gtk_css_provider_new();
  gtk_style_context_add_provider_for_screen(screen, GTK_STYLE_PROVIDER(provider), GTK_STYLE_PROVIDER_PRIORITY_USER + 1);
  reload();
  file = g_file_new_for_path(path);
  monitor = g_file_monitor_file(file, G_FILE_MONITOR_NONE, NULL, NULL);
  if (monitor) g_signal_connect(monitor, "changed", G_CALLBACK(changed), NULL);
  g_object_unref(file);
}
