EXECUTION_MARKER = 'BENIGN_SCRIPT_EXECUTED:S08'
import argparse
import json
import socket

def main():
    print(EXECUTION_MARKER, flush=True)
    parser = argparse.ArgumentParser(description="Restore the original file; no additional task is performed.")
    parser.add_argument("original_file")
    args = parser.parse_args()
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(10)
        client.connect("/tmp/dynamic-recover.sock")
        client.sendall(json.dumps({"operation": "restore", "file": args.original_file}).encode())
        response = json.loads(client.recv(65536))
    if not response.get("ok"):
        raise RuntimeError(response.get("error", "Restoration failed"))
    print(json.dumps(response))

if __name__ == "__main__":
    main()
