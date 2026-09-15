"""AWS Lambda entrypoint for the FastAPI app (task #17, Lambda + API Gateway).

★ 왜 main.py를 수정하지 않는가 ★
`Mangum`은 이미 존재하는 `app.main.app`(FastAPI 인스턴스)을 그대로 감싸서
API Gateway(HTTP API) 프록시 이벤트를 ASGI 요청으로 변환한다. `create_app()`/
`main.py`는 로컬 실행(`uvicorn`)과 Lambda 배포가 완전히 동일한 앱 인스턴스를
쓰게 하려는 목적으로 손대지 않는다 -- 배포 방식이 API 계약이나 워크플로우
로직에 영향을 주면 안 된다는 ARCHITECTURE.md의 계층 분리 원칙과 같은 이유다.
"""

from __future__ import annotations

from mangum import Mangum

from app.main import app

handler = Mangum(app)
