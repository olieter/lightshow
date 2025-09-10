#!/bin/bash
#echo "[Lightshow] Netjes afsluiten..."
#sudo shutdown -h now

sudo tee ~/lightshow/scripts/safe_shutdown.sh >/dev/null <<'EOF'
#!/usr/bin/env bash
sleep 0.5
sudo shutdown -h now
EOF
chmod +x ~/lightshow/scripts/safe_shutdown.sh