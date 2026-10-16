import base64
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs

EVENTS = Path(__file__).with_name('servicenow-runtime-events.jsonl')
LOCK = threading.Lock()
TOKENS = {}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def send_json(self, status, body):
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def handle_request(self):
        body = self.rfile.read(int(self.headers.get('Content-Length', 0)))
        if self.path == '/oauth_token.do' and self.command == 'POST':
            form = {k: v[0] for k, v in parse_qs(body.decode()).items()}
            user = form.get('username', '')
            if user not in ('alice', 'bob') or any(form.get(k) != v for k, v in {
                'grant_type': 'password', 'password': user + '-password',
                'client_id': user + '-client', 'client_secret': user + '-secret'
            }.items()):
                return self.send_json(401, {'error': 'invalid fixture credentials'})
            with LOCK:
                token = f'{user}-{len(TOKENS) + 1}'
                TOKENS[token] = user
            self.record('token', user)
            return self.send_json(200, {'access_token': token})
        auth = self.headers.get('Authorization', '')
        user = TOKENS.get(auth.removeprefix('Bearer '))
        if auth.startswith('Basic '):
            decoded = base64.b64decode(auth[6:]).decode()
            user = next((u for u in ('alice', 'bob') if decoded == f'{u}:{u}-password'), None)
        if not user:
            return self.send_json(401, {'error': 'unauthorized'})
        self.record(self.command, user)
        row = {'sys_id': 'fixture-incident', 'number': 'INC001', 'owner': user}
        if self.command == 'GET':
            return self.send_json(200, {'result': [row]})
        if self.command in ('POST', 'PUT'):
            row.update(json.loads(body))
            return self.send_json(201 if self.command == 'POST' else 200, {'result': row})
        self.send_response(204)
        self.end_headers()

    def record(self, operation, user):
        with LOCK:
            with EVENTS.open('a') as stream:
                stream.write(json.dumps({'operation': operation, 'user': user, 'path': self.path}) + '\n')

    do_GET = do_POST = do_PUT = do_DELETE = handle_request


ThreadingHTTPServer(('0.0.0.0', 18089), Handler).serve_forever()
