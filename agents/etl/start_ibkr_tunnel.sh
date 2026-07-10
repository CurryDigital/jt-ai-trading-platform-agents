#!/bin/bash
# Start persistent IBKR SSH tunnel using autossh
# Use: nohup /home/ubuntu/.hermes/profiles/qr_etl/home/trading-platform/agents/etl/start_ibkr_tunnel.sh > /tmp/ibkr_tunnel.log 2>&1 &
# Or via systemd/cron.

export AUTOSSH_PORT=0
export AUTOSSH_POLL=30
export AUTOSSH_GATETIME=0

LOCAL_PORT=14002
REMOTE_HOST=127.0.0.1
REMOTE_PORT=4002
EC2_HOST=52.74.14.181
EC2_USER=ubuntu
EC2_KEY=/home/ubuntu/.ssh/ibkr_ec2.pem

exec autossh -M 0 \
  -o "ServerAliveInterval=15" \
  -o "ServerAliveCountMax=3" \
  -o "ExitOnForwardFailure=yes" \
  -o "StrictHostKeyChecking=no" \
  -N -L ${LOCAL_PORT}:${REMOTE_HOST}:${REMOTE_PORT} \
  -i ${EC2_KEY} \
  ${EC2_USER}@${EC2_HOST}
