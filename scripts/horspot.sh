#!/bin/bash
set -e

echo "[Lightshow] Configuratie hotspot..."

sudo systemctl stop dnsmasq || true
sudo systemctl stop hostapd || true

# DHCP configuratie
cat <<EOF | sudo tee /etc/dhcpcd.conf
interface wlan0
    static ip_address=192.168.4.1/24
EOF

cat <<EOF | sudo tee /etc/dnsmasq.conf
dhcp-range=192.168.4.2,192.168.4.300,255.255.255.0,24h
# vaste IP's
dhcp-host=AA:BB:CC:DD:EE:FF,192.168.4.100   # iPad
dhcp-host=11:22:33:44:55:66,192.168.4.101   # WLED Guirlande
dhcp-host=22:33:44:55:66:77,192.168.4.102   # WLED Tube L
dhcp-host=33:44:55:66:77:88,192.168.4.103   # WLED Tube R
dhcp-host=44:55:66:77:88:99,192.168.4.104   # Relay
EOF

# Hotspot config
cat <<EOF | sudo tee /etc/hostapd/hostapd.conf
interface=wlan0
ssid=DMX-Control
hw_mode=g
channel=6
wmm_enabled=0
auth_algs=1
wpa=2
wpa_passphrase=dmxwled123
EOF
sudo sed -i 's|#DAEMON_CONF=""|DAEMON_CONF="/etc/hostapd/hostapd.conf"|' /etc/default/hostapd

sudo systemctl unmask hostapd
sudo systemctl enable hostapd
sudo systemctl enable dnsmasq
sudo systemctl restart dhcpcd
sudo systemctl restart dnsmasq
sudo systemctl restart hostapd

echo "[Lightshow] Hotspot actief (SSID=DMX-Control, pass=dmxwled123)."