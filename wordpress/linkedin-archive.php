<?php
/**
 * Plugin Name: LinkedIn Archive Feed
 * Description: Zeigt freigegebene Beiträge aus dem eigenen LinkedIn-Archiv über [linkedin_archive] an.
 * Version: 2.0.0
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

/** Grobe Zeichenzahl pro Textzeile in einer zweispaltigen Karte. */
const LINKEDIN_ARCHIVE_CHARS_PER_LINE = 55;

/**
 * Schätzt, ob der Text über die erlaubte Zeilenzahl hinausgeht.
 *
 * CSS kann zwar kürzen, aber nicht mitteilen, ob es gekürzt hat. Ohne diese
 * Schätzung stünde «Ganzen Beitrag lesen» auch unter einem Dreizeiler.
 */
function linkedin_archive_exceeds_lines($text, $max_lines) {
    if ($max_lines < 1) {
        return false;
    }
    $lines = 0;
    foreach (preg_split('/\R/u', trim($text)) as $line) {
        $length = function_exists('mb_strlen') ? mb_strlen($line) : strlen($line);
        $lines += max(1, (int) ceil($length / LINKEDIN_ARCHIVE_CHARS_PER_LINE));
        if ($lines > $max_lines) {
            return true;
        }
    }
    return false;
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
 * Verlinkt #hashtags auf die LinkedIn-Hashtagsuche.
 *
 * Läuft nur über Textabschnitte ausserhalb von <a>-Elementen, damit bereits
 * echte Hashtag-Links aus der Beitragsseite nicht verschachtelt werden.
 */
function linkedin_archive_linkify_hashtags($text) {
    return preg_replace_callback(
        '/(?<![\w&#])#([\p{L}\p{N}_]{2,80})/u',
        function ($matches) {
            $url = LINKEDIN_ARCHIVE_HASHTAG_BASE . rawurlencode($matches[1]);
            return '<a class="li-archive-hashtag" href="' . esc_url($url)
                . '" target="_blank" rel="noopener noreferrer nofollow">#'
                . esc_html($matches[1]) . '</a>';
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
        $result .= $anchor_depth > 0 ? $part : linkedin_archive_linkify_hashtags($part);
    }
    return $result;
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
        'clamp'   => 10,
        'author'  => '',
        'avatar'  => '',
        'profile' => '',
    ), $attributes, 'linkedin_archive');

    $limit   = max(1, min(100, (int) $options['limit']));
    $columns = max(1, min(4, (int) $options['columns']));
    $clamp   = max(0, min(100, (int) $options['clamp']));
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
    /* align-items:start, damit eine kurze Karte nicht auf die Höhe der längsten
       in derselben Zeile aufgezogen wird. */
    .li-archive-grid{display:grid;grid-template-columns:repeat(var(--li-columns,2),minmax(0,1fr));gap:24px;margin:20px 0;align-items:start}
    @media (max-width:860px){.li-archive-grid{grid-template-columns:1fr}}
    .li-archive-card{background:#fff;border:1px solid #e7eaf0;border-radius:12px;box-shadow:0 5px 25px rgba(0,0,0,.055);overflow:hidden;display:flex;flex-direction:column}
    .li-archive-card__header{display:flex;align-items:center;gap:12px;padding:18px 20px 14px}
    .li-archive-card__avatar{width:48px;height:48px;border-radius:50%;object-fit:cover;flex:0 0 auto;background:#e7eaf0}
    .li-archive-card__identity{min-width:0;line-height:1.35}
    .li-archive-card__author{font-weight:600;color:#1b1f24;text-decoration:none;display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
    .li-archive-card__author:hover{text-decoration:underline}
    .li-archive-card__time{font-size:.82rem;color:#6b7481}
    .li-archive-card__media{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,220px),1fr));gap:3px;background:#edf0f4}
    /* Deckel gegen Hochformate, die sonst die ganze Karte füllen. */
    .li-archive-card__media img,.li-archive-card__media video{width:100%;height:auto;display:block;max-height:520px;object-fit:cover}
    .li-archive-card__body{padding:18px 20px;flex:1 1 auto}
    /* LinkedIn liefert Absätze im Fliesstext als echte Zeilenumbrüche, nicht als
       <br>. Ohne pre-line würden sie im Browser zu Leerzeichen zusammenfallen. */
    .li-archive-card__text{line-height:1.6;color:#1b1f24;overflow-wrap:anywhere;white-space:pre-line}
    .li-archive-card__text p{margin:0 0 .8em}
    .li-archive-card__text p:last-child{margin-bottom:0}
    .li-archive-card__text a{color:#0a66c2;text-decoration:none}
    .li-archive-card__text a:hover{text-decoration:underline}
    .li-archive-card__text--clamped{display:-webkit-box;-webkit-line-clamp:var(--li-clamp,10);line-clamp:var(--li-clamp,10);-webkit-box-orient:vertical;overflow:hidden}
    .li-archive-card__more{display:inline-block;margin-top:8px;font-size:.88rem;color:#0a66c2;text-decoration:none}
    .li-archive-card__more:hover{text-decoration:underline}
    .li-archive-card__footer{margin-top:auto;display:flex;align-items:center;gap:16px;padding:12px 20px;border-top:1px solid #edf0f4;font-size:.88rem;color:#66707d}
    .li-archive-card__stat{display:inline-flex;align-items:center;gap:5px}
    .li-archive-card__link{margin-left:auto;display:inline-flex;align-items:center;color:#0a66c2;text-decoration:none}
    .li-archive-card__link:hover{color:#004182}
    .li-archive-logo{display:block}
    .li-archive-pages{display:flex;gap:16px;justify-content:center;margin:30px 0}
    </style>
    <div class="li-archive-grid" style="--li-columns:<?php echo esc_attr($columns); ?>">
    <?php foreach ($data['posts'] as $post) :
        if (!is_array($post)) { continue; }

        $permalink = '';
        foreach (array('canonical_url', 'source_url') as $candidate) {
            if (!empty($post[$candidate])) { $permalink = $post[$candidate]; break; }
        }
        $timestamp = !empty($post['published_at']) ? strtotime($post['published_at']) : false;

        if (!empty($post['content_html'])) {
            $body = linkedin_archive_prepare_content(wp_kses_post($post['content_html']));
        } else {
            $body = linkedin_archive_linkify_hashtags(esc_html($post['content_text'] ?? ''));
        }

        $plain = $post['content_text'] ?? wp_strip_all_tags($body);
        $truncated = linkedin_archive_exceeds_lines($plain, $clamp);
        ?>
        <article class="li-archive-card">
            <header class="li-archive-card__header">
                <?php if ($avatar) : ?>
                    <img class="li-archive-card__avatar" loading="lazy" src="<?php echo esc_url($avatar); ?>"
                         alt="<?php echo esc_attr($author ?: 'Profilbild'); ?>" width="48" height="48">
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
                    <?php if ($timestamp) : ?>
                        <time class="li-archive-card__time" datetime="<?php echo esc_attr(gmdate('c', $timestamp)); ?>"
                              title="<?php echo esc_attr(wp_date(get_option('date_format') . ' ' . get_option('time_format'), $timestamp)); ?>">
                            <?php echo esc_html(linkedin_archive_relative_time($timestamp)); ?>
                        </time>
                    <?php endif; ?>
                </div>
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
                <div class="li-archive-card__text<?php echo $truncated ? ' li-archive-card__text--clamped' : ''; ?>"
                     <?php echo $truncated ? 'style="--li-clamp:' . esc_attr($clamp) . '"' : ''; ?>><?php
                    echo $body;
                ?></div>
                <?php if ($truncated && $permalink) : ?>
                    <a class="li-archive-card__more" href="<?php echo esc_url($permalink); ?>"
                       target="_blank" rel="noopener noreferrer">Ganzen Beitrag auf LinkedIn lesen</a>
                <?php endif; ?>
            </div>

            <footer class="li-archive-card__footer">
                <?php if (isset($post['reaction_count']) && null !== $post['reaction_count']) : ?>
                    <span class="li-archive-card__stat">👍 <?php echo esc_html(number_format_i18n((int) $post['reaction_count'])); ?></span>
                <?php endif; ?>
                <?php if (isset($post['comment_count']) && null !== $post['comment_count']) : ?>
                    <span class="li-archive-card__stat">💬 <?php echo esc_html(number_format_i18n((int) $post['comment_count'])); ?></span>
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
    <?php if (empty($data['posts'])) : ?><p>Noch keine freigegebenen LinkedIn-Beiträge.</p><?php endif; ?>
    <nav class="li-archive-pages" aria-label="LinkedIn-Beiträge">
        <?php if ($page > 1) : ?><a href="<?php echo esc_url(add_query_arg('li_page', $page - 1)); ?>">← Neuere Beiträge</a><?php endif; ?>
        <?php if ($offset + count($data['posts']) < (int) ($data['total'] ?? 0)) : ?><a href="<?php echo esc_url(add_query_arg('li_page', $page + 1)); ?>">Ältere Beiträge →</a><?php endif; ?>
    </nav>
    <?php
    return ob_get_clean();
});
