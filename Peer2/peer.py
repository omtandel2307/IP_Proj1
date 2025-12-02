import socket
import threading
import os
import time
import platform

#global
PEER_HOST = socket.gethostname()


# upload server -- get rfc
def upload_server_conn(port):
    try:
        s_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s_socket.bind(('', port))
        s_socket.listen(5)
        print(f"[UPLOAD SERVER] Listening on port {port}")
    except OSError as e:
        if e.errno == 10048 or e.errno == 48:  # Windows/Unix port in use
            print(f"[UPLOAD SERVER] Error: Port {port} is already in use")
            print("[UPLOAD SERVER] Please choose a different port and restart")
        else:
            print(f"[UPLOAD SERVER] Error: Cannot bind to port {port} - {e}")
        return
    except Exception as e:
        print(f"[UPLOAD SERVER] Error: Failed to start upload server - {e}")
        return

    while True:
        try:
            conn, addr = s_socket.accept()
            threading.Thread(
                target=handle_get_rfc,
                args=(conn, addr),
                daemon=True
            ).start()
        except Exception as e:
            print(f"[UPLOAD SERVER] Error accepting connection: {e}")
            continue

def extract_title_from_file(filename, rfc_number):
    try:
        with open(filename, 'r', encoding='utf-8', errors='ignore') as f:
            for _ in range(10):
                line = f.readline().strip()
                if line and len(line) > 5:
                    return line[:100]
    except Exception as e:
        print(f"[Peer] Warning: Could not read title from {filename}: {e}")
    
    return f"RFC {rfc_number}"

def register_local_rfcs(ci_file, upload_port):
    print("[Peer] Scanning for local RFC files...")
    
    try:
        files = os.listdir('.')
    except Exception as e:
        print(f"[Peer] Error reading directory: {e}")
        return
    
    rfc_files = [f for f in files if f.startswith('rfc') and f.endswith('.txt')]
    
    if not rfc_files:
        print("[Peer] No local RFC files found.")
        return
    
    print(f"[Peer] Found {len(rfc_files)} RFC file(s)")
    
    for filename in rfc_files:
        try:
            rfc_number_str = filename[3:-4]
            rfc_number = int(rfc_number_str)
            
            title = extract_title_from_file(filename, rfc_number)
            
            print(f"[Peer] Registering RFC {rfc_number}: {title}")
            
            send_add(ci_file, rfc_number, title, upload_port)
            
        except ValueError:
            print(f"[Peer] Skipping invalid filename: {filename}")
            continue
        except Exception as e:
            print(f"[Peer] Error registering {filename}: {e}")
            continue
    
    print("[Peer] Registration complete.")

def handle_get_rfc(conn, addr):
    conn_file = conn.makefile('rwb')
    print(f"[UPLOAD SERVER] Connection from {addr}")

    try:
        # read request line
        request_line = conn_file.readline().decode().strip()
        if not request_line:
            return

        print(f"[UPLOAD SERVER] Request: {request_line}")
        parts = request_line.split()
        if len(parts) != 4:
            send_err(conn_file, 400, "Bad Request")
            return

        method, obj, rfc_str, version = parts

        # validate method and format
        if method != "GET" or obj != "RFC" or version != "P2P-CI/1.0":
            send_err(conn_file, 400, "Bad Request")
            return

        # validate rfc number
        try:
            rfc_number = int(rfc_str)
        except ValueError:
            send_err(conn_file, 400, "Bad Request")
            return

        # read headers
        headers = read_headers(conn_file)
        host = headers.get("Host")
        os_header = headers.get("OS")

        if not host:
            send_err(conn_file, 400, "Bad Request")
            return

        # rfc file
        rfc_file = f"rfc{rfc_number}.txt"
        if not os.path.isfile(rfc_file):
            send_err(conn_file, 404, "Not Found")
            return

        send_rfc(conn_file, rfc_file, rfc_number)

    finally:
        conn_file.close()
        conn.close()


