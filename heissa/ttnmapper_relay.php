<?php
// ttnmapper_relay.php -- sits between the TTN webhook "ttnmapper" (application
// sensorsa) and TTN Mapper. It adds the altitude from the Copernicus GLO-30
// tiles on heissa where an uplink carries latitude/longitude but no altitude
// (the TrackerD sends none), and passes everything else through unchanged.
//
// TTN webhook:  base URL https://heissa.de/web1/ttnmapper_relay.php
//               paths    ?p=uplink-message | ?p=join-accept | ?p=location-solved
//               headers  TTNMAPPERORG-USER, X-Relay-Token (secret below)
// Test without forwarding: append &dry=1 -- answers with the modified message.
//
// The JSON is decoded into objects, not arrays: an empty {} would otherwise
// come back as [] and could break the TTN Mapper parser.

const SECRET_FILE = '/etc/ttnmapper_relay.secret';
const DEM_DIR     = '/home/gh/syncthing/copernicus_cache';
const GDAL        = '/usr/bin/gdallocationinfo';
const TARGET      = 'https://integrations.ttnmapper.org/tts/v3/';
const PATHS       = ['uplink-message', 'join-accept', 'location-solved'];

header('Content-Type: text/plain; charset=utf-8');

if ($_SERVER['REQUEST_METHOD'] !== 'POST') {
    http_response_code(405);
    exit("POST only\n");
}

$secret = trim((string)@file_get_contents(SECRET_FILE));
$token  = $_SERVER['HTTP_X_RELAY_TOKEN'] ?? '';
if ($secret === '' || !hash_equals($secret, $token)) {
    http_response_code(403);
    exit("forbidden\n");
}

$pfad = $_GET['p'] ?? '';
if (!in_array($pfad, PATHS, true)) {
    http_response_code(404);
    exit("unknown path\n");
}

$body = file_get_contents('php://input');
$msg  = json_decode($body);
if (!is_object($msg)) {
    http_response_code(400);
    exit("no JSON object\n");
}

// Ground height in metres from the 1-degree tile, null when unknown.
function dem_hoehe(float $lat, float $lon): ?float {
    if ($lat < 0 || $lon < 0) return null;                  // tiles are N/E only
    $datei = sprintf('%s/N%02d_E%03d.tif', DEM_DIR, (int)floor($lat), (int)floor($lon));
    if (!is_readable($datei)) return null;
    $cmd = sprintf('%s -valonly -wgs84 %s %s %s 2>/dev/null', GDAL,
                   escapeshellarg($datei), escapeshellarg(sprintf('%.6f', $lon)),
                   escapeshellarg(sprintf('%.6f', $lat)));
    $out = trim((string)shell_exec($cmd));
    if ($out === '' || !is_numeric($out)) return null;
    $h = (float)$out;
    if ($h < -500 || $h > 9000) return null;                // NoData and the like
    return round($h, 1);
}

$ergaenzt = null;
if ($pfad === 'uplink-message' && isset($msg->uplink_message->decoded_payload)) {
    $d = $msg->uplink_message->decoded_payload;
    if (is_object($d) && isset($d->latitude, $d->longitude) && !isset($d->altitude)
        && is_numeric($d->latitude) && is_numeric($d->longitude)
        && ($d->latitude != 0 || $d->longitude != 0)) {
        $h = dem_hoehe((float)$d->latitude, (float)$d->longitude);
        if ($h !== null) {
            $d->altitude = $h;
            $ergaenzt = $h;
        }
    }
}

$raus = ($ergaenzt === null) ? $body
      : json_encode($msg, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE | JSON_PRESERVE_ZERO_FRACTION);

if (isset($_GET['dry'])) {
    header('Content-Type: application/json');
    header('X-Relay-Altitude: ' . ($ergaenzt === null ? 'none' : $ergaenzt));
    exit($raus);
}

// TTN Mapper needs more than its own headers: without X-TTS-DOMAIN (set by
// TTN on every webhook call) it answers 400 "Originating network server header
// not set". So everything TTN sends as X-Tts-* / X-Downlink-* goes along, plus
// the User-Agent; only our own token stays here.
$kopf = ['Content-Type: application/json'];
foreach ($_SERVER as $srv => $wert) {
    if (!is_string($wert) || $wert === '') continue;
    if ($srv === 'HTTP_TTNMAPPERORG_USER' || $srv === 'HTTP_TTNMAPPERORG_EXPERIMENT'
        || strpos($srv, 'HTTP_X_TTS_') === 0 || strpos($srv, 'HTTP_X_DOWNLINK_') === 0) {
        $name = str_replace('_', '-', substr($srv, 5));
        $kopf[] = $name . ': ' . $wert;
    }
}
if (!empty($_SERVER['HTTP_USER_AGENT'])) $kopf[] = 'User-Agent: ' . $_SERVER['HTTP_USER_AGENT'];

$ch = curl_init(TARGET . $pfad);
curl_setopt_array($ch, [
    CURLOPT_POST           => true,
    CURLOPT_POSTFIELDS     => $raus,
    CURLOPT_HTTPHEADER     => $kopf,
    CURLOPT_RETURNTRANSFER => true,
    CURLOPT_CONNECTTIMEOUT => 5,
    CURLOPT_TIMEOUT        => 15,
]);
$antwort = curl_exec($ch);
$code    = (int)curl_getinfo($ch, CURLINFO_RESPONSE_CODE);
$fehler  = curl_error($ch);
curl_close($ch);

$dev = $msg->end_device_ids->device_id ?? '?';
error_log(sprintf('ttnmapper_relay: %s %s alt=%s -> HTTP %d %s %s', $pfad, $dev,
                  $ergaenzt === null ? '-' : $ergaenzt, $code, $fehler,
                  $code >= 300 ? substr(preg_replace('/\s+/', ' ', (string)$antwort), 0, 300) : ''));
// The last message per path and device, for replaying a rejected one by hand.
@file_put_contents(sprintf('%s/ttnmapper_relay_%s_%s.json', sys_get_temp_dir(), $pfad,
                           preg_replace('/[^a-z0-9-]/', '', strtolower($dev))), $raus);

if ($antwort === false || $code === 0) {
    http_response_code(502);
    exit("upstream error: $fehler\n");
}
http_response_code($code);
echo $antwort;
