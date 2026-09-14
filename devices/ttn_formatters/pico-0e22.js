// pico-0e22 (Raspberry Pi Pico + SX1262, e22pico firmware) -- TTN uplink decoder.
// fPort 1: status, big endian. Version 1 = 10 bytes, version 2 (fw v2.2.0) = 16 bytes.
// fPort 20: repeater report (MODE_REPEAT_ID), passed through as hex.
function decodeUplink(input) {
  var b = input.bytes;
  var s8 = function (v) { return v > 127 ? v - 256 : v; };
  var hex = function (a) {
    return a.map(function (x) { return ('0' + x.toString(16)).slice(-2); }).join('');
  };

  if (input.fPort === 1 && b.length >= 10) {
    var d = {
      version: b.length >= 16 ? 2 : 1,
      laufzeit_min: (b[0] << 8) | b[1],
      roh_empfangen: (b[2] << 8) | b[3],
      roh_beantwortet: (b[4] << 8) | b[5],
      roh_rssi_dbm: s8(b[6]),
      roh_snr_db: s8(b[7]),
      adc_mv: (b[8] << 8) | b[9]
    };
    d.adc_v = Math.round(d.adc_mv) / 1000;
    // Stationary node without GPS: fixed position for the TTN Mapper
    // integration (needs lowercase latitude/longitude/altitude plus an
    // accuracy indicator). Position: Brauneck-Gipfelhaus (DAV), 1550 m.
    d.latitude = 47.664217;
    d.longitude = 11.524835;
    d.altitude = 1550;
    d.accuracy = 10;   // TTN Mapper rejects accuracy > 15 m
    if (b.length >= 16) {
      if (b[10] !== 0x80) {
        d.gw_rssi_dbm = s8(b[10]);
        d.gw_snr_db = s8(b[11]) / 4;
        d.gw_alter_min = b[12];
      }
      if (b[13] !== 0xFF) {
        d.linkcheck_margin_db = b[13];
        d.linkcheck_gateways = b[14];
      }
      d.intervall_min = b[15];
    }
    return { data: d };
  }

  if (input.fPort === 20) {
    return { data: { repeater_bericht_hex: hex(b), laenge: b.length } };
  }

  return { data: { fport: input.fPort, roh_hex: hex(b) } };
}