def read_headers(conn_file):
    headers = {}
    while True:
        line = conn_file.readline().decode()
        if not line:
            break
        line = line.strip()
        if line == "":
            break
        if ":" in line:
            key, value = line.split(":", 1)
            headers[key.strip()] = value.strip()
    return headers


def send_err(conn_file, code, message):
    response = f"P2P-CI/1.0 {code} {message}\r\n\r\n"
    conn_file.write(response.encode())
    conn_file.flush()


def send_rfc(conn_file, filename, rfc_number):
    file_size = os.path.getsize(filename)
    modified_time = time.ctime(os.path.getmtime(filename))
    os_name = platform.system()

    header = (
        "P2P-CI/1.0 200 OK\r\n"
        f"Date: {time.ctime()}\r\n"
        f"OS: {os_name}\r\n"
        f"Last-Modified: {modified_time}\r\n"
        f"Content-Length: {file_size}\r\n"
        "Content-Type: text/text\r\n"
        "\r\n"
    )

    conn_file.write(header.encode())

    with open(filename, 'rb') as f:
        conn_file.write(f.read())

    conn_file.flush()


# client side -- talk to ci server
def connect_to_ci(ci_host, ci_port):
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect((ci_host, ci_port))
        return sock, sock.makefile('rwb')
    except ConnectionRefusedError:
        print(f"[Peer] Error: Cannot connect to CI server at {ci_host}:{ci_port} - Connection refused")
        print("[Peer] Make sure the server is running")
        return None, None
    except socket.gaierror:
        print(f"[Peer] Error: Cannot resolve hostname '{ci_host}'")
        return None, None
    except Exception as e:
        print(f"[Peer] Error: Failed to connect to CI server - {e}")
        return None, None


def send_add(ci_file, rfc_number, title, upload_port):
    request = (
        f"ADD RFC {rfc_number} P2P-CI/1.0\r\n"
        f"Host: {PEER_HOST}\r\n"
        f"Port: {upload_port}\r\n"
        f"Title: {title}\r\n"
        "\r\n"
    )
    ci_file.write(request.encode())
    ci_file.flush()

    # read and print status line
    status = ci_file.readline().decode()
    print(status, end="")
    
    # Check for errors
    if "400" in status or "404" in status or "505" in status:
        ci_file.readline()
        return False

    blank = ci_file.readline().decode()
    print(blank, end="")

    # rfc line (if any)
    line = ci_file.readline().decode()
    print(line, end="")
    
    final_blank = ci_file.readline().decode()
    print(final_blank, end="")
    return True 


def send_lookup(ci_file, rfc_number, upload_port, title):
    request = (
        f"LOOKUP RFC {rfc_number} P2P-CI/1.0\r\n"
        f"Host: {PEER_HOST}\r\n"
        f"Port: {upload_port}\r\n"
        f"Title: {title}\r\n"
        "\r\n"
    )
    ci_file.write(request.encode())
    ci_file.flush()

    # read status line
    status = ci_file.readline().decode().strip()
    print(status)
    
    # Check for any error status
    if "400" in status:
        print("[Peer] Error: Bad Request")
        ci_file.readline()
        return []
    elif "404" in status:
        print("[Peer] Error: RFC not found")
        ci_file.readline()
        return []
    elif "505" in status:
        print("[Peer] Error: Protocol version not supported")
        ci_file.readline()
        return []
    elif "200" not in status:
        print(f"[Peer] Error: Unexpected response: {status}")
        ci_file.readline()
        return []

    ci_file.readline()

    entries = []
    while True:
        line = ci_file.readline().decode().strip()
        if line == "":
            break
        print(line)
        parts = line.split()
        if parts[0] == "RFC":
            rfc = int(parts[1])
            port = int(parts[-1])
            host = parts[-2]
            title = " ".join(parts[2:-2])
        else:
            # Fallback if no RFC prefix
            rfc = int(parts[0])
            port = int(parts[-1])
            host = parts[-2]
            title = " ".join(parts[1:-2])
        entries.append({
            "rfc": rfc,
            "title": title,
            "host": host,
            "port": port
        })

    return entries


