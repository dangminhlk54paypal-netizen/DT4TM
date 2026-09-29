# Vortrag DT4TM – Skript und Vorbereitung der Verteidigung

**Titel:** Digital Twin für das Thermomanagement eines elektrodynamischen Levitators
**Folien:** `DT4TM_Praesentation.pptx` (14 Vortragsfolien + Dankesfolie + 7 Backup-Folien B1–B7)
**Redezeit:** Ziel 14–15 min (Rahmen 13–16 min). Der Sprechtext steht zusätzlich in den Notizen jeder Folie (Referentenansicht).

---

## 1. Zeitplan

| Folie | Inhalt | Zeit | kumuliert |
|---|---|---|---|
| 1 | Titel | 0:30 | 0:30 |
| 2 | Warum ein virtueller Sensor? | 1:15 | 1:45 |
| 3 | Versuchsstand und physikalisches Modell | 1:15 | 3:00 |
| 4 | Vom Vorgang zur Gleichung | 1:30 | 4:30 |
| 5 | Methodik: zwei Stufen, MOR vs. ROM | 1:00 | 5:30 |
| 6 | Finite-Elemente-Methode | 1:15 | 6:45 |
| 7 | MOR: Grundidee und Reduktion A | 1:15 | 8:00 |
| 8 | Reduktion B (Eigenwerte, ROM vs. FEM) | 1:30 | 9:30 |
| 9 | Reduktion C und Kalibrierung | 1:15 | 10:45 |
| 10 | Berechnungswerkzeug (+ optionale Demo) | 1:15 | 12:00 |
| 11 | Ergebnis 1: Verluste | 0:45 | 12:45 |
| 12 | Ergebnis 2: Vergleich mit der Messung | 1:30 | 14:15 |
| 13 | Ursachen der Abweichungen | 1:00 | 15:15 |
| 14 | Ausblick und Fazit | 1:00 | 16:15 |

Die Summe der Richtwerte (16:15) ist bewusst großzügig. Der Sprechtext hat rund 1 600 Wörter und dauert bei ruhigem Vortragstempo etwa **14 min**.

**Wenn die Zeit knapp wird (→ 13 min):**
- Folie 6: nur die drei Plausibilitätsprüfungen nennen, Diskretisierung in einem Satz.
- Folie 11: nur „138 W, Spulen drei Viertel“ sagen, Stromkonvention auf die Backup-Folie verschieben.
- Keine Live-Demo auf Folie 10.

**Wenn Zeit übrig ist (→ 16 min):** Live-Demo auf Folie 10 (max. 30 s): `RUN.command` vorher öffnen, im Vortrag nur Strom-Schieberegler bewegen und mit „+“ die Zeit raffen.

**Sprecheraufteilung (Vorschlag, frei änderbar):**
- Person 1: Folien 1–4 (Einleitung, Problemstellung)
- Person 2: Folien 5–9 (Methodik: FEM und MOR)
- Person 3: Folien 10–14 (Code, Ergebnisse, Ausblick)

Übergabesätze: „… und wie wir diese Gleichungen lösen, zeigt jetzt [Name].“ / „Was dabei herauskommt, stellt [Name] vor.“

---

## 2. Sprechtext

### Folie 1 – Titel  *(ca. 0:30)*

Guten Tag, sehr geehrter Herr Professor Hartmann, sehr geehrte Frau Dr. Merkel, liebe Kommilitoninnen und Kommilitonen.

Wir stellen heute unser Projekt vor: einen Digital Twin für das Thermomanagement eines elektrodynamischen Levitators.

Kurz gesagt: Wir berechnen aus dem Spulenstrom die Temperaturen im Gerät, und zwar so schnell, dass die Vorhersage live mitläuft.

Wir zeigen, wie wir dafür ein genaues, aber langsames FEM-Modell in ein schnelles reduziertes Modell überführt haben, wie gut es zur Messung passt und wo es noch nicht passt.

### Folie 2 – Warum ein virtueller Sensor?  *(ca. 1:15)*

Worum geht es? Unser Versuchsstand ist ein Levitator nach dem TEAM-Benchmark 28. Zwei Spulen mit 50-Hz-Wechselstrom erzeugen ein Magnetfeld; es induziert Wirbelströme in einer Aluminiumscheibe, und die Scheibe schwebt.

Dieselben Ströme erzeugen aber auch Wärme – in der Scheibe, in den Spulen und im Eisen.

Diese Temperaturen sind schwer zu messen: Ein Fühler an der schwebenden Scheibe würde die Levitation stören, und in die Wicklung kommt man nicht hinein. Den Strom dagegen kann man leicht messen.

Die Idee ist deshalb ein virtueller Sensor: Ein Modell rechnet aus dem Strom die Temperatur.

