#!/usr/bin/python3
import serial
import time
import argparse
import logging

# Set up logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

def send_command(ser, command):
    logging.debug(f"Sending command: {command.hex()}")
    ser.write(command)
    time.sleep(0.1)
    response = ser.read(100)
    logging.debug(f"Received response: {response.hex()}")
    return response

def read_config(ser):
    command = bytes([0xC1, 0x00, 0x09])
    response = send_command(ser, command)
    if len(response) < 12:
        raise ValueError(f"Unexpected response length or format: {response.hex()}")
    return response[3:12]  # Return 9 bytes of configuration data

def write_config(ser, config):
    # C0 = Save on power down, 00 = Starting address, 09 = Length
    command = bytes([0xC0, 0x00, 0x09] + list(config))
    response = send_command(ser, command)
    if response[0:3] != bytes([0xC1, 0x00, 0x09]):
        raise ValueError(f"Failed to write configuration: {response.hex()}")
    return response[3:12]

def write_encryption_keys(ser, key_high, key_low):
    command = bytes([0xC0, 0x00, 0x02, key_high, key_low])
    response = send_command(ser, command)
    if response[0:3] != bytes([0xC1, 0x00, 0x02]):
        raise ValueError(f"Failed to write encryption keys: {response.hex()}")

def read_product_info(ser):
    command = bytes([0xC1, 0x80, 0x07])
    response = send_command(ser, command)
    if len(response) < 10:
        raise ValueError(f"Unexpected response length or format for product info: {response.hex()}")
    return response[3:10]

def parse_config(config):
    addh, addl, netid, reg0, reg1, reg2, reg3, reg4, reg5 = config
    address = (addh << 8) | addl
    network_address = netid
    channel = reg2
    air_rate_code = reg0 & 0x07
    air_rates = ["0.3k", "1.2k", "2.4k", "4.8k", "9.6k", "19.2k", "38.4k", "62.5k"]
    air_rate = air_rates[air_rate_code] if air_rate_code < len(air_rates) else "Unknown"
    baud_rate_code = (reg0 >> 5) & 0x07
    baud_rates = ["1200", "2400", "4800", "9600", "19200", "38400", "57600", "115200"]
    baud_rate = baud_rates[baud_rate_code] if baud_rate_code < len(baud_rates) else "Unknown"
    parity_code = (reg0 >> 3) & 0x03
    parities = ["8N1", "8O1", "8E1", "8N1"]
    parity = parities[parity_code]
    power_code = reg1 & 0x03
    powers = ["13dBm", "18dBm", "22dBm", "27dBm"]
    power = powers[power_code] if power_code < len(powers) else "Unknown"
    fixed_transmission = "Fixed-point" if reg3 & 0x40 else "Transparent"
    relay_function = "Enabled" if reg3 & 0x20 else "Disabled"
    lbt_enable = "Enabled" if reg3 & 0x10 else "Disabled"
    rssi_enable = "Enabled" if reg1 & 0x20 else "Disabled"
    noise_enable = "Enabled" if reg3 & 0x80 else "Disabled"
    
    return {
        "Address": f"0x{address:04X}",
        "Network Address": f"0x{network_address:02X}",
        "Channel": channel,
        "Air Rate": air_rate,
        "Baud Rate": baud_rate,
        "Parity": parity,
        "Transmitting Power": power,
        "Fixed Transmission": fixed_transmission,
        "Relay Function": relay_function,
        "LBT Enable": lbt_enable,
        "RSSI Enable": rssi_enable,
        "Noise Enable": noise_enable
    }

def create_config(address, network_address, channel, air_rate, baud_rate, parity, power, fixed_transmission, relay_function, lbt_enable, rssi_enable, noise_enable="0"):
    addh = (address >> 8) & 0xFF
    addl = address & 0xFF
    netid = network_address
    air_rates = {"0.3k": 0, "1.2k": 1, "2.4k": 2, "4.8k": 3, "9.6k": 4, "19.2k": 5, "38.4k": 6, "62.5k": 7}
    baud_rates = {"1200": 0, "2400": 1, "4800": 2, "9600": 3, "19200": 4, "38400": 5, "57600": 6, "115200": 7}
    parities = {"8N1": 0, "8O1": 1, "8E1": 2}
    powers = {"13dBm": 0, "18dBm": 1, "22dBm": 2, "27dBm": 3}

    reg0 = (baud_rates[baud_rate] << 5) | (parities[parity] << 3) | air_rates[air_rate]
    reg1 = 0xE0 | powers[power]
    if rssi_enable == "1": reg1 |= 0x20
    else: reg1 &= ~0x20

    reg2 = channel
    reg3 = 0x00 # Reset base
    if noise_enable == "1": reg3 |= 0x80
    if fixed_transmission == "1": reg3 |= 0x40
    if relay_function == "1": reg3 |= 0x20
    if lbt_enable == "1": reg3 |= 0x10

    return [addh, addl, netid, reg0, reg1, reg2, reg3, 0x00, 0x00]

