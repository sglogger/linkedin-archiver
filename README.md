# LinkedIn Personal Archive

Docker-Worker für die eigenen LinkedIn-Beiträge: regelmässiger API-Abgleich,
MariaDB, dauerhaft gespeicherte Bilder sowie erhaltene Personen-, Firmen- und
sonstige Links. Die Texte werden sowohl als Klartext als auch als bereinigtes
HTML gespeichert. Eine HTTP-API und ein WordPress-Shortcode machen freigegebene
Beiträge für eine eigene Website nutzbar. Der Worker veröffentlicht selbst nichts.

## Was enthalten ist

- Historischer Erstimport über die Member Snapshot API (`MEMBER_SHARE_INFO`).
- Laufende neue/geänderte/gelöschte eigene Beiträge über die Changelog API.
- Zusätzlicher täglicher Snapshot-Abgleich; Seitenanreicherung für neue,
  geänderte, fehlgeschlagene und ältere Beiträge.
- Direkter Abruf der öffentlichen Beitragsseite; Chromium/Playwright als Fallback.
- HTML mit echten Links statt erratener Profilzuordnungen. Tracking-Parameter
  von LinkedIn-Links werden entfernt; Hashtag-Anmeldelinks werden nach Möglichkeit
  auf das tatsächliche LinkedIn-Hashtagziel zurückgeführt.
- Bilder, direkt angebotene MP4/WebM-Videos und PDF-Dateien. Datei-Hash,
  Dateityp, Reihenfolge, Alt-Text, Herkunft und Downloadstatus werden gespeichert.
- Reaktionen und Kommentarzahlen aus der öffentlichen Beitragsseite, mit
  Zeitstempel des letzten erfolgreichen Abrufs. Das Veröffentlichungsdatum
  wird bei manuell abgerufenen Beiträgen aus den strukturierten Seitendaten ergänzt.
- Lese-API für freigegebene Beiträge und Bilder sowie geschützter Rohdaten-Endpunkt.
- WordPress-Plugin mit responsiven Beitragskarten und erhaltenen Links.
- Wiederholbare Imports, Transaktionen, Sperre gegen parallele Worker,
  Wiederaufnahme nach Neustarts und begrenzte Wiederholungsversuche bei API-Fehlern.
- CLI für Einzelabruf, JSON-Import, Status und Export.

## Schnellstart

Voraussetzung: Docker Engine/Desktop mit Docker Compose v2 oder neuer.

```bash
cp docker-compose.yml-example docker-compose.yml
cp .env-example .env
chmod 600 .env
mkdir -p secrets
```

`.env` bearbeiten: einen **neuen** LinkedIn-Access-Token, zwei unterschiedliche
zufällige Datenbankpasswörter und einen separaten `API_READ_KEY` eintragen.
Beispielsweise liefert `openssl rand -hex 32`
ein geeignetes Passwort. Falls bereits eine lokale `.env` mit erzeugten Passwörtern
vorhanden ist, diese verwenden und nicht überschreiben.

```dotenv
LINKEDIN_ACCESS_TOKEN=DEIN_OAUTH_ACCESS_TOKEN
MARIADB_PASSWORD=DEIN_ZUFAELLIGES_DATENBANKPASSWORT
MARIADB_ROOT_PASSWORD=EIN_ANDERES_ZUFAELLIGES_ROOTPASSWORT
API_READ_KEY=EIN_DRITTER_ZUFAELLIGER_WERT
SYNC_INTERVAL_SECONDS=3600
```

Danach:

```bash
docker compose up -d --build
docker compose logs -f archive
docker compose exec archive python -m linkedin_archiver status
curl http://127.0.0.1:8080/health
```

MariaDB ist nur im Compose-Netz erreichbar; es wird kein Datenbankport am Host
veröffentlicht. Die Website-API lauscht standardmässig nur auf `127.0.0.1:8080`.
Das Image läuft als `pwuser`, nicht als root. Chromium benötigt
etwas Arbeitsspeicher; Compose reserviert 512 MB gemeinsamen Speicher.

