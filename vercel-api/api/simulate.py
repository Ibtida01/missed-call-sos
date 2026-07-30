from http.server import BaseHTTPRequestHandler
import json

def handler(req: BaseHTTPRequestHandler):
    if req.method == 'POST':
        try:
            payload = json.loads(req.body.decode())
            severity = payload.get('severity', 1)
            if severity not in (1, 2, 3):
                return {'statusCode': 400, 'body': json.dumps({'error': 'invalid severity'})}
            return {
                'statusCode': 200,
                'body': json.dumps({'severity': severity, 'simulated': True})
            }
        except:
            return {'statusCode': 400, 'body': json.dumps({'error': 'invalid request'})}
    return {'statusCode': 405, 'body': 'Method not allowed'}