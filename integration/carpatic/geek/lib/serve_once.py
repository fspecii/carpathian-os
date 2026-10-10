"""Serve one file once over HTTP on this network, then stop (also stops after 15 minutes). Used by carpatic trigger share.
usage: serve_once.py FILE ADDRESS URLFILE"""
import http.server
import os
import socketserver
import sys
import threading
import urllib.parse

f, ip, urlfile = sys.argv[1], sys.argv[2], sys.argv[3]
name = os.path.basename(f)


class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != "/" + urllib.parse.quote(name):
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Length", str(os.path.getsize(f)))
        self.send_header("Content-Disposition", 'attachment; filename="%s"' % name)
        self.end_headers()
        with open(f, "rb") as fh:
            self.wfile.write(fh.read())
        threading.Thread(target=srv.shutdown).start()

    def log_message(self, *a):
        pass


socketserver.TCPServer.allow_reuse_address = True
# 53317 is the one port the default firewall leaves open for sharing (docs/SECURITY.md); fall back to a random port when it is busy
try:
    srv = socketserver.TCPServer(("0.0.0.0", 53317), H)
except OSError:
    srv = socketserver.TCPServer(("0.0.0.0", 0), H)
with open(urlfile, "w") as u:
    u.write("http://%s:%d/%s\n" % (ip, srv.server_address[1], urllib.parse.quote(name)))
threading.Timer(900, srv.shutdown).start()
srv.serve_forever()
