#!/usr/bin/env python3
import serial
import socket
import time
import json
import subprocess
import argparse
import threading
from collections import OrderedDict
import requests
import io
from io import BytesIO
# ASN.1 tags
ASN1_INTEGER = 0x02
ASN1_OCTET_STRING = 0x04
ASN1_NULL = 0x05
ASN1_OBJECT_IDENTIFIER = 0x06
ASN1_SEQUENCE = 0x30
ASN1_GET_REQUEST_PDU = 0xA0
ASN1_GET_RESPONSE_PDU = 0xA2
ASN1_GET_NEXT_REQUEST_PDU = 0xA1

# Configuration Section
ipmiip = "192.168.1.60"      # IP iLO/IPMI
ipmilogin = "Administrator"  # IPMI login
ipmipassword = "Pass$"    # IPMI password
prefan = 120                 # Pre-fan at start 100% (n seconds)
country = "Moscow"           # City
debug_mode = False

# Global
global_fan_speeds = {}
global_temperatures = {}
global_outdoor_temp = 0.0
global_status = {
    'fan_speeds': {},
    'temps': {},
    'outdoor_temp': 0.0,
    'weather': "",
    'last_update_time': time.time()
}

try:
    # Get location information
    response = requests.get('https://ipinfo.io', timeout=5)
    response.raise_for_status()
    data = response.json()
    city = data.get('city', country)
    print(f"City found, using {city}")
except requests.exceptions.RequestException as e:
    print(f"Error getting city: {e}, using default: {country}")
    city = country


# ASN.1
def encode_integer(value):
    if value == 0:
        return bytes([ASN1_INTEGER, 1, 0])
    length = (value.bit_length() + 7) // 8
    return bytes([ASN1_INTEGER, length]) + value.to_bytes(length, 'big', signed=value<0)

def encode_octet_string(value):
    value = value.encode('latin1')
    return bytes([ASN1_OCTET_STRING, len(value)]) + value

def encode_null():
    return bytes([ASN1_NULL, 0])

def encode_oid(oid):
    parts = list(map(int, oid.split('.')))
    if len(parts) < 2:
        parts = [1, 3] + parts
    first = parts[0] * 40 + parts[1]
    encoded = [first]
    for part in parts[2:]:
        tmp = []
        while part > 0:
            tmp.insert(0, part & 0x7f)
            part >>= 7
        if not tmp:
            tmp = [0]
        for i in range(len(tmp)-1):
            tmp[i] |= 0x80
        encoded.extend(tmp)
    return bytes([ASN1_OBJECT_IDENTIFIER, len(encoded)]) + bytes(encoded)

def decode_length(stream):
    length = stream.read(1)[0]
    if length & 0x80:
        nbytes = length & 0x7f
        length = int.from_bytes(stream.read(nbytes), 'big')
    return length

