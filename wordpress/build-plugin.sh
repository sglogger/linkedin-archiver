#!/usr/bin/env bash
#
# Baut aus wordpress/linkedin-archive.php ein ZIP, das sich im WordPress-Admin
# unter «Plugins → Installieren → Plugin hochladen» direkt einspielen lässt.
#
#   ./wordpress/build-plugin.sh
#   ./wordpress/build-plugin.sh --output-dir /pfad/zum/ziel
#
# WordPress erwartet im Archiv genau ein Verzeichnis auf oberster Ebene, dessen
# Name dem Plugin-Slug entspricht. Ein ZIP mit der PHP-Datei an der Wurzel wird
# abgelehnt oder falsch installiert.

set -euo pipefail

SLUG='linkedin-archive-feed'
MAIN_FILE='linkedin-archive.php'

here=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
root=$(dirname -- "$here")
source_file="$here/$MAIN_FILE"
output_dir="$root/dist"

while [ $# -gt 0 ]; do
    case "$1" in
        -o|--output-dir)
            [ $# -ge 2 ] || { echo "Fehler: $1 erwartet ein Verzeichnis." >&2; exit 2; }
            output_dir="$2"
            shift 2
            ;;
        -h|--help)
            sed -n '3,12p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
            exit 0
            ;;
        *)
            echo "Unbekannte Option: $1 (siehe --help)" >&2
            exit 2
            ;;
    esac
done

command -v zip >/dev/null 2>&1 || {
    echo "Fehler: 'zip' ist nicht installiert." >&2
    exit 1
}
[ -f "$source_file" ] || {
    echo "Fehler: $source_file nicht gefunden." >&2
    exit 1
}

# Die Version steht im Plugin-Header und ist die einzige Quelle dafür; WordPress
# erkennt ein Update nur, wenn sie sich gegenüber der installierten erhöht.
version=$(sed -n 's/^[[:space:]]*\*[[:space:]]*Version:[[:space:]]*\([0-9][0-9.]*\).*/\1/p' \
    "$source_file" | head -n 1)
[ -n "$version" ] || {
    echo "Fehler: Kein 'Version:'-Eintrag im Plugin-Header von $MAIN_FILE." >&2
    exit 1
}

# Syntaxfehler würden auf dem Server einen weissen Bildschirm erzeugen. Falls
# lokal kein PHP vorhanden ist, wird die Prüfung übersprungen statt zu scheitern.
if command -v php >/dev/null 2>&1; then
    php -l "$source_file" >/dev/null || {
        echo "Fehler: $MAIN_FILE enthält einen PHP-Syntaxfehler; kein Paket erstellt." >&2
        exit 1
    }
    echo "PHP-Syntax geprüft."
    if [ -f "$here/tests.php" ]; then
        php "$here/tests.php" >/dev/null || {
            echo "Fehler: tests.php schlägt fehl; kein Paket erstellt." >&2
            echo "Einzelheiten: php wordpress/tests.php" >&2
            exit 1
        }
        echo "Plugin-Tests bestanden."
    fi
else
    echo "Hinweis: PHP nicht gefunden, Syntax- und Testprüfung übersprungen."
    echo "         Mit Docker: docker run --rm -v \"\$PWD/wordpress:/w:ro\" php:8.3-cli php /w/tests.php"
fi

archive="$output_dir/$SLUG-$version.zip"
mkdir -p "$output_dir"
stage=$(mktemp -d)
trap 'rm -rf "$stage"' EXIT

mkdir -p "$stage/$SLUG"
# Nur die Plugin-Datei wandert ins Paket, nicht die Tests.
cp "$source_file" "$stage/$SLUG/$MAIN_FILE"

rm -f "$archive"
# -X lässt macOS-Metadaten weg, die sonst als __MACOSX im Archiv landen.
(cd "$stage" && zip -r -q -X "$archive" "$SLUG" -x '*.DS_Store')

echo
echo "Paket erstellt: $archive"
echo "Version:        $version"
echo "Grösse:         $(du -h "$archive" | cut -f1 | tr -d ' ')"
echo
echo "Inhalt:"
unzip -Z1 "$archive" | sed 's/^/  /'
echo
echo "Installation: WordPress-Admin → Plugins → Installieren → Plugin hochladen."
echo "Danach in wp-config.php die API-Basis setzen, zum Beispiel:"
echo "  define('LINKEDIN_ARCHIVE_API_BASE', 'https://www.glogger.ch/linkedin-api');"
echo "Anzeigen mit dem Shortcode [linkedin_archive limit=\"12\"]."
