"""
IRIS — AI-Powered Wearable Personal Assistant for the Visually Impaired
========================================================================
Admin / Command Router  (main entry point for the full system)

Wake word : "Iris"   (detected via Porcupine, runs offline on-device)
STT       : Whisper  (records and transcribes the command after wake word)
TTS       : pyttsx3  (offline, fast, no network required)

Flow
----
1. Porcupine listens continuously for "Iris"
2. On detection → record COMMAND_RECORD_SECONDS of audio
3. Whisper transcribes audio → command text
4. Command router matches text → module number
5. Module launched as subprocess (cwd = its own folder)
6. Admin blocks until module exits, then returns to step 1

Module map (verified against actual repos)
------------------------------------------
  1  gps_navigation      Voice-Guided-GPS-Navigation-for-the-Visually-Impaired  → main.py
  2  visionaid           VisionAid-AI-Navigation-Assistant-for-the-Visually-Impaired → pi_client.py
  3  hybrid_navigation   AI-Vision-Assistant-for-the-Blind                       → main.py
  4  face_recognition    AI-Vision-Assistant-for-Real-Time-Face-Recognition      → main.py
  5  email_assistant     AI-Voice-Based-Email-Assistant                          → main.py
  6  scene_narrator      AI-Scene-Narrator                                       → main.py
  7  sos_emergency       Smart-SOS-alert-system                                  → sos.py

NOTE — Module 2 (VisionAid) is a split system:
  • server.py  runs on the LAPTOP  (heavy AI inference — YOLOv8, Depth Anything V2)
  • pi_client.py runs on the PI    (camera capture + TTS output)
  The admin launches pi_client.py.  Make sure server.py is already running on the
  laptop and SERVER_IP is set in modules/visionaid/config.py before activating.

Author : T. Adithya Reddy
Project: B.Tech Final Year Project — IRIS
"""

import os
import sys
import struct
import subprocess
import tempfile
import wave

import pvporcupine
import pyaudio

# ── Optional: Whisper STT ────────────────────────────────────────────────────
try:
    import whisper as _whisper
    WHISPER_AVAILABLE = True
except ImportError:
    WHISPER_AVAILABLE = False

# ── Optional: pyttsx3 TTS ────────────────────────────────────────────────────
try:
    import pyttsx3 as _pyttsx3
    _tts_engine = _pyttsx3.init()
    _tts_engine.setProperty("rate", 150)
    TTS_AVAILABLE = True
except Exception:
    TTS_AVAILABLE = False

# ────────────────────────────────────────────────────────────────────────────
# CONFIGURATION
# ────────────────────────────────────────────────────────────────────────────

