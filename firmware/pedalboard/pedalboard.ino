// Pédalier de scène : Seeed Studio XIAO ESP32S3, 7 pédales, 7 LED.
// Protocole : docs/pedalier/protocole.md. NON COMPILÉ ni essayé sur le matériel (à vérifier).
//
// Câblage :
//   pédales  : D0..D6 -> interrupteur -> GND (résistance de rappel interne)
//   LED      : 74HC595 (alimenté en 3,3 V) : D8 = DS (données), D9 = SHCP (horloge), D10 = STCP (verrou),
//              /OE à GND, /MR à 3,3 V ; sorties Q0..Q6 -> résistance 330 ohms -> LED -> GND
//   pédales 1 à 6 = emplacements du boîtier, pédale 7 = blackout
//
// Carte Arduino : « XIAO_ESP32S3 », option « USB CDC On Boot : Enabled ».

#include <Arduino.h>

static const char *VERSION = "1.0";
static const uint8_t N = 7;
static const uint8_t BTN_PIN[N] = {D0, D1, D2, D3, D4, D5, D6};
static const uint8_t PIN_DATA = D8, PIN_CLK = D9, PIN_LATCH = D10;
// Niveau lu quand la pédale est enfoncée : LOW pour un contact normalement ouvert (câblé vers GND).
// Pour une pédale « normalement fermée » (certaines pédales de sustain), mettre HIGH.
static const uint8_t PRESSED_LEVEL = LOW;

static const unsigned long SCAN_MS = 2;          // période de balayage des pédales
static const uint8_t DEBOUNCE_SCANS = 8;         // 8 x 2 ms = 16 ms d'état stable
static const unsigned long LINK_LOST_MS = 5000;  // sans nouvelle du Pi : LED clignotantes

static bool stable[N];            // état validé de chaque pédale (true = enfoncée)
static uint8_t counter[N];        // balayages consécutifs différents de l'état validé
static uint8_t ledMask = 0;       // bit i = LED de la pédale i+1
static unsigned long lastRx = 0;  // dernière ligne reçue du Pi
static bool everHeard = false;    // le Pi s'est manifesté depuis le démarrage
static char line[48];
static uint8_t lineLen = 0;

static void writeLeds(uint8_t mask) {
  digitalWrite(PIN_LATCH, LOW);
  shiftOut(PIN_DATA, PIN_CLK, MSBFIRST, mask);
  digitalWrite(PIN_LATCH, HIGH);
}

static void hello() {
  Serial.print("HELLO ");
  Serial.print(VERSION);
  Serial.print(' ');
  Serial.println(N);
}

// LED <6 chiffres 0/1> <0/1> : emplacements 1 à 6, puis blackout (pédale 7)
static void handleLed(const char *args) {
  if (strlen(args) < 8 || args[6] != ' ') return;
  uint8_t mask = 0;
  for (uint8_t i = 0; i < 6; i++) {
    if (args[i] == '1') mask |= (1 << i);
    else if (args[i] != '0') return;
  }
  if (args[7] == '1') mask |= (1 << 6);
  else if (args[7] != '0') return;
  ledMask = mask;
}

static void handleLine(const char *text) {
  lastRx = millis();
  everHeard = true;
  if (strcmp(text, "WHO") == 0) hello();
  else if (strcmp(text, "PING") == 0) Serial.println("PONG");
  else if (strncmp(text, "LED ", 4) == 0) handleLed(text + 4);
}

static void readSerial() {
  while (Serial.available()) {
    char c = (char)Serial.read();
    if (c == '\r') continue;
    if (c == '\n') {
      line[lineLen] = 0;
      if (lineLen > 0) handleLine(line);
      lineLen = 0;
    } else if (lineLen < sizeof(line) - 1) {
      line[lineLen++] = c;
    } else {
      lineLen = 0;  // ligne trop longue : on repart de zéro
    }
  }
}

static void scanButtons() {
  for (uint8_t i = 0; i < N; i++) {
    bool pressed = (digitalRead(BTN_PIN[i]) == PRESSED_LEVEL);
    if (pressed == stable[i]) {
      counter[i] = 0;
    } else if (++counter[i] >= DEBOUNCE_SCANS) {
      stable[i] = pressed;
      counter[i] = 0;
      Serial.print("BTN ");
      Serial.print(i + 1);
      Serial.println(pressed ? " 1" : " 0");
    }
  }
}

void setup() {
  Serial.begin(115200);  // sans effet sur l'USB natif
  Serial.setTxTimeoutMs(0);  // ne jamais bloquer le balayage si personne ne lit (à vérifier selon la version du cœur ESP32)
  pinMode(PIN_DATA, OUTPUT);
  pinMode(PIN_CLK, OUTPUT);
  pinMode(PIN_LATCH, OUTPUT);
  for (uint8_t i = 0; i < N; i++) {
    pinMode(BTN_PIN[i], INPUT_PULLUP);
    stable[i] = (digitalRead(BTN_PIN[i]) == PRESSED_LEVEL);  // pédale tenue au démarrage : pas d'événement
  }
  writeLeds(0);
  hello();
}

void loop() {
  static unsigned long nextScan = 0;
  readSerial();
  unsigned long now = millis();
  if ((long)(now - nextScan) >= 0) {
    nextScan = now + SCAN_MS;
    scanButtons();
  }
  // Liaison perdue (ou jamais établie) : toutes les LED clignotent lentement.
  bool lost = !everHeard || (now - lastRx > LINK_LOST_MS);
  writeLeds(lost ? ((now / 500) % 2 ? 0x7F : 0x00) : ledMask);
}
