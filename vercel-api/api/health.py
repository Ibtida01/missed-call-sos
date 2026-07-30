from http.server import BaseHTTPRequestHandler
import json

def handler(req: BaseHTTPRequestHandler):
    return {
        'statusCode': 200,
        'body': json.dumps({'ok': True, 'calls': 0})
    }