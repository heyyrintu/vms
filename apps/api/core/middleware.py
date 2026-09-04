import logging
import time
import uuid

logger = logging.getLogger("vms.request")


class RequestIDMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))[:64]
        response = self.get_response(request)
        response["X-Request-ID"] = request.request_id
        return response


class RequestLogMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        started = time.perf_counter()
        response = self.get_response(request)
        logger.info(
            "request_complete",
            extra={
                "request_id": getattr(request, "request_id", ""),
                "method": request.method,
                "path": request.path,
                "status": response.status_code,
                "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                "user_id": getattr(getattr(request, "user", None), "pk", None),
            },
        )
        return response
