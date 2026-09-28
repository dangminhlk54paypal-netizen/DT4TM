# WebAR Anleitung: Kameraerkennung & 3D-Feldüberlagerung

Diese Anleitung beschreibt, wie der reale Versuchsstand (TEAM 28 Levitator) mit einer Smartphone-Kamera erfasst wird und das 3D-Temperaturfeld sowie die magnetischen Feldlinien in Augmented Reality (AR) direkt im Browser dargestellt werden.

---

## 1. Übersicht

* **Keine App-Installation notwendig:** Funktioniert direkt im Webbrowser (Safari auf iOS, Chrome auf Android).
* **Ausrichtung über Marker:** Ein ausgedruckter QR-Marker wird zentriert auf die Aluminiumplatte gelegt oder geklebt ($r = 0$).
* **Was im Kamerabild sichtbar ist:**
  - **Thermische Heatmap:** Echtzeit-Temperaturverteilung auf der Platte und den Spulen mit einstellbarer Transparenz (X-Ray-Modus), damit die echte Maschine sichtbar bleibt.
  - **Elektromagnetische Flusslinien:** Die realen 3D-Feldlinienschlaufen ($\psi = \text{const}$) mit dynamischer Fluss-Animation bei Stromfluss.
  - **Schwebehöhe:** Die berechnete Schwebehöhe und Vibration werden in Echtzeit simuliert.

---

## 2. Marker ausdrucken und vorbereiten

1. Die Druckvorlage liegt im Ordner:
   ```
   outputs/ar_marker.png
   ```
2. **Druckhinweis:**
   - Drucke das Bild im Druckdialog mit **100% Skalierung** („Tatsächliche Größe“, nicht „Auf Seite einpassen“) aus.
   - Die Standard-Kantenlänge des **QR-Symbols** (nur die schwarz/weißen Module, ohne weißen Rand, Rahmen und Text) beträgt **$60 \times 60\,\text{mm}$**; das ganze Blatt ist ca. 104 mm breit. Mit dem Lineal nachmessen: ist das Symbol kleiner/größer, den Wert in der App unter ⚙️ → „QR-Code Größe“ anpassen. (Ausdrucke vor 2026-09-28 sind nur ca. 29,5 mm groß, weil das PNG mit fester Auflösung gespeichert wurde.)
3. **Platzierung am Versuchsstand:**
   - **Auf der Schwebescheibe (Standard):** Klebe oder lege den Marker genau in die Mitte der oberen Aluminiumplatte ($r=0$).
   - Da $r=0$ die Symmetrieachse ist, richtet sich das gesamte 3D-Modell ohne seitlichen Versatz exakt an der Spulenachse aus.

> [!TIP]
> **Neu-Generieren des Markers mit eigener URL:**
> ```bash
> python gen_ar_marker.py https://meine-domain.de/ar_twin.html --size 60
> ```

---

## 3. WebAR-Seite auf dem Smartphone öffnen

Aufgrund von Sicherheitsrichtlinien der Mobilbrowser (iOS Safari & Android Chrome) erfordert der Zugriff auf die Smartphone-Kamera (`getUserMedia`) eine **sichere Verbindung (HTTPS)** oder `localhost`.

### Methode A: Bereitstellung über GitHub Pages (Empfohlen für Demos)
1. Aktiviere in den GitHub-Repository-Einstellungen unter **Pages** den Branch `main` (Ordner `/` oder `/docs`).
2. Rufe die URL auf deinem Smartphone auf:
   ```
   https://<dein-github-username>.github.io/DT4TM/outputs/ar_twin.html
   ```
3. Der QR-Code auf dem Marker kann genau auf diese URL programmiert werden, sodass Besucher nur den QR-Code mit der normalen Kamera-App scannen müssen!

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
  Ermöglicht das Umschalten der Marker-Position (auf der Scheibe vs. auf dem festen Tisch) und die Auswahl alternativer Marker-Druckgrößen (50, 60, 70, 80 mm).
