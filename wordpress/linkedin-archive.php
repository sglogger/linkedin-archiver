<?php
/**
 * Plugin Name: LinkedIn Archive Feed
 * Description: Zeigt freigegebene Beiträge aus dem eigenen LinkedIn-Archiv über [linkedin_archive] an.
 * Version: 2.6.0
 */

if (!defined('ABSPATH')) {
    exit;
}

/**
 * Optionale Konstanten in wp-config.php:
 *
 *   define('LINKEDIN_ARCHIVE_API_BASE',     'https://linkedinapi.glogger.ch');
 *   define('LINKEDIN_ARCHIVE_AUTHOR_NAME',  'Steven Glogger');
 *   define('LINKEDIN_ARCHIVE_AUTHOR_IMAGE', 'https://www.glogger.ch/wp-content/uploads/steven.jpg');
 *   define('LINKEDIN_ARCHIVE_AUTHOR_URL',   'https://www.linkedin.com/in/steven-glogger/');
 *
 * Name und Profilbild stehen bewusst hier: Die Archiv-API liefert sie nicht.
 * Sie speichert nur die eigenen Beiträge, keine Profilbilder — alle Beiträge
 * stammen ohnehin von derselben Person.
 */

const LINKEDIN_ARCHIVE_HASHTAG_BASE = 'https://www.linkedin.com/feed/hashtag/?keywords=';

/**
 * Initialen als Rückfall, wenn kein Profilbild konfiguriert ist.
 *
 * Besser ein gefüllter Kreis mit Initialen als eine Lücke, wo das Bild hingehört.
 */
function linkedin_archive_initials($name) {
    $letters = '';
    foreach (preg_split('/\s+/u', trim($name), -1, PREG_SPLIT_NO_EMPTY) as $word) {
        $letters .= function_exists('mb_substr') ? mb_substr($word, 0, 1) : substr($word, 0, 1);
        if (strlen($letters) >= 2) {
            break;
        }
    }
    return function_exists('mb_strtoupper') ? mb_strtoupper($letters) : strtoupper($letters);
}

/**
 * Wert aus Shortcode-Attribut, sonst Konstante, sonst Vorgabe.
 */
function linkedin_archive_setting($value, $constant, $default = '') {
    if ('' !== trim((string) $value)) {
        return trim((string) $value);
    }
    if (defined($constant) && '' !== trim((string) constant($constant))) {
        return trim((string) constant($constant));
    }
    return $default;
}

/**
 * Grammatikalisch korrektes «vor 3 Tagen».
 *
 * human_time_diff() liefert im Deutschen den Nominativ («3 Tage»), was nach
 * «vor» falsch wäre. Deshalb eine eigene, kurze Umsetzung.
 */
function linkedin_archive_relative_time($timestamp) {
    $seconds = time() - (int) $timestamp;
    if ($seconds < 0) {
        return '';
    }
    if ($seconds < 60) {
        return 'gerade eben';
    }
    $units = array(
        array(60,       'Minute',  'Minuten'),
        array(3600,     'Stunde',  'Stunden'),
        array(86400,    'Tag',     'Tagen'),
        array(604800,   'Woche',   'Wochen'),
        array(2592000,  'Monat',   'Monaten'),
        array(31536000, 'Jahr',    'Jahren'),
    );
    $chosen = $units[0];
    foreach ($units as $unit) {
        if ($seconds >= $unit[0]) {
            $chosen = $unit;
        }
    }
    $count = (int) floor($seconds / $chosen[0]);
    return sprintf('vor %d %s', $count, 1 === $count ? $chosen[1] : $chosen[2]);
}

/**
 * Kompakte Zeitangabe oben rechts, wie LinkedIn sie selbst verwendet:
 * 5m, 3h, 25d, 2w, 3mo, 1y. Das ausgeschriebene Datum steht im title-Attribut.
 */
function linkedin_archive_short_time($timestamp) {
    $seconds = time() - (int) $timestamp;
    if ($seconds < 0) {
        return '';
    }
    // Ohne Wochenstufe: LinkedIn zählt den ersten Monat in Tagen durch (25d, 31d)
    // und wechselt erst danach auf Monate.
    foreach (array(
        array(31536000, 'y'),
        array(2592000,  'mo'),
        array(86400,    'd'),
        array(3600,     'h'),
        array(60,       'm'),
    ) as $unit) {
        if ($seconds >= $unit[0]) {
            return ((int) floor($seconds / $unit[0])) . $unit[1];
        }
    }
    return 'jetzt';
}

