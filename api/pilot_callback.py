"""Fail-closed GitHub Actions Pilot event callback for Vercel."""
from http.server import BaseHTTPRequestHandler
import hashlib, hmac, json, os
from deploygrade.engine.contracts import validate_artifact


class handler(BaseHTTPRequestHandler):
    def _send(self, status, payload):
        body=json.dumps(payload,sort_keys=True,separators=(",",":"),allow_nan=False).encode()
        self.send_response(status);self.send_header("Content-Type","application/json; charset=utf-8");self.send_header("Cache-Control","no-store");self.send_header("Content-Length",str(len(body)));self.end_headers();self.wfile.write(body)
    def do_POST(self):  # noqa: N802
        secret=os.environ.get("PILOT_CALLBACK_SECRET")
        try:
            if not secret: raise ValueError("Pilot callback is not configured")
            length=int(self.headers.get("Content-Length","0"))
            if length <= 0 or length > 32768: raise ValueError("invalid callback body length")
            raw=self.rfile.read(length)
            supplied=self.headers.get("X-DeployGrade-Signature","")
            expected=hmac.new(secret.encode(),raw,hashlib.sha256).hexdigest()
            if not hmac.compare_digest(supplied,expected): raise ValueError("invalid callback signature")
            event=json.loads(raw);event={"$schema":"../schemas/pilot_callback.schema.json","schema_version":"1.0",**event}
            validate_artifact(event)
            self._send(202,{"accepted":True,"event_type":event["event_type"]})
        except (ValueError,json.JSONDecodeError) as error: self._send(400,{"accepted":False,"error":str(error)})
