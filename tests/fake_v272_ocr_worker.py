import json
import sys
import time


mode = sys.argv[1]
if mode == 'late-ready':
    time.sleep(30)
print('__READY__', flush=True)
if mode == 'no-read':
    time.sleep(30)
for line in sys.stdin:
    request = json.loads(line)
    request_id = request['request_id']
    if mode == 'silent':
        time.sleep(30)
    if mode == 'partial':
        print('{', end='', flush=True)
        time.sleep(30)
    if mode == 'malformed':
        print('{broken', flush=True)
        continue
    if mode == 'stderr':
        sys.stderr.write('x' * 200_000)
        sys.stderr.flush()
    response = {'status': 'ok', 'lines': [], 'request_id': request_id}
    if mode == 'wrong-id':
        response['request_id'] = 'previous-request'
    if mode == 'missing-id':
        del response['request_id']
    if mode == 'application-error':
        response.update(status='error', error='image cannot be decoded')
    print(json.dumps(response), flush=True)
