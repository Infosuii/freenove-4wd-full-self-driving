from gpiozero import DistanceSensor, PWMSoftwareFallback, DistanceSensorNoEcho
import warnings
import time

class FreshDistanceSensor(DistanceSensor):
    """Timestamp actual GPIOZero echo samples, including failed echoes.

    GPIOZero's smoothed distance can retain old values after no-echo failures.
    The guarded path reads this atomic sample instead of that cached median.
    """
    def __init__(self, *args, **kwargs):
        self.latest_echo = (None, 0.0)
        super().__init__(*args, **kwargs)

    def _read(self):
        value = super()._read()
        self.latest_echo = (value, time.monotonic())
        return value

class Ultrasonic:
    def __init__(self, trigger_pin: int = 27, echo_pin: int = 22, max_distance: float = 3.0, track_freshness=False):
        # Initialize the Ultrasonic class and set up the distance sensor.
        warnings.filterwarnings("ignore", category = DistanceSensorNoEcho)
        warnings.filterwarnings("ignore", category = PWMSoftwareFallback)  # Ignore PWM software fallback warnings
        self.trigger_pin = trigger_pin  # Set the trigger pin number
        self.echo_pin = echo_pin        # Set the echo pin number
        self.max_distance = max_distance  # Set the maximum distance
        sensor_type = FreshDistanceSensor if track_freshness else DistanceSensor
        self.sensor = sensor_type(echo=self.echo_pin, trigger=self.trigger_pin, max_distance=self.max_distance)

    def get_fresh_sample(self):
        value, timestamp = self.sensor.latest_echo
        return (None if value is None else round(value * self.max_distance * 100, 1), timestamp)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()

    def get_distance(self) -> float:
        """
        Get the distance measurement from the ultrasonic sensor.

        Returns:
        float: The distance measurement in centimeters, rounded to one decimal place.
        """
        try:
            distance = self.sensor.distance * 100  # Get the distance in centimeters
            return round(float(distance), 1)  # Return the distance rounded to one decimal place
        except RuntimeWarning as e:
            print(f"Warning: {e}")
            return None

    def close(self):
        # Close the distance sensor.
        self.sensor.close()  # Close the sensor to release resources

if __name__ == '__main__':
    # Initialize the Ultrasonic instance with default pin numbers and max distance
    with Ultrasonic() as ultrasonic:
        try:
            while True:
                distance = ultrasonic.get_distance()  # Get the distance measurement in centimeters
                if distance is not None:
                    print(f"Ultrasonic distance: {distance}cm")  # Print the distance measurement
                time.sleep(0.5)  # Wait for 0.5 seconds
        except KeyboardInterrupt:  # Handle keyboard interrupt (Ctrl+C)
            print("\nEnd of program")  # Print an end message
