# sysstat-recorder

轻量级系统运行状态记录与可视化工具，支持 Docker 部署。

## 功能

- 📊 **实时采集** — CPU、内存、磁盘、网络、负载、进程数、系统运行时间
- 📈 **趋势图表** — 历史数据可视化（Chart.js 前端）
- 🔝 **Top 进程** — 按 CPU 占用率展示最耗资源的进程
- 🌡️ **温度监控** — 支持传感器温度采集（如可用）
- 💾 **SQLite 存储** — 零依赖数据库，自动清理过期数据
- 🐳 **Docker 一键部署**

## 快速启动

```bash
docker compose up -d --build
```

打开 http://localhost:8080 查看仪表盘。

## 直接运行（无需 Docker）

```bash
pip install -r requirements.txt
# 启动采集器（后台）
python3 collector.py &
# 启动 Web（前台）
python3 app.py
```

## 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `SYSSTAT_DB` | `/data/sysstat.db` | 数据库路径 |
| `SYSSTAT_INTERVAL` | `10` | 采集间隔（秒） |
| `SYSSTAT_RETENTION` | `7` | 数据保留天数 |
| `SYSSTAT_PORT` | `8080` | Web 端口 |
| `SYSSTAT_HOST` | `0.0.0.0` | Web 监听地址 |

## API

- `GET /api/latest` — 最新一条快照
- `GET /api/history?minutes=60` — 最近 N 分钟的历史数据
