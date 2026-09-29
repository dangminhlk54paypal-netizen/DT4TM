/*
 * thermal_sensor.ino — DT4TM current logger (Arduino UNO R3/R4)
 *
 * ONE job: measure the RMS coil current I_rms(t) with an ACS712-20A and stream
 * it to the PC. That current is the INPUT of the digital twin — data_io.py
 * feeds it into TwinState.step(I, dt), which computes the temperature field.
 * Temperature is a model OUTPUT here; this rig has no temperature sensor, so
 * the firmware measures none. (`calibrate_from_file()` on the Python side needs
 * a measured temperature and therefore stays unusable with this rig — that is a
 * known, accepted limit, not something the firmware can fix.)
 *
 * Serial CSV at 1 Hz, 9600 baud:
 *
 *     millis,I_rms_A
 *
 * Lines starting with '#' are diagnostics and are skipped by data_io.py.
 *
 * Wiring (UNO R3/R4 pin-compatible):
 *   ACS712-20A OUT       -> A0   (+ 0.1uF ceramic cap OUT->GND at the Arduino
 *                                  end, for noise filtering — see BOM)
 *   ACS712-20A VCC       -> 5V
 *   ACS712-20A GND       -> GND
 *   ACS712-20A IP+ / IP- -> in SERIES with one coil-supply conductor
 *                           (190-270V AC mains side)
 *
 * !! SAFETY !! The coil circuit carries 190-270V AC mains. IP+/IP- are
 * galvanically isolated (Hall effect, ~2.1kV) from OUT/VCC/GND — never bridge
 * the two sides, never touch IP+/IP- while the Variac is on. Always set the
 * Variac dial to 0 before making or changing any IP+/IP- wiring.
 *
 * No external libraries. Compiles as-is on the UNO R4 (Renesas) and the R3 (AVR).
 */

// --- ACS712-20A current sensor ---------------------------------------------
// Vout = Vcc/2 + 0.100 V/A * I(t) (the module has a built-in Vcc/2 bias, no
// external biasing needed). We RMS the AC component around the MEASURED mean,
// not an assumed 2.5V, since both the Arduino's actual 5V rail and the module's
// bias have tolerance and drift.
#define ACS712_PIN A0
#define ACS712_SENSITIVITY_V_PER_A 0.100
#define ADC_VREF_V 5.0
#define ADC_COUNTS 1023.0   // 10-bit; the UNO R4 also defaults to 10-bit unless
                            // analogReadResolution() is called (it is not).

// One-point calibration against a multimeter at the rig's 190V->5A operating
// point (params.yaml validation_data). Leave at 1.0 until measured, then set to
//     ACS712_CAL_SCALE = I_multimeter / I_reported_here
// It absorbs the tolerance of BOTH nominal constants above (the 5V rail and the
// module's V/A sensitivity), which are datasheet values, not measured ones.
#define ACS712_CAL_SCALE 1.0

// The sampling burst is bounded by TIME, not by a sample COUNT. True RMS is only
// exact over an INTEGER number of mains periods, so that is what we hold fixed.
// A fixed sample count instead ties accuracy to the board's ADC speed: 1000
// samples span 5.6 mains cycles on the AVR's ~112us analogRead() but only ~1.25
// on the R4's faster ADC, which biases the result by a phase-dependent several
// percent (see docs/CHANGELOG.md, WP-ACS). Bounding by time is correct on any
// board, whatever its ADC speed.
#define MAINS_FREQ_HZ 50.0
#define I_WINDOW_CYCLES 5    // 5 cycles @ 50Hz = exactly 100 ms
const unsigned long I_WINDOW_US =
    (unsigned long)(1000000.0 * I_WINDOW_CYCLES / MAINS_FREQ_HZ);

const unsigned long INTERVAL_MS = 1000;
unsigned long lastRead = 0;

// True RMS of the AC component over an integer number of mains cycles:
// single-pass sum + sum-of-squares, mean subtracted at the end, so no
// per-sample buffer is needed. Accumulators are `double` (true 64-bit on the
// R4's ARM core) because sumSq/n and mean*mean are two nearly-equal numbers
// around the 2.5V bias, and their difference loses precision in 32-bit float
// at low current. Optionally reports the sample count and the DC bias.
float readCurrentRMS(uint32_t *n_out, float *bias_out) {
  double sum = 0.0, sumSq = 0.0;
  uint32_t n = 0;
  unsigned long t0 = micros();
  while ((unsigned long)(micros() - t0) < I_WINDOW_US) {
    double v = analogRead(ACS712_PIN) * (ADC_VREF_V / ADC_COUNTS);
    sum += v;
    sumSq += v * v;
    n++;
  }
  if (n < 2) {
    if (n_out) *n_out = n;
    return NAN;
  }
  double mean = sum / n;
  double variance = (sumSq / n) - (mean * mean);
  if (variance < 0.0) variance = 0.0;   // guard against rounding near 0A
  if (n_out) *n_out = n;
  if (bias_out) *bias_out = (float)mean;
  return (float)(sqrt(variance) / ACS712_SENSITIVITY_V_PER_A * ACS712_CAL_SCALE);
}

void setup() {
  Serial.begin(9600);
  while (!Serial) { delay(1); }   // the R4's native USB CDC needs this
  delay(500);                     // let the sensor board settle

  // Startup diagnostics. The DC bias is the useful one: a correctly wired and
  // powered ACS712 sits near Vcc/2 (~2.5V). A floating A0 (sensor not connected)
  // drifts far from that, so this line tells you the sensor is really there
  // before you trust any current reading.
  uint32_t n = 0;
  float bias = NAN, i0 = 0.0;
  i0 = readCurrentRMS(&n, &bias);
  Serial.print("# ADC burst: ");
  Serial.print(n);
  Serial.print(" samples / ");
  Serial.print(I_WINDOW_CYCLES);
  Serial.print(" mains cycles (");
  Serial.print(I_WINDOW_US);
  Serial.println(" us)");
  Serial.print("# DC bias: ");
  Serial.print(bias, 3);
  Serial.println(" V  (expect ~2.5V; far off => ACS712 not wired/powered)");
  Serial.print("# noise floor at startup: ");
  Serial.print(i0, 3);
  Serial.println(" A  (measure with the Variac at 0 to get the true baseline)");
  Serial.println("# millis,I_rms_A");
}

void loop() {
  unsigned long now = millis();
  if (now - lastRead < INTERVAL_MS) return;
  lastRead = now;

  float I_rms = readCurrentRMS(NULL, NULL);

  Serial.print(now);
  Serial.print(",");
  Serial.println(I_rms, 3);
}
