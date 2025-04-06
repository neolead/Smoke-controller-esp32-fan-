import sys
import os
import numpy as np
import argparse
import requests
import time
import numpy as np
import matplotlib.pyplot as plt
import re
from matplotlib.animation import FuncAnimation
from mpl_toolkits.mplot3d import Axes3D  # Для 3D-графика
from matplotlib import gridspec
from collections import deque
import matplotlib.dates as mdates
from datetime import datetime

# ======================== Параметры конфигурации ===========================
use_mq2_pin = True
use_getSmoke = False
#cal sensor 21
URL = "http://192.168.1.75"
GET_URL = f"{URL}/getSmoke"
MQ2_URL = f"{URL}/getAnalogRead34"
COMMAND_URL = f"{URL}/set3?s3="

MAXFANSPEED = 60
INTERVAL = 1
CALIBRATION_DURATION = 40       # секунд
RECALIBRATION_INTERVAL = 3600   # секунд
SMOKE_HOLD_DURATION = 600       # секунд
WARMUP_TIME = 10  # время прогрева в секундах
sensor_warmed_up = False
warmup_start_time = None  # Время начала прогрева

# Порог срабатывания для каждого датчика (в процентах от baseline)
TRIGGER_PERCENTAGEMQ2 = 20
TRIGGER_PERCENTAGEPPM = 45
TRIGGER_PERCENTAGECUR = 60

AVG_WINDOW_SIZE = 3

# Глобальные переменные калибровки
baseline_ppm = baseline_cur = baseline_mq2 = 0

# Глобальные переменные тревоги
smoke_detected = False
smoke_start_time = 0
current_device_state = 20

# Данные для графиков
timestamps = []
ppm_data = []
cur_data = []
mq2_data = []

# Буферы для усреднения
mq2_avg_window = deque(maxlen=AVG_WINDOW_SIZE)
ppm_avg_window = deque(maxlen=AVG_WINDOW_SIZE)
cur_avg_window = deque(maxlen=AVG_WINDOW_SIZE)

# Для сохранения последних валидных значений (fallback)
last_valid_ppm = None
last_valid_cur = None
last_valid_mq2 = None

# Глобальная переменная для хранения начального превышения MQ2 при активации режима
initial_excess_mq2 = None

# ======================== Функции ===========================

def send_device_command(value, force=False):
    global current_device_state
    if force or current_device_state != value:
        try:
            response = requests.get(f"{COMMAND_URL}{value}", timeout=3)
            response.raise_for_status()
            current_device_state = value
            print(f"Устройство установлено в {value}")
        except requests.RequestException as e:
            print(f"Ошибка отправки команды: {e}")

def is_valid_value(value):
    return not (np.isnan(value) or np.isinf(value) or value <= 0)

def calibrate_sensor():
    """
    Калибровка всех датчиков (getSmoke: ppm и cur, а также MQ2).
    Собираются данные, удаляются выбросы, затем вычисляется медиана.
    """
    global baseline_ppm, baseline_cur, baseline_mq2,warmup_start_time, sensor_warmed_up
    ppm_samples, cur_samples, mq2_samples = [], [], []
    warmup_start_time = time.time() + CALIBRATION_DURATION + 30
    sensor_warmed_up = False
    print("Калибровка датчиков...")
    start_time = time.time()
    while time.time() - start_time < CALIBRATION_DURATION:
        try:
            response = requests.get(GET_URL, timeout=5).text
            ppm_match = re.search(r'ppm:(\d+\.?\d*)', response)
            cur_match = re.search(r'cur:(\d+\.?\d*)', response)
            if ppm_match and cur_match:
                ppm = float(ppm_match.group(1).replace(',', '.'))
                cur = float(cur_match.group(1).replace(',', '.'))
                if is_valid_value(ppm):
                    ppm_samples.append(ppm)
                if is_valid_value(cur):
                    cur_samples.append(cur)
        except Exception as e:
            print(f"Ошибка калибровки getSmoke: {e}")
        try:
            response_mq2 = requests.get(MQ2_URL, timeout=5).text.strip()
            mq2 = float(response_mq2)
            if is_valid_value(mq2):
                mq2_samples.append(mq2)
        except Exception as e:
            print(f"Ошибка калибровки MQ2: {e}")
    time.sleep(INTERVAL)
    
    def remove_outliers(data):
        if len(data) < 3:
            return data
        q1 = np.percentile(data, 25)
        q3 = np.percentile(data, 75)
        iqr = q3 - q1
        return [x for x in data if (x > q1 - 1.5 * iqr) and (x < q3 + 1.5 * iqr)]
    
    ppm_filtered = remove_outliers(ppm_samples)
    cur_filtered = remove_outliers(cur_samples)
    mq2_filtered = remove_outliers(mq2_samples)
    
    if ppm_filtered:
        baseline_ppm = np.median(ppm_filtered)
    if cur_filtered:
        baseline_cur = np.median(cur_filtered)
    if mq2_filtered:
        baseline_mq2 = np.median(mq2_filtered)
    
    print(f"Калибровка завершена.\n  ppm: {baseline_ppm:.1f}\n  cur: {baseline_cur:.1f}\n  MQ2: {baseline_mq2:.1f}")

