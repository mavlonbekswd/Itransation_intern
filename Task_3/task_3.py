from flask import Flask, request
import math


def calculate_lcm(x, y):
    try:
        x = int(x)
        y = int(y)
        if x < 0 or y < 0:
            return "NaN"
        return str(math.lcm(x, y))
    except:
        return "NaN"


app = Flask(__name__)          # create the web server


@app.route("/mavlonbeksultanbekov3_gmail_com")            # when someone visits /lcm
def lcm_endpoint():            # run this function
    x = request.args.get("x")  # get x from the URL  (?x=4)
    y = request.args.get("y")  # get y from the URL  (?y=6)
    return calculate_lcm(x, y)  # return the answer


if __name__ == "__main__":
    app.run(debug=False)
