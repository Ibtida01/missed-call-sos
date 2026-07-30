from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs
import json

def handler(req: BaseHTTPRequestHandler):
    if req.method == 'POST':
        body = parse_qs(req.body.decode())
        from_num = body.get('From', [''])[0]
        to_num = body.get('To', [''])[0]
        
        twiml = '<?xml version="1.0" encoding="UTF-8"?><Response><Reject reason="busy"/></Response>'
        return {
            'statusCode': 200,
            'headers': {'Content-Type': 'application/xml'},
            'body': twiml
        }
    return {'statusCode': 405, 'body': 'Method not allowed'}