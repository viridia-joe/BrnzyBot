#!/bin/bash
# VM startup script — runs once on first boot after Terraform provisions the machine.
# Installs Docker, creates the brnz user, and sets up directory structure.
set -e

export DEBIAN_FRONTEND=noninteractive

apt-get update -q
apt-get install -y -q docker.io docker-compose-v2 git curl

# Start Docker and enable it to start on reboot
systemctl enable docker
systemctl start docker

# Create the brnz user (matches Jarvis convention)
if ! id -u brnz &>/dev/null; then
  useradd -m -s /bin/bash brnz
fi
usermod -aG docker brnz

# Data and log directories — these are bind-mounted into the containers.
# SQLite databases and cached JSON files live here.
mkdir -p /home/brnz/openclaw-data /home/brnz/openclaw-logs
chown -R brnz:brnz /home/brnz/openclaw-data /home/brnz/openclaw-logs

# Placeholder repo directory — GitHub Actions CI populates this on first deploy.
mkdir -p /home/brnz/brnzybot-git
chown brnz:brnz /home/brnz/brnzybot-git
