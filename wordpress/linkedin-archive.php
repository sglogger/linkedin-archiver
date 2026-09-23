<?php
/**
 * Plugin Name: LinkedIn Archive Feed
 * Description: Zeigt freigegebene Beiträge aus dem eigenen LinkedIn-Archiv über [linkedin_archive] an.
 * Version: 1.0.0
 */

if (!defined('ABSPATH')) {
    exit;
}

add_shortcode('linkedin_archive', function ($attributes) {
    $options = shortcode_atts(array('limit' => 12), $attributes, 'linkedin_archive');
    $limit = max(1, min(100, (int) $options['limit']));
    $page = isset($_GET['li_page']) ? max(1, min(10000, absint($_GET['li_page']))) : 1;
    $offset = ($page - 1) * $limit;
    $base = defined('LINKEDIN_ARCHIVE_API_BASE') ? rtrim(LINKEDIN_ARCHIVE_API_BASE, '/') : 'http://127.0.0.1:8080';
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
    .li-archive-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,320px),1fr));gap:24px;margin:20px 0}
    .li-archive-card{background:#fff;border:1px solid #e7eaf0;border-radius:12px;box-shadow:0 5px 25px rgba(0,0,0,.055);overflow:hidden;display:flex;flex-direction:column}
    .li-archive-card__body{padding:22px;flex:1}
    .li-archive-card__date{display:block;font-size:.83rem;color:#6b7481;margin-bottom:12px}
    .li-archive-card__text{line-height:1.65;overflow-wrap:anywhere;white-space:pre-wrap}
    .li-archive-card__text a{color:#0875bc;text-decoration:underline}
    .li-archive-card__media{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,220px),1fr));gap:4px}
    .li-archive-card__media img,.li-archive-card__media video{width:100%;height:auto;display:block}
    .li-archive-card__footer{padding:14px 22px;border-top:1px solid #edf0f4;display:flex;flex-wrap:wrap;gap:14px;align-items:center;font-size:.88rem;color:#66707d}
    .li-archive-card__footer a{margin-left:auto}
    .li-archive-pages{display:flex;gap:16px;justify-content:center;margin:30px 0}
    </style>
    <div class="li-archive-grid">
    <?php foreach ($data['posts'] as $post) :
        if (!is_array($post)) { continue; }
        $raw_date = isset($post['published_at']) ? strtotime($post['published_at']) : false;
        $body = !empty($post['content_html']) ? wp_kses_post($post['content_html']) : nl2br(esc_html($post['content_text'] ?? ''));
        ?>
        <article class="li-archive-card">
            <div class="li-archive-card__body">
                <?php if ($raw_date) : ?><time class="li-archive-card__date" datetime="<?php echo esc_attr(gmdate('c', $raw_date)); ?>"><?php echo esc_html(wp_date(get_option('date_format'), $raw_date)); ?></time><?php endif; ?>
                <div class="li-archive-card__text"><?php echo $body; ?></div>
            </div>
            <?php if (!empty($post['media'])) : ?>
            <div class="li-archive-card__media">
                <?php foreach ($post['media'] as $item) :
                    if (empty($item['media_url'])) { continue; }
                    if (($item['kind'] ?? '') === 'image') : ?>
                        <img loading="lazy" src="<?php echo esc_url($item['media_url']); ?>" alt="<?php echo esc_attr($item['alt_text'] ?? ''); ?>">
                    <?php elseif (($item['kind'] ?? '') === 'video') : ?>
                        <video controls preload="none" src="<?php echo esc_url($item['media_url']); ?>"></video>
                    <?php endif;
                endforeach; ?>
            </div>
            <?php endif; ?>
            <div class="li-archive-card__footer">
                <?php if (isset($post['reaction_count']) && null !== $post['reaction_count']) : ?><span>👍 <?php echo esc_html(number_format_i18n((int) $post['reaction_count'])); ?> Reaktionen</span><?php endif; ?>
                <?php if (isset($post['comment_count']) && null !== $post['comment_count']) : ?><span>💬 <?php echo esc_html(number_format_i18n((int) $post['comment_count'])); ?> Kommentare</span><?php endif; ?>
                <a href="<?php echo esc_url($post['canonical_url'] ?: $post['source_url']); ?>" target="_blank" rel="noopener noreferrer">Auf LinkedIn ansehen ↗</a>
            </div>
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
