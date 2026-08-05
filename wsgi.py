"""PythonAnywhere용 WSGI 엔트리 (ASGI 앱 → WSGI 브리지).

PythonAnywhere 웹 탭에서 "WSGI configuration file"에 아래 코드를 붙여넣거나,
이 파일을 import 하도록 설정합니다:

    from wsgi import application
"""
from a2wsgi import ASGIMiddleware

from app.main import app

application = ASGIMiddleware(app)
