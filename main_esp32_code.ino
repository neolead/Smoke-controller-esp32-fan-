#include <WiFi.h>
#include <WebServer.h>
#include <Preferences.h>
#include <ArduinoOTA.h>
#include <TroykaMQ.h>
#include <cmath>
#include <math.h> 

const char* ssid = "teeeest";
const char* password = "test";
const char* ns = "fanCtrl";
const int PWM_CHANNEL1 = 0; const int PWM_CHANNEL2 = 1; const int PWM_CHANNEL3 = 2;

#define FAN_PIN1 13
#define RPM_PIN1 12
#define FAN_PIN2 14
#define RPM_PIN2 27
#define FAN_PIN3 26
#define RPM_PIN3 25 
#define MQ2PIN          34 //pin d34

#define PWM_FREQ 30000
#define PWM_RES 10
#define INIT_PERCENT 100
#define PERCENT_STEP 5
// #define INTERVAL1_GET_DATA 600000  // длительность включения вентилятора 10мин
#define INTERVAL_CALIBRATE 600000
unsigned long millis_INTERVAL_CALIBRATE=0;
#define INTERVAL_MQ2 2000
#define INTERVAL2_MQ2 3000
int INTERVAL1_GET_DATA = 600000;
unsigned long millis_mq2=0;
unsigned long millis2_mq2=0;
unsigned long lastFan3StartTime = 0;  // Время последнего включения FAN3
int i1_get_data = 10 ;
bool fan3Started = false;
bool autocalibrate = false;
float totalval = 0.0;
float totalvalx = 0.0;
float totalvaly = 0.0;
float rsValue = 0.0;
static unsigned long lastSampleTime = 0;
static int i = 0;
static float totalval1 = 0;
float alpha = 0.1; // Коэффициент сглаживания
float ema = 0; // Экспоненциальное скользящее среднее

volatile unsigned long pc1 = 0, pc2 = 0, pc3 = 0, lpc1 = 0, lpc2 = 0, lpc3 = 0, lpt = 0;
volatile int p1 = INIT_PERCENT, p2 = INIT_PERCENT, p3 = INIT_PERCENT,limitx = INIT_PERCENT;
volatile unsigned long rpm1 = 0, rpm2 = 0, rpm3 = 0, remtime = 0, zero = 0;

MQ2 mq2(MQ2PIN);

WebServer s(80);
Preferences prefs;

void fanCounter1() { pc1++; }
void fanCounter2() { pc2++; }
void fanCounter3() { pc3++; }

float readAverageSmokeRatio(int readings, int delayTime) {
  float total = 0.0;
   total = totalval;
   return total ; // Возвращаем среднее значение
}

void checkSmokeLevelAndControlFan3() {
  float smoke = readAverageSmokeRatio(3, 200);
    float  onlower = prefs.getFloat("onlower", 0);
      float  onhigher = prefs.getFloat("onhigher", 0);
      float  offlower = prefs.getFloat("offlower", 0);
      float  offhigher = prefs.getFloat("offhigher", 0);

  if (prefs.getUInt("en_autofan", 0) == 1) {
    //Serial.println("Automatic antismoker is on");
   if (!fan3Started) {
     Serial.println("Checking if fan is off (antismoker is on)");
     // Если FAN3 не был включен, то проверяем уровень дыма и включаем, если необходимо
     ////////        if (!std::isinf(smoke) && (smoke <= -19.00 || smoke >= 9.0)) {
     
  // HERE // if (smoke <= -19.00 || smoke >= 10.2) {

    if (smoke <= onlower || smoke >= onhigher) {
      //if (analogRead(34) == 4095) {
      // Уровень дыма считается высоким, включаем FAN3
      Serial.println("smoke lvl");
      Serial.println(smoke);
      Serial.println("Try on fan");
      startFan3();                  //    }
    }
  } else if (fan3Started) {
    // FAN3 был включен
      if (millis() - lastFan3StartTime >= INTERVAL1_GET_DATA) {
          Serial.println("Millis is more interval");
          if  (smoke > offlower && smoke < offhigher){
          // Прошло 10 минут, выключаем FAN3
              Serial.println("Try off fan 10 min");
              stopFan3();
          }
          else if (smoke <= -30.00 || analogRead(34) == 4095 || (smoke > offlower && smoke < offhigher)) {
              Serial.println("smoke <= -30.00 || analogRead(34) == 4095 || (smoke > 1.0 && smoke < 9.0");
                stopFan3();
        // Условия для выключения FAN3 не выполнены, продолжаем включенным
        Serial.println("Stop fan");
          }else {
            // Вентилятор включен,дым не упал... ничего не делаем.
            lastFan3StartTime = millis();
            }
      }
  }
 }else  if (prefs.getUInt("en_autofan", 0) == 0){
 Serial.println("Automatic antismoker is off");
 }
}

