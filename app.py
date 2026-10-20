
import threading
import time

import cv2
from flask import Flask, Response, jsonify, render_template, request

from focussense.session_engine import SessionEngine
from focussense.accountability import AccountabilityController
from focussense.history import FocusHistory

app = Flask(__name__)

engine = None
controller = None
camera = None
camera_lock = threading.Lock()
session_lock = threading.RLock()

history = FocusHistory()
session_id = None

# Focus time is stored as seconds, including fractions of a second.
focused_seconds = 0.0
current_interval_seconds = 0.0
last_sync = time.monotonic()
last_tracking_active = False
last_remaining = 0.0
last_status = "idle"
last_completed_intervals = 0

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


def sync_focus_time():
    """Track elapsed focus time and persist the current session."""
    global focused_seconds, current_interval_seconds
    global last_sync, last_tracking_active, last_remaining
    global last_status, last_completed_intervals

    now = time.monotonic()

    with session_lock:
        if engine is None or session_id is None:
            last_sync = now
            return

        elapsed = max(0.0, now - last_sync)

        # Count only time spent actively focusing.
        if last_tracking_active:
            elapsed = min(elapsed, last_remaining)
            focused_seconds += elapsed
            current_interval_seconds += elapsed

        # A reset discards time from the current focus interval only.
        if (
            engine.status == "awaiting_restart"
            and last_status != "awaiting_restart"
        ):
            focused_seconds = max(
                0.0, focused_seconds - current_interval_seconds
            )
            current_interval_seconds = 0.0

        # A completed interval is preserved in the total.
        if engine.completed_focus_intervals > last_completed_intervals:
            current_interval_seconds = 0.0
            last_completed_intervals = engine.completed_focus_intervals

        last_sync = now
        last_status = engine.status

        last_tracking_active = (
            engine.status == "running" and engine.phase == "focus"
        )
        last_remaining = (
            engine.remaining_seconds if last_tracking_active else 0.0
        )

        history.update_session(
            session_id=session_id,
            focused_seconds=int(focused_seconds),
            status=engine.status,
            completed_focus_intervals=engine.completed_focus_intervals,
            violation_count=controller.violation_count if controller else 0,
        )


def tick_and_sync():
    """Account for elapsed time before and after advancing the timer."""
    if engine is None:
        return

    sync_focus_time()
    engine.tick()
    sync_focus_time()


def get_state():
    global camera_error, last_face_detected

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
            "camera_error": camera_error,
        }

    tick_and_sync()

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
    global session_id, focused_seconds, current_interval_seconds
    global last_sync, last_tracking_active, last_remaining
    global last_status, last_completed_intervals

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

    # Verify that the camera can open before starting the session.
    release_camera()
    camera_error = None
    last_face_detected = False

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

    with session_lock:
        engine = SessionEngine(
            focus_minutes=focus_minutes,
            break_minutes=break_minutes,
        )
        engine.start(cycles=cycles)
        controller = AccountabilityController(engine, grace_seconds=5)

        focused_seconds = 0.0
        current_interval_seconds = 0.0
        last_completed_intervals = 0
        last_status = engine.status
        last_tracking_active = True
        last_remaining = engine.remaining_seconds
        last_sync = time.monotonic()

        session_id = history.create_session(
            focus_minutes=focus_minutes,
            break_minutes=break_minutes,
            planned_cycles=cycles,
        )

        sync_focus_time()

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
            sync_focus_time()
            camera_error = "Camera connection lost. The timer has been paused."

            if engine and engine.status == "running":
                engine.pause()

            if controller:
                controller.warning_pause = False
                controller.message = camera_error

            sync_focus_time()
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
            sync_focus_time()
            engine.tick()
            controller.update(last_face_detected)
            sync_focus_time()

        for (x, y, width, height) in faces:
            cv2.rectangle(
                frame,
                (x, y),
                (x + width, y + height),
                (0, 200, 100),
                2,
            )

        label = "Face detected" if last_face_detected else "No face detected"

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
    global camera_error

    if engine is None or controller is None:
        return jsonify({"error": "Start a session first."}), 400

    data = request.get_json(silent=True) or {}
    action = data.get("action")

    try:
        with session_lock:
            # Record time before any action changes the timer state.
            sync_focus_time()

            if action == "pause":
                if engine.status != "running":
                    raise RuntimeError("The timer is not running.")

                engine.pause()
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
                controller.message = (
                    "Session ended. Completed intervals saved."
                )
                release_camera()

            else:
                return jsonify({"error": "Unknown action."}), 400

            sync_focus_time()

    except RuntimeError as error:
        return jsonify({"error": str(error)}), 400

    if action == "exit":
        camera_error = None

    return jsonify(get_state())


@app.route("/api/achievements", methods=["GET"])
def achievements():
    sync_focus_time()

    return jsonify({
        "daily": history.daily_summary(),
        "recent_days": history.recent_days(7),
        "daily_goal_minutes": history.get_daily_goal(),
    })


@app.route("/api/daily-goal", methods=["POST"])
def update_daily_goal():
    data = request.get_json(silent=True) or {}
    minutes = data.get("minutes")

    try:
        if isinstance(minutes, str):
            minutes = int(minutes)

        history.set_daily_goal(minutes)

    except (ValueError, TypeError) as error:
        return jsonify({"error": str(error)}), 400

    return jsonify({
        "message": "Daily focus goal updated.",
        "daily_goal_minutes": history.get_daily_goal(),
        "daily": history.daily_summary(),
    })


if __name__ == "__main__":
    app.run(debug=True, threaded=True, use_reloader=False)
