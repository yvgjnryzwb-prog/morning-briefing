<?php
// Startet den Build des Morning-Briefings (GitHub Actions), höchstens alle 5 Minuten.
// Wird von der Briefing-Seite beim Öffnen aufgerufen. Der GitHub-Schlüssel steht in
// aktualisieren-token.php im selben Ordner (siehe README) und verlässt den Server nie.

const REPO = 'yvgjnryzwb-prog/morning-briefing';
const WORKFLOW = 'news-dashboard.yml';
const ORIGIN = 'https://yvgjnryzwb-prog.github.io';
const COOLDOWN = 300; // Sekunden

// PHP-Warnungen nicht in die Antwort schreiben – die Seite erwartet reines JSON.
ini_set('display_errors', '0');

header('Access-Control-Allow-Origin: ' . (getenv('BRIEFING_TEST_ORIGIN') ?: ORIGIN));
header('Access-Control-Allow-Methods: POST, OPTIONS');
header('Content-Type: application/json; charset=utf-8');
header('Cache-Control: no-store');
if ($_SERVER['REQUEST_METHOD'] === 'OPTIONS') { http_response_code(204); exit; }
if ($_SERVER['REQUEST_METHOD'] === 'GET') {
    // Selbsttest im Browser: zeigt nur Ja/Nein-Werte, nie den Schlüssel.
    $tokenFile = __DIR__ . '/aktualisieren-token.php';
    $token = is_readable($tokenFile) ? (include $tokenFile) : '';
    echo json_encode([
        'skript' => 'ok',
        'php' => PHP_VERSION,
        'token_datei_da' => is_readable($tokenFile),
        'token_eingetragen' => is_string($token) && strpos($token, 'github_pat_') === 0
                               && strpos($token, 'HIER_DEN') === false,
        'ordner_beschreibbar' => is_writable(__DIR__),
        'url_abruf_erlaubt' => (bool) ini_get('allow_url_fopen'),
    ], JSON_PRETTY_PRINT);
    exit;
}
if ($_SERVER['REQUEST_METHOD'] !== 'POST') { http_response_code(405); echo '{"error":"POST"}'; exit; }

$stamp = __DIR__ . '/.briefing-letzter-start';
$fp = @fopen($stamp, 'c+');
if (!$fp || !flock($fp, LOCK_EX)) { http_response_code(500); echo '{"error":"lock"}'; exit; }
$last = (int) stream_get_contents($fp);
$since = time() - $last;
if ($since < COOLDOWN) {
    flock($fp, LOCK_UN);
    echo json_encode(['started' => false, 'since' => $since]);
    exit;
}

$tokenFile = __DIR__ . '/aktualisieren-token.php';
if (!is_readable($tokenFile)) { flock($fp, LOCK_UN); http_response_code(500); echo '{"error":"token"}'; exit; }
$token = trim((string) (include $tokenFile));
$ctx = stream_context_create(['http' => [
    'method' => 'POST',
    'header' => "Authorization: Bearer $token\r\n"
              . "Accept: application/vnd.github+json\r\n"
              . "X-GitHub-Api-Version: 2022-11-28\r\n"
              . "User-Agent: morning-briefing\r\n"
              . "Content-Type: application/json\r\n",
    'content' => json_encode(['ref' => 'main']),
    'ignore_errors' => true,
    'timeout' => 15,
]]);
@file_get_contents((getenv('BRIEFING_TEST_API') ?: 'https://api.github.com') . '/repos/' . REPO . '/actions/workflows/' . WORKFLOW . '/dispatches', false, $ctx);
$status = 0;
if (isset($http_response_header[0]) && preg_match('/\s(\d{3})\s?/', $http_response_header[0], $m)) {
    $status = (int) $m[1];
}
if ($status === 204) {
    ftruncate($fp, 0); rewind($fp); fwrite($fp, (string) time());
}
flock($fp, LOCK_UN);
echo json_encode(['started' => $status === 204, 'status' => $status, 'since' => $since]);