void startFan3() { 
  fan3Started = true;
  lastFan3StartTime = millis();
  limitx = prefs.getUInt("fan_limit", 80);
  setSpeed3edit(limitx); // Вызов setSpeed3 с максимальной скоростью
}



void stopFan3() {
  // Выключаем FAN3
  ledcWrite(PWM_CHANNEL3, 0);
  prefs.putUInt("f3", 0);
  fan3Started = false;
}


void root() {
   String h = "<html><head><style>";
  
  h += "input[type='range'] {";
  h += "-webkit-appearance: none; appearance: none; width: 50%; height: 35px; background: #ddd;";
  h += "outline: none; opacity: 0.7; transition: opacity .2s;}";
  h += "input[type='range']:hover {opacity: 1;}";
  h += "input[type='range']::-webkit-slider-thumb {";
  h += "-webkit-appearance: none; appearance: none; width: 25px; height: 25px;";
  h += "background: #4CAF50; cursor: pointer; border-radius: 50%;}";
  h += "input[type='range']::-moz-range-thumb {";
  h += "width: 25px; height: 25px; background: #4CAF50; cursor: pointer; border-radius: 50%;}";
  h += "input[type='number'] {width: 10ch;}";
  h += "</style></head><body><h1>Fan Control</h1>";

  // Fan 1
  h += "<p>Fan 1 [FAN_PIN1(Lower common Main)((Y):" + String(FAN_PIN1) + ", RPM_PIN1(B):" + String(RPM_PIN1) + "] RPM: <span id='rpm1'>" + String(rpm1) + "</span> RPM</p>";
  h += "<input type='range' min='0' max='100' step='" + String(PERCENT_STEP) + "' id='s1' value='" + String(p1) + "' onchange='sS1()'>";
  
  // Fan 2
  h += "<p>Fan 2 [FAN_PIN2(Basement Server Room)(Y):" + String(FAN_PIN2) + ", RPM_PIN2(B):" + String(RPM_PIN2) + "] RPM: <span id='rpm2'>" + String(rpm2) + "</span> RPM</p>";
  h += "<input type='range' min='0' max='100' step='" + String(PERCENT_STEP) + "' id='s2' value='" + String(p2) + "' onchange='sS2()'>";

  bool en_autofan = prefs.getUInt("en_autofan", 0);
  bool en_autocalibrate = prefs.getUInt("en_ac",0);
  int fan_limit = prefs.getUInt("fan_limit", 0);
  float calme = prefs.getFloat("calibr", 0);
  
  // Fan 3
  h += "<p>Fan 3 [FAN_PIN3(Smoke)(Y):" + String(FAN_PIN3) + ", RPM_PIN3(B):" + String(RPM_PIN3) + "] RPM: <span id='rpm3'>" + String(rpm3) + "</span> RPM, State: " + (fan3Started ? "On" : "Off") + "</p>";
  h += "<input type='range' min='0' max='100' step='" + String(PERCENT_STEP) + "' id='s3' value='" + String(p3) + "' onchange='sS3()'>";
  h += "<br><p>Smoke Level: <span id='smoke'>" + String(readAverageSmokeRatio(2, 200)) + "</span>";
  h += "<p>Time until next check: <span id='remtime'>"+ String(remtime) + "</span> seconds</p>";
  h += "Calibrate  <input type='number' step='0.01' id='calz' value='" + String(calme) + "' onchange='updateCalibrate()'>";
  h += "<script>";
  h += "function updateCalibrate() {";
  h += "  var calibrate = document.getElementById('calz').value;";
  h += "  fetch('/calibrate?value=' + calibrate);";
  h += "}";
  h += "function updateAutoFan() {";
  h += "  var isChecked = document.getElementById('enableAutoFan').checked ? 1 : 0;";
  h += "  fetch('/setAutoFan?value=' + isChecked);";
  h += "}";
  h += "function updateAutoCalibrate() {";
  h += "  var isChecked = document.getElementById('enableAutoCalibrate').checked ? 1 : 0;";
  h += "  fetch('/setCalibrate?value=' + isChecked);";
  h += "}";
  h += "function updateAutoSmokeLimit() {";
  h += "  var limit = document.getElementById('autoSmokeLimit').value;";
  h += "  fetch('/setAutoSmokeLimit?value=' + limit);";
  h += "}";
  h += "</script>";

  // Scripts
  h += "<script>function sS1(){var s=document.getElementById('s1').value;fetch('/set1?s1='+s).then(r=>r.text()).then(d=>{document.getElementById('rpm1').textContent=d;});}";
  h += "function sS2(){var s=document.getElementById('s2').value;fetch('/set2?s2='+s).then(r=>r.text()).then(d=>{document.getElementById('rpm2').textContent=d;});}";
  h += "function sS3(){var s=document.getElementById('s3').value;fetch('/set3?s3='+s).then(r=>r.text()).then(d=>{document.getElementById('rpm3').textContent=d;});}";
  h += "setInterval(function(){fetch('/get1').then(r=>r.text()).then(d=>{document.getElementById('rpm1').textContent=d;});";
  h += "fetch('/get2').then(r=>r.text()).then(d=>{document.getElementById('rpm2').textContent=d;});";
  h += "fetch('/get3').then(r=>r.text()).then(d=>{document.getElementById('rpm3').textContent=d;});},10000);";
  h += "setInterval(function(){fetch('/getSmoke').then(r=>r.text()).then(d=>{document.getElementById('smoke').textContent=d;});";
  //h += "fetch('/getAnalogRead34').then(r=>r.text()).then(d=>{document.getElementById('analogRead34').textContent=d;});";
  h += "fetch('/remtime').then(r => r.text()).then(d => {document.getElementById('remtime').textContent = d;});";
  h += "}, 3000);</script>";

  float  onlower = prefs.getFloat("onlower", 0);
  float  onhigher = prefs.getFloat("onhigher", 0);
  float  offlower = prefs.getFloat("offlower", 0);
  float  offhigher = prefs.getFloat("offhigher", 0);
  //prefs.putUInt("en_autofan", value);
  //int remtime = (millis() - lastFan3StartTime);
  unsigned long elapsedTime = millis() - lastFan3StartTime;
  unsigned long remainingTime = INTERVAL1_GET_DATA - elapsedTime;
  int i1_get_data = prefs.getInt("ttl2");
  // Additional Info
  
  h += "<input type='checkbox' id='enableAutoFan' " + String(en_autofan ? "checked" : "") + " onchange='updateAutoFan()'> Enable AutoSmoke<br>" ;
  h += "<input type='checkbox' id='enableAutoCalibrate' " + String(en_autocalibrate ? "checked" : "") + " onchange='updateAutoCalibrate()'> Enable AutoCalibrate<br>" ;
  h += "<br>Speed Fan limit<input type='number' id='autoSmokeLimit' value='" + String(fan_limit) + "' onchange='updateAutoSmokeLimit()'>";
  h += "<br>Time after detect in min *def* 10min<input type='number' id='tl' value='" + String(i1_get_data) + "' onchange='updatetl()'>";
  
  //h += "<p>Analog Read(34): <span id='analogRead34'>" + String(analogRead(34)) + "</span></p>";
  
  
  
  h += "<br><br><table><tr><td><input type='number' id='onlower' value='" + String(onlower) + "' onchange='updateonlower()'><p>Value for start fan (lower)<br>(default:-19.00)</p></td>";
  h += "<td><input type='number' id='onhigher' value='" + String(onhigher) + "' onchange='updateonhigher()'><p>Value for start fan (higher)<br>(default:10.2)</p></td></tr>";
  h += "<tr><td><input type='number' id='offlower' value='" + String(offlower) + "' onchange='updateofflower()'><p>Value for stop fan (lower)<br>(default:1.0)</p></td>";
  h += "<td><input type='number' id='offhigher' value='" + String(offhigher) + "' onchange='updateoffhigher()'><p>Value for stop fan (higher)<br>(default:9.5)</p></td></tr></table>";
h += "<script>";
h += "function updatetl() {";
h += "  var limit = document.getElementById('tl').value;"; // Correct the ID here
h += "  fetch('/settlm?value=' + limit);"; // Ensure your endpoint matches
h += "}";
h += "function updateonlower() {";
h += "  var limit = document.getElementById('onlower').value;"; // Correct the ID here
h += "  fetch('/setonlower?value=' + limit);"; // Ensure your endpoint matches
h += "}";
h += "function updateonhigher() {";
h += "  var limit = document.getElementById('onhigher').value;"; // Correct the ID here
h += "  fetch('/setonhigher?value=' + limit);"; // Ensure your endpoint matches
h += "}";
h += "function updateofflower() {";
h += "  var limit = document.getElementById('offlower').value;"; // Correct the ID here
h += "  fetch('/setofflower?value=' + limit);"; // Ensure your endpoint matches
h += "}";
h += "function updateoffhigher() {";
h += "  var limit = document.getElementById('offhigher').value;"; // Correct the ID here
h += "  fetch('/setoffhigher?value=' + limit);"; // Ensure your endpoint matches
h += "}";
h += "</script>";
h += "</body></html>";
s.send(200, "text/html", h);
}

