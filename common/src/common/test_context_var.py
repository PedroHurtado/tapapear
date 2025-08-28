import time
import tracemalloc
import contextvars

# --- Caso 1: Pasamanos ---
def repo_with_param(tx):
    return tx["id"]

def service_with_param(tx):
    return repo_with_param(tx)

def run_with_param(n):
    for i in range(n):
        tx = {"id": i}  # simulamos transacción
        service_with_param(tx)

# --- Caso 2: ContextVar ---
tx_context = contextvars.ContextVar("tx")

def repo_with_ctx():
    return tx_context.get()["id"]

def service_with_ctx():
    return repo_with_ctx()

def run_with_ctx(n):
    for i in range(n):
        token = tx_context.set({"id": i})
        try:
            service_with_ctx()
        finally:
            tx_context.reset(token)

# --- Benchmark ---
def benchmark():
    N = 1_000_00  # 100k simulaciones

    print("=== Pasamanos ===")
    tracemalloc.start()
    t0 = time.time()
    run_with_param(N)
    t1 = time.time()
    mem1 = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    print(f"Tiempo: {t1-t0:.4f} s")
    print(f"Memoria actual: {mem1[0]/1024:.2f} KB, Pico: {mem1[1]/1024:.2f} KB\n")

    print("=== ContextVar ===")
    tracemalloc.start()
    t0 = time.time()
    run_with_ctx(N)
    t1 = time.time()
    mem2 = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    print(f"Tiempo: {t1-t0:.4f} s")
    print(f"Memoria actual: {mem2[0]/1024:.2f} KB, Pico: {mem2[1]/1024:.2f} KB\n")

benchmark()
