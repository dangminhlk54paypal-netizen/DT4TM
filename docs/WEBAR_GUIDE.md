# WebAR Anleitung: Kameraerkennung & 3D-Feldüberlagerung

Diese Anleitung beschreibt, wie der reale Versuchsstand (TEAM 28 Levitator) mit einer Smartphone-Kamera erfasst wird und das 3D-Temperaturfeld sowie die magnetischen Feldlinien in Augmented Reality (AR) direkt im Browser dargestellt werden.

---

## 1. Übersicht

* **Englische Variante:** `python build_ar_twin.py --lang en` erzeugt `outputs/ar_twin_en.html` (gleiche Seite, englische Oberfläche; Übersetzungstabelle in `ar_i18n.py`).
* **Keine App-Installation notwendig:** Funktioniert direkt im Webbrowser (Safari auf iOS, Chrome auf Android).
* **Ausrichtung über ZWEI Marker (WP-AR-DUAL):** Zwei ausgedruckte **AprilTag-Boards** (je 2×2 tag36h11-Tags, 120 × 120 mm, gleiche Größe): der **Platten-Marker** (IDs 0–3) wird mit seiner Mitte auf die Aluminiumplatte geklebt ($r = 0$) und dreht, schwebt und kippt mit ihr; der **Basis-Marker** (IDs 4–7) liegt fest neben dem Prüfstand. Der Unterbau (Spulen, Eisen, Kork, Holzgehäuse, Feldlinien) hängt am Basis-Marker und **bleibt stehen**, die Platte im Modell folgt der echten Platte. Die Kamera muss nicht alle Tags sehen: ab 2 sichtbaren Tags je Board wird getrackt, ein teilweise verdecktes Board bleibt stabil.
* **Was im Kamerabild sichtbar ist:**
  - **Thermische Heatmap:** Echtzeit-Temperaturverteilung auf der Platte und den Spulen mit einstellbarer Transparenz (X-Ray-Modus), damit die echte Maschine sichtbar bleibt.
  - **Elektromagnetische Flusslinien:** Die realen 3D-Feldlinienschlaufen ($\psi = \text{const}$) mit dynamischer Fluss-Animation bei Stromfluss.
  - **Schwebehöhe:** Die berechnete Schwebehöhe und Vibration werden in Echtzeit simuliert.

---

## 2. Marker ausdrucken und vorbereiten

1. Die Druckvorlage ist ein **Vektor-PDF** (A4, **2 Seiten**):
   ```
   outputs/ar_marker.pdf        Seite 1 = Platten-Marker (IDs 0-3), Seite 2 = Basis-Marker (IDs 4-7)
                                (Vorschau: outputs/ar_marker.png bzw. outputs/ar_marker_base.png)
   ```
   Beide Seiten tragen oben ihren Titel („PLATTEN-MARKER (dreht mit)“ / „BASIS-MARKER (fest)“). **Beide ausdrucken, beide gleich groß** – die Marker-Größe in der App gilt für beide Boards.
   Neu erzeugen: `python gen_ar_marker.py` (braucht `reportlab` und `pillow`, keine URL nötig).
2. **Druckhinweis:**
   - Im Druckdialog **100 % / „Tatsächliche Größe“** wählen, **nicht** „An Seite anpassen“ (die Seite trägt diesen Hinweis auch selbst).
   - **Maßstab prüfen:** Der Balken unten auf der Seite muss mit dem Lineal **genau 100 mm** messen. Die vier schwarzen Quadrate (Tags) sind **48 mm** groß, das ganze Board (inkl. weißem Rand, Schnittmarken an den Ecken) ist **120 × 120 mm**.
   - Ist der Ausdruck doch skaliert: Kantenlänge eines schwarzen Tag-Quadrats nachmessen und den Wert in der App unter ⚙️ → „Marker-Größe (Tag)“ einstellen.
   - Matt drucken (kein Hochglanzpapier, keine Spiegelungen); das Board am besten auf eine ebene Fläche kleben.
3. **Aufbau der Boards:** Platten-Marker: Tags mit den IDs **0 1 / 2 3** (0 = oben links); Basis-Marker: **4 5 / 6 7**. Der Pfeil „OBEN / TOP“ zeigt die Marker-Oberseite (Tags 0 + 1); die Achsen sind wie beim früheren QR-Marker: Ursprung = Board-Mitte, x nach rechts, y nach oben. Versatz X/Y, Drehung, Neigung, Größe und Höhentrimmung im ⚙️-Menü verschieben ab jetzt nur noch den **Unterbau** gegenüber der Platte (die Platte sitzt immer auf dem Platten-Marker). Die frühere Wahl „Marker auf der Scheibe / auf dem Tisch“ gibt es nicht mehr: der Platten-Marker sitzt immer auf der Platte, der Basis-Marker immer fest.
4. **Platzierung am Versuchsstand:**
   - **Platten-Marker:** Board-Mitte genau auf die Mitte der Aluminiumplatte ($r=0$, flach aufkleben, möglichst leicht – die Platte muss noch schweben). Die Platte hat nur Ø160 mm: das 120-mm-Board passt darauf. Da $r=0$ die Symmetrieachse ist, liegt das Modell ohne seitlichen Versatz an der Spulenachse.
   - **Basis-Marker:** fest auf den Tisch oder das Gehäuse **neben** dem Prüfstand (ca. 5–15 cm Abstand, **flach**, nie bewegen; er darf beliebig gedreht sein). Beide Marker sollten **gleichzeitig** im Bild sein; je näher der Basis-Marker an der Platte liegt, desto genauer ist die Einmessung (Hebelarm) – und desto öfter reicht ein einziger Bildausschnitt.
