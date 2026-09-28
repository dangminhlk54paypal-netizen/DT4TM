# WebAR Anleitung: Kameraerkennung & 3D-Feldüberlagerung

Diese Anleitung beschreibt, wie der reale Versuchsstand (TEAM 28 Levitator) mit einer Smartphone-Kamera erfasst wird und das 3D-Temperaturfeld sowie die magnetischen Feldlinien in Augmented Reality (AR) direkt im Browser dargestellt werden.

---

## 1. Übersicht

* **Keine App-Installation notwendig:** Funktioniert direkt im Webbrowser (Safari auf iOS, Chrome auf Android).
* **Ausrichtung über Marker:** Ein ausgedruckter **AprilTag-Marker** (2×2-Board aus vier tag36h11-Tags, 120 × 120 mm) wird mit seiner Mitte auf die Aluminiumplatte gelegt oder geklebt ($r = 0$). Die Kamera muss nicht alle Tags sehen: ab 2 sichtbaren Tags wird getrackt, ein teilweise verdecktes Board bleibt stabil.
* **Was im Kamerabild sichtbar ist:**
  - **Thermische Heatmap:** Echtzeit-Temperaturverteilung auf der Platte und den Spulen mit einstellbarer Transparenz (X-Ray-Modus), damit die echte Maschine sichtbar bleibt.
  - **Elektromagnetische Flusslinien:** Die realen 3D-Feldlinienschlaufen ($\psi = \text{const}$) mit dynamischer Fluss-Animation bei Stromfluss.
  - **Schwebehöhe:** Die berechnete Schwebehöhe und Vibration werden in Echtzeit simuliert.

---

## 2. Marker ausdrucken und vorbereiten

1. Die Druckvorlage ist ein **Vektor-PDF** (A4):
   ```
   outputs/ar_marker.pdf        (Vorschau: outputs/ar_marker.png)
   ```
   Neu erzeugen: `python gen_ar_marker.py` (braucht `reportlab` und `pillow`, keine URL nötig).
2. **Druckhinweis:**
   - Im Druckdialog **100 % / „Tatsächliche Größe“** wählen, **nicht** „An Seite anpassen“ (die Seite trägt diesen Hinweis auch selbst).
   - **Maßstab prüfen:** Der Balken unten auf der Seite muss mit dem Lineal **genau 100 mm** messen. Die vier schwarzen Quadrate (Tags) sind **48 mm** groß, das ganze Board (inkl. weißem Rand, Schnittmarken an den Ecken) ist **120 × 120 mm**.
   - Ist der Ausdruck doch skaliert: Kantenlänge eines schwarzen Tag-Quadrats nachmessen und den Wert in der App unter ⚙️ → „Marker-Größe (Tag)“ einstellen.
   - Matt drucken (kein Hochglanzpapier, keine Spiegelungen); das Board am besten auf eine ebene Fläche kleben.
3. **Aufbau des Boards:** Tags mit den IDs **0 1 / 2 3** (0 = oben links). Der Pfeil „OBEN / TOP“ zeigt die Marker-Oberseite (Tags 0 + 1); die Achsen sind wie beim früheren QR-Marker: Ursprung = Board-Mitte, x nach rechts, y nach oben. Die bisherigen Kalibrierwerte (Versatz X/Y, Drehung, Marker-auf-Scheibe/Tisch) behalten deshalb ihre Bedeutung, wenn die **Board-Mitte** dort liegt, wo vorher die QR-Mitte lag.
4. **Platzierung am Versuchsstand:**
   - **Auf der Schwebescheibe (Standard):** Board-Mitte genau auf die Mitte der Aluminiumplatte ($r=0$). Die Platte hat nur Ø160 mm: das 120-mm-Board passt darauf, ragt aber weit über die Mitte hinaus – bei Bedarf stattdessen neben dem Aufbau auf den Tisch legen und den Versatz im Menü einstellen.
   - Da $r=0$ die Symmetrieachse ist, richtet sich das gesamte 3D-Modell ohne seitlichen Versatz an der Spulenachse aus.
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
  Ermöglicht das Umschalten der Marker-Position (auf der Scheibe vs. auf dem festen Tisch) und die Einstellung der Marker-Größe (Kantenlänge eines Tags in mm, Standard 48; das Board skaliert mit).
