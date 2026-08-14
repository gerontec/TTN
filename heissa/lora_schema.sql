-- LoRaWAN-Uplinks aus dem Gateway Lenggries, angelegt 14.08.2026.
--
-- Zwei Ebenen mit Absicht: `raw` haelt die komplette TTN-Nachricht, damit auch
-- Felder erhalten bleiben, an die beim Anlegen niemand gedacht hat. `decoded`
-- ist der Decoder-Output. Die Einzelspalten daneben sind nur Spiegel der
-- haeufig gebrauchten Werte, damit Grafana und SQL nicht jedes Mal JSON
-- auspacken muessen.

CREATE TABLE IF NOT EXISTS lora_uplinks (
    id              BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    received_at     DATETIME(3)     NOT NULL,
    app_id          VARCHAR(64)     NOT NULL,
    device_id       VARCHAR(64)     NOT NULL,
    dev_eui         CHAR(16)        NOT NULL,
    f_port          SMALLINT UNSIGNED,
    f_cnt           INT UNSIGNED,
    payload_hex     VARCHAR(510),

    -- Decoder-Werte (TrackerD, fPort 2/3/4/5/6/7/8)
    latitude        DECIMAL(10,6),
    longitude       DECIMAL(10,6),
    battery_v       DECIMAL(5,3),
    alarm           TINYINT(1),
    md              TINYINT UNSIGNED,       -- Betriebsmodus
    led_on          TINYINT(1),
    transport       VARCHAR(8),             -- MOVE / STILL
    temperature     DECIMAL(5,1),
    humidity        DECIMAL(5,1),
    firmware        VARCHAR(16),
    freq_band       VARCHAR(16),
    smode           VARCHAR(24),            -- GPS / BLE / Spots / Hybrid
    wifi_ssid       VARCHAR(32),
    beacon_uuid     VARCHAR(64),

    -- Funkmetadaten des am besten empfangenden Gateways
    gateway_eui     CHAR(16),
    rssi            SMALLINT,
    snr             DECIMAL(5,2),
    spreading_factor TINYINT UNSIGNED,
    bandwidth       INT UNSIGNED,
    frequency       BIGINT UNSIGNED,
    airtime_ms      DECIMAL(8,2),

    decoded         JSON,
    raw             JSON            NOT NULL,

    PRIMARY KEY (id),
    -- Ein Uplink kann ueber mehrere Gateways hereinkommen; TTN dedupliziert,
    -- ein Neustart der Bruecke darf aber trotzdem nichts doppelt schreiben.
    UNIQUE KEY uq_uplink (dev_eui, f_cnt, received_at),
    KEY idx_dev_time (dev_eui, received_at),
    KEY idx_time (received_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Join-Vorgaenge getrennt mitschreiben: solange ein Geraet nicht sauber
-- beitritt, ist das hier die einzige Spur, die es hinterlaesst.
CREATE TABLE IF NOT EXISTS lora_joins (
    id          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    received_at DATETIME(3)     NOT NULL,
    app_id      VARCHAR(64)     NOT NULL,
    device_id   VARCHAR(64)     NOT NULL,
    dev_eui     CHAR(16)        NOT NULL,
    join_eui    CHAR(16),
    dev_addr    CHAR(8),
    gateway_eui CHAR(16),
    rssi        SMALLINT,
    snr         DECIMAL(5,2),
    raw         JSON            NOT NULL,
    PRIMARY KEY (id),
    KEY idx_dev_time (dev_eui, received_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

SHOW TABLES LIKE 'lora%';