def send_list(ci_file, upload_port):
    request = (
        "LIST ALL P2P-CI/1.0\r\n"
        f"Host: {PEER_HOST}\r\n"
        f"Port: {upload_port}\r\n"
        "\r\n"
    )
    ci_file.write(request.encode())
    ci_file.flush()

    status = ci_file.readline().decode().strip()
    print(status)
    
    # Check for any error status
    if "400" in status:
        print("[Peer] Error: Bad Request")
        ci_file.readline()
        return []
    elif "404" in status:
        print("[Peer] Error: No RFCs available")
        ci_file.readline()
        return []
    elif "505" in status:
        print("[Peer] Error: Protocol version not supported")
        ci_file.readline()
        return []
    elif "200" not in status:
        print(f"[Peer] Error: Unexpected response: {status}")
        ci_file.readline()
        return []

    ci_file.readline()

    entries = []
    while True:
        line = ci_file.readline().decode().strip()
        if line == "":
            break
        print(line)
        parts = line.split()
        if parts[0] == "RFC":
            rfc = int(parts[1])
            port = int(parts[-1])
            host = parts[-2]
            title = " ".join(parts[2:-2])
        else:
            rfc = int(parts[0])
            port = int(parts[-1])
            host = parts[-2]
            title = " ".join(parts[1:-2])
        entries.append({
            "rfc": rfc,
            "title": title,
            "host": host,
            "port": port
        })

    return entries


def download_rfc_from_peer(rfc_number, peer_host, peer_port, upload_port):
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect((peer_host, peer_port))
        sock_file = sock.makefile('rwb')
    except ConnectionRefusedError:
        print(f"[Peer] Error: Cannot connect to {peer_host}:{peer_port} - Connection refused")
        return False
    except socket.timeout:
        print(f"[Peer] Error: Connection to {peer_host}:{peer_port} timed out")
        return False
    except Exception as e:
        print(f"[Peer] Error: Failed to connect to {peer_host}:{peer_port} - {e}")
        return False

    try:
        request = (
            f"GET RFC {rfc_number} P2P-CI/1.0\r\n"
            f"Host: {PEER_HOST}\r\n"
            f"OS: {platform.system()} {platform.release()}\r\n"
            "\r\n"
        )
        sock_file.write(request.encode())
        sock_file.flush()

        # status line
        status = sock_file.readline().decode().strip()
        print(status)

        # Check for any error status
        if "400" in status:
            print("[Peer] Error: Bad Request from peer")
            sock_file.readline()
            sock.close()
            return False
        elif "404" in status:
            print("[Peer] Error: RFC not found on peer")
            sock_file.readline()
            sock.close()
            return False
        elif "505" in status:
            print("[Peer] Error: Protocol version not supported by peer")
            sock_file.readline()
            sock.close()
            return False
        elif "200" not in status:
            print(f"[Peer] Error: Unexpected response from peer: {status}")
            sock_file.readline()
            sock.close()
            return False

        # read headers from peer
        headers = {}
        while True:
            line = sock_file.readline().decode()
            if not line:
                break
            line = line.strip()
            if line == "":
                break
            print(line)
            if ":" in line:
                key, value = line.split(":", 1)
                headers[key.strip()] = value.strip()

        content_len = int(headers.get("Content-Length", "0"))

        # read file content
        filename = f"rfc{rfc_number}.txt"
        with open(filename, 'wb') as f:
            if content_len > 0:
                remaining = content_len
                while remaining > 0:
                    chunk = sock_file.read(min(4096, remaining))
                    if not chunk:
                        break
                    f.write(chunk)
                    remaining -= len(chunk)
            else:
                # fallback: read until socket closes
                f.write(sock_file.read())

        print(f"[PEER] Downloaded RFC {rfc_number} from {peer_host}")
        return True
        
    except Exception as e:
        print(f"[Peer] Error during download: {e}")
        return False
    finally:
        sock.close()