void getSmoke() {
  int maxval = 
  s.send(200, "text/plain", "avg:" + String(readAverageSmokeRatio(2, 200)) + "  cur:" + String(mq2.readRatio()) + " ppm:" + String(mq2.readSmoke()) );
  //s.send(200, "text/plain", "cur:" + String(mq2.readRatio()) );
}

void getAnalogRead34() {
  s.send(200, "text/plain", String(analogRead(34)));
}



void getRemainingTime() {
  if (fan3Started){
  unsigned long elapsedTime = millis() - lastFan3StartTime;
  unsigned long remainingTime = INTERVAL1_GET_DATA - elapsedTime;
  s.send(200, "text/plain", String(remainingTime / 1000));  // convert milliseconds to seconds
  }
  if (!fan3Started){
    s.send(200, "text/plain", String(zero));  // convert milliseconds to seconds
  }
}
void setSpeed1() {
  String sp = s.arg("s1"); Serial.println(String(s.arg("s1")));  
  p1 = sp.toInt();  
  int dc = map(p1, 0, 100, 0, 1024);  
  ledcWrite(PWM_CHANNEL1, dc);  
  rpm1 = map(p1, 0, 100, 0, 11000);
  prefs.putUInt("f1", p1);  Serial.print("Value of sp: ");  Serial.println(sp);  Serial.print("Set Speed Fan1: ");  Serial.println(String(rpm1));
  s.send(200, "text/plain", String(rpm1));
}
void getRPM1() {
  s.send(200, "text/plain", String(rpm1) + "," + String(p1));
}
void setSpeed2() {
  String sp = s.arg("s2");  p2 = sp.toInt();  int dc = map(p2, 0, 100, 0, 1024);  ledcWrite(PWM_CHANNEL2, dc);  rpm2 = map(p2, 0, 100, 0, 11000);
  prefs.putUInt("f2", p2);  Serial.print("Set Speed Fan2: ");  Serial.println(String(rpm2));
  s.send(200, "text/plain", String(rpm2));
}
void getRPM2() {
  s.send(200, "text/plain", String(rpm2) + "," + String(p2));
}
void setSpeed3() {
  String sp = s.arg("s3");  
  p3 = sp.toInt();  
  int dc = map(p3, 0, 100, 0, 1024);  
//  int dc = map(p3, 0, 100, 0, 1024);  
  ledcWrite(PWM_CHANNEL3, dc);  
  rpm3 = map(p3, 0, 100, 0, 11000);
  prefs.putUInt("f3", p3);    
  Serial.print("Set Speed Fan3: ");  
  Serial.println(String(rpm3));
  s.send(200, "text/plain", String(rpm3));
}
void getRPM3() {
  s.send(200, "text/plain", String(rpm3) + "," + String(p3));
}