def calculate_thresholds():
    """
    Вычисление порогов для датчиков как baseline * (1 + TRIGGER_PERCENTAGE/100).
    """
    threshold_mq2 = baseline_mq2 * (1 + TRIGGER_PERCENTAGEMQ2 / 100)
    threshold_ppm = baseline_ppm * (1 + TRIGGER_PERCENTAGEPPM / 100)
    threshold_cur = baseline_cur * (1 + TRIGGER_PERCENTAGECUR / 100)
    return threshold_mq2, threshold_ppm, threshold_cur

def check_smoke(ppm, cur, mq2):
    """
    Детекция дыма:
      - Если оба датчика используются, срабатывание, если MQ2 и хотя бы один из getSmoke (ppm или cur) превышают порог.
      - Если один из датчиков отключён, то детекция по оставшемуся.
      - При активации фиксируется начальное превышение (initial_excess_mq2).
      - Если в режиме задымления, начиная с 50% времени, текущее превышение MQ2 снижается до 50% от начального, скорость вентилятора уменьшается постепенно.
    """
    global smoke_detected, smoke_start_time, current_device_state, initial_excess_mq2,sensor_warmed_up, warmup_start_time
    if not sensor_warmed_up and time.time() - warmup_start_time >= WARMUP_TIME:
        sensor_warmed_up = True
        print("Датчик прогрелся, данные теперь можно использовать.")
    if not sensor_warmed_up:
        print("Датчик ещё не прогрет. Пропускаем данные.")
        return  # Пропускаем обработку данных, если датчик не прогрелся
    mq2_avg_window.append(mq2)
    ppm_avg_window.append(ppm)
    cur_avg_window.append(cur)
    
    mq2_filtered = np.mean(mq2_avg_window)
    ppm_filtered = np.mean(ppm_avg_window)
    cur_filtered = np.mean(cur_avg_window)
    
    threshold_mq2, threshold_ppm, threshold_cur = calculate_thresholds()
    
    if use_mq2_pin and use_getSmoke:
        condition = (mq2_filtered > threshold_mq2) or ((ppm_filtered > threshold_ppm) or (cur_filtered > threshold_cur))
    elif use_mq2_pin:
        condition = mq2_filtered > threshold_mq2
    elif use_getSmoke:
        condition = (ppm_filtered > threshold_ppm) or (cur_filtered > threshold_cur)
    else:
        condition = False

    if condition:
        if not smoke_detected:
            smoke_start_time = time.time()
            initial_excess_mq2 = mq2_filtered - threshold_mq2
            if initial_excess_mq2 < 0:
                initial_excess_mq2 = 0
            send_device_command(MAXFANSPEED)
            smoke_detected = True
            print("Обнаружено задымление!")
        else:
            elapsed = time.time() - smoke_start_time
            current_excess = mq2_filtered - threshold_mq2
            if current_excess < 0:
                current_excess = 0
            # Если прошло 50% от SMOKE_HOLD_DURATION
            if elapsed >= SMOKE_HOLD_DURATION * 0.5:
                # После 75% времени продолжаем мониторинг и, если превышение снизилось до 50% от начального, уменьшаем скорость
                if current_excess <= initial_excess_mq2 * 0.5:
                    new_speed = max(20, current_device_state - 1)
                    if new_speed != current_device_state:
                        send_device_command(new_speed)
                        print(f"Снижение скорости вентилятора до {new_speed} (elapsed: {elapsed:.1f}s, excess: {current_excess:.1f})")
                    if new_speed == 20:
                        smoke_detected = False
                        print("Задымление прекращено (минимальная скорость).")
    else:
        if smoke_detected and (time.time() - smoke_start_time >= SMOKE_HOLD_DURATION):
            smoke_detected = False
            send_device_command(20)
            print("Задымление прекратилось.")

