import json
import os
import subprocess
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LOG = ROOT / 'voice_bridge.log'

MODEL = None
LOAD_ERROR = None


def log(line):
    with open(LOG, 'a', encoding='utf-8') as f:
        f.write('%s %s\n' % (time.strftime('%H:%M:%S'), line))


def load_model():
    global MODEL, LOAD_ERROR
    try:
        import whisper_engine
        MODEL = whisper_engine.load_model('auto')
        log('whisper model loaded')
    except Exception as exc:
        LOAD_ERROR = str(exc)
        log('model load failed: %s' % exc)


import threading
threading.Thread(target=load_model, daemon=True).start()


class Handler(BaseHTTPRequestHandler):
    def _send(self, status, body):
        data = json.dumps(body).encode('utf-8')
        self.send_response(status)
        self.send_header('Access-Control-Allow-Origin', 'http://127.0.0.1:3080')
        self.send_header('Access-Control-Allow-Headers', 'content-type')
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self):
        self._send(204, {})

    def do_POST(self):
        if self.path != '/transcribe':
            self._send(404, {'error': 'not found'})
            return
        started = time.time()
        try:
            size = int(self.headers.get('Content-Length', '0'))
            if size <= 0 or size > 25_000_000:
                raise ValueError('invalid audio size')
            body = self.rfile.read(size)
            data_dir = ROOT / 'data'
            data_dir.mkdir(exist_ok=True)
            audio = data_dir / ('voice_%d.webm' % os.getpid())
            audio.write_bytes(body)
            try:
                if MODEL is None:
                    waited = 0.0
                    while MODEL is None and LOAD_ERROR is None and waited < 120:
                        time.sleep(0.5); waited += 0.5
                if LOAD_ERROR:
                    raise RuntimeError('model: ' + LOAD_ERROR)
                if MODEL is None:
                    raise RuntimeError('model not ready')
                import whisper_engine
                text = whisper_engine.transcribe(MODEL, str(audio), 'en') or ''
                log('transcribed %d bytes in %.1fs -> %r' % (size, time.time() - started, text[:80]))
                self._send(200, {'text': text.strip()})
            finally:
                try: audio.unlink()
                except OSError: pass
        except Exception as exc:
            import traceback
            with open(LOG, 'a', encoding='utf-8') as f:
                f.write(traceback.format_exc() + '\n')
            self._send(500, {'error': str(exc)})

    def log_message(self, *_):
        pass


ThreadingHTTPServer(('127.0.0.1', 3099), Handler).serve_forever()