void setSpeed3edit(int speed) {
  p3 = speed;  // Прямая передача скорости как параметра функции
  int dc = map(p3, 0, 100, 0, 1024);
  ledcWrite(PWM_CHANNEL3, dc);
  rpm3 = map(p3, 0, 100, 0, 11000);
  prefs.putUInt("f3", p3);    
  }

class MovingAverageFilter {
  public:
    MovingAverageFilter(int windowSize) : windowSize(windowSize), currentIndex(0), currentSum(0.0) {
      buffer = new float[windowSize];
      for (int i = 0; i < windowSize; i++) {
        buffer[i] = 0.0;
      }
    }
    
    ~MovingAverageFilter() {
      delete[] buffer;
    }
    
    float addValue(float value) {
      currentSum -= buffer[currentIndex];  // subtract the oldest value
      buffer[currentIndex] = value;       // store the new value
      currentSum += value;                // add the new value to the sum
      currentIndex = (currentIndex + 1) % windowSize;  // update the index
      return currentSum / windowSize;
    }
    
  private:
    int windowSize;
    float* buffer;
    int currentIndex;
    float currentSum;
};

MovingAverageFilter rpm1_filter(5);  // for last 5 values
MovingAverageFilter rpm2_filter(5);
MovingAverageFilter rpm3_filter(5);


