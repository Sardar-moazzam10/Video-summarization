import http.server
import os
import socketserver

BUILD_DIR = os.path.abspath("build")

class SPAHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=BUILD_DIR, **kwargs)

    def do_GET(self):
        full_path = self.translate_path(self.path)
        if not os.path.isfile(full_path):
            self.path = "/index.html"
        return super().do_GET()

if __name__ == "__main__":
    port = 3000
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("", port), SPAHandler) as httpd:
        print(f"Serving SPA from {BUILD_DIR} on port {port}")
        httpd.serve_forever()

