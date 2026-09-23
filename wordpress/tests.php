<?php
/**
 * Prüfungen für die Textaufbereitung des WordPress-Plugins.
 *
 *   docker run --rm -v "$PWD/wordpress:/w:ro" php:8.3-cli php /w/tests.php
 *
 * build-plugin.sh führt die Datei automatisch aus, wenn PHP verfügbar ist.
 * Die WordPress-Funktionen werden nur so weit nachgebildet, wie das Plugin sie
 * benutzt; geprüft wird ausschliesslich die eigene Logik.
 */

define('ABSPATH', true);

function esc_url($value) { return htmlspecialchars($value, ENT_QUOTES); }
function esc_html($value) { return htmlspecialchars($value, ENT_QUOTES); }
function esc_attr($value) { return htmlspecialchars($value, ENT_QUOTES); }
function add_shortcode($name, $callback) {}

require __DIR__ . '/linkedin-archive.php';

$failures = 0;
$checks = 0;

function check($label, $got, $want) {
    global $failures, $checks;
    $checks++;
    if ($got === $want) {
        printf("  [OK ] %s\n", $label);
        return;
    }
    $failures++;
    printf("  [FEHL] %s\n        erwartet: %s\n        erhalten: %s\n",
        $label, var_export($want, true), var_export($got, true));
}

echo "== Nackte URLs im nicht angereicherten Text ==\n";
$r = linkedin_archive_prepare_content(
    '<p>Plugin bei WP: https://lnkd.in/e2EDXFqt<br>Source Code: https://lnkd.in/ehqT36Mu</p>');
check('beide URLs verlinkt', substr_count($r, '<a '), 2);
check('href unverändert', strpos($r, 'href="https://lnkd.in/e2EDXFqt"') !== false, true);
check('Linktext ist die URL', strpos($r, '>https://lnkd.in/e2EDXFqt</a>') !== false, true);
check('öffnet in neuem Fenster', substr_count($r, 'target="_blank"'), 2);

echo "\n== Satzzeichen gehören nicht zum Link ==\n";
$r = linkedin_archive_prepare_content('<p>Mehr auf https://hidden.ch. Und https://example.com/x, oder?</p>');
check('Punkt bleibt aussen vor', strpos($r, 'href="https://hidden.ch"') !== false, true);
check('Punkt bleibt im Text', strpos($r, '</a>. Und') !== false, true);
check('Komma bleibt aussen vor', strpos($r, 'href="https://example.com/x"') !== false, true);

echo "\n== Ein URL-Fragment ist kein Hashtag ==\n";
$r = linkedin_archive_prepare_content('<p>Siehe https://example.com/seite#oben dazu</p>');
check('genau ein Link', substr_count($r, '<a '), 1);
check('keine Hashtagsuche erzeugt', strpos($r, 'keywords=oben') === false, true);
check('Fragment bleibt in der URL', strpos($r, 'seite#oben') !== false, true);

echo "\n== Kodiertes & im Query-String ==\n";
$r = linkedin_archive_prepare_content('<p>Link https://example.com/?a=1&amp;b=2 hier</p>');
check('& korrekt kodiert', strpos($r, 'a=1&amp;b=2') !== false, true);
check('nicht doppelt kodiert', strpos($r, 'amp;amp;') === false, true);

echo "\n== Hashtags ==\n";
$r = linkedin_archive_prepare_content('<p>Text #WordPress und #Grüezi und #a</p>');
check('zwei Hashtags verlinkt', substr_count($r, 'li-archive-hashtag'), 2);
check('Umlaut kodiert', strpos($r, 'keywords=Gr%C3%BCezi') !== false, true);
check('Einzelzeichen ignoriert', strpos($r, 'keywords=a"') === false, true);
$r = linkedin_archive_prepare_content('<p>Weiss&#8217;s schon</p>');
check('Entity ist kein Hashtag', strpos($r, 'keywords=8217') === false, true);

echo "\n== Bestehende Anker bleiben unangetastet ==\n";
$r = linkedin_archive_prepare_content(
    '<p>Danke <a href="https://www.linkedin.com/in/dan/" rel="noopener noreferrer">Dan</a></p>');
check('kein zweiter Anker', substr_count($r, '<a '), 1);
check('bekommt target', strpos($r, 'target="_blank"') !== false, true);
check('rel unverändert', substr_count($r, 'rel="noopener noreferrer"'), 1);
$r = linkedin_archive_prepare_content(
    '<p><a href="https://lnkd.in/x" rel="noopener noreferrer">https://lnkd.in/x</a></p>');
check('URL im Linktext nicht doppelt verlinkt', substr_count($r, '<a '), 1);
$r = linkedin_archive_prepare_content(
    '<p><a href="https://example.com/s#teil" rel="noopener noreferrer">Doku</a></p>');
check('Attributwert unangetastet', strpos($r, 's#teil') !== false, true);

echo "\n== Nur http(s) ==\n";
$r = linkedin_archive_prepare_content('<p>mail@example.com oder ftp://x.y</p>');
check('keine Links erzeugt', substr_count($r, '<a '), 0);

echo "\n== Zeitangaben ==\n";
check('1 Tag',      linkedin_archive_relative_time(time() - 86400),     'vor 1 Tag');
check('3 Tage',     linkedin_archive_relative_time(time() - 3 * 86400), 'vor 3 Tagen');
check('1 Stunde',   linkedin_archive_relative_time(time() - 3600),      'vor 1 Stunde');
check('2 Monate',   linkedin_archive_relative_time(time() - 70 * 86400), 'vor 2 Monaten');
check('Zukunft leer', linkedin_archive_relative_time(time() + 500),     '');
check('kompakt 25d', linkedin_archive_short_time(time() - 25 * 86400),  '25d');
check('kompakt 3mo', linkedin_archive_short_time(time() - 95 * 86400),  '3mo');
check('kompakt 2h',  linkedin_archive_short_time(time() - 7200),        '2h');
check('keine Wochenstufe', linkedin_archive_short_time(time() - 10 * 86400), '10d');

echo "\n== Initialen als Rückfall ==\n";
check('zwei Wörter', linkedin_archive_initials('Steven Glogger'), 'SG');
check('ein Wort',    linkedin_archive_initials('Steven'), 'S');

echo "\n== Icons ==\n";
check('Like vorhanden',    strpos(linkedin_archive_stat_icon('like'), '<svg') === 0, true);
check('Kommentar vorhanden', strpos(linkedin_archive_stat_icon('comment'), '<svg') === 0, true);
check('Repost vorhanden',  strpos(linkedin_archive_stat_icon('repost'), '<svg') === 0, true);
check('erbt die Textfarbe', strpos(linkedin_archive_stat_icon('like'), 'currentColor') !== false, true);
check('unbekanntes Icon leer', linkedin_archive_stat_icon('gibtsnicht'), '');

printf("\n%d Prüfungen, %d Fehlschläge\n", $checks, $failures);
exit($failures === 0 ? 0 : 1);
