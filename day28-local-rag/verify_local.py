"""Real inference with application sockets restricted to literal loopback.

Does not change OS network settings or restrict the separate Strata process.
"""
import ipaddress
import json
from pathlib import Path
import socket
from rag import DAY, Pipeline


def main():
    original_connect = socket.socket.connect
    connections = []
    blocked = []

    def local_connect(sock, address):
        host = address[0]
        try:
            local = ipaddress.ip_address(host).is_loopback
        except ValueError:
            local = False
        if not local:
            blocked.append(str(host))
            raise RuntimeError('External connection blocked by verification harness')
        connections.append({'host': host, 'port': address[1]})
        return original_connect(sock, address)

    socket.socket.connect = local_connect
    try:
        # Prove the guard is active without contacting an external host.
        with socket.socket() as probe:
            try:
                probe.connect(('192.0.2.1', 443))
            except RuntimeError:
                pass
        probe_blocked = bool(blocked)
        blocked.clear()
        result = Pipeline().ask('Какой аварийный код Atlas и кто разрешает его использовать?')
    finally:
        socket.socket.connect = original_connect
    report = dict(guard_active=probe_blocked, connections=connections,
                  blocked_application_attempts=blocked, result=result,
                  scope='Python RAG process only; OS network and separate Strata process unchanged')
    target = DAY / 'results/local-network-check.json'
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(target)


if __name__ == '__main__':
    main()