5. **Reichweite:** In der Simulation (1280×720-Video) wird das Board zuverlässig von ca. 25 cm bis über 1 m erkannt (der alte 45-mm-QR-Code nur bis ca. 30 cm). Reale Kameras rauschen/verwackeln mehr: bei Zittern des Overlays zuerst `POS_MIN_CUTOFF_HZ`, `POS_Z_MIN_CUTOFF_HZ`, `ROT_MIN_CUTOFF_HZ` in `build_ar_twin.py` (Block `TRK`) senken.

> [!NOTE]
> **Erkennung:** Der offizielle AprilTag-3-Detektor (C-Bibliothek) läuft als WebAssembly direkt in der Seite (`apriltag_wasm.js`, in `ar_twin.html` eingebettet, kein Netz nötig; Neubau: `python build_apriltag_wasm.py`, braucht Docker). Ein QR-Code mit der URL ist nicht mehr Teil des Markers – dafür bei Bedarf `python gen_qr.py <URL>` verwenden.

---

## 3. WebAR-Seite auf dem Smartphone öffnen

Aufgrund von Sicherheitsrichtlinien der Mobilbrowser (iOS Safari & Android Chrome) erfordert der Zugriff auf die Smartphone-Kamera (`getUserMedia`) eine **sichere Verbindung (HTTPS)** oder `localhost`.

### Methode A: Bereitstellung über GitHub Pages (Empfohlen für Demos)
1. Aktiviere in den GitHub-Repository-Einstellungen unter **Pages** den Branch `main` (Ordner `/` oder `/docs`).
2. Rufe die URL auf deinem Smartphone auf:
   ```
   https://<dein-github-username>.github.io/DT4TM/outputs/ar_twin.html
   ```
3. Für Besucher kann mit `python gen_qr.py <URL>` ein separater QR-Code (nur die URL) erzeugt werden – der AR-Marker selbst enthält keine URL mehr.

### Methode B: Lokales Testen im WLAN (z. B. via ngrok)
1. Starte im Projektverzeichnis einen lokalen Webserver:
   ```powershell
   python -m http.server 8000
   ```
