import cv2
from deepface import DeepFace
# Load OpenCV face detector
face_cascade = cv2.CascadeClassifier(
    cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
)
cap = cv2.VideoCapture(0)
while True:
    ret, frame = cap.read()
    if not ret:
        print("Could not access the webcam.")
        break
 # Detect faces
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    faces = face_cascade.detectMultiScale(
        gray,
        scaleFactor=1.1,
        minNeighbors=5,
        minSize=(50, 50)
    )
  # No face
    if len(faces) == 0:
        cv2.putText(
            frame,
            "No face detected",
            (20, 40),
            cv2.FONT_HERSHEY_SIMPLEX,
            1,
            (0, 0, 255),
            2
        )
    else:
 # Process every detected face
        for (x, y, w, h) in faces:
# Crop only this face
            face = frame[y:y+h, x:x+w]
            try:
                result = DeepFace.analyze(
                    face,
                    actions=["emotion"],
                    enforce_detection=False
                )
                emotion = result[0]["dominant_emotion"]
                confidence = result[0]["emotion"][emotion]
# Draw rectangle
                cv2.rectangle(
                    frame,
                    (x, y),
                    (x + w, y + h),
                    (0, 255, 0),
                    2
                )
 # Display emotion
                cv2.putText(
                    frame,
                    f"{emotion} ({confidence:.1f}%)",
                    (x, y - 10),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.7,
                    (0, 255, 0),
                    2
                )

            except Exception as e:
                print("Analysis error:", e)

    cv2.imshow("Real-Time Emotion Detection", frame)

    # Press Q to quit
    if cv2.waitKey(1) & 0xFF == ord("q"):
        break
cap.release()
cv2.destroyAllWindows()