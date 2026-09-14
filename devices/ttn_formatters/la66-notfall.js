// la66-notfall (Dragino LA66 USB, crisis chat over LoRaWAN) -- TTN uplink decoder.
// The chat payload itself is decoded on the dell (dragino_rx.py); here only
// the fixed position is added so the TTN Mapper webhook can place the
// measurement. TTN does not include the registry location in webhook uplinks,
// and TTN Mapper rejects accuracy > 15 m.
// Position: Reiser Alm, Brauneck (47.673528 / 11.542695, 914 m).
function decodeUplink(input) {
  return {
    data: {
      fport: input.fPort,
      laenge: input.bytes.length,
      latitude: 47.673528,
      longitude: 11.542695,
      altitude: 914,
      accuracy: 10
    }
  };
}