Dafür muss es drei Dinge erfüllen: Es muss schnell sein, also in Echtzeit laufen. Es muss physikalisch begründet sein, nicht nur eine angepasste Kurve. Und es muss sich an Messungen kalibrieren lassen.

Das Problem: Genaue Modelle sind langsam. Die Brücke dazwischen ist die Modellordnungsreduktion – und genau darum geht es in diesem Vortrag.

### Folie 3 – Versuchsstand und physikalisches Modell  *(ca. 1:15)*

Hier sehen Sie den halben Querschnitt – die Radien haben wir selbst mit dem Lineal gemessen.

Von innen nach außen: Eisenkern, Innenspule mit etwa 1000 Windungen, Eisenring, Außenspule mit etwa 500 Windungen. Darüber schwebt die Aluminiumscheibe mit 80 Millimetern Radius und 3 Millimetern Dicke.

Das Eisen bündelt das Feld, das Wechselfeld induziert in Scheibe und Eisen Wirbelströme, und alle Ströme erzeugen Wärme.

Für das Modell treffen wir vier Vereinfachungen: Das Gerät ist drehsymmetrisch, also rechnen wir nur in einer Halbebene r–z. Die Umgebung ist konstant 20 Grad, wie mit Ihnen vereinbart. Standardmäßig fließen 5 Ampere, im Modell ist der Strom aber frei einstellbar. Und in der Feldrechnung ist die Scheibenhöhe fest.

Wichtig für später: Das Gerät hat keine fest eingebauten Temperatursensoren. Alle Temperaturmesswerte stammen aus Aufnahmen mit einer IR-Kamera vom 23. Juni.

### Folie 4 – Vom physikalischen Vorgang zur Gleichung  *(ca. 1:30)*

Jeder dieser physikalischen Vorgänge wird zu einer Gleichung.

Erstens das Magnetfeld: Wir rechnen das magnetische Vektorpotential A-phi. Weil der Strom sinusförmig ist, reicht eine komplexe Amplitude, ein Phasor – wir müssen die 50 Hertz also nicht in der Zeit auflösen.

Zweitens die Wärmequelle: Aus dem Feld folgt die Wirbelstromdichte und daraus die mittlere Verlustleistung pro Volumen: q gleich ein halb sigma omega-Quadrat mal Betrag A zum Quadrat. In den Spulen ist es einfach ein halb I-Quadrat R.

Drittens die Wärmeleitung: die Fourier-Gleichung mit Konvektion am Rand.

Viertens die Temperaturabhängigkeit: Warme Metalle leiten schlechter. Das koppelt zurück auf die Feldgleichung – aber langsam, weil sich Temperaturen über Minuten ändern.

Im Bericht steht zu jeder Gleichung, in welchem Python-Modul sie gelöst wird.

### Folie 5 – Methodik: zwei Stufen  *(ca. 1:00)*

Wie lösen wir das? In zwei Stufen.

Offline, also einmal, löst die Finite-Elemente-Methode die Gleichungen genau – das dauert etwa eine Sekunde und braucht Löserbibliotheken.

Daraus leiten wir mit Modellordnungsreduktion, kurz MOR, ein reduziertes Modell ab, das ROM. Zur Begriffsklärung: MOR ist das Verfahren, das ROM ist sein Ergebnis.

Das ROM läuft online: Jeder Zeitschritt dauert wenige Mikrosekunden und braucht nur Grundrechenarten. Deshalb kann es live mitlaufen und im Browser dargestellt werden.

Die nächsten Folien gehen die beiden Stufen durch – zuerst die FEM, dann die Reduktion.

### Folie 6 – Finite-Elemente-Methode  *(ca. 1:15)*

Warum FEM? Das Gerät hat fünf Materialbereiche, dafür gibt es keine Formellösung.

Wir zerlegen die r-z-Ebene in Dreiecke; in jedem Dreieck ändert sich die gesuchte Größe linear. Die Gleichung wird im Mittel um jeden Knoten erfüllt – physikalisch ist das eine Wärmebilanz pro Knoten, mit dem Faktor 2 pi r für die Drehung um die Achse. Heraus kommt ein großes, aber fast leeres lineares Gleichungssystem, das wir mit SciPy direkt lösen.

Klein bleibt es durch zwei physikalische Argumente: den Phasor statt Zeitschritten, und die Eindringtiefe von etwa 12 Millimetern – viel mehr als die 3 Millimeter Scheibendicke. Wir brauchen also kein feines Netz in Dickenrichtung. So kommen wir auf rund 8700 Unbekannte im Feld und 700 in der Scheibe.

Da eine FEM immer Zahlen liefert, auch falsche, prüfen wir bei jedem Lauf drei Dinge: Die Energiebilanz stimmt auf Rundungsgenauigkeit, zwei verschiedene Randbedingungen unterscheiden sich um weniger als ein Prozent, und doppelter Strom ergibt exakt vierfache Verluste.

