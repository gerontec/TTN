-- Rohspeicher fuer alles, was ueber den Broker von LoRaWAN-Geraeten kommt.
--
-- Absichtlich eine Tabelle fuer alle Ereignisarten: up, join, ack, txack,
-- status, log. Was sich sinnvoll herausziehen laesst, steht in eigenen
-- Spalten; der vollstaendige Rahmen bleibt in `raw`, damit spaetere Filter
-- auch an Felder kommen, an die heute niemand denkt.
--
-- Zeiten in Ortszeit, wie in den uebrigen Tabellen dieser Datenbank
-- (Grafana braucht dafuer CONVERT_TZ im SELECT).

CREATE TABLE IF NOT EXISTS loradevice (
  id           BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  ts           DATETIME(3)     NOT NULL,   -- Empfang auf dem Broker
  dev_time     DATETIME(3)     NULL,       -- Zeitstempel aus dem Ereignis
  event        VARCHAR(16)     NOT NULL,   -- up | join | ack | txack | status | log
  topic        VARCHAR(255)    NOT NULL,
  dev_eui      CHAR(16)        NULL,
  dev_name     VARCHAR(100)    NULL,
  application  VARCHAR(100)    NULL,
  f_port       SMALLINT UNSIGNED NULL,
  f_cnt        INT UNSIGNED    NULL,
  confirmed    TINYINT(1)      NULL,
  dr           TINYINT         NULL,
  frequency    INT UNSIGNED    NULL,
  rssi         SMALLINT        NULL,
  snr          FLOAT           NULL,
  gateway_id   CHAR(16)        NULL,
  payload_hex  VARCHAR(1024)   NULL,       -- unentschluesselte Nutzlast, hex
  decoded      LONGTEXT        NULL CHECK (decoded IS NULL OR JSON_VALID(decoded)),
  raw          LONGTEXT        NOT NULL CHECK (JSON_VALID(raw)),
  PRIMARY KEY (id),
  KEY k_ts (ts),
  KEY k_dev_ts (dev_eui, ts),
  KEY k_event_ts (event, ts)
  -- Bewusst *kein* eindeutiger Schluessel auf (dev_eui, f_cnt): der LA66
  -- faengt nach einem Neustart wieder bei 0 an. Ein Unique wuerde die neuen
  -- Uplinks stillschweigend verwerfen — in einem Rohspeicher ist eine
  -- Doublette das kleinere Uebel als eine Luecke.
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
