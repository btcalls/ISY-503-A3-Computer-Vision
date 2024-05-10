import argparse
import base64
import eventlet
import eventlet.wsgi
import h5py
import numpy as np
import os
import shutil
import socketio
import utils

from datetime import datetime
from flask import Flask
from keras import __version__ as keras_version
from keras.models import load_model
from io import BytesIO
from PIL import Image

# Server setup
sio = socketio.Server()
app = Flask(__name__)

model = None
prev_image_array = None

# Set min/max speed for our autonomous car
MAX_SPEED = 25
MIN_SPEED = 10

speed_limit = MAX_SPEED

# Registering event handler for the server


@sio.on("telemetry")
def telemetry(sid, data):
    if data:
        # The current steering angle of the car
        steering_angle = float(data["steering_angle"])
        # The current throttle of the car, how hard to push pedal
        throttle = float(data["throttle"])
        # The current speed of the car
        speed = float(data["speed"])
        # The current image from the center camera of the car
        data_image = Image.open(BytesIO(base64.b64decode(data["image"])))

        try:
            image = np.asarray(data_image)  # from PIL image to numpy array
            image = utils.preprocess(image)  # apply the preprocessing
            image = np.array([image])  # the model expects 4D array

            # Predict the steering angle for the image
            steering_angle = float(model.predict(image, batch_size=1))

            # Lower the throttle as the speed increases
            # If the speed is above the current speed limit, we are on a downhill.
            # Make sure we slow down first and then go back to the original max speed.
            global speed_limit

            if speed > speed_limit:
                speed_limit = MIN_SPEED
            else:
                speed_limit = MAX_SPEED

            throttle = 1.0 - steering_angle**2 - (speed/speed_limit)**2

            print("Steering angle: {}\nThrottle: {}\nSpeed:{}"
                  .format(steering_angle, throttle, speed))

            send_control(steering_angle, throttle)
        except Exception as e:
            print(e)

        # Save frame
        if args.image_folder != '':
            timestamp = datetime.utcnow().strftime("%Y_%m_%d_%H_%M_%S_%f")[:-3]
            image_filename = os.path.join(args.image_folder, timestamp)

            data_image.save("{}.jpg".format(image_filename))
    else:
        sio.emit("manual", data={}, skip_sid=True)


@sio.on("connect")
def connect(sid, environ):
    print(f"Connect: {sid}")
    send_control(0, 0)


def send_control(steering_angle, throttle):
    sio.emit(
        "steer",
        data={
            "steering_angle": steering_angle.__str__(),
            "throttle": throttle.__str__()
        },
        skip_sid=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Remote Driving")

    parser.add_argument(
        "model",
        type=str,
        help="Path to model h5 file. Model should be on the same path."
    )
    parser.add_argument(
        "image_folder",
        type=str,
        nargs="?",
        default="",
        help="Path to image folder. This is where the images from the run will be saved."
    )
    args = parser.parse_args()

    # Load model
    model = load_model(args.model)

    # Check that model Keras version is same as local Keras version
    f = h5py.File(args.model, mode='r')
    model_version = f.attrs.get('keras_version')
    keras_version = str(keras_version).encode('utf8')

    if model_version != keras_version:
        print(
            f"You are using Keras version {keras_version}, but the model was built using {model_version}")

    if args.image_folder != '':
        print("Creating image folder at {}".format(args.image_folder))

        if not os.path.exists(args.image_folder):
            os.makedirs(args.image_folder)
        else:
            shutil.rmtree(args.image_folder)
            os.makedirs(args.image_folder)

        print("Recording run...")
    else:
        print("Not recording run...")

    # Wrap Flask application with engineio's middleware
    app = socketio.Middleware(sio, app)

    # Deploy as an eventlet WSGI server
    eventlet.wsgi.server(eventlet.listen(("", 4567)), app)
