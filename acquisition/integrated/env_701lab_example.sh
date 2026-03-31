# 701 Lab Integrated Logger v1.3 env (systemd version)

# ===== Storage (override) =====
LOGGER_STORAGE_ROOT=/media/seven_zero_one/MF-SU2C/701lab_data/runs

# ===== Simulation =====
# SIMULATE=1

# ===== IMU (WITMOTION BWT901CL) =====
IMU_ENABLE=1
IMU_PORT=/dev/ttyUSB0
IMU_BAUD=115200
IMU_SERIAL_TIMEOUT=0.2

# ===== Audio (USB microphone via ALSA arecord) =====
AUDIO_ENABLE=1
AUDIO_DEVICE=hw:3,0
AUDIO_RATE=48000
AUDIO_CHANNELS=1
AUDIO_FORMAT=S16_LE
AUDIO_FILE_WAV=audio.wav
AUDIO_CHUNK_SEC=0
AUDIO_NICE=0
AUDIO_SIGINT_TIMEOUT_SEC=8.0
AUDIO_SIGTERM_TIMEOUT_SEC=4.0
AUDIO_KILL_TIMEOUT_SEC=2.0

# ===== Polar (H9/H10 via BLE, Bleak) =====
POLAR_ENABLE=1
POLAR_DEVICE=24:AC:AC:12:4E:72

# ===== GPS =====
# GPS uses fixed config in code (/dev/serial0, 9600).