2. Öffne einen HTTPS-Tunnel (z. B. via [ngrok](https://ngrok.com)):
   ```bash
   ngrok http 8000
   ```
3. Öffne den ausgegebenen HTTPS-Link auf dem Smartphone und navigiere zu `/outputs/ar_twin.html`.

### Methode C: Lokales Testen am PC mit Webcam
* Öffne [outputs/ar_twin.html](../outputs/ar_twin.html) direkt in Chrome oder Edge auf einem Laptop mit Webcam.
* Klicke auf **„Kamera starten“** und halte den ausgedruckten Marker (oder das Bild auf deinem Smartphone) vor die Webcam.

---

## 4. Bedienung in der WebAR-App

* **3D-Vorschau vs. Live-Kamera:** 
  Vor dem Aktivieren der Kamera kann das Modell per Touch oder Maus frei gedreht und gezoomt werden. Ein Klick auf **„📷 Kamera starten“** wechselt in den AR-Tracking-Modus.
* **Erregerstrom-Slider ($0 \dots 7{,}8\,\text{A}$):**
  Stellt den virtuellen Erregerstrom bzw. die Trafo-Stellung ein. Die Erwärmung der Spulen und die Hubkraft reagieren sofort physikalisch konsistent.
* **Tastenleiste:**
  - `⚡ B-Feld`: Schaltet die 3D-Magnetfeldlinien ein/aus.
  - `🌡️ Temp`: Schaltet die thermische Oberflächenfärbung ein/aus.
  - `👁️ X-Ray`: Macht das 3D-Modell halbtransparent, damit die realen Spulen darunter durchscheinen.
  - `🚀 7.8A`: Springt direkt auf den maximalen Betriebspunkt (270V Stelltrafo-Endanschlag).
* **Zahnrad-Menü (⚙️):**
  Unterbau einmessen (siehe 5.), Ausrichtung des Unterbaus (Drehwinkel, Neigung, Größe, X/Y/Z), Deckkraft, Marker-Größe (Kantenlänge eines Tags in mm, Standard 48; beide Boards skalieren mit) und „Levitation simulieren“.
* **Anzeige oben rechts (Tracking-Modus):** `🟢 Platte 4/4 + Basis 4/4 Tags` (Normalfall), `🟢 Basis … · Platte: Modell`, `🟠 Nur Platte … · Basis kamerafest`, `🟡 Marker verdeckt`, `🟡 Suche Marker...` (Details unter 6.). Der Zusatz „· vorläufig“ heißt: noch nicht eingemessen.
* **Telemetrie „Spalt“:** „Spalt Modell“ = Schwebehöhe aus der Physik; darunter (nur bei beiden Markern) „Spalt gemessen ≈ … mm · Kipp ≈ …° · Dreh ≈ … U/min“ = **mit der Kamera gemessen** (≈: Näherung, siehe Grenzen). Rein zur Anzeige, die Physik bleibt unberührt.

---

## 5. Unterbau einmessen (einmalig pro Aufbau)

Der Basis-Marker liegt beliebig neben dem Prüfstand; die App muss wissen, wo die Spulenachse relativ zu ihm liegt. Dafür:

1. Platte **liegt auf den Spulen** (kein Strom, Platten-Marker aufgeklebt), beide Marker sind im Bild, Kamera ruhig halten.
2. ⚙️ → **„📏 Unterbau einmessen (Platte liegt auf)“** tippen. Nach ca. 0,5 s steht dort „eingemessen ✓“ (σ = Streuung der Messung, typisch < 0,2 mm). Bei „zu unruhig“ (Kamera/Platte bewegt sich) oder „zu wenige Bilder“ (Marker nur kurz erkannt, z. B. sehr langsame Kamera) einfach noch einmal tippen.
3. Die Einmessung wird im Browser gespeichert (je Marker-Größe) und beim nächsten Start geladen – **zusammen mit der Fein-Anpassung** (Drehwinkel, Neigung, Größe, X/Y/Z; spätere Änderungen werden mitgespeichert). **„zurücksetzen“** löscht sie. Wurde der Basis-Marker verschoben, neu einmessen.

Wenn beide Marker ca. 0,3 s ruhig gleichzeitig zu sehen sind, legt die App automatisch eine **vorläufige** Einmessung an (Anzeige „vorläufig“), damit es sofort funktioniert – sie ist nur so gut wie die Platte dabei auflag (eine drehende Platte wird nicht übernommen). Die Fein-Anpassung (Drehwinkel 22,5° für die Kantenausrichtung des Gehäuses, X/Y/Z) wirkt zusätzlich auf den Unterbau.

---

## 6. Was passiert, wenn ein Marker nicht zu sehen ist?

| Zustand | Unterbau | Platte |
|---|---|---|
| **Beide Marker** | vom Basis-Marker (+ Einmessung): fest | gemessen: Position, Kippen, Drehen |
| **Nur Basis-Marker** (Platte verdeckt) | exakt | 1,5 s letzte gemessene Lage, danach Modellzustand (aufliegend bzw. Modell-Spalt), Drehung eingefroren |
| **Nur Platten-Marker** (Fallback) | Position und Neigung aus der Plattenebene, um den zuletzt gemessenen Spalt (bis die Platte aus dem Bild war; sonst Modell-Spalt, sonst 0) abgesenkt; **Drehung (Gier) an die Kamera gekoppelt**, nicht an den Marker – er dreht sich also nicht mit der Platte mit | folgt dem Marker |
| **Keiner** | letzte Pose bis 0,8 s halten, dann ausblenden | – |

Wichtig beim Fallback: Ohne Basis-Marker kann die App „Platte dreht sich“ nicht von „Kamera wandert um den Aufbau“ unterscheiden. Bei ruhiger Kamera bleibt der Unterbau deshalb korrekt; umkreist man den Aufbau, **läuft die Drehung des Unterbaus mit der Kamera mit** (Umlauf von 30° ≈ 30° Gier-Fehler), bis der Basis-Marker wieder erscheint. Beim Wechsel der Zustände gleitet das Bild in ca. 0,25 s auf die neue Quelle (kein Springen). Wird nur der Platten-Marker benutzt (altes Verhalten mit einem Marker), gilt immer dieser Fallback – der Unterbau dreht sich nicht mehr mit dem Marker.

**Grenzen:** (1) Die Brennweite der Kamera ist geschätzt (f = 1,05 × Videohöhe): bei falscher Schätzung und anderem Blickwinkel als beim Einmessen weicht der gemessene Spalt ab (Größenordnung 0,4 mm je 1 % Brennweitenfehler nach 30° Umlauf; am Einmess-Blickwinkel praktisch fehlerfrei). (2) Bei sehr schnellem Drehen und langer Belichtung (Innenraum) verwischen die Tags; im Test (1/60 s Belichtung) blieb die Erkennung bis 300°/s stabil, darüber ist sie ungetestet. (3) Die Kameraanzeige „Kipp“ und „Spalt“ sind Näherungen (≈), keine Messgeräte.