/**
 * Verlinkt nackte URLs und #hashtags im Fliesstext.
 *
 * Beides in EINEM Durchgang, damit der Fragmentbezeichner einer URL
 * (…/seite#oben) nicht anschliessend als Hashtag missdeutet wird.
 *
 * Läuft nur über Textabschnitte ausserhalb von <a>-Elementen, damit bereits
 * echte Links aus der Beitragsseite nicht verschachtelt werden. Nicht
 * angereicherte Beiträge liefern ihren Text ohne jeden Anker — dort entstehen
 * die Links erst hier.
 */
function linkedin_archive_linkify($text) {
    return preg_replace_callback(
        '~(?<![\w&#])(?:(https?://[^\s<>"\'()\[\]]+)|\#([\p{L}\p{N}_]{2,80}))~u',
        function ($matches) {
            if (isset($matches[1]) && '' !== $matches[1]) {
                // Der Textabschnitt ist bereits HTML-kodiert: &amp; zurück in &,
                // sonst landet ein kaputter Query-String im href.
                $url = html_entity_decode($matches[1], ENT_QUOTES, 'UTF-8');
                // Satzzeichen direkt hinter der URL gehören nicht zum Link.
                $clean = rtrim($url, '.,;:!?\'"«»');
                $tail = substr($url, strlen($clean));
                return '<a class="li-archive-link" href="' . esc_url($clean)
                    . '" target="_blank" rel="noopener noreferrer nofollow">'
                    . esc_html($clean) . '</a>' . esc_html($tail);
            }
            $url = LINKEDIN_ARCHIVE_HASHTAG_BASE . rawurlencode($matches[2]);
            return '<a class="li-archive-hashtag" href="' . esc_url($url)
                . '" target="_blank" rel="noopener noreferrer nofollow">#'
                . esc_html($matches[2]) . '</a>';
        },
        $text
    );
}

/**
 * Ergänzt target="_blank" an einem <a>-Starttag, ohne vorhandene zu überschreiben.
 */
function linkedin_archive_open_in_new_tab($tag) {
    if (!preg_match('#\starget\s*=#i', $tag)) {
        $tag = preg_replace('#^<a\b#i', '<a target="_blank"', $tag, 1);
    }
    if (!preg_match('#\srel\s*=#i', $tag)) {
        $tag = preg_replace('#^<a\b#i', '<a rel="noopener noreferrer"', $tag, 1);
    }
    return $tag;
}

/**
 * Bereitet content_html für die Anzeige auf: Links in neuem Fenster, Hashtags
 * verlinkt. Zerlegt das HTML an den Tags, statt mit einem Ausdruck über das
 * gesamte Markup zu gehen — so werden Attributwerte nie angefasst.
 */
function linkedin_archive_prepare_content($html) {
    $parts = preg_split('/(<[^>]*>)/', $html, -1, PREG_SPLIT_DELIM_CAPTURE);
    if (!is_array($parts)) {
        return $html;
    }
    $anchor_depth = 0;
    $result = '';
    foreach ($parts as $part) {
        if ('' === $part) {
            continue;
        }
        if ('<' === $part[0]) {
            if (preg_match('#^<a\b#i', $part)) {
                $anchor_depth++;
                $part = linkedin_archive_open_in_new_tab($part);
            } elseif (preg_match('#^</a\b#i', $part)) {
                $anchor_depth = max(0, $anchor_depth - 1);
            }
            $result .= $part;
            continue;
        }
        $result .= $anchor_depth > 0 ? $part : linkedin_archive_linkify($part);
    }
    return $result;
}

/**
 * Graue Strich-Icons für Reaktionen und Kommentare.
 *
 * Emoji (👍 💬) bringen ihre Farbe aus der Systemschrift mit und lassen sich
 * per CSS nicht entfärben. Diese SVGs erben über currentColor die Textfarbe
 * der Fussleiste.
 */