void setup() {
  Serial.begin(115200);
  prefs.begin(ns, false);

  i1_get_data = prefs.getInt("ttl2",0);
  if (i1_get_data == 0) {
    i1_get_data = 10;
  }
  
   if (prefs.getUInt("en_ac") == 1) {
    mq2.calibrate();
    float kek = mq2.getRo();
    prefs.putFloat("calibr",kek);
    millis_INTERVAL_CALIBRATE=millis();
    } else if (prefs.getUInt("en_ac") == 0) {
    mq2.calibrate(prefs.getFloat("calibr", 0));
    delay(5000);
    mq2.getRo();
    
  } else {mq2.calibrate();}



  pinMode(FAN_PIN1, OUTPUT);  pinMode(FAN_PIN2, OUTPUT);  pinMode(FAN_PIN3, OUTPUT);
  ledcSetup(PWM_CHANNEL1, PWM_FREQ, PWM_RES);  ledcSetup(PWM_CHANNEL2, PWM_FREQ, PWM_RES);  ledcSetup(PWM_CHANNEL3, PWM_FREQ, PWM_RES);
  ledcSetup(0, PWM_FREQ, PWM_RES);
  ledcAttachPin(FAN_PIN1, PWM_CHANNEL1);  ledcAttachPin(FAN_PIN2, PWM_CHANNEL2);  ledcAttachPin(FAN_PIN3, PWM_CHANNEL3);
  pinMode(RPM_PIN1, INPUT_PULLUP);  pinMode(RPM_PIN2, INPUT_PULLUP);  pinMode(RPM_PIN3, INPUT_PULLUP);
  attachInterrupt(digitalPinToInterrupt(RPM_PIN1), fanCounter1, RISING);  attachInterrupt(digitalPinToInterrupt(RPM_PIN2), fanCounter2, RISING);  attachInterrupt(digitalPinToInterrupt(RPM_PIN3), fanCounter3, RISING);


  p1 = prefs.getUInt("f1", INIT_PERCENT);  p2 = prefs.getUInt("f2", INIT_PERCENT);  p3 = prefs.getUInt("f3", INIT_PERCENT);
  
  float  onlower = prefs.getFloat("onlower", 0) == 0 ? prefs.putFloat("onlower", -19), -19 : prefs.getFloat("onlower");
  float  onhigher = prefs.getFloat("onhigher", 0) == 0 ? prefs.putFloat("onhigher", 10.2), 10.2 : prefs.getFloat("onhigher");
  float  offlower = prefs.getFloat("offlower", 0) == 0 ? prefs.putFloat("offlower", 1.0), 1.0 : prefs.getFloat("offlower");
  float  offhigher = prefs.getFloat("offhigher", 0) == 0 ? prefs.putFloat("offhigher", 9.5), 9.5 : prefs.getFloat("offhigher");
    
  Serial.print("onlower:"); Serial.println(prefs.getFloat("onlower"));
  Serial.print("onhigher:"); Serial.println(prefs.getFloat("onhigher"));
  Serial.print("offlower:"); Serial.println(prefs.getFloat("offlower"));
  Serial.print("offhigher:"); Serial.println(prefs.getFloat("offhigher"));

  
  int dc1 = map(p1, 0, 100, 0, 1024);  int dc2 = map(p2, 0, 100, 0, 1024);  int dc3 = map(p3, 0, 100, 0, 1024);
  ledcWrite(PWM_CHANNEL1, dc1);  rpm1 = map(p1, 0, 100, 0, 11000);
  ledcWrite(PWM_CHANNEL2, dc2);  rpm2 = map(p2, 0, 100, 0, 11000);
  ledcWrite(PWM_CHANNEL3, dc3);  rpm3 = map(p3, 0, 100, 0, 11000);
  Serial.println("gay is: ");
  Serial.println(rpm3);
  if (rpm3 >0) {
    fan3Started = false; 
  }

  WiFi.mode(WIFI_STA);
  WiFi.begin(ssid, password);

  while (WiFi.waitForConnectResult() != WL_CONNECTED) {
    delay(5000);
    ESP.restart();
  }
  s.on("/", HTTP_GET, root);  
  s.on("/set1", HTTP_GET, setSpeed1);  s.on("/get1", HTTP_GET, getRPM1);  s.on("/set2", HTTP_GET, setSpeed2);  s.on("/get2", HTTP_GET, getRPM2);  s.on("/set3", HTTP_GET, setSpeed3);  s.on("/get3", HTTP_GET, getRPM3);
  s.on("/getSmoke", HTTP_GET, getSmoke);
  s.on("/remtime", HTTP_GET, getRemainingTime);
  s.on("/getAnalogRead34", HTTP_GET, getAnalogRead34);
  s.on("/setAutoFan", HTTP_GET, []() {
    if (s.hasArg("value")) {
      int value = s.arg("value").toInt();
      if (value == 0) { fan3Started = false;}
      prefs.putUInt("en_autofan", value);
      s.send(200, "text/plain", "AutoFan setting updated");
    } else {
      s.send(400, "text/plain", "Bad Request");
    }
  });

  s.on("/setCalibrate", HTTP_GET, []() {
    if (s.hasArg("value")) {
      int value = s.arg("value").toInt();
      if (value == 0) { autocalibrate = false;}
      if (value == 1) { autocalibrate = true;}
      prefs.putUInt("en_ac", value);
      s.send(200, "text/plain", String(prefs.getUInt("en_ac")));
    } else {
      s.send(200, "text/plain", String(prefs.getUInt("en_ac")));
    }
  });

s.on("/reboot", HTTP_GET, []() {
          s.send(200, "text/plain", "reboot");
          ESP.restart();
    
  });
s.on("/reset", HTTP_GET, []() {
          s.send(200, "text/plain", "reboot");
          ESP.restart();
    
  });
s.on("/calibrate", HTTP_GET, []() {
     if (s.hasArg("value")) {
      float value = s.arg("value").toFloat();
      prefs.putFloat("calibr", value);
      mq2.calibrate(value);
      s.send(200, "text/plain", String(prefs.getFloat("calibr")));
    }else{ 
          mq2.calibrate();
          float kek = mq2.getRo();
          prefs.putFloat("calibr",kek);
          s.send(200, "text/plain", String(mq2.getRo()));
          //s.send(200, "text/plain", String(kek));
    }
  });


  s.on("/setAutoSmokeLimit", HTTP_GET, []() {
    if (s.hasArg("value")) {
      int value = s.arg("value").toInt();
      prefs.putUInt("fan_limit", value);
      s.send(200, "text/plain", "AutoSmokeLimit updated");
    } else {
      s.send(400, "text/plain", "Bad Request");
    }
  });
  
    s.on("/settlm", HTTP_GET, []() {
    if (s.hasArg("value")) {
      int value = s.arg("value").toInt();
      prefs.putInt("ttl2", value);
      int lol2 = prefs.getInt("ttl2") * 60000;
    s.send(200, "text/plain", String(lol2));
    } else {
      s.send(400, "text/plain", "Bad Request");
    }
  });
    s.on("/setonlower", HTTP_GET, []() {
    if (s.hasArg("value")) {
      float value = s.arg("value").toFloat();
      prefs.putFloat("onlower", value);
      s.send(200, "text/plain", "onlower updated");
    } else {
      s.send(400, "text/plain", "Bad Request");
    }
  });

  s.on("/setonhigher", HTTP_GET, []() {
    if (s.hasArg("value")) {
      float value = s.arg("value").toFloat();
      prefs.putFloat("onhigher", value);
      s.send(200, "text/plain", "onhigher updated");
    } else {
      s.send(400, "text/plain", "Bad Request");
    }
  });

  s.on("/setofflower", HTTP_GET, []() {
    if (s.hasArg("value")) {
      float value = s.arg("value").toFloat();
      prefs.putFloat("offlower", value);
      s.send(200, "text/plain", "offlower updated");
    } else {
      s.send(400, "text/plain", "Bad Request");
    }
  });

  s.on("/setoffhigher", HTTP_GET, []() {
    if (s.hasArg("value")) {
      float value = s.arg("value").toFloat();
      prefs.putFloat("offhigher", value);
      s.send(200, "text/plain", "offhigher updated");
    } else {
      s.send(400, "text/plain", "Bad Request");
    }
  });

  
  
  s.begin();
  Serial.println("Ready");  Serial.print("IP address: ");  Serial.println(WiFi.localIP());  
  ArduinoOTA.setHostname("Fun_and_smoke");    
  ArduinoOTA.begin();
  ArduinoOTA.onStart([]() {
    String type;
    if (ArduinoOTA.getCommand() == U_FLASH)
      type = "sketch";
    else // U_SPIFFS
      type = "filesystem";

    // NOTE: if updating SPIFFS this would be the place to unmount SPIFFS using SPIFFS.end()
    Serial.println("Start updating " + type);
  });
  ArduinoOTA.onEnd([]() {
    Serial.println("\nEnd");
  });
  ArduinoOTA.onProgress([](unsigned int progress, unsigned int total) {
    Serial.printf("Progress: %u%%\r", (progress / (total / 100)));
  });
  ArduinoOTA.onError([](ota_error_t error) {
    Serial.printf("Error[%u]: ", error);
    if (error == OTA_AUTH_ERROR) Serial.println("Auth Failed");
    else if (error == OTA_BEGIN_ERROR) Serial.println("Begin Failed");
    else if (error == OTA_CONNECT_ERROR) Serial.println("Connect Failed");
    else if (error == OTA_RECEIVE_ERROR) Serial.println("Receive Failed");
    else if (error == OTA_END_ERROR) Serial.println("End Failed");
  });
  ArduinoOTA.begin();
}


