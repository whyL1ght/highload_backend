import os
import time
import random
import string
import threading
from concurrent import futures

import grpc
import paste_pb2
import paste_pb2_grpc

ALPHABET = string.ascii_letters + string.digits
MAX_SIZE = 1024 * 1024  # 1 MB

# for testing: the server sleeps after creating a paste (first call only)
DELAY_FIRST = float(os.environ.get("DELAY_FIRST", "0"))
delay_first_pending = True

pastes = {}      # id -> dict with paste data
idem_keys = {}   # idempotency_key -> (id, expires_at)
lock = threading.Lock()


def new_id():
    while True:
        pid = "".join(random.choice(ALPHABET) for _ in range(8))
        if pid not in pastes:
            return pid


def check_paste(context, pid):
    # returns the paste or stops the call with an error
    paste = pastes.get(pid)
    if paste is None:
        context.abort(grpc.StatusCode.NOT_FOUND, "paste not found")
    if paste["deleted_at"] != 0:
        context.abort(grpc.StatusCode.NOT_FOUND, "paste was deleted")
    if paste["expires_at"] != 0 and time.time() > paste["expires_at"]:
        context.abort(grpc.StatusCode.NOT_FOUND, "paste expired")
    return paste


def check_owner(context, paste, user_id):
    if user_id == "":
        context.abort(grpc.StatusCode.UNAUTHENTICATED, "login required")
    if paste["user_id"] != user_id:
        context.abort(grpc.StatusCode.PERMISSION_DENIED, "not your paste")


class PasteService(paste_pb2_grpc.PasteServiceServicer):

    def CreatePaste(self, request, context):
        global delay_first_pending

        if len(request.content.encode()) > MAX_SIZE:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT,
                          "content is too big (max 1 MB)")

        key = request.idempotency_key
        with lock:
            # same key again -> return the old answer, do not create a new paste
            if key and key in idem_keys:
                pid, expires_at = idem_keys[key]
                return paste_pb2.CreatePasteResponse(id=pid, expires_at=expires_at)

            pid = new_id()
            now = int(time.time())
            expires_at = now + request.ttl_seconds if request.ttl_seconds > 0 else 0
            pastes[pid] = {
                "content": request.content,
                "user_id": request.user_id,
                "created_at": now,
                "updated_at": now,
                "expires_at": expires_at,
                "deleted_at": 0,
            }
            if key:
                idem_keys[key] = (pid, expires_at)
            print("created paste", pid)

        if DELAY_FIRST and delay_first_pending:
            delay_first_pending = False
            time.sleep(DELAY_FIRST)  # fake slow server
        return paste_pb2.CreatePasteResponse(id=pid, expires_at=expires_at)

    def GetPaste(self, request, context):
        paste = check_paste(context, request.id)
        return paste_pb2.GetPasteResponse(
            content=paste["content"],
            created_at=paste["created_at"],
            expires_at=paste["expires_at"],
        )

    def UpdatePaste(self, request, context):
        if len(request.content.encode()) > MAX_SIZE:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT,
                          "content is too big (max 1 MB)")
        paste = check_paste(context, request.id)
        check_owner(context, paste, request.user_id)
        paste["content"] = request.content
        paste["updated_at"] = int(time.time())
        return paste_pb2.UpdatePasteResponse(updated_at=paste["updated_at"])

    def DeletePaste(self, request, context):
        paste = check_paste(context, request.id)
        check_owner(context, paste, request.user_id)
        paste["deleted_at"] = int(time.time())  # soft delete
        return paste_pb2.DeletePasteResponse()


def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    paste_pb2_grpc.add_PasteServiceServicer_to_server(PasteService(), server)
    server.add_insecure_port("[::]:50051")
    server.start()
    print("gRPC server started on port 50051")
    server.wait_for_termination()


if __name__ == "__main__":
    serve()