def main():
    try:
        upload_port = int(input("Enter your upload port: ").strip())
        if upload_port < 1024 or upload_port > 65535:
            print("[Peer] Error: Port must be between 1024 and 65535")
            return
    except ValueError:
        print("[Peer] Error: Invalid port number")
        return
    
    threading.Thread(
        target=upload_server_conn,
        args=(upload_port,),
        daemon=True
    ).start()
    
    # Give upload server time to start
    time.sleep(0.5)

    ci_host = input("Enter CI server host: ").strip()
    try:
        ci_port = int(input("Enter CI server port: ").strip())
        if ci_port < 1 or ci_port > 65535:
            print("[Peer] Error: Port must be between 1 and 65535")
            return
    except ValueError:
        print("[Peer] Error: Invalid port number")
        return

    ci_sock, ci_file = connect_to_ci(ci_host, ci_port)
    
    if ci_sock is None or ci_file is None:
        print("[Peer] Failed to connect to CI server. Exiting...")
        return
    
    print(f"[Peer] Connected to server at port {ci_port}")

    register_local_rfcs(ci_file, upload_port)

    while True:
        try:
            cmd = input("\nEnter command (ADD / LOOKUP / LIST / GET / EXIT): ").strip().upper()

            if cmd == "ADD":
                rfc = int(input("RFC number: ").strip())
                title = input("Title: ").strip()
                version = input("Version: ").strip()
                if not version.startswith("P2P-CI/"):
                    print("P2P-CI/1.0 400 Bad Request")
                    continue
                if version != "P2P-CI/1.0":
                    print("P2P-CI/1.0 505 P2P-CI Version Not Supported")
                    continue
                send_add(ci_file, rfc, title, upload_port)

            elif cmd == "LOOKUP":
                rfc = int(input("RFC number: ").strip())
                title = input("Title: ").strip()
                version = input("Version: ").strip()
                if not version.startswith("P2P-CI/"):
                    print("P2P-CI/1.0 400 Bad Request")
                    continue
                if version != "P2P-CI/1.0":
                    print("P2P-CI/1.0 505 P2P-CI Version Not Supported")
                    continue
                _entries = send_lookup(ci_file, rfc, upload_port, title) 

            elif cmd == "LIST":
                version = input("Version: ").strip()
                if not version.startswith("P2P-CI/"):
                    print("P2P-CI/1.0 400 Bad Request")
                    continue
                if version != "P2P-CI/1.0":
                    print("P2P-CI/1.0 505 P2P-CI Version Not Supported")
                    continue
                _entries = send_list(ci_file, upload_port)

            elif cmd == "GET":
                rfc = int(input("RFC number: ").strip())
                host = input("Peer host: ").strip()
                port = int(input("Peer upload port: ").strip())
                version = input("Version: ").strip()
                if not version.startswith("P2P-CI/"):
                    print("P2P-CI/1.0 400 Bad Request")
                    continue
                if version != "P2P-CI/1.0":
                    print("P2P-CI/1.0 505 P2P-CI Version Not Supported")
                    continue
                download_rfc_from_peer(rfc, host, port, upload_port)

            elif cmd == "EXIT":
                print("[PEER] Disconnecting.")
                ci_sock.close()
                break

            else:
                print("Unknown command. Use ADD / LOOKUP / LIST / GET / EXIT.")
                
        except ValueError as e:
            print(f"[Peer] Error: Invalid input - {e}")
        except KeyboardInterrupt:
            print("\n[PEER] Interrupted. Disconnecting...")
            ci_sock.close()
            break
        except BrokenPipeError:
            print("[Peer] Error: Connection to server lost")
            break
        except Exception as e:
            print(f"[Peer] Error: {e}")
            print("Continuing...")


if __name__ == "__main__":
    main()
