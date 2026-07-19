FROM debian:trixie-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates python3 squid squidclient \
 && rm -rf /var/lib/apt/lists/*

COPY squid.conf /etc/squid/squid.conf
COPY collector.py /opt/archipelago/collector.py
COPY certs/agent-help.crt /opt/archipelago/certs/agent-help.crt
COPY certs/agent-help.key /opt/archipelago/certs/agent-help.key

RUN chmod 600 /opt/archipelago/certs/agent-help.key

EXPOSE 443 3128

CMD ["squid", "-N", "-f", "/etc/squid/squid.conf"]
