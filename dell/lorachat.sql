-- Die Textebene des Krisenkanals: was gefunkt und was gerufen wurde.
--
-- Bewusst eine eigene Tabelle neben `loradevice`. Dort steht, was ein Geraet
-- gesendet hat — mit DevEUI, fPort und Zaehlerstand. Hier steht, was Menschen
-- einander mitgeteilt haben. Das in eine Tabelle zu zwingen hiesse, die
-- Haelfte der Spalten dauerhaft leer zu lassen.
--
-- Zeiten in Ortszeit, wie in den uebrigen Tabellen dieser Datenbank.

CREATE TABLE IF NOT EXISTS lorachat (
  id        BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  ts        DATETIME(3)     NOT NULL,
  richtung  ENUM('raus','rein','status') NOT NULL,
  topic     VARCHAR(255)    NOT NULL,
  text      TEXT            NULL,   -- die Nachricht, wie sie auf dem Topic stand
  meta      LONGTEXT        NULL CHECK (meta IS NULL OR JSON_VALID(meta)),
  PRIMARY KEY (id),
  KEY k_ts (ts),
  KEY k_richtung_ts (richtung, ts)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
