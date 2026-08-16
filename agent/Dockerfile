# CYPHER65 WAR ROOM — LOCAL AGENT (SaaS)
# Runs on the USER'S home network (NAS / Raspberry Pi / mini-PC / any
# always-on box). Connects OUT to the Render dashboard — no open ports.
FROM python:3.11-slim

WORKDIR /opt/cypher65-agent

# 100% stdlib — no pip install needed (urllib does HTTP).
COPY agent.py .

ENV CYPHER65_SERVER_URL=""
ENV CYPHER65_AGENT_TOKEN=""
ENV CYPHER65_POLL_INTERVAL="30"

# Host network so the agent can reach 192.168.x.x / 10.x LAN devices.
CMD ["python3", "agent.py"]
