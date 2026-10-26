import socket
import os
import threading
import time
from agones import AgonesSDK

PORT = int(os.getenv("PORT", "7654"))

def handle_client(conn, addr):
    print(f"[{addr}] connected", flush=True)
    try:
        conn.sendall(b"Welcome to Cloud-Lab Game Server!\nGuess a number (1-10): ")
        while True:
            data = conn.recv(1024)
            if not data:
                break
            guess = data.decode().strip()
            if guess == "7":
                conn.sendall(b"Correct! You win!\n")
                break
            else:
                conn.sendall(f"Wrong, {guess} is not it. Try again: ".encode())
    except Exception as e:
        print(f"[{addr}] error: {e}", flush=True)
    finally:
        conn.close()
        print(f"[{addr}] disconnected", flush=True)

def main():
    # 1. Подключаемся к Agones SDK
    sdk = AgonesSDK()
    sdk.connect()
    
    # 2. Запускаем health-пинг в фоне (каждые 2 секунды)
    def health_loop():
        while True:
            try:
                sdk.health()
                time.sleep(2)
            except Exception as e:
                print(f"Health ping error: {e}", flush=True)
                time.sleep(2)
    
    threading.Thread(target=health_loop, daemon=True).start()
    
    # 3. Открываем TCP-порт
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("0.0.0.0", PORT))
    sock.listen(5)
    print(f"Game server listening on port {PORT}", flush=True)
    
    # 4. Говорим Agones, что мы готовы
    sdk.ready()
    print("SDK Ready() called, server is ready!", flush=True)

    while True:
        conn, addr = sock.accept()
        t = threading.Thread(target=handle_client, args=(conn, addr))
        t.daemon = True
        t.start()

if __name__ == "__main__":
    main()
