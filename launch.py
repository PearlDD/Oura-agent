"""Open the local app, reusing an already running instance."""
import threading
import urllib.request
import webbrowser
import app

url = f'http://127.0.0.1:{app.PORT}'
try:
    with urllib.request.urlopen(url + '/api/status', timeout=2) as r:
        running = r.status == 200
except Exception:
    running = False
if running:
    webbrowser.open(url)
else:
    threading.Timer(1, lambda: webbrowser.open(url)).start()
    app.main()
