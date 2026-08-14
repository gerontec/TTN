#!/bin/bash
# Lokaler LoRaWAN-Netzserver auf dem dell (192.168.5.23).
#
# Zweck ist der Krisenfall: faellt das Internet aus, ist ipgate1 nicht mehr
# erreichbar und heissa.de damit auch nicht. Der Pfad Gateway -> dell laeuft
# direkt ueber das LAN und braucht weder WireGuard noch Internet.
#
# PostgreSQL 18 ist vorhanden, Port 8080 ist belegt -> ChirpStack auf 8090.
set -e

echo "=== Repository ==="
sudo install -d -m 0755 /etc/apt/keyrings
curl -fsSL https://artifacts.chirpstack.io/packages/chirpstack.key \
  | sudo gpg --dearmor --yes -o /etc/apt/keyrings/chirpstack.gpg
echo "deb [signed-by=/etc/apt/keyrings/chirpstack.gpg] https://artifacts.chirpstack.io/packages/4.x/deb stable main" \
  | sudo tee /etc/apt/sources.list.d/chirpstack.list >/dev/null
sudo apt-get update -qq

echo "=== Pakete ==="
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
  redis-server mosquitto mosquitto-clients chirpstack chirpstack-gateway-bridge

echo "=== Datenbank ==="
DBPW=$(openssl rand -base64 24 | tr -d '/+=' | head -c 24)
sudo -u postgres psql -v ON_ERROR_STOP=0 <<SQL
create role chirpstack with login password '${DBPW}';
create database chirpstack with owner chirpstack;
SQL
sudo -u postgres psql -d chirpstack -c 'create extension if not exists pg_trgm;'
sudo -u postgres psql -d chirpstack -c 'create extension if not exists hstore;'

sudo install -d -m 0700 -o gh -g gh /home/gh/.config/chirpstack
umask 077
printf 'CHIRPSTACK_DB_PASSWORD=%s\nCHIRPSTACK_URL=http://192.168.5.23:8090\n' "$DBPW" \
  > /home/gh/.config/chirpstack/db.env
chmod 600 /home/gh/.config/chirpstack/db.env

echo "=== mosquitto ==="
# Nur im LAN erreichbar; der Broker traegt im Krisenfall die Notfall-Nachrichten.
sudo tee /etc/mosquitto/conf.d/lora.conf >/dev/null <<'CONF'
listener 1883 0.0.0.0
allow_anonymous true
CONF
sudo systemctl enable --now mosquitto

echo "=== chirpstack.toml ==="
sudo sed -i \
  -e "s|^\s*dsn=.*|  dsn=\"postgres://chirpstack:${DBPW}@localhost/chirpstack?sslmode=disable\"|" \
  /etc/chirpstack/chirpstack.toml
# Port 8080 gehoert schon einem anderen Dienst auf diesem Rechner.
sudo sed -i -e 's|^\s*bind=.*"0.0.0.0:8080".*|  bind="0.0.0.0:8090"|' \
            -e 's|^\s*bind="0.0.0.0:8080"|  bind="0.0.0.0:8090"|' \
  /etc/chirpstack/chirpstack.toml
grep -nE '^\s*(bind|dsn)=' /etc/chirpstack/chirpstack.toml | sed 's|://chirpstack:[^@]*@|://chirpstack:<PW>@|'

echo "=== gateway-bridge ==="
# Der Semtech-UDP-Forwarder des Gateways sendet direkt ins LAN.
sudo tee /etc/chirpstack-gateway-bridge/chirpstack-gateway-bridge.toml >/dev/null <<'CONF'
[backend]
type="semtech_udp"

  [backend.semtech_udp]
  udp_bind = "0.0.0.0:1700"

[integration]
marshaler="json"

  [integration.mqtt]
  event_topic_template="eu868/gateway/{{ .GatewayID }}/event/{{ .EventType }}"
  state_topic_template="eu868/gateway/{{ .GatewayID }}/state/{{ .StateType }}"
  command_topic_template="eu868/gateway/{{ .GatewayID }}/command/#"

    [integration.mqtt.auth.generic]
    servers=["tcp://127.0.0.1:1883"]
CONF

echo "=== Start ==="
sudo systemctl enable --now redis-server chirpstack-gateway-bridge chirpstack
sleep 8
for s in redis-server mosquitto chirpstack-gateway-bridge chirpstack; do
  printf '%-30s %s\n' "$s" "$(systemctl is-active $s)"
done
echo "=== Ports ==="
ss -lntu | grep -E ':(1700|1883|8090)' || true
echo "=== ChirpStack-Log ==="
journalctl -u chirpstack -n 12 --no-pager | tail -12
