import json
import time
import uuid
import random
import string

import grpc
import requests
import paste_pb2
import paste_pb2_grpc

SIZES = [1_000, 10_000, 100_000, 1_000_000]  # text size in bytes
WARMUP = 100
RUNS = 500
CREATE_WARMUP = 10
CREATE_RUNS = 100
REST_URL = "http://localhost:8000"

channel = grpc.insecure_channel(
    "localhost:50051",
    options=[("grpc.max_receive_message_length", 4 * 1024 * 1024)],
)
stub = paste_pb2_grpc.PasteServiceStub(channel)
session = requests.Session()  # keep-alive, so it is fair for REST


def random_text(size):
    return "".join(random.choices(string.ascii_letters + " ", k=size))


def percentile(sorted_list, p):
    index = int(len(sorted_list) * p / 100)
    return sorted_list[min(index, len(sorted_list) - 1)]


def measure(func, warmup=WARMUP, runs=RUNS):
    for _ in range(warmup):
        func()
    times = []
    for _ in range(runs):
        start = time.perf_counter()
        func()
        times.append((time.perf_counter() - start) * 1000)  # ms
    times.sort()
    return percentile(times, 50), percentile(times, 95), percentile(times, 99)


payload_rows = []
latency_rows = []
create_rows = []

for size in SIZES:
    text = random_text(size)

    # --- gRPC: create + get one paste
    create_req = paste_pb2.CreatePasteRequest(
        content=text, ttl_seconds=3600, user_id="u1",
        idempotency_key=str(uuid.uuid4()))
    grpc_id = stub.CreatePaste(create_req).id
    get_req = paste_pb2.GetPasteRequest(id=grpc_id)
    grpc_resp = stub.GetPaste(get_req)

    # --- REST: create + get one paste
    body = {"content": text, "ttl_seconds": 3600, "user_id": "u1"}
    r = session.post(REST_URL + "/pastes", json=body,
                     headers={"Idempotency-Key": str(uuid.uuid4())})
    rest_id = r.json()["id"]
    rest_resp = session.get(f"{REST_URL}/pastes/{rest_id}")

    # --- payload size (bytes)
    payload_rows.append((
        size,
        len(create_req.SerializeToString()), len(json.dumps(body).encode()),
        len(grpc_resp.SerializeToString()), len(rest_resp.content),
    ))

    # --- latency of GET (ms)
    g = measure(lambda: stub.GetPaste(get_req, timeout=5))
    h = measure(lambda: session.get(f"{REST_URL}/pastes/{rest_id}"))
    latency_rows.append((size, g, h))

    # --- latency of POST (create), a new idempotency key for every call
    def grpc_create():
        stub.CreatePaste(paste_pb2.CreatePasteRequest(
            content=text, ttl_seconds=3600, user_id="u1",
            idempotency_key=str(uuid.uuid4())), timeout=5)

    def rest_create():
        session.post(REST_URL + "/pastes", json=body,
                     headers={"Idempotency-Key": str(uuid.uuid4())})

    gc = measure(grpc_create, CREATE_WARMUP, CREATE_RUNS)
    hc = measure(rest_create, CREATE_WARMUP, CREATE_RUNS)
    create_rows.append((size, gc, hc))

print("\nPayload size (bytes)")
print(f"{'text':>9} | {'gRPC req':>9} | {'JSON req':>9} | {'gRPC resp':>9} | {'JSON resp':>9}")
for size, pr, jr, ps, js in payload_rows:
    print(f"{size:>9} | {pr:>9} | {jr:>9} | {ps:>9} | {js:>9}")

print(f"\nGET latency (ms), {RUNS} runs after {WARMUP} warmup")
print(f"{'text':>9} | {'protocol':>8} | {'p50':>7} | {'p95':>7} | {'p99':>7}")
for size, g, h in latency_rows:
    print(
        f"{size:>9} | {'gRPC':>8} | {g[0]:>7.2f} | {g[1]:>7.2f} | {g[2]:>7.2f}")
    print(
        f"{'':>9} | {'REST':>8} | {h[0]:>7.2f} | {h[1]:>7.2f} | {h[2]:>7.2f}")

print(
    f"\nPOST (create) latency (ms), {CREATE_RUNS} runs after {CREATE_WARMUP} warmup")
print(f"{'text':>9} | {'protocol':>8} | {'p50':>7} | {'p95':>7} | {'p99':>7}")
for size, g, h in create_rows:
    print(
        f"{size:>9} | {'gRPC':>8} | {g[0]:>7.2f} | {g[1]:>7.2f} | {g[2]:>7.2f}")
    print(
        f"{'':>9} | {'REST':>8} | {h[0]:>7.2f} | {h[1]:>7.2f} | {h[2]:>7.2f}")
