import cv2
#Default webcam open
cap = cv2.VideoCapture(0)
while True:
    ret, frame = cap.read()# Read one frame from the webcam
    if not ret:
        print("Could not access the webcam.")# if the camera did not return the frame ,stop
        break
    cv2.imshow("Webcam Test", frame) #Display the webcam frame 
    if cv2.waitKey(1) & 0xFF == ord("q"):
        break #Press 'q' to exit the loop
cap.release() #Release the webcam
cv2.destroyAllWindows() #Close all OpenCV windows