PORCUPINE_ACCESS_KEY = os.environ.get(
    "PORCUPINE_ACCESS_KEY", "YOUR_PORCUPINE_ACCESS_KEY"
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Whisper model — "tiny" is fastest on Pi 5; "base" is more accurate
WHISPER_MODEL = "tiny"

# Seconds of audio to record after wake word for command capture
COMMAND_RECORD_SECONDS = 4

# PyAudio mic device index (None = system default)
MIC_DEVICE_INDEX = None

# ────────────────────────────────────────────────────────────────────────────
# MODULE REGISTRY
# folder name under modules/   →  entry script (relative to that folder)
# ────────────────────────────────────────────────────────────────────────────

MODULE_ENTRY = {
    1: ("gps_navigation",    "main.py"),        # GPS turn-by-turn navigation
    2: ("visionaid",         "pi_client.py"),   # Obstacle detection (Pi client)
    3: ("hybrid_navigation", "main.py"),        # GPS + obstacle combined
    4: ("face_recognition",  "main.py"),        # Face recognition
    5: ("email_assistant",   "main.py"),        # Voice email (Gemini AI)
    6: ("scene_narrator",    "main.py"),        # Scene / surroundings description
    7: ("sos_emergency",     "sos.py"),         # SOS emergency alert
}

MODULE_NAMES = {
    1: "GPS Navigation",
    2: "VisionAid Obstacle Detection",
    3: "Hybrid Navigation",
    4: "Face Recognition",
    5: "Email Assistant",
    6: "Scene Narrator",
    7: "SOS Emergency",
}

# ────────────────────────────────────────────────────────────────────────────
# COMMAND → MODULE MAPPING
# Longer / more specific phrases must come first (handled by sorted() below)
# ────────────────────────────────────────────────────────────────────────────

COMMAND_MAP = {
    # ── Module 1 : GPS Navigation ────────────────────────────────────────────
    "navigate to":           1,
    "take me to":            1,
    "go to":                 1,
    "directions to":         1,
    "navigate":              1,
    "navigation":            1,
    "gps":                   1,

    # ── Module 2 : VisionAid (obstacle detection only, Pi↔laptop) ───────────
    "vision aid":            2,
    "visionaid":             2,
    "obstacle detection":    2,
    "obstacle mode":         2,
    "obstacle":              2,

    # ── Module 3 : Hybrid Navigation (GPS + obstacle vision on Pi) ───────────
    "hybrid navigation":     3,
    "navigate with vision":  3,
    "vision navigation":     3,
    "hybrid":                3,

    # ── Module 4 : Face Recognition ──────────────────────────────────────────
    "face recognition":      4,
    "who is in front of me": 4,
    "who is in front":       4,
    "who is this":           4,
    "identify":              4,
    "recognize":             4,
    "face":                  4,
    "who":                   4,

    # ── Module 5 : Email Assistant ───────────────────────────────────────────
    "write an email":        5,
    "send an email":         5,
    "read my email":         5,
    "check my email":        5,
    "write email":           5,
    "send email":            5,
    "read email":            5,
    "check email":           5,
    "unread emails":         5,
    "email":                 5,
    "mail":                  5,

    # ── Module 6 : Scene Narrator ────────────────────────────────────────────
    "describe surroundings": 6,
    "what is around me":     6,
    "describe the scene":    6,
    "scene narrator":        6,
    "what is in front":      6,
    "surroundings":          6,
    "describe":              6,
    "narrate":               6,
    "scene":                 6,

    # ── Module 7 : SOS Emergency ─────────────────────────────────────────────
    "call for help":         7,
    "send sos":              7,
    "emergency":             7,
    "sos":                   7,
    "help":                  7,
}

# ────────────────────────────────────────────────────────────────────────────
# TTS HELPER
# ────────────────────────────────────────────────────────────────────────────

def speak(text: str) -> None:
    print(f"[IRIS] {text}")
    if TTS_AVAILABLE:
        try:
            _tts_engine.say(text)
            _tts_engine.runAndWait()
        except Exception as e:
            print(f"[IRIS][TTS error] {e}")


# ────────────────────────────────────────────────────────────────────────────
# AUDIO HELPERS
# ────────────────────────────────────────────────────────────────────────────

def _record_audio(seconds: int, sample_rate: int = 16000) -> bytes:
    """Record `seconds` of mono 16-bit PCM and return raw bytes."""
    pa = pyaudio.PyAudio()
    stream = pa.open(
        format=pyaudio.paInt16,
        channels=1,
        rate=sample_rate,
        input=True,
        input_device_index=MIC_DEVICE_INDEX,
        frames_per_buffer=512,
    )
    frames = []
    for _ in range(int(sample_rate / 512 * seconds)):
        frames.append(stream.read(512, exception_on_overflow=False))
    stream.stop_stream()
    stream.close()
    pa.terminate()
    return b"".join(frames)


def _transcribe(audio_bytes: bytes, sample_rate: int = 16000) -> str:
    """Transcribe raw PCM bytes via Whisper. Returns lowercase string."""
    if not WHISPER_AVAILABLE:
        return ""
    model = _whisper.load_model(WHISPER_MODEL)
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp_path = tmp.name
    with wave.open(tmp_path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(audio_bytes)
    result = model.transcribe(tmp_path, language="en")
    os.unlink(tmp_path)
    return result.get("text", "").strip().lower()


# ────────────────────────────────────────────────────────────────────────────
# COMMAND ROUTER
# ────────────────────────────────────────────────────────────────────────────

def parse_module(text: str) -> int | None:
    """Match spoken text to a module ID using longest-keyword-first matching."""
    text = text.lower()
    for keyword in sorted(COMMAND_MAP, key=len, reverse=True):
        if keyword in text:
            return COMMAND_MAP[keyword]
    return None


def run_module(module_id: int, full_command: str = "") -> None:
    """
    Launch the selected module as a blocking subprocess.
    Passes the full spoken command as the IRIS_COMMAND env variable so
    modules can optionally skip their own initial prompts.
    """
    folder, entry = MODULE_ENTRY[module_id]
    module_path = os.path.join(BASE_DIR, "modules", folder)
    script = os.path.join(module_path, entry)

    if not os.path.isfile(script):
        speak(
            f"Module {MODULE_NAMES[module_id]} is not installed. "
            "Please run setup.sh to clone all submodules."
        )
        print(f"[IRIS] Expected script not found: {script}")
        return

    # Special warning for Module 2 (VisionAid) — server must already be running
    if module_id == 2:
        speak(
            "Activating VisionAid. "
            "Make sure the VisionAid server is already running on the laptop."
        )
    else:
        speak(f"Activating {MODULE_NAMES[module_id]}.")

    print(f"\n{'='*60}")
    print(f"  Module {module_id} : {MODULE_NAMES[module_id]}")
    print(f"  Script  : {script}")
    print(f"{'='*60}\n")

    try:
        result = subprocess.run(
            [sys.executable, entry],
            cwd=module_path,
            env={**os.environ, "IRIS_COMMAND": full_command},
        )
        if result.returncode != 0:
            speak(f"{MODULE_NAMES[module_id]} exited with an error. Returning to Iris.")
        else:
            speak(f"{MODULE_NAMES[module_id]} complete. Say Iris to continue.")
    except KeyboardInterrupt:
        speak("Module interrupted. Returning to Iris.")
    except Exception as e:
        speak("An error occurred while running the module.")
        print(f"[IRIS][error] {e}")

    print(f"\n[IRIS] Module {module_id} finished. Back to wake-word listening.\n")


# ────────────────────────────────────────────────────────────────────────────
# MAIN LOOP
# ────────────────────────────────────────────────────────────────────────────

def main() -> None:
    print("\n" + "=" * 60)
    print("  IRIS — AI Wearable Assistant for the Visually Impaired")
    print("  Wake word : \"Iris\"")
    print("  Say 'Iris' then speak your command.")
    print("=" * 60 + "\n")

    if PORCUPINE_ACCESS_KEY == "YOUR_PORCUPINE_ACCESS_KEY":
        print("[ERROR] Porcupine access key not set.")
        print("        Export it:  export PORCUPINE_ACCESS_KEY=\"your_key\"")
        print("        Or edit PORCUPINE_ACCESS_KEY in this file.")
        print("        Free key at https://console.picovoice.ai/\n")
        sys.exit(1)

    if not WHISPER_AVAILABLE:
        print("[WARN] Whisper not installed → falling back to keyboard input.")
        print("       Install: pip install openai-whisper\n")

    # ── Initialise Porcupine ─────────────────────────────────────────────────
    try:
        porcupine = pvporcupine.create(
            access_key=PORCUPINE_ACCESS_KEY,
            keywords=["iris"],
        )
    except Exception as e:
        print(f"[ERROR] Porcupine initialisation failed: {e}")
        sys.exit(1)

    pa = pyaudio.PyAudio()
    audio_stream = pa.open(
        rate=porcupine.sample_rate,
        channels=1,
        format=pyaudio.paInt16,
        input=True,
        input_device_index=MIC_DEVICE_INDEX,
        frames_per_buffer=porcupine.frame_length,
    )

    speak("Iris is ready. Say Iris to activate.")

    try:
        while True:
            # ── Wake word detection ──────────────────────────────────────────
            pcm = audio_stream.read(
                porcupine.frame_length, exception_on_overflow=False
            )
            pcm_unpacked = struct.unpack_from("h" * porcupine.frame_length, pcm)

            if porcupine.process(pcm_unpacked) >= 0:
                speak("Yes?")
                print("[IRIS] Wake word detected. Listening for command…")

                if WHISPER_AVAILABLE:
                    audio_stream.stop_stream()
                    audio_bytes = _record_audio(COMMAND_RECORD_SECONDS)
                    audio_stream.start_stream()
                    command_text = _transcribe(audio_bytes)
                    print(f"[IRIS] Heard: \"{command_text}\"")
                else:
                    print("[IRIS] Type your command:")
                    command_text = input("  >> ").strip().lower()

                module_id = parse_module(command_text)

                if module_id:
                    run_module(module_id, full_command=command_text)
                    speak("Iris is listening. Say Iris to activate a module.")
                else:
                    speak(
                        "Sorry, I didn't understand that. "
                        "Try saying: navigate, obstacle mode, hybrid navigation, "
                        "face recognition, email, describe surroundings, or emergency."
                    )

    except KeyboardInterrupt:
        print("\n[IRIS] Shutting down.")
        speak("Iris shutting down. Goodbye.")
    finally:
        audio_stream.stop_stream()
        audio_stream.close()
        pa.terminate()
        porcupine.delete()


if __name__ == "__main__":
    main()