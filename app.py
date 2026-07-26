# Root-level entry point.
#
# The actual Flask app lives in api/app.py (module path: api.app).
# Render's default start command for Python web services is
# "gunicorn app:app", which looks for a top-level module named
# "app" — this file exists purely so that command finds the real
# app object without you needing to change any Render dashboard
# settings.
from api.app import app

if __name__ == '__main__':
    import os
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 3000)), debug=False)