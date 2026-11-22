<!--
SPDX-FileCopyrightText: Christian Pfeiffer
SPDX-License-Identifier: MIT
-->

# Metrics

`nwi-metrics.service` serves how the servers run, for Prometheus or Netdata:
each server's tick rate against its tickrate, its CPU time, traffic and uptime,
its human players and bots, and the human players' ping, packet loss and choke
(median and most, and how many lose more than 5% or get more than 5% of the
server's packets held back). At each scrape it asks the servers over RCON
(`nwi-server metrics`, see `nwi-server metrics --help` for all of them). The
choke comes from the `nwi_netstats` plugin, as `status` doesn't show it: a
server without it has no choke metrics. It listens on this machine only,
`127.0.0.1:9734`; another address, of an internal network, goes into a drop-in
(see the unit), never a public one, and its port into the firewall's internal
ports.

```bash
systemctl enable --now nwi-metrics.service
nwi-server metrics --once   # the metrics once, by hand
```

Prometheus scrapes it with:

```yaml
scrape_configs:
  - job_name: nwi-servers
    scrape_interval: 15s
    static_configs:
      - targets: ["127.0.0.1:9734"]
```

and Netdata with its Prometheus collector, in `/etc/netdata/go.d/prometheus.conf`:

```yaml
jobs:
  - name: nwi-servers
    url: http://127.0.0.1:9734/metrics
```

A server that can't keep its tick, e.g. below 94% of it for a minute, is worth an
alert (Prometheus):

```yaml
- alert: ServerTickRateLow
  expr: nwi_server_tick_rate / nwi_server_tick_rate_target < 0.94
  for: 1m
```

The CPU time is the server unit's, of all its processes, as the game's own
figure is always 0 on Linux: `rate(nwi_server_cpu_seconds_total[1m])` is the
share of a core a server uses. Netdata shows it as a rate by itself.