def build_bar(value, threshold, width=50):
    """Создает строку-полоску для отображения соотношения value/threshold."""
    if not is_valid_value(value) or not is_valid_value(threshold):
        return "[" + "-" * width + "]"
    ratio = value / threshold if threshold > 0 else 0
    if np.isnan(ratio):
        ratio = 0
    ratio = min(max(ratio, 0), 1)
    filled = int(ratio * width)
    return "[" + "#" * filled + "-" * (width - filled) + "]"

def update_terminal():
    """Обновление псевдографики в терминале."""
    global last_valid_ppm, last_valid_cur, last_valid_mq2
    try:
        ppm_val = cur_val = mq2_val = np.nan
        try:
            response = requests.get(GET_URL, timeout=5).text
            ppm_match = re.search(r'ppm:(\d+\.?\d*)', response)
            cur_match = re.search(r'cur:(\d+\.?\d*)', response)
            if ppm_match and cur_match:
                ppm_val = float(ppm_match.group(1).replace(',', '.'))
                cur_val = float(cur_match.group(1).replace(',', '.'))
        except Exception as e:
            print(f"Ошибка getSmoke: {e}")
        try:
            mq2_val = float(requests.get(MQ2_URL, timeout=5).text.strip())
        except Exception as e:
            print(f"Ошибка MQ2: {e}")


        if ppm_val < baseline_ppm / 4 or ppm_val > baseline_ppm * 4:
            if last_valid_ppm is not None:
                ppm_val = last_valid_ppm
        else:
            last_valid_ppm = ppm_val
        
        if cur_val < baseline_cur / 4 or cur_val > baseline_cur * 4:
            if last_valid_cur is not None:
                cur_val = last_valid_cur
        else:
            last_valid_cur = cur_val
        
        if mq2_val < baseline_mq2 / 4 or mq2_val > baseline_mq2 * 4:
            if last_valid_mq2 is not None:
                mq2_val = last_valid_mq2
        else:
            last_valid_mq2 = mq2_val

        mq2_avg_window.append(mq2_val)
        ppm_avg_window.append(ppm_val)
        cur_avg_window.append(cur_val)
        
        mq2_filtered = np.mean(mq2_avg_window)
        ppm_filtered = np.mean(ppm_avg_window)
        cur_filtered = np.mean(cur_avg_window)
        
        threshold_mq2, threshold_ppm, threshold_cur = calculate_thresholds()
        
        check_smoke(ppm_val, cur_val, mq2_val)
        
        bar_mq2 = build_bar(mq2_filtered, threshold_mq2)
        bar_ppm = build_bar(ppm_filtered, threshold_ppm)
        bar_cur = build_bar(cur_filtered, threshold_cur)
        
        status = "КУРЯТ!" if smoke_detected else "НЕ КУРЯТ"
        status_msg = (
            "+++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++\n"
            f"MQ2: {mq2_filtered:.1f} {bar_mq2} (Порог: {threshold_mq2:.1f})\n"
            f"PPM: {ppm_filtered:.1f} {bar_ppm} (Порог: {threshold_ppm:.1f})\n"
            f"CUR: {cur_filtered:.1f} {bar_cur} (Порог: {threshold_cur:.1f})\n"
            f"СТАТУС: {status}\n"
        )
        os.system('cls' if os.name == 'nt' else 'clear')
        print(status_msg)
    except Exception as e:
        print(f"Ошибка в update_terminal: {e}")

# ======================== Режим GUI: Объединённое окно (2D слева, 3D справа) ===========================
# Создаем одну фигуру с двумя столбцами
fig = plt.figure(figsize=(16, 9))
gs = gridspec.GridSpec(1, 2, width_ratios=[1, 1])

# Левый столбец: 2D графики, организованные в 3 ряда
gs_left = gridspec.GridSpecFromSubplotSpec(3, 1, subplot_spec=gs[0])
ax_ppm = fig.add_subplot(gs_left[0, 0])
ax_cur = fig.add_subplot(gs_left[1, 0])
ax_mq2 = fig.add_subplot(gs_left[2, 0])
status_text = ax_ppm.text(0.5, 0.9, "", transform=ax_ppm.transAxes, ha='center', fontsize=12)
# Настройка подписей для 2D графиков
ax_ppm.set_title("Датчик PPM")
ax_ppm.set_xlabel("Время", position=(0, -10))
ax_ppm.set_ylabel("PPM")
ax_cur.set_title("Датчик CUR")
ax_cur.set_xlabel("Время", position=(0, -10))
ax_cur.set_ylabel("CUR")
ax_mq2.set_title("Датчик MQ2")
ax_mq2.set_xlabel("Время", position=(0, -10))
ax_mq2.set_ylabel("MQ2")