function linkedin_archive_stat_icon($name) {
    $paths = array(
        'like' => 'M2 20h2.5V9H2v11zm19.8-9.2c0-.9-.8-1.7-1.7-1.7h-5.3l.8-3.8v-.3c0-.4-.1-.7-.4-.9L14.3 3 8.6 8.7c-.3.3-.5.7-.5 1.2v8.4c0 .9.8 1.7 1.7 1.7h7.6c.7 0 1.3-.4 1.6-1l2.6-6c.1-.2.1-.4.1-.6v-1.6z',
        'repost' => 'M6.5 4h9.6l-2-2 1.4-1.4L19.9 5l-4.4 4.4-1.4-1.4 2-2H6.5c-1.4 0-2.5 1.1-2.5 2.5V12H2V8.5C2 6 4 4 6.5 4zm11 6H22v3.5c0 2.5-2 4.5-4.5 4.5H7.9l2 2-1.4 1.4L4.1 17l4.4-4.4 1.4 1.4-2 2h9.6c1.4 0 2.5-1.1 2.5-2.5V10z',
        'comment' => 'M12 2.5C6.5 2.5 2 6.2 2 10.8c0 2.5 1.3 4.8 3.4 6.3v4.4l4-2.6c.8.2 1.7.3 2.6.3 5.5 0 10-3.7 10-8.4S17.5 2.5 12 2.5z',
    );
    if (!isset($paths[$name])) {
        return '';
    }
    return '<svg class="li-archive-stat-icon" viewBox="0 0 24 24" width="16" height="16" '
        . 'aria-hidden="true" focusable="false"><path fill="currentColor" d="'
        . $paths[$name] . '"/></svg>';
}

function linkedin_archive_logo_svg() {
    return '<svg class="li-archive-logo" viewBox="0 0 24 24" width="28" height="28" '
        . 'role="img" aria-hidden="true" focusable="false"><path fill="currentColor" d="'
        . 'M20.447 20.452h-3.554v-5.569c0-1.328-.027-3.037-1.852-3.037-1.853 0-2.136 1.445-2.136 '
        . '2.939v5.667H9.351V9h3.414v1.561h.046c.477-.9 1.637-1.85 3.37-1.85 3.601 0 4.267 2.37 '
        . '4.267 5.455v6.286zM5.337 7.433c-1.144 0-2.063-.926-2.063-2.065 0-1.138.92-2.063 '
        . '2.063-2.063 1.14 0 2.064.925 2.064 2.063 0 1.139-.925 2.065-2.064 2.065zm1.782 '
        . '13.019H3.555V9h3.564v11.452zM22.225 0H1.771C.792 0 0 .774 0 1.729v20.542C0 23.227.792 '
        . '24 1.771 24h20.451C23.2 24 24 23.227 24 22.271V1.729C24 .774 23.2 0 22.225 0z"/></svg>';
}