### Folie 7 – MOR: Grundidee und Reduktion A  *(ca. 1:15)*

Jetzt zur Reduktion. Die FEM ist genau, aber für jeden neuen Strom und jeden Zeitschritt müsste man sie neu lösen.

Die Beobachtung dahinter: Die tausenden Unbekannten sind nicht unabhängig. Beim Aufheizen ändert sich vor allem, wie warm die Scheibe ist – kaum, wo sie wärmer ist.

Stellen Sie sich ein Foto vor, das nur heller oder dunkler wird: Man speichert das Bild einmal und merkt sich pro Moment nur einen Helligkeitsfaktor. Mathematisch schreiben wir das Feld als Summe weniger fester Formen mit zeitabhängigen Gewichten.

Das setzen wir in drei Schritten um. Reduktion A: Die Feldgleichung ist linear. Doppelter Strom heißt doppeltes Feld und vierfache Wärmequelle – an jedem Ort gleich. Also lösen wir die Feld-FEM genau einmal bei 5 Ampere; für jeden anderen Strom ist es nur noch eine Multiplikation.

Das gilt, solange das Eisen nicht sättigt – am Betriebspunkt ist das erfüllt.

### Folie 8 – Reduktion B: eine Temperaturform für die Scheibe  *(ca. 1:30)*

Reduktion B betrifft die Scheibe. Aluminium leitet sehr gut, die Scheibe ist dünn und gibt Wärme nur langsam ab – sie ist also fast überall gleich warm.

Deshalb nehmen wir nur eine einzige Form, nämlich das stationäre FEM-Temperaturfeld, und eine Gleichung für ihr Gewicht beta: Beta strebt mit der Zeitkonstante tau gegen seinen Zielwert.

Dass eine Form genügt, haben wir nicht angenommen, sondern geprüft.

Links die Eigenwertanalyse: Die langsamste Form hat 204 Sekunden, die zweite nur 4,4 Sekunden – ein Faktor 47. Alles außer der ersten Form ist nach wenigen Sekunden abgeklungen.

Rechts der direkte Vergleich mit der vollen FEM: Mit der Zeitkonstante aus dem Eigenproblem ist der größte Fehler 0,36 Kelvin.

Im Code verwenden wir tau gleich C durch UA, also 244 Sekunden. Das gibt beim Aufheizen bis zu 3 Kelvin Fehler, im Endwert null. Der Grund: Die Scheibenunterseite sieht Luft, die von den Spulen vorgewärmt ist.

### Folie 9 – Reduktion C: RC-Netzwerk und Kalibrierung  *(ca. 1:15)*

Reduktion C betrifft Spulen und Eisen. Hier nutzen wir ein thermisches RC-Netzwerk – wie ein elektrischer Schaltkreis: Wärmekapazität entspricht einem Kondensator, Wärmeleitwert einem Widerstand.

Jede Spule hat zwei Knoten: die sichtbare Oberfläche und das träge Wicklungsinnere. Dazu kommen das Eisen und die Luft im Gerät – also sechs Knoten.

Die zwei wichtigsten Parameter, die Wärmeübergänge der Spulen, kalibrieren wir an der IR-Messung bei 7,8 Ampere: 79 und 74 Grad.

Wichtig dabei: Das Suchverfahren lässt jeweils das tatsächliche, nichtlineare Modell bis zum Gleichgewicht laufen – keine vereinfachte Handformel.

Zusammen ergibt das acht Zustandsgrößen: zwei Gewichte beta für die Scheibe und sechs Knoten. Ein Zeitschritt dauert rund drei Mikrosekunden.

### Folie 10 – Berechnungswerkzeug  *(ca. 1:15)*

So sieht das im Code aus. Alle Zahlenwerte stehen in einer einzigen Datei, params.yaml – keine Konstante ist im Code fest verdrahtet.

Offline rechnen em_solver und thermal_solver die FEM, rom.py macht die Reduktionen A und B, der HTML-Builder die Reduktion C. Online läuft nur twin_core.py – das ist das ROM.

Ein Doppelklick auf RUN startet alles und öffnet die Ansicht im Browser; rechts sehen Sie einen Screenshot. Man kann den Strom mit einem Schieberegler ändern und sieht Temperaturen und Schwebehöhe live.

[OPTIONAL: kurze Live-Demo, höchstens 30 Sekunden – Strom hochziehen, Zeitraffer mit „+“.]

Ein Stromsensor am Arduino ist softwareseitig vorbereitet; der Einbau am Versuchsstand läuft noch.

### Folie 11 – Ergebnis 1: Verlustleistungen  *(ca. 0:45)*

Zu den Ergebnissen. Bei 5 Ampere liefert die Feld-FEM insgesamt 138 Watt.

