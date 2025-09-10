#!/bin/bash
set -e

echo "[Lightshow] Installatie gestart..."

# Systeem bijwerken
sudo apt update
sudo apt upgrade -y

# Vereiste pakketten
sudo apt install -y python3 python3-venv python3-pip git nginx hostapd dnsmasq ola

# Python virtualenv
if [ ! -d venv ]; then
  python3 -m venv venv
fi
source venv/bin/activate
pip install -r requirements.txt

# Nginx configuratie
sudo tee /etc/nginx/sites-available/lightshow <<EOF
server {
    listen 80;
    server_name _;
    root /home/pi/lightshow/web;
    index index.html;
    location /api {
        proxy_pass http://127.0.0.1:5000;
    }
}
EOF

sudo ln -sf /etc/nginx/sites-available/lightshow /etc/nginx/sites-enabled/lightshow
sudo systemctl restart nginx

# Systemd services kopiëren
sudo cp scripts/systemd-lightshow.service /etc/systemd/system/
sudo cp scripts/systemd-launchpad.service /etc/systemd/system/
sudo cp scripts/systemd-midimix.service /etc/systemd/system/

# Autostart inschakelen
sudo systemctl enable systemd-lightshow.service
sudo systemctl enable systemd-launchpad.service
sudo systemctl enable systemd-midimix.service

echo "[Lightshow] Installatie afgerond."