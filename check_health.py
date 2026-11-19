import urllib.request, sys, traceback
try:
    with urllib.request.urlopen('http://127.0.0.1:8001/health') as resp:
        print('Status:', resp.status)
        print('Body:', resp.read().decode())
except Exception as e:
    traceback.print_exc()
    print('Error:', e)
