FROM debian:trixie-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates python3 squid squidclient \
 && rm -rf /var/lib/apt/lists/*

COPY squid.conf /etc/squid/squid.conf
COPY collector.py /opt/archipelago/collector.py

EXPOSE 80 3128

CMD ["squid", "-N", "-f", "/etc/squid/squid.conf"]
