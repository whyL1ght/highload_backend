import time
import random
import uuid

import grpc
import paste_pb2
import paste_pb2_grpc

TIMEOUT = 0.15      # 150 ms, same as our p99 goal
MAX_ATTEMPTS = 3
RETRY_CODES = (grpc.StatusCode.UNAVAILABLE, grpc.StatusCode.DEADLINE_EXCEEDED)


def call_with_retry(method, request):
    delay = 0.2
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            return method(request, timeout=TIMEOUT)
        except grpc.RpcError as e:
            # retry only for temporary errors, and not after the last attempt
            if e.code() not in RETRY_CODES or attempt == MAX_ATTEMPTS:
                raise
            wait = delay + random.uniform(0, 0.1)  # backoff + jitter
            print(
                f"  attempt {attempt} failed ({e.code().name}), retry in {wait:.2f}s")
            time.sleep(wait)
            delay *= 2


def main():
    channel = grpc.insecure_channel("localhost:50051")
    stub = paste_pb2_grpc.PasteServiceStub(channel)

    print("1. create")
    key = str(uuid.uuid4())  # one key for ALL retries of this request
    create_req = paste_pb2.CreatePasteRequest(
        content="print('hello')", ttl_seconds=3600,
        user_id="user-1", idempotency_key=key,
    )
    created = call_with_retry(stub.CreatePaste, create_req)
    print("  id =", created.id)

    print("2. send the same create again (same key)")
    again = call_with_retry(stub.CreatePaste, create_req)
    print("  id =", again.id, "-> same id:", again.id == created.id)

    print("3. get")
    got = call_with_retry(
        stub.GetPaste, paste_pb2.GetPasteRequest(id=created.id))
    print("  content =", got.content)

    print("4. update by owner")
    call_with_retry(stub.UpdatePaste, paste_pb2.UpdatePasteRequest(
        id=created.id, content="print('new text')", user_id="user-1"))
    got = call_with_retry(
        stub.GetPaste, paste_pb2.GetPasteRequest(id=created.id))
    print("  content =", got.content)

    print("4b. list my pastes")
    my = call_with_retry(
        stub.ListMyPastes, paste_pb2.ListMyPastesRequest(user_id="user-1"))
    print("  count =", len(my.pastes), "ids =", [p.id for p in my.pastes])

    print("5. update by another user")
    try:
        call_with_retry(stub.UpdatePaste, paste_pb2.UpdatePasteRequest(
            id=created.id, content="hack", user_id="user-2"))
    except grpc.RpcError as e:
        print("  error:", e.code().name)

    print("6. delete, then get")
    call_with_retry(stub.DeletePaste, paste_pb2.DeletePasteRequest(
        id=created.id, user_id="user-1"))
    try:
        call_with_retry(
            stub.GetPaste, paste_pb2.GetPasteRequest(id=created.id))
    except grpc.RpcError as e:
        print("  error:", e.code().name, "-", e.details())


if __name__ == "__main__":
    main()