def main():
    parser = argparse.ArgumentParser(description="Read/Write configuration for E22 LoRa module")
    parser.add_argument("--port", default="/dev/ttyUSB0", help="Serial port")
    parser.add_argument("--address", type=lambda x: int(x, 0), help="Set address (e.g., 0x1234)")
    parser.add_argument("--network-address", type=lambda x: int(x, 0), help="Set network address")
    parser.add_argument("--channel", type=int, help="Set channel (0-83)")
    parser.add_argument("--air-rate", choices=["0.3k", "1.2k", "2.4k", "4.8k", "9.6k", "19.2k", "38.4k", "62.5k"], help="Set air rate")
    parser.add_argument("--baud-rate", choices=["1200", "2400", "4800", "9600", "19200", "38400", "57600", "115200"], help="Set baud rate")
    parser.add_argument("--parity", choices=["8N1", "8O1", "8E1"], help="Set parity")
    parser.add_argument("--power", choices=["13dBm", "18dBm", "22dBm", "27dBm"], help="Set transmitting power")
    parser.add_argument("--fixed-transmission", choices=["0", "1"], help="Set fixed-point transmission (0: Transparent, 1: Fixed-point)")
    parser.add_argument("--relay-function", choices=["0", "1"], help="Set relay function (0: Disable, 1: Enable)")
    parser.add_argument("--lbt-enable", choices=["0", "1"], help="Set LBT enable (0: Disable, 1: Enable)")
    parser.add_argument("--rssi-enable", choices=["0", "1"], help="Enable RSSI reading (0: Disable, 1: Enable)")
    parser.add_argument("--write-key", nargs=2, type=lambda x: int(x, 16), help="Write encryption key (high low in hex)")
    parser.add_argument("--read-product-info", action="store_true", help="Read product information")
    parser.add_argument("--raw-config", help="Set entire config using hex string (9 bytes, e.g., '00000062E017700000')")
    args = parser.parse_args()

    try:
        baud_rate_to_use = int(args.baud_rate) if args.baud_rate else 9600
        with serial.Serial(args.port, baudrate=baud_rate_to_use, timeout=1) as ser:
            
            # 1. Handle Encryption Key
            if args.write_key:
                write_encryption_keys(ser, *args.write_key)
                print(f"Encryption keys written: 0x{args.write_key[0]:02X} 0x{args.write_key[1]:02X}")

            # 2. Handle Raw Configuration (Highest Priority)
            if args.raw_config:
                raw_bytes = bytes.fromhex(args.raw_config.replace(" ", ""))
                if len(raw_bytes) != 9:
                    raise ValueError(f"Raw config must be exactly 9 bytes, got {len(raw_bytes)}")
                write_config(ser, list(raw_bytes))
                print("Raw configuration updated successfully.")

            # 3. Handle Parameterized Configuration
            else:
                config_params = [args.address, args.network_address, args.channel, args.air_rate, 
                                 args.baud_rate, args.parity, args.power, args.fixed_transmission, 
                                 args.relay_function, args.lbt_enable, args.rssi_enable]
                
                if any(v is not None for v in config_params):
                    current_config = read_config(ser)
                    parsed_config = parse_config(current_config)

                    # Update only provided arguments
                    if args.address is not None: parsed_config['Address'] = f"0x{args.address:04X}"
                    if args.network_address is not None: parsed_config['Network Address'] = f"0x{args.network_address:02X}"
                    if args.channel is not None: parsed_config['Channel'] = args.channel
                    if args.air_rate is not None: parsed_config['Air Rate'] = args.air_rate
                    if args.baud_rate is not None: parsed_config['Baud Rate'] = args.baud_rate
                    if args.parity is not None: parsed_config['Parity'] = args.parity
                    if args.power is not None: parsed_config['Transmitting Power'] = args.power
                    if args.fixed_transmission is not None:
                        parsed_config['Fixed Transmission'] = "Fixed-point" if args.fixed_transmission == "1" else "Transparent"
                    if args.relay_function is not None:
                        parsed_config['Relay Function'] = "Enabled" if args.relay_function == "1" else "Disabled"
                    if args.lbt_enable is not None:
                        parsed_config['LBT Enable'] = "Enabled" if args.lbt_enable == "1" else "Disabled"
                    if args.rssi_enable is not None:
                        parsed_config['RSSI Enable'] = "Enabled" if args.rssi_enable == "1" else "Disabled"

                    new_config = create_config(
                        int(parsed_config['Address'], 16),
                        int(parsed_config['Network Address'], 16),
                        parsed_config['Channel'],
                        parsed_config['Air Rate'],
                        parsed_config['Baud Rate'],
                        parsed_config['Parity'],
                        parsed_config['Transmitting Power'],
                        "1" if parsed_config['Fixed Transmission'] == "Fixed-point" else "0",
                        "1" if parsed_config['Relay Function'] == "Enabled" else "0",
                        "1" if parsed_config['LBT Enable'] == "Enabled" else "0",
                        "1" if parsed_config['RSSI Enable'] == "Enabled" else "0"
                    )
                    write_config(ser, new_config)
                    print("Configuration updated successfully.")

            # 4. Display Final Status
            if args.read_product_info:
                print(f"Product Info: {read_product_info(ser).hex(' ').upper()}")

            final_config_raw = read_config(ser)
            final_parsed = parse_config(final_config_raw)
            print("\n--- E22 Current Configuration ---")
            for key, value in final_parsed.items():
                print(f"{key:20}: {value}")
            print(f"Raw Hex: {final_config_raw.hex(' ').upper()}")

    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    main()
