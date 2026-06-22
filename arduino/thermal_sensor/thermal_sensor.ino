/*
 * thermal_sensor.ino — DT4TM sensor firmware (see SENSOR_PLAN.md)
 *
 * Two Type-K thermocouples via MAX31855 breakouts (SPI), one at the copper
 * core, one at the disc bottom. Prints CSV at 1 Hz over Serial:
 *
 *     millis,T_core_degC,T_disc_degC
 *
 * On a thermocouple fault, the corresponding field is printed as "nan" and a
 * "# FAULT ..." line is sent first; data_io.py (Python side) skips both.
 *
 * Wiring (Arduino Uno/Nano, hardware SPI: SCK=13, MISO=12):
 *   MAX31855 #1 (core) CS -> D10
 *   MAX31855 #2 (disc) CS -> D9
 *
 * Library: Adafruit MAX31855 library (Arduino IDE Library Manager).
 */
#include <Adafruit_MAX31855.h>

#define MAXCS_CORE 10
#define MAXCS_DISC 9

Adafruit_MAX31855 tc_core(MAXCS_CORE);
Adafruit_MAX31855 tc_disc(MAXCS_DISC);

const unsigned long INTERVAL_MS = 1000;
unsigned long lastRead = 0;

void setup() {
  Serial.begin(9600);
  while (!Serial) { delay(1); }
  delay(500);  // let the MAX31855 boards power up before the first read
  Serial.println("# millis,T_core_degC,T_disc_degC");
}

float readThermocouple(Adafruit_MAX31855 &tc, const char *label) {
  double t = tc.readCelsius();
  if (isnan(t)) {
    uint8_t fault = tc.readError();
    Serial.print("# FAULT ");
    Serial.print(label);
    Serial.print(": ");
    if (fault & MAX31855_FAULT_OPEN)        Serial.println("open circuit (no thermocouple attached)");
    else if (fault & MAX31855_FAULT_SHORT_GND) Serial.println("short to GND");
    else if (fault & MAX31855_FAULT_SHORT_VCC) Serial.println("short to VCC");
    else                                     Serial.println("unknown");
    return NAN;
  }
  return (float)t;
}

void loop() {
  unsigned long now = millis();
  if (now - lastRead < INTERVAL_MS) return;
  lastRead = now;

  float T_core = readThermocouple(tc_core, "T_core");
  float T_disc = readThermocouple(tc_disc, "T_disc");

  Serial.print(now);
  Serial.print(",");
  if (isnan(T_core)) Serial.print("nan"); else Serial.print(T_core, 2);
  Serial.print(",");
  if (isnan(T_disc)) Serial.print("nan"); else Serial.print(T_disc, 2);
  Serial.println();
}
