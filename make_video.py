import cv2
import numpy as np

# Create a blank 10-second video simulation at 30 FPS
fourcc = cv2.VideoWriter_fourcc(*'mp4v')
out = cv2.VideoWriter('store.mp4', fourcc, 30.0, (640, 480))

print("Generating simulated local video track asset...")
for i in range(300):
    # Creating simulated background noise matrices
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    # Drawing bounding layers to emulate store aisles
    cv2.putText(frame, f"Simulated Store Feed - Frame {i}", (50, 240), 
                cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
    out.write(frame)

out.release()
print("SUCCESS: 'store.mp4' successfully generated inside your project root folder!")