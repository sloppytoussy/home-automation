# DNS Monitor

Real-time DNS query analytics — top domains, blocked queries, clients, and query trends over time.

## Data Sources
- Pi-hole query log (tail/follow)
- Pi-hole API (for aggregates)

## Metrics Collected
- Total queries / blocked queries (per minute)
- Top queried domains
- Top blocked domains
- Per-client query counts
- Query type breakdown (A, AAAA, CNAME, etc.)

## Config
```
DNS_SERVER_IP=192.168.1.x
DNS_LOG_PATH=/var/log/pihole/pihole.log
```