Die beiden Spulen erzeugen zusammen gut drei Viertel davon, die Scheibe etwa ein Fünftel, das Eisen vier Prozent. Das passt zum Wärmebild, in dem die Spulen die heißesten Bauteile sind.

Eine ehrliche Anmerkung zur Stromkonvention: Die Verlustrechnung setzt den gemessenen Effektivwert als Amplitude ein. Die absoluten Wattzahlen sind dadurch um den Faktor zwei zu klein. Für die Temperatur ist das unschädlich, weil die Kalibrierung den Faktor auffängt – Details auf einer Backup-Folie.

### Folie 12 – Ergebnis 2: Vergleich mit der Messung  *(ca. 1:30)*

Jetzt der Vergleich mit der Messung – und hier trennen wir bewusst.

Die stationären Spulentemperaturen trifft das Modell exakt, aber nur, weil wir genau darauf kalibriert haben. Das ist also kein Nachweis.

Der Zeitverlauf ist eine echte Vorhersage – und hier liegt das Modell daneben: In der Aufheizrampe der Außenspule heizt es zu langsam; der mittlere Fehler ist 11,5 Kelvin. Links sehen Sie die fünf Messpunkte gegen das Modell.

Bei der Scheibe misst die IR-Kamera 37 bis 40 Grad, das Modell sagt 107 – aber auf blankem Aluminium ist die IR-Messung nicht verlässlich; ein Urteil ist nicht möglich.

Und die Schwebehöhe überschätzt das Modell um etwa 7 Millimeter.

### Folie 13 – Ursachen der Abweichungen  *(ca. 1:00)*

Woran liegt das?

Erstens der Zeitverlauf: Die Endtemperatur hängt nur von den kalibrierten Wärmeübergängen ab, das Tempo aber von den Wärmekapazitäten und der Aufteilung zwischen Oberfläche und Wicklung. Die lassen sich aus einer Aufheizkurve allein nicht bestimmen – dafür fehlt eine Abkühlkurve.

Zweitens die Scheibe: Blankes Aluminium strahlt wenig ab und spiegelt die Umgebung, deshalb zeigt die Kamera zu tiefe Werte.

Drittens die Schwebehöhe: Wahrscheinlichste Ursache ist die angenommene Eisenpermeabilität von 1000, die nie gemessen wurde. Wir haben sie bewusst nicht nachträglich an die Beobachtung angepasst – sonst hätten wir eine Anpassung als Validierung verkauft.

### Folie 14 – Ausblick und Fazit  *(ca. 1:00)*

Fast alle Abweichungen haben also dieselbe Ursache: Es fehlen Messdaten. Die nächsten Schritte sind deshalb konkret: eine Abkühlkurve aufnehmen, ein mattschwarzer Messfleck für verlässliche IR-Werte, die Eisenpermeabilität messen, den Stromsensor einbauen und einen unabhängigen Messpunkt bei 5 Ampere, um die Kalibrierung zu prüfen statt nur anzupassen.

Unser Fazit: Aus einem FEM-Modell mit tausenden Unbekannten ist ein ROM mit acht Zuständen geworden, das in Mikrosekunden rechnet. Die Reduzierbarkeit ist geprüft, nicht angenommen. Und wir wissen genau, wo das Modell noch nicht stimmt und warum. Das Vorgehen lässt sich auf 3D-Modelle übertragen.

Vielen Dank für Ihre Aufmerksamkeit – wir freuen uns auf Ihre Fragen.

---

## 3. Vorbereitung der Verteidigung

### 3.1 Grundregeln

1. **Erst die Frage wiederholen oder präzisieren**, dann antworten. Das gibt Zeit und vermeidet Missverständnisse.
2. **Kurz antworten (20–40 s)**, dann auf eine Backup-Folie oder den Bericht verweisen („Details stehen in Anhang C.3“).
3. **Gemessen, angenommen und kalibriert sauber trennen.** Das ist unsere stärkste Position: Wir sagen offen, was nicht validiert ist.
4. **„Das haben wir nicht untersucht“ ist eine gültige Antwort**, am besten mit dem nächsten Schritt: „… das wäre der nächste Schritt, und zwar so: …“
5. Nicht spekulieren und keine Zahlen erfinden. Lieber: „Den genauen Wert haben wir nicht im Kopf, er steht in Tabelle A.2.“

### 3.2 Zahlen-Spickzettel