void loop() {
  s.handleClient();
  ArduinoOTA.handle(); // Обработка OTA
  INTERVAL1_GET_DATA = prefs.getInt("ttl2") * 60000;
  if (millis() - millis_INTERVAL_CALIBRATE >= INTERVAL_CALIBRATE)
  {
   if (prefs.getUInt("en_ac") == 1) {
    mq2.calibrate();
    float kek = mq2.getRo();
    prefs.putFloat("calibr",kek);
    millis_INTERVAL_CALIBRATE=millis();
  }
  }

///  static unsigned long lastSampleTime = 0;
///  static int i = 0;
///  static float totalval1 = 0;
int timez = 10;
  if (millis() - millis_mq2 >= INTERVAL_MQ2) {
  float currentReading = mq2.readRatio();
      if (i < timez && millis() - lastSampleTime >= 1000) {
      float ratio = mq2.readRatio();
  if (ratio == 0 || isnan(ratio)) {
   ratio = mq2.readRatio();
  }
  if ( ratio <= 2 || ratio >= 20) 
  {ratio = 10;}
  
      totalval1 += ratio;
      i++;
      lastSampleTime = millis();
    }
    if (i == timez) {
      float averageVal = totalval1 / timez;
      if (averageVal > 20){averageVal = 10;}
      totalval = averageVal;
      checkSmokeLevelAndControlFan3();
      millis_mq2 = millis();
      i = 0;
      totalval1 = 0;
    }
  }
 
  unsigned long t = millis();
  if (t - lpt >= 1000) {
    noInterrupts();
    rpm1 = rpm1_filter.addValue((pc1 - lpc1) * 60 / 2);    rpm2 = rpm2_filter.addValue((pc2 - lpc2) * 60 / 2);    rpm3 = rpm3_filter.addValue((pc3 - lpc3) * 60 / 2);    lpc1 = pc1;    lpc2 = pc2;    lpc3 = pc3;    lpt = t;
    interrupts();
  }
}
