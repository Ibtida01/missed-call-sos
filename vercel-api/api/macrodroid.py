from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs
import json

def handler(req: BaseHTTPRequestHandler):
    if req.method in ['GET', 'POST']:
        caller = ''
        if req.method == 'GET':
            query = parse_qs(req.url.split('?')[1] if '?' in req.url else '')
            caller = query.get('caller', [''])[0]
        else:
            try:
                body = json.loads(req.body.decode())
                caller = body.get('caller', '')
            except:
                pass
        
        if not caller:
            return {'statusCode': 400, 'body': json.dumps({'error': 'missing caller'})}
        
        return {
            'statusCode': 200,
            'body': json.dumps({'caller': caller, 'received': True})
        }
    return {'statusCode': 405, 'body': 'Method not allowed'}