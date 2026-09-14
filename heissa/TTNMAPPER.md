# TTN Mapper über heissa.de

Die Anwendung `sensorsa` bei TTN schickt ihre Uplinks nicht direkt an TTN
Mapper, sondern über `ttnmapper_relay.php` auf heissa. Die Weiterleitung
ergänzt die Höhe, wo ein Uplink Koordinaten, aber keine Höhe trägt (der
TrackerD sendet keine), und reicht alles andere unverändert durch.

    TTN Webhook "ttnmapper"  ->  https://heissa.de/web1/ttnmapper_relay.php
                             ->  https://integrations.ttnmapper.org/tts/v3/<pfad>

Die Decoder, die die Koordinaten liefern, liegen in
[`../devices/ttn_formatters/`](../devices/ttn_formatters/).

## Einrichten

**Weiterleitung** (docroot gehört www-data, daher per sudo):

    sudo install -o root -g root -m 644 ttnmapper_relay.php /var/www/web1/ttnmapper_relay.php
    sudo sh -c 'umask 027; openssl rand -hex 24 > /etc/ttnmapper_relay.secret'
    sudo chown root:www-data /etc/ttnmapper_relay.secret; sudo chmod 640 /etc/ttnmapper_relay.secret

**Höhe:** `gdallocationinfo` (Paket `gdal-bin`) liest die Copernicus-GLO-30-Kacheln
`/home/gh/syncthing/copernicus_cache/N47_E011.tif` usw. rasterio geht hier nicht:
es liegt nur in `~/.local` von gh, php-fpm läuft als www-data.

**TTN-Webhook** `ttnmapper` in `sensorsa`:

| Feld | Wert |
|---|---|
| Base URL | `https://heissa.de/web1/ttnmapper_relay.php` |
| Format | JSON |
| Header | `TTNMAPPERORG-USER: <E-Mail>`, `X-Relay-Token: <Inhalt von /etc/ttnmapper_relay.secret>` |
| Uplink message | `?p=uplink-message` |
| Join accept | `?p=join-accept` |
| Location solved | `?p=location-solved` |

Die Pfade gehen als Query-Parameter, damit es nicht darauf ankommt, ob der
Webserver PATH_INFO weiterreicht.

**Testen ohne Weiterleitung:** `&dry=1` anhängen — die Antwort ist die
veränderte Nachricht, der Header `X-Relay-Altitude` zeigt die ergänzte Höhe.

## Fallen, die Zeit gekostet haben

- **`X-Tts-Domain` muss mit.** TTN setzt den Header bei jedem Webhook-Aufruf;
  fehlt er, antwortet TTN Mapper `400 Originating network server header not
  set`. Die Weiterleitung reicht deshalb alle `X-Tts-*`/`X-Downlink-*` und den
  User-Agent durch, nur das eigene Token nicht.
- **Direkt an TTN Mapper braucht es den Pfad `/uplink-message`** — ohne Pfad
  gibt es HTTP 405 und der Webhook wird `unhealthy`.
- **Abgelehnt heißt HTTP 200, angenommen 202.** Die Plausibilitätsprüfung
  (`CheckData` in ttnmapper/ingress-api) verwirft still bei `hdop > 5`,
  `accuracy > 15`, `sats < 4` und Koordinaten 0/0 oder lat = lon.
- **Der Registerstandort eines Geräts kommt im Webhook nicht mit**
  (`uplink_message.locations` fehlt) — Geräte ohne GPS brauchen die Position
  im Decoder.
- **JSON als Objekte decodieren**, sonst wird aus `{}` beim Neuschreiben `[]`.

Protokoll: `heissa_error.log` (Zeilen `ttnmapper_relay:` mit Code und bei
Fehlern der Antwort), die letzte Nachricht je Pfad und Gerät unter
`/tmp/ttnmapper_relay_<pfad>_<gerät>.json`.
