# Home Automation

A collection of home monitoring and automation projects.

## Projects

| Project | Description |
|---|---|
| [power-dashboard](projects/power-dashboard/) | Real-time power balance monitoring in kWh |
| [water-monitor](projects/water-monitor/) | Underground water tank level tracking |
| [solar-battery](projects/solar-battery/) | Solar production and battery State of Charge dashboard |
| [dns-monitor](projects/dns-monitor/) | Live DNS query activity and analytics |
| [lighting-control](projects/lighting-control/) | Shelly device control — room lighting, scenes, schedules, presence |
| [notifications](projects/notifications/) | Shared alerting and notification system |

## Architecture

```
home-automation/
├── projects/           # Individual project modules
├── shared/             # Reusable code (DB, MQTT, utilities)
├── infrastructure/     # Docker, Grafana, InfluxDB, Nginx configs
├── scripts/            # Setup and maintenance scripts
└── docs/               # Architecture diagrams and notes
```

## Stack

- **Data collection**: Python collectors (MQTT / REST / polling)
- **Storage**: InfluxDB (time-series metrics)
- **Dashboards**: Grafana + custom web UIs
- **Broker**: Mosquitto MQTT
- **Deployment**: Docker Compose

## Getting Started

```bash
cp .env.example .env        # Fill in your credentials and IPs
docker compose up -d        # Start all services
```

See each project's `README.md` for individual setup instructions.
