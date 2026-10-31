<?php
/**
 * Front-end Web em PHP do Link Extractor (baseado em step5/step6 de ibnesayeed/linkextractor).
 *
 *   GET /?url=<url>              -> Interface HTML completa com resumo por domínio e lista de links
 *   GET /?url=<url>&formato=json -> Resposta JSON repassada da API
 *   GET /?health                 -> Verificação de saúde do front-end
 */
$api_endpoint = getenv('API_ENDPOINT');
if (!$api_endpoint) {
    $api_base = rtrim(getenv('API_URL') ?: 'http://api:5000', '/');
    $api_endpoint = $api_base . '/api/';
}

if (isset($_GET['health'])) {
    header('Content-Type: application/json');
    echo json_encode(['status' => 'ok', 'frontend' => 'php', 'api_endpoint' => $api_endpoint]);
    exit;
}

$url = trim($_GET['url'] ?? '');
$links = null;
$domainct = [];
$err = null;
$cache_status = '-';

if ($url !== '') {
    $api_root = preg_replace('#/api/?$#', '', $api_endpoint);
    $ch = curl_init($api_root . '/api?url=' . urlencode($url));
    curl_setopt_array($ch, [
        CURLOPT_RETURNTRANSFER => true,
        CURLOPT_CONNECTTIMEOUT => 3,
        CURLOPT_TIMEOUT        => 10,
        CURLOPT_HEADER         => true,
    ]);
    $raw = curl_exec($ch);
    $http_code = (int) curl_getinfo($ch, CURLINFO_HTTP_CODE);
    $hdr_size = (int) curl_getinfo($ch, CURLINFO_HEADER_SIZE);
    $curl_err = curl_error($ch);
    curl_close($ch);

    if ($raw === false) {
        $http_code = 504;
        $err = "Falha ao contatar o serviço de extração: " . $curl_err;
    } else {
        $headers_str = substr($raw, 0, $hdr_size);
        $body_str = substr($raw, $hdr_size);
        if (preg_match('/^X-Cache:\s*(\S+)/mi', $headers_str, $m)) {
            $cache_status = $m[1];
        }
        $decoded = json_decode($body_str, true);
        if ($http_code === 200 && is_array($decoded)) {
            $links = [];
            $domains = [];
            foreach ($decoded as $item) {
                if (is_array($item) && isset($item['href'])) {
                    $href = (string) $item['href'];
                    $text = (string) ($item['text'] ?? $href);
                } else {
                    $href = (string) $item;
                    $text = $href;
                }
                $links[] = ['text' => $text, 'href' => $href];
                $host = parse_url($href, PHP_URL_HOST);
                if ($host) {
                    $domains[] = $host;
                }
            }
            $domainct = @array_count_values($domains);
            arsort($domainct);
        } else {
            $msg = (is_array($decoded) && isset($decoded['error'])) ? $decoded['error'] : "HTTP $http_code";
            $err = "Erro ao extrair links de $url ($msg)";
        }
    }

    if ($err !== null) {
        http_response_code($http_code >= 400 ? $http_code : 502);
    }
    if (($_GET['formato'] ?? '') === 'json') {
        header('Content-Type: application/json');
        header('X-Cache: ' . $cache_status);
        echo $err === null ? json_encode($links) : json_encode(['error' => $err]);
        exit;
    }
}
?>
<!DOCTYPE html>
<html lang="pt-BR">
  <head>
    <meta charset="utf-8">
    <title>Link Extractor</title>
    <style media="screen">
      html { background: #EAE7D6; font-family: sans-serif; }
      body { margin: 0; }
      h1 { padding: 10px; margin: 0 auto; color: #EAE7D6; max-width: 700px; }
      h1 a { text-decoration: none; color: #EAE7D6; }
      h2 { background: #082E41; color: #EAE7D6; margin: -10px; padding: 10px; }
      p { margin: 25px 5px 5px; }
      section { max-width: 700px; margin: 10px auto; padding: 10px; border: 1px solid #082E41; background: #F7F5EC; }
      div.header { background: #082E41; margin: 0; }
      div.footer { background: #082E41; margin: 20px 0 0; padding: 8px; }
      .footer p { margin: 0 auto; max-width: 700px; color: #EAE7D6; text-align: center; }
      .footer p a { color: #24C2CB; text-decoration: none; }
      .error { color: #DA2536; font-weight: bold; }
      .badge { display: inline-block; padding: 2px 8px; background: #082E41; color: #EAE7D6; border-radius: 4px; font-size: 12px; }
      form { display: flex; gap: 6px; }
      input { font-size: 18px; padding: 4px 8px; height: 40px; }
      input.text { box-sizing: border-box; flex-grow: 1; border: 1px solid #082E41; }
      input.button { width: 160px; background: #082E41; border: 1px solid #082E41; color: #EAE7D6; cursor: pointer; }
      table { width: 100%; text-align: left; margin-top: 10px; border-collapse: collapse; }
      table th, table td { padding: 4px 6px; }
      table th:last-child, table td:last-child { width: 90px; text-align: right; }
      table th { border-top: 1px solid #082E41; border-bottom: 1px solid #082E41; }
      table tr:last-child td { border-top: 1px solid #082E41; border-bottom: 1px solid #082E41; }
    </style>
  </head>
  <body>
    <div class="header">
      <h1><a href="/">Link Extractor</a></h1>
    </div>

    <section>
      <form action="/" method="get">
        <input class="text" type="text" name="url" placeholder="https://www.python.org/" value="<?= htmlspecialchars($url) ?>">
        <input class="button" type="submit" value="Extract Links">
      </form>
    </section>

    <?php if ($err !== null): ?>
      <section>
        <h2>Error</h2>
        <p id="erro" class="error"><?= htmlspecialchars($err) ?></p>
      </section>
    <?php endif; ?>

    <?php if ($url !== '' && $err === null && $links !== null): ?>
      <section>
        <h2>Summary</h2>
        <p id="resumo">
          <strong>Page:</strong> <a href="<?= htmlspecialchars($url) ?>"><?= htmlspecialchars($url) ?></a>
          &nbsp;<span class="badge">Cache: <?= htmlspecialchars($cache_status) ?></span>
        </p>
        <table>
          <tr>
            <th>Domain</th>
            <th># Links</th>
          </tr>
          <?php foreach ($domainct as $domain => $count): ?>
            <tr>
              <td><?= htmlspecialchars((string) $domain) ?></td>
              <td><?= (int) $count ?></td>
            </tr>
          <?php endforeach; ?>
          <tr>
            <td><strong>Total</strong></td>
            <td><strong><?= count($links) ?></strong></td>
          </tr>
        </table>
      </section>

      <section>
        <h2>Links</h2>
        <ul id="links">
          <?php foreach ($links as $link): ?>
            <li><a href="<?= htmlspecialchars($link['href']) ?>"><?= htmlspecialchars($link['text']) ?></a></li>
          <?php endforeach; ?>
        </ul>
      </section>
    <?php endif; ?>

    <div class="footer">
      <p><a href="https://github.com/ibnesayeed/linkextractor">Link Extractor</a> &mdash; Trabalho 4 (Testes de Desempenho com Locust, Python vs Ruby, Redis Cache)</p>
    </div>
  </body>
</html>