# Правый столбец: 3D график
ax3d = fig.add_subplot(gs[1], projection='3d')

# Линии для 2D графиков
line_ppm, = ax_ppm.plot([], [], color='orange', label="PPM")
line_cur, = ax_cur.plot([], [], color='blue', label="CUR")
line_mq2, = ax_mq2.plot([], [], color='green', label="MQ2")

ppm_threshold_line = ax_ppm.plot([], [], 'r--', label='Threshold')[0]
cur_threshold_line = ax_cur.plot([], [], 'r--', label='Threshold')[0]
mq2_threshold_line = ax_mq2.plot([], [], 'r--', label='Threshold')[0]

def update_plots(frame):
    global timestamps, ppm_data, cur_data, mq2_data, smoke_detected
    global last_valid_ppm, last_valid_cur, last_valid_mq2
    try:
        ppm_val = cur_val = mq2_val = np.nan
        try:
            response = requests.get(GET_URL, timeout=5).text
            ppm_match = re.search(r'ppm:(\d+\.?\d*)', response)
            cur_match = re.search(r'cur:(\d+\.?\d*)', response)
            if ppm_match and cur_match:
                ppm_val = float(ppm_match.group(1).replace(',', '.'))
                cur_val = float(cur_match.group(1).replace(',', '.'))
        except Exception as e:
            print(f"Ошибка getSmoke: {e}")
        try:
            mq2_val = float(requests.get(MQ2_URL, timeout=5).text.strip())
        except Exception as e:
            print(f"Ошибка MQ2: {e}")
        
        # Восстановление последних валидных значений
        if not is_valid_value(ppm_val) and last_valid_ppm is not None:
            ppm_val = last_valid_ppm
        else:
            last_valid_ppm = ppm_val
        if not is_valid_value(cur_val) and last_valid_cur is not None:
            cur_val = last_valid_cur
        else:
            last_valid_cur = cur_val
        if not is_valid_value(mq2_val) and last_valid_mq2 is not None:
            mq2_val = last_valid_mq2
        else:
            last_valid_mq2 = mq2_val
        
        # Используем datetime для оси X
        current_time = datetime.now()
        timestamps.append(current_time)
        ppm_data.append(ppm_val if is_valid_value(ppm_val) else np.nan)
        cur_data.append(cur_val if is_valid_value(cur_val) else np.nan)
        mq2_data.append(mq2_val if is_valid_value(mq2_val) else np.nan)
        
        max_len = 100
        if len(timestamps) > max_len:
            timestamps[:] = timestamps[-max_len:]
            ppm_data[:] = ppm_data[-max_len:]
            cur_data[:] = cur_data[-max_len:]
            mq2_data[:] = mq2_data[-max_len:]
        
        # Преобразуем время в формат для matplotlib
        x_dates = mdates.date2num(timestamps)
        
        # Обновляем 2D графики
        line_ppm.set_data(x_dates, ppm_data)
        line_cur.set_data(x_dates, cur_data)
        line_mq2.set_data(x_dates, mq2_data)
        
        threshold_mq2, threshold_ppm, threshold_cur = calculate_thresholds()
        ppm_threshold_line.set_data(x_dates, [threshold_ppm]*len(x_dates))
        cur_threshold_line.set_data(x_dates, [threshold_cur]*len(x_dates))
        mq2_threshold_line.set_data(x_dates, [threshold_mq2]*len(x_dates))
        
        for ax, data, thr in zip([ax_ppm, ax_cur, ax_mq2],
                                 [ppm_data, cur_data, mq2_data],
                                 [threshold_ppm, threshold_cur, threshold_mq2]):
            if data:
                valid_data = [d for d in data if not np.isnan(d)]
                if valid_data:
                    y_min = min(valid_data + [thr]) - 10
                    y_max = max(valid_data + [thr]) + 10
                    ax.set_ylim(y_min, y_max)
                    ax.set_xlim(x_dates[0], x_dates[-1])
                    ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M:%S'))  # формат времени
        
        check_smoke(ppm_val, cur_val, mq2_val)
        
        # Обновление текста статуса
        status_msg = (
            "\n"
            f"Порог MQ2: {threshold_mq2:.1f}, ppm: {threshold_ppm:.1f}, cur: {threshold_cur:.1f}    "
            f"СТАТУС: {'КУРЯТ!' if smoke_detected else 'НЕ КУРЯТ'}"
        )
        status_text.set_text(status_msg)
        status_text.set_color('red' if smoke_detected else 'green')
        status_text.set_zorder(100)
        
        # Преобразуем время в формат для matplotlib
        x_vals = mdates.date2num(timestamps)
        
        # Проверим данные перед построением графика
        if len(x_vals) == 0 or len(ppm_data) == 0 or len(cur_data) == 0 or len(mq2_data) == 0:
            print("Ошибка: данные пусты, график не будет построен")
            return
        
        # Выводим данные перед фильтрацией