def parse_snmp(data):
    stream = BytesIO(data)
    try:
        if stream.read(1)[0] != ASN1_SEQUENCE:
            raise ValueError("Invalid SNMP packet")
        decode_length(stream)  # Skip overall length
        # Version
        if stream.read(1)[0] != ASN1_INTEGER:
            raise ValueError("Invalid version")
        ver_len = decode_length(stream)
        version = int.from_bytes(stream.read(ver_len), 'big')
        # Community
        if stream.read(1)[0] != ASN1_OCTET_STRING:
            raise ValueError("Invalid community")
        comm_len = decode_length(stream)
        community = stream.read(comm_len).decode('latin1')
        # PDU type
        pdu_type = stream.read(1)[0]
        pdu_len = decode_length(stream)
        # Request ID
        if stream.read(1)[0] != ASN1_INTEGER:
            raise ValueError("Invalid request ID")
        req_id_len = decode_length(stream)
        request_id = int.from_bytes(stream.read(req_id_len), 'big')
        # Error status and index
        if stream.read(1)[0] != ASN1_INTEGER:
            raise ValueError("Invalid error status")
        err_stat_len = decode_length(stream)
        stream.read(err_stat_len)  
        if stream.read(1)[0] != ASN1_INTEGER:
            raise ValueError("Invalid error index")
        err_idx_len = decode_length(stream)
        stream.read(err_idx_len)  
        # Varbind list
        if stream.read(1)[0] != ASN1_SEQUENCE:
            raise ValueError("Invalid varbind list")
        varbind_len = decode_length(stream)
        oids = []
        end_pos = stream.tell() + varbind_len
        while stream.tell() < end_pos:
            if stream.read(1)[0] != ASN1_SEQUENCE:
                break
            var_len = decode_length(stream)
            # OID
            if stream.read(1)[0] != ASN1_OBJECT_IDENTIFIER:
                break
            oid_len = decode_length(stream)
            oid_data = stream.read(oid_len)
            # Decode OID
            parts = []
            first = oid_data[0]
            parts.extend([first // 40, first % 40])
            current = 0
            for byte in oid_data[1:]:
                current = (current << 7) | (byte & 0x7f)
                if not byte & 0x80:
                    parts.append(current)
                    current = 0
            oid = '.'.join(map(str, parts))
            # Skip value
            value_tag = stream.read(1)[0]
            value_len = decode_length(stream)
            stream.read(value_len)
            oids.append(oid)
        return {
            'version': version,
            'community': community,
            'pdu_type': pdu_type,
            'request_id': request_id,
            'oids': oids
        }
    except Exception as e:
        raise ValueError(f"SNMP parsing error: {str(e)}")

def get_next_oid(oids, current_oid):
    current_parts = list(map(int, current_oid.split('.')))
    sorted_oids = sorted(
        oids.keys(),
        key=lambda x: list(map(int, x.split('.')))
    )
    for oid in sorted_oids:
        oid_parts = list(map(int, oid.split('.')))
        if oid_parts > current_parts:
            return oid
    return None

def create_response(version, community, request_id, oid_values):
    varbinds = b''
    for oid, value in oid_values.items():
        encoded_oid = encode_oid(oid)
        varbind = (
            bytes([ASN1_SEQUENCE, len(encoded_oid + value)]) +
            encoded_oid +
            value
        )
        varbinds += varbind
    pdu = (
        encode_integer(request_id) +
        encode_integer(0) +  # error status
        encode_integer(0) +  # error index
        bytes([ASN1_SEQUENCE, len(varbinds)]) +
        varbinds
    )
    return (
        bytes([ASN1_SEQUENCE]) +
        _encode_length(len(encode_integer(version) + encode_octet_string(community) + 
                      bytes([ASN1_GET_RESPONSE_PDU]) + _encode_length(len(pdu)) + pdu)) +
        encode_integer(version) +
        encode_octet_string(community) +
        bytes([ASN1_GET_RESPONSE_PDU]) +
        _encode_length(len(pdu)) +
        pdu
    )

def _encode_length(length):
    if length < 0x80:
        return bytes([length])
    length_bytes = length.to_bytes((length.bit_length() + 7) // 8, 'big')
    return bytes([0x80 | len(length_bytes)]) + length_bytes

# Класс для работы с вентиляторами
class FanController:
    def __init__(self, offset, usetemp="warning"):
        self.last_outdoor_temp = 0.0
        self.last_outdoor_update = 0
        self.serial_port = self._connect_arduino()
        self.MIN_SPEED = self.update_min_speed_initial()
        self.MAX_SPEED = 100
        self.offset = offset / 100.0
        self.usetemp = usetemp.lower()
        self.fan_map = {
            1: [0,1,2,3,4,5], 2: [1,2], 3: [3,4],
            4: [1,2], 5: [1,2], 6: [3,4], 7: [3,4],
            8: [0,1,2,3,4,5], 9: [0,5], 10: [1,2,3,4],
            11: [0,5], 12: [0,1,2,3,4,5], 16: [0,5],
            17: [0,5], 18: [0,5], 19: [0,5], 20: [0,5],
            21: [1,2,3,4], 22: [1,2,3,4], 23: [0,5],
            24: [0,5], 25: [0,5], 26: [0,5], 28: [0,5], 29: [0,1,2],
            30: [0,1,2,3,4,5]
        }
        self.sensor_overrides = {
            30: {"warning": 100, "critical": 110},
            29: {"warning": 81, "critical": 85}  
        }
#        self.latest_status = {'fan_speeds': {}, 'temps': {}, 'outdoor_temp': 0.0}
        self.latest_status = {
            'fan_speeds': {}, 
            'temps': self.get_temperatures(),
            'outdoor_temp': self.last_outdoor_temp,
            'weather': global_status['weather'],
            'usetemp': self.usetemp,
            'last_update_time': time.time()
        }
        global_status.update(self.latest_status)
        
        update_thread = threading.Thread(target=self.periodic_update_min_speed, daemon=True)
        update_thread.start()

    def _connect_arduino(self):
        try:
            ser = serial.Serial('/dev/ttyUSB0', 115200, timeout=1)
            time.sleep(2)
            return ser
        except serial.SerialException as e:
            print(f"Error connecting to Arduino: {e}")
            raise

    def get_temperatures(self):
        cmd = (f"ipmitool -I lanplus -H {ipmiip} -U {ipmilogin} -P {ipmipassword} "
               "sensor list 2>/dev/null | grep degrees")
        try:
            output = subprocess.check_output(cmd, shell=True).decode()
            temps = OrderedDict()
            for line in output.split('\n'):
                if 'Temp' in line and '|' in line:
                    parts = [p.strip() for p in line.split('|')]
                    if len(parts) < 10:
                        continue
                    try:
                        sensor_num = int(parts[0].split()[1])
                        current_temp = float(parts[1])
                        warning_temp = float(parts[8])
                        critical_temp = float(parts[9])
                        temps[sensor_num] = {
                            'current': current_temp,
                            'warning': warning_temp,
                            'critical': critical_temp
                        }
                    except (ValueError, IndexError):
                        continue
            return temps
        except subprocess.CalledProcessError as e:
            print(f"Error executing IPMI command: {e}")
            return OrderedDict()

    def calculate_required_speed(self, current_temp, base_temp):
        safety_threshold = base_temp * (1 - self.offset)
        if current_temp < safety_threshold:
            return self.MIN_SPEED 
        speed_range = self.MAX_SPEED - self.MIN_SPEED
        temp_range = base_temp - safety_threshold
        speed = self.MIN_SPEED + int((current_temp - safety_threshold) / temp_range * speed_range)
        return max(self.MIN_SPEED, min(self.MAX_SPEED, speed))

    def _draw_ansi_dashboard(self, temps, fan_speeds):
        print("\033[H\033[J", end="")
        if time.time() - self.last_outdoor_update > 3600:
            try:
                self.last_outdoor_temp = self.get_outdoor_temperature()
                self.last_outdoor_update = time.time()
            except Exception as e:
                print(f"\033[1;31mError getting outdoor temp: {e}\033[0m")
                self.last_outdoor_temp = 0.0
        print("\033[1;36m╔════════════════════════════════════════════╗")
        print("\033[1;36m║\033[1;34m SERVER COOLING SYSTEM                      \033[1;36m║")
        print(f"\033[1;36m║ City: {city.ljust(15)} Weather: {str(self.last_outdoor_temp).ljust(4)}°C\033[1;36m      ║")
        print("\033[1;36m╚════════════════════════════════════════════╝\033[0m")
        print("\033[1;35mTEMPERATURE SENSORS:\033[0m")
        for sensor, data in temps.items():
            current_temp = data['current']
            if sensor in self.sensor_overrides and self.usetemp in self.sensor_overrides[sensor]:
                base_temp = self.sensor_overrides[sensor][self.usetemp]
                override_used = True
            else:
                base_temp = data[self.usetemp]
                override_used = False
            ratio = current_temp / base_temp
            color = self._get_temp_color(ratio)
            bar = self._create_3d_bar(ratio, 20)
            base_type = 'WARN' if self.usetemp == 'warning' else 'CRIT'
            source = "OVERRIDE" if override_used else "IPMI"
            print(f" \033[35m{sensor:2d}:\033[0m {color}{current_temp:5.1f}°C \033[0m{bar} "
                  f"\033[35m[{ratio*100:3.0f}%]\033[0m \033[90m({base_type}: {base_temp}°C, {source})\033[0m")
        print("\033[1;35mFAN CONTROL:\033[0m")
        for fan, speed in fan_speeds.items():
            ratio = speed / 100
            color = self._get_speed_color(ratio)
            bar = self._create_fan_bar(ratio, 15)
            fan_char = self._get_fan_visual(speed)
            print(f" \033[35mFan{fan}:\033[0m {color}{speed:3d}% \033[0m{bar} "
                  f"{fan_char*3} \033[90m(MIN:{self.MIN_SPEED}% MAX:{self.MAX_SPEED}%)\033[0m")
        print("\033[1;36m╔══════════════════════════════════════════╗")
        print("\033[1;36m║\033[1;33m Status: \033[32mNORMAL \033[90m| \033[33mUpdated:\033[0m", 
              time.strftime("%H:%M:%S"), "\033[1;36m      ║")
        print("\033[1;36m╚══════════════════════════════════════════╝\033[0m")
    
    def _get_temp_color(self, ratio):
        if ratio >= 0.9: return "\033[1;31m"
        elif ratio >= 0.82: return "\033[1;33m"
        else: return "\033[1;32m"
    
    def _get_speed_color(self, ratio):
        if ratio >= 0.8: return "\033[1;31m"
        elif ratio >= 0.5: return "\033[1;33m"
        else: return "\033[1;32m"
    
    def _create_3d_bar(self, ratio, width):
        filled = int(width * ratio)
        bar = []
        for i in range(width):
            if i < filled:
                if ratio > 0.9: bar.append("\033[41m \033[101m ")
                elif ratio > 0.82: bar.append("\033[43m \033[103m ")
                else: bar.append("\033[42m \033[102m ")
            else: bar.append("\033[100m \033[40m ")
        return ''.join(bar) + '\033[0m'
    
    def _create_fan_bar(self, ratio, width):
        filled = int(width * ratio)
        symbols = ['▁','▂','▃','▄','▅','▆','▇','█']
        symbols = ['\u2581', '\u2582', '\u2583', '\u2584', '\u2585', '\u2586', '\u2587', '\u2588']
        bar = []
        for i in range(width):
            if i < filled:
                level = min(int(ratio * 8), 7)
                bar.append(f"\033[1;36m{symbols[level]}")
            else: bar.append("\033[90m▁")
        return ''.join(bar) + '\033[0m'
    
    def _get_fan_visual(self, speed):
        if speed > 80:
            return "\u26A1"  
        elif speed > 50:
            return "\u1F32C"  
        else:
            return "\u273F"  
    
    def control_fans(self):
        temps = self.get_temperatures()
        if not temps:
            print("\033[1;31mERROR: No temperature data received\033[0m")
            return False
        fan_speeds = {fan: self.MIN_SPEED for fan in range(6)}
        for sensor, data in temps.items():
            if sensor not in self.fan_map:
                continue
            current_temp = data['current']
            if sensor in self.sensor_overrides and self.usetemp in self.sensor_overrides[sensor]:
                base_temp = self.sensor_overrides[sensor][self.usetemp]
            else:
                base_temp = data[self.usetemp]
            required_speed = self.calculate_required_speed(current_temp, base_temp)
            for fan in self.fan_map[sensor]:
                if required_speed > fan_speeds[fan]:
                    fan_speeds[fan] = required_speed
        for fan, speed in fan_speeds.items():
            self._send_fan_command(fan, speed)
        self._draw_ansi_dashboard(temps, fan_speeds)
    
        # save data for SNMP
        self.latest_status = {
            'fan_speeds': fan_speeds,
            'temps': temps,
            'outdoor_temp': self.last_outdoor_temp,
            'usetemp': self.usetemp,
            'last_update_time': time.time()
        }
        global_status.update(self.latest_status)
        if debug_mode:
            print("Global status updated:", global_status) 
        return True

    def _send_fan_command(self, fan_idx, speed):
        safe_speed = max(self.MIN_SPEED, min(self.MAX_SPEED, speed))
        inverted_speed = 100 - safe_speed
        try:
            cmd = json.dumps({"fan": fan_idx, "speed": inverted_speed})
            self.serial_port.write((cmd + '\n').encode())  
            print(f"\033[90m[DEBUG] Fan -> {speed}%\033[0m", end='\r')
        except Exception as e:
            print(f"\033[1;31mERROR: Failed to send command to fan: {e}\033[0m")
    
    def get_outdoor_temperature(self):
        try:
            # get C temperatures at the city
            if debug_mode:
                output = subprocess.check_output("echo -10°C", shell=True).decode().strip()
            else:
                output = subprocess.check_output(f"timeout 10 curl wttr.in/{country}?format=%t --silent", shell=True).decode().strip()
            
            temp_str = output.replace("°C", "").replace("+", "").strip()
            self.last_outdoor_temp = float(temp_str)
            
            return self.last_outdoor_temp
        except Exception as e:
            raise Exception(f"Error retrieving outdoor temperature: {e}")
    
    def update_min_speed_initial(self):
        try:
            outdoor_temp = self.get_outdoor_temperature()
            new_min = self.determine_min_speed(outdoor_temp)
            print(f"On startup: outdoor temperature: {outdoor_temp}°C → MIN_SPEED = {new_min}%")
            return new_min
        except Exception as e:
            print(e)
            print("Failed to get temperature on startup, setting MIN_SPEED = 20%")
            return 20
    
    def determine_min_speed(self, outdoor_temp):
        if outdoor_temp > 15: return 30
        elif -3 <= outdoor_temp <= 5: return 20
        elif outdoor_temp < -3: return 10
        else: return 25
    
    def periodic_update_min_speed(self):
        while True:
            time.sleep(43200)  # 12 hours
            try:
                outdoor_temp = self.get_outdoor_temperature()
                new_min = self.determine_min_speed(outdoor_temp)
                print(f"\nUpdate: outdoor temperature: {outdoor_temp}°C → MIN_SPEED updated to {new_min}%")
                self.MIN_SPEED = new_min
            except Exception as e:
                print(f"\nError updating MIN_SPEED: {e}\nMIN_SPEED value not changed.")
    
    def run(self):
        try:
            print("\033[1;32mStarting fan control system\033[0m")
            print(f"\033[1;34mSetting all fans to 100% for {prefan} seconds\033[0m")
            for fan in range(6):
                self._send_fan_command(fan, 100)
            time.sleep(prefan)
            print(f"\033[33mSpeed range: {self.MIN_SPEED}-{self.MAX_SPEED}%\033[0m")
            while True:
                success = self.control_fans()
                if not success:
                    print("\033[1;33mRetrying in 10 seconds...\033[0m")
                    time.sleep(10)
                else:
                    time.sleep(5)
        except KeyboardInterrupt:
            print("\n\033[1;33mResetting fans to minimum speed...\033[0m")
            for fan in range(6):
                self._send_fan_command(fan, self.MIN_SPEED)
        finally:
            if self.serial_port:
                self.serial_port.close()
            print("\033[1;32mFan control system stopped\033[0m")
    
    def test_mode(self):
        print("\033[1;33mStarting test mode...\033[0m")
        try:
            for speed in [100, 50, 100]:
                print(f"\033[1;34mSetting all fans to {speed}%\033[0m")
                for fan in range(6):
                    self._send_fan_command(fan, speed)
                time.sleep(90)
        except KeyboardInterrupt:
            pass
        finally:
            print("\033[1;32mTest completed\033[0m")

class SNMPServer(threading.Thread):
    def __init__(self, fan_controller, snmp_port=161, global_status=None):
        super().__init__(daemon=True)
        self.fan_controller = fan_controller
        self.snmp_port = snmp_port
        self.global_status = global_status or {}
        self.city = city
        self.country = country
        self.global_outdoor_temp = global_outdoor_temp

        # Create OIDs for all required data
        self.oids = OrderedDict()
        self.oids['1.3.6.1.2.1.1.1.0'] = lambda _: encode_octet_string("SNMP Fan Proxy Server")
        self.oids['1.3.6.1.2.1.1.5.0'] = lambda _: encode_octet_string(self.city)
        self.oids['1.3.6.1.2.1.1.8.0'] = lambda _: encode_integer(int(self.global_status.get('outdoor_temp', 0.0)))
        self.oids['1.3.6.1.2.1.1.9.0'] = lambda _: encode_octet_string(self.global_status.get('usetemp', 'warning'))
        self.oids['1.3.6.1.2.1.1.10.0'] = lambda _: encode_integer(int(self.global_status.get('last_update_time', 0)))
 
        # For each fan (using global_status['fan_speeds'])
        for i in range(6):  # 0-5
            self.oids[f'1.3.6.1.2.1.1.2.{i+1}.0'] = lambda _, i=i: encode_integer(
                self.global_status['fan_speeds'].get(i, 0)  
            )

        # For each temperature sensor (use global_status['temps'] and key i)
        for i in range(1, 31):
            # Current C from ipmi
            self.oids[f'1.3.6.1.2.1.1.4.{i}.0.0'] = lambda _, i=i: encode_integer(
                int(self.get_temp_value(i, 'current'))
            )
            # Warning threshold
            self.oids[f'1.3.6.1.2.1.1.4.{i}.1.0'] = lambda _, i=i: encode_integer(
                int(self.get_temp_value(i, 'warning'))
            )
            # Critical threshold
            self.oids[f'1.3.6.1.2.1.1.4.{i}.2.0'] = lambda _, i=i: encode_integer(
                int(self.get_temp_value(i, 'critical'))
            )

    def get_temp_value(self, sensor, key_type):
        temps = self.global_status.get('temps', {})
        sensor_data = temps.get(sensor, {})
        usetemp = self.global_status.get('usetemp', 'warning')
        
        # Check for override
        if sensor in self.fan_controller.sensor_overrides:
            override = self.fan_controller.sensor_overrides[sensor]
            if key_type == 'warning' and 'warning' in override:
                return override['warning']
            elif key_type == 'critical' and 'critical' in override:
                return override['critical']
        
        # Return value from IPMI
        if key_type == 'current':
            return sensor_data.get('current', 0)
        elif key_type == 'warning':
            return sensor_data.get('warning', 0)
        elif key_type == 'critical':
            return sensor_data.get('critical', 0)
        return 0

    def run(self):
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.bind(('192.168.1.1', self.snmp_port))
            print(f"SNMP server listening on {self.snmp_port}")
            print("Test with: snmpwalk -v2c -c public 192.168.1.1 1.3.6.1.2.1.1")
            while True:
                try:
                    data, addr = sock.recvfrom(65535)
                    try:
                        request = parse_snmp(data)
                    except ValueError as e:
                        print(f"Invalid packet: {e}")
                        print("Hex dump:", binascii.hexlify(data).decode())
                        continue
                    if request['community'] != 'public':
                        print(f"Invalid community: {request['community']}")
                        continue
                    response_oids = OrderedDict()
                    for oid in request['oids']:
                        if request['pdu_type'] == ASN1_GET_REQUEST_PDU:
                            if oid in self.oids:
                                response_oids[oid] = self.oids[oid](oid) if callable(self.oids[oid]) else self.oids[oid]
                            else:
                                response_oids[oid] = encode_null()
                        elif request['pdu_type'] == ASN1_GET_NEXT_REQUEST_PDU:
                            next_oid = get_next_oid(self.oids, oid)
                            if next_oid:
                                response_oids[next_oid] = self.oids[next_oid](next_oid) if callable(self.oids[next_oid]) else self.oids[next_oid]
                            else:
                                response_oids[oid] = encode_null()
                    response = create_response(
                        request['version'],
                        request['community'],
                        request['request_id'],
                        response_oids
                    )
                    sock.sendto(response, addr)
                except KeyboardInterrupt:
                    print("\nServer stopped")
                    break
                except Exception as e:
                    print(f"Error: {str(e)}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Server fan speed control with SNMP agent')
    parser.add_argument('--offset', type=int, default=20, help='Percentage below base temperature (default 20%)')
    parser.add_argument('--usetemp', type=str, default="warning", choices=["warning", "critical"],
                        help='Use warning or critical temperature for calculation')
    parser.add_argument('--test', action='store_true', help='Test mode (check all fans)')
    parser.add_argument('--snmp', action='store_true', help='Start SNMP server')
    args = parser.parse_args()
    
    controller = FanController(args.offset, args.usetemp)
    
    # If SNMP agent startup is requested, we start it in a separate thread
    if args.snmp:
        snmp_server = SNMPServer(controller, global_status=global_status)
        snmp_server.start()  # Now start() starts the thread, not run()
    
    # Launch the monitoring system in the main thread
    if args.test:
        controller.test_mode()
    else:
        controller.run()