| Größe | Wert |
|---|---|
| Strom | 5,0 A eff. (Betrieb), 7,8 A eff. (Kalibrierung), 50 Hz |
| Variac | 220° ≈ 195 V → 5 A; 270° (max.) ≈ 240 V → 7,8 A |
| Scheibe | R = 80 mm, d = 3 mm, Masse 159–163 g (Kraftrechnung: 162,9 g) |
| Windungen | ca. 1000 (innen) / 500 (außen) |
| Verluste @ 5 A | Scheibe 25,81 · Eisen 5,86 · innen 52,32 · außen 54,12 · **gesamt 138,11 W** |
| FEM-Größe | Feld 8 700 Knoten / 17 028 Dreiecke (0,40 s); Wärme 697 Knoten (0,03 s) |
| Gebietsgröße | 1 m × 1 m, Dirichlet vs. Neumann: 0,77 % |
| Scheibe | C = 146,6 J/K, UA = 0,600 W/K, τ = 244 s; Eigenproblem τ₁ = 204 s, τ₂ = 4,4 s (Faktor 47) |
| ROM vs. FEM | max. 0,36 K (τ₁), 3,0 K beim Aufheizen (τ = C/UA), Endwert 0 |
| Kalibrierung | hA innen/außen = 2,474 / 2,889 W/K → 79,0 / 74,0 °C @ 7,8 A, T_amb 29 °C |
| ROM | 8 Zustände (2 β + 6 Knoten), ≈ 3,25 µs pro Schritt |
| Rampe Außenspule | RMS-Fehler 11,5 K (Modell zu langsam) |
| Schwebehöhe | Modell 11,7 mm Unterkante / 14,7 mm sichtbar; beobachtet 7–8 mm sichtbar |
| Stationär 5 A / 20 °C (Modell) | Spulen 44,0 / 41,5 °C, Eisen 46,3 °C, Scheibe (Mittel) 57,5 °C |

### 3.3 Erwartete Fragen und Antwortvorschläge

#### A. Physik und Modellannahmen

**A1. Warum darf man axialsymmetrisch rechnen?**
Alle Bauteile sind rotationssymmetrisch um die Mittelachse, und der Strom fließt in Umfangsrichtung. Dann hat das Vektorpotential nur eine φ-Komponente, und eine 2D-Rechnung in (r, z) ist exakt. Nicht erfasst sind Unsymmetrien wie eine schief schwebende Scheibe; das ist eine Grenze des Modells.

**A2. Warum ein Phasor statt einer Rechnung im Zeitbereich? Die Verluste pulsieren doch mit 100 Hz.**
Ja, die Momentanleistung pulsiert mit 100 Hz. Die thermische Zeitkonstante liegt aber bei Minuten (τ ≈ 4 min), die Wärme „sieht“ also nur den Mittelwert. Genau diesen Mittelwert liefert q = ½ σ ω² |A|². Eine Zeitbereichsrechnung wäre um Größenordnungen teurer, ohne die Temperatur zu verbessern.

**A3. Warum 20 °C Umgebung, wenn bei der IR-Messung 29 °C herrschten?**
20 °C ist der mit Ihnen vereinbarte Standardfall. Für die Kalibrierung haben wir die tatsächlichen 29 °C der Messung verwendet (Tabelle A.2, L3). Das Modell rechnet ohnehin mit der Temperaturerhöhung über der Umgebung; die Umgebung ist ein Parameter.
*(Falls nachgefragt: Für echte Messungen kann der Code die aktuelle Außentemperatur über eine Wetter-API mitschreiben. Das ist aber nicht Teil der Auswertung im Bericht.)*

**A4. Welche Werte sind gemessen, welche angenommen?** → Backup B4.
Gemessen: Geometrie, Strom, Spulentemperaturen (IR), Rampe, Schwebehöhe. Angenommen: μr und σ des Eisens, Wärmeübergänge der Scheibe, Luftknoten, Draht und Füllfaktor. Kalibriert: nur die zwei Werte hA innen und außen.

**A5. Woher kommt μr = 1000? Warum passen Sie μr nicht an die Schwebehöhe an?**
μr = 1000 ist ein typischer Wert für Baustahl. Gemessen wurde nur, *dass* Kern und Ring ferromagnetisch sind (Magnettest), nicht μr selbst. Wir haben μr bewusst nicht an die beobachtete Schwebehöhe angepasst. Sonst wäre die Schwebehöhe kein unabhängiger Test mehr, und wir würden eine Anpassung als Validierung ausgeben. Richtig ist, μr zu messen (B-H-Kurve).

**A6. Kann Sättigung die Schwebehöhe erklären?** → Backup B2.
Wir haben das geprüft: Mit Sättigungskorrektur ändert sich die Kraft um weniger als 0,1 %, die Schwebehöhe bleibt gleich. Sättigung ist also als Ursache ausgeschlossen.

**A7. Warum sind die Verluste um Faktor 2 zu klein, und warum ist das egal?** → Backup B1.
Der Multimeter misst den Effektivwert. Die Verlustrechnung setzt diesen Wert als Amplitude ein, und wegen P ∝ I² sind die Wattzahlen halb so groß. Die Temperaturen stimmen trotzdem, weil hA an gemessenen Temperaturen kalibriert ist und den Faktor auffängt. Die Kraftrechnung nutzt die echte Amplitude √2 · 5 A. Für einen Vergleich mit einer Leistungsmessung müsste man die Wattzahlen verdoppeln.