add_shortcode('linkedin_archive', function ($attributes) {
    $options = shortcode_atts(array(
        'limit'   => 12,
        'columns' => 2,
        'author'  => '',
        'avatar'  => '',
        'profile' => '',
    ), $attributes, 'linkedin_archive');

    $limit   = max(1, min(100, (int) $options['limit']));
    $columns = max(1, min(4, (int) $options['columns']));
    $author  = linkedin_archive_setting($options['author'], 'LINKEDIN_ARCHIVE_AUTHOR_NAME');
    $avatar  = linkedin_archive_setting($options['avatar'], 'LINKEDIN_ARCHIVE_AUTHOR_IMAGE');
    $profile = linkedin_archive_setting($options['profile'], 'LINKEDIN_ARCHIVE_AUTHOR_URL');

    $page   = isset($_GET['li_page']) ? max(1, min(10000, absint($_GET['li_page']))) : 1;
    $offset = ($page - 1) * $limit;
    $base   = defined('LINKEDIN_ARCHIVE_API_BASE')
        ? rtrim(LINKEDIN_ARCHIVE_API_BASE, '/')
        : 'http://127.0.0.1:8080';

    $cache_key = 'li_archive_' . md5($base . ':' . $limit . ':' . $offset);
    $data = get_transient($cache_key);
    if (false === $data) {
        $url = add_query_arg(array('limit' => $limit, 'offset' => $offset), $base . '/api/v1/posts');
        $response = wp_remote_get($url, array('timeout' => 10, 'headers' => array('Accept' => 'application/json')));
        if (is_wp_error($response) || 200 !== wp_remote_retrieve_response_code($response)) {
            return '<p>Die LinkedIn-Beiträge sind derzeit nicht verfügbar.</p>';
        }
        $data = json_decode(wp_remote_retrieve_body($response), true);
        if (!is_array($data) || !isset($data['posts']) || !is_array($data['posts'])) {
            return '<p>Die LinkedIn-Beiträge sind derzeit nicht verfügbar.</p>';
        }
        set_transient($cache_key, $data, 5 * MINUTE_IN_SECONDS);
    }

    ob_start();
    ?>
    <style>
    /* Echte Spalten statt Raster: Jede Karte schliesst direkt an die darüber in
       derselben Spalte an, unabhängig von der Nachbarspalte. Die Beiträge werden
       serverseitig abwechselnd verteilt (links, rechts, links, ...). */
    .li-archive-grid{display:flex;gap:24px;margin:20px 0;align-items:flex-start}
    .li-archive-col{flex:1 1 0;min-width:0;display:flex;flex-direction:column;gap:24px}
    /* Einspaltig: Die Spalten lösen sich auf, und `order` stellt die
       ursprüngliche chronologische Reihenfolge wieder her. */
    @media (max-width:860px){
      .li-archive-grid{flex-direction:column}
      .li-archive-col{display:contents}
    }
    .li-archive-card{background:#fff;border:1px solid #e7eaf0;border-radius:12px;box-shadow:0 5px 25px rgba(0,0,0,.055);overflow:hidden;display:flex;flex-direction:column}
    .li-archive-card__header{display:flex;align-items:center;gap:10px;padding:14px 16px 12px}
    .li-archive-card__avatar{width:40px;height:40px;border-radius:50%;object-fit:cover;flex:0 0 auto;background:#e7eaf0}
    .li-archive-card__avatar--initials{display:flex;align-items:center;justify-content:center;background:#0a66c2;color:#fff;font-weight:600;font-size:1.05rem;letter-spacing:.02em}
    .li-archive-card__identity{min-width:0;line-height:1.35}
    .li-archive-card__author{font-weight:600;color:#1b1f24;text-decoration:none;display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
    .li-archive-card__author:hover{text-decoration:underline}
    .li-archive-card__time{margin-left:auto;flex:0 0 auto;align-self:flex-start;font-size:.8rem;color:#8a94a0;white-space:nowrap}
    .li-archive-card__media{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,220px),1fr));gap:3px;background:#edf0f4}
    /* Deckel gegen Hochformate, die sonst die ganze Karte füllen. */
    .li-archive-card__media img,.li-archive-card__media video{width:100%;height:auto;display:block;max-height:520px;object-fit:cover}
    .li-archive-card__body{padding:14px 16px;flex:1 1 auto}
    /* LinkedIn liefert Absätze im Fliesstext als echte Zeilenumbrüche, nicht als
       <br>. Ohne pre-line würden sie im Browser zu Leerzeichen zusammenfallen. */
    .li-archive-card__text{line-height:1.6;color:#1b1f24;overflow-wrap:anywhere;white-space:pre-line}
    .li-archive-card__text p{margin:0 0 .8em}
    .li-archive-card__text p:last-child{margin-bottom:0}
    .li-archive-card__text a{color:#0a66c2;text-decoration:none;overflow-wrap:anywhere}
    .li-archive-card__text a:hover{text-decoration:underline}
    .li-archive-reshare{margin-top:14px;border:1px solid #e7eaf0;border-radius:8px;padding:12px 14px;background:#f8f9fb}
    .li-archive-reshare__head{display:flex;align-items:center;gap:7px;font-size:.84rem;color:#66707d;margin-bottom:8px}
    .li-archive-reshare__head a{color:#0a66c2;text-decoration:none;font-weight:600}
    .li-archive-reshare__head a:hover{text-decoration:underline}
    .li-archive-reshare__text{line-height:1.55;font-size:.94rem;color:#3d454f;overflow-wrap:anywhere;white-space:pre-line}
    .li-archive-reshare__text p{margin:0 0 .7em}
    .li-archive-reshare__text p:last-child{margin-bottom:0}
    .li-archive-reshare__text a{color:#0a66c2;text-decoration:none}
    .li-archive-reshare__text a:hover{text-decoration:underline}
    .li-archive-card__article{display:block;text-decoration:none;border:1px solid #e7eaf0;border-radius:8px;padding:12px 14px;background:#f8f9fb}
    .li-archive-card__article:hover{background:#f1f3f7}
    .li-archive-card__article-title{display:block;font-weight:600;color:#1b1f24;line-height:1.4}
    .li-archive-card__article-host{display:block;margin-top:4px;font-size:.8rem;color:#8a94a0}
    .li-archive-card__footer{margin-top:auto;display:flex;align-items:center;gap:16px;padding:10px 16px;border-top:1px solid #edf0f4;font-size:.88rem;color:#66707d}
    .li-archive-card__stat{display:inline-flex;align-items:center;gap:6px;color:#8a94a0}
    .li-archive-stat-icon{display:block;flex:0 0 auto}
    .li-archive-sr{position:absolute;width:1px;height:1px;margin:-1px;padding:0;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap;border:0}
    .li-archive-card__link{margin-left:auto;display:inline-flex;align-items:center;color:#0a66c2;text-decoration:none}
    .li-archive-card__link:hover{color:#004182}
    .li-archive-logo{display:block}
    .li-archive-pages{display:flex;gap:16px;justify-content:center;margin:30px 0}
    </style>
    <?php
    $entries = array_values(array_filter($data['posts'], 'is_array'));
    $buckets = array_fill(0, $columns, array());
    foreach ($entries as $index => $entry) {
        $buckets[$index % $columns][] = array($index, $entry);
    }
    ?>
    <div class="li-archive-grid">
    <?php foreach ($buckets as $bucket) : ?>
    <div class="li-archive-col">
    <?php foreach ($bucket as $slot) :
        list($order, $post) = $slot;

        $permalink = '';
        foreach (array('canonical_url', 'source_url') as $candidate) {
            if (!empty($post[$candidate])) { $permalink = $post[$candidate]; break; }
        }
        $timestamp = !empty($post['published_at']) ? strtotime($post['published_at']) : false;

        if (!empty($post['content_html'])) {
            $body = linkedin_archive_prepare_content(wp_kses_post($post['content_html']));
        } else {
            $body = linkedin_archive_linkify(esc_html($post['content_text'] ?? ''));
        }
        ?>
        <article class="li-archive-card" style="order:<?php echo esc_attr($order); ?>">
            <header class="li-archive-card__header">
                <?php if ($avatar) : ?>
                    <img class="li-archive-card__avatar" loading="lazy" src="<?php echo esc_url($avatar); ?>"
                         alt="<?php echo esc_attr($author ?: 'Profilbild'); ?>" width="48" height="48">
                <?php elseif ($author) : ?>
                    <span class="li-archive-card__avatar li-archive-card__avatar--initials"
                          aria-hidden="true"><?php echo esc_html(linkedin_archive_initials($author)); ?></span>
                <?php endif; ?>
                <div class="li-archive-card__identity">
                    <?php if ($author) : ?>
                        <?php if ($profile) : ?>
                            <a class="li-archive-card__author" href="<?php echo esc_url($profile); ?>"
                               target="_blank" rel="noopener noreferrer"><?php echo esc_html($author); ?></a>
                        <?php else : ?>
                            <span class="li-archive-card__author"><?php echo esc_html($author); ?></span>
                        <?php endif; ?>
                    <?php endif; ?>
                </div>
                <?php if ($timestamp) : ?>
                    <time class="li-archive-card__time" datetime="<?php echo esc_attr(gmdate('c', $timestamp)); ?>"
                          title="<?php echo esc_attr(linkedin_archive_relative_time($timestamp) . ' — ' . wp_date(get_option('date_format') . ' ' . get_option('time_format'), $timestamp)); ?>">
                        <?php echo esc_html(linkedin_archive_short_time($timestamp)); ?>
                    </time>
                <?php endif; ?>
            </header>

            <?php if (!empty($post['media'])) : ?>
            <div class="li-archive-card__media">
                <?php foreach ($post['media'] as $item) :
                    if (empty($item['media_url'])) { continue; }
                    $kind = $item['kind'] ?? '';
                    if ('image' === $kind) : ?>
                        <img loading="lazy" src="<?php echo esc_url($item['media_url']); ?>"
                             alt="<?php echo esc_attr($item['alt_text'] ?? ''); ?>">
                    <?php elseif ('video' === $kind) : ?>
                        <video controls preload="none" src="<?php echo esc_url($item['media_url']); ?>"></video>
                    <?php endif;
                endforeach; ?>
            </div>
            <?php endif; ?>

            <div class="li-archive-card__body">
                <?php if ('' !== trim(wp_strip_all_tags($body))) : ?>
                    <div class="li-archive-card__text"><?php echo $body; ?></div>
                <?php endif; ?>
                <?php
                // Beiträge ohne eigenen Text — ein geteilter Artikel, ein
                // Zertifikat — hätten sonst eine leere Karte. Dann ist der Link
                // der Inhalt und wird als Titelzeile gezeigt.
                if ('' === trim(wp_strip_all_tags($body)) && !empty($post['links'])) :
                    foreach ($post['links'] as $link) :
                        if (empty($link['url'])) { continue; } ?>
                        <a class="li-archive-card__article" href="<?php echo esc_url($link['url']); ?>"
                           target="_blank" rel="noopener noreferrer">
                            <span class="li-archive-card__article-title"><?php
                                echo esc_html($link['label'] ?: $link['url']); ?></span>
                            <span class="li-archive-card__article-host"><?php
                                echo esc_html(preg_replace('#^www\.#', '',
                                    (string) wp_parse_url($link['url'], PHP_URL_HOST))); ?></span>
                        </a>
                    <?php endforeach;
                endif; ?>
                <?php if (!empty($post['reshare_author'])) : ?>
                    <div class="li-archive-reshare">
                        <div class="li-archive-reshare__head">
                            <?php echo linkedin_archive_stat_icon('repost'); ?>
                            <span>Beitrag geteilt von
                            <?php if (!empty($post['reshare_author_url'])) : ?>
                                <a href="<?php echo esc_url($post['reshare_author_url']); ?>"
                                   target="_blank" rel="noopener noreferrer"><?php
                                   echo esc_html($post['reshare_author']); ?></a>
                            <?php else : ?>
                                <?php echo esc_html($post['reshare_author']); ?>
                            <?php endif; ?></span>
                        </div>
                        <?php if (!empty($post['reshare_html'])) : ?>
                            <div class="li-archive-reshare__text"><?php
                                echo linkedin_archive_prepare_content(wp_kses_post($post['reshare_html'])); ?></div>
                        <?php endif; ?>
                    </div>
                <?php endif; ?>
            </div>

            <footer class="li-archive-card__footer">
                <?php if (isset($post['reaction_count']) && null !== $post['reaction_count']) : ?>
                    <span class="li-archive-card__stat"><?php echo linkedin_archive_stat_icon('like'); ?><?php
                        echo esc_html(number_format_i18n((int) $post['reaction_count'])); ?><span
                        class="li-archive-sr">&nbsp;Reaktionen</span></span>
                <?php endif; ?>
                <?php if (isset($post['comment_count']) && null !== $post['comment_count']) : ?>
                    <span class="li-archive-card__stat"><?php echo linkedin_archive_stat_icon('comment'); ?><?php
                        echo esc_html(number_format_i18n((int) $post['comment_count'])); ?><span
                        class="li-archive-sr">&nbsp;Kommentare</span></span>
                <?php endif; ?>
                <?php if ($permalink) : ?>
                    <a class="li-archive-card__link" href="<?php echo esc_url($permalink); ?>"
                       target="_blank" rel="noopener noreferrer"
                       aria-label="Beitrag auf LinkedIn öffnen"><?php echo linkedin_archive_logo_svg(); ?></a>
                <?php endif; ?>
            </footer>
        </article>
    <?php endforeach; ?>
    </div>
    <?php endforeach; ?>
    </div>
    <?php if (empty($entries)) : ?><p>Noch keine freigegebenen LinkedIn-Beiträge.</p><?php endif; ?>
    <nav class="li-archive-pages" aria-label="LinkedIn-Beiträge">
        <?php if ($page > 1) : ?><a href="<?php echo esc_url(add_query_arg('li_page', $page - 1)); ?>">← Neuere Beiträge</a><?php endif; ?>
        <?php if ($offset + count($entries) < (int) ($data['total'] ?? 0)) : ?><a href="<?php echo esc_url(add_query_arg('li_page', $page + 1)); ?>">Ältere Beiträge →</a><?php endif; ?>
    </nav>
    <?php
    return ob_get_clean();
});
