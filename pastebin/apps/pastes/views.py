import json
import time

from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from .store import pastes, idem_keys, lock, new_id, MAX_SIZE


def error(status, message):
    return JsonResponse({"detail": message}, status=status)


def find_paste(pid):
    # returns (paste, error_response)
    paste = pastes.get(pid)
    if paste is None:
        return None, error(404, "paste not found")
    if paste["deleted_at"] != 0:
        return None, error(410, "paste was deleted")
    if paste["expires_at"] != 0 and time.time() > paste["expires_at"]:
        return None, error(410, "paste expired")
    return paste, None


def owner_error(paste, user_id):
    if user_id == "":
        return error(401, "login required")
    if paste["user_id"] != user_id:
        return error(403, "not your paste")
    return None


@csrf_exempt
@require_http_methods(["POST"])
def create_paste(request):
    body = json.loads(request.body)
    content = body.get("content", "")
    if len(content.encode()) > MAX_SIZE:
        return error(413, "content is too big (max 1 MB)")
    ttl = body.get("ttl_seconds", 0)
    key = request.headers.get("Idempotency-Key", "")

    with lock:
        # same key again -> return the old answer, do not create a new paste
        if key and key in idem_keys:
            pid, expires_at = idem_keys[key]
            return JsonResponse({"id": pid, "expires_at": expires_at}, status=201)

        pid = new_id()
        now = int(time.time())
        expires_at = now + ttl if ttl > 0 else 0
        pastes[pid] = {
            "content": content,
            "user_id": body.get("user_id", ""),
            "created_at": now,
            "updated_at": now,
            "expires_at": expires_at,
            "deleted_at": 0,
        }
        if key:
            idem_keys[key] = (pid, expires_at)

    return JsonResponse({"id": pid, "expires_at": expires_at}, status=201)


@csrf_exempt
@require_http_methods(["GET", "PUT", "DELETE"])
def paste_detail(request, pid):
    paste, err = find_paste(pid)
    if err:
        return err

    if request.method == "GET":
        return JsonResponse({
            "content": paste["content"],
            "created_at": paste["created_at"],
            "expires_at": paste["expires_at"],
        })

    if request.method == "PUT":
        body = json.loads(request.body)
        content = body.get("content", "")
        if len(content.encode()) > MAX_SIZE:
            return error(413, "content is too big (max 1 MB)")
        err = owner_error(paste, body.get("user_id", ""))
        if err:
            return err
        paste["content"] = content
        paste["updated_at"] = int(time.time())
        return JsonResponse({"updated_at": paste["updated_at"]})

    # DELETE
    err = owner_error(paste, request.GET.get("user_id", ""))
    if err:
        return err
    paste["deleted_at"] = int(time.time())  # soft delete
    return HttpResponse(status=204)
