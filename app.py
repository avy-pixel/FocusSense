import threading
import time

import cv2
from flask import Flask, Response, jsonify, render_template, request

from focussense.session_engine import SessionEngine
from focussense.accountability import AccountabilityController

app = Flask(__name__)

engine = None
controller = None
camera = None
camera_lock = threading.Lock()

face_cascade = cv2.CascadeClassifier(
    cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
)

last_face_detected = False
camera_error = None


def release_camera():
    global camera

    with camera_lock:
        if camera is not None:
            camera.release()
            camera = None


def get_state():
    global engine, controller, camera_error, last_face_detected

    if engine is None:
        return {
            "status": "idle",
            "phase": None,
            "current_cycle": 0,
            "planned_cycles": 0,
            "completed_focus_intervals": 0,
            "remaining_seconds": 0,
            "face_missing": False,
            "warning_used": False,
            "warning_pause": False,
            "violation_count": 0,
            "message": "Choose your settings and start focusing.",
            "face_detected": False,
            "camera_error": None,
        }

    engine.tick()

    state = controller._state()
    state["face_detected"] = last_face_detected
    state["camera_error"] = camera_error
    return state


@app.route("/")
def home():
    return render_template("index.html")


@app.route("/api/start", methods=["POST"])
def start_session():
    global engine, controller, camera, camera_error, last_face_detected
    data = request.get_json(silent=True) or {}

    try:
        focus_minutes = int(data.get("focus_minutes", 25))
        break_minutes = int(data.get("break_minutes", 5))
        cycles = int(data.get("cycles", 4))

        if not 1 <= focus_minutes <= 180:
            raise ValueError("Focus duration must be 1–180 minutes.")

        if not 1 <= break_minutes <= 60:
            raise ValueError("Break duration must be 1–60 minutes.")

        if not 1 <= cycles <= 12:
            raise ValueError("Choose between 1 and 12 cycles.")

    except (ValueError, TypeError) as error:
        return jsonify({"error": str(error)}), 400

    if face_cascade.empty():
        return jsonify({"error": "OpenCV face detector could not load."}), 500

    release_camera()
    camera_error = None
    last_face_detected = False

    # Check that the camera is available before starting the timer.
    with camera_lock:
        camera = cv2.VideoCapture(0)

        if not camera.isOpened():
            camera.release()
            camera = None
            return jsonify({
                "error": "Camera unavailable. Check your camera connection "
                         "and browser permissions."
            }), 503

        success, _ = camera.read()

        if not success:
            camera.release()
            camera = None
            return jsonify({
                "error": "Could not read from the camera."
            }), 503

    engine = SessionEngine(
        focus_minutes=focus_minutes,
        break_minutes=break_minutes,
    )
    engine.start(cycles=cycles)

    controller = AccountabilityController(engine, grace_seconds=5)

    return jsonify(get_state())


def generate_frames():
    global camera, engine, controller
    global camera_error, last_face_detected

    while True:
        with camera_lock:
            active_camera = camera

            if active_camera is None:
                break

            success, frame = active_camera.read()

        if not success:
            camera_error = (
                "Camera connection lost. The timer has been paused."
            )

            if engine and engine.status == "running":
                engine.pause()

            if controller:
                controller.warning_pause = False
                controller.message = camera_error

            break

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        faces = face_cascade.detectMultiScale(
            gray,
            scaleFactor=1.1,
            minNeighbors=5,
            minSize=(50, 50),
        )

        last_face_detected = len(faces) > 0

        if engine is not None and controller is not None:
            engine.tick()

            # A camera error must never be treated as a face absence.
            controller.update(last_face_detected)

        for (x, y, width, height) in faces:
            cv2.rectangle(
                frame,
                (x, y),
                (x + width, y + height),
                (0, 200, 100),
                2,
            )

        label = (
            "Face detected"
            if last_face_detected
            else "No face detected"
        )

        cv2.putText(
            frame,
            label,
            (15, 30),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (0, 200, 100) if last_face_detected else (0, 0, 255),
            2,
        )

        success, buffer = cv2.imencode(".jpg", frame)

        if not success:
            continue

        yield (
            b"--frame\r\n"
            b"Content-Type: image/jpeg\r\n\r\n"
            + buffer.tobytes()
            + b"\r\n"
        )

        time.sleep(0.03)


@app.route("/video_feed")
def video_feed():
    if camera is None:
        return "Camera is not running.", 503

    return Response(
        generate_frames(),
        mimetype="multipart/x-mixed-replace; boundary=frame",
    )


@app.route("/api/state")
def session_state():
    return jsonify(get_state())


@app.route("/api/action", methods=["POST"])
def session_action():
    global engine, controller, camera_error

    if engine is None or controller is None:
        return jsonify({"error": "Start a session first."}), 400

    data = request.get_json(silent=True) or {}
    action = data.get("action")

    try:
        if action == "pause":
            if engine.status != "running":
                raise RuntimeError("The timer is not running.")

            engine.pause()

            # Mark this as a manual pause, not a warning pause.
            controller.warning_pause = False
            controller.message = "Session paused manually."

        elif action == "resume":
            if engine.status != "paused":
                raise RuntimeError("The timer is not paused.")

            if controller.warning_used:
                raise RuntimeError(
                    "Return to the camera to resume after a warning."
                )

            engine.resume()
            controller.message = "Session resumed."

        elif action == "start_after_reset":
            controller.start_after_reset()

        elif action == "exit":
            if engine.status not in ("running", "paused"):
                raise RuntimeError("There is no active session to exit.")

            engine.early_exit()
            controller.message = "Session ended. Completed intervals saved."
            release_camera()

        else:
            return jsonify({"error": "Unknown action."}), 400

    except RuntimeError as error:
        return jsonify({"error": str(error)}), 400

    camera_error = None if action == "exit" else camera_error
    return jsonify(get_state())


if __name__ == "__main__":
    app.run(debug=True, threaded=True, use_reloader=False)