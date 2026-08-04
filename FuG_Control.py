#!/usr/bin/env python3
"""
FuG Control - Simple command line interface for controlling a FuG power supply.

Version 0.6.0
Author: Patrick Sturm
Copyright 2025 TOFWERK
"""

import os
import socket
import time
import threading
import logging
import argparse
import prompt_toolkit
from prompt_toolkit.styles import Style
from prompt_toolkit.patch_stdout import patch_stdout
from dataclasses import dataclass, field
from TofDaq import *
from TwTool import *

FUG_IP = '10.205.100.208'
FUG_PORT = 2101
FUG_POLL_INTERVAL = 1.0  # seconds

TPS_IP = 'localhost'
INTERLOCK_MON_RC = 601  # INTERLOCK_MON RC code
INTERLOCK_POLL_INTERVAL = 1.0  # seconds

HELP_MESSAGE = """
FuG Control - Simple command line interface for controlling a FuG power supply.

Commands:
u1000       Set voltage to e.g. 1000 V
f0          Set output OFF
f1          Set output ON
p0          Set polarity to +
p1          Set polarity to -
>s1 0.0001  Set current limit to e.g. 0.0001 A
>s0r 500    Set ramp speed to e.g. 500 V/s
>s0b 1      Enable ramping
h           Show this help message
c           Clear screen
q           Quit
"""

parser = argparse.ArgumentParser(description = 'Simple command line interface for controlling a FuG power supply.')
parser.add_argument('-i', '--interlock', action = 'store_true', help = 'run with TPS2 interlock monitoring')
args = parser.parse_args()

class FUG:
  def __init__(self, ip, port, timeout = 2.0):
    self.ip = ip
    self.port = port
    self.timeout = timeout
    self._socket = None
    self._lock = threading.Lock()

  def connect(self) -> str:
    self._socket = socket.create_connection((self.ip, self.port), timeout = self.timeout)
    return self.send_command('*IDN?')

  def close(self):
    if self._socket is not None:
      self._socket.close()
      self._socket = None

  def _recv_line(self) -> str:
    buffer = bytearray()
    while b'\n' not in buffer:
      chunk = self._socket.recv(1024)
      if not chunk:
        raise ConnectionError('Connection closed.')
      buffer.extend(chunk)
    line = buffer.partition(b'\r\n')[0]
    return line.decode()

  def send_command(self, command) -> str:
    if self._socket is None:
      raise RuntimeError('FuG not connected.')
    with self._lock:
      self._socket.sendall(f'{command}\n'.encode())
      return self._recv_line()

@dataclass
class State:
  voltage: float = 0.0
  current: float = 0.0
  last_response: str = ''
  interlock: bool = False
  lock: threading.Lock = field(default_factory=threading.Lock)

state = State()

class LogHandler(logging.Handler):
  """Ensure logging works with prompt_toolkit."""
  def emit(self, record):
    print(self.format(record))

def setup_logging():
  logging.basicConfig(
    level = logging.INFO,
    handlers = [LogHandler()],
    format = '%(asctime)s [%(levelname)s] %(message)s',
    datefmt = '%Y-%m-%d %H:%M:%S',
  )
  return logging.getLogger(__name__)

log = setup_logging()

def monitor_fug(stop_event, fug):
  while not stop_event.is_set():
    try:
      state.voltage = parse_response(fug.send_command('>m0?'))
      state.current = parse_response(fug.send_command('>m1?'))
    except (socket.timeout, ConnectionError, ValueError) as e:
      log.error('FuG polling failed: %s', e)
    stop_event.wait(FUG_POLL_INTERVAL)

def parse_response(response: str) -> float:
  if response.startswith('M0:'):
    return float(response[3:])
  elif response.startswith('M1:'):
    return float(response[3:])*1e6
  else:
    return float('nan')

def bottom_toolbar():
  text = f'Voltage: {state.voltage:.1f} V, Current: {state.current:.1f} \u00B5A'
  if state.interlock:
    return [('class:interlock', text)]
  if (abs(state.voltage) > 5):
    return [('class:set', text)]
  return [('class:bottom-toolbar', text)]

def dynamic_rprompt():
  if state.last_response == 'E0':
    return 'OK'
  return state.last_response

def monitor_interlock(stop_event, fug):
  while not stop_event.is_set():
    value = np.zeros(1, dtype=np.float64)
    rv = TwTpsGetMonitorValue(INTERLOCK_MON_RC, value)
    if (rv != TwSuccess):
      log.error(f'Failed to read INTERLOCK_MON: {TwTranslateReturnValue(rv).decode()}.')
    else:
      interlock_active = bool(value[0] == 1)
      with state.lock:
        if interlock_active and not state.interlock:
          state.interlock = True
          fug.send_command('f0')
          fug.send_command('u0')
          log.warning('Interlock triggered – output forced OFF.')
        elif not interlock_active and state.interlock:
          state.interlock = False
          fug.send_command('f1')
          log.info('Interlock cleared – output switched ON.')
    stop_event.wait(INTERLOCK_POLL_INTERVAL)

def main():
  os.system('title ' + 'FuG Control')
  os.system('cls')
  print(HELP_MESSAGE)

  # Connect to FuG
  fug = FUG(FUG_IP, FUG_PORT)
  fug_id = fug.connect()
  log.info(f'{fug_id.rstrip()} connected via {FUG_IP}:{FUG_PORT}')

  stop_event = threading.Event()
  threading.Thread(target=monitor_fug, args=(stop_event,fug,), daemon=True).start()

  if args.interlock:
    # Connect to TPS2
    if TwTpsConnect2(TPS_IP.encode(), 1) != TwSuccess:
      log.error('Failed to connect to TPS2.')
      fug.close()
      TwCleanupDll()
      return
    log.info(f'TPS2 connected via {TPS_IP} for interlock monitoring.\n')
    threading.Thread(target=monitor_interlock, args=(stop_event,fug,), daemon=True).start()

  style = Style.from_dict({
    'bottom-toolbar': '#FFFFFF bg:#333333 noreverse',
    'set': '#FFFFFF bg:green noreverse',
    'interlock': '#FFFFFF bg:red noreverse',
  })

  session = prompt_toolkit.PromptSession(
    '\u26A1 ', 
    bottom_toolbar = bottom_toolbar,
    rprompt = dynamic_rprompt,
    style = style,
    refresh_interval = 0.5
  )

  try:
    with patch_stdout():  # ensures logs appear above the prompt 
      while True:
        try:
          command = session.prompt()
        except (KeyboardInterrupt, EOFError):
          log.error('Program interrupted by user.')
          break
        if (command == 'q'):
          break
        elif (command == 'h'):
          print(HELP_MESSAGE)
        elif (command =='c'):
          os.system('cls')
        elif (command != ''):
          with state.lock:
            if (state.interlock and command.lower() == 'f1'):
              log.warning('Interlock active – output ON blocked.')
            else:
              state.last_response = fug.send_command(command)
  finally:
    stop_event.set()
    if args.interlock:
      TwTpsDisconnect()
      TwCleanupDll()
    fug.close()

if __name__ == '__main__':
  main()