#        print(f"Данные перед фильтрацией: ")
#        print(f"x_vals: {len(x_vals)}, ppm_data: {len(ppm_data)}, cur_data: {len(cur_data)}, mq2_data: {len(mq2_data)}")
        
        # Фильтрация данных (убираем nan-значения)
        valid_mask = (~np.isnan(x_vals)) & (~np.isnan(ppm_data)) & (~np.isnan(cur_data)) & (~np.isnan(mq2_data))
        x_vals = x_vals[valid_mask]
        ppm_vals = np.array(ppm_data)[valid_mask]
        cur_vals = np.array(cur_data)[valid_mask]
        mq2_vals = np.array(mq2_data)[valid_mask]
        mq2_vals = mq2_vals / 10

        
        # Если после фильтрации данных мало, пропускаем отрисовку
        if len(x_vals) < 3:
            print("Недостаточно данных для построения 3D графика")
            return
        
        # Проверим, что фильтрация дала данные
#        print(f"Данные после фильтрации: ")
#        print(f"x_vals: {len(x_vals)}, ppm_vals: {len(ppm_vals)}, cur_vals: {len(cur_vals)}, mq2_vals: {len(mq2_vals)}")
        
        # Подготовка данных для 3D
        x_vals_flat = np.tile(x_vals, 3)  # Все данные по оси X
        y_vals_flat = np.concatenate([np.zeros(len(ppm_vals)), np.ones(len(cur_vals)), np.full(len(mq2_vals), 2)])  # Y для PPM, CUR и MQ2
        z_vals_flat = np.concatenate([ppm_vals, cur_vals, mq2_vals])  # Z-значения: PPM, CUR и MQ2
        
        # Удаляем старые графики и рисуем новые
        ax3d.cla()  # Очистка оси перед новым рисованием

        # Рисуем новые поверхности с меньшей прозрачностью и улучшенными цветами
        ax3d.plot_trisurf(x_vals_flat, y_vals_flat, z_vals_flat, cmap='viridis', edgecolor='none', alpha=0.7)
        
        # Подписи на осях
        ax3d.set_xticks(np.linspace(x_vals[0], x_vals[-1], num=5))
        ax3d.set_xticklabels([mdates.num2date(t).strftime("%H:%M:%S") for t in np.linspace(x_vals[0], x_vals[-1], num=5)], rotation=45, ha='right')
        ax3d.set_zticks([0, 1, 2])
        ax3d.set_zticklabels(['PPM', 'CUR', 'MQ2'])

        # Обновление графика
        fig.canvas.draw()

    except Exception as e:
        print(f"Ошибка в update_plots: {e}")
    return []


# ======================== Режимы работы ===========================
def gui_mode():
    send_device_command(20, force=True)
    calibrate_sensor()
    ani = FuncAnimation(fig, update_plots, interval=int(INTERVAL * 1000), blit=False)
    plt.tight_layout()
    plt.show()

def terminal_mode():
    send_device_command(20, force=True)
    calibrate_sensor()
    try:
        while True:
            update_terminal()
            time.sleep(INTERVAL)
    except KeyboardInterrupt:
        print("Выход из терминального режима.")

def print_help():
    help_msg = (
        "Использование:\n"
        "  python3 script.py [--help] [gui=true|false]\n\n"
        "Опции:\n"
        "  --help         Вывод этой справки\n"
        "  gui=true       Запуск в графическом режиме (по умолчанию)\n"
        "  gui=false      Запуск в терминальном режиме (псевдографика)\n"
    )
    print(help_msg)

# ======================== Основной блок ===========================
if __name__ == "__main__":
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("gui", nargs="?", default="gui=true")
    parser.add_argument("--help", action="store_true")
    args, unknown = parser.parse_known_args()
    
    if args.help:
        print_help()
        sys.exit(0)
    
    gui_mode_flag = True
    if "gui=false" in sys.argv or "gui=0" in sys.argv or "nogui" in sys.argv:
        gui_mode_flag = False

    if gui_mode_flag:
        gui_mode()
    else:
        terminal_mode()