Der erste Import kann mehrere Durchläufe benötigen: standardmässig werden pro
Durchlauf höchstens 20 Beitragsseiten angereichert. Die API-Metadaten werden
unabhängig davon vollständig eingelesen. Zwischen Seitenaufrufen liegen mindestens
fünf Sekunden. Ein Zyklus startet sofort und danach jeweils nach der konfigurierten
Pause; es gibt keine überlappenden Zyklen.

## LinkedIn: Wie bekomme ich den API-Zugang?

Gemeint ist ein **OAuth Access Token**, nicht die Client-ID oder das Client Secret.
Für das eigene Profil in der Schweiz bzw. EU/EWR stellt LinkedIn das Produkt
**Member Data Portability API (Member)** bereit.

1. Mit dem eigenen LinkedIn-Konto das [Developer Portal](https://www.linkedin.com/developers/)
   öffnen und eine neue App erstellen.
2. Im Feld „LinkedIn Page“ genau die dafür vorgesehene
   [Member Data Portability Default Company](https://www.linkedin.com/company/member-data-portability-member-default-company)
   auswählen. LinkedIn verlangt diese spezielle Seite; keine neue Firma anlegen.
3. Die weiteren Pflichtfelder des Formulars ausfüllen.
4. Unter „Products“ **Member Data Portability API (Member)** auswählen und den
   Zugang über „Request access“ beantragen; die zugehörigen Bedingungen lesen.
5. Unter „Docs and tools“ die
   [OAuth Token Tools](https://www.linkedin.com/developers/tools/oauth) öffnen.
6. „Create token“, die gerade angelegte App und den Scope
   **`r_dma_portability_self_serve`** auswählen; „Request access token“ ausführen
   und dem Zugriff auf die eigenen Daten zustimmen.
7. Den erzeugten Token nur lokal in `LINKEDIN_ACCESS_TOKEN` in `.env` eintragen.

Die [offizielle Einrichtungsanleitung](https://learn.microsoft.com/en-us/linkedin/dma/member-data-portability/member-data-portability-member/)
beschreibt diese Schritte. LinkedIn bestimmt die regionale Berechtigung anhand
des Profilstandorts. Der Zugang ist für die eigenen Mitgliedsdaten gedacht.

### Tokenablauf und Austausch

Tokens können ablaufen oder widerrufen werden. Bei HTTP 401/403 zeigt der Worker
einen Fehler; bereits gespeicherte Daten bleiben erhalten. Über das Token-Tool
einen neuen Token erstellen, `.env` aktualisieren und den Container **neu erstellen**:

```bash
docker compose up -d --force-recreate archive
```

`docker compose restart` übernimmt geänderte Umgebungsvariablen nicht. Eine
automatische Token-Erneuerung wird nicht vorausgesetzt; der Member-Zugang
liefert nicht notwendigerweise einen Refresh Token. Client Secrets werden
für diesen manuellen Token-Workflow nicht benötigt.

`.env`, Cookies und Daten sind von Git und Docker-Builds ausgeschlossen. Tokens
werden nicht in die Datenbank oder in Exportdateien geschrieben. Ein zuvor in
einen Chat kopierter Token sollte widerrufen und ersetzt werden.

## Konfiguration in .env

| Variable | Standard | Bedeutung |
|---|---:|---|
| `LINKEDIN_ACCESS_TOKEN` | erforderlich | OAuth-Token für die Member-Portability-API |
| `SYNC_INTERVAL_SECONDS` | 3600 | Pause zwischen abgeschlossenen Durchläufen |
| `SNAPSHOT_INTERVAL_SECONDS` | 86400 | Intervall für den historischen Abgleich |
| `POST_REFRESH_DAYS` | 1 | Erfolgreich gelesene Seiten und Zähler erneut besuchen |
| `RETRY_INTERVAL_SECONDS` | 3600 | Wiederholungsintervall bei Seiten-/Medienfehlern |
| `MAX_POSTS_PER_CYCLE` | 20 | Maximale Seitenanreicherungen pro Durchlauf |
| `PAGE_DELAY_SECONDS` | 5 | Abstand zwischen Beitragsseiten |
| `REQUEST_TIMEOUT_SECONDS` | 45 | Timeout pro Netzwerk-/Browseroperation |
| `MAX_API_PAGES` | 10000 | Schutz vor endloser API-Paginierung |
| `PAGE_ENRICHMENT_ENABLED` | true | Seiten für Links und Medien lesen |
| `BROWSER_FALLBACK_ENABLED` | true | Chromium versuchen, wenn HTTP nicht reicht |
| `BROWSER_STORAGE_STATE` | leer | Optional `/run/secrets/linkedin-state.json` |
| `AUTO_PUBLISH` | false | Neu eingelesene Beiträge sofort freigeben, statt einzeln mit `publish` |
| `DOWNLOAD_MEDIA` | true | Erreichbare Mediendateien dauerhaft herunterladen |
| `MAX_MEDIA_SIZE_MB` | 100 | Obergrenze pro Datei |
| `MEDIA_ALLOWED_HOSTS` | licdn.com,linkedin.com | Erlaubte Medienhosts, inklusive Subdomains |
| `LOG_LEVEL` | INFO | Python-Loglevel |
| `DB_HOST` / `DB_PORT` | db / 3306 | MariaDB-Verbindung |
| `MARIADB_DATABASE` / `MARIADB_USER` | linkedin_archive / linkedin | Datenbank und Benutzer |
| `MARIADB_PASSWORD` | erforderlich | Passwort des Anwendungsbenutzers |
| `MARIADB_ROOT_PASSWORD` | erforderlich | Passwort zur Initialisierung der Compose-DB |
| `API_READ_KEY` | erforderlich für Rohdaten | Geheimnis für `X-Archive-Key`; nicht im Browser verwenden |
| `API_BIND_ADDRESS` / `API_PORT` | 127.0.0.1 / 8080 | Bind-Adresse und Host-Port der Website-API |
| `API_PUBLIC_BASE_URL` | http://localhost:8080 | Öffentliche Basis-URL, aus der Bild-URLs gebildet werden |
| `API_ALLOWED_ORIGIN` | https://www.glogger.ch | Erlaubter Browser-Origin für CORS |

Um beispielsweise externe Vorschau-Bilder von Credly herunterzuladen, kann
`images.credly.com` zur Hostliste hinzugefügt werden. OAuth-Header werden
ausschliesslich an `api.linkedin.com` gesendet, nie an Medienhosts.

## Wie bleiben Personen- und Firmenlinks erhalten?

Der reine Snapshot liefert häufig nur Text. Die öffentliche Beitragsseite
enthält dagegen echte `<a href="…">Name</a>`-Elemente. Gespeichert werden:

- `posts.content_html`: bereinigter Beitrag mit diesen Links und Absätzen.
- `posts.content_text`: Klartext für Suche und Vorschauen.
- `post_links`: Ziel, Beschriftung, Reihenfolge und Typ (`person`, `organization`,
  `hashtag`, `external`).

Im geprüften Beispiel
[6978966287410470912](https://www.linkedin.com/feed/update/urn%3Ali%3Ashare%3A6978966287410470912)
sind Dan Rodriguez, Sven Decrauzat, Oliver Stein, Mike Feusi und Florian Kässberger
als Links vorhanden. Andere dort genannte Namen stehen öffentlich nur als Text;
ihre Profil-URLs werden nicht erfunden. Firmenlinks wie Digitec Galaxus bleiben
auf dieselbe Weise erhalten. Links aus Kommentaren und Profilbilder werden
nicht als Teil des eigenen Beitrags übernommen.
Im weiteren Beispiel
[6947191367093653525](https://www.linkedin.com/feed/update/urn%3Ali%3Ashare%3A6947191367093653525)
bleiben die Links auf Swisscom, TSK Zürich, Stefan Rüegg, Marco Lüthi und
Christoph Aeschlimann erhalten. Die öffentliche Seite zeigte beim Test 60
Reaktionen und 3 Kommentare; die Werte können sich später ändern.

Das HTML wird auf Text, Absätze, einfache Hervorhebungen und HTTP(S)-Links reduziert.
Eventhandler, Skripte, eingebettete Frames und `javascript:`-Links werden entfernt.
Für erhaltene Zeilenumbrüche später beispielsweise `.post-body { white-space: pre-wrap; }`
verwenden. Nur `content_html` rendern, nicht `raw_page_fragment` oder API-Rohdaten.

Die Zähler sind LinkedIn-*Reaktionen* insgesamt, nicht nur die Reaktion „Gefällt
mir“. Wenn möglich werden die exakten Zahlen aus dem strukturierten Beitrag
gelesen. Fehlt ein Zähler auch im öffentlichen HTML, bleibt sein Datenbankfeld `NULL`;
die API erfindet keine Null. `engagement_updated_at` zeigt den letzten erkannten
Stand. Mit `POST_REFRESH_DAYS=1` werden erfolgreich gelesene Beiträge nach einem
Tag erneut vorgemerkt; Abarbeitung erfolgt bis `MAX_POSTS_PER_CYCLE` pro Zyklus.

## Medien und Grenzen

Bei den hier geprüften Kontodaten war `MediaUrl` bzw. `Media Link` oft leer.
Der Worker nutzt deshalb die tatsächlichen Medienattribute der Beitragsseite.
Bilder werden aus dem Beitrags-Bildcontainer geladen, einschliesslich
`data-delayed-url` und `srcset`, statt alle Bilder einer Seite zu sammeln.

Dateien liegen unter `/data/media/<Hash-Präfix>/<SHA256>.<Endung>`; gleiche Bytes
werden nur einmal gespeichert. Die SQL-Zuordnung enthält die ursprüngliche URL,
die Position und den Downloadstatus. Signierte CDN-URLs können ablaufen; eine
erfolgreich gespeicherte lokale Datei bleibt unabhängig davon verfügbar.

**Keine Garantie für Originalauflösung:** Gesichert wird die grösste unmittelbar
angebotene Bildvariante. Beispielsweise lieferte die öffentliche Seite des
Katzenklo-Beitrags 800 × 600 Pixel. Signaturen und Grössenparameter werden nicht
manipuliert. Bereits gespeicherte Dateien werden bei Wiederholung nicht erneut
geladen, ausser die lokale Datei fehlt oder sich die Asset-ID ändert.

Videos/PDFs werden nur heruntergeladen, wenn die Seite direkte unterstützte
Datei-URLs offenlegt. HLS/DASH, nicht sichtbare Karussellseiten, interne
Dokument-Viewer, externe Embeds und geschützte Originaldateien sind keine
vollständig unterstützten Medienarchive. `complete` bedeutet, dass die **erkannten**
Medien verarbeitet wurden; es beweist nicht, dass LinkedIn alle Anhänge ausliefert.
Native lange LinkedIn-Artikel/Newsletter (`/pulse/`) werden in dieser Version
nicht als vollständige Artikel importiert; Schwerpunkt sind Feed-Beiträge.

LinkedIn kann öffentliche Seiten einschränken oder deren HTML ändern. Dann
bleiben die API-Texte erhalten, und der Fehler ist über `status` sichtbar.
Ein fehlender Snapshot oder eine Login-Seite wird nicht als Löschung behandelt.
Nur ein passendes eigenes DELETE-Ereignis markiert einen Beitrag als gelöscht;
sein Archiv bleibt bestehen, er verschwindet aus Exporten.

Der Seitenabruf fällt unter LinkedIns Regeln für automatisierten Zugriff.
[LinkedIn untersagt Scraping-Werkzeuge](https://www.linkedin.com/help/lms/answer/a1341387).
Mit `PAGE_ENRICHMENT_ENABLED=false` lässt sich der Betrieb auf die offizielle API
begrenzen; bei leeren API-Medienfeldern fehlen dann Bilder und Erwähnungslinks.

## API-Paginierung und laufender Abgleich

Die [Snapshot API](https://learn.microsoft.com/en-us/linkedin/dma/member-data-portability/shared/member-snapshot-api)
verlangt den Header `Linkedin-Version: 202312`. Der Wert ist absichtlich fest.
Ihr `start`-Parameter ist ein Seitenindex; die angegebene Gesamtzahl ist nicht
immer vollständig. Der Worker liest weiter bis zur Leerantwort bzw. „No data
found for this memberId“ und erkennt wiederholte Seiten als Fehler.

Die [Changelog API](https://learn.microsoft.com/en-us/linkedin/dma/member-data-portability/shared/member-changelog-api)
liefert Ereignisse ab der Einwilligung mit einem rückblickenden Fenster von
28 Tagen. Der Worker verwendet `processedAt` als inklusiven Checkpoint,
dedupliziert Ereignisse und schreibt den Checkpoint erst nach erfolgreichem
Verarbeiten aller Ergebnisseiten. Kommentare, Likes und Ereignisse anderer
Autoren werden nicht als eigene Beiträge gespeichert. Ausfälle über 28 Tage
können zu nicht rekonstruierbaren Änderungen/Löschereignissen führen.

Der Erst-Snapshot kann nach der Einwilligung noch leer sein. Neue oder bearbeitete
Beiträge können verzögert bei LinkedIn bereitstehen. Abrufintervalle sind daher
keine Garantie für sekundengenaue Aktualität.

## Befehle

Einzelner API-Durchlauf bzw. erzwungener Snapshot (bei Bedarf laufenden Worker
vorher stoppen; eine Datenbanksperre verhindert parallele Verarbeitung):

```bash
docker compose run --rm archive sync
docker compose run --rm archive sync --force-snapshot
docker compose run --rm archive enrich
```

Einen bestimmten eigenen Beitrag direkt lesen, auch ohne API-Token:

```bash
docker compose run --rm archive fetch \
  'https://www.linkedin.com/feed/update/urn%3Ali%3Ashare%3A6978966287410470912'
```

Bestehende API-JSON-Antwort importieren (nur JSON, kein Terminaltranskript):

```bash
docker compose run --rm \
  -v "$PWD/linkedin-posts.json:/import/posts.json:ro" \
  archive import-json /import/posts.json
docker compose run --rm archive enrich
```

## Daten für eine eigene Website

Ein privater Gesamtexport enthält alle nicht als gelöscht markierten Beiträge:

```bash
docker compose exec archive python -m linkedin_archiver export
docker compose cp archive:/data/export/archive.json ./archive.json
docker compose cp archive:/data/media ./media
```

Vor einer Veröffentlichung Beiträge auswählen. `MEMBER_NETWORK` ist keine
verlässliche Freigabe für eine öffentliche Website. Deshalb gibt es zusätzlich
eine eigene, standardmässig deaktivierte `publish_enabled`-Markierung:

```bash
docker compose exec archive python -m linkedin_archiver publish 'urn:li:share:6978966287410470912'
docker compose exec archive python -m linkedin_archiver export --published-only
docker compose cp archive:/data/export/website.json ./website.json
```

`publish` ändert nur die Auswahl in der eigenen Datenbank. Es veröffentlicht
nichts auf LinkedIn oder einer Website. Mit `publish <URN> --disable` rückgängig machen.

### Alle neuen Beiträge automatisch freigeben

Wer die Einzelauswahl nicht will, setzt `AUTO_PUBLISH=true` in `.env` und
erstellt den Container neu. Jeder danach **neu** eingelesene Beitrag ist sofort
über die Website-Endpunkte und `export --published-only` verfügbar.

Damit entfällt die Kontrolle pro Beitrag: Auch Beiträge mit Sichtbarkeit
`MEMBER_NETWORK`, die auf LinkedIn nur das eigene Netzwerk sieht, landen dann
automatisch auf der öffentlichen Website.

Die Einstellung wirkt nur beim erstmaligen Anlegen eines Beitrags:

- Bereits archivierte Beiträge bleiben unverändert und brauchen weiterhin `publish`.
- Ein mit `publish <URN> --disable` zurückgezogener Beitrag wird durch einen
  späteren Snapshot- oder Changelog-Abgleich nicht wieder freigegeben.
- Gelöschte Beiträge werden nie freigegeben.

Den vorhandenen Bestand gibt `AUTO_PUBLISH` nicht nachträglich frei. Falls das
gewünscht ist, einmalig in MariaDB:

```bash
docker compose exec -T db sh -c \
  'exec mariadb -u"$MARIADB_USER" -p"$MARIADB_PASSWORD" "$MARIADB_DATABASE"' <<'SQL'
UPDATE posts SET publish_enabled = TRUE WHERE deleted_at IS NULL;
SQL
```

Jeder JSON-Beitrag enthält `post_key`, URLs, Zeitpunkt, Sichtbarkeit, `content_html`,
`content_text`, `links` und `media`. Medien haben `local_url` wie
`/media/ab/abcdef….jpg`. Die Website kann das Medienverzeichnis unter `/media/`
ausliefern oder die Dateien in ihren eigenen Object Storage kopieren.

Alternativ direkt aus MariaDB lesen:

```sql
SELECT post_key, published_at, content_text, content_html
FROM posts
WHERE publish_enabled = TRUE AND deleted_at IS NULL
ORDER BY published_at DESC;
```

Für eine direkte MariaDB-Anbindung der Website einen separaten Benutzer mit
nur SELECT-Rechten einrichten.
Keine OAuth-Tokens, Browser-Cookies oder Rohdaten im Frontend ausliefern. Die
Rohdaten sind für spätere erneute Verarbeitung gedacht, nicht als fertiges HTML.

## HTTP-API für die Website

Der Compose-Dienst `api` liest nur Daten. Er zeigt standardmässig **keine**
Beiträge: Erst `publish <URN>` gibt einen Beitrag für Website-Endpunkte und
Mediendateien frei — oder `AUTO_PUBLISH=true` für alle neu eingelesenen. Gelöschte Beiträge erscheinen dort nicht. Die API ist
zunächst nur auf dem Docker-Host unter `http://127.0.0.1:8080` erreichbar.

| Endpunkt | Ergebnis |
|---|---|
| `GET /health` | Datenbankverbindung prüfen |
| `GET /api/v1/posts?limit=12&offset=0` | Freigegebene Beiträge, paginiert, fertig für die Anzeige |
| `GET /api/v1/posts/urn%3Ali%3Ashare%3A6978966287410470912` | Ein freigegebener Beitrag |
| `GET /media/<Pfad>` | Lokal gespeicherte Datei eines freigegebenen Beitrags |
| `GET /api/v1/raw/posts?limit=20&offset=0` | Vollständige Rohfelder aller nicht gelöschten Beiträge; `X-Archive-Key` erforderlich |

Beispiele:

```bash
curl 'http://127.0.0.1:8080/api/v1/posts?limit=12&offset=0'
curl -H 'X-Archive-Key: DEIN_API_READ_KEY' \
  'http://127.0.0.1:8080/api/v1/raw/posts?limit=20&offset=0'
```

`limit` ist 1–100, `offset` 0–1000000. Die Antwort enthält `total`, `limit`,
`offset` und `posts`. Formatierte Beiträge haben unter anderem `content_html`,
`content_text`, `links`, `media`, `reaction_count`, `comment_count` und
`engagement_updated_at`. `media[].media_url` ist eine absolute URL zur lokalen
Datei, sofern der Download gelang. Der private Rohdaten-Endpunkt liefert
zusätzlich `raw_snapshot`, `raw_event`, `raw_page_fragment` und technische
Medienfelder. Den Rohdaten-Schlüssel nur serverseitig verwenden, nie in
WordPress-HTML oder JavaScript. Fehlt `API_READ_KEY` oder ist er noch ein
`REPLACE_`-Platzhalter, antwortet der Rohdaten-Endpunkt mit 503.

### Einbindung auf glogger.ch (WordPress)

Die derzeitige Seite [glogger.ch/linkedin/](https://www.glogger.ch/linkedin/)
ist eine WordPress-Seite mit einem Juicer-Embed. Das mitgelieferte Plugin
[`wordpress/linkedin-archive.php`](wordpress/linkedin-archive.php) ersetzt es
durch eigene Beitragskarten in einem mehrspaltigen Raster:

- Kopfzeile mit Profilbild, Name und relativer Zeitangabe („vor 3 Tagen“).
- Darunter die Bilder, dann der Beitragstext.
- Fussleiste mit Reaktions- und Kommentarzahl sowie dem LinkedIn-Logo unten
  rechts, das den Beitrag auf LinkedIn öffnet.
- Erwähnungen und externe Links bleiben klickbar und öffnen in einem neuen Tab.
  `#hashtags` werden auf die LinkedIn-Hashtagsuche verlinkt, auch wenn sie im
  Archiv nur als Text vorliegen.
- Lange Beiträge werden auf eine einstellbare Zeilenzahl gekürzt und bekommen
  einen Link zum vollständigen Beitrag.

Es holt die freigegebenen JSON-Daten serverseitig und speichert die Antwort fünf
Minuten im WordPress-Cache. Auf schmalen Bildschirmen wird das Raster einspaltig.

1. Installationspaket bauen und im Adminbereich unter „Plugins → Installieren →
   Plugin hochladen“ einspielen, danach aktivieren:

   ```bash
   ./wordpress/build-plugin.sh
   ```

   Das Skript legt `dist/linkedin-archive-feed-<Version>.zip` an. Die Version
   liest es aus dem Plugin-Header; WordPress erkennt ein Update nur, wenn sie
   dort erhöht wurde. Alternativ `wordpress/linkedin-archive.php` von Hand als
   `wp-content/plugins/linkedin-archive-feed/linkedin-archive.php` ablegen.
2. Im `wp-config.php` die vom WordPress-Server erreichbare API-Basis setzen und
   Name sowie Profilbild hinterlegen:

   ```php
   define('LINKEDIN_ARCHIVE_API_BASE',     'https://linkedinapi.glogger.ch');
   define('LINKEDIN_ARCHIVE_AUTHOR_NAME',  'Steven Glogger');
   define('LINKEDIN_ARCHIVE_AUTHOR_IMAGE', 'https://www.glogger.ch/wp-content/uploads/steven.jpg');
   define('LINKEDIN_ARCHIVE_AUTHOR_URL',   'https://www.linkedin.com/in/steven-glogger/');
   ```

   Name und Profilbild stehen bewusst hier und nicht in der Datenbank: Das
   Archiv speichert nur die eigenen Beiträge und lädt keine Profilbilder
   herunter. Alle Beiträge stammen ohnehin von derselben Person.
3. Auf `/linkedin/` das bisherige Juicer-Embed durch den Shortcode
   `[linkedin_archive limit="12" columns="2"]` ersetzen und den
   WordPress-Seitencache leeren.
4. Gewünschte Beiträge mit `docker compose exec archive python -m linkedin_archiver publish '<URN>'`
   freigeben. Erst dann werden sie im Feed sichtbar. Mit `AUTO_PUBLISH=true`
   entfällt dieser Schritt für neue Beiträge.

Alle Shortcode-Attribute:

| Attribut | Standard | Bedeutung |
|---|---:|---|
| `limit` | 12 | Beiträge pro Seite, 1–100 |
| `columns` | 2 | Spalten im Raster, 1–4; unter 860 px immer einspaltig |
| `clamp` | 10 | Maximale Textzeilen je Karte; `0` schaltet das Kürzen ab |
| `author` | Konstante | Überschreibt `LINKEDIN_ARCHIVE_AUTHOR_NAME` |
| `avatar` | Konstante | Überschreibt `LINKEDIN_ARCHIVE_AUTHOR_IMAGE` |
| `profile` | Konstante | Überschreibt `LINKEDIN_ARCHIVE_AUTHOR_URL` |

Reaktions- und Kommentarzahl erscheinen nur, wenn sie im Archiv vorhanden sind;
fehlende Werte werden weggelassen und nicht als Null dargestellt.

Wenn WordPress und Docker auf demselben Host laufen, kann WordPress intern
`http://127.0.0.1:8080` verwenden. Für Bilder im Browser braucht es zusätzlich
eine öffentliche HTTPS-Basis. Ein Nginx-Reverse-Proxy auf demselben Host kann
den Pfad vor den WordPress-Rewrite-Regeln weiterleiten:

```nginx
location = /linkedin-api/api/v1/raw/posts {
    return 403;
}

location /linkedin-api/ {
    proxy_pass http://127.0.0.1:8080/;
    proxy_set_header Host $host;
}
```

Dann `API_PUBLIC_BASE_URL=https://www.glogger.ch/linkedin-api` in `.env` setzen
und `docker compose up -d --force-recreate api` ausführen. Auch die
`LINKEDIN_ARCHIVE_API_BASE`-Konstante auf diese URL setzen. Liegt WordPress auf
einem anderen Server, muss dessen Server die API über eine erreichbare
HTTPS-Adresse ansprechen können; Nginx und Netzwerkfreigabe entsprechend auf
dem Docker-Host einrichten. Der gezeigte Nginx-Block sperrt den privaten
Rohdaten-Endpunkt für externe Zugriffe. Der Browser-Origin `API_ALLOWED_ORIGIN` ist für eine direkte
JavaScript-Einbindung gedacht; der WordPress-Shortcode benötigt kein CORS.

Die Vorlage ändert die bestehende Website nicht automatisch. WordPress-Zugang,
Serverstandort und Reverse-Proxy-Konfiguration sind dafür erforderlich.

## Optional: angemeldeter Browser

Für öffentlich lesbare Beiträge ist kein Browser-Login nötig. Für eigene
eingeschränkte Beiträge kann lokal ein Playwright-Storage-State erzeugt werden:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/playwright install chromium
.venv/bin/playwright codegen --save-storage=secrets/linkedin-state.json https://www.linkedin.com/login
```

Im geöffneten Browser selbst anmelden, anschliessend das Fenster schliessen.
Die Datei enthält Zugangsdaten und gehört nur lokal in `secrets/`. Unter Linux
muss sie für den Containerbenutzer lesbar sein. Dann setzen:

```dotenv
BROWSER_STORAGE_STATE=/run/secrets/linkedin-state.json
```

Container neu erstellen. Es werden keine CAPTCHAs gelöst und keine Zugriffs- oder
Anmeldesperren umgangen. Der Parser unterstützt die öffentliche Feed-HTML-Struktur;
LinkedIns angemeldete Ansicht kann eine andere Struktur liefern und wird dann
als nicht unterstützt protokolliert. Login ist daher keine Zusage, dass private
Beiträge vollständig extrahiert werden können.

## Datenbank, Backups, Updates

Tabellen: `posts`, `post_links`, `post_media`, `post_events`, `sync_state`.
Alle Textfelder verwenden utf8mb4, inklusive Emojis. Datumswerte werden in UTC
gespeichert; bei Snapshot-Datumstexten wird UTC angenommen, passend zu den
geprüften GMT-Uploadangaben. Rohdaten bleiben unverändert archiviert.

MariaDB liegt im Volume `mariadb-data`, Medien und Exporte in `archive-data`.
Beide sichern; nur ein SQL-Dump enthält nicht die Bilddateien.

```bash
mkdir -p backup
docker compose exec -T db sh -c \
  'exec mariadb-dump --single-transaction -u"$MARIADB_USER" -p"$MARIADB_PASSWORD" "$MARIADB_DATABASE"' \
  > backup/archive.sql
docker compose cp archive:/data/media backup/media
```

Normales Stoppen: `docker compose down`. **`down -v` löscht die Datenvolumes.**
Passwortvariablen des MariaDB-Images wirken nur beim ersten Initialisieren eines
leeren Volumes. Spätere Passwortwechsel zusätzlich in MariaDB durchführen.

Bei Quellcode-Updates `docker compose up -d --build`. Diese erste Version erstellt
das Schema mit `CREATE TABLE IF NOT EXISTS`; künftige Schemaänderungen benötigen
explizite Migrationen. Image- und Bibliotheksversionen sind festgelegt und sollten
regelmässig kontrolliert aktualisiert werden.

## Entwicklung und Tests

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
```

Die MariaDB-Integrationstests laufen nur bei gesetztem `TEST_DB_HOST`,
`TEST_DB_PORT` und `TEST_DB_PASSWORD`. **Nur eine leere Testdatenbank**
`linkedin_archive` mit Benutzer `linkedin` verwenden: Die Tests leeren die
Anwendungstabellen. Geprüft werden u.a. Linkerhaltung, Abgrenzung von Kommentaren,
HTML-Bereinigung, Paginierung, Checkpoint-Rollback, Duplikate und Medienfehler.

Quellen: [LinkedIn Member-Zugang](https://learn.microsoft.com/en-us/linkedin/dma/member-data-portability/member-data-portability-member/),
[Snapshot](https://learn.microsoft.com/en-us/linkedin/dma/member-data-portability/shared/member-snapshot-api),
[Changelog](https://learn.microsoft.com/en-us/linkedin/dma/member-data-portability/shared/member-changelog-api),
[Playwright Docker](https://playwright.dev/python/docs/docker),
[MariaDB Docker Image](https://hub.docker.com/_/mariadb).
