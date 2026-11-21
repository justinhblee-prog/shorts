# scripts/ui_development_monitor_smoke_server.py

from http.server import BaseHTTPRequestHandler, HTTPServer

class DevelopmentMonitorServer(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/api/monitor':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(b'{