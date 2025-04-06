# ESP32 Fan Control System with Web Interface and Python Script
### **GitHub Description for the Project**

---

## **ESP32 Fan Control System with Web Interface and Python Script**

This project is a comprehensive solution for controlling fans using an ESP32 microcontroller, a web-based interface, and a Python script for advanced monitoring and control. It integrates hardware control with software automation, making it suitable for server rooms, ventilation systems, or any environment requiring precise fan management.

---

### **ESP32 Part (Microcontroller)**

#### **Описание на русском:**
ESP32 управляет тремя вентиляторами с использованием ШИМ-сигналов и мониторинга оборотов (RPM). Также поддерживается автоматическое управление на основе показаний датчика дыма MQ-2. Основные функции:

1. **Управление вентиляторами**:
   - Возможность ручной настройки скорости (0–100%) через веб-интерфейс.
   - Автоматическое включение вентилятора при превышении пороговых значений датчика дыма.
   - Мониторинг RPM через прерывания.

2. **Датчик дыма MQ-2**:
   - Автокалибровка при запуске.
   - Настройка порогов срабатывания через веб-интерфейс или сохранение в энергонезависимой памяти.

3. **Веб-интерфейс**:
   - Слайдеры для ручного управления скоростью вентиляторов.
   - Отображение текущих RPM и уровня дыма.
   - Настройки автоматического режима работы.

4. **Сетевые функции**:
   - Подключение к Wi-Fi.
   - Встроенный веб-сервер для управления.
   - Поддержка OTA-обновлений прошивки.

5. **Особенности**:
   - Сохранение настроек в энергонезависимой памяти (Preferences).
   - Плавное управление скоростью вентиляторов.
   - Защита от перегрузок и аварийных ситуаций.

---

#### **Description in English:**
The ESP32 microcontroller manages three fans using PWM signals and RPM monitoring. It also supports automatic control based on readings from the MQ-2 smoke sensor. Key features include:

1. **Fan Control**:
   - Manual speed adjustment (0–100%) via a web interface.
   - Automatic fan activation when smoke thresholds are exceeded.
   - RPM monitoring using interrupts.

2. **MQ-2 Smoke Sensor**:
   - Auto-calibration at startup.
   - Configurable thresholds via the web interface or persistent storage.

3. **Web Interface**:
   - Sliders for manual fan speed control.
   - Real-time display of RPM and smoke levels.
   - Settings for automatic operation mode.

4. **Network Features**:
   - Wi-Fi connectivity.
   - Built-in web server for management.
   - OTA firmware update support.

5. **Features**:
   - Persistent settings storage using Preferences.
   - Smooth fan speed control.
   - Overload and fault protection.

---

### **Web Interface**

#### **Описание на русском:**
Веб-интерфейс предоставляет удобный способ управления системой через браузер. Его основные возможности:

1. **Управление вентиляторами**:
   - Слайдеры для настройки скорости каждого вентилятора.
   - Отображение текущих оборотов (RPM).

2. **Мониторинг датчика дыма**:
   - Отображение текущего уровня дыма.
   - Индикатор времени до следующей проверки.

3. **Настройки автоматического режима**:
   - Включение/выключение автоматического контроля.
   - Настройка порогов срабатывания и выключения.

4. **Калибровка**:
   - Возможность калибровки датчика дыма через интерфейс.

5. **Дополнительные функции**:
   - Отображение состояния системы (например, "Курят"/"Не курят").
   - Поддержка AJAX для обновления данных без перезагрузки страницы.

---

#### **Description in English:**
The web interface provides a user-friendly way to manage the system through a browser. Its key features include:

1. **Fan Control**:
   - Sliders for adjusting the speed of each fan.
   - Display of current RPM.

2. **Smoke Sensor Monitoring**:
   - Current smoke level display.
   - Timer indicating time until the next check.

3. **Automatic Mode Settings**:
   - Enable/disable automatic control.
   - Configure activation and deactivation thresholds.

4. **Calibration**:
   - Option to calibrate the smoke sensor via the interface.

5. **Additional Features**:
   - System status display (e.g., "Smoking"/"Not Smoking").
   - AJAX support for data updates without page reloads.

---

### **Python Script (Server-Side Control)**

#### **Описание на русском:**
Python-скрипт обеспечивает высокий уровень управления и интеграции с внешними системами. Он работает на сервере и взаимодействует с ESP32 через последовательный порт или HTTP-запросы.

1. **Основные функции**:
   - Получение данных с датчиков через IPMI или HTTP.
   - Анализ теплового состояния и дыма.
   - Динамическая регулировка скорости вентиляторов на основе температур и уровня дыма.

2. **Визуализация**:
   - Цветной ASCII-интерфейс для терминала.
   - Графики температуры, RPM и уровня дыма.
   - 3D-график для объединенного анализа данных.

3. **Автоматическое управление**:
   - Адаптивное снижение скорости вентиляторов при нормализации условий.
   - Автоматическое увеличение скорости при обнаружении задымления.

4. **Дополнительные функции**:
   - Получение внешней температуры через API (например, wttr.in).
   - Тестовый режим для проверки системы.

5. **SNMP-сервер**:
   - Интеграция с системами мониторинга (Zabbix, Nagios и др.).

---

#### **Description in English:**
The Python script provides advanced control and integration with external systems. It runs on a server and communicates with the ESP32 via a serial port or HTTP requests.

1. **Main Functions**:
   - Data acquisition from sensors via IPMI or HTTP.
   - Thermal and smoke analysis.
   - Dynamic fan speed adjustment based on temperature and smoke levels.

2. **Visualization**:
   - Colorful ASCII interface for terminal use.
   - Graphs of temperature, RPM, and smoke levels.
   - 3D graph for combined data analysis.

3. **Automatic Control**:
   - Adaptive fan speed reduction when conditions normalize.
   - Automatic speed increase upon smoke detection.

4. **Additional Features**:
   - External temperature retrieval via API (e.g., wttr.in).
   - Test mode for system verification.

5. **SNMP Server**:
   - Integration with monitoring systems (Zabbix, Nagios, etc.).

---

### **Usage Instructions**

1. **ESP32 Setup**:
   - Upload the code to the ESP32.
   - Connect fans and sensors according to the wiring diagram.

2. **Python Script**:
   - Install dependencies (`pyserial`, `requests`, `matplotlib`).
   - Run the script with desired parameters:
     ```bash
     python3 fan_control.py --gui=true
     ```

3. **Access Web Interface**:
   - Open a browser and navigate to the ESP32's IP address.

---

### **Requirements**

#### **ESP32**:
- Libraries: `WiFi`, `WebServer`, `Preferences`, `ArduinoOTA`, `TroykaMQ`.

#### **Python Script**:
- Python 3.x.
- Dependencies: `pyserial`, `requests`, `matplotlib`.
- Tools: `ipmitool`, `curl`.

---

### **License**

This project is distributed under the MIT License. Feel free to modify and use it as needed!

---

### **Contributions**

Contributions are welcome! If you have ideas for improvements or find bugs, please open an issue or submit a pull request.

--- 

This description provides a clear overview of the project's functionality, making it easy for users to understand and contribute.