**A8. Wie groß ist die Wicklungstemperatur, und ist 178 °C gefährlich?**
178 °C bei 7,8 A ist ein Modellwert und nicht gemessen. Er ist vermutlich zu hoch, weil der innere Wärmeleitwert der Wicklung nur geschätzt ist. Ohne Messung im Wicklungsinneren können wir das nicht belegen; das nennen wir im Bericht ausdrücklich.

#### B. Numerik

**B1. Warum FEM und nicht FDM, FVM oder BEM?**
Fünf Materialbereiche mit Sprüngen in μ und σ, Drehsymmetrie mit dem Faktor 2πr und Konvektionsränder: Die FEM behandelt das ohne Sonderfälle. FDM braucht an jeder Materialgrenze Sonderbehandlung, BEM führt zu vollbesetzten Matrizen. FVM wäre möglich gewesen (Anhang C.1).

**B2. Warum eigener Code statt COMSOL oder FEMM?**
Für das ROM brauchen wir direkten Zugriff auf Matrizen, Verlustkarte und Eigenwerte, und das Online-Modell muss als reines JavaScript im Browser laufen. FEMM läuft nur unter Windows. Mit eigenem Code in Python/SciPy ist jede Gleichung nachvollziehbar und wird bei jedem Lauf geprüft (Energiebilanz, Linearität, Gebietsgröße).

**B3. Haben Sie eine Netzkonvergenzstudie gemacht?** → Backup B5.
Ehrliche Antwort: Eine systematische Netzkonvergenzstudie ist im Bericht nicht dokumentiert. Abgesichert ist die Rechnung durch die Energiebilanz, die Gebietsgrößenprüfung, die Linearität und das Skintiefen-Argument (12 mm ≫ 3 mm). Für die Schwebehöhe gibt es einen Vergleich zweier Netzfeinheiten: z_eq verschiebt sich dabei um etwa 0,7 mm. Eine vollständige Konvergenzstudie für die Verluste und Temperaturen wäre ein sinnvoller nächster Schritt.

**B4. Wie groß ist das Rechengebiet, und welche Randbedingungen gelten?**
1 m × 1 m. Feld: A = 0 auf der Achse und am Außenrand. Als Kontrolle haben wir mit einer Neumann-Randbedingung gerechnet; die Verluste unterscheiden sich um höchstens 0,77 %, das Gebiet ist also groß genug.

**B5. Warum explizites Euler? Das ist doch nicht stabil.**
Explizites Euler ist nur stabil, wenn der Zeitschritt klein gegen die Zeitkonstanten ist. Deshalb teilt der Code jeden Schritt automatisch in Teilschritte von höchstens 5 % der Zeitkonstante. Explizit haben wir gewählt, weil das ROM so ohne Bibliotheken auskommt und eins zu eins nach JavaScript übertragbar ist.

#### C. MOR und ROM

**C1. Was ist der Unterschied zwischen MOR und ROM?**
MOR (Model Order Reduction) ist das Verfahren, ROM (Reduced-Order Model) sein Ergebnis. Bei uns ist das ROM das Online-Modell in `twin_core.py` mit acht Zuständen.

**C1b. Verwenden Sie alle drei Reduktionen oder nur eine davon?** → Backup B7 / Anhang F

*Kurzantwort (10 s):*
„Alle drei gleichzeitig, jede für einen anderen Teil des Geräts. Zusammen ergeben sie die acht Zustände des ROM.“

*Ausführlich, Schritt für Schritt (wenn nachgefragt wird; dabei auf Backup B7 zeigen):*

