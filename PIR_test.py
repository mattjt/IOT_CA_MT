from gpiozero import MotionSensor
from signal import pause

pir = MotionSensor(17)

print("Waiting for motion...")
pir.when_motion = lambda: print("MOTION DETECTED")
pir.when_no_motion = lambda: print("CLEAR")

pause()