1. **Ausgangspunkt:** „Ohne Reduktion hätten wir drei große Probleme: das Magnetfeld mit 8 700 Unbekannten, das für jeden Strom neu gelöst werden müsste, die Scheibe mit 697 Knotentemperaturen und Spulen und Eisen, die als feines Feld ebenfalls Tausende Knoten bräuchten.“
2. **Reduktion A (Verluste):** „Die Feldgleichung ist linear. Deshalb lösen wir sie nur einmal bei 5 Ampere und speichern die Verlustkarte. Für jeden anderen Strom multiplizieren wir mit (I durch 5 Ampere) zum Quadrat, wie bei einem Lautstärkeregler: dieselbe Melodie, nur lauter. Das gilt für alle Bauteile, also für die Scheibe, die Spulen und das Eisen.“
3. **Reduktion B (Scheibe):** „Die Scheibe ist fast überall gleich warm. Wir speichern ihre Temperaturform einmal und merken uns nur, wie stark sie gerade ausgeprägt ist, das Gewicht beta. Es sind zwei Gewichte: eines für die Wärme aus den Wirbelströmen, eines für die warme Luft von den Spulen darunter.“
4. **Reduktion C (Spulen, Eisen, Luft):** „Jeder dieser Körper ist fast gleich warm, also genügt ein Knoten pro Körper, wie ein Schaltplan statt einer Landkarte. Jede Spule bekommt zwei Knoten, weil ihre Oberfläche und ihr Inneres verschieden warm sind. Mit Eisen und Luft sind das sechs Knoten.“
5. **Zusammenspiel pro Zeitschritt:** „In jedem Zeitschritt läuft alles nacheinander: Zuerst skaliert A die Verluste mit dem aktuellen Strom. Dann rechnet C die sechs Knotentemperaturen. Zum Schluss rechnet B die zwei Gewichte der Scheibe, und dabei geht die Spulentemperatur aus C ein, weil die warme Luft die Scheibe mitheizt. B und C sind also gekoppelt.“
6. **Ergebnis:** „Zwei Gewichte plus sechs Knoten sind acht Zahlen statt über 9 000 Unbekannten. Ein Zeitschritt dauert etwa drei Mikrosekunden.“

*Wenn weiter gefragt wird, „Warum nicht nur eine?“:*
„Jede Reduktion deckt nur einen Teil ab. Mit A allein müssten wir die Temperaturen weiterhin mit der vollen FEM rechnen. Mit B allein hätten wir keine Spulen, obwohl sie drei Viertel der Wärme erzeugen. Mit C allein hätten wir keine Temperaturverteilung in der Scheibe.“

*Ehrliche Einschränkung (nur wenn nach σ(T) gefragt wird):*
„Der Leitfähigkeitsfaktor σ(T) aus Reduktion A wird im Code nur für die Scheibe angewendet. Bei den Spulen steckt die Temperaturabhängigkeit indirekt in den kalibrierten hA-Werten. Am Kalibrierpunkt ist das exakt, weit davon entfernt ist es eine Vereinfachung.“

*Code-Beleg:* `twin_core.py`, Methode `_rom_step`: A in Zeile 398, C in Zeile 407–432, B in Zeile 447–452.

**C2. Ist das „echte“ MOR? Sie nutzen ja kein POD, Krylov oder Balanced Truncation.**
Unsere Reduktion ist physikalisch begründet:
- **A** nutzt die Linearität der Feldgleichung und ist exakt.
- **B** ist eine Projektion auf eine einzige Form, das stationäre Feld. Dass eine Form reicht, belegt die Eigenwertlücke (τ₁/τ₂ = 47). Ein POD auf Aufheiz-Snapshots würde wegen dieser Lücke eine sehr ähnliche erste Mode liefern.
- **C** ist ein konzentriertes RC-Netzwerk und nicht aus einer Projektion abgeleitet.

Formale Verfahren wie POD wären der nächste Schritt, wenn mehr Moden nötig werden, etwa in 3D.

**C3. Warum verwenden Sie τ = C/UA = 244 s statt τ₁ = 204 s, wenn τ₁ genauer ist?**
C/UA ist physikalisch interpretierbar und lässt sich an Messungen kalibrieren. Der Endwert ist in beiden Fällen exakt. Der Unterschied beträgt beim Aufheizen höchstens 3 K und ist damit deutlich kleiner als der Spulenfehler von 11,5 K. τ₁ zu verwenden wäre eine kleine, sinnvolle Verbesserung.

**C4. Woher kommen die acht Zustände?**
Zwei Gewichte β für die Scheibe: ein Anteil aus den Wirbelströmen und ein Anteil aus der von den Spulen erwärmten Luft darunter. Dazu sechs RC-Knoten: Oberfläche und Wicklung beider Spulen, Eisen und Luft im Gerät.

**C5. Wie schnell ist das ROM wirklich?**
Etwa 3,25 µs pro Zeitschritt in Python. Das ist ungefähr 4 · 10⁵-mal schneller als ein FEM-Lauf aus Feld und Wärme.

#### D. Validierung

**D1. Ist Ihre Kalibrierung nicht zirkulär?**
Doch, für die stationären Spulenwerte schon. Deshalb nennen wir diese Übereinstimmung ausdrücklich „kalibriert, kein Nachweis“. Echte Vorhersagen sind die Rampe, die Scheibe und die Schwebehöhe, und dort stimmt das Modell noch nicht. Für einen Nachweis brauchen wir einen unabhängigen Messpunkt, zum Beispiel stationär bei 5 A.

**D2. Wie genau ist die IR-Messung?**
Auf den lackierten Spulen ist sie brauchbar. Auf blankem Aluminium ist die Emissivität sehr klein und unbekannt, deshalb sind die Werte auf der Scheibe und auf blankem Metall unzuverlässig. Die Zeitstempel der Rampe sind auf etwa ±10 s genau.

**D3. Warum ist das Modell in der Rampe zu langsam?**
Das Aufheiztempo hängt von den Wärmekapazitäten und der Aufteilung zwischen Oberfläche und Wicklung ab. Beide lassen sich aus einer Aufheizkurve allein nicht trennen. Mit einer Abkühlkurve (Strom aus) lassen sich Kapazität und Wärmeabgabe getrennt bestimmen.

**D4. 107 °C an der Scheibe gegen 37–40 °C gemessen – ist das Modell dort falsch?**
Das lässt sich derzeit nicht entscheiden. Die IR-Werte auf blankem Aluminium sind zu tief, und die Wärmeübergänge der Scheibe im Modell sind nur geschätzt. Klärung bringt ein mattschwarzer Messfleck oder ein Kontaktfühler direkt nach dem Abschalten.

**D5. Warum 7 mm Abweichung bei der Schwebehöhe?**
Wahrscheinlichste Ursache ist μr des Eisens, das nicht gemessen ist; Sättigung ist ausgeschlossen (A6). Außerdem rechnet das Feldmodell mit fester Scheibenhöhe, also ohne Rückwirkung der Bewegung.

#### E. Digital Twin und Einordnung

**E1. Ist das schon ein Digital Twin? Es fließen ja noch keine Live-Daten.**
Streng genommen ist es derzeit ein digitales Modell mit vorbereitetem Datenpfad. Mit eingebautem Stromsensor fließen Messdaten automatisch ins Modell; das wäre ein „digitaler Schatten“. Ein Digital Twin im vollen Sinn braucht auch den Rückweg, also Entscheidungen oder Eingriffe am Gerät. Das ist der Schritt zum Thermomanagement.

**E2. Wo ist das „Thermomanagement“?**
Das ROM liefert die Grundlage dafür: Temperaturen, die man nicht messen kann, in Echtzeit, also auch die Wicklungstemperatur. Darauf lassen sich Strom- oder Zeitgrenzen und Warnungen aufbauen. Eine solche Regelung ist noch nicht umgesetzt; der Titel beschreibt das Projektziel.

**E3. Wie lässt sich das auf 3D übertragen?**
Das Vorgehen bleibt gleich: FEM einmal lösen, Reduzierbarkeit prüfen (Linearität, Eigenwertlücke), online ein ROM rechnen. In 3D wird die FEM größer, und für die Reduktion bieten sich dann formale Verfahren wie POD an.

**E4. Haben Sie KI-Werkzeuge verwendet?**
Ja, bei der Implementierung haben wir ein in die Entwicklungsumgebung integriertes KI-Werkzeug genutzt. Die physikalischen Annahmen, die Prüfkriterien (Energiebilanz, Linearität, Gebietsgröße) und die Bewertung der Ergebnisse gegen die Messung lagen beim Team. Jede Zahl im Bericht ist mit `report_numbers.py` reproduzierbar.
*(Nur so antworten, wenn es für euer Team zutrifft, und vorher intern abstimmen.)*

**E5. Was würden Sie mit mehr Zeit als Erstes tun?**
Eine Abkühlkurve aufnehmen. Sie ist die Messung mit dem größten Nutzen, weil sie die Wärmekapazitäten bestimmt und damit den größten Fehler, den Zeitverlauf, direkt angeht.

### 3.4 Stolpersteine: kleine Unstimmigkeiten, auf die man angesprochen werden kann

1. **Scheibenmasse:** Im Bericht steht jetzt 159–163 g (gemessen); die Kraftrechnung nutzt 162,9 g. Falls gefragt: Für die Gewichtskraft wurde der obere Messwert verwendet.
2. **Schwebehöhe im Screenshot:** Die HTML-Ansicht zeigt 11,9 mm, der Bericht 11,7 mm (Unterkante). Beide Werte kommen aus demselben Kräftegleichgewicht der Feld-FEM (`compute_lift_force`), aber aus zwei getrennten Suchläufen mit eigenem Netz. Laut Code-Kommentar verschiebt sich z_eq je nach Netzfeinheit um etwa 0,7 mm. 0,2 mm Unterschied liegen also innerhalb der Netzempfindlichkeit, und beide Werte sind gleich weit von der Beobachtung (7–8 mm sichtbar) entfernt.
3. **Scheibentemperatur im Screenshot:** „T_ss target 63 °C“ ist das **Maximum** des stationären FEM-Referenzfelds, hochskaliert mit (I/I_ref)² (T_amb + ΔT_max,ref = 20 + 43,3 °C). Die 57,5 °C im Bericht sind der **Mittelwert** der Scheibe aus dem vollständigen ROM bei 5 A und 20 °C.
4. **Titel „Thermomanagement“:** siehe E2. Nicht behaupten, dass schon geregelt wird.